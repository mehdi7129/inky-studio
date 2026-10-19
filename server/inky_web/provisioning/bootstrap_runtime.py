"""Inactive lot A candidate: prepared factory QR -> bootstrap TLS -> claim.

Construct only after the reviewed OS writer/admission boundary. This module is
not an entrypoint and creates no HTTP/network client, normal identity, scheduler,
credential or phase B capability. The existing store remains the sole ledger.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import struct
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import bootstrap_wire as wire
from .bluez import BlueZServer
from .bootstrap_identity import BootstrapIdentityRecoveryRequired, PreparedFactoryIdentity
from .bootstrap_screen import BootstrapScreen
from .bootstrap_tls import BootstrapTLSPeer
from .factory import FactoryRecoveryRequired, FactoryState
from .first_boot import FirstBootResult
from .identity import validate_token
from .ownership import OwnershipError
from .transport import BOOTSTRAP_PROFILE, MAX_MESSAGE, GATTTransport, TransportError

logger = logging.getLogger(__name__)
_DISPLAY_CODES = frozenset({
    "display_unavailable", "display_stopping", "display_busy_timeout", "display_busy_unverified",
    "display_refresh_failed", "display_confirmation_pending", "display_confirmation_interrupted",
    "display_confirmation_storage_failed",
})
_BUSY_PHASES = frozenset({"setup", "power_on", "refresh", "power_off", "standby", "unrecognized"})
_BUSY_OUTCOMES = frozenset({
    "edge_received", "held_high_unverified", "edge_timeout", "edge_unverified", "unrecognized",
    "level_released", "level_timeout", "idle_low_unverified", "refresh_assert_timeout",
    "refresh_completed", "refresh_timeout", "error",
})


def _log_bootstrap_event(stage, display=None, error=None):
    """Fixed startup milestones; refusal diagnostics never format private values."""
    if stage in {"qr_ready", "ble_advertised"}:
        logger.info("Factory bootstrap %s", stage)
        return
    if stage != "qr_refused":
        return
    code = getattr(error, "code", None)
    code = code if type(code) is str and code in _DISPLAY_CODES else "unclassified"
    observations = []
    try:
        snapshot = display.status()
        raw = snapshot.get("observations") if type(snapshot) is dict else None
        if type(raw) is list:
            for item in raw[:8]:
                if type(item) is not dict:
                    continue
                phase, outcome = item.get("phase"), item.get("outcome")
                sequence, timeout = item.get("sequence"), item.get("timeout")
                observations.append({
                    "phase": phase if type(phase) is str and phase in _BUSY_PHASES else "unrecognized",
                    "sequence": sequence if type(sequence) is int and 1 <= sequence <= 8 else None,
                    "outcome": outcome if type(outcome) is str and outcome in _BUSY_OUTCOMES else "unrecognized",
                    "timeout": timeout if type(timeout) in (int, float) and math.isfinite(timeout)
                    and 0 <= timeout <= 120 else None,
                })
    except Exception:
        # Diagnostic access must neither replace the failure nor expose its text.
        observations = []
    logger.warning("Factory bootstrap qr_refused code=%s observations=%s",
                   code, json.dumps(observations, separators=(",", ":")))


class BootstrapApplicationPeer(BootstrapTLSPeer):
    def _decode_message(self, payload: bytes) -> dict:
        # Encoding, duplicate names and framing fail at transport. A readable
        # but invalid schema receives only the fixed runtime error envelope.
        return wire.parse_json(payload)

    async def _dispatch(self, message: dict) -> None:
        try:
            result = await self.handler(message)
            rpc_id = wire.request_id(message)
            if rpc_id is not None and (type(result) is not dict or result.get("id") != rpc_id):
                # A producer knows the readable request's canonical identifier.
                # Null errors remain readable by clients, but cannot be emitted
                # here when that identifier was successfully extracted.
                raise TransportError("Réponse indisponible")
            encoded = json.dumps(result, separators=(",", ":"), allow_nan=False).encode("utf-8")
            if len(encoded) > MAX_MESSAGE:
                raise TransportError("Réponse indisponible")
            content = result.get("result", {}) if type(result) is dict else {}
            context = {
                "rpc_id": rpc_id,
                # Runtime owns and revalidates the actual pinned frame binding;
                # this transport check enforces grammar, not another authority.
                "frame_id": content.get("frame_id") if type(content) is dict else None,
                "owner_id": message.get("owner_id"),
                "claim_request_id": (message.get("id") if message.get("op") == "bootstrap.claim"
                                     else message.get("claim_request_id")),
            }
            if message.get("v") == 2:
                from . import system_setup_wire
                system_setup_wire.decode_response(encoded, operation=message.get("op"), context=context)
            else:
                wire.decode_response(encoded, context=context)
            if not self.closed:
                self.reply.extend(struct.pack("!I", len(encoded)) + encoded)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Normal TLSPeer's legacy fallback is deliberately not inherited:
            # bootstrap encoding/handler failures close without a v1 envelope.
            self.closed = True
            self.plaintext.clear()
            self.reply.clear()
        finally:
            self.task = None


@dataclass(frozen=True)
class BootstrapPublicIdentity:
    frame_id: str
    cert_der: bytes


class OperationRegistry:
    """Global lifetime, independent of disappearing GATT sessions.

    Shielding preserves the real operation, including asyncio.to_thread work.
    The caller may disappear; shutdown must still await the registered task.
    """

    def __init__(self):
        self.tasks: set[asyncio.Task] = set()

    def create(self, coroutine) -> asyncio.Task:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self._done)
        return task

    def _done(self, task):
        self.tasks.discard(task)
        # A disconnected caller cannot leave a background error unobserved.
        if not task.cancelled():
            task.exception()

    async def drain(self):
        while self.tasks:
            await asyncio.gather(*(asyncio.shield(task) for task in tuple(self.tasks)),
                                 return_exceptions=True)


async def _complete(task: asyncio.Task):
    """Cancellation is delivered only after the real shutdown/startup drains."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    if cancelled:
        # Observe errors but preserve the caller's cancellation after drain.
        if not task.cancelled():
            task.exception()
        raise asyncio.CancelledError
    return task.result()


