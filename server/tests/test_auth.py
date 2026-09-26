"""Auth tests: enforces 401 on protected endpoints, login flow, rate limiting."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


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


def test_websocket_requires_session(auth_client):
    client, app = auth_client
    with pytest.raises(WebSocketDisconnect) as rejected:
        with client.websocket_connect("/api/ws"):
            pytest.fail("Unauthenticated WebSocket was accepted")
    assert rejected.value.code == 1008
    assert not app.state.bus._subscribers


def test_websocket_session_is_revoked_on_logout(auth_client):
    client, app = auth_client
    client.post("/api/auth/login", json={"password": app.state.credentials.password})
    with client.websocket_connect("/api/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        client.post("/api/auth/logout")
        app.state.bus.broadcast("queue_updated")
        with pytest.raises(WebSocketDisconnect) as rejected:
            ws.receive_json()
        assert rejected.value.code == 1008


def test_unicode_password_is_rejected_without_server_error(auth_client):
    client, _ = auth_client
    assert client.post("/api/auth/login", json={"password": "éincorrect"}).status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/photos/unknown"),
        ("GET", "/api/state"),
        ("GET", "/api/settings"),
        ("POST", "/api/settings"),
        ("POST", "/api/display/next"),
        ("DELETE", "/api/history"),
        ("GET", "/api/system/update"),
        ("POST", "/api/system/update"),
    ],
)
def test_api_surfaces_reject_missing_or_forged_session(auth_client, method, path):
    from inky_web.auth import COOKIE_NAME

    client, _ = auth_client
    assert client.request(method, path).status_code == 401
    client.cookies.set(COOKIE_NAME, "forged-session")
    assert client.request(method, path).status_code == 401
