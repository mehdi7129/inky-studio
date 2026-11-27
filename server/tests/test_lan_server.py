"""Real PHOTO HTTPS listener and reboot flow, with inert display/radio ports."""
from __future__ import annotations

import http.client
import json
import os
import secrets
import signal
import socket
import sqlite3
import ssl
import subprocess
import sys
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image

from inky_web.provisioning.identity import load_or_create_identity
from tests.test_provisioning_listeners import CHILD, _events, _listeners, _wait_event

ORIGIN = "https://inky-fixture.local:8443"
_CREDENTIAL_WRITE = 'auth._write_credentials(auth._new_credentials(directory, "listener-test-password", bootstrap=stage == "welcome"))'
assert CHILD.count(_CREDENTIAL_WRITE) == CHILD.count("main.run()") == 1
LAN_CHILD = CHILD.replace(
    _CREDENTIAL_WRITE,
    'if not (directory / "credentials.json").exists():\n    ' + _CREDENTIAL_WRITE,
).replace("main.run()", r'''
from inky_web.photo_access import PhotoAccessStore

original_invite = PhotoAccessStore.begin_lan_bootstrap
def capture_invite(self, invitation_id, invitation_token, request_id):
    result = original_invite(self, invitation_id, invitation_token, request_id)
    (directory / "invitation.json").write_text(json.dumps({
        "invitation_id": invitation_id, "invitation_token": invitation_token,
    }))
    event("lan.invite")
    return result
PhotoAccessStore.begin_lan_bootstrap = capture_invite

main.run_lan()
''')


@contextmanager
def lan_frame(directory, **overrides):
    directory.mkdir(exist_ok=True)
    environment = {
        **os.environ, "INKY_STUDIO_DATA_DIR": str(directory),
        "INKY_STUDIO_DISABLE_AUTH": "0", "INKY_STUDIO_BLUETOOTH": "0",
        "INKY_STUDIO_DISPLAY_MODE": "mock", "INKY_STUDIO_PHOTO_ACCESS_URL": ORIGIN,
        "PYTHONUNBUFFERED": "1", **overrides,
    }
    with (directory / "process.log").open("w+") as output:
        process = subprocess.Popen(
            [sys.executable, "-c", LAN_CHILD], env=environment,
            cwd=Path(__file__).resolve().parents[1], stdout=output, stderr=output,
        )
        try:
            yield process
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def https_request(port, identity, path, *, method="GET", payload=None, cookie=None,
                  content_type="application/json"):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
    context.load_verify_locations(cadata=identity.cert_pem.decode())
    connection = http.client.HTTPSConnection("127.0.0.1", port, timeout=5, context=context)
    connection.sock = context.wrap_socket(
        socket.create_connection(("127.0.0.1", port), timeout=5),
        server_hostname=identity.server_name,
    )
    headers = {"Content-Type": content_type, "X-Inky-Direct-Auth": "1"}
    if cookie:
        headers["Cookie"] = cookie
    body = payload if isinstance(payload, bytes) else json.dumps(payload) if payload is not None else None
    try:
        assert connection.sock.version() == "TLSv1.3"
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        return response.status, dict(response.getheaders()), json.loads(raw) if raw else None
    finally:
        connection.close()


