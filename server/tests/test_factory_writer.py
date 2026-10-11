"""Studio admission envelopes; OS identity/Ready checks have their own suite.

Only synthetic contract modules are loaded. The lifecycle tests use actual
flock and blocked startup threads, without root files, radios or an app DB.
"""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from inky_web import main
from inky_web.provisioning import factory_environment as environment
from inky_web.provisioning import factory_runtime
from inky_web.provisioning import factory_writer as writer


@pytest.fixture(autouse=True)
def inky_env(tmp_path, monkeypatch):
    directory = tmp_path / "state"
    monkeypatch.setenv("INKY_STUDIO_DATA_DIR", str(directory))
    monkeypatch.delenv("INKY_STUDIO_FACTORY_REQUIRED", raising=False)
    for name in tuple(os.environ):
        if name.startswith("INKYOS_WRITER_"):
            monkeypatch.delenv(name)
    monkeypatch.setattr(environment, "FACTORY_SIGNAL_PATHS", (tmp_path / "absent",))
    return directory


def test_legacy_guard_never_imports_os(monkeypatch):
    monkeypatch.setattr(writer, "_installed_runtime", lambda: pytest.fail("OS imported in legacy"))
    with writer.main_writer_guard() as lease:
        assert lease is None


@pytest.mark.parametrize("signal", ["INKY_STUDIO_FACTORY_REQUIRED", *environment.WRITER_ENV_NAMES,
                                   "INKYOS_WRITER_UNKNOWN"])
@pytest.mark.parametrize("value", ["", "invalid"])
def test_partial_signal_cannot_fall_back_to_legacy(signal, value, monkeypatch):
    monkeypatch.setenv(signal, value)
    monkeypatch.setattr(writer, "_installed_runtime", lambda: pytest.fail("Malformed signal imported OS"))
    with pytest.raises(writer.FactoryWriterRefused):
        with writer.main_writer_guard():
            pytest.fail("Malformed factory signal admitted")


def test_unknown_writer_variable_refused_before_loader(monkeypatch):
    monkeypatch.setenv("INKY_STUDIO_FACTORY_REQUIRED", "1")
    monkeypatch.setenv("INKYOS_WRITER_UNKNOWN", "")
    monkeypatch.setattr(writer, "_installed_runtime", lambda: pytest.fail("Unknown signal imported OS"))
    with pytest.raises(writer.FactoryWriterRefused):
        with writer.main_writer_guard():
            pytest.fail("Unknown signal admitted")


def test_public_signal_without_flag_refuses_before_loader(tmp_path, monkeypatch):
    marker = tmp_path / "marker"
    marker.symlink_to(tmp_path / "missing")
    monkeypatch.setattr(environment, "FACTORY_SIGNAL_PATHS", (marker,))
    monkeypatch.setattr(writer, "_installed_runtime", lambda: pytest.fail("Missing flag imported OS"))
    with pytest.raises(writer.FactoryWriterRefused):
        with writer.main_writer_guard():
            pytest.fail("Opaque marker selected legacy")


@pytest.mark.parametrize("manifest", [b"{}", b"not JSON", b'{"os_module_pins":{},"os_module_pins":{}}',
                                      b'{"os_module_pins":{"factory-runtime-contract.py":7}}',
                                      b'{"os_module_pins":{"factory-runtime-contract.py":"' + b"0" * 64 + b'"}}'])
def test_unpinned_module_is_never_executed(manifest, monkeypatch):
    monkeypatch.setenv("INKY_STUDIO_FACTORY_REQUIRED", "1")
    module = b'raise AssertionError("Unpinned module executed")\n'
    monkeypatch.setattr(writer, "_read_protected", lambda path, _mode, _limit:
                        manifest if path == writer.MANIFEST_PATH else module)
    with pytest.raises(writer.FactoryWriterRefused):
        with writer.main_writer_guard():
            pytest.fail("Invalid module admitted")


