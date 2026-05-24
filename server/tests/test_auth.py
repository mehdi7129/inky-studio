"""Auth tests: enforces 401 on protected endpoints, login flow, rate limiting."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    """A TestClient with auth ENABLED (overrides the global inky_env autouse)."""
    monkeypatch.setenv("INKY_STUDIO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("INKY_STUDIO_DISABLE_AUTH", raising=False)
    from inky_web.db import init_db
    init_db()
    from inky_web.main import app
    with TestClient(app) as client:
        yield client, app


def test_protected_endpoint_returns_401_without_session(auth_client):
    client, _ = auth_client
    response = client.get("/api/queue")
    assert response.status_code == 401


def test_health_remains_public(auth_client):
    client, _ = auth_client
    response = client.get("/api/health")
    assert response.status_code == 200


def test_login_with_correct_password_grants_access(auth_client):
    client, app = auth_client
    creds = app.state.credentials
    login = client.post("/api/auth/login", json={"password": creds.password})
    assert login.status_code == 200
    assert login.json()["authenticated"] is True

    response = client.get("/api/queue")
    assert response.status_code == 200


def test_login_with_bad_password_is_rejected(auth_client):
    client, _ = auth_client
    response = client.post("/api/auth/login", json={"password": "nope"})
    assert response.status_code == 401


def test_logout_invalidates_session(auth_client):
    client, app = auth_client
    creds = app.state.credentials
    client.post("/api/auth/login", json={"password": creds.password})
    client.post("/api/auth/logout")
    response = client.get("/api/queue")
    assert response.status_code == 401


def test_rate_limit_blocks_after_five_bad_attempts(auth_client):
    client, _ = auth_client
    for _ in range(5):
        response = client.post("/api/auth/login", json={"password": "wrong"})
        assert response.status_code == 401
    response = client.post("/api/auth/login", json={"password": "wrong"})
    assert response.status_code == 429


def test_auth_status_endpoint_reflects_state(auth_client):
    client, app = auth_client
    status = client.get("/api/auth/status").json()
    assert status["auth_required"] is True
    assert status["authenticated"] is False

    creds = app.state.credentials
    client.post("/api/auth/login", json={"password": creds.password})
    status = client.get("/api/auth/status").json()
    assert status["authenticated"] is True
