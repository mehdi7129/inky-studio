"""Standalone helper qualification with a fake NM adapter; no D-Bus or radio."""
from __future__ import annotations

import importlib.util
import json
import secrets
import socket
import stat
import sys
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

SPEC = importlib.util.spec_from_file_location("inky_network_helper", Path(__file__).resolve().parents[2] / "scripts" / "inky-network-helper.py")
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


class PowerLoss(BaseException):
    pass


class FakeNM:
    device = "/org/freedesktop/NetworkManager/Devices/2"

    def __init__(self):
        self.previous = str(uuid4())
        self.current = {"uuid": self.previous, "active_path": "/active/old", "activated": True,
                        "failed": False, "addresses": ["192.168.1.2"]}
        self.checkpoints = set()
        self.profiles = {}
        self.calls = []
        self.failure = None
        self.service_instance = "boot-id:nm-owner"
        self.granted = {action: "yes" for action in helper.PERMISSIONS}
        self.journal = None
        self.next_checkpoint = 1

    def called(self, name, required_phase=None):
        if required_phase:
            assert self.journal.active()["phase"] == required_phase
        self.calls.append(name)
        if self.failure == name:
            self.failure = None
            raise RuntimeError("simulated D-Bus error with sensitive details")

    def permissions(self):
        return self.granted

    def instance(self):
        return self.service_instance

    def snapshot(self):
        self.called("snapshot")
        return self.current.copy()

    def scan(self):
        self.called("scan")
        return {"networks": [{"ssid": "Synthetic", "security": "wpa2", "strength": 80}]}

    def checkpoint_create(self):
        self.called("checkpoint_create", "prepared")
        path = f"/org/freedesktop/NetworkManager/Checkpoint/{self.next_checkpoint}"
        self.next_checkpoint += 1
        self.checkpoints.add(path)
        return path

    def checkpoint_exists(self, path):
        self.called("checkpoint_exists")
        return path in self.checkpoints

    def checkpoint_rollback(self, path):
        self.called("checkpoint_rollback", "rolling_back")
        self.checkpoints.remove(path)
        self.current = {"uuid": self.previous, "active_path": "/active/old", "activated": True,
                        "failed": False, "addresses": ["192.168.1.2"]}

    def checkpoint_destroy(self, path):
        self.called("checkpoint_destroy", "commit_ready")
        self.checkpoints.remove(path)

    def activate_new(self, row, ssid, password):
        self.called("activate_new", "activating")
        assert ssid and password
        self.profiles[row["profile_uuid"]] = {"saved": False, "bound": True}
        self.current = {"uuid": row["profile_uuid"], "active_path": "/active/bound", "activated": False,
                        "failed": False, "addresses": []}

    def finish_activation(self):
        self.current.update(activated=True, addresses=["192.168.2.2"])

    def persist_profile(self, row, password):
        assert password
        self.profiles[row["profile_uuid"]]["saved"] = True
        self.called("persist_profile", "saving")

    def activate_persistent(self, row):
        self.called("activate_persistent", "detaching")
        self.profiles[row["profile_uuid"]]["bound"] = False
        self.current.update(active_path="/active/unbound", activated=False, addresses=[])
        return "/active/unbound"

    def delete_profile(self, row):
        self.called("delete_profile", "rolling_back")
        self.profiles.pop(row["profile_uuid"], None)
        if self.current["uuid"] == row["profile_uuid"]:
            self.current.update(uuid=None, activated=False, addresses=[])

    def restore_previous(self, previous_uuid):
        self.called("restore_previous", "rolling_back")
        assert previous_uuid == self.previous
        self.current.update(uuid=previous_uuid, activated=True, addresses=["192.168.1.2"])


@pytest.fixture
def state(tmp_path):
    journal = helper.Journal(tmp_path / "network")
    nm, clock = FakeNM(), [1000.0]
    nm.journal = journal
    engine = helper.Provisioner(nm, journal, monotonic=lambda: clock[0])
    return engine, nm, clock


def begin_request():
    return {"op": "begin", "id": str(uuid4()), "owner_id": str(uuid4()),
            "ssid": "Synthetic network", "security": "wpa2", "password": "Synthetic-password-123"}


