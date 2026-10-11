"""Inactive lifecycle composition with real ledgers, sockets and flock.

Root identity/admission, display and BlueZ are synthetic. These tests are not
evidence of an installed OS graph, Linux credentials or physical first boot.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
from contextvars import copy_context
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio

from inky_web import auth, db
from inky_web.provisioning import factory_environment as environment
from inky_web.provisioning import factory_phase_a as phase
from inky_web.provisioning import factory_runtime, factory_writer, identity
from inky_web.provisioning import initialization_ipc as ipc
from inky_web.provisioning.bootstrap_runtime import BootstrapRuntime
from inky_web.provisioning.first_boot import FirstBootResult

from .test_factory_observation import admission as admission
from .test_factory_runtime import configured as configured
from .test_factory_runtime import record as record
from .test_factory_runtime import snapshot
from .test_initialization_ipc import encode, success
from .test_initialization_ipc import root_peer as root_peer
from .test_initialization_ipc import serve as serve


@pytest.fixture(autouse=True)
def inky_env(tmp_path, monkeypatch):
    # Prevent conftest from eagerly initializing the normal application DB.
    monkeypatch.setenv("INKY_STUDIO_DATA_DIR", str(tmp_path / "unused-normal"))
    monkeypatch.delenv("INKY_STUDIO_FACTORY_REQUIRED", raising=False)
    monkeypatch.delenv("INKY_STUDIO_DISABLE_AUTH", raising=False)
    for name in tuple(os.environ):
        if name.startswith("INKYOS_WRITER_"):
            monkeypatch.delenv(name)
    monkeypatch.setattr(environment, "FACTORY_SIGNAL_PATHS", (tmp_path / "absent",))

    def forbidden(*_args, **_kwargs):
        pytest.fail("Phase A admitted a normal application subsystem")

    monkeypatch.setattr(db, "init_db", forbidden)
    monkeypatch.setattr(db, "data_dir", forbidden)
    monkeypatch.setattr(auth, "load_or_create_credentials", forbidden)
    monkeypatch.setattr(identity, "load_or_create_identity", forbidden)
    monkeypatch.setattr(factory_runtime, "initialize_factory", forbidden)
    yield
    assert not (tmp_path / "unused-normal").exists()


class Display:
    def __init__(self, events, *, entered=None, release=None, failure=None):
        self.events, self.entered, self.release, self.failure = events, entered, release, failure
        self.closing = False

    def initialize(self):
        self.events.append("initialize")
        if self.entered:
            self.entered.set()
            assert self.release.wait(5)
        if self.failure:
            raise self.failure

    def require_available(self):
        self.events.append("available")

    def begin_shutdown(self):
        self.closing = True
        self.events.append("closed-display")

    def shutdown(self):
        self.events.append("shutdown")


class Runtime:
    def __init__(self, events, stop, verify, *, entered=None, release=None, stop_entered=None,
                 stop_release=None, failure=None):
        self.events, self.stop_requested, self.verify = events, stop, verify
        self.entered, self.release = entered, release
        self.stop_entered, self.stop_release, self.failure = stop_entered, stop_release, failure
        self.stop_calls = 0

    async def start(self):
        self.events.append("start")
        self.verify()
        if self.entered:
            self.entered.set()
            await self.release.wait()
        if self.failure:
            raise self.failure
        self.stop_requested.set()

    async def stop(self):
        self.stop_calls += 1
        self.events.append("stop")
        if self.stop_entered:
            self.stop_entered.set()
            await self.stop_release.wait()
        self.events.append("drained")


@pytest_asyncio.fixture
async def harness(configured, admission, monkeypatch):
    stop, events, prepared, runtimes, callbacks = asyncio.Event(), [], [], [], []
    loop = asyncio.get_running_loop()
    display = Display(events)
    real_prepare = phase.prepare_factory

    def prepare(config):
        assert not admission.available()
        result = real_prepare(config)
        assert type(result) is FirstBootResult
        prepared.append(result)
        return result

    def display_factory():
        assert asyncio.get_running_loop() is loop and not admission.available()
        events.append("display-factory")
        return display

    def runtime_factory(result, controller, verify):
        assert result is prepared[-1] and controller.closing is False
        assert asyncio.get_running_loop() is loop and not admission.available()
        events.append("runtime-factory")
        callbacks.append(verify)
        runtime = Runtime(events, stop, verify)
        runtimes.append(runtime)
        return runtime

    monkeypatch.setattr(phase, "prepare_factory", prepare)
    return SimpleNamespace(stop=stop, events=events, prepared=prepared, runtimes=runtimes,
                           callbacks=callbacks, display=display, prepare=prepare,
                           display_factory=display_factory, runtime_factory=runtime_factory,
                           data=configured.data, configured=configured, admission=admission)


def run(harness, *, display_factory=None, runtime_factory=None):
    return phase.serve_factory_phase_a(
        harness.data, stop_requested=harness.stop,
        display_factory=display_factory or harness.display_factory,
        runtime_factory=runtime_factory or harness.runtime_factory,
    )


async def terminal(coroutine, code="factory_runtime_pending"):
    with pytest.raises(factory_runtime.FactoryRuntimeError) as caught:
        await coroutine
    assert caught.value.code == str(caught.value) == code and caught.value.exit_status == 78


def assert_closed(harness):
    assert all(result.ownership._closed for result in harness.prepared)
    assert harness.admission.available() and harness.admission.child_available()
    assert len(harness.admission.acquisitions) == len(harness.admission.releases)


async def test_prepares_once_and_serves_same_loop_then_exits_pending(harness):
    before_credentials = (harness.data / "credentials.json").read_bytes()
    await terminal(run(harness))
    assert len(harness.prepared) == len(harness.runtimes) == len(harness.callbacks) == 1
    assert harness.runtimes[0].stop_calls == 1
    assert harness.events.index("initialize") < harness.events.index("start")
    assert harness.events.index("drained") < harness.events.index("shutdown")
    assert harness.configured.adapter.inspect_calls == len(harness.configured.adapter.begin_calls) == 1
    assert before_credentials == (harness.data / "credentials.json").read_bytes()
    assert not (harness.data / "inky.sqlite3").exists()
    assert not (harness.data / "provisioning" / "identity.json").exists()
    assert_closed(harness)


async def test_stop_already_requested_has_zero_preparation_display_or_radio(harness):
    harness.stop.set()
    before = snapshot(harness.configured.root)
    await terminal(run(harness))
    assert not harness.events and not harness.prepared and not harness.runtimes
    assert not harness.configured.adapter.inspect_calls and snapshot(harness.configured.root) == before
    assert_closed(harness)


async def test_event_from_another_loop_refuses_before_preparation(harness):
    async def bind_elsewhere():
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(harness.stop.wait(), 0.01)

    await asyncio.to_thread(lambda: asyncio.run(bind_elsewhere()))
    await terminal(run(harness), "factory_runtime_refused")
    assert not harness.events and not harness.prepared and not harness.configured.adapter.inspect_calls
    assert_closed(harness)


async def test_legacy_refuses_without_importing_os_or_selecting(tmp_path, monkeypatch):
    monkeypatch.setattr(factory_writer, "_installed_runtime", lambda: pytest.fail("Legacy imported OS"))
    monkeypatch.setattr(phase, "select_runtime", lambda *_: pytest.fail("Legacy reached selector"))
    await terminal(phase.serve_factory_phase_a(
        tmp_path / "absent", stop_requested=asyncio.Event(),
        display_factory=lambda: pytest.fail("Legacy opened display"),
        runtime_factory=lambda *_: pytest.fail("Legacy opened radio"),
    ), "factory_runtime_refused")


@pytest.mark.parametrize("failure", ["outer", "owned"])
async def test_guard_refusal_precedes_coordinator_and_hardware(harness, monkeypatch, failure):
    load, calls = factory_writer._installed_runtime, []

    def installed():
        calls.append(True)
        if failure == "outer" or len(calls) == 2:
            raise ValueError("private-guard-secret")
        return load()

    monkeypatch.setattr(factory_writer, "_installed_runtime", installed)
    before = snapshot(harness.configured.root)
    await terminal(run(harness), "factory_runtime_refused")
    assert not harness.events and not harness.prepared and not harness.configured.adapter.inspect_calls
    assert snapshot(harness.configured.root) == before
    assert_closed(harness)


async def test_closed_inherited_guard_refuses_before_owned_start(harness):
    with factory_writer.main_writer_guard():
        context = copy_context()
    task = asyncio.create_task(run(harness), context=context)
    await terminal(task, "factory_runtime_refused")
    assert not harness.events and not harness.configured.adapter.inspect_calls
    assert_closed(harness)


async def test_changed_inherited_environment_refuses_before_owned_start(harness, monkeypatch):
    with factory_writer.main_writer_guard():
        context = copy_context()
    monkeypatch.setenv("INKYOS_WRITER_ROLE", "helper")
    await terminal(asyncio.create_task(run(harness), context=context), "factory_runtime_refused")
    assert not harness.events and not harness.configured.adapter.inspect_calls
    assert_closed(harness)


@pytest.mark.parametrize("failure", ["selector", "credentials", "epoch"])
async def test_invalid_prerequisites_have_zero_effects(harness, monkeypatch, failure):
    if failure == "selector":
        monkeypatch.setattr(phase, "select_runtime", lambda *_: None)
    elif failure == "credentials":
        harness.configured.credentials = harness.data / "credentials.json"
        harness.configured.credentials.write_text("{}")
    else:
        monkeypatch.setattr(phase, "_verified_epoch", lambda *_: (_ for _ in ()).throw(ValueError("private")))
    before = snapshot(harness.configured.root)
    await terminal(run(harness), "factory_runtime_refused")
    assert not harness.events and not harness.configured.adapter.inspect_calls
    assert snapshot(harness.configured.root) == before
    assert_closed(harness)


@pytest.mark.parametrize("failure", ["marker", "epoch", "environment"])
async def test_post_prepare_revalidation_closes_store_before_any_display(harness, monkeypatch, failure):
    def prepare(config):
        result = harness.prepare(config)
        if failure == "marker":
            harness.configured.marker.unlink()
        elif failure == "epoch":
            path = harness.data / "credentials.json"
            value = json.loads(path.read_text()) | {"hash": "f" * 64}
            path.write_text(json.dumps(value))
        else:
            monkeypatch.setenv("INKYOS_WRITER_ROLE", "helper")
        return result

    monkeypatch.setattr(phase, "prepare_factory", prepare)
    await terminal(run(harness), "factory_runtime_refused")
    assert len(harness.prepared) == 1 and not harness.events
    assert_closed(harness)


@pytest.mark.parametrize("stage", ["prepare", "display", "runtime"])
async def test_failures_are_fixed_and_all_created_resources_close(harness, monkeypatch, stage):
    if stage == "prepare":
        monkeypatch.setattr(phase, "prepare_factory",
                            lambda *_: (_ for _ in ()).throw(OSError("private-prepare-secret")))
        await terminal(run(harness), "factory_runtime_refused")
        assert not harness.events
    else:
        def fail(*_args):
            raise OSError("private-constructor-secret")

        await terminal(run(harness, **{stage + "_factory": fail}), "factory_runtime_refused")
        assert len(harness.prepared) == 1
        if stage == "runtime":
            assert harness.events.count("shutdown") == 1 and not harness.runtimes
    assert_closed(harness)


async def test_foreign_prepare_result_does_not_gain_cleanup_or_runtime_execution(harness, monkeypatch):
    foreign = SimpleNamespace(ownership=SimpleNamespace(close=lambda: pytest.fail("Foreign cleanup executed")))
    monkeypatch.setattr(phase, "prepare_factory", lambda *_: foreign)
    await terminal(run(harness), "factory_runtime_refused")
    assert not harness.events and not harness.runtimes
    assert_closed(harness)


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize("worker_error", [False, True])
async def test_stop_during_prepare_drains_worker_and_never_opens_display(
    harness, monkeypatch, cancel, worker_error,
):
    entered, release = threading.Event(), threading.Event()

    def prepare(config):
        entered.set()
        assert release.wait(5)
        assert not harness.admission.child_available()
        if worker_error:
            raise OSError("private-worker-after-cancel")
        return harness.prepare(config)

    monkeypatch.setattr(phase, "prepare_factory", prepare)
    task = asyncio.create_task(run(harness))
    assert await asyncio.to_thread(entered.wait, 5)
    try:
        harness.stop.set()
        for _ in range(5):
            if cancel:
                task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and not harness.admission.child_available()
            assert not harness.events
    finally:
        release.set()
    if cancel:
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await terminal(task, "factory_runtime_refused" if worker_error else "factory_runtime_pending")
    assert not harness.events and not harness.runtimes
    assert_closed(harness)


@pytest.mark.parametrize("cancel", [False, True])
async def test_owned_shared_guard_outlives_external_guard_during_prepare(harness, monkeypatch, cancel):
    entered, release = threading.Event(), threading.Event()

    def prepare(config):
        entered.set()
        assert release.wait(5)
        return harness.prepare(config)

    monkeypatch.setattr(phase, "prepare_factory", prepare)
    with factory_writer.main_writer_guard():
        task = asyncio.create_task(run(harness))
        assert await asyncio.to_thread(entered.wait, 5)
    assert len(harness.admission.acquisitions) == 2
    assert len(harness.admission.releases) == 1
    assert not harness.admission.child_available()
    try:
        harness.stop.set()
        if cancel:
            for _ in range(3):
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()
    finally:
        release.set()
    if cancel:
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await terminal(task)
    assert not harness.events
    assert_closed(harness)


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize("worker_error", [False, True])
async def test_stop_during_display_closes_admission_before_worker_drains(
    harness, cancel, worker_error,
):
    entered, release = threading.Event(), threading.Event()
    display = Display(harness.events, entered=entered, release=release,
                      failure=OSError("private-driver-secret") if worker_error else None)
    task = asyncio.create_task(run(harness, display_factory=lambda: display))
    assert await asyncio.to_thread(entered.wait, 5)
    try:
        harness.stop.set()
        for _ in range(5):
            if cancel:
                task.cancel()
            await asyncio.sleep(0)
        assert display.closing and not task.done() and "shutdown" not in harness.events
        assert not harness.admission.child_available() and not harness.runtimes
    finally:
        release.set()
    if cancel:
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await terminal(task, "factory_runtime_refused" if worker_error else "factory_runtime_pending")
    assert harness.events.count("shutdown") == 1 and not harness.runtimes
    assert_closed(harness)


@pytest.mark.parametrize("cancel", [False, True])
async def test_stop_during_runtime_start_and_stop_keeps_lease_to_last_drain(harness, cancel):
    entered, release = asyncio.Event(), asyncio.Event()
    stopping, stop_release = asyncio.Event(), asyncio.Event()
    runtime = Runtime(harness.events, harness.stop, lambda: None, entered=entered, release=release,
                      stop_entered=stopping, stop_release=stop_release)
    task = asyncio.create_task(run(harness, runtime_factory=lambda *_: runtime))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        harness.stop.set()
        await asyncio.wait_for(stopping.wait(), 5)
        assert harness.display.closing and not task.done() and not harness.admission.child_available()
        for _ in range(3):
            if cancel:
                task.cancel()
            await asyncio.sleep(0)
        release.set()
        await asyncio.sleep(0)
        assert "shutdown" not in harness.events and not task.done()
    finally:
        release.set()
        stop_release.set()
    if cancel:
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await terminal(task)
    assert runtime.stop_calls == 1 and harness.events.count("shutdown") == 1
    assert_closed(harness)


async def test_cancel_after_parent_guard_closes_stops_runtime_in_owned_context(harness):
    entered, release = asyncio.Event(), asyncio.Event()
    stopping, stop_release, checks = asyncio.Event(), asyncio.Event(), []

    class CheckingRuntime(Runtime):
        async def stop(self):
            checks.append(self.verify())
            await super().stop()

    def factory(_prepared, _display, verify):
        return CheckingRuntime(harness.events, harness.stop, verify, entered=entered, release=release,
                               stop_entered=stopping, stop_release=stop_release)

    with factory_writer.main_writer_guard():
        task = asyncio.create_task(run(harness, runtime_factory=factory))
        await asyncio.wait_for(entered.wait(), 5)
    assert len(harness.admission.acquisitions) == 2 and len(harness.admission.releases) == 1
    try:
        task.cancel()
        await asyncio.wait_for(stopping.wait(), 5)
        assert checks and harness.display.closing and not harness.admission.child_available()
        release.set()
        for _ in range(5):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and "shutdown" not in harness.events
    finally:
        release.set()
        stop_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert_closed(harness)


@pytest.mark.parametrize("failure", ["epoch", "marker", "lease"])
async def test_runtime_callback_revalidates_credentials_selector_and_owned_lease(harness, failure):
    checked = []

    def runtime_factory(_result, _display, verify):
        if failure == "epoch":
            path = harness.data / "credentials.json"
            path.write_text(json.dumps(json.loads(path.read_text()) | {"hash": "f" * 64}))
        elif failure == "marker":
            harness.configured.marker.unlink()
        else:
            harness.admission.acquisitions[-1].close()
        with pytest.raises((factory_runtime.FactoryRuntimeError, factory_writer.FactoryWriterRefused)):
            verify()
        checked.append(True)
        return Runtime(harness.events, harness.stop, verify)

    await terminal(run(harness, runtime_factory=runtime_factory), "factory_runtime_refused")
    assert checked and "start" not in harness.events
    assert_closed(harness)


async def test_real_ipc_refusal_has_zero_identity_display_or_retry(harness, serve, root_peer, monkeypatch):
    server = serve(lambda connection, request: connection.sendall(encode({
        "v": 1, "id": request["id"], "ok": False, "error": "forbidden",
    })))
    constructions = []

    def client(*args, **kwargs):
        assert not args and not kwargs
        constructions.append(True)
        return ipc.InitializationIPCClient(server.path)

    monkeypatch.setattr(factory_runtime, "InitializationIPCClient", client)
    await terminal(run(harness), "factory_runtime_refused")
    assert len(constructions) == len(root_peer) == len(server.requests) == 1
    assert server.requests[0]["op"] == "initialization.inspect"
    assert not harness.events and not harness.prepared
    assert not list((harness.data / "provisioning").glob("*.json"))
    assert not (harness.data / "provisioning" / "ownership.sqlite3").exists()
    assert_closed(harness)


async def test_real_begin_failure_is_uncertain_without_retry_or_radio(harness, serve, root_peer, monkeypatch):
    def handler(connection, request):
        if request["op"] == "initialization.inspect":
            connection.sendall(encode(success(request)))
        else:
            connection.sendall(encode({"v": 1, "id": request["id"], "ok": False,
                                       "error": "unavailable"}))

    server = serve(handler)
    monkeypatch.setattr(factory_runtime, "InitializationIPCClient",
                        lambda: ipc.InitializationIPCClient(server.path))
    await terminal(run(harness), "factory_runtime_uncertain")
    assert [request["op"] for request in server.requests] == ["initialization.inspect", "initialization.begin"]
    assert len(root_peer) == 2 and not harness.prepared and not harness.events
    assert not (harness.data / "provisioning" / "ownership.sqlite3").exists()
    assert_closed(harness)


async def test_store_cleanup_error_after_cancel_is_observed_before_lease_closes(harness, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    errors = []
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: errors.append(context))

    def prepare(config):
        result = harness.prepare(config)
        original = result.ownership.close

        def close():
            entered.set()
            assert release.wait(5)
            assert not harness.admission.child_available()
            original()
            raise OSError("private-cleanup-secret")

        monkeypatch.setattr(result.ownership, "close", close)
        return result

    monkeypatch.setattr(phase, "prepare_factory", prepare)
    task = asyncio.create_task(run(harness))
    assert await asyncio.to_thread(entered.wait, 5)
    try:
        for _ in range(5):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and not harness.admission.child_available()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)
        assert not errors
        assert_closed(harness)
    finally:
        release.set()
        loop.set_exception_handler(previous)


@pytest.mark.parametrize("early_stop", [False, True])
async def test_final_validation_rejects_epoch_change_in_last_store_drain(harness, monkeypatch, early_stop):
    def prepare(config):
        result = harness.prepare(config)
        original = result.ownership.close

        def close():
            assert not harness.admission.child_available()
            original()
            path = harness.data / "credentials.json"
            path.write_text(json.dumps(json.loads(path.read_text()) | {"hash": "f" * 64}))

        monkeypatch.setattr(result.ownership, "close", close)
        if early_stop:
            harness.stop.set()
        return result

    monkeypatch.setattr(phase, "prepare_factory", prepare)
    await terminal(run(harness), "factory_runtime_refused")
    assert len(harness.prepared) == 1
    if early_stop:
        assert not harness.events and not harness.runtimes
    assert_closed(harness)


@pytest.mark.parametrize("cancel", [False, True])
async def test_stop_during_real_begin_exchange_waits_for_eof_then_closes_store(
    harness, serve, root_peer, monkeypatch, cancel,
):
    entered, release = threading.Event(), threading.Event()
    state = {"status": "authorized"}
    receipt = {"receipt_id": str(uuid4()), "digest": "d" * 64}

    def handler(connection, request):
        nonlocal state
        assert not harness.admission.child_available()
        if request["op"] == "initialization.inspect":
            connection.sendall(encode(success(request, state)))
        else:
            state = {"status": "consumed", "intent": request["intent"], "receipt": receipt}
            connection.sendall(encode(success(request, state | {"status": "newly_consumed"})))
            entered.set()
            assert release.wait(5)

    server = serve(handler)
    monkeypatch.setattr(factory_runtime, "InitializationIPCClient",
                        lambda: ipc.InitializationIPCClient(server.path))
    task = asyncio.create_task(run(harness))
    assert await asyncio.to_thread(entered.wait, 5)
    try:
        harness.stop.set()
        for _ in range(5):
            if cancel:
                task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and not harness.admission.child_available()
            assert not harness.events
    finally:
        release.set()
    if cancel:
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await terminal(task)
    assert len(server.requests) == len(root_peer) == 2
    assert [request["op"] for request in server.requests] == ["initialization.inspect", "initialization.begin"]
    assert len(harness.prepared) == 1 and not harness.events
    assert_closed(harness)


def production_runtime(harness, monkeypatch, *, blocked=None):
    from inky_web.inky.display import DisplayController
    from inky_web.provisioning import bootstrap_screen

    monkeypatch.delenv("INKY_STUDIO_DISPLAY_PROFILE", raising=False)
    payloads, runtimes, ready, radios = [], [], asyncio.Event(), []
    entered, release = threading.Event(), threading.Event()
    registering, registered_release = asyncio.Event(), asyncio.Event()
    original_render = bootstrap_screen.render_qr

    def capture(payload, *dimensions):
        payloads.append(json.loads(payload))
        return original_render(payload, *dimensions)

    monkeypatch.setattr(bootstrap_screen, "render_qr", capture)

    class Driver:
        refreshes = 0

        def set_image(self, image, **_kwargs):
            assert image.size == (800, 480)

        def show(self):
            assert not harness.admission.child_available()
            self.refreshes += 1
            if blocked == "spi" and self.refreshes == 2:
                entered.set()
                assert release.wait(5)

    class Controller(DisplayController):
        def initialize(self):
            super().initialize()
            self._is_mock, self._impl = False, Driver()

    class Radio:
        def __init__(self, transport, _identity, **_kwargs):
            self.transport, self.stopped = transport, False
            radios.append(self)

        async def start(self):
            if blocked == "bluez":
                registering.set()
                await registered_release.wait()
            ready.set()

        async def stop(self):
            self.transport.close()
            self.stopped = True

    def factory(result, display, verify):
        runtime = BootstrapRuntime(result, verify, display, harness.data / "provisioning", server_factory=Radio)
        runtimes.append(runtime)
        return runtime

    async def start():
        ready.clear()
        harness.stop.clear()
        task = asyncio.create_task(run(harness, display_factory=lambda: Controller(mode="mock"),
                                       runtime_factory=factory))
        await asyncio.wait_for(ready.wait(), 5)
        return task, runtimes[-1]

    return SimpleNamespace(start=start, factory=factory, controller=Controller, payloads=payloads,
                           runtimes=runtimes, radios=radios, ready=ready, entered=entered, release=release,
                           registering=registering, registered_release=registered_release)


async def test_real_qr_claim_replay_then_adopted_restart_without_normal_state(harness, monkeypatch):
    candidate = production_runtime(harness, monkeypatch)
    start, payloads = candidate.start, candidate.payloads
    task, runtime = await start()
    claim = {"v": 1, "id": str(uuid4()), "op": "bootstrap.claim", "owner_id": str(uuid4()),
             "owner_token": "b" * 64, "claim_token": payloads[-1]["t"]}
    reply = await runtime.command(claim)
    assert reply["ok"] and reply["result"]["next_step"] == "system_setup"
    assert await runtime.command(claim) == reply
    harness.stop.set()
    await terminal(task)
    binding = harness.prepared[0].prepared_identity.binding
    task, runtime = await start()
    assert harness.prepared[-1].prepared_identity.binding == binding and len(payloads) == 1
    recovered = await runtime.command({"v": 1, "id": str(uuid4()), "op": "bootstrap.status",
                                       "owner_id": claim["owner_id"], "owner_token": claim["owner_token"],
                                       "claim_request_id": claim["id"]})
    assert recovered["ok"] and recovered["result"] == reply["result"]
    harness.stop.set()
    await terminal(task)
    assert all(radio.stopped for radio in candidate.radios)
    assert all(not item.operations.tasks for item in candidate.runtimes)
    with sqlite3.connect(harness.data / "provisioning" / "ownership.sqlite3") as connection:
        assert connection.execute("SELECT state FROM factory_initialization").fetchall() == [("adopted",)]
        assert connection.execute("SELECT owner_id FROM owners").fetchall() == [(claim["owner_id"],)]
    assert not (harness.data / "provisioning" / "identity.json").exists()
    assert_closed(harness)


@pytest.mark.parametrize("blocked", ["sqlite", "spi"])
async def test_real_claim_finishes_under_lease_after_caller_and_session_cancel(harness, monkeypatch, blocked):
    candidate = production_runtime(harness, monkeypatch, blocked=blocked)
    task, runtime = await candidate.start()
    if blocked == "sqlite":
        original = runtime.owners.claim

        def claim(*args, **kwargs):
            candidate.entered.set()
            assert candidate.release.wait(5)
            assert not harness.admission.child_available()
            return original(*args, **kwargs)

        monkeypatch.setattr(runtime.owners, "claim", claim)
    message = {"v": 1, "id": str(uuid4()), "op": "bootstrap.claim", "owner_id": str(uuid4()),
               "owner_token": "b" * 64, "claim_token": candidate.payloads[-1]["t"]}
    caller = asyncio.create_task(runtime.command(message))
    assert await asyncio.to_thread(candidate.entered.wait, 5)
    try:
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        for _ in range(5):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and not harness.admission.child_available()
        assert runtime.display.closing and runtime.display._impl is not None
        assert runtime.display._reservation == "factory-bootstrap"
        assert (await runtime.command(message))["error"] == "service_stopping"
    finally:
        candidate.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not runtime.operations.tasks and candidate.radios[-1].stopped
    assert runtime.display._impl is None and runtime.display._reservation is None
    with sqlite3.connect(harness.data / "provisioning" / "ownership.sqlite3") as connection:
        assert connection.execute("SELECT state FROM factory_initialization").fetchall() == [("adopted",)]
        assert connection.execute("SELECT owner_id FROM owners").fetchall() == [(message["owner_id"],)]
    assert_closed(harness)


async def test_bootstrap_registration_finishes_before_unregister_under_cancel(harness, monkeypatch):
    candidate = production_runtime(harness, monkeypatch, blocked="bluez")
    task = asyncio.create_task(run(
        harness, display_factory=lambda: candidate.controller(mode="mock"), runtime_factory=candidate.factory,
    ))
    await asyncio.wait_for(candidate.registering.wait(), 5)
    runtime = candidate.runtimes[-1]
    try:
        for _ in range(5):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and not harness.admission.child_available()
        assert runtime.display.closing and not runtime.available
        assert not candidate.radios[-1].stopped and runtime.display._impl is not None
    finally:
        candidate.registered_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert candidate.radios[-1].stopped and not runtime.operations.tasks
    assert runtime.display._impl is None and runtime.display._reservation is None
    assert_closed(harness)
