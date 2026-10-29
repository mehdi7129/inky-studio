"""Legacy QR upgrade proof: exact MAC, public HTTP, bounded and read-only."""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from starlette.requests import HTTPConnection

from inky_web import auth
from inky_web.api import legacy_tls_proof

PROOF_PATH = "/api/auth/legacy-tls-proof"
UNAVAILABLE = {"detail": "Preuve HTTPS indisponible"}
NONCE = "01" * 32
# Independent fixtures from contract SHA256 c2e589c38ac37c70d9314a783832c8a68
# cdc1cbec59c8f9dfa078ed33a8bd628; do not derive expected values from server code.
VECTORS = [
    {
        "secret": "Abcdef0123456789",
        "nonce": "00" * 32,
        "identity": {
            "frame_id": "11111111-1111-4111-8111-111111111111",
            "spki_sha256": "ab" * 32,
            "url": "https://inky-fixture.local:8443",
        },
        "message_hex": (
            "696e6b792d6c65676163792d746c732d70726f6f662d763100"
            "0000000000000000000000000000000000000000000000000000000000000000"
            "11111111111141118111111111111111"
            "abababababababababababababababababababababababababababababababab"
            "001f68747470733a2f2f696e6b792d666978747572652e6c6f63616c3a38343433"
        ),
        "proof": "f2bd35f28b36c364a9b2447e89a2158195e4f4b506d3f993e26cd2804fc8456d",
    },
    {
        "secret": "Zyxwv9876543210A",
        "nonce": "ff" * 32,
        "identity": {
            "frame_id": "22222222-2222-4222-8222-222222222222",
            "spki_sha256": "cd" * 32,
            "url": "https://[::1]:8443",
        },
        "message_hex": (
            "696e6b792d6c65676163792d746c732d70726f6f662d763100"
            "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
            "22222222222242228222222222222222"
            "cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd"
            "001268747470733a2f2f5b3a3a315d3a38343433"
        ),
        "proof": "25f160a10af95cd5c1fafe9c2787c83c6446f80d9a62cc4857bb4f9dde4b8cca",
    },
]


def expected_proof(secret, nonce, identity):
    """Client-side construction, independent of both server MAC helpers."""
    url = identity["url"].encode("utf-8")
    message = b"".join((
        b"inky-legacy-tls-proof-v1\0", bytes.fromhex(nonce),
        UUID(identity["frame_id"]).bytes, bytes.fromhex(identity["spki_sha256"]),
        len(url).to_bytes(2, "big"), url,
    ))
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def no_store_no_cookie(response):
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers


def forbidden(*args, **kwargs):
    raise AssertionError("Proof must not access credentials, cookies, authority or private TLS material")


@pytest.fixture(autouse=True)
def isolated_proof_limiter(monkeypatch):
    monkeypatch.setattr(legacy_tls_proof, "limiter", auth.LoginRateLimiter(max_attempts=30))


class PublicIdentity:
    def __init__(self, identity):
        self.frame_id = identity.frame_id
        self.cert_pem = identity.cert_pem

    @property
    def key_pem(self):
        return forbidden()


@pytest.fixture
def frame(tmp_path, monkeypatch):
    monkeypatch.delenv("INKY_STUDIO_DISABLE_AUTH", raising=False)
    monkeypatch.delenv("INKY_STUDIO_BLUETOOTH", raising=False)
    monkeypatch.setenv("INKY_STUDIO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INKY_STUDIO_PHOTO_ACCESS_URL", "https://frame.local:8443")
    from inky_web import welcome
    from inky_web.main import app
    from inky_web.provisioning.identity import load_or_create_identity

    monkeypatch.setattr(welcome, "show_welcome", lambda *_: None)
    identity = load_or_create_identity(tmp_path / "test-identity")
    app.state.frame_identity = PublicIdentity(identity)
    expected_identity = {
        "frame_id": identity.frame_id, "spki_sha256": identity.spki_sha256,
        "url": "https://frame.local:8443",
    }
    with TestClient(app, base_url="http://testserver") as client:
        client.portal.call(app.state.scheduler.stop)
        yield SimpleNamespace(client=client, app=app, identity=expected_identity, directory=tmp_path)
    del app.state.frame_identity


