"""Private PHOTO credentials, anti-replay, closed media roles and idle WS revocation."""
from __future__ import annotations

import secrets
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from inky_web import auth
from inky_web.photo_access import AccessError, PhotoAccessStore


def credential():
    return {"device_id": str(uuid4()), "device_token": secrets.token_hex(32)}


def enrollment():
    return {**credential(), "request_id": str(uuid4())}


def invitation():
    return {"invitation_id": str(uuid4()), "invitation_token": secrets.token_hex(32),
            "request_id": str(uuid4()), "ttl_seconds": 300}


def claim(invite):
    return {"invitation_id": invite["invitation_id"], "invitation_token": invite["invitation_token"], **enrollment()}


@pytest.fixture
def store(tmp_path):
    clock = SimpleNamespace(wall=1000.0, mono=50.0, epoch="a" * 64)
    value = PhotoAccessStore(tmp_path / "private", lambda: clock.epoch,
                             clock=lambda: clock.wall, monotonic=lambda: clock.mono)
    return value, clock


def setup_invite(value):
    owner = enrollment()
    actor = value.enroll(**owner)
    invite = invitation()
    value.invite(actor, **invite)
    return actor, owner, invite


def test_private_hashes_and_enrollment_retry(store):
    value, _ = store
    owner = enrollment()
    actor = value.enroll(**owner)
    assert value.enroll(**owner) == actor
    assert value.authenticate(owner["device_id"], owner["device_token"]) == actor
    assert value.directory.stat().st_mode & 0o777 == 0o700
    assert value.path.stat().st_mode & 0o777 == 0o600
    assert owner["device_token"].encode() not in value.path.read_bytes()
    for key, replacement in [("device_token", "0" * 64), ("request_id", str(uuid4()))]:
        with pytest.raises(AccessError):
            value.enroll(**{**owner, key: replacement})


def test_claim_idempotence_binds_all_fields(store):
    value, _ = store
    _, _, invite = setup_invite(value)
    payload = claim(invite)
    actor = value.claim(**payload)
    assert actor.role == "media"
    assert value.claim(**payload) == actor
    for key, replacement in [("device_id", str(uuid4())), ("request_id", str(uuid4())),
                             ("device_token", "1" * 64), ("invitation_token", "2" * 64)]:
        with pytest.raises(AccessError):
            value.claim(**{**payload, key: replacement})
    for key in ("device_token", "invitation_token"):
        assert payload[key].encode() not in value.path.read_bytes()


def test_concurrent_claim_is_atomic(store):
    value, _ = store
    _, _, invite = setup_invite(value)
    first, second = claim(invite), claim(invite)
    def attempt(payload):
        try:
            return value.claim(**payload)
        except AccessError:
            return None
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(attempt, [first, second] * 8))
    assert len({result.device_id for result in results if result is not None}) == 1
    assert sum(result is not None for result in results) == 8
    with value._connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM devices WHERE role='media'").fetchone()[0] == 1
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2


@pytest.mark.parametrize("change", ["wall_expiry", "mono_expiry", "backwards", "epoch", "restart"])
def test_expiry_epoch_restart_fail_closed(store, change):
    value, clock = store
    actor, owner, invite = setup_invite(value)
    if change == "wall_expiry":
        clock.wall += 300
    elif change == "mono_expiry":
        clock.mono += 300
    elif change == "backwards":
        clock.wall -= 1
    elif change == "epoch":
        clock.epoch = "b" * 64
    else:
        value = PhotoAccessStore(value.directory, lambda: clock.epoch,
                                 clock=lambda: clock.wall, monotonic=lambda: clock.mono)
        assert value.authenticate(owner["device_id"], owner["device_token"]) == actor
    with pytest.raises(AccessError):
        value.claim(**claim(invite))
    if change in {"wall_expiry", "mono_expiry", "restart"}:
        with pytest.raises(AccessError):
            value.invite(actor, **invite)