def operation(request, name):
    return {key: request[key] for key in ("id", "owner_id")} | {"op": name}


def error(code, call):
    with pytest.raises(helper.HelperError) as failure:
        call()
    assert failure.value.code == code
    assert "sensitive" not in str(failure.value)


def make_ready(state, request):
    engine, nm, _ = state
    assert engine.handle(request)["state"] == "connecting"
    nm.finish_activation()
    assert engine.handle(operation(request, "status"))["state"] == "awaiting_confirmation"


def test_json_bounds_schema_and_duplicate_keys():
    request = begin_request()
    assert helper.parse_request(json.dumps(request).encode() + b"\n") == request
    invalid = [b"{}", b"[]\n", b'{"op":"scan","op":"scan"}\n', b"x" * 8193 + b"\n", b'{"op":NaN}\n']
    for raw in invalid:
        error("invalid_request", lambda raw=raw: helper.parse_request(raw))
    for mutation in ({"unknown": True}, {"op": "shell"}, {"owner_id": "invalid"}, {"security": "open"},
                     {"ssid": "é" * 17}, {"password": "g" * 64}, {"password": "tiny"}, {"ssid": "\ud800"}):
        error("invalid_request", lambda mutation=mutation: helper.validate_request(request | mutation))
    helper.validate_request(request | {"password": "f" * 64})


def test_begin_returns_without_waiting_for_dhcp_and_persists_no_wifi_secret(state):
    engine, nm, _ = state
    request = begin_request()
    result = engine.handle(request)
    assert result == {"id": request["id"], "state": "connecting", "addresses": [], "remaining_seconds": 180}
    assert not nm.current["activated"]
    assert len(nm.profiles) == 1
    for path in engine.journal.directory.iterdir():
        assert request["password"].encode() not in path.read_bytes()
        assert request["ssid"].encode() not in path.read_bytes()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(engine.journal.directory.stat().st_mode) == 0o700


def test_begin_same_intent_replays_and_conflict_is_rejected(state):
    engine, nm, _ = state
    request = begin_request()
    result = engine.handle(request)
    assert engine.handle(request) == result
    assert nm.calls.count("activate_new") == 1
    error("conflict", lambda: engine.handle(request | {"password": "Different-password"}))
    error("not_found", lambda: engine.handle(request | {"owner_id": str(uuid4())}))
    error("busy", lambda: engine.handle(begin_request()))


def test_owner_can_only_read_or_mutate_own_transaction(state):
    engine, _, _ = state
    request = begin_request()
    engine.handle(request)
    for name in ("status", "cancel", "confirm"):
        error("not_found", lambda name=name: engine.handle(operation(request, name) | {"owner_id": str(uuid4())}))


def test_confirm_requires_live_checkpoint_and_real_current_activation(state):
    engine, nm, _ = state
    request = begin_request()
    engine.handle(request)
    error("not_ready", lambda: engine.handle(operation(request, "confirm")))
    nm.finish_activation()
    nm.current["uuid"] = str(uuid4())
    error("not_ready", lambda: engine.handle(operation(request, "confirm")))
    assert "persist_profile" not in nm.calls


def test_commit_waits_for_unbound_activation_then_survives_restart(state):
    engine, nm, clock = state
    request = begin_request()
    make_ready(state, request)
    result = engine.handle(operation(request, "confirm"))
    assert result["state"] == "awaiting_confirmation"
    assert "checkpoint_destroy" not in nm.calls
    nm.finish_activation()
    assert engine.handle(operation(request, "status"))["state"] == "committed"
    profile = next(iter(nm.profiles.values()))
    assert profile == {"saved": True, "bound": False}
    assert engine._password is None
    nm.journal = helper.Journal(engine.journal.directory)
    reopened = helper.Provisioner(nm, nm.journal, monotonic=lambda: clock[0])
    assert reopened.handle(operation(request, "status"))["state"] == "committed"
    assert len(nm.profiles) == 1 and "delete_profile" not in nm.calls
    assert reopened.handle(request)["state"] == "committed"