@pytest.mark.parametrize("vector", VECTORS)
def test_known_contract_vectors(vector):
    assert legacy_tls_proof.PROOF_PATH == PROOF_PATH
    assert legacy_tls_proof._message(vector["nonce"], vector["identity"]).hex() == vector["message_hex"]
    assert legacy_tls_proof._proof(vector["secret"], vector["nonce"], vector["identity"]) == vector["proof"]
    assert expected_proof(vector["secret"], vector["nonce"], vector["identity"]) == vector["proof"]


@pytest.mark.parametrize("field", ["nonce", "frame_id", "spki_sha256", "url"])
def test_mac_binds_every_returned_identity_field_and_nonce(field):
    vector = VECTORS[0]
    identity, nonce = dict(vector["identity"]), vector["nonce"]
    if field == "nonce":
        nonce = "01" * 32
    elif field == "frame_id":
        identity[field] = VECTORS[1]["identity"][field]
    elif field == "spki_sha256":
        identity[field] = "cd" * 32
    else:
        identity[field] += "/"
    assert legacy_tls_proof._proof(vector["secret"], nonce, identity) != vector["proof"]
    assert legacy_tls_proof._proof(vector["secret"], nonce, identity) == expected_proof(
        vector["secret"], nonce, identity,
    )


def test_public_http_proof_uses_loaded_public_identity_and_existing_secret(frame):
    response = frame.client.post(PROOF_PATH, json={"v": 1, "nonce": NONCE})
    assert response.status_code == 200, response.text
    no_store_no_cookie(response)
    body = response.json()
    assert set(body) == {"v", "nonce", "identity", "proof"}
    assert type(body["v"]) is int
    assert body["v"] == 1 and body["nonce"] == NONCE
    assert body["identity"] == frame.identity
    secret = frame.app.state.auth_service.credentials.bootstrap_password
    assert body["proof"] == expected_proof(secret, NONCE, frame.identity)
    assert secret not in response.text
    assert not frame.client.cookies


def test_proof_ignores_all_cookies_and_existing_photo_principals(frame, monkeypatch):
    baseline = frame.client.post(PROOF_PATH, json={"v": 1, "nonce": NONCE})
    assert baseline.status_code == 200
    monkeypatch.setattr(auth, "get_session_token", forbidden)
    monkeypatch.setattr(frame.app.state.sessions, "principal", forbidden)
    monkeypatch.setattr(frame.app.state.sessions, "validate", forbidden)
    response = frame.client.post(PROOF_PATH, json={"v": 1, "nonce": NONCE}, headers={
        "Cookie": f"{auth.COOKIE_NAME}=untrusted-device-cookie; another=private",
    })
    assert response.status_code == 200, response.text
    assert response.json() == baseline.json()
    no_store_no_cookie(response)


@pytest.mark.parametrize("method", ["GET", "HEAD", "PUT", "DELETE", "PATCH", "OPTIONS"])
def test_non_post_methods_produce_no_proof_and_never_read_cookies(frame, monkeypatch, method):
    monkeypatch.setattr(HTTPConnection, "cookies", property(forbidden))
    response = frame.client.request(method, PROOF_PATH, json={"v": 1, "nonce": NONCE})
    assert response.status_code == 405
    assert "proof" not in response.text
    no_store_no_cookie(response)


@pytest.mark.parametrize("origin", ["http://localhost:5173", "https://untrusted.invalid"])
def test_cors_preflight_also_produces_no_proof_and_is_uncacheable(frame, origin):
    response = frame.client.options(PROOF_PATH, headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
    })
    assert response.status_code in (200, 400, 405)
    assert "proof" not in response.text
    no_store_no_cookie(response)