def test_photo_https_claim_upload_display_and_reboot_without_qr(tmp_path):
    directory = tmp_path / "lan"
    credential = {"device_id": str(uuid4()), "device_token": secrets.token_hex(32)}
    with lan_frame(directory) as process:
        ports = _listeners(process, directory, expected=1)
        assert set(ports) == {"https"}
        _wait_event(process, directory, "lan.invite")
        identity = load_or_create_identity(directory / "provisioning")
        invite = json.loads((directory / "invitation.json").read_text())
        claim = {**invite, **credential, "request_id": str(uuid4())}
        status, headers, result = https_request(
            ports["https"], identity, "/api/auth/invitations/claim", method="POST", payload=claim,
        )
        assert status == 200 and result["authenticated"] and result["role"] == "media"
        assert result["can_invite"] is True
        assert result["identity"] == {"frame_id": identity.frame_id, "spki_sha256": identity.spki_sha256}
        cookie = headers["set-cookie"].split(";", 1)[0]
        assert "Secure" in headers["set-cookie"]
        assert https_request(ports["https"], identity, "/api/auth/invitations/claim",
                             method="POST", payload=claim)[0] == 200
        shared = {"invitation_id": str(uuid4()), "invitation_token": secrets.token_hex(32),
                  "request_id": str(uuid4()), "ttl_seconds": 300}
        assert https_request(ports["https"], identity, "/api/auth/invitations", method="POST",
                             payload=shared, cookie=cookie)[0] == 200
        assert https_request(ports["https"], identity, "/api/settings", method="POST",
                             payload={"change_mode": "manual"}, cookie=cookie)[0] == 200
        png = BytesIO()
        Image.new("RGB", (800, 480), (200, 80, 30)).save(png, format="PNG")
        boundary = "inky-lan-test"
        multipart = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"photo.png\"\r\n"
                     "Content-Type: image/png\r\n\r\n").encode() + png.getvalue() + f"\r\n--{boundary}--\r\n".encode()
        status, _, uploaded = https_request(
            ports["https"], identity, "/api/queue", method="POST", payload=multipart,
            content_type=f"multipart/form-data; boundary={boundary}", cookie=cookie,
        )
        assert status == 201 and uploaded["photo"]["width"] == 800
        assert https_request(ports["https"], identity, "/api/display/next",
                             method="POST", cookie=cookie)[0] == 202
        _wait_event(process, directory, "history.record")
        assert len(https_request(ports["https"], identity, "/api/history", cookie=cookie)[2]) == 1
        with sqlite3.connect(directory / "photo-access/access.sqlite3") as conn:
            assert conn.execute("SELECT role FROM devices").fetchall() == [("media",)]
        names = [event["name"] for event in _events(directory)]
        assert names.index("listen") < names.index("lan.invite")
        assert "bluez.start" not in names
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=15) == 0, (directory / "process.log").read_text()
    with lan_frame(directory) as process:
        _wait_event(process, directory, "listen", count=2)
        port = _listeners(process, directory, expected=1)["https"]
        renewed = load_or_create_identity(directory / "provisioning")
        assert renewed.frame_id == identity.frame_id and renewed.spki_sha256 == identity.spki_sha256
        status, headers, result = https_request(
            port, renewed, "/api/auth/device-session", method="POST", payload=credential,
        )
        assert status == 200 and result["authenticated"] and result["role"] == "media"
        assert result["can_invite"] is True
        cookie = headers["set-cookie"].split(";", 1)[0]
        assert len(https_request(port, renewed, "/api/history", cookie=cookie)[2]) == 1
        names = [event["name"] for event in _events(directory)]
        assert names.count("lan.invite") == 1 and "bluez.start" not in names
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=15) == 0, (directory / "process.log").read_text()


def test_lan_bind_failure_never_displays_initial_qr(tmp_path):
    directory = tmp_path / "blocked"
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        with lan_frame(directory, BLOCKED_PROTOCOL="https", BLOCKED_PORT=str(occupied.getsockname()[1])) as process:
            assert process.wait(timeout=15) != 0
    names = [event["name"] for event in _events(directory)]
    assert "lan.invite" not in names and "bluez.start" not in names
    assert names.count("display.initialize") == names.count("display.shutdown") == 1