def test_different_active_path_cannot_finalize_old_bound_connection(state):
    engine, nm, _ = state
    request = begin_request()
    make_ready(state, request)
    engine.handle(operation(request, "confirm"))
    nm.finish_activation()
    nm.current["active_path"] = "/active/bound"
    assert engine.handle(operation(request, "status"))["state"] == "awaiting_confirmation"
    assert "checkpoint_destroy" not in nm.calls


def test_cancel_and_timeout_target_only_created_profile(state):
    engine, nm, clock = state
    request = begin_request()
    engine.handle(request)
    assert engine.handle(operation(request, "cancel"))["state"] == "rolled_back"
    assert not nm.profiles and nm.current["uuid"] == nm.previous
    request2 = begin_request()
    engine.handle(request2)
    clock[0] += 180
    engine.tick()
    assert engine.handle(operation(request2, "status"))["state"] == "rolled_back"
    assert not nm.profiles and not nm.checkpoints


def test_missing_checkpoint_never_commits(state):
    engine, nm, _ = state
    request = begin_request()
    make_ready(state, request)
    nm.checkpoints.clear()
    assert engine.handle(operation(request, "confirm"))["state"] == "rolled_back"
    assert "persist_profile" not in nm.calls


def test_failure_after_save_deletes_new_disk_profile_and_restores_old(state):
    engine, nm, _ = state
    request = begin_request()
    make_ready(state, request)
    nm.failure = "persist_profile"
    error("network_failed", lambda: engine.handle(operation(request, "confirm")))
    assert not nm.profiles and nm.current["uuid"] == nm.previous
    assert engine.handle(operation(request, "status"))["state"] == "failed"
    assert engine._password is None


def test_failed_rollback_blocks_new_switch_until_retry_succeeds(state):
    engine, nm, _ = state
    request = begin_request()
    engine.handle(request)
    nm.failure = "delete_profile"
    error("network_failed", lambda: engine.handle(operation(request, "cancel")))
    assert engine.journal.active()["phase"] == "rolling_back"
    engine.tick()
    assert engine.journal.active() is None and not nm.profiles


@pytest.mark.parametrize("phase", ["prepared", "checkpoint", "activating", "waiting", "saving", "detaching", "commit_ready"])
def test_power_loss_at_every_durable_phase_rolls_back_on_restart(state, monkeypatch, phase):
    engine, nm, clock = state
    request = begin_request()
    original_put = engine.journal.put

    def crash_after_write(row):
        original_put(row)
        if row["phase"] == phase:
            raise PowerLoss()

    monkeypatch.setattr(engine.journal, "put", crash_after_write)
    with pytest.raises(PowerLoss):
        engine.handle(request)
        nm.finish_activation()
        engine.handle(operation(request, "confirm"))
        nm.finish_activation()
        engine.tick()
    nm.journal = helper.Journal(engine.journal.directory)
    recovered = helper.Provisioner(nm, nm.journal, monotonic=lambda: clock[0])
    assert recovered.handle(operation(request, "status"))["state"] == "rolled_back"
    assert not nm.profiles and nm.current["uuid"] == nm.previous


def test_power_loss_after_checkpoint_destroy_before_final_journal(state, monkeypatch):
    engine, nm, clock = state
    request = begin_request()
    make_ready(state, request)
    engine.handle(operation(request, "confirm"))
    nm.finish_activation()
    destroy = nm.checkpoint_destroy

    def crash(path):
        destroy(path)
        raise PowerLoss()

    monkeypatch.setattr(nm, "checkpoint_destroy", crash)
    with pytest.raises(PowerLoss):
        engine.tick()
    nm.journal = helper.Journal(engine.journal.directory)
    recovered = helper.Provisioner(nm, nm.journal, monotonic=lambda: clock[0])
    assert recovered.handle(operation(request, "status"))["state"] == "rolled_back"
    assert nm.current["uuid"] == nm.previous and not nm.profiles


