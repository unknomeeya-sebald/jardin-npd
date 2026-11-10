"""일정관리(복제 화면) API: 로그인한 사람에게만 원본 HTML을 준다."""
import os
import tempfile

# app 을 불러오기 전에 임시 SQLite로 고정 (실제 DB에 테스트 사용자를 만들지 않도록)
os.environ["DB_FORCE_SQLITE"] = "1"
os.environ["SQLITE_PATH"] = os.path.join(tempfile.mkdtemp(), "test_clone.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def test_requires_login():
    assert client.get("/api/clone/npd-schedule").status_code == 401


def test_serves_original_html_when_logged_in():
    r = client.post("/api/auth/signup", json={"email": "clone-test@jardin.co.kr", "name": "테스트", "password": "test1234"})
    assert r.status_code == 201
    token = r.json()["token"]
    r = client.get("/api/clone/npd-schedule", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<title>NPD 일정</title>" in r.text
    assert 'data-v="A"' in r.text  # 「한 화면」 보기