def test_signal_during_lan_welcome_drains_display_before_exit(tmp_path):
    directory = tmp_path / "drain"
    with lan_frame(directory, HOLD_STAGE="welcome") as process:
        _wait_event(process, directory, "display.show.begin")
        process.send_signal(signal.SIGTERM)
        _wait_event(process, directory, "display.drain")
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=0.1)
        assert not any(event["name"] == "display.shutdown" for event in _events(directory))
        (directory / "release").touch()
        assert process.wait(timeout=10) == 0, (directory / "process.log").read_text()
    names = [event["name"] for event in _events(directory)]
    assert names.index("display.show.end") < names.index("display.shutdown")
    assert "bluez.start" not in names


async def test_lan_factory_refusal_precedes_writer_and_hardware(monkeypatch):
    from inky_web import main
    from inky_web.provisioning import factory_runtime

    called = []
    def refuse(directory):
        raise factory_runtime.FactoryRuntimeError()
    monkeypatch.setattr(factory_runtime, "guard_legacy_command", refuse)
    monkeypatch.setattr(main, "main_writer_guard", lambda: called.append("writer"))
    with pytest.raises(factory_runtime.FactoryRuntimeError):
        await main.serve(with_https=True, lan_photo=True)
    assert called == []


@pytest.mark.parametrize("patch,https", [
    ({"INKY_STUDIO_DISABLE_AUTH": "1"}, True),
    ({"INKY_STUDIO_BLUETOOTH": "1"}, True),
    ({"INKY_STUDIO_PHOTO_ACCESS_URL": "http://inky-fixture.local:8000"}, True),
    ({}, False),
])
async def test_lan_rejects_invalid_policy_before_selector(monkeypatch, patch, https):
    from inky_web import main
    from inky_web.lan_runtime import LANRuntimeError

    monkeypatch.setenv("INKY_STUDIO_DISABLE_AUTH", "0")
    monkeypatch.setenv("INKY_STUDIO_BLUETOOTH", "0")
    monkeypatch.setenv("INKY_STUDIO_PHOTO_ACCESS_URL", ORIGIN)
    for key, value in patch.items():
        monkeypatch.setenv(key, value)
    async def not_reached():
        raise AssertionError("Selector/effects reached before invalid LAN policy was refused")
    monkeypatch.setattr(main, "_select_startup_runtime", not_reached)
    with pytest.raises(LANRuntimeError):
        await main._serve_admitted(with_https=https, lan_photo=True)


@pytest.mark.parametrize("hostname", ["inky-a1b2c3", "inky-a1b2c3.local"])
def test_default_origin_uses_os_hostname_not_frame_uuid(monkeypatch, hostname):
    from inky_web import main

    monkeypatch.delenv("INKY_STUDIO_PHOTO_ACCESS_URL", raising=False)
    monkeypatch.setattr(main.socket, "gethostname", lambda: hostname)
    assert main._lan_photo_origin() == "https://inky-a1b2c3.local:8443"


@pytest.mark.parametrize("hostname", ["", "../bad", "inky:8443", "Upper", "bad_name"])
def test_invalid_os_hostname_cannot_create_qr_authority(monkeypatch, hostname):
    from inky_web import main
    from inky_web.lan_runtime import LANRuntimeError

    monkeypatch.delenv("INKY_STUDIO_PHOTO_ACCESS_URL", raising=False)
    monkeypatch.setattr(main.socket, "gethostname", lambda: hostname)
    with pytest.raises(LANRuntimeError):
        main._lan_photo_origin()


def test_explicit_empty_origin_is_not_replaced_by_hostname(monkeypatch):
    from inky_web import main
    from inky_web.lan_runtime import LANRuntimeError

    monkeypatch.setenv("INKY_STUDIO_PHOTO_ACCESS_URL", "")
    with pytest.raises(LANRuntimeError):
        main._lan_photo_origin()


