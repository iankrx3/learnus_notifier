"""
LearnUs (Yonsei) 크롤러 - 순수 크롤링 로직 모듈

기능:
- Yonsei Portal SSO 로그인
- 수강 강좌 목록 수집
- 강좌별 공지사항 페이지 이동
- 공지사항 목록 수집
- 필요 시 공지 상세 내용 수집

CLI로 직접 실행:
    python learnus_crawler.py

FastAPI에서:
    from learnus_crawler import run_crawl
"""

import json
import os
import re
import time
from getpass import getpass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


# ============================================================
# 환경 설정
# ============================================================

load_dotenv(
    dotenv_path=Path(__file__).resolve().parent / ".env"
)

LEARNUS_LOGIN_URL = "https://ys.learnus.org/login/index.php"
LEARNUS_HOME_URL = "https://ys.learnus.org/"
SSO_HOST_HINT = "infra.yonsei.ac.kr"


# ============================================================
# Selector
# ============================================================

SELECTORS = {
    # LearnUs 로그인 페이지
    "portal_login_button": (
        By.CSS_SELECTOR,
        "a.btn-sso"
    ),

    # Yonsei SSO
    "sso_id_input": (
        By.ID,
        "loginId"
    ),

    "sso_pw_input": (
        By.ID,
        "loginPasswd"
    ),

    "sso_login_button": (
        By.ID,
        "loginBtn"
    ),
}


# ============================================================
# 강좌 미개설 판단용 문자열
# ============================================================

COURSE_NOT_SET_MARKERS = [
    "Course has not been set",
    "강좌가 개설되지",
    "아직 개설되지",
    "가상 강의실에 입장하지 않아",
]


# ============================================================
# 공지사항 링크 텍스트
# ============================================================

ANNOUNCEMENT_LINK_MARKERS = [
    "Class Announcements",
    "공지사항",
    "과목공지",
]


# ============================================================
# 디버깅
# ============================================================

def _save_debug_snapshot(
    driver: webdriver.Chrome,
    label: str
):
    """
    실패/애매한 지점의 스크린샷과 HTML 저장.
    """

    try:
        driver.save_screenshot(
            f"debug_{label}.png"
        )

        with open(
            f"debug_{label}.html",
            "w",
            encoding="utf-8"
        ) as f:
            f.write(driver.page_source)

        print(
            f"[DEBUG] 저장됨: "
            f"debug_{label}.png / "
            f"debug_{label}.html"
        )

        print(
            f"[DEBUG] 현재 URL: "
            f"{driver.current_url}"
        )

    except Exception as e:
        print(
            f"[DEBUG] 스냅샷 저장 실패: {e}"
        )


# ============================================================
# Selenium Driver
# ============================================================

def create_driver(
    headless: bool = True
) -> webdriver.Chrome:

    options = Options()

    if headless:
        options.add_argument("--headless=new")

    options.add_argument(
        "--window-size=1280,960"
    )

    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")

    return webdriver.Chrome(
        options=options
    )


# ============================================================
# 로그인
# ============================================================

def login(
    driver: webdriver.Chrome,
    username: str,
    password: str,
    timeout: int = 15
):

    wait = WebDriverWait(
        driver,
        timeout
    )

    # --------------------------------------------------------
    # 1. LearnUs 로그인 페이지
    # --------------------------------------------------------

    driver.get(
        LEARNUS_LOGIN_URL
    )

    # --------------------------------------------------------
    # 2. Portal Login 클릭
    # --------------------------------------------------------

    try:

        portal_login_btn = wait.until(
            EC.element_to_be_clickable(
                SELECTORS[
                    "portal_login_button"
                ]
            )
        )

        portal_login_btn.click()

    except Exception:

        _save_debug_snapshot(
            driver,
            "portal_login_button_not_found"
        )

        raise

    # --------------------------------------------------------
    # 3. SSO 페이지 대기
    # --------------------------------------------------------

    try:

        wait.until(
            lambda d:
            SSO_HOST_HINT in d.current_url
            or len(d.window_handles) > 1
        )

        if len(driver.window_handles) > 1:
            driver.switch_to.window(
                driver.window_handles[-1]
            )

        wait.until(
            EC.url_contains(
                SSO_HOST_HINT
            )
        )

    except Exception:

        _save_debug_snapshot(
            driver,
            "sso_redirect_failed"
        )

        raise

    # --------------------------------------------------------
    # 4. 아이디 / 비밀번호
    # --------------------------------------------------------

    try:

        id_input = wait.until(
            EC.presence_of_element_located(
                SELECTORS[
                    "sso_id_input"
                ]
            )
        )

        pw_input = driver.find_element(
            *SELECTORS[
                "sso_pw_input"
            ]
        )

        id_input.clear()
        id_input.send_keys(username)

        pw_input.clear()
        pw_input.send_keys(password)

    except Exception:

        _save_debug_snapshot(
            driver,
            "sso_credentials_failed"
        )

        raise

    # --------------------------------------------------------
    # 5. 로그인 버튼
    # --------------------------------------------------------

    login_btn = driver.find_element(
        *SELECTORS[
            "sso_login_button"
        ]
    )

    login_btn.click()

    # --------------------------------------------------------
    # 6. LearnUs 리다이렉트
    # --------------------------------------------------------

    if len(driver.window_handles) > 1:

        # LearnUs 원래 탭으로 돌아감
        driver.switch_to.window(
            driver.window_handles[0]
        )

    wait.until(
        EC.url_contains(
            "learnus.org"
        )
    )

    time.sleep(1.5)

    # --------------------------------------------------------
    # 로그인 실패 확인
    # --------------------------------------------------------

    if "login/index.php" in driver.current_url:

        raise RuntimeError(
            "로그인 실패: "
            "SSO 이후에도 로그인 페이지에 "
            "머물러 있습니다."
        )


