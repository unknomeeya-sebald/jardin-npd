"""가입 도메인 제한: 허용 도메인이거나 예외 주소일 때만 가입된다."""
import os
import tempfile

# app 을 불러오기 전에 임시 SQLite로 고정 (실제 DB에 테스트 사용자를 만들지 않도록)
os.environ["DB_FORCE_SQLITE"] = "1"
os.environ["SQLITE_PATH"] = os.path.join(tempfile.mkdtemp(), "test_auth_domain.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import auth  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def _rules(monkeypatch):
    monkeypatch.setattr(auth, "ALLOWED_DOMAINS", frozenset({"jardin.co.kr"}))
    monkeypatch.setattr(auth, "ALLOWED_EMAILS", frozenset({"guest@example.com"}))


def _signup(email: str) -> int:
    return client.post("/api/auth/signup", json={"email": email, "name": "테스트", "password": "test1234"}).status_code


def test_company_domain_can_sign_up():
    assert _signup("Domain-OK@Jardin.co.kr") == 201


def test_other_domain_is_rejected():
    assert _signup("someone@gmail.com") == 403
    # 도메인 끝부분만 같은 주소·하위 도메인도 막는다
    assert _signup("someone@notjardin.co.kr") == 403
    assert _signup("someone@jardin.co.kr.example.com") == 403
    assert _signup("someone@sub.jardin.co.kr") == 403


def test_exception_address_can_sign_up():
    assert _signup("Guest@example.com") == 201
    assert _signup("guest2@example.com") == 403


def test_existing_account_outside_domain_can_still_log_in(monkeypatch):
    assert _signup("guest@example.com") in (201, 409)
    monkeypatch.setattr(auth, "ALLOWED_EMAILS", frozenset())
    r = client.post("/api/auth/login", json={"email": "guest@example.com", "password": "test1234"})
    assert r.status_code == 200


def test_wildcard_turns_restriction_off(monkeypatch):
    monkeypatch.setattr(auth, "ALLOWED_DOMAINS", frozenset({"*"}))
    assert _signup("anyone@anywhere.org") == 201
