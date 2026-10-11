"""Custom model settings without calling a provider."""

from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app

client = TestClient(app)


def setup_module() -> None:
    init_db()


def _token(email: str) -> str:
    response = client.post("/auth/register", json={"email": email, "password": "password123"})
    if response.status_code != 200:
        response = client.post("/auth/login", json={"email": email, "password": "password123"})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_create_custom_model_appears_in_catalog():
    headers = {"Authorization": f"Bearer {_token('models@example.com')}"}
    created = client.post(
        "/settings/models",
        headers=headers,
        json={
            "label": "My GPT",
            "provider": "openai",
            "model_id": "gpt-4o-mini",
            "api_key": "sk-test-secret-key",
            "base_url": "https://api.openai.com/v1",
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["api_key_hint"] == "-key"
    assert "sk-test" not in created.text
    assert body["selection_id"].startswith("custom:")

    listed = client.get("/settings/models", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    catalog = client.get("/models", headers=headers)
    ids = {item["id"] for item in catalog.json()["models"]}
    assert body["selection_id"] in ids
    assert any(item["source"] == "custom" for item in catalog.json()["models"])


def test_custom_model_is_user_scoped():
    alice = {"Authorization": f"Bearer {_token('alice-models@example.com')}"}
    bob = {"Authorization": f"Bearer {_token('bob-models@example.com')}"}
    created = client.post(
        "/settings/models",
        headers=alice,
        json={
            "label": "Alice only",
            "provider": "anthropic",
            "model_id": "claude-sonnet-4-5",
            "api_key": "sk-ant-secret",
        },
    )
    assert created.status_code == 200
    model_pk = created.json()["id"]

    bob_list = client.get("/settings/models", headers=bob)
    assert bob_list.json() == []

    stolen = client.delete(f"/settings/models/{model_pk}", headers=bob)
    assert stolen.status_code == 404


def test_set_default_custom_model():
    headers = {"Authorization": f"Bearer {_token('default-model@example.com')}"}
    created = client.post(
        "/settings/models",
        headers=headers,
        json={
            "label": "Local OpenAI",
            "provider": "openai",
            "model_id": "llama3",
            "api_key": "local-key",
            "base_url": "http://localhost:11434/v1",
        },
    )
    selection = created.json()["selection_id"]
    updated = client.put("/settings/default-model", headers=headers, json={"model": selection})
    assert updated.status_code == 200, updated.text
    catalog = client.get("/models", headers=headers)
    assert catalog.json()["default"] == selection


def test_rejects_bad_base_url():
    headers = {"Authorization": f"Bearer {_token('badurl@example.com')}"}
    response = client.post(
        "/settings/models",
        headers=headers,
        json={
            "label": "Nope",
            "provider": "openai",
            "model_id": "gpt-4o",
            "api_key": "sk-test",
            "base_url": "not-a-url",
        },
    )
    assert response.status_code == 400