class BootstrapRuntime:
    def __init__(self, result: FirstBootResult, verify_epoch: Callable[[], str], display,
                 directory: Path, *, server_factory=BlueZServer,
                 monotonic: Callable[[], float] = time.monotonic):
        if type(result) is not FirstBootResult:
            raise TypeError("A validated first-boot result is required")
        self.result, self.owners = result, result.ownership
        self.verify_epoch, self.display = verify_epoch, display
        self.directory, self.monotonic = Path(directory), monotonic
        self.screen = BootstrapScreen(display, self.directory, verify_epoch=self._verified_epoch)
        self.server_factory = server_factory
        self.operations = OperationRegistry()
        self.mutation_lock = asyncio.Lock()
        self.transport = None
        self.bluez = None
        self.available = False
        self._admitting = False
        self._started = False
        self._stopping = False
        self._stop_task = None
        self._window_task = None
        self._attempts: deque[float] = deque()

    def _verified_epoch(self) -> str:
        try:
            epoch = self.verify_epoch()
            if type(epoch) is not str:
                raise ValueError()
            validate_token(epoch)
        except Exception:
            raise FactoryRecoveryRequired() from None
        return epoch

    def _verify(self):
        epoch = self._verified_epoch()
        prepared = PreparedFactoryIdentity.reopen(
            self.directory, expected_intent=self.result.prepared_identity.initialization_intent,
            expected_binding=self.result.prepared_identity.binding,
        )
        # Lot A has no phase B closure gate. A published normal identity is
        # deliberately refused instead of reopening bootstrap from ADOPTED.
        if prepared.verify_current_or_unpublished() is not None:
            raise FactoryRecoveryRequired()
        status = self.owners.factory_status()
        if (status.identity != prepared.binding or status.state not in (
                FactoryState.FACTORY, FactoryState.ADOPTED)):
            raise FactoryRecoveryRequired()
        return prepared, status, epoch

    async def start(self):
        if self._started or self._stopping:
            raise RuntimeError("Bootstrap runtime cannot be restarted")
        self._started = True
        task = self.operations.create(self._start())
        try:
            await _complete(task)
        except BaseException:
            await self.stop()
            raise

    async def _show_qr(self, payload):
        try:
            await asyncio.to_thread(self.screen.show_qr, payload)
        except Exception as error:
            _log_bootstrap_event("qr_refused", self.display, error)
            raise
        _log_bootstrap_event("qr_ready")

    async def _start(self):
        async with self.mutation_lock:
            prepared, status, epoch = await asyncio.to_thread(self._verify)
            await asyncio.to_thread(self.screen.reserve)
            context = await asyncio.to_thread(prepared.bootstrap_tls_context)
            identity = BootstrapPublicIdentity(prepared.frame_id, prepared.bootstrap_certificate_der)
            self.transport = GATTTransport(context, self.command, profile=BOOTSTRAP_PROFILE,
                                           peer_factory=BootstrapApplicationPeer)
            self.bluez = self.server_factory(self.transport, identity, profile=BOOTSTRAP_PROFILE)
            if status.state == FactoryState.FACTORY:
                token = await asyncio.to_thread(self.owners.open_factory_window, expected_epoch=epoch)
                deadline = self.monotonic() + 600
                try:
                    payload = wire.encode_qr(prepared.frame_id, prepared.binding.spki_sha256, token.value)
                    await self._show_qr(payload)
                except BaseException:
                    await asyncio.to_thread(self.owners.close_window)
                    raise
                self._window_task = asyncio.create_task(self._expire_window(deadline))
            else:
                await asyncio.to_thread(self.screen.show_status, adopted=True)
            if self._stopping:
                return
            # A completed QR refresh is not a reusable admission for a new
            # radio registration. Once started, registration remains owned by
            # this startup task and shutdown must drain it before unregister.
            await asyncio.to_thread(self._verified_epoch)
            if self._stopping:
                return
            await self.bluez.start()
            _log_bootstrap_event("ble_advertised")
            if not self._stopping:
                await asyncio.to_thread(self._verified_epoch)
            if not self._stopping:
                self.available = self._admitting = True

    async def _expire_window(self, deadline):
        try:
            await asyncio.sleep(max(0, deadline - self.monotonic()))
            task = self.operations.create(self._expire_screen())
            await asyncio.shield(task)
        except asyncio.CancelledError:
            return

    async def _expire_screen(self):
        async with self.mutation_lock:
            try:
                await asyncio.to_thread(self.owners.close_window)
                if not self._stopping:
                    status = await asyncio.to_thread(self.owners.factory_status)
                    await asyncio.to_thread(self.screen.show_status,
                                            adopted=status.state == FactoryState.ADOPTED)
            except Exception:
                # Corrupt durable state may prevent even window deletion. Keep
                # no radio admission open while recovery is required.
                self._fail_closed()

    def _fail_closed(self):
        self._admitting = self.available = False
        if self.transport:
            self.transport.close()

    def _claim_allowed(self):
        now = self.monotonic()
        while self._attempts and now - self._attempts[0] >= 60:
            self._attempts.popleft()
        if len(self._attempts) >= 12:
            return False
        self._attempts.append(now)
        return True

    async def command(self, message: dict) -> dict:
        rpc_id = wire.request_id(message)
        try:
            message = wire.validate_request(message)
        except wire.WireError:
            return self._error(rpc_id, "invalid_request")
        if not self._admitting or self._stopping or self.display.closing:
            return self._error(rpc_id, "service_stopping")
        # Removed sessions do not release admitted operations. Bound that
        # global backlog too, so repeated reconnects cannot queue unbounded
        # SQLite work behind a stalled durable transaction/SPI refresh.
        if len(self.operations.tasks) >= 2:
            return self._error(rpc_id, "unavailable")
        # Admission and registry insertion contain no await: stop() cannot pass
        # between them and accidentally lose an admitted transaction.
        task = self.operations.create(self._execute(message))
        return await asyncio.shield(task)

    async def _execute(self, message):
        rpc_id = message["id"]
        try:
            async with self.mutation_lock:
                prepared, status, epoch = await asyncio.to_thread(self._verify)
                if message["op"] == "bootstrap.claim":
                    if not self._claim_allowed():
                        raise OwnershipError("rate_limited")
                    result = await asyncio.to_thread(
                        self.owners.claim, message["claim_token"], message["owner_id"],
                        message["owner_token"], rpc_id, epoch,
                    )
                    claim_id = result.request_id
                    status = await asyncio.to_thread(self.owners.factory_status)
                    if status.state != FactoryState.ADOPTED or status.first_owner_id != result.owner_id:
                        raise FactoryRecoveryRequired()
                    self._cancel_window_timer()
                    # Failure here leaves the durable winning claim intact.
                    # Close admission and let the same owner recover next boot.
                    if not self._stopping:
                        try:
                            await asyncio.to_thread(self.screen.show_status, adopted=True)
                        except Exception:
                            self._fail_closed()
                            await asyncio.to_thread(self.owners.close_window)
                            raise
                else:
                    result = await asyncio.to_thread(
                        self.owners.status, message["owner_id"], message["owner_token"],
                        request_id=message["claim_request_id"],
                    )
                    claim_id = result.request_id
                    status = await asyncio.to_thread(self.owners.factory_status)
                    if status.state != FactoryState.ADOPTED or status.first_owner_id != result.owner_id:
                        raise FactoryRecoveryRequired()
                return {"v": 1, "id": rpc_id, "ok": True, "result": {
                    "frame_id": prepared.frame_id, "owner_id": result.owner_id,
                    "claim_request_id": claim_id, "factory_state": "adopted",
                    "next_step": "system_setup",
                }}
        except OwnershipError as exc:
            code = ("qr_unavailable" if exc.code == "factory_not_ready" else
                    exc.code if exc.code in wire.PUBLIC_ERRORS else "invalid_request")
        except (FactoryRecoveryRequired, BootstrapIdentityRecoveryRequired):
            self._fail_closed()
            code = "recovery_required"
        except (TypeError, ValueError):
            code = "invalid_request"
        except Exception:
            code = "unavailable"
        return self._error(rpc_id, code)

    @staticmethod
    def _error(rpc_id, code):
        return {"v": 1, "id": rpc_id, "ok": False, "error": code}

    def _cancel_window_timer(self):
        task, self._window_task = self._window_task, None
        if task is not None:
            task.cancel()

    async def stop(self):
        if self._stop_task is None:
            self._stopping = True
            self._fail_closed()
            self._cancel_window_timer()
            self._stop_task = asyncio.create_task(self._stop())
        await _complete(self._stop_task)

    async def _stop(self):
        try:
            # Drain startup too: a concurrent RegisterApplication must finish
            # before its corresponding unregister, never reopen after stop.
            await self.operations.drain()
        finally:
            try:
                if self.bluez:
                    await self.bluez.stop()
            finally:
                try:
                    await asyncio.to_thread(self.owners.close)
                finally:
                    await asyncio.to_thread(self.screen.release)
