"""Factory maintenance refusals use local signals, never OS writer admission."""
from __future__ import annotations

import os
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from inky_web.api import system
from inky_web.provisioning import factory_environment
from inky_web.provisioning import factory_runtime as guard
from inky_web.provisioning.bootstrap_identity import PREPARED_IDENTITY_FILENAME
from inky_web.provisioning.ownership import OwnershipStore
from inky_web.services import updater


@pytest.fixture(autouse=True)
def inky_env(tmp_path, monkeypatch):
    # Override the shared fixture: these guards must not create the legacy DB.
    data = tmp_path / "data"
    monkeypatch.setenv("INKY_STUDIO_DATA_DIR", str(data))
    for name in list(os.environ):
        if name == guard.REQUIRED_ENV or name.startswith("INKYOS_WRITER_"):
            monkeypatch.delenv(name)
    monkeypatch.setattr(factory_environment, "FACTORY_SIGNAL_PATHS", (tmp_path / "missing-signal",))
    monkeypatch.setattr(guard, "MARKER_PATH", tmp_path / "missing-studio-marker")
    monkeypatch.setattr(guard, "InitializationIPCClient", lambda: pytest.fail("No maintenance IPC"))
    return data


def _snapshot(directory):
    return {
        str(path.relative_to(directory)): (
            ("link", os.readlink(path)) if path.is_symlink()
            else ("dir", None) if path.is_dir()
            else ("file", path.read_bytes())
        )
        for path in directory.rglob("*")
    }