# ============================================================
# 강좌명 파싱
# ============================================================

_TITLE_LINE_RE = re.compile(
    r"^(?P<name>.+?)\s*"
    r"\((?P<code>"
    r"[A-Z]{2,5}\d{3,4}\.\d{2}-\d{2}"
    r")\)"
)


_CODE_PROF_LINE_RE = re.compile(
    r"^(?P<code>"
    r"[A-Z]{2,5}\d{3,4}\.\d{2}-\d{2}"
    r")\s*/\s*(?P<prof>.+)$"
)


def parse_course_text(
    raw_text: str
):
    """
    강좌 링크 텍스트에서

    course_code
    name
    professor

    추출
    """

    lines = [
        line.strip()
        for line in raw_text.splitlines()
        if line.strip()
    ]

    course_code = None
    name = None
    professor = None

    for line in lines:

        # --------------------------------------------
        # 강좌명 + 코드
        # --------------------------------------------

        title_match = (
            _TITLE_LINE_RE.match(line)
        )

        if title_match and name is None:

            name = (
                title_match
                .group("name")
                .strip()
            )

            course_code = (
                course_code
                or title_match.group("code")
            )

            continue

        # --------------------------------------------
        # 코드 / 교수
        # --------------------------------------------

        code_prof_match = (
            _CODE_PROF_LINE_RE.match(line)
        )

        if code_prof_match:

            course_code = (
                course_code
                or code_prof_match.group("code")
            )

            professor = (
                code_prof_match
                .group("prof")
                .strip()
            )

    # --------------------------------------------
    # 코드 패턴이 없는 비교과 강좌
    # --------------------------------------------

    if name is None:

        name = (
            " ".join(lines)
            if lines
            else raw_text.strip()
        )

    return (
        course_code,
        name,
        professor
    )


# ============================================================
# 강좌 목록
# ============================================================

def get_course_links(
    driver: webdriver.Chrome,
    timeout: int = 15
) -> list[dict]:

    wait = WebDriverWait(
        driver,
        timeout
    )

    driver.get(
        LEARNUS_HOME_URL
    )

    wait.until(
        EC.presence_of_element_located(
            (By.TAG_NAME, "body")
        )
    )

    courses = []
    seen = set()

    # LearnUs 강좌 링크
    elements = driver.find_elements(
        By.CSS_SELECTOR,
        "a[href*='course/view.php']"
    )

    for el in elements:

        raw_text = el.text.strip()
        link = el.get_attribute("href")

        if not raw_text:
            continue

        if not link:
            continue

        if link in seen:
            continue

        seen.add(link)

        course_code, name, professor = (
            parse_course_text(
                raw_text
            )
        )

        courses.append(
            {
                "link": link,
                "course_code": course_code,
                "name": name,
                "professors": professor,
            }
        )

    return courses


# ============================================================
# 공지사항 페이지 열기
# ============================================================

