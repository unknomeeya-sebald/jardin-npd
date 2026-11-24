"""비밀번호 찾기: 인증 코드 발급(/forgot) → 새 비밀번호 설정(/reset)."""
import os
import tempfile

# app 을 불러오기 전에 임시 SQLite로 고정 (실제 DB에 테스트 사용자를 만들지 않도록)
os.environ["DB_FORCE_SQLITE"] = "1"
os.environ["SQLITE_PATH"] = os.path.join(tempfile.mkdtemp(), "test_auth_reset.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import auth, notify  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
sent: list[tuple[str, str]] = []


@pytest.fixture(autouse=True)
def _fake_send(monkeypatch):
    """Slack으로 실제 보내지 않고 코드를 가로챈다. 다시 보내기 간격 제한은 끈다."""
    sent.clear()
    monkeypatch.setattr(auth, "send_reset_code", lambda email, code: sent.append((email, code)))
    monkeypatch.setattr(auth, "RESET_RESEND_SEC", 0)


def _signup(email: str, pw: str = "old12345"):
    r = client.post("/api/auth/signup", json={"email": email, "name": "테스트", "password": pw})
    assert r.status_code == 201


def _login(email: str, pw: str) -> int:
    return client.post("/api/auth/login", json={"email": email, "password": pw}).status_code


def test_reset_changes_password_and_logs_in():
    _signup("reset-ok@jardin.co.kr")
    r = client.post("/api/auth/forgot", json={"email": " Reset-OK@jardin.co.kr "})
    assert r.status_code == 200
    email, code = sent[-1]
    assert email == "reset-ok@jardin.co.kr" and len(code) == 6 and code.isdigit()

    r = client.post("/api/auth/reset", json={"email": email, "code": code, "password": "new12345"})
    assert r.status_code == 200
    token = r.json()["token"]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["email"] == email
    assert _login(email, "new12345") == 200
    assert _login(email, "old12345") == 401
    # 쓴 코드는 다시 쓸 수 없다
    assert client.post("/api/auth/reset", json={"email": email, "code": code, "password": "again1234"}).status_code == 400


def test_unknown_email_is_told_to_sign_up():
    r = client.post("/api/auth/forgot", json={"email": "nobody@jardin.co.kr"})
    assert r.status_code == 404
    assert not sent


def test_wrong_code_locks_after_max_attempts():
    email = "reset-lock@jardin.co.kr"
    _signup(email)
    client.post("/api/auth/forgot", json={"email": email})
    code = sent[-1][1]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(auth.RESET_MAX_ATTEMPTS):
        assert client.post("/api/auth/reset", json={"email": email, "code": wrong, "password": "new12345"}).status_code == 400
    # 횟수를 다 쓰면 맞는 코드도 거절
    assert client.post("/api/auth/reset", json={"email": email, "code": code, "password": "new12345"}).status_code == 400
    assert _login(email, "old12345") == 200


def test_expired_code_is_rejected(monkeypatch):
    email = "reset-exp@jardin.co.kr"
    _signup(email)
    monkeypatch.setattr(auth, "RESET_TTL", -1)
    client.post("/api/auth/forgot", json={"email": email})
    r = client.post("/api/auth/reset", json={"email": email, "code": sent[-1][1], "password": "new12345"})
    assert r.status_code == 400


def test_weak_password_is_rejected():
    email = "reset-weak@jardin.co.kr"
    _signup(email)
    client.post("/api/auth/forgot", json={"email": email})
    r = client.post("/api/auth/reset", json={"email": email, "code": sent[-1][1], "password": "onlyletters"})
    assert r.status_code == 422
    assert _login(email, "old12345") == 200


def test_resend_is_rate_limited(monkeypatch):
    email = "reset-rate@jardin.co.kr"
    _signup(email)
    monkeypatch.setattr(auth, "RESET_RESEND_SEC", 60)
    assert client.post("/api/auth/forgot", json={"email": email}).status_code == 200
    assert client.post("/api/auth/forgot", json={"email": email}).status_code == 429
    assert len(sent) == 1


def test_send_failures_are_reported(monkeypatch):
    email = "reset-fail@jardin.co.kr"
    _signup(email)

    def no_slack_user(e, c):
        raise notify.SlackUserNotFound(e)

    monkeypatch.setattr(auth, "send_reset_code", no_slack_user)
    assert client.post("/api/auth/forgot", json={"email": email}).status_code == 422

    def broken(e, c):
        raise RuntimeError("missing_scope")

    monkeypatch.setattr(auth, "send_reset_code", broken)
    assert client.post("/api/auth/forgot", json={"email": email}).status_code == 503
    # 보내지 못한 코드는 저장하지 않는다
    assert client.post("/api/auth/reset", json={"email": email, "code": "123456", "password": "new12345"}).status_code == 400