def test_reboot_never_reuses_an_old_checkpoint_object_path(state):
    engine, nm, clock = state
    request = begin_request()
    engine.handle(request)
    nm.service_instance = "different-boot:another-nm-owner"
    calls_before = nm.calls.count("checkpoint_rollback")
    nm.journal = helper.Journal(engine.journal.directory)
    recovered = helper.Provisioner(nm, nm.journal, monotonic=lambda: clock[0])
    assert nm.calls.count("checkpoint_rollback") == calls_before
    assert recovered.handle(operation(request, "status"))["state"] == "rolled_back"
    assert not nm.profiles


def test_recovery_does_not_replace_an_unrelated_manual_connection(state):
    engine, nm, _ = state
    request = begin_request()
    engine.handle(request)
    nm.checkpoints.clear()
    unrelated = str(uuid4())
    nm.current["uuid"] = unrelated
    engine.tick()
    assert nm.current["uuid"] == unrelated
    assert "restore_previous" not in nm.calls


def test_journal_write_failure_prevents_first_nm_mutation(state, monkeypatch):
    engine, nm, _ = state

    def fail(*_):
        raise OSError("disk full")

    monkeypatch.setattr(helper, "atomic_write", fail)
    error("not_ready", lambda: engine.handle(begin_request()))
    assert "checkpoint_create" not in nm.calls and "activate_new" not in nm.calls
    assert not engine.ready


def test_permissions_checked_as_real_adapter_identity_before_mutations(tmp_path):
    nm = FakeNM()
    nm.granted[helper.PERMISSIONS[0]] = "auth"
    error("permission_denied", lambda: helper.Provisioner(nm, helper.Journal(tmp_path)))
    assert not nm.calls


def test_corrupt_journal_never_resets_or_reaches_nm(tmp_path):
    helper.Journal(tmp_path)
    path = tmp_path / "journal.json"
    path.write_bytes(b"corrupt private journal")
    error("not_ready", lambda: helper.Journal(tmp_path))
    assert path.read_bytes() == b"corrupt private journal"


def test_hmac_intent_is_keyed_and_history_bounded(tmp_path, monkeypatch):
    left, right = helper.Journal(tmp_path / "a"), helper.Journal(tmp_path / "b")
    request = begin_request()
    assert left.intention(request) != right.intention(request)
    monkeypatch.setattr(helper, "HISTORY_LIMIT", 2)
    nm = FakeNM()
    nm.journal = left
    engine = helper.Provisioner(nm, left)
    for _ in range(3):
        request = begin_request()
        engine.handle(request)
        engine.handle(operation(request, "cancel"))
    assert len(left.records) == 2


def test_same_activation_path_does_not_prove_binding_was_removed(state, monkeypatch):
    engine, nm, _ = state
    request = begin_request()
    make_ready(state, request)
    monkeypatch.setattr(nm, "activate_persistent", lambda _: "/active/bound")
    error("network_failed", lambda: engine.handle(operation(request, "confirm")))
    assert not nm.profiles and nm.current["uuid"] == nm.previous


def typed_adapter():
    adapter = helper.NetworkManagerAdapter.__new__(helper.NetworkManagerAdapter)
    adapter.device = FakeNM.device
    adapter.dbus = SimpleNamespace(
        Dictionary=lambda value, signature: dict(value), Array=lambda value, signature: list(value),
        ObjectPath=str, UInt32=int, Boolean=bool, ByteArray=bytes,
    )
    return adapter


def test_adapter_exact_checkpoint_and_memory_profile_contract():
    adapter = typed_adapter()
    calls = {}

    def checkpoint(*args, **kwargs):
        calls["checkpoint"] = (args, kwargs)
        return "/org/freedesktop/NetworkManager/Checkpoint/1"

    def activate(*args, **kwargs):
        calls["activate"] = (args, kwargs)

    adapter.manager = SimpleNamespace(CheckpointCreate=checkpoint, AddAndActivateConnection2=activate)
    adapter.checkpoint_create()
    args, _ = calls["checkpoint"]
    assert args == ([adapter.device], 180, 0)
    row = {"id": str(uuid4()), "profile_uuid": str(uuid4())}
    adapter.activate_new(row, "Banc synthétique", "Synthetic-password")
    args, _ = calls["activate"]
    settings, device, specific, options = args
    assert device == adapter.device and specific == "/"
    assert options == {"persist": "memory", "bind-activation": "dbus-client"}
    assert settings["connection"]["autoconnect"] is False
    assert settings["connection"]["id"] == "inky-provisioning-" + row["id"]
    assert settings["802-11-wireless"]["ssid"] == "Banc synthétique".encode()
    assert settings["802-11-wireless"]["band"] == "bg"
    assert settings["802-11-wireless-security"]["proto"] == ["rsn"]
    assert settings["802-11-wireless-security"]["psk-flags"] == 0


