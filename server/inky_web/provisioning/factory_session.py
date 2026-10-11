"""Inert factory lifecycle seam; deliberately unused by installed entry points.

The caller owns OS admission and its lifetime lease. A FirstBootResult only
proves local durable preparation and cannot substitute for that OS contract.
This module neither selects startup nor initializes normal application state.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Protocol, TypeVar

from inky_web.inky.display import DisplayController

from .first_boot import FirstBootResult

_T = TypeVar("_T")


class FactorySessionRuntime(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...


async def _drain(task: asyncio.Task[_T]) -> _T:
    """Repeated cancellation never releases ownership before worker completion."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


async def serve_prepared_factory(
    prepared: FirstBootResult,
    *,
    display: DisplayController,
    stop_requested: asyncio.Event,
    runtime_factory: Callable[[FirstBootResult, DisplayController], FactorySessionRuntime],
) -> None:
    """Run an explicitly injected candidate, draining radio/SQLite/SPI at exit.

    This callable is a testable integration seam, not an activation API. There
    is no CLI/env option or call from run/serve/lifespan. The outer caller must
    already hold a qualified OS lease and retain it until this returns.
    """
    runtime: FactorySessionRuntime | None = None
    try:
        if stop_requested.is_set():
            return
        await _drain(asyncio.create_task(asyncio.to_thread(display.initialize)))
        display.require_available()
        if stop_requested.is_set():
            return
        runtime = runtime_factory(prepared, display)
        await _drain(asyncio.create_task(runtime.start()))
        await stop_requested.wait()
    finally:
        # Close hardware admission immediately, before awaiting asynchronous
        # shutdown. In-flight operations are still owned until both drains end.
        display.begin_shutdown()
        try:
            if runtime is not None:
                await _drain(asyncio.create_task(runtime.stop()))
        finally:
            await _drain(asyncio.create_task(asyncio.to_thread(display.shutdown)))
