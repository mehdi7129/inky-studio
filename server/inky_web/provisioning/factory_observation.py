"""Explicit, inactive observation of IPC-A; never initialization authority.

No installed entry point calls this API. A successful result describes one
completed inspect exchange after its socket and owned SH scope have closed.
It cannot authorize begin, recreate a ledger, or activate a bootstrap runtime.
"""
from __future__ import annotations

import asyncio
import secrets
from contextlib import suppress
from contextvars import Context
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .factory_runtime import FactoryRuntimeError, _verified_epoch, select_runtime
from .factory_writer import main_writer_guard
from .first_boot import _receipt_response
from .initialization_ipc import InitializationIPCClient


@dataclass(frozen=True)
class InitializationServiceObservation:
    receipt_state: Literal["authorized", "consumed"]

    def __post_init__(self) -> None:
        if type(self.receipt_state) is not str or self.receipt_state not in {"authorized", "consumed"}:
            raise FactoryRuntimeError()


async def _drain(task: asyncio.Task):
    """Cancellation cannot abandon a task or its blocking transport worker."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    if cancelled:
        with suppress(BaseException):
            task.result()
        raise asyncio.CancelledError()
    return task.result()


def _inspect(data_directory: Path) -> InitializationServiceObservation:
    # to_thread copies the isolated owner's Context, including its live lease.
    with main_writer_guard() as lease:
        if lease is None:
            raise FactoryRuntimeError()
        lease.check()
        config = select_runtime(data_directory)
        if config is None:
            raise FactoryRuntimeError()
        epoch = _verified_epoch(config)
        # Re-entry verifies the environment after the local prerequisites too.
        with main_writer_guard():
            lease.check()
        state, _, _ = _receipt_response(
            InitializationIPCClient().inspect_initialization(), inspect=True,
        )
        # inspect has returned only after EOF and closing the connected socket.
        with main_writer_guard():
            lease.check()
            if not secrets.compare_digest(epoch, _verified_epoch(config)):
                raise FactoryRuntimeError()
        with main_writer_guard():
            lease.check()
        return InitializationServiceObservation(state)


async def _observe_owned(data_directory: Path) -> InitializationServiceObservation:
    # A fresh Context means this task owns a new SH, never a caller's inherited
    # lease. The external caller may leave its guard while this worker runs.
    with main_writer_guard() as lease:
        if lease is None:
            raise FactoryRuntimeError()
        lease.check()
        worker = asyncio.create_task(asyncio.to_thread(_inspect, data_directory))
        result = await _drain(worker)
        with main_writer_guard():
            lease.check()
        return result


async def observe_initialization_service(data_directory: Path) -> InitializationServiceObservation:
    """Inspect once under independent admission; return no reusable authority.

    Validate an inherited caller context before starting any operation, then
    retain our own SH until the real transport worker has finished. Repeated
    cancellation is propagated only after that drain. Legacy callers refuse.
    """
    try:
        with main_writer_guard() as caller_lease:
            if caller_lease is None:
                raise FactoryRuntimeError()
            caller_lease.check()
            task = asyncio.create_task(_observe_owned(Path(data_directory)), context=Context())
            return await _drain(task)
    except Exception:
        raise FactoryRuntimeError() from None