def open_course_announcements(
    driver: webdriver.Chrome,
    course_url: str,
    timeout: int = 15
) -> str:

    wait = WebDriverWait(
        driver,
        timeout
    )

    # --------------------------------------------------------
    # 강좌 페이지
    # --------------------------------------------------------

    driver.get(
        course_url
    )

    wait.until(
        EC.presence_of_element_located(
            (By.TAG_NAME, "body")
        )
    )

    # --------------------------------------------------------
    # 강좌 미개설 여부
    # --------------------------------------------------------

    page_text = driver.find_element(
        By.TAG_NAME,
        "body"
    ).text

    if any(
        marker in page_text
        for marker in COURSE_NOT_SET_MARKERS
    ):
        return "not_set"

    # --------------------------------------------------------
    # 공지사항 링크 찾기
    #
    # 영어:
    #   Class Announcements
    #
    # 한국어:
    #   공지사항
    #   과목공지
    #
    # 반드시 <a> 태그로 제한
    # --------------------------------------------------------

    announcement_xpath = (
        "//a["
        "contains(normalize-space(.), "
        "'Class Announcements')"
        " or "
        "contains(normalize-space(.), "
        "'공지사항')"
        " or "
        "contains(normalize-space(.), "
        "'과목공지')"
        "]"
    )

    try:

        link = wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    announcement_xpath
                )
            )
        )

        # ----------------------------------------------------
        # 디버깅 정보
        # ----------------------------------------------------

        print(
            "찾은 요소:",
            link.tag_name
        )

        print(
            "텍스트:",
            repr(link.text)
        )

        href = link.get_attribute(
            "href"
        )

        print(
            "href:",
            href
        )

        # ----------------------------------------------------
        # href가 있으면 직접 이동
        #
        # Selenium click보다 안정적
        # ----------------------------------------------------

        if href:

            driver.get(href)

        else:

            # href가 없는 경우에만 click
            driver.execute_script(
                """
                arguments[0]
                .scrollIntoView({
                    block: 'center'
                });
                """,
                link
            )

            time.sleep(0.5)

            driver.execute_script(
                "arguments[0].click();",
                link
            )

        # ----------------------------------------------------
        # 페이지 로딩 대기
        # ----------------------------------------------------

        wait.until(
            EC.presence_of_element_located(
                (By.TAG_NAME, "body")
            )
        )

        time.sleep(0.5)

        print(
            "공지사항 페이지 URL:",
            driver.current_url
        )

        return "ok"

    except Exception as e:

        print(
            "공지사항 이동 실패"
        )

        print(
            "에러 타입:",
            type(e).__name__
        )

        print(
            "에러 내용:",
            str(e)
        )

        _save_debug_snapshot(
            driver,
            "announcements_link_failed"
        )

        return "not_found"


# ============================================================
# 공지 상세 페이지
# ============================================================

def scrape_announcement_detail(
    driver: webdriver.Chrome,
    timeout: int = 15
) -> dict:

    wait = WebDriverWait(
        driver,
        timeout
    )

    wait.until(
        EC.presence_of_element_located(
            (By.TAG_NAME, "body")
        )
    )

    detail = {
        "writer": None,
        "date": None,
        "hit": None,
        "content": None,
        "url": driver.current_url,
    }

    # --------------------------------------------------------
    # 본문 컨테이너 후보
    # --------------------------------------------------------

    container_selectors = [
        ".ubboard_view",
        ".ubboard",
    ]

    full_text = None

    for selector in container_selectors:

        try:

            container = driver.find_element(
                By.CSS_SELECTOR,
                selector
            )

            full_text = container.text

            break

        except Exception:
            continue

    # 컨테이너를 못 찾으면 body 전체 사용
    if full_text is None:

        full_text = driver.find_element(
            By.TAG_NAME,
            "body"
        ).text

    # --------------------------------------------------------
    # 작성자 / 작성일 / 조회수
    # --------------------------------------------------------

    for line in full_text.splitlines():

        line = line.strip()

        if not line:
            continue

        low = line.lower()

        # 작성자
        if (
            low.startswith("writer")
            or line.startswith("작성자")
        ):

            detail["writer"] = (
                line.split(
                    ":",
                    1
                )[-1].strip()
            )

        # 작성일
        elif (
            low.startswith("wrote on")
            or line.startswith("작성일")
        ):

            detail["date"] = (
                line.split(
                    ":",
                    1
                )[-1].strip()
            )

        # 조회수
        elif (
            low.startswith("hit")
            or line.startswith("조회")
        ):

            detail["hit"] = (
                line.split(
                    ":",
                    1
                )[-1].strip()
            )

    # --------------------------------------------------------
    # 본문
    # --------------------------------------------------------

    content_selectors = [
        ".ubboard_view .content",
        ".ubboard_content",
        ".view_content",
    ]

    for selector in content_selectors:

        try:

            el = driver.find_element(
                By.CSS_SELECTOR,
                selector
            )

            if el.text.strip():

                detail["content"] = (
                    el.text.strip()
                )

                break

        except Exception:
            continue

    # --------------------------------------------------------
    # 본문 selector 실패
    # --------------------------------------------------------

    if not detail["content"]:

        detail["content"] = (
            full_text
        )

        _save_debug_snapshot(
            driver,
            "announcement_detail_fallback"
        )

    return detail


