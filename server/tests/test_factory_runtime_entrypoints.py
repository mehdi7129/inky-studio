"""Factory selection must precede every legacy startup side effect.

The OS selector/coordinator boundaries are replaced here; their real storage and
IPC contract are covered separately. No device, root service or socket is used.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from inky_web import auth, db, main, welcome
from inky_web.provisioning import factory_runtime, identity


@pytest.fixture(autouse=True)
def inky_env(tmp_path, monkeypatch):
    # Override the shared fixture: it eagerly creates the legacy database.
    directory = tmp_path / "state"
    monkeypatch.setenv("INKY_STUDIO_DATA_DIR", str(directory))
    monkeypatch.setenv("INKY_STUDIO_DISPLAY_MODE", "mock")
    monkeypatch.delenv("INKY_STUDIO_DISABLE_AUTH", raising=False)
    monkeypatch.delenv("INKY_STUDIO_BLUETOOTH", raising=False)
    monkeypatch.delenv("INKY_STUDIO_DISPLAY_PROFILE", raising=False)
    monkeypatch.setattr(factory_runtime, "select_runtime", lambda _path: None)
    monkeypatch.setattr(factory_runtime, "guard_legacy_command", lambda _path: None)
    return directory


@pytest.fixture
def forbid_legacy(monkeypatch):
    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append("legacy effect")
        raise AssertionError("Legacy effect admitted during factory startup")

    monkeypatch.setattr(main, "data_dir", forbidden)
    monkeypatch.setattr(main, "init_db", forbidden)
    monkeypatch.setattr(main, "DisplayController", forbidden)
    monkeypatch.setattr(main, "Scheduler", forbidden)
    monkeypatch.setattr(main, "PhotoAccessStore", forbidden)
    monkeypatch.setattr(auth, "load_or_create_credentials", forbidden)
    monkeypatch.setattr(auth, "reset_credentials", forbidden)
    monkeypatch.setattr(auth, "display_password", forbidden)
    monkeypatch.setattr(identity, "load_or_create_identity", forbidden)
    monkeypatch.setattr(main.uvicorn, "Config", forbidden)
    monkeypatch.setattr(welcome, "DisplayController", forbidden)
    monkeypatch.setattr(welcome, "default_data_dir", forbidden)
    monkeypatch.setattr(welcome, "_show_welcome", forbidden)
    return calls


def test_resolve_data_dir_has_no_creation_but_data_dir_keeps_legacy_behavior(inky_env):
    assert db.resolve_data_dir() == inky_env
    assert not inky_env.exists()
    assert db.data_dir() == inky_env
    assert (inky_env / "photos").is_dir()


async def test_opt_out_selection_neither_initializes_nor_creates_state(inky_env, monkeypatch):
    def forbidden(_config):
        pytest.fail("Opt-out attempted factory initialization")

    monkeypatch.setattr(factory_runtime, "initialize_factory", forbidden)
    await main._select_startup_runtime()
    assert not inky_env.exists()


@pytest.mark.parametrize("entry", ["http", "https", "asgi"])
@pytest.mark.parametrize("outcome", ["factory_runtime_refused", "factory_runtime_uncertain",
                                    "factory_runtime_pending", "unexpected_return"])
async def test_factory_never_reaches_legacy_even_after_preparation(
    entry, outcome, inky_env, monkeypatch, forbid_legacy,
):
    config = object()
    calls = []

    def select(directory):
        assert directory == inky_env
        calls.append("select")
        return config

    def initialize(value):
        assert value is config
        calls.append("initialize")
        if outcome != "unexpected_return":
            raise factory_runtime.FactoryRuntimeError(outcome)

    monkeypatch.setattr(factory_runtime, "select_runtime", select)
    monkeypatch.setattr(factory_runtime, "initialize_factory", initialize)
    expected = "factory_runtime_uncertain" if outcome == "unexpected_return" else outcome
    with pytest.raises(factory_runtime.FactoryRuntimeError) as failure:
        if entry == "asgi":
            async with main.lifespan(main.app):
                pytest.fail("ASGI factory startup yielded")
        else:
            await main.serve(with_https=entry == "https")
    assert failure.value.code == expected
    assert calls == ["select", "initialize"]
    assert not forbid_legacy
    assert not inky_env.exists()


@pytest.mark.parametrize("entry", ["http", "https", "asgi"])
async def test_rejected_selection_precedes_coordinator_and_legacy(
    entry, inky_env, monkeypatch, forbid_legacy,
):
    def select(_directory):
        raise factory_runtime.FactoryRuntimeError("factory_runtime_refused")

    def initialize(_config):
        pytest.fail("Rejected selector reached coordinator")

    monkeypatch.setattr(factory_runtime, "select_runtime", select)
    monkeypatch.setattr(factory_runtime, "initialize_factory", initialize)
    with pytest.raises(factory_runtime.FactoryRuntimeError, match="factory_runtime_refused"):
        if entry == "asgi":
            async with main.lifespan(main.app):
                pytest.fail("Rejected selector yielded")
        else:
            await main.serve(with_https=entry == "https")
    assert not forbid_legacy
    assert not inky_env.exists()


async def test_repeated_cancellation_drains_admitted_factory_worker(inky_env, monkeypatch, forbid_legacy):
    loop = asyncio.get_running_loop()
    started, completed = asyncio.Event(), asyncio.Event()
    release = threading.Event()

    def initialize(_config):
        loop.call_soon_threadsafe(started.set)
        try:
            assert release.wait(5), "Test did not release the admitted worker"
        finally:
            loop.call_soon_threadsafe(completed.set)
        raise factory_runtime.FactoryRuntimeError("factory_runtime_pending")

    monkeypatch.setattr(factory_runtime, "select_runtime", lambda _path: object())
    monkeypatch.setattr(factory_runtime, "initialize_factory", initialize)
    task = asyncio.create_task(main._select_startup_runtime())
    try:
        await asyncio.wait_for(started.wait(), 2)
        for _ in range(2):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert not completed.is_set()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert completed.is_set()
    assert not forbid_legacy
    assert not inky_env.exists()


@pytest.mark.parametrize("code", ["factory_runtime_refused", "factory_runtime_uncertain", "factory_runtime_pending"])
def test_console_startup_reports_fixed_error_and_exit_78(code, monkeypatch, caplog):
    async def stopped(*, with_https):
        raise factory_runtime.FactoryRuntimeError(code)

    monkeypatch.setattr(main, "serve", stopped)
    with pytest.raises(SystemExit) as failure:
        main.run()
    assert failure.value.code == 78
    assert code in caplog.text


@pytest.mark.parametrize("command", ["password", "reset-password", "welcome", "show_welcome"])
def test_legacy_cli_refuses_factory_before_secrets_network_or_spi(
    command, inky_env, monkeypatch, forbid_legacy, capsys,
):
    guarded = []

    def guard(directory):
        assert directory == inky_env
        guarded.append(directory)
        raise factory_runtime.FactoryRuntimeError("factory_runtime_refused")

    def initialize(_config):
        pytest.fail("A legacy command attempted factory initialization")

    monkeypatch.setattr(factory_runtime, "guard_legacy_command", guard)
    monkeypatch.setattr(factory_runtime, "initialize_factory", initialize)
    if command in {"password", "reset-password"}:
        # If admitted, reset would try the network helper before credentials.
        monkeypatch.setenv("INKY_STUDIO_BLUETOOTH", "1")
        monkeypatch.setattr(sys, "argv", ["inky-studio", command])
        assert auth.main() == 78
    elif command == "welcome":
        assert welcome.main() == 78
    else:
        with pytest.raises(factory_runtime.FactoryRuntimeError):
            welcome.show_welcome()
    assert guarded == [inky_env]
    assert not forbid_legacy
    assert not inky_env.exists()
    assert "secret" not in capsys.readouterr().out.lower()


async def test_legacy_serve_selects_once_and_preserves_lifespan(inky_env, monkeypatch):
    selections = []
    monkeypatch.setenv("INKY_STUDIO_DISABLE_AUTH", "1")
    monkeypatch.setattr(factory_runtime, "select_runtime", lambda path: selections.append(path))

    class FakeServer:
        def __init__(self, config):
            self.config = config
            self.started = False

        async def serve(self, sockets=None):
            self.started = True

        async def shutdown(self, sockets=None):
            pass

    monkeypatch.setattr(main.uvicorn, "Server", FakeServer)
    monkeypatch.setattr(main.uvicorn, "Config", lambda **kwargs: SimpleNamespace(**kwargs))
    await main.serve()
    assert selections == [inky_env]
    assert (inky_env / "inky_studio.db").is_file()
    assert (inky_env / "credentials.json").is_file()
    assert main.app.state.display.closing


def test_import_main_does_not_create_state_or_load_pi_driver(inky_env):
    script = """
import os
import sys
from pathlib import Path
import inky_web.main
assert not Path(os.environ['INKY_STUDIO_DATA_DIR']).exists()
assert 'inky.auto' not in sys.modules
"""
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).parents[1],
                            env=environment, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert not inky_env.exists()
