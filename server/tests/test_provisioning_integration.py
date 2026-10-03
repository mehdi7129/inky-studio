import asyncio
import secrets
import threading
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from inky_web import auth
from inky_web.inky.display import DisplayController
from inky_web.provisioning.network import NetworkUnavailable
from inky_web.provisioning.ownership import OwnershipError
from inky_web.provisioning.runtime import ProvisioningRuntime


async def test_shutdown_keeps_qr_marker_without_refresh_and_cancels_network(inky_env, monkeypatch):
    credentials = auth._new_credentials(inky_env, "test-stop-password")
    auth._write_credentials(credentials)
    display = DisplayController(mode="mock")
    runtime = ProvisioningRuntime(inky_env / "provisioning",
                                  auth.CredentialService(credentials, auth.SessionStore()), display)
    marker = runtime.directory / ".adoption-screen"
    marker.touch()
    display.reserve("bluetooth-adoption")
    runtime.owners.open_window()
    calls = []

    async def stop_bluez():
        calls.append("ble-stop")

    def no_restore(*args):
        pytest.fail("Shutdown must not start a new display refresh")

    original_close = runtime.owners.close_window

    def close_window():
        calls.append("window-close")
        original_close()

    monkeypatch.setattr(runtime.bluez, "stop", stop_bluez)
    monkeypatch.setattr(runtime.network, "cancel_pending_sync", lambda: calls.append("network-cancel"))
    monkeypatch.setattr(runtime.owners, "close_window", close_window)
    monkeypatch.setattr("inky_web.provisioning.screen.restore_if_reserved", no_restore)
    display.begin_shutdown()
    await runtime.stop()
    assert calls[:3] == ["ble-stop", "network-cancel", "window-close"]
    assert marker.is_file()
    assert not display.reserved


@pytest.fixture
def secured_frame(inky_env, monkeypatch):
    from inky_web.main import app

    monkeypatch.setenv("INKY_STUDIO_DISABLE_AUTH", "0")
    monkeypatch.setenv("INKY_STUDIO_BLUETOOTH", "1")
    auth._write_credentials(auth._new_credentials(inky_env, "existing-password"))

    async def without_radio(self):
        self.available = True

    monkeypatch.setattr(ProvisioningRuntime, "start", without_radio)
    with TestClient(app, base_url="https://testserver") as client:
        assert client.post("/api/auth/login", json={"password": "existing-password"}).status_code == 200
        monkeypatch.setattr(app.state.provisioning.network, "cancel_pending_sync", lambda: None)
        yield client, app.state.provisioning


def adopt(runtime):
    qr = runtime.owners.open_window()
    owner, token = str(uuid4()), secrets.token_hex(32)
    runtime.owners.claim(qr, owner, token, str(uuid4()), runtime.epoch())
    return owner, token


def test_password_epoch_preserves_authenticated_caller_and_revokes_other(secured_frame):
    client, runtime = secured_frame
    caller, other = adopt(runtime), adopt(runtime)
    response = client.post("/api/auth/password", headers={
        "X-Inky-Owner-ID": caller[0], "X-Inky-Owner-Token": caller[1],
    }, json={"current_password": "existing-password", "new_password": "replacement-password"})
    assert response.status_code == 200
    assert runtime.authorize(*caller).owner_id == caller[0]
    with pytest.raises(OwnershipError):
        runtime.authorize(*other)
    assert client.post("/api/auth/login", json={"password": "replacement-password"}).status_code == 200
    assert client.post("/api/auth/login", json={"password": "existing-password"}).status_code == 401


def test_legacy_rotation_revokes_all_owners_and_fake_owner_does_not_rotate(secured_frame):
    client, runtime = secured_frame
    owner = adopt(runtime)
    body = {"current_password": "existing-password", "new_password": "replacement-password"}
    response = client.post("/api/auth/password", headers={
        "X-Inky-Owner-ID": owner[0], "X-Inky-Owner-Token": secrets.token_hex(32),
    }, json=body)
    assert response.status_code == 401
    runtime.authorize(*owner)
    assert client.post("/api/auth/password", json=body).status_code == 200
    with pytest.raises(OwnershipError):
        runtime.authorize(*owner)


def test_failed_password_commit_keeps_old_owner_authorized(secured_frame, monkeypatch):
    client, runtime = secured_frame
    owner = adopt(runtime)

    def failure(_):
        raise auth.CredentialStorageError(committed=False)

    monkeypatch.setattr(auth, "_write_credentials", failure)
    response = client.post("/api/auth/password", json={
        "current_password": "existing-password", "new_password": "replacement-password",
    })
    assert response.status_code == 503
    runtime.authorize(*owner)


