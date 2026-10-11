"""Inactive, explicitly injected phase A lifecycle; no installed activation.

The retained main writer lease protects this process's owned effects. It does
not qualify the installed helper/IPC graph or turn FirstBootResult into an OS
grant. Installed initialize_factory remains a terminal pending refusal.
"""
from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable
from contextlib import suppress
from contextvars import Context, copy_context
from pathlib import Path
from typing import NoReturn, cast

from inky_web.inky.display import DisplayController

from .connected_peer import ConnectedPeerGuard
from .factory_runtime import FactoryRuntimeError, _verified_epoch, prepare_factory, select_runtime
from .factory_session import FactorySessionRuntime, serve_prepared_factory
from .factory_writer import main_writer_guard
from .first_boot import FirstBootResult


async def _drain(task: asyncio.Task, on_cancel: Callable[[], None] = lambda: None):
    """Observe even an error after cancellation before relinquishing ownership."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
            # A faulty injected admission closer must not orphan the owner.
            with suppress(Exception):
                on_cancel()
        except Exception:
            break
    if cancelled:
        with suppress(BaseException):
            task.result()
        raise asyncio.CancelledError()
    return task.result()


class _Lifetime:
    def __init__(self, stop_requested: asyncio.Event):
        self.stop_requested = stop_requested
        self.loop = asyncio.get_running_loop()
        self.display: DisplayController | None = None
        self.runtime: _OwnedRuntime | None = None

    def close_admission(self) -> None:
        # DisplayController's gate is a threading.Event: close it before
        # scheduling loop-owned Event/BlueZ work from a credential callback.
        try:
            if self.display is not None:
                self.display.begin_shutdown()
        finally:
            def stop_on_loop() -> None:
                self.stop_requested.set()
                if self.runtime is not None:
                    self.runtime.begin_stop()

            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None
            if current_loop is self.loop:
                stop_on_loop()
            else:
                self.loop.call_soon_threadsafe(stop_on_loop)

    async def watch_stop(self) -> None:
        await self.stop_requested.wait()
        self.close_admission()


class _GuardedDisplay:
    """Validate startup boundaries without changing the controller's drains."""

    def __init__(self, display: DisplayController, verify_epoch: Callable[[], str],
                 stop_requested: asyncio.Event):
        self.display, self.verify_epoch, self.stop_requested = display, verify_epoch, stop_requested

    def __getattr__(self, name):
        return getattr(self.display, name)

    def initialize(self) -> None:
        self.verify_epoch()
        if not self.stop_requested.is_set():
            self.display.initialize()
        self.verify_epoch()

    def require_available(self) -> None:
        self.verify_epoch()
        if not self.stop_requested.is_set():
            self.display.require_available()


class _OwnedRuntime:
    """Share one shutdown between the stop watcher and the session's finally."""

    def __init__(self, runtime: FactorySessionRuntime, verify_epoch: Callable[[], str],
                 lifetime: _Lifetime):
        self.runtime, self.verify_epoch, self.lifetime = runtime, verify_epoch, lifetime
        self.context = copy_context()
        self.stop_task: asyncio.Task | None = None

    async def start(self) -> None:
        self.verify_epoch()
        if self.lifetime.stop_requested.is_set():
            return
        await self.runtime.start()
        self.verify_epoch()

    def begin_stop(self) -> None:
        if self.stop_task is None:
            self.stop_task = asyncio.create_task(self.runtime.stop(), context=self.context.copy())

    async def stop(self) -> None:
        self.begin_stop()
        assert self.stop_task is not None
        await _drain(self.stop_task)