@pytest.mark.parametrize("path", [PROOF_PATH + "/", PROOF_PATH + "/other", PROOF_PATH + "-other"])
def test_only_exact_proof_path_bypasses_authentication(frame, path):
    response = frame.client.post(path, json={"v": 1, "nonce": NONCE}, follow_redirects=False)
    assert response.status_code == 401
    assert "proof" not in response.text
    assert "location" not in response.headers


INVALID_BODIES = [
    {}, {"v": 1}, {"nonce": NONCE}, [], None, "input-private-marker",
    *({"v": value, "nonce": NONCE} for value in [True, False, 1.0, 1.5, "1", 0, 2, None]),
    *({"v": 1, "nonce": value} for value in [
        True, 1, None, "", "00" * 31, "00" * 33, "AB" * 32, "gg" * 32,
        "01" * 32 + "\n", "  " + "01" * 31,
    ]),
    {"v": 1, "nonce": NONCE, "password": "input-private-marker"},
    {"v": 1, "nonce": NONCE, "device_token": "input-private-marker"},
]


@pytest.mark.parametrize("body", INVALID_BODIES)
def test_invalid_request_schema_is_fixed_private_and_uncacheable(frame, body, caplog):
    response = frame.client.post(PROOF_PATH, content=json.dumps(body), headers={
        "Content-Type": "application/json",
    })
    assert response.status_code == 422
    assert "proof" not in response.json()
    assert "input" not in response.text
    assert "input-private-marker" not in caplog.text
    no_store_no_cookie(response)