def test_pinned_module_without_guard_api_refuses_closed(monkeypatch):
    monkeypatch.setenv("INKY_STUDIO_FACTORY_REQUIRED", "1")
    module = b'legacy_api = True\n'
    manifest = json.dumps({"os_module_pins": {writer.RUNTIME_PATH.name:
                                             hashlib.sha256(module).hexdigest()}}).encode()
    monkeypatch.setattr(writer, "_read_protected", lambda path, _mode, _limit:
                        manifest if path == writer.MANIFEST_PATH else module)
    with pytest.raises(writer.FactoryWriterRefused):
        with writer.main_writer_guard():
            pytest.fail("Old contract without guard API admitted")


def test_verified_module_guard_is_called_and_owned_until_scope_exit(monkeypatch):
    monkeypatch.setenv("INKY_STUDIO_FACTORY_REQUIRED", "1")
    module = b'''from contextlib import contextmanager
class Lease:
    closed = False
    def check(self):
        assert not self.closed
    def fileno(self):
        return 7
@contextmanager
def writer_guard(role):
    assert role == "main"
    lease = Lease()
    try:
        yield lease
    finally:
        lease.closed = True
'''
    manifest = json.dumps({"os_module_pins": {writer.RUNTIME_PATH.name:
                                             hashlib.sha256(module).hexdigest()}}).encode()
    monkeypatch.setattr(writer, "_read_protected", lambda path, _mode, _limit:
                        manifest if path == writer.MANIFEST_PATH else module)
    with writer.main_writer_guard() as lease:
        assert not lease.closed
    assert lease.closed


def test_os_refusal_does_not_expose_exception_values(monkeypatch):
    monkeypatch.setenv("INKY_STUDIO_FACTORY_REQUIRED", "1")

    @contextmanager
    def refused(_role):
        raise ValueError("private path and request secret")
        yield  # pragma: no cover

    monkeypatch.setattr(writer, "_installed_runtime", lambda: SimpleNamespace(writer_guard=refused))
    with pytest.raises(writer.FactoryWriterRefused) as error:
        with writer.main_writer_guard():
            pytest.fail("Rejected OS admission yielded")
    assert str(error.value) == "factory_runtime_refused"
    assert error.value.__cause__ is None


@pytest.fixture
def real_lease(tmp_path, monkeypatch):
    path = tmp_path / "writer.lock"
    path.touch()
    acquisitions, releases = [], []
    monkeypatch.setenv("INKY_STUDIO_FACTORY_REQUIRED", "1")

    def exclusive_available():
        with path.open("rb") as probe:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            return True

    @contextmanager
    def admitted(role):
        assert role == "main"
        with path.open("rb") as descriptor:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)

            def check():
                assert not descriptor.closed
                os.fstat(descriptor.fileno())

            lease = SimpleNamespace(check=check, fileno=descriptor.fileno)
            acquisitions.append(lease)
            try:
                yield lease
            finally:
                releases.append(lease)

    monkeypatch.setattr(writer, "_installed_runtime", lambda: SimpleNamespace(writer_guard=admitted))
    return SimpleNamespace(available=exclusive_available, acquisitions=acquisitions, releases=releases)


def test_nested_entries_reuse_owned_lease_and_preserve_body_exception(real_lease):
    with pytest.raises(factory_runtime.FactoryRuntimeError, match="factory_runtime_pending"):
        with writer.main_writer_guard() as outer:
            assert not real_lease.available()
            with writer.main_writer_guard() as inner:
                assert inner is outer
                raise factory_runtime.FactoryRuntimeError("factory_runtime_pending")
    assert len(real_lease.acquisitions) == len(real_lease.releases) == 1
    assert real_lease.available()


@pytest.mark.parametrize("name,value", [("INKYOS_WRITER_UNKNOWN", ""),
                                        ("INKYOS_WRITER_ROLE", "helper"),
                                        ("INKY_STUDIO_FACTORY_REQUIRED", "")])
def test_nested_entry_cannot_reuse_admission_after_environment_change(real_lease, monkeypatch, name, value):
    with writer.main_writer_guard():
        monkeypatch.setenv(name, value)
        with pytest.raises(writer.FactoryWriterRefused):
            with writer.main_writer_guard():
                pytest.fail("Changed factory environment reused admission")
        assert not real_lease.available()
    assert real_lease.available()