# ============================================================
# 공지사항 목록
# ============================================================

def scrape_announcement_list(
    driver: webdriver.Chrome,
    timeout: int = 15,
    max_pages: Optional[int] = 1,
    fetch_detail: bool = True,
) -> list[dict]:

    wait = WebDriverWait(
        driver,
        timeout
    )

    # --------------------------------------------------------
    # 게시판 페이지 로딩
    #
    # 공지가 없어도 table은 존재한다고 가정
    # --------------------------------------------------------

    wait.until(
        EC.presence_of_element_located(
            (By.TAG_NAME, "table")
        )
    )

    all_posts = []

    page_num = 1

    # ========================================================
    # 페이지 반복
    # ========================================================

    while True:

        # ----------------------------------------------------
        # 게시글 행
        # ----------------------------------------------------

        rows = driver.find_elements(
            By.CSS_SELECTOR,
            "table.ubboard_table tbody tr"
        )

        # fallback
        if not rows:

            rows = driver.find_elements(
                By.XPATH,
                "//table//tbody/tr"
            )

        # ----------------------------------------------------
        # 게시글 추출
        # ----------------------------------------------------

        for row in rows:

            cells = row.find_elements(
                By.TAG_NAME,
                "td"
            )

            # -----------------------------------------------
            # "No registered post." 같은 행
            # -----------------------------------------------

            if len(cells) < 5:
                continue

            try:

                link_el = cells[1].find_element(
                    By.TAG_NAME,
                    "a"
                )

                title = (
                    link_el.text.strip()
                )

                href = (
                    link_el.get_attribute(
                        "href"
                    )
                )

            except Exception:

                title = (
                    cells[1].text.strip()
                )

                href = None

            if not title:
                continue

            all_posts.append(
                {
                    "number": (
                        cells[0]
                        .text
                        .strip()
                    ),

                    "title": title,

                    "link": href,

                    "writer": (
                        cells[2]
                        .text
                        .strip()
                    ),

                    "date": (
                        cells[3]
                        .text
                        .strip()
                    ),

                    "hit": (
                        cells[4]
                        .text
                        .strip()
                    ),
                }
            )

        # ----------------------------------------------------
        # 전체 페이지 수
        # ----------------------------------------------------

        total_pages = 1

        try:

            page_info_text = (
                driver.find_element(
                    By.XPATH,
                    "//*[contains("
                    "text(), "
                    "'Total Page'"
                    ")]"
                ).text
            )

            total_pages = int(
                page_info_text
                .split("/")[-1]
                .strip()
            )

        except Exception:
            pass

        # max_pages 제한
        if max_pages:
            total_pages = min(
                total_pages,
                max_pages
            )

        # ----------------------------------------------------
        # 마지막 페이지
        # ----------------------------------------------------

        if page_num >= total_pages:
            break

        page_num += 1

        # ----------------------------------------------------
        # 다음 페이지
        # ----------------------------------------------------

        try:

            next_page_btn = driver.find_element(
                By.XPATH,
                f"//*["
                f"self::a or "
                f"self::button or "
                f"self::span"
                f"]["
                f"normalize-space(.)="
                f"'{page_num}'"
                f"]"
            )

            next_page_btn.click()

            wait.until(
                EC.presence_of_element_located(
                    (By.TAG_NAME, "table")
                )
            )

            time.sleep(0.5)

        except Exception:

            break

    # ========================================================
    # 상세 페이지
    # ========================================================

    if fetch_detail:

        for post in all_posts:

            if not post.get("link"):
                continue

            try:

                driver.get(
                    post["link"]
                )

                detail = (
                    scrape_announcement_detail(
                        driver,
                        timeout=timeout
                    )
                )

                post.update(
                    detail
                )

            except Exception:

                _save_debug_snapshot(
                    driver,
                    "announcement_detail_error_"
                    + str(
                        post.get(
                            "number",
                            "unknown"
                        )
                    )
                )

    return all_posts


# ============================================================
# 모든 강좌 공지사항 수집
# ============================================================