async def _serve_owned(
    data_directory: Path,
    lifetime: _Lifetime,
    display_factory: Callable[[], DisplayController],
    runtime_factory: Callable[
        [FirstBootResult, DisplayController, Callable[[], str]], FactorySessionRuntime,
    ],
    admission_check: Callable[[], None],
    initialization_peer_guard: ConnectedPeerGuard,
) -> None:
    with main_writer_guard() as lease:
        if lease is None:
            raise FactoryRuntimeError()
        lease.check()

        def check_admission() -> None:
            try:
                with main_writer_guard():
                    lease.check()
                    if admission_check() is not None:
                        raise FactoryRuntimeError()
                    lease.check()
            except Exception:
                lifetime.close_admission()
                raise FactoryRuntimeError() from None

        check_admission()
        config = select_runtime(data_directory)
        if config is None:
            raise FactoryRuntimeError()
        check_admission()
        expected_epoch = _verified_epoch(config)
        check_admission()

        def verify_epoch() -> str:
            # Runtime mutations run in to_thread, which inherits this owner's
            # live Context. Re-entry also checks the complete writer handoff.
            try:
                with main_writer_guard():
                    lease.check()
                    check_admission()
                    current = _verified_epoch(config)
                    check_admission()
                    if not secrets.compare_digest(expected_epoch, current):
                        raise FactoryRuntimeError()
                    lease.check()
                    return current
            except Exception:
                lifetime.close_admission()
                raise FactoryRuntimeError() from None

        prepared: FirstBootResult | None = None
        session_started = False
        pending = False
        watcher = asyncio.create_task(lifetime.watch_stop())
        try:
            # Establish the supplied Event's loop before any preparation. A
            # foreign-loop Event must refuse without starting a thread effect.
            await asyncio.sleep(0)
            if watcher.done():
                watcher.result()
            verify_epoch()
            if lifetime.stop_requested.is_set():
                pending = True
                return

            def prepare() -> FirstBootResult:
                verify_epoch()
                return prepare_factory(
                    config, admission_check=check_admission,
                    initialization_peer_guard=initialization_peer_guard,
                )

            # No cancellation of the coordinator: its one-use begin may have
            # been consumed even if the caller disappears during the exchange.
            candidate = await _drain(asyncio.create_task(asyncio.to_thread(prepare)))
            if type(candidate) is not FirstBootResult:
                raise FactoryRuntimeError()
            prepared = candidate
            verify_epoch()
            if lifetime.stop_requested.is_set():
                pending = True
                return
            lifetime.display = display_factory()
            guarded_display = cast(DisplayController, _GuardedDisplay(
                lifetime.display, verify_epoch, lifetime.stop_requested,
            ))
            verify_epoch()

            def runtime(result, controller):
                verify_epoch()
                wrapped = _OwnedRuntime(runtime_factory(result, controller, verify_epoch),
                                        verify_epoch, lifetime)
                lifetime.runtime = wrapped
                return wrapped

            session_started = True
            await serve_prepared_factory(
                prepared, display=guarded_display, stop_requested=lifetime.stop_requested,
                runtime_factory=runtime,
            )
            pending = True
        finally:
            # Keep the independent SH while every owned async/thread resource
            # finishes, including stores prepared without constructing a radio.
            try:
                lifetime.close_admission()
            finally:
                try:
                    if lifetime.runtime is not None:
                        await _drain(asyncio.create_task(lifetime.runtime.stop()))
                finally:
                    try:
                        if lifetime.display is not None and not session_started:
                            await _drain(asyncio.create_task(asyncio.to_thread(lifetime.display.shutdown)))
                    finally:
                        try:
                            if prepared is not None:
                                await _drain(asyncio.create_task(asyncio.to_thread(prepared.ownership.close)))
                        finally:
                            if not watcher.done():
                                watcher.cancel()
                            with suppress(asyncio.CancelledError):
                                await _drain(watcher)
                            # Early STOP returns execute this finally too. Do
                            # not replace an uncertain preparation diagnostic;
                            # only a clean terminal path is eligible for pending.
                            if pending:
                                verify_epoch()


async def serve_factory_phase_a(
    data_directory: Path,
    *,
    stop_requested: asyncio.Event,
    display_factory: Callable[[], DisplayController],
    runtime_factory: Callable[
        [FirstBootResult, DisplayController, Callable[[], str]], FactorySessionRuntime,
    ],
    admission_check: Callable[[], None],
    initialization_peer_guard: ConnectedPeerGuard,
) -> NoReturn:
    """Compose candidates on this event loop, then exit pending or refuse.

    This seam has no installed caller or defaults selecting a driver/radio. A
    future installed wrapper still requires the separately qualified OS graph.
    Cancellation closes admission immediately and wins only after owned drains.
    """
    lifetime = _Lifetime(stop_requested)
    try:
        if not callable(admission_check) or not callable(initialization_peer_guard):
            raise FactoryRuntimeError()
        with main_writer_guard() as caller_lease:
            if caller_lease is None:
                raise FactoryRuntimeError()
            caller_lease.check()
            task = asyncio.create_task(_serve_owned(
                Path(data_directory), lifetime, display_factory, runtime_factory,
                admission_check, initialization_peer_guard,
            ), context=Context())
            await _drain(task, lifetime.close_admission)
    except FactoryRuntimeError:
        raise
    except Exception:
        raise FactoryRuntimeError() from None
    raise FactoryRuntimeError("factory_runtime_pending")
