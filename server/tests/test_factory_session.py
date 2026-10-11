"""Lifecycle ownership tests: inert adapters only, no radio or GPIO."""
from __future__ import annotations

import asyncio
import sqlite3
import threading
from typing import cast
from uuid import uuid4

import pytest

from inky_web.provisioning.factory_session import serve_prepared_factory
from inky_web.provisioning.first_boot import FirstBootResult


@pytest.fixture(autouse=True)
def inky_env(tmp_path, monkeypatch):
    # Do not inherit conftest's eager normal DB initialization.
    monkeypatch.setenv("INKY_STUDIO_DATA_DIR", str(tmp_path / "normal-state"))
    monkeypatch.delenv("INKY_STUDIO_DISABLE_AUTH", raising=False)
    from inky_web import auth, db
    from inky_web.provisioning import identity

    def forbidden(*_args, **_kwargs):
        pytest.fail("Factory session admitted normal application state")

    monkeypatch.setattr(db, "init_db", forbidden)
    monkeypatch.setattr(db, "data_dir", forbidden)
    monkeypatch.setattr(auth, "load_or_create_credentials", forbidden)
    monkeypatch.setattr(identity, "load_or_create_identity", forbidden)
    yield tmp_path
    assert not (tmp_path / "normal-state").exists()


class InertDisplay:
    def __init__(self, events, *, failure=None, entered=None, release=None):
        self.events, self.failure = events, failure
        self.entered, self.release = entered, release

    def initialize(self):
        self.events.append("initialize")
        if self.entered:
            self.entered.set()
            assert self.release.wait(5)

    def require_available(self):
        self.events.append("available")
        if self.failure:
            raise self.failure

    def begin_shutdown(self):
        self.events.append("close-admission")

    def shutdown(self):
        self.events.append("shutdown")


class InertRuntime:
    def __init__(self, events, stop_requested, *, failure=None, stopping=None, release=None):
        self.events, self.stop_requested, self.failure = events, stop_requested, failure
        self.stopping, self.release = stopping, release

    async def start(self):
        self.events.append("start")
        if self.failure:
            raise self.failure
        self.stop_requested.set()

    async def stop(self):
        self.events.append("stop")
        if self.stopping:
            self.stopping.set()
            await self.release.wait()
        self.events.append("drained")


def session(events, stop, display, **options):
    prepared = cast(FirstBootResult, object())

    def runtime_factory(received, controller):
        assert received is prepared and controller is display
        return InertRuntime(events, stop, **options)

    return serve_prepared_factory(prepared, display=display, stop_requested=stop,
                                  runtime_factory=runtime_factory)


async def test_lifecycle_checks_display_before_radio_and_drains_before_shutdown():
    events, stop = [], asyncio.Event()
    await session(events, stop, InertDisplay(events))
    assert events == ["initialize", "available", "start", "close-admission", "stop", "drained", "shutdown"]


async def test_requested_stop_never_initializes_or_admits_runtime():
    events, stop = [], asyncio.Event()
    stop.set()
    await session(events, stop, InertDisplay(events))
    assert events == ["close-admission", "shutdown"]


async def test_hardware_initialization_failure_prevents_radio_admission():
    events, stop = [], asyncio.Event()
    with pytest.raises(OSError, match="inert device unavailable"):
        await session(events, stop, InertDisplay(events, failure=OSError("inert device unavailable")))
    assert events == ["initialize", "available", "close-admission", "shutdown"]


async def test_partial_runtime_start_is_still_drained():
    events, stop = [], asyncio.Event()
    with pytest.raises(OSError, match="inert radio unavailable"):
        await session(events, stop, InertDisplay(events), failure=OSError("inert radio unavailable"))
    assert events == ["initialize", "available", "start", "close-admission", "stop", "drained", "shutdown"]


async def test_repeated_cancellation_during_initialize_retains_hardware_ownership():
    events, stop = [], asyncio.Event()
    entered, release = threading.Event(), threading.Event()
    task = asyncio.create_task(session(events, stop, InertDisplay(events, entered=entered, release=release)))
    assert await asyncio.to_thread(entered.wait, 5)
    try:
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert events == ["initialize"]
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == ["initialize", "close-admission", "shutdown"]


async def test_repeated_cancellation_during_stop_retains_runtime_and_display_ownership():
    events, stop = [], asyncio.Event()
    stopping, release = asyncio.Event(), asyncio.Event()
    task = asyncio.create_task(session(events, stop, InertDisplay(events), stopping=stopping, release=release))
    await asyncio.wait_for(stopping.wait(), 5)
    try:
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert "shutdown" not in events
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events[-4:] == ["close-admission", "stop", "drained", "shutdown"]


