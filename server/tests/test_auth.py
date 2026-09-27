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
    creds = app.state.auth_service.credentials
    login = client.post("/api/auth/login", json={"password": creds.bootstrap_password})
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
    creds = app.state.auth_service.credentials
    client.post("/api/auth/login", json={"password": creds.bootstrap_password})
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
    assert status["password_change_supported"] is True

    creds = app.state.auth_service.credentials
    client.post("/api/auth/login", json={"password": creds.bootstrap_password})
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
    client.post("/api/auth/login", json={"password": app.state.auth_service.credentials.bootstrap_password})
    with client.websocket_connect("/api/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        client.post("/api/auth/logout")
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
        ("POST", "/api/auth/password"),
    ],
)
def test_api_surfaces_reject_missing_or_forged_session(auth_client, method, path):
    from inky_web.auth import COOKIE_NAME

    client, _ = auth_client
    assert client.request(method, path).status_code == 401
    client.cookies.set(COOKIE_NAME, "forged-session")
    assert client.request(method, path).status_code == 401


def _login(client, app):
    password = app.state.auth_service.credentials.bootstrap_password
    assert client.post("/api/auth/login", json={"password": password}).status_code == 200
    return password


def test_password_rotation_replaces_cookie_and_revokes_other_sessions_and_idle_ws(auth_client, caplog):
    from inky_web.auth import COOKIE_NAME, load_or_create_credentials

    client, app = auth_client
    caplog.set_level("INFO")
    password = _login(client, app)
    old_token = client.cookies.get(COOKIE_NAME)
    other_token = app.state.auth_service.login(password)
    with client.websocket_connect("/api/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        result = client.post("/api/auth/password", json={
            "current_password": password, "new_password": "Nouveau-é🔐-password",
        })
        assert result.status_code == 200
        assert result.json() == {
            "authenticated": True, "auth_required": True, "password_change_supported": True,
        }
        assert client.cookies.get(COOKIE_NAME) != old_token
        assert "HttpOnly" in result.headers["set-cookie"]
        assert "SameSite=strict" in result.headers["set-cookie"]
        assert not app.state.sessions.validate(old_token)
        assert not app.state.sessions.validate(other_token)
        assert client.get("/api/queue").status_code == 200
        with pytest.raises(WebSocketDisconnect) as rejected:
            ws.receive_json()
        assert rejected.value.code == 1008
    credentials = load_or_create_credentials(app.state.auth_service.credentials.path.parent)
    assert credentials.verify("Nouveau-é🔐-password")
    assert credentials.bootstrap_password is None
    assert client.post("/api/auth/login", json={"password": password}).status_code == 401
    assert client.post("/api/auth/login", json={"password": "Nouveau-é🔐-password"}).status_code == 200
    assert password not in caplog.text
    assert "Nouveau-é🔐-password" not in caplog.text


def test_wrong_current_password_preserves_session_and_is_throttled(auth_client):
    from inky_web.auth import COOKIE_NAME

    client, app = auth_client
    _login(client, app)
    token = client.cookies.get(COOKIE_NAME)
    for _ in range(5):
        result = client.post("/api/auth/password", json={
            "current_password": "wrong-password", "new_password": "new-password",
        })
        assert result.status_code == 403
        assert "set-cookie" not in result.headers
        assert client.cookies.get(COOKIE_NAME) == token
        assert client.get("/api/queue").status_code == 200
    assert client.post("/api/auth/password", json={
        "current_password": "wrong-password", "new_password": "new-password",
    }).status_code == 429


@pytest.mark.parametrize("password", ["x" * 7, "x" * 65, "private-\ud800-secret"])
def test_password_validation_does_not_echo_secret(auth_client, password):
    import json

    client, app = auth_client
    current = _login(client, app)
    result = client.post("/api/auth/password", content=json.dumps({
        "current_password": current, "new_password": password,
    }), headers={"Content-Type": "application/json"})
    assert result.status_code == 422
    assert "input" not in result.text
    assert current not in result.text
    assert "private-" not in result.text
    assert client.get("/api/queue").status_code == 200


@pytest.mark.parametrize("password", ["a" * 8, "🔐" * 64])
def test_new_password_length_boundaries_work_with_login(auth_client, password):
    client, app = auth_client
    current = _login(client, app)
    assert client.post("/api/auth/password", json={
        "current_password": current, "new_password": password,
    }).status_code == 200
    assert client.post("/api/auth/login", json={"password": password}).status_code == 200


def test_password_change_rejects_cross_origin_but_accepts_same_origin(auth_client):
    client, app = auth_client
    password = _login(client, app)
    body = {"current_password": password, "new_password": "new-password"}
    assert client.post("/api/auth/password", json=body, headers={"Origin": "http://attacker"}).status_code == 403
    assert client.get("/api/queue").status_code == 200
    assert client.post("/api/auth/password", json=body, headers={"Origin": "http://testserver"}).status_code == 200


def test_storage_failure_returns_503_and_preserves_old_access(auth_client, monkeypatch):
    from inky_web import auth

    client, app = auth_client
    current = _login(client, app)
    previous_file = app.state.auth_service.credentials.path.read_bytes()
    replace = auth.os.replace

    def fail(source, destination):
        if destination == app.state.auth_service.credentials.path:
            raise OSError("storage failure")
        return replace(source, destination)

    monkeypatch.setattr(auth.os, "replace", fail)
    result = client.post("/api/auth/password", json={
        "current_password": current, "new_password": "new-password",
    })
    assert result.status_code == 503
    assert "set-cookie" not in result.headers
    assert app.state.auth_service.credentials.path.read_bytes() == previous_file
    assert client.get("/api/queue").status_code == 200
    assert client.post("/api/auth/login", json={"password": current}).status_code == 200


def test_disabled_auth_does_not_offer_password_changes(client):
    assert client.get("/api/auth/status").json()["password_change_supported"] is False
    assert client.post("/api/auth/login", json={"password": "test"}).json()["password_change_supported"] is False
    assert client.post("/api/auth/password", json={
        "current_password": "test", "new_password": "new-password",
    }).status_code == 409
