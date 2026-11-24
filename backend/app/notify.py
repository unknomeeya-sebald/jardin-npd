"""지연 알림을 Slack 채널로 보낸다. 표준 라이브러리(urllib)만 사용.

설정(backend/.env) — 둘 중 하나:
- SLACK_WEBHOOK_URL : Incoming Webhook 주소(채널이 웹훅에 묶여 있음)
- SLACK_BOT_TOKEN   : xoxb- 봇 토큰 + SLACK_CHANNEL(기본 C0C093UBJ49). 봇을 채널에 초대해야 함
그 밖: FRONTEND_URL(메시지 속 링크, 기본 http://localhost:3000),
       SLACK_CHECK_INTERVAL_MIN(자동 점검 주기, 기본 60분, 0이면 끔)

보내는 경우
1. 빨강 Task: 예정 종료일 지남·미완료, 또는 지연 완료. Task마다 한 번만(npd_alert_log로 중복 방지)
2. 지연 흡수 결과 출시일 영향이 생길 때. 같은 (제품·Task·지연일수·출시일) 조합은 한 번만
보내기에 실패하면 기록하지 않으므로 다음 점검 때 다시 보낸다.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime

from sqlalchemy import DateTime, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, SessionLocal

log = logging.getLogger("npd.notify")

WEBHOOK = os.getenv("SLACK_WEBHOOK_URL", "").strip()
BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "").strip()
CHANNEL = os.getenv("SLACK_CHANNEL", "C0C093UBJ49").strip()
FRONTEND = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")
INTERVAL_MIN = int(os.getenv("SLACK_CHECK_INTERVAL_MIN", "60"))


class AlertLog(Base):
    __tablename__ = "npd_alert_log"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    message: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def configured() -> str | None:
    """'webhook' | 'bot' | None"""
    if WEBHOOK:
        return "webhook"
    if BOT_TOKEN and CHANNEL:
        return "bot"
    return None


def status() -> dict:
    mode = configured()
    return {"configured": mode is not None, "mode": mode, "channel": CHANNEL if mode == "bot" else None,
            "interval_min": INTERVAL_MIN}


# ---------- 보내기 ----------
def post(text: str) -> None:
    """Slack으로 한 건 보낸다. 실패하면 예외."""
    mode = configured()
    if mode is None:
        raise RuntimeError("Slack 설정 없음: backend/.env에 SLACK_WEBHOOK_URL 또는 SLACK_BOT_TOKEN을 넣으세요")
    if mode == "webhook":
        req = urllib.request.Request(WEBHOOK, data=json.dumps({"text": text}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                body = r.read().decode()
        except urllib.error.HTTPError as e:
            reason = e.read().decode(errors="replace").strip()
            hint = {"no_team": "워크스페이스 ID가 틀림 — 주소의 대·소문자가 바뀌었는지 확인",
                    "no_service": "웹훅이 삭제됐거나 주소가 틀림",
                    "invalid_token": "주소 마지막 부분(비밀 키)이 틀림 — Slack에서 Copy 버튼으로 다시 복사",
                    "channel_not_found": "웹훅에 연결된 채널이 없어짐",
                    "channel_is_archived": "채널이 보관 처리됨"}.get(reason, "")
            raise RuntimeError(f"Slack 웹훅 HTTP {e.code} {reason}" + (f" ({hint})" if hint else "")) from e
        if body.strip() != "ok":
            raise RuntimeError(f"Slack 웹훅 오류: {body[:200]}")
        return
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=json.dumps({"channel": CHANNEL, "text": text, "unfurl_links": False}).encode(),
        headers={"Content-Type": "application/json; charset=utf-8", "Authorization": f"Bearer {BOT_TOKEN}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        res = json.loads(r.read())
    if not res.get("ok"):
        hint = {"not_in_channel": " (봇을 채널에 초대하세요: /invite @봇이름)",
                "channel_not_found": " (SLACK_CHANNEL 확인, 비공개 채널이면 봇 초대 필요)",
                "invalid_auth": " (SLACK_BOT_TOKEN 확인)"}.get(res.get("error", ""), "")
        raise RuntimeError(f"Slack API 오류: {res.get('error')}{hint}")


class SlackUserNotFound(RuntimeError):
    """그 이메일을 쓰는 Slack 사용자가 없다."""


def _slack_api(method: str, payload: dict | None = None, query: dict | None = None) -> dict:
    url = f"https://slack.com/api/{method}" + (f"?{urllib.parse.urlencode(query)}" if query else "")
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json; charset=utf-8", "Authorization": f"Bearer {BOT_TOKEN}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def dm_by_email(email: str, text: str) -> None:
    """이메일로 Slack 사용자를 찾아 개인 메시지(DM)를 보낸다. 실패하면 예외.

    봇 권한 users:read.email(사용자 찾기)·chat:write(보내기)가 필요하다.
    """
    if not BOT_TOKEN:
        raise RuntimeError("Slack 봇 토큰 없음: SLACK_BOT_TOKEN이 필요합니다")
    res = _slack_api("users.lookupByEmail", query={"email": email})
    if not res.get("ok"):
        err = res.get("error")
        if err == "users_not_found":
            raise SlackUserNotFound(email)
        hint = " (Slack 앱에 users:read.email 권한을 추가하고 다시 설치하세요)" if err == "missing_scope" else ""
        raise RuntimeError(f"Slack 사용자 찾기 오류: {err}{hint}")
    res = _slack_api("chat.postMessage", {"channel": res["user"]["id"], "text": text, "unfurl_links": False})
    if not res.get("ok"):
        raise RuntimeError(f"Slack DM 오류: {res.get('error')}")


_lock = threading.Lock()
_inflight: set[str] = set()


def _send_and_record(keys: list[str], text: str) -> None:
    try:
        post(text)
    except Exception as e:  # noqa: BLE001
        log.warning("Slack 알림 실패(다음 점검 때 다시 보냄): %s", e)
        return
    finally:
        with _lock:
            _inflight.difference_update(keys)
    with SessionLocal() as db:
        for k in keys:
            if db.get(AlertLog, k) is None:
                db.add(AlertLog(key=k, message=text[:2000]))
        db.commit()


def _dispatch(db: Session, items: list[tuple[str, str]], header: str, footer: str = "") -> int:
    """items = [(중복키, 한 줄)]. 아직 안 보낸 것만 모아 백그라운드로 한 메시지 보낸다. 보낸 줄 수 반환."""
    if configured() is None or not items:
        return 0
    keys = [k for k, _ in items]
    sent = set(db.scalars(select(AlertLog.key).where(AlertLog.key.in_(keys))))
    with _lock:
        new = [(k, line) for k, line in items if k not in sent and k not in _inflight]
        _inflight.update(k for k, _ in new)
    if not new:
        return 0
    text = "\n".join([header, *(line for _, line in new)] + ([footer] if footer else []))
    threading.Thread(target=_send_and_record, args=([k for k, _ in new], text), daemon=True).start()
    return len(new)


# ---------- 알림 종류 ----------
def notify_red(db: Session, product, rows: list[dict]) -> int:
    """rows = 신호등 판정이 붙은 schedule 행(dict). 새 빨강만 보낸다."""
    items = []
    for r in rows:
        if r.get("signal") != "빨강":
            continue
        kind = "late" if r.get("actual_end") else "overdue"
        key = f"red:{product.id}:{r['no']}:{kind}:{r.get('end')}"
        items.append((key, f"• Task {r['no']} {r['name']} — 예정 종료 {r.get('end')} · {r.get('reason')}"))
    return _dispatch(
        db, items,
        header=f":red_circle: *지연 알림* {product.name} (출시 {product.launch_date.isoformat()}) 빨강 Task",
        footer=f"<{FRONTEND}/signals|신호등 현황 보기>")


def notify_absorb(db: Session, product, result: dict) -> int:
    if not result.get("alert"):
        return 0
    key = f"absorb:{product.id}:{result['delayed_task']}:{result['delay']}:{result['launch']}"
    line = (f"• {result['alert'].removeprefix('지연 알림:').strip()}\n"
            f"• 출시일 {result['launch']} → {result['impacted_launch']} ({result['launch_impact_days']}영업일 영향)")
    return _dispatch(db, [(key, line)],
                     header=f":warning: *지연 알림* {product.name} 지연 흡수 한도 초과",
                     footer=f"<{FRONTEND}/absorb|지연 흡수 보기>")


# ---------- 주기 점검 ----------
def start_scheduler(check_all) -> threading.Event | None:
    """check_all(as_of) 를 INTERVAL_MIN 분마다 부른다. 멈출 때 반환한 Event를 set."""
    if configured() is None or INTERVAL_MIN <= 0:
        return None
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                check_all(date.today())
            except Exception as e:  # noqa: BLE001
                log.warning("지연 알림 점검 실패: %s", e)
            stop.wait(INTERVAL_MIN * 60)

    threading.Thread(target=loop, name="npd-alert-check", daemon=True).start()
    return stop