def test_restart_preserves_device_not_claim_retry(store):
    value, clock = store
    actor, _, invite = setup_invite(value)
    payload = claim(invite)
    media = value.claim(**payload)
    value = PhotoAccessStore(value.directory, lambda: clock.epoch)
    assert value.authenticate(payload["device_id"], payload["device_token"]) == media
    with pytest.raises(AccessError):
        value.claim(**payload)
    with pytest.raises(AccessError):
        value.invite(actor, **invite)


def test_revocation_and_media_authority(store):
    value, _ = store
    actor, _, invite = setup_invite(value)
    payload = claim(invite)
    media = value.claim(**payload)
    with pytest.raises(AccessError):
        value.invite(media, **invitation())
    with pytest.raises(AccessError):
        value.devices(media)
    value.revoke_device(actor, media.device_id)
    assert not value.valid(media)
    with pytest.raises(AccessError):
        value.claim(**payload)
    fresh = invitation()
    value.invite(actor, **fresh)
    value.revoke_invitation(actor, fresh["invitation_id"])
    with pytest.raises(AccessError):
        value.claim(**claim(fresh))
    fresh = invitation()
    value.invite(actor, **fresh)
    value.revoke_device(actor, actor.device_id)
    with pytest.raises(AccessError):
        value.claim(**claim(fresh))


def test_retry_does_not_extend_ttl_and_capacity_is_bounded(store, monkeypatch):
    from inky_web import photo_access
    value, clock = store
    actor, _, invite = setup_invite(value)
    first = value.invite(actor, **invite)
    clock.wall += 30
    clock.mono += 30
    assert value.invite(actor, **invite) == first
    with pytest.raises(AccessError):
        value.invite(actor, **{**invite, "ttl_seconds": 100})
    monkeypatch.setattr(photo_access, "MAX_INVITATIONS", 1)
    with pytest.raises(AccessError):
        value.invite(actor, **invitation())
    clock.wall += 300
    clock.mono += 300
    value.invite(actor, **invitation())
    monkeypatch.setattr(photo_access, "MAX_DEVICES", 1)
    with pytest.raises(AccessError):
        value.enroll(**enrollment())
    monkeypatch.setattr(photo_access, "MAX_ISSUED_INVITATIONS", 1)
    with pytest.raises(AccessError):
        value.invite(actor, **invitation())


@pytest.fixture
def frame(tmp_path, monkeypatch):
    monkeypatch.delenv("INKY_STUDIO_DISABLE_AUTH", raising=False)
    monkeypatch.setenv("INKY_STUDIO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INKY_STUDIO_PHOTO_ACCESS_URL", "https://frame.local:8443")
    from inky_web.main import app
    from inky_web.provisioning.identity import load_or_create_identity
    app.state.frame_identity = load_or_create_identity(tmp_path / "test-identity")
    with TestClient(app, base_url="https://testserver") as client:
        client.portal.call(app.state.scheduler.stop)
        yield client, app
    del app.state.frame_identity


def login(client, app):
    assert client.post("/api/auth/login", json={"password": app.state.auth_service.credentials.bootstrap_password}).status_code == 200


def enroll_client(client, app):
    login(client, app)
    owner = enrollment()
    result = client.post("/api/auth/devices/enroll", json=owner)
    assert result.status_code == 200, result.text
    assert client.post("/api/auth/device-session", json={key: owner[key] for key in ("device_id", "device_token")}).status_code == 200
    return owner