def test_real_https_photo_delegation_three_devices_and_restart(tmp_path):
    directory = tmp_path / "delegation"
    credentials = [{"device_id": str(uuid4()), "device_token": secrets.token_hex(32)} for _ in range(3)]
    with lan_frame(directory) as process:
        port = _listeners(process, directory, expected=1)["https"]
        _wait_event(process, directory, "lan.invite")
        identity = load_or_create_identity(directory / "provisioning")
        invite = json.loads((directory / "invitation.json").read_text())
        cookies = []
        for credential in credentials:
            status, headers, reply = https_request(
                port, identity, "/api/auth/invitations/claim", method="POST",
                payload={**invite, **credential, "request_id": str(uuid4())},
            )
            assert status == 200 and reply["role"] == "media" and reply["can_invite"] is True
            assert credential["device_token"] not in json.dumps(reply)
            cookie = headers["set-cookie"].split(";", 1)[0]
            cookies.append(cookie)
            invite = {"invitation_id": str(uuid4()), "invitation_token": secrets.token_hex(32),
                      "request_id": str(uuid4()), "ttl_seconds": 300}
            status, _, reply = https_request(
                port, identity, "/api/auth/invitations", method="POST", payload=invite, cookie=cookie,
            )
            assert status == 200 and reply["role"] == "media"
            assert invite["invitation_token"] not in json.dumps(reply)
            invite = {key: invite[key] for key in ("invitation_id", "invitation_token")}
            for method, path in (("GET", "/api/auth/devices"), ("POST", "/api/auth/password"),
                                 ("GET", "/api/provisioning/capabilities"),
                                 ("POST", "/api/system/update"), ("GET", "/api/unknown-admin")):
                assert https_request(port, identity, path, method=method, cookie=cookie)[0] == 403
        assert https_request(
            port, identity, f"/api/auth/invitations/{invite['invitation_id']}",
            method="DELETE", cookie=cookies[0],
        )[0] == 403
        assert https_request(
            port, identity, f"/api/auth/invitations/{invite['invitation_id']}",
            method="DELETE", cookie=cookies[-1],
        )[0] == 200
        assert https_request(
            port, identity, "/api/auth/invitations/claim", method="POST",
            payload={**invite, "device_id": str(uuid4()), "device_token": secrets.token_hex(32),
                     "request_id": str(uuid4())},
        )[0] == 401
        # The newly invited second device can perform the existing photo action.
        png = BytesIO()
        Image.new("RGB", (800, 480), (10, 80, 120)).save(png, format="PNG")
        boundary = "inky-lan-delegation-test"
        multipart = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"photo.png\"\r\n"
                     "Content-Type: image/png\r\n\r\n").encode() + png.getvalue() + f"\r\n--{boundary}--\r\n".encode()
        assert https_request(
            port, identity, "/api/queue", method="POST", payload=multipart, cookie=cookies[1],
            content_type=f"multipart/form-data; boundary={boundary}",
        )[0] == 201
        assert https_request(port, identity, "/api/settings", method="POST",
                             payload={"change_mode": "manual"}, cookie=cookies[1])[0] == 200
        with sqlite3.connect(directory / "photo-access/access.sqlite3") as conn:
            assert conn.execute("SELECT role FROM devices").fetchall() == [("media",)] * 3
            assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=15) == 0
    with lan_frame(directory) as process:
        _wait_event(process, directory, "listen", count=2)
        port = _listeners(process, directory, expected=1)["https"]
        renewed = load_or_create_identity(directory / "provisioning")
        assert renewed.frame_id == identity.frame_id and renewed.spki_sha256 == identity.spki_sha256
        for credential in credentials:
            status, _, reply = https_request(
                port, renewed, "/api/auth/device-session", method="POST", payload=credential,
            )
            assert status == 200 and reply["role"] == "media" and reply["can_invite"] is True
        assert [event["name"] for event in _events(directory)].count("lan.invite") == 1
        assert https_request(port, renewed, "/api/auth/invitations/claim", method="POST", payload={
            **invite, "device_id": str(uuid4()), "device_token": secrets.token_hex(32),
            "request_id": str(uuid4()),
        })[0] == 401
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=15) == 0