@pytest.mark.parametrize("content", [b"{", b'{"v":1,"nonce":', b"\xff", b""])
def test_malformed_json_is_fixed_private_and_uncacheable(frame, content):
    response = frame.client.post(PROOF_PATH, content=content, headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert "proof" not in response.text
    assert "input" not in response.text
    no_store_no_cookie(response)


def test_duplicate_json_fields_are_rejected(frame):
    content = '{"v":1,"nonce":"' + NONCE + '","v":1}'
    response = frame.client.post(PROOF_PATH, content=content, headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert "proof" not in response.text
    no_store_no_cookie(response)


@pytest.mark.parametrize("chunked", [False, True])
def test_body_limit_counts_actual_bytes_before_json_parsing(frame, chunked):
    content = b'{"v":1,"nonce":"' + NONCE.encode() + b'","extra":"' + b"x" * 2048 + b'"}'
    if chunked:
        content = iter([content[:1000], content[1000:2000], content[2000:]])
    response = frame.client.post(PROOF_PATH, content=content, headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert "proof" not in response.text
    no_store_no_cookie(response)


@pytest.mark.asyncio
async def test_chunked_body_limit_without_content_length(frame):
    chunks_received = []

    async def chunks():
        for index in range(3):
            chunks_received.append(index)
            yield b" " * 1000

    async with AsyncClient(transport=ASGITransport(app=frame.app), base_url="http://testserver") as client:
        response = await client.post(PROOF_PATH, content=chunks(), headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert chunks_received == [0, 1, 2]
    assert "content-length" not in response.request.headers
    no_store_no_cookie(response)


def test_exact_body_limit_still_accepts_valid_json(frame):
    content = json.dumps({"v": 1, "nonce": NONCE}).encode()
    content += b" " * (2048 - len(content))
    response = frame.client.post(PROOF_PATH, content=content, headers={"Content-Type": "application/json"})
    assert response.status_code == 200, response.text
    no_store_no_cookie(response)


def test_disabled_auth_refuses_capability_without_any_proof(frame, monkeypatch):
    monkeypatch.setenv("INKY_STUDIO_DISABLE_AUTH", "1")
    response = frame.client.post(PROOF_PATH, json={"v": 1, "nonce": NONCE})
    assert response.status_code == 409
    assert "proof" not in response.json()
    no_store_no_cookie(response)


@pytest.mark.parametrize("secret", [None, "custom-password", "a" * 15, "a" * 17, "é" * 16, "-" * 16, True, 1234])
def test_absent_or_non_generated_bootstrap_refuses_fixed_response(frame, monkeypatch, secret):
    service = frame.app.state.auth_service
    current = replace(service.credentials, bootstrap_password=secret)
    monkeypatch.setattr(service, "credentials", current)
    current.path.write_text(json.dumps(current.record()), encoding="utf-8")
    response = frame.client.post(PROOF_PATH, json={"v": 1, "nonce": NONCE})
    assert response.status_code == 503
    assert response.json() == UNAVAILABLE
    no_store_no_cookie(response)


@pytest.mark.parametrize("change", ["hash", "bootstrap", "extra", "bool_version", "bool_p", "float_n", "legacy", "corrupt", "missing"])
def test_durable_record_must_strictly_match_loaded_credentials(frame, change):
    current = frame.app.state.auth_service.credentials
    record = current.record()
    if change == "hash":
        record["hash"] = "ff" * 32
    elif change == "bootstrap":
        record["bootstrap_password"] = "Zyxwv9876543210A"
    elif change == "extra":
        record["unexpected"] = "private-marker"
    elif change == "bool_version":
        record["version"] = True
    elif change == "bool_p":
        record["p"] = True
    elif change == "float_n":
        record["n"] = float(record["n"])
    elif change == "legacy":
        record = {"password": current.bootstrap_password}
    if change == "missing":
        current.path.unlink()
    else:
        current.path.write_text("{private-marker" if change == "corrupt" else json.dumps(record), encoding="utf-8")
    previous = current.path.read_bytes() if current.path.exists() else None
    response = frame.client.post(PROOF_PATH, json={"v": 1, "nonce": NONCE})
    assert response.status_code == 503
    assert response.json() == UNAVAILABLE
    assert frame.app.state.auth_service.credentials is current
    assert (current.path.read_bytes() if current.path.exists() else None) == previous
    no_store_no_cookie(response)


@pytest.mark.parametrize("kind", ["missing", "bad_cert", "bad_uuid"])
def test_unavailable_or_invalid_loaded_identity_refuses_fixed_response(frame, monkeypatch, kind):
    current = frame.app.state.frame_identity
    replacement = None if kind == "missing" else SimpleNamespace(
        cert_pem=b"private-marker" if kind == "bad_cert" else current.cert_pem,
        frame_id="private-marker" if kind == "bad_uuid" else current.frame_id,
    )
    monkeypatch.setattr(frame.app.state, "frame_identity", replacement)
    response = frame.client.post(PROOF_PATH, json={"v": 1, "nonce": NONCE})
    assert response.status_code == 503
    assert response.json() == UNAVAILABLE
    no_store_no_cookie(response)


@pytest.mark.parametrize("url", [
    None, "", "http://frame.local:8443", "https://user:private@frame.local:8443",
    "https://frame.local/private", "https://frame.local?private=1", "https://frame.local#private",
    "https://frame.local:0", "https://frame.local:65536", "https://",
])
def test_missing_or_invalid_explicit_https_origin_refuses_fixed_response(frame, monkeypatch, url):
    if url is None:
        monkeypatch.delenv("INKY_STUDIO_PHOTO_ACCESS_URL")
    else:
        monkeypatch.setenv("INKY_STUDIO_PHOTO_ACCESS_URL", url)
    response = frame.client.post(PROOF_PATH, json={"v": 1, "nonce": NONCE}, headers={
        "X-Forwarded-Proto": "https", "X-Forwarded-Host": "trusted.local:8443",
        "Forwarded": "proto=https;host=trusted.local:8443",
    })
    assert response.status_code == 503
    assert response.json() == UNAVAILABLE
    no_store_no_cookie(response)


def snapshot(directory):
    return {
        str(path.relative_to(directory)): (
            path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns, path.stat().st_ino,
        )
        for path in directory.rglob("*") if path.is_file()
    }


def test_proof_has_no_storage_session_authority_private_key_or_secret_log_effects(frame, monkeypatch, caplog):
    from inky_web.provisioning import identity

    caplog.set_level("DEBUG")
    service = frame.app.state.auth_service
    previous_credentials = service.credentials
    secret = service.credentials.bootstrap_password
    session = frame.app.state.sessions.create()
    previous_sessions = dict(frame.app.state.sessions._sessions)
    previous_files = snapshot(frame.directory)
    for name in ("load_or_create_credentials", "reset_credentials", "_parse_record", "_new_credentials", "_write_credentials"):
        monkeypatch.setattr(auth, name, forbidden)
    monkeypatch.setattr(identity, "load_or_create_identity", forbidden)
    monkeypatch.setattr(frame.app.state.photo_access, "_connection", forbidden)
    for name in ("create", "invalidate", "invalidate_all", "invalidate_device", "principal", "validate"):
        monkeypatch.setattr(frame.app.state.sessions, name, forbidden)
    monkeypatch.setattr(auth.os, "chmod", forbidden)
    monkeypatch.setattr(auth.os, "fchmod", forbidden)
    response = frame.client.post(PROOF_PATH, json={"v": 1, "nonce": NONCE}, headers={
        "Cookie": f"{auth.COOKIE_NAME}={session}",
    })
    assert response.status_code == 200, response.text
    no_store_no_cookie(response)
    assert snapshot(frame.directory) == previous_files
    assert frame.app.state.sessions._sessions == previous_sessions
    assert not frame.app.state.sessions._principals
    assert frame.app.state.auth_service.credentials is previous_credentials
    assert secret not in response.text and secret not in caplog.text


def test_durable_read_holds_password_rotation_lock(frame, monkeypatch):
    service = frame.app.state.auth_service
    original = auth._read_record
    original_proof = legacy_tls_proof._proof
    observed = []

    def read(path):
        assert service._lock._is_owned()
        observed.append(path)
        return original(path)

    def proof(secret, nonce, identity):
        assert service._lock._is_owned()
        observed.append("proof")
        return original_proof(secret, nonce, identity)

    monkeypatch.setattr(auth, "_read_record", read)
    monkeypatch.setattr(legacy_tls_proof, "_proof", proof)
    response = frame.client.post(PROOF_PATH, json={"v": 1, "nonce": NONCE})
    assert response.status_code == 200
    assert observed == [service.credentials.path, "proof"]


def test_global_throttle_has_one_bounded_key_and_recovers_after_window(frame, monkeypatch):
    limiter = legacy_tls_proof.limiter
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(auth.time, "monotonic", lambda: clock.now)
    assert limiter._max == 30 and limiter._window == 60
    for index in range(30):
        response = frame.client.post(PROOF_PATH, json={"v": 1, "nonce": NONCE}, headers={
            "X-Forwarded-For": f"192.0.2.{index}", "Forwarded": f"for=192.0.2.{index}",
        })
        assert response.status_code == 200
    for index in range(3):
        response = frame.client.post(PROOF_PATH, json={"v": 1, "nonce": NONCE}, headers={
            "X-Forwarded-For": f"198.51.100.{index}",
        })
        assert response.status_code == 429
        assert "proof" not in response.json()
        no_store_no_cookie(response)
    assert set(limiter._attempts) == {"global"}
    assert len(limiter._attempts["global"]) == 30
    clock.now += 60
    response = frame.client.post(PROOF_PATH, json={"v": 1, "nonce": NONCE})
    assert response.status_code == 200
    assert len(limiter._attempts["global"]) == 1
    no_store_no_cookie(response)
