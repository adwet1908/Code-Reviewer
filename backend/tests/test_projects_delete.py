"""Project delete route."""

import io
import zipfile

from fastapi.testclient import TestClient

from app.db import SessionLocal, init_db
from app.main import app
from app.models import Project

client = TestClient(app)


def setup_module() -> None:
    init_db()


def _token(email: str) -> str:
    response = client.post("/auth/register", json={"email": email, "password": "password123"})
    if response.status_code != 200:
        response = client.post("/auth/login", json={"email": email, "password": "password123"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _tiny_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.py", "print('hi')\n")
    return buffer.getvalue()


def test_delete_project_removes_it():
    headers = {"Authorization": f"Bearer {_token('delete-proj@example.com')}"}
    created = client.post(
        "/projects",
        headers=headers,
        data={"name": "To delete"},
        files={"repo_zip": ("repo.zip", _tiny_zip(), "application/zip")},
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]

    deleted = client.delete(f"/projects/{project_id}", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["id"] == project_id

    missing = client.get(f"/projects/{project_id}", headers=headers)
    assert missing.status_code == 404

    with SessionLocal() as db:
        assert db.get(Project, project_id) is None


def test_delete_project_is_user_scoped():
    alice = {"Authorization": f"Bearer {_token('alice-del@example.com')}"}
    bob = {"Authorization": f"Bearer {_token('bob-del@example.com')}"}
    created = client.post(
        "/projects",
        headers=alice,
        data={"name": "Alice project"},
        files={"repo_zip": ("repo.zip", _tiny_zip(), "application/zip")},
    )
    project_id = created.json()["id"]

    stolen = client.delete(f"/projects/{project_id}", headers=bob)
    assert stolen.status_code == 404

    still_there = client.get(f"/projects/{project_id}", headers=alice)
    assert still_there.status_code == 200
