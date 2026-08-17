"""
LearnUs 공지사항 새 글 감지 & 텔레그램 알림

동작 방식:
1. learnus_crawler.run_crawl() 으로 전체 강좌의 공지사항을 수집
2. data/seen_announcements.json 에 저장된 "이전에 이미 알림 보낸 공지" 목록과 비교
3. 새로 생긴 공지만 텔레그램으로 전송
4. 최신 상태를 다시 data/seen_announcements.json 에 저장

GitHub Actions에서 30분마다 실행되는 것을 전제로 작성됨.
(로컬에서 테스트하려면 .env 에 YONSEI_ID / YONSEI_PW / TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 설정)
"""

import hashlib
import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

from learnus_crawler import run_crawl

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

STATE_PATH = Path(__file__).resolve().parent / "data" / "seen_announcements.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# 상세 내용(본문)까지 가져올지 여부 - 강좌 수가 많으면 느려질 수 있어 env로 조절 가능
FETCH_DETAIL = os.environ.get("FETCH_DETAIL", "true").lower() == "true"
MAX_PAGES = int(os.environ.get("MAX_PAGES", "1"))


# ============================================================
# 상태 저장/로드
# ============================================================

def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        # 파일이 깨져있으면 처음부터 다시 시작 (전부 새 글로 취급하지 않도록
        # 최초 1회는 알림이 몰릴 수 있음 - 아래 FIRST_RUN 처리 참고)
        return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _announcement_key(course_code: str, ann: dict) -> str:
    raw = f"{course_code}::{ann.get('title')}::{ann.get('published_at')}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


# ============================================================
# 텔레그램
# ============================================================

def _send_telegram(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[WARN] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 미설정 - 알림 스킵")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        resp = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=15,
        )

        if resp.status_code != 200:
            print("[ERROR] 텔레그램 전송 실패:", resp.status_code, resp.text)

    except Exception as e:
        print("[ERROR] 텔레그램 전송 중 예외:", type(e).__name__, str(e))


def _format_message(course_name: str, ann: dict) -> str:
    title = ann.get("title") or "(제목 없음)"
    date = ann.get("published_at") or ""
    content = (ann.get("content") or "").strip()

    if len(content) > 300:
        content = content[:300] + "..."

    lines = [
        "\U0001F4E2 LearnUs 새 공지",
        f"강좌: {course_name}",
        f"제목: {title}",
    ]

    if date:
        lines.append(f"작성일: {date}")

    if content:
        lines.append("")
        lines.append(content)

    return "\n".join(lines)


# ============================================================
# 메인
# ============================================================

def main() -> None:
    state = _load_state()
    is_first_run = len(state) == 0

    print("LearnUs 크롤링 시작...")

    result = run_crawl(
        headless=True,
        max_pages=MAX_PAGES,
        fetch_detail=FETCH_DETAIL,
    )

    new_count = 0

    for course in result.get("courses", []):

        course_code = course.get("course_code") or course.get("name") or "unknown"
        course_name = course.get("name") or course_code

        seen_keys = set(state.get(course_code, []))
        current_keys = set()

        for ann in course.get("announcements", []):

            key = _announcement_key(course_code, ann)
            current_keys.add(key)

            if key not in seen_keys:
                new_count += 1
                print(f"[NEW] {course_name} - {ann.get('title')}")

                # 최초 실행(상태 파일이 없던 첫 회차)에는 기존 공지 전체가
                # "새 글"로 잡혀 알림이 쏟아지므로 전송은 건너뛰고
                # 상태만 기록해서 다음 회차부터 정상적으로 diff를 잡는다.
                if not is_first_run:
                    _send_telegram(_format_message(course_name, ann))

        state[course_code] = list(seen_keys | current_keys)

    _save_state(state)

    if is_first_run:
        print(f"최초 실행: 공지 {new_count}건을 baseline으로 저장 (알림 없음).")
    else:
        print(f"완료. 새 공지 {new_count}건 발견, 텔레그램 전송 시도.")


if __name__ == "__main__":
    main()