def test_adapter_save_preserves_only_current_in_memory_wifi_secret():
    adapter = typed_adapter()
    calls = []
    settings = {"connection": {"autoconnect": False}, "802-11-wireless-security": {"key-mgmt": "wpa-psk"}}
    connection = SimpleNamespace(UpdateUnsaved=lambda values, **_: calls.append(("update", values.copy())),
                                 Save=lambda **_: calls.append(("save", None)))
    adapter._profile = lambda *_: ("/settings/1", connection, settings)
    adapter.persist_profile({"profile_uuid": str(uuid4()), "id": str(uuid4())}, "Only-the-new-secret")
    assert [name for name, _ in calls] == ["update", "save"]
    assert calls[0][1]["connection"]["autoconnect"] is True
    assert calls[0][1]["802-11-wireless-security"]["psk"] == "Only-the-new-secret"


def test_socket_returns_bounded_fixed_errors_without_exception_details(tmp_path):
    class FailingEngine:
        def handle(self, request):
            raise RuntimeError("private-password-do-not-publish")

        def tick(self):
            pass

    # macOS Unix sockets have a short path limit; use a small /tmp directory.
    import tempfile

    with tempfile.TemporaryDirectory(prefix="inky-helper-", dir="/tmp") as directory:
        path = Path(directory) / "socket"
        with helper.Server(path, FailingEngine()) as server:
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(2)
                client.connect(str(path))
                client.sendall(json.dumps({"op": "scan", "owner_id": str(uuid4())}).encode() + b"\n")
                response = client.recv(16385)
            thread.join(timeout=2)
            assert not thread.is_alive()
    assert response == b'{"ok":false,"error":"network_failed"}\n'
    assert len(response) <= helper.RESPONSE_LIMIT


def test_private_cancellation_schema_does_not_require_transaction_id():
    helper.validate_request({"op": "cancel_pending"})
    helper.validate_request({"op": "cancel_owner", "owner_id": str(uuid4())})
    for request in ({"op": "cancel_pending", "owner_id": str(uuid4())},
                    {"op": "cancel_owner"},
                    {"op": "cancel_owner", "owner_id": "invalid"},
                    {"op": "cancel_pending", "id": str(uuid4())}):
        error("invalid_request", lambda request=request: helper.validate_request(request))


def test_private_cancel_pending_covers_lost_begin_response(state):
    engine, nm, _ = state
    engine.handle(begin_request())  # The application never received the result.
    assert engine.handle({"op": "cancel_pending"}) == {"cancelled": True}
    assert engine.handle({"op": "cancel_pending"}) == {"cancelled": False}
    assert not nm.profiles and nm.current["uuid"] == nm.previous


@pytest.mark.parametrize("phase", ["detaching", "commit_ready"])
@pytest.mark.parametrize("operation_name", ["cancel_pending", "cancel_owner"])
def test_private_cancel_precedes_tick_and_blocks_post_revocation_commit(state, monkeypatch, phase, operation_name):
    engine, nm, _ = state
    request = begin_request()
    make_ready(state, request)
    engine.handle(operation(request, "confirm"))
    nm.finish_activation()
    # The watchdog would commit immediately if handle() called tick first.
    engine._put(engine.journal.get(request["id"]), phase=phase)

    def forbidden_tick():
        pytest.fail("private cancellation must precede the watchdog")

    monkeypatch.setattr(engine, "tick", forbidden_tick)
    cancellation = {"op": operation_name}
    if operation_name == "cancel_owner":
        cancellation["owner_id"] = request["owner_id"]
    assert engine.handle(cancellation) == {"cancelled": True}
    assert engine.journal.get(request["id"])["state"] == "rolled_back"
    assert not nm.profiles and nm.current["uuid"] == nm.previous
    assert "checkpoint_destroy" not in nm.calls