def collect_all_course_announcements(
    driver: webdriver.Chrome,
    courses: list[dict],
    timeout: int = 15,
    max_pages: Optional[int] = 1,
    fetch_detail: bool = True,
) -> list[dict]:

    results = []

    # ========================================================
    # 강좌 반복
    # ========================================================

    for course in courses:

        print(
            "\n========================================"
        )

        print(
            "강좌:",
            course.get("name")
        )

        print(
            "코드:",
            course.get("course_code")
        )

        print(
            "========================================"
        )

        base = {
            "course_code": (
                course.get(
                    "course_code"
                )
            ),

            "name": (
                course.get(
                    "name"
                )
            ),

            "professors": (
                course.get(
                    "professors"
                )
            ),
        }

        link = course["link"]

        # ----------------------------------------------------
        # 공지사항 페이지
        # ----------------------------------------------------

        status = open_course_announcements(
            driver,
            link,
            timeout=timeout
        )

        # ----------------------------------------------------
        # 강좌 미개설
        # ----------------------------------------------------

        if status == "not_set":

            results.append(
                {
                    **base,
                    "status": "not set",
                    "announcements": [],
                }
            )

            continue

        # ----------------------------------------------------
        # 공지 링크를 못 찾음
        # ----------------------------------------------------

        if status == "not_found":

            results.append(
                {
                    **base,
                    "status": "not found",
                    "announcements": [],
                }
            )

            continue

        # ----------------------------------------------------
        # 공지 목록
        # ----------------------------------------------------

        try:

            posts = scrape_announcement_list(
                driver,
                timeout=timeout,
                max_pages=max_pages,
                fetch_detail=fetch_detail,
            )

        except Exception as e:

            print(
                "공지 목록 크롤링 오류:",
                type(e).__name__,
                str(e)
            )

            _save_debug_snapshot(
                driver,
                "announcement_list_error"
            )

            posts = []

        # ----------------------------------------------------
        # API 반환 형태
        # ----------------------------------------------------

        announcements = []

        for post in posts:

            announcements.append(
                {
                    "title": post.get(
                        "title"
                    ),

                    "published_at": post.get(
                        "date"
                    ),

                    "content": (
                        post.get(
                            "content"
                        )
                        if fetch_detail
                        else ""
                    ),
                }
            )

        results.append(
            {
                **base,
                "status": "ok",
                "announcements": announcements,
            }
        )

    return results


# ============================================================
# 전체 크롤링
# ============================================================

def run_crawl(
    username: Optional[str] = None,
    password: Optional[str] = None,
    headless: bool = True,
    max_pages: Optional[int] = 1,
    fetch_detail: bool = True,
) -> dict:

    """
    전체 파이프라인

    1. 로그인
    2. 강좌 목록
    3. 강좌별 공지사항
    4. 공지 상세

    반환:
    {
        "courses": [...]
    }
    """

    # --------------------------------------------------------
    # 인증정보
    # --------------------------------------------------------

    username = (
        username
        or os.environ.get(
            "YONSEI_ID"
        )
    )

    password = (
        password
        or os.environ.get(
            "YONSEI_PW"
        )
    )

    if not username or not password:

        raise ValueError(
            "아이디/비밀번호가 필요합니다.\n"
            "환경변수 YONSEI_ID / YONSEI_PW "
            "를 설정하세요."
        )

    # --------------------------------------------------------
    # Driver
    # --------------------------------------------------------

    driver = create_driver(
        headless=headless
    )

    try:

        # ----------------------------------------------------
        # 로그인
        # ----------------------------------------------------

        print("로그인 중...")

        login(
            driver,
            username,
            password
        )

        print("로그인 성공")

        # ----------------------------------------------------
        # 강좌 목록
        # ----------------------------------------------------

        print(
            "강좌 목록 수집 중..."
        )

        courses = get_course_links(
            driver
        )

        print(
            f"강좌 {len(courses)}개 발견"
        )

        # ----------------------------------------------------
        # 공지사항
        # ----------------------------------------------------

        course_results = (
            collect_all_course_announcements(
                driver,
                courses,
                max_pages=max_pages,
                fetch_detail=fetch_detail,
            )
        )

        # ----------------------------------------------------
        # 결과
        # ----------------------------------------------------

        return {
            "courses": course_results
        }

    finally:

        driver.quit()


# ============================================================
# CLI
# ============================================================

def _cli_main():

    username = (
        os.environ.get(
            "YONSEI_ID"
        )
        or input(
            "Yonsei Portal ID: "
        ).strip()
    )

    password = (
        os.environ.get(
            "YONSEI_PW"
        )
        or getpass(
            "Yonsei Portal Password: "
        )
    )

    result = run_crawl(
        username=username,
        password=password,
        headless=False,
        max_pages=1,
        fetch_detail=True,
    )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2
        )
    )


# ============================================================
# 실행
# ============================================================

if __name__ == "__main__":
    _cli_main()