"""Route checks that fail before any model call."""

from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app

client = TestClient(app)
_auth_token: str | None = None


def setup_module() -> None:
    init_db()


def _auth_header() -> dict[str, str]:
    global _auth_token
    if _auth_token is None:
        response = client.post(
            "/auth/register",
            json={"email": "reviewer@example.com", "password": "password123"},
        )
        assert response.status_code == 200, response.text
        _auth_token = response.json()["access_token"]
    return {"Authorization": f"Bearer {_auth_token}"}


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_models():
    response = client.get("/models")
    assert response.status_code == 200
    body = response.json()
    assert body["default"]
    assert len(body["models"]) == 3
    ids = {item["id"] for item in body["models"]}
    assert body["default"] in ids


def test_unsupported_model_is_400():
    response = client.post(
        "/review",
        headers=_auth_header(),
        data={"model": "not-a-real-model"},
        files=[("files", ("app.py", b"x = 1\n", "text/plain"))],
    )
    assert response.status_code == 400
    assert "Unsupported model" in response.json()["detail"]


def test_review_requires_auth():
    response = client.post(
        "/review",
        files=[("files", ("app.py", b"x = 1\n", "text/plain"))],
    )
    assert response.status_code == 401


def test_register_and_login():
    register = client.post(
        "/auth/register",
        json={"email": "alice@example.com", "password": "password123"},
    )
    assert register.status_code == 200
    assert register.json()["user"]["email"] == "alice@example.com"

    login = client.post(
        "/auth/login",
        json={"email": "alice@example.com", "password": "password123"},
    )
    assert login.status_code == 200
    assert "access_token" in login.json()

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"


def test_unsupported_type_is_400():
    response = client.post(
        "/review",
        headers=_auth_header(),
        files=[("files", ("notes.rtf", b"hello", "application/octet-stream"))],
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


def test_non_utf8_is_400():
    response = client.post(
        "/review",
        headers=_auth_header(),
        files=[("files", ("app.py", b"\xff\xfe", "text/plain"))],
    )
    assert response.status_code == 400
    assert "UTF-8" in response.json()["detail"]