@pytest.mark.parametrize("name", [
    "INKYOS_WRITER_LEASE_FD", "INKYOS_WRITER_ROLE", "INKYOS_WRITER_CONTEXT_SHA256",
    "INKYOS_WRITER_UNRECOGNIZED",
])
@pytest.mark.parametrize("value", ["", "private-synthetic-handoff"])
def test_any_writer_signal_refuses_without_selection_or_ipc(inky_env, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    monkeypatch.setattr(guard, "select_runtime", lambda _data: pytest.fail("No writer admission for maintenance"))
    with pytest.raises(guard.FactoryRuntimeError) as failure:
        guard.guard_legacy_command(inky_env)
    assert str(failure.value) == "factory_runtime_refused"
    assert failure.value.exit_status == 78
    assert not inky_env.exists()


@pytest.mark.parametrize("value", ["", "0", "1", "private-synthetic-value"])
def test_any_required_flag_refuses_maintenance(inky_env, monkeypatch, value):
    monkeypatch.setenv(guard.REQUIRED_ENV, value)
    with pytest.raises(guard.FactoryRuntimeError, match="^factory_runtime_refused$"):
        guard.guard_legacy_command(inky_env)
    assert not inky_env.exists()


@pytest.mark.parametrize("kind", ["opaque-file", "dangling-symlink", "directory"])
def test_factory_signal_path_presence_refuses_without_reading_contents(
    tmp_path, inky_env, monkeypatch, kind,
):
    signal = tmp_path / "factory-signal"
    if kind == "opaque-file":
        signal.write_bytes(b"private invalid contents" * 100)
    elif kind == "dangling-symlink":
        signal.symlink_to(tmp_path / "missing-private-target")
    else:
        signal.mkdir()
    monkeypatch.setattr(factory_environment, "FACTORY_SIGNAL_PATHS", (signal,))
    monkeypatch.setattr(guard, "select_runtime", lambda _data: pytest.fail("Do not inspect factory state"))
    before = _snapshot(tmp_path)
    with pytest.raises(guard.FactoryRuntimeError, match="^factory_runtime_refused$"):
        guard.guard_legacy_command(inky_env)
    assert _snapshot(tmp_path) == before


def test_signal_inspection_failure_has_fixed_public_diagnostic(inky_env, monkeypatch):
    def failed_inspection():
        raise PermissionError("private synthetic path and details")

    monkeypatch.setattr(factory_environment, "factory_signals_present", failed_inspection)
    with pytest.raises(guard.FactoryRuntimeError, match="^factory_runtime_refused$"):
        guard.guard_legacy_command(inky_env)
    assert not inky_env.exists()


@pytest.mark.parametrize("name", [".first-boot.lock", PREPARED_IDENTITY_FILENAME, ".bootstrap-identity.lock"])
def test_durable_factory_traces_still_refuse_when_all_installed_signals_are_absent(
    tmp_path, inky_env, name,
):
    directory = inky_env / "provisioning"
    directory.mkdir(parents=True)
    (directory / name).symlink_to(directory / "missing-private-target")
    before = _snapshot(tmp_path)
    with pytest.raises(guard.FactoryRuntimeError, match="^factory_runtime_refused$"):
        guard.guard_legacy_command(inky_env)
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("stored", ["absent", "legacy-ledger"])
def test_no_factory_signal_preserves_legacy_and_does_not_create_or_rewrite_state(
    tmp_path, inky_env, stored,
):
    if stored == "legacy-ledger":
        store = OwnershipStore(inky_env / "provisioning", lambda: "a" * 64)
        store.close()
    before = _snapshot(tmp_path)
    guard.guard_legacy_command(inky_env)
    assert _snapshot(tmp_path) == before


def _forbid_update_effects(monkeypatch):
    operations = []
    for target, name in (
        (updater, "get_status"), (updater, "_fetch_latest_release"),
        (updater.fcntl, "flock"), (updater.tempfile, "mkdtemp"),
        (updater, "_download"), (updater, "_safe_extract"),
        (updater, "_backup_current"), (updater, "_apply"), (updater, "_restore"),
        (updater.shutil, "rmtree"),
    ):
        operation = Mock(side_effect=AssertionError(f"Factory update reached {name}"))
        monkeypatch.setattr(target, name, operation)
        operations.append(operation)
    for target, name in (
        (updater, "_run_streaming"), (updater.asyncio, "create_subprocess_exec"),
    ):
        operation = AsyncMock(side_effect=AssertionError(f"Factory update reached {name}"))
        monkeypatch.setattr(target, name, operation)
        operations.append(operation)
    return operations


def _factory_update_signal(tmp_path, inky_env, monkeypatch, signal):
    if signal == "partial-writer":
        monkeypatch.setenv("INKYOS_WRITER_ROLE", "")
    elif signal == "required-flag":
        monkeypatch.setenv(guard.REQUIRED_ENV, "1")
    elif signal == "installed-marker":
        marker = tmp_path / "installed-marker"
        marker.write_text("private malformed factory marker")
        monkeypatch.setattr(factory_environment, "FACTORY_SIGNAL_PATHS", (marker,))
    else:
        directory = inky_env / "provisioning"
        directory.mkdir(parents=True)
        (directory / PREPARED_IDENTITY_FILENAME).write_text("private prepared identity")


@pytest.mark.parametrize("signal", ["partial-writer", "required-flag", "installed-marker", "durable-trace"])
async def test_direct_update_refuses_before_lock_temp_network_deps_or_service(
    tmp_path, inky_env, monkeypatch, signal,
):
    _factory_update_signal(tmp_path, inky_env, monkeypatch, signal)
    operations = _forbid_update_effects(monkeypatch)
    before = _snapshot(tmp_path)
    events = []
    install = tmp_path / "absent-install"
    assert not await updater.perform_update(
        lambda *args, **kwargs: events.append((args, kwargs)), install_dir=install,
    )
    assert events == [(("error", "factory_runtime_refused"), {})]
    assert _snapshot(tmp_path) == before
    for operation in operations:
        operation.assert_not_called()


@pytest.mark.parametrize("signal", ["partial-writer", "required-flag", "installed-marker", "durable-trace"])
def test_updater_main_refuses_before_status_network_or_perform(
    tmp_path, inky_env, monkeypatch, capsys, signal,
):
    _factory_update_signal(tmp_path, inky_env, monkeypatch, signal)
    operations = _forbid_update_effects(monkeypatch)
    perform = AsyncMock()
    monkeypatch.setattr(updater, "perform_update", perform)
    before = _snapshot(tmp_path)
    assert updater.main() == 78
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "factory_runtime_refused\n"
    assert _snapshot(tmp_path) == before
    for operation in [*operations, perform]:
        operation.assert_not_called()


def test_http_update_uses_same_guard_before_update_effects(tmp_path, inky_env, monkeypatch):
    monkeypatch.setenv("INKYOS_WRITER_CONTEXT_SHA256", "")
    monkeypatch.setattr(updater, "INSTALL_DIR", tmp_path / "absent-install")
    operations = _forbid_update_effects(monkeypatch)
    events = []
    notified = threading.Event()

    def broadcast(name, payload):
        events.append((name, payload))
        notified.set()

    app = FastAPI()
    app.include_router(system.router, prefix="/api")
    app.state.bus = SimpleNamespace(broadcast=broadcast)
    app.state.updating = False
    before = _snapshot(tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/system/update")
        assert response.status_code == 202
        assert notified.wait(timeout=2)
    assert events == [("system_update", {"stage": "error", "message": "factory_runtime_refused"})]
    assert app.state.updating is False
    assert _snapshot(tmp_path) == before
    for operation in operations:
        operation.assert_not_called()


@pytest.mark.parametrize("available", [False, True])
def test_legacy_updater_main_keeps_status_and_install_behavior(inky_env, monkeypatch, available):
    status = Mock(return_value={"current": "1.0.0", "latest": "1.1.0", "update_available": available})
    perform = AsyncMock(return_value=True)
    monkeypatch.setattr(updater, "get_status", status)
    monkeypatch.setattr(updater, "perform_update", perform)
    assert updater.main() == 0
    status.assert_called_once_with(use_cache=False)
    if available:
        perform.assert_awaited_once()
    else:
        perform.assert_not_called()
    assert not inky_env.exists()