def test_rotation_cancels_wifi_before_password_commit_and_rejects_failed_cancel(secured_frame, monkeypatch):
    client, runtime = secured_frame
    owner = adopt(runtime)
    body = {"current_password": "existing-password", "new_password": "replacement-password"}
    writes = []
    original_write = auth._write_credentials

    def write(credentials):
        writes.append("password")
        original_write(credentials)

    def cancel_failed():
        raise NetworkUnavailable("network_unavailable")

    monkeypatch.setattr(auth, "_write_credentials", write)
    monkeypatch.setattr(runtime.network, "cancel_pending_sync", cancel_failed)
    assert client.post("/api/auth/password", json=body).status_code == 503
    assert not writes
    runtime.authorize(*owner)
    monkeypatch.setattr(runtime.network, "cancel_pending_sync", lambda: writes.append("cancel"))
    assert client.post("/api/auth/password", json=body).status_code == 200
    assert writes == ["cancel", "password"]


def test_qr_remains_physical_and_display_reservation_protects_it(secured_frame, monkeypatch):
    client, runtime = secured_frame
    payloads = []

    def show(display, directory, payload):
        payloads.append(payload)
        display.reserve("bluetooth-adoption")

    monkeypatch.setattr("inky_web.provisioning.screen.show", show)
    response = client.post("/api/provisioning/adoption/window")
    assert response.status_code == 200
    assert set(response.json()) == {"frame_id", "expires_in"}
    assert len(payloads) == 1
    assert client.post("/api/display/next").status_code == 409
    assert client.post("/api/display/previous").status_code == 409
    assert client.delete("/api/provisioning/adoption/window").status_code == 200
    assert not runtime.display.reserved


def test_confirmation_rejects_http_and_cookie_alone(secured_frame):
    client, runtime = secured_frame
    owner = adopt(runtime)
    body = {"transaction_id": str(uuid4())}
    assert client.post("/api/provisioning/wifi/confirm", json=body).status_code == 401
    headers = {"X-Inky-Owner-ID": owner[0], "X-Inky-Owner-Token": owner[1]}
    assert client.post("http://testserver/api/provisioning/wifi/confirm", headers=headers, json=body).status_code == 403
    response = client.post("/api/provisioning/wifi/confirm", headers=headers,
                           json={"transaction_id": body["transaction_id"], "password": "must-not-echo"})
    assert response.status_code == 422
    assert "must-not-echo" not in response.text


async def test_protocol_rejects_malformed_payload_and_invalid_owner(secured_frame):
    _, runtime = secured_frame
    owner = adopt(runtime)
    message = {"v": 1, "id": str(uuid4()), "op": "status", "owner_id": owner[0], "owner_token": owner[1]}
    assert (await runtime.command(message))["ok"]
    response = await runtime.command({**message, "password": "must-not-echo"})
    assert response["error"] == "invalid_request"
    assert "must-not-echo" not in str(response)
    runtime.owners.revoke(owner[0])
    assert not (await runtime.command(message))["ok"]


async def test_cancelled_adoption_drains_physical_refresh_and_restores(secured_frame, monkeypatch):
    _, runtime = secured_frame
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    completed = []

    def delayed_show(display, directory, payload):
        display.reserve("bluetooth-adoption")
        loop.call_soon_threadsafe(started.set)
        assert release.wait(3)
        completed.append("show")

    def restore(display, directory):
        completed.append("restore")
        display.release("bluetooth-adoption")

    monkeypatch.setattr("inky_web.provisioning.screen.show", delayed_show)
    monkeypatch.setattr("inky_web.provisioning.screen.restore", restore)
    task = asyncio.create_task(runtime.begin_adoption())
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert completed == ["show", "restore"]
    assert not runtime.display.reserved
    assert runtime._window_task is None


async def test_failed_bluetooth_restart_retries_after_certificate_is_already_renewed(secured_frame, monkeypatch):
    from inky_web.provisioning.bluez import BlueZServer
    from inky_web.provisioning.identity import Identity

    _, runtime = secured_frame
    renewed = runtime.identity.refresh_certificate_if_needed(runtime.identity.issued_at + timedelta(days=310))
    assert renewed.cert_der != runtime.identity.cert_der
    monkeypatch.setattr(Identity, "refresh_certificate_if_needed", lambda _: renewed)
    calls = []

    async def flaky_start(self):
        calls.append("start")
        if len(calls) == 1:
            raise OSError("synthetic transient radio failure")

    monkeypatch.setattr(BlueZServer, "start", flaky_start)
    with pytest.raises(OSError):
        await runtime._maintain_certificate()
    assert not runtime.available
    assert runtime.identity.cert_der == renewed.cert_der
    await runtime._maintain_certificate()
    assert runtime.available
    assert calls == ["start", "start"]