@pytest.mark.parametrize("entry", ["selector", "http", "https", "asgi", "asgi_preselected"])
async def test_admission_refusal_precedes_selector_and_every_legacy_effect(entry, monkeypatch, inky_env):
    monkeypatch.setenv("INKY_STUDIO_FACTORY_REQUIRED", "1")
    monkeypatch.setattr(writer, "_installed_runtime", lambda: (_ for _ in ()).throw(ValueError("secret")))

    def forbidden(*_args, **_kwargs):
        pytest.fail("Effect or selector executed before rejected admission")

    monkeypatch.setattr(factory_runtime, "select_runtime", forbidden)
    for name in ("init_db", "data_dir", "DisplayController", "Scheduler"):
        monkeypatch.setattr(main, name, forbidden)
    with pytest.raises(writer.FactoryWriterRefused):
        if entry == "selector":
            await main._select_startup_runtime()
        elif entry.startswith("asgi"):
            async with main.lifespan(main.app, _legacy_selected=entry == "asgi_preselected"):
                pytest.fail("Rejected lifespan yielded")
        else:
            await main.serve(with_https=entry == "https")
    assert not inky_env.exists()


@pytest.mark.parametrize("entry", ["selector", "http", "asgi_preselected"])
async def test_repeated_cancellation_retains_lease_until_factory_worker_finishes(
    entry, real_lease, monkeypatch, inky_env,
):
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()
    finished = threading.Event()

    def initialize(_config):
        assert not real_lease.available()
        loop.call_soon_threadsafe(started.set)
        try:
            assert release.wait(5), "Test did not release admitted startup worker"
        finally:
            finished.set()
        raise factory_runtime.FactoryRuntimeError("factory_runtime_pending")

    async def invoke():
        if entry == "selector":
            await main._select_startup_runtime()
        elif entry == "http":
            await main.serve()
        else:
            async with main.lifespan(main.app, _legacy_selected=True):
                pytest.fail("Prepared factory fell back to legacy")

    monkeypatch.setattr(factory_runtime, "select_runtime", lambda _path: object())
    monkeypatch.setattr(factory_runtime, "initialize_factory", initialize)
    monkeypatch.setattr(main, "init_db", lambda: pytest.fail("Factory initialized legacy DB"))
    task = asyncio.create_task(invoke())
    try:
        await asyncio.wait_for(started.wait(), 2)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert not finished.is_set()
            assert not real_lease.available()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert finished.is_set()
    assert real_lease.available()
    assert len(real_lease.acquisitions) == len(real_lease.releases) == 1
    assert not inky_env.exists()


def test_console_reports_guard_refusal_as_exit_78(monkeypatch, caplog):
    monkeypatch.setenv("INKY_STUDIO_FACTORY_REQUIRED", "1")
    monkeypatch.setattr(writer, "_installed_runtime", lambda: (_ for _ in ()).throw(ValueError("secret")))
    with pytest.raises(SystemExit) as error:
        main.run()
    assert error.value.code == 78
    assert "factory_runtime_refused" in caplog.text
    assert "secret" not in caplog.text


@pytest.mark.parametrize("preselected", [False, True])
async def test_private_legacy_boolean_never_bypasses_durable_factory_trace(
    preselected, inky_env, monkeypatch,
):
    provisioning = inky_env / "provisioning"
    provisioning.mkdir(parents=True)
    (provisioning / ".first-boot.lock").touch()
    monkeypatch.setattr(factory_runtime, "MARKER_PATH", inky_env / "absent-marker")
    monkeypatch.setattr(writer, "_installed_runtime", lambda: pytest.fail("No installed OS signal"))
    monkeypatch.setattr(main, "init_db", lambda: pytest.fail("Durable trace bypass reached legacy DB"))
    assert not environment.factory_signals_present()
    with pytest.raises(factory_runtime.FactoryRuntimeError):
        async with main.lifespan(main.app, _legacy_selected=preselected):
            pytest.fail("Durable factory trace yielded legacy lifespan")
    assert not (inky_env / "inky_studio.db").exists()
    assert not (inky_env / "credentials.json").exists()