def test_private_cancel_owner_only_affects_matching_owner_without_ticking(state, monkeypatch):
    engine, nm, _ = state
    request = begin_request()
    make_ready(state, request)
    engine.handle(operation(request, "confirm"))
    nm.finish_activation()

    def forbidden_tick():
        pytest.fail("an unrelated private cancellation must not advance commit")

    monkeypatch.setattr(engine, "tick", forbidden_tick)
    assert engine.handle({"op": "cancel_owner", "owner_id": str(uuid4())}) == {"cancelled": False}
    assert engine.journal.active()["phase"] == "detaching"
    assert len(nm.profiles) == 1


def test_private_cancellation_preserves_already_committed_profile(state):
    engine, nm, _ = state
    request = begin_request()
    make_ready(state, request)
    engine.handle(operation(request, "confirm"))
    nm.finish_activation()
    assert engine.handle(operation(request, "status"))["state"] == "committed"
    assert engine.handle({"op": "cancel_pending"}) == {"cancelled": False}
    assert engine.handle({"op": "cancel_owner", "owner_id": request["owner_id"]}) == {"cancelled": False}
    assert len(nm.profiles) == 1


def test_private_cancellation_failure_is_not_acknowledged_and_remains_recoverable(state):
    engine, nm, _ = state
    request = begin_request()
    engine.handle(request)
    nm.failure = "delete_profile"
    error("network_failed", lambda: engine.handle({"op": "cancel_pending"}))
    assert engine.journal.active()["phase"] == "rolling_back"
    assert engine.handle({"op": "cancel_pending"}) == {"cancelled": True}
    assert engine.journal.active() is None


@contextmanager
def cancellation_socket(engine, count=1):
    """Use the actual bounded socket protocol without the automatic NM tick."""
    with tempfile.TemporaryDirectory(prefix="inky-cancel-", dir="/tmp") as directory:
        path = Path(directory) / "socket"
        with helper.Server(path, engine) as server:
            server.timeout = 2

            def requests():
                for _ in range(count):
                    server.handle_request()

            thread = threading.Thread(target=requests)
            thread.start()
            try:
                yield str(path)
            finally:
                thread.join(timeout=5)
                assert not thread.is_alive()


@pytest.mark.parametrize("phase", ["detaching", "commit_ready"])
async def test_shutdown_and_cli_reset_cancel_real_pending_transaction_before_epoch(state, tmp_path, monkeypatch, phase):
    from inky_web import auth
    from inky_web.inky.display import DisplayController
    from inky_web.provisioning.network import NetworkClient
    from inky_web.provisioning.ownership import OwnershipError, OwnershipStore
    from inky_web.provisioning.runtime import ProvisioningRuntime

    engine, nm, _ = state
    directory = tmp_path / "frame"
    credentials = auth.reset_credentials(directory)
    runtime = ProvisioningRuntime(directory / "provisioning",
                                  auth.CredentialService(credentials, auth.SessionStore()), DisplayController())
    request = begin_request()
    token = secrets.token_hex(32)
    runtime.owners.claim(runtime.owners.open_window(), request["owner_id"], token, str(uuid4()), runtime.epoch())
    make_ready(state, request)
    engine.handle(operation(request, "confirm"))
    nm.finish_activation()
    engine._put(engine.journal.get(request["id"]), phase=phase)
    before = credentials.path.read_bytes()
    monkeypatch.setenv("INKY_STUDIO_DATA_DIR", str(directory))
    monkeypatch.delenv("INKY_STUDIO_BLUETOOTH", raising=False)
    monkeypatch.setattr(sys, "argv", ["inky-auth", "reset-password"])
    with cancellation_socket(engine, count=2) as path:
        runtime.network = NetworkClient(path)
        monkeypatch.setenv("INKY_NETWORK_SOCKET", path)
        await runtime.stop()
        assert engine.journal.get(request["id"])["state"] == "rolled_back"
        assert credentials.path.read_bytes() == before
        assert auth.main() == 0
    assert credentials.path.read_bytes() != before
    assert not nm.profiles and nm.current["uuid"] == nm.previous
    engine.tick()
    assert "checkpoint_destroy" not in nm.calls
    owners = OwnershipStore(directory / "provisioning", runtime.epoch)
    try:
        with pytest.raises(OwnershipError):
            owners.authenticate(request["owner_id"], token)
    finally:
        owners.close()