@pytest.mark.parametrize("blocked_operation", ["sqlite", "spi"])
async def test_real_runtime_session_drains_claim_and_controller_without_normal_state(
    tmp_path, monkeypatch, blocked_operation,
):
    from inky_web.inky.display import DisplayController
    from inky_web.provisioning import bootstrap_screen
    from inky_web.provisioning.bootstrap_runtime import BootstrapRuntime
    from inky_web.provisioning.first_boot import FirstBootCoordinator

    monkeypatch.delenv("INKY_STUDIO_DISPLAY_PROFILE", raising=False)
    directory, epoch = tmp_path / "factory", "e" * 64
    entered, release, advertised, stop = threading.Event(), threading.Event(), asyncio.Event(), asyncio.Event()
    qr_payloads, runtimes = [], []

    class SyntheticOS:
        receipt = {"receipt_id": str(uuid4()), "digest": "d" * 64}

        def inspect_initialization(self):
            return {"status": "authorized"}

        def begin_initialization(self, intent):
            return {"status": "newly_consumed", "intent": intent, "receipt": self.receipt}

    class InertDriver:
        refreshes = 0

        def set_image(self, image, **_kwargs):
            assert image.size == (800, 480)

        def show(self):
            self.refreshes += 1
            if blocked_operation == "spi" and self.refreshes == 2:
                entered.set()
                assert release.wait(5)

    class ControlledDisplay(DisplayController):
        def initialize(self):
            # Use the production controller and operation lock, replacing only
            # physical device selection/output. Never import GPIO/SPI modules.
            super().initialize()
            self._is_mock, self._impl = False, InertDriver()

    class SyntheticBlueZ:
        def __init__(self, transport, _identity, **_kwargs):
            self.transport = transport

        async def start(self):
            advertised.set()

        async def stop(self):
            self.transport.close()

    original_render = bootstrap_screen.render_qr

    def capture_qr(payload, *dimensions):
        qr_payloads.append(payload)
        return original_render(payload, *dimensions)

    monkeypatch.setattr(bootstrap_screen, "render_qr", capture_qr)
    prepared = FirstBootCoordinator(directory, SyntheticOS(), lambda: epoch).initialize()
    display = ControlledDisplay(mode="mock")

    def runtime_factory(result, controller):
        runtime = BootstrapRuntime(result, lambda: epoch, controller, directory, server_factory=SyntheticBlueZ)
        runtimes.append(runtime)
        return runtime

    session_task = asyncio.create_task(serve_prepared_factory(
        prepared, display=display, stop_requested=stop, runtime_factory=runtime_factory,
    ))
    await asyncio.wait_for(advertised.wait(), 5)
    runtime = runtimes[0]

    async def admitted():
        # BlueZ registration precedes the runtime's final admission check.
        # Exercise claim lifetime only once that check has opened admission.
        while not runtime.available:
            if session_task.done():
                await session_task
            await asyncio.sleep(0.001)

    await asyncio.wait_for(admitted(), 5)
    if blocked_operation == "sqlite":
        original_claim = prepared.ownership.claim

        def blocked_claim(*args, **kwargs):
            entered.set()
            assert release.wait(5)
            return original_claim(*args, **kwargs)

        monkeypatch.setattr(prepared.ownership, "claim", blocked_claim)
    import json

    owner, claim = str(uuid4()), str(uuid4())
    command_task = asyncio.create_task(runtime.command({
        "v": 1, "id": claim, "op": "bootstrap.claim", "owner_id": owner,
        "owner_token": "b" * 64, "claim_token": json.loads(qr_payloads[0])["t"],
    }))
    assert await asyncio.to_thread(entered.wait, 5)
    try:
        command_task.cancel()  # Disappearing caller does not own the transaction.
        with pytest.raises(asyncio.CancelledError):
            await command_task
        stop.set()
        for _ in range(3):
            session_task.cancel()
            await asyncio.sleep(0)
            assert not session_task.done()
            assert display._impl is not None
            assert display._reservation == "factory-bootstrap"
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await session_task
    assert display._impl is None and display._reservation is None
    assert not runtime.operations.tasks
    with sqlite3.connect(directory / "ownership.sqlite3") as connection:
        assert connection.execute("SELECT state FROM factory_initialization").fetchone() == ("adopted",)
        assert connection.execute("SELECT owner_id FROM owners").fetchall() == [(owner,)]