def invited_client(client):
    invite = invitation()
    result = client.post("/api/auth/invitations", json=invite)
    assert result.status_code == 200, result.text
    owner_cookie = client.cookies.get(auth.COOKIE_NAME)
    client.cookies.clear()
    payload = claim(invite)
    result = client.post("/api/auth/invitations/claim", json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["role"] == "media"
    assert "Secure" in result.headers["set-cookie"]
    return payload, owner_cookie


def test_live_legacy_enrollment_and_retry(frame):
    client, app = frame
    payload = enrollment()
    assert client.post("/api/auth/devices/enroll", json=payload).status_code == 401
    login(client, app)
    previous = client.cookies.get(auth.COOKIE_NAME)
    first = client.post("/api/auth/devices/enroll", json=payload)
    assert first.status_code == 200
    assert "set-cookie" not in first.headers
    assert client.post("/api/auth/devices/enroll", json=payload).json() == first.json()
    assert client.cookies.get(auth.COOKIE_NAME) == previous
    assert payload["device_token"] not in first.text
    assert "url" not in first.json()["identity"]
    assert client.post("/api/auth/device-session", json={key: payload[key] for key in ("device_id", "device_token")}).status_code == 200
    assert client.post("/api/auth/devices/enroll", json=enrollment()).status_code == 403


@pytest.mark.parametrize(("method", "path"), [
    ("POST", "/api/auth/password"), ("POST", "/api/auth/devices/enroll"),
    ("GET", "/api/auth/devices"), ("GET", f"/api/auth/devices/{uuid4()}"),
    ("DELETE", f"/api/auth/devices/{uuid4()}"), ("POST", "/api/auth/invitations"),
    ("DELETE", f"/api/auth/invitations/{uuid4()}"),
    ("GET", "/api/provisioning/capabilities"), ("POST", "/api/provisioning/adoption/window"),
    ("POST", "/api/provisioning/wifi/confirm"),
    ("GET", "/api/system/update"), ("POST", "/api/system/update"),
    ("GET", "/api/future-admin-route"),
])
def test_media_denied_owner_routes(frame, method, path):
    client, app = frame
    enroll_client(client, app)
    invited_client(client)
    result = client.request(method, path, json={})
    assert result.status_code == 403
    assert result.headers["cache-control"] == "no-store"


def test_media_upload_schedule_and_display(frame, png_factory):
    client, app = frame
    enroll_client(client, app)
    invited_client(client)
    assert client.get("/api/auth/status").json()["password_change_supported"] is False
    for path in ["/api/state", "/api/queue", "/api/history", "/api/settings", "/api/display", "/api/display/status"]:
        result = client.get(path)
        assert result.status_code == 200, path
        assert result.headers["cache-control"] == "no-store"
    upload = client.post("/api/queue", files={"file": ("photo.png", png_factory(), "image/png")})
    assert upload.status_code == 201
    assert client.get(f"/api/photos/{upload.json()['photo']['id']}").status_code == 200
    assert client.post("/api/settings", json={"change_mode": "manual"}).status_code == 200
    assert client.post("/api/settings", json={"saturation": 2}).status_code == 403
    assert client.post("/api/settings", json={"unknown": 1}).status_code == 403
    assert client.post("/api/display/next").status_code == 202
    assert client.get("/api/history").json()


def test_revoke_closes_idle_ws_and_all_sessions(frame):
    client, app = frame
    enroll_client(client, app)
    payload, owner_cookie = invited_client(client)
    media_cookie = client.cookies.get(auth.COOKIE_NAME)
    with client.websocket_connect("wss://testserver/api/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        client.cookies.clear()
        client.cookies.set(auth.COOKIE_NAME, owner_cookie)
        assert client.delete(f"/api/auth/devices/{payload['device_id']}").status_code == 200
        with pytest.raises(WebSocketDisconnect) as rejected:
            ws.receive_json()
        assert rejected.value.code == 1008
    assert not app.state.sessions.validate(media_cookie)
    client.cookies.clear()
    assert client.post("/api/auth/device-session", json={key: payload[key] for key in ("device_id", "device_token")}).status_code == 401


def test_media_ws_filters_system_and_refuses_cleartext(frame):
    client, app = frame
    enroll_client(client, app)
    invited_client(client)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("ws://testserver/api/ws"):
            pytest.fail("Device cookie accepted over cleartext")
    with client.websocket_connect("wss://testserver/api/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        app.state.bus.broadcast("system_update", {"private": "admin-event"})
        app.state.bus.broadcast("queue_updated", {"action": "test"})
        assert ws.receive_json() == {"type": "queue_updated", "payload": {"action": "test"}}


@pytest.mark.parametrize("path", ["/api/auth/devices/enroll", "/api/auth/device-session", "/api/auth/invitations", "/api/auth/invitations/claim"])
def test_http_and_forwarded_headers_refused(frame, path):
    client, app = frame
    login(client, app)
    result = client.post("http://testserver" + path, json={}, headers={"X-Forwarded-Proto": "https", "Forwarded": "proto=https"})
    assert result.status_code == 403
    assert result.headers["cache-control"] == "no-store"


def test_device_cookie_not_usable_on_http(frame):
    client, app = frame
    enroll_client(client, app)
    raw_cookie = client.cookies.get(auth.COOKIE_NAME)
    result = client.get("http://testserver/api/queue", headers={"Cookie": f"{auth.COOKIE_NAME}={raw_cookie}", "X-Forwarded-Proto": "https"})
    assert result.status_code == 403


@pytest.mark.parametrize("url", [None, "http://frame.local:8443", "https://a:b@frame.local:8443", "https://frame.local/a", "https://frame.local?secret=1"])
def test_invitation_requires_explicit_canonical_https_url(frame, monkeypatch, url):
    client, app = frame
    enroll_client(client, app)
    if url is None:
        monkeypatch.delenv("INKY_STUDIO_PHOTO_ACCESS_URL")
    else:
        monkeypatch.setenv("INKY_STUDIO_PHOTO_ACCESS_URL", url)
    result = client.post("/api/auth/invitations", json=invitation())
    assert result.status_code == 503
    assert "secret" not in result.text
    with app.state.photo_access._connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM invitations").fetchone()[0] == 0


def test_validation_and_logs_do_not_echo_any_secret(frame, caplog):
    client, app = frame
    enroll_client(client, app)
    secret = secrets.token_hex(32)
    bodies = [{"device_id": str(uuid4()), "device_token": secret, "unexpected": secret},
              {secret: "extra-field-name"}, {"device_id": str(uuid4()), "device_token": secret + "x"}]
    for body in bodies:
        result = client.post("/api/auth/device-session", json=body)
        assert result.status_code == 422
        assert secret not in result.text
        assert "input" not in result.text
        assert result.headers["cache-control"] == "no-store"
    result = client.post("/api/auth/invitations", content=secret * 100)
    assert result.status_code == 413
    assert secret not in result.text
    assert secret not in caplog.text


def test_password_epoch_revokes_device_sessions(frame):
    client, app = frame
    owner = enroll_client(client, app)
    cookie = client.cookies.get(auth.COOKIE_NAME)
    current = app.state.auth_service.credentials.bootstrap_password
    with client.websocket_connect("wss://testserver/api/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        assert client.post("/api/auth/password", json={"current_password": current, "new_password": "new-password"}).status_code == 200
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert not app.state.sessions.validate(cookie)
    client.cookies.clear()
    assert client.post("/api/auth/device-session", json={key: owner[key] for key in ("device_id", "device_token")}).status_code == 401


@pytest.mark.parametrize("invalid", ["expiry", "backwards", "nan", "infinity"])
def test_observed_clock_failure_never_reactivates_same_qr(store, invalid):
    value, clock = store
    _, _, invite = setup_invite(value)
    original = clock.wall
    clock.wall = {"expiry": original + 300, "backwards": original - 1,
                  "nan": float("nan"), "infinity": float("inf")}[invalid]
    payload = claim(invite)
    with pytest.raises(AccessError):
        value.claim(**payload)
    clock.wall = original
    with pytest.raises(AccessError):
        value.claim(**payload)


def test_stale_legacy_cookie_cannot_enroll_after_external_durable_reset(frame):
    client, app = frame
    login(client, app)
    old_credentials = app.state.auth_service.credentials
    auth.reset_credentials(old_credentials.path.parent)
    result = client.post("/api/auth/devices/enroll", json=enrollment())
    assert result.status_code == 401
    assert app.state.auth_service.credentials is old_credentials


def test_external_reset_invalidates_device_and_idle_ws(frame):
    client, app = frame
    owner = enroll_client(client, app)
    cookie = client.cookies.get(auth.COOKIE_NAME)
    with client.websocket_connect("wss://testserver/api/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        auth.reset_credentials(app.state.auth_service.credentials.path.parent)
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert not app.state.sessions.validate(cookie)
    assert client.post("/api/auth/device-session", json={key: owner[key] for key in ("device_id", "device_token")}).status_code == 401


def test_corrupt_or_missing_durable_credentials_fail_closed_without_creation(frame):
    client, app = frame
    owner = enroll_client(client, app)
    client.cookies.clear()
    path = app.state.auth_service.credentials.path
    path.write_text("invalid", encoding="utf-8")
    assert client.post("/api/auth/device-session", json={key: owner[key] for key in ("device_id", "device_token")}).status_code == 503
    path.unlink()
    assert client.post("/api/auth/device-session", json={key: owner[key] for key in ("device_id", "device_token")}).status_code == 503
    assert not path.exists()


def test_reissued_ids_request_ids_and_tokens_are_never_reusable(store):
    value, clock = store
    actor, _, invite = setup_invite(value)
    clock.wall += 301
    clock.mono += 301
    for key in ("invitation_id", "request_id", "invitation_token"):
        replacement = invitation()
        replacement[key] = invite[key]
        with pytest.raises(AccessError):
            value.invite(actor, **replacement)


def test_new_device_session_displaces_bounded_old_sessions_and_closes_idle_ws(frame):
    client, app = frame
    owner = enroll_client(client, app)
    with client.websocket_connect("wss://testserver/api/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        for _ in range(8):
            assert client.post("/api/auth/device-session", json={key: owner[key] for key in ("device_id", "device_token")}).status_code == 200
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert len(app.state.sessions._principals) == 8


def test_real_http_listener_ignores_forwarded_https_and_real_tls_accepts_device_session(tmp_path):
    import http.client
    import json

    from inky_web.provisioning.identity import load_or_create_identity
    from tests.test_provisioning_listeners import _frame, _listeners, _request
    directory = tmp_path / "real-transport"
    with _frame(directory) as process:
        ports = _listeners(process, directory)
        payload = credential()
        connection = http.client.HTTPConnection("127.0.0.1", ports["http"], timeout=3)
        try:
            connection.request("POST", "/api/auth/device-session", body=json.dumps(payload),
                               headers={"Content-Type": "application/json", "X-Forwarded-Proto": "https",
                                        "Forwarded": "proto=https", "X-Forwarded-Host": "trusted.local"})
            result = connection.getresponse()
            assert result.status == 403
            assert result.getheader("Cache-Control") == "no-store"
            assert payload["device_token"].encode() not in result.read()
        finally:
            connection.close()
        identity = load_or_create_identity(directory / "provisioning")
        _, headers, _, _ = _request(ports["https"], "/api/auth/login", identity=identity,
                                    method="POST", payload={"password": "listener-test-password"})
        cookie = headers["set-cookie"].split(";", 1)[0]
        status, _, result, tls = _request(ports["https"], "/api/auth/devices/enroll", identity=identity,
                                          method="POST", payload={**payload, "request_id": str(uuid4())}, cookie=cookie)
        assert status == 200 and tls == "TLSv1.3"
        assert result["identity"]["spki_sha256"] == identity.spki_sha256
        status, headers, result, _ = _request(ports["https"], "/api/auth/device-session", identity=identity,
                                              method="POST", payload=payload)
        assert status == 200 and result["role"] == "owner"
        assert "Secure" in headers["set-cookie"]


def test_corrupt_unknown_role_does_not_gain_owner_capabilities(store):
    value, _ = store
    owner = enrollment()
    value.enroll(**owner)
    with value._transaction() as conn:
        conn.execute("PRAGMA ignore_check_constraints=ON")
        conn.execute("UPDATE devices SET role='unknown-admin'")
    with pytest.raises(AccessError):
        value.authenticate(owner["device_id"], owner["device_token"])