@pytest.mark.parametrize("phase", ["detaching", "commit_ready"])
def test_cli_reset_without_clean_shutdown_cancels_or_preserves_credentials(state, tmp_path, monkeypatch, capsys, phase):
    from inky_web import auth

    engine, nm, _ = state
    request = begin_request()
    make_ready(state, request)
    engine.handle(operation(request, "confirm"))
    nm.finish_activation()
    engine._put(engine.journal.get(request["id"]), phase=phase)
    directory = tmp_path / "frame"
    credentials = auth.reset_credentials(directory)
    (directory / "provisioning").mkdir()
    before = credentials.path.read_bytes()
    monkeypatch.setenv("INKY_STUDIO_DATA_DIR", str(directory))
    monkeypatch.delenv("INKY_STUDIO_BLUETOOTH", raising=False)
    monkeypatch.setattr(sys, "argv", ["inky-auth", "reset-password"])
    original_write = auth._write_credentials

    def write_after_rollback(replacement):
        assert engine.journal.get(request["id"])["state"] == "rolled_back"
        assert not nm.profiles
        original_write(replacement)

    monkeypatch.setattr(auth, "_write_credentials", write_after_rollback)
    with cancellation_socket(engine, count=2) as path:
        monkeypatch.setenv("INKY_NETWORK_SOCKET", path)
        nm.failure = "delete_profile"
        assert auth.main() == 1
        assert credentials.path.read_bytes() == before
        assert "Reset annulé" in capsys.readouterr().out
        assert auth.main() == 0
    assert credentials.path.read_bytes() != before
    assert "checkpoint_destroy" not in nm.calls


def test_cli_reset_with_unreachable_helper_preserves_credentials(tmp_path, monkeypatch, capsys):
    from inky_web import auth

    directory = tmp_path / "frame"
    credentials = auth.reset_credentials(directory)
    (directory / "provisioning").mkdir()
    before = credentials.path.read_bytes()
    monkeypatch.setenv("INKY_STUDIO_DATA_DIR", str(directory))
    monkeypatch.setenv("INKY_NETWORK_SOCKET", "/tmp/inky-no-such-reset-helper/socket")
    monkeypatch.delenv("INKY_STUDIO_BLUETOOTH", raising=False)
    monkeypatch.setattr(sys, "argv", ["inky-auth", "reset-password"])
    assert auth.main() == 1
    assert credentials.path.read_bytes() == before
    assert "Reset annulé" in capsys.readouterr().out


def test_health_ready_probe_has_no_network_or_watchdog_side_effect(state, monkeypatch):
    engine, nm, _ = state
    request = begin_request()
    make_ready(state, request)
    engine.handle(operation(request, "confirm"))
    nm.finish_activation()  # A tick would now finalize the pending commit.
    calls_before = list(nm.calls)

    def forbidden_tick():
        pytest.fail("health must not run the watchdog")

    monkeypatch.setattr(engine, "tick", forbidden_tick)
    assert helper.parse_request(b'{"op":"health"}\n') == {"op": "health"}
    assert engine.handle({"op": "health"}) == {"ready": True, "protocol": 1}
    assert nm.calls == calls_before
    assert engine.journal.active()["phase"] == "detaching"


def test_health_not_ready_returns_error_without_network_calls(state, monkeypatch):
    engine, nm, _ = state
    engine.ready = False
    calls_before = list(nm.calls)

    def forbidden_tick():
        pytest.fail("unavailable health must not run the watchdog")

    monkeypatch.setattr(engine, "tick", forbidden_tick)
    error("not_ready", lambda: engine.handle({"op": "health"}))
    assert nm.calls == calls_before
    error("invalid_request", lambda: helper.validate_request({"op": "health", "owner_id": str(uuid4())}))
