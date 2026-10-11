"""Bounded structured client for the separately privileged network helper."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import time

from .connected_peer import ConnectedPeerGuard, connected_peer_scope

_RESPONSE_LIMIT = 16384
_SYNC_DEADLINE_SECONDS = 15
_ASYNC_DEADLINE_SECONDS = 20


def _response_complete(raw: bytes) -> bool:
    return len(raw) <= _RESPONSE_LIMIT and raw.endswith(b"\n") and raw.count(b"\n") == 1


def _read_attested_sync(connection: socket.socket, deadline: float) -> bytes:
    raw = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        connection.settimeout(remaining)
        chunk = connection.recv(min(4096, _RESPONSE_LIMIT + 1 - len(raw)))
        if not chunk:
            break
        raw.extend(chunk)
        if len(raw) > _RESPONSE_LIMIT or (b"\n" in raw and raw.find(b"\n") != len(raw) - 1):
            raise ValueError
    if not _response_complete(raw):
        raise ValueError
    return bytes(raw)


async def _read_attested_async(reader: asyncio.StreamReader) -> bytes:
    raw = bytearray()
    while True:
        chunk = await reader.read(min(4096, _RESPONSE_LIMIT + 1 - len(raw)))
        if not chunk:
            break
        raw.extend(chunk)
        if len(raw) > _RESPONSE_LIMIT or (b"\n" in raw and raw.find(b"\n") != len(raw) - 1):
            raise NetworkUnavailable("network_response_invalid")
    if not _response_complete(raw):
        raise NetworkUnavailable("network_response_invalid")
    return bytes(raw)


async def _close_writer_owned(writer: asyncio.StreamWriter, *, cancelled: bool) -> None:
    """Drain closure under the proof, even if the awaiting caller is cancelled again."""
    writer.close()
    task = asyncio.create_task(writer.wait_closed())
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            # Observe the result below; no cleanup task is abandoned.
            break
    try:
        task.result()
    except BaseException:
        if cancelled:
            raise asyncio.CancelledError from None
        raise
    if cancelled:
        raise asyncio.CancelledError


class NetworkUnavailable(Exception):
    pass


class NetworkClient:
    def __init__(self, path: str | None = None, *, peer_guard: ConnectedPeerGuard | None = None):
        self.path = path or os.environ.get("INKY_NETWORK_SOCKET", "/run/inky-network/control.sock")
        self.peer_guard = peer_guard

    def cancel_pending_sync(self) -> None:
        """Called only by the password-rotation worker, after password proof.

        Complete rollback before committing the credential epoch. Failure aborts
        rotation: a previously confirmed but unfinished activation cannot later
        commit on behalf of a newly revoked owner.
        """
        try:
            deadline = time.monotonic() + _SYNC_DEADLINE_SECONDS
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(_SYNC_DEADLINE_SECONDS)
                connection.connect(self.path)
                with connected_peer_scope(connection, self.peer_guard):
                    try:
                        if self.peer_guard is not None:
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise TimeoutError
                            connection.settimeout(remaining)
                        connection.sendall(b'{"op":"cancel_pending"}\n')
                        if self.peer_guard is None:
                            with connection.makefile("rb") as source:
                                raw = source.readline(16385)
                        else:
                            raw = _read_attested_sync(connection, deadline)
                        if len(raw) > 16384 or not raw.endswith(b"\n"):
                            raise ValueError
                        result = json.loads(raw)
                        if result.get("ok") is not True or type(result.get("result", {}).get("cancelled")) is not bool:
                            raise ValueError
                    finally:
                        connection.close()
        except Exception:
            raise NetworkUnavailable("network_unavailable") from None

    async def call(self, operation: str, **arguments) -> dict:
        writer = None
        closed = False
        cancelled = False
        deadline = asyncio.get_running_loop().time() + _ASYNC_DEADLINE_SECONDS
        try:
            async with asyncio.timeout_at(deadline):
                reader, writer = await asyncio.open_unix_connection(self.path, limit=16385)
            connection = writer.get_extra_info("socket")
            if self.peer_guard is not None and connection is None:
                raise NetworkUnavailable("network_unavailable")
            with connected_peer_scope(connection, self.peer_guard):
                try:
                    async with asyncio.timeout_at(deadline):
                        payload = json.dumps({"op": operation, **arguments}, separators=(",", ":"), allow_nan=False).encode()
                        if len(payload) > 8192:
                            raise NetworkUnavailable("network_request_invalid")
                        if asyncio.get_running_loop().time() >= deadline:
                            raise TimeoutError
                        writer.write(payload + b"\n")
                        await writer.drain()
                        raw = (await reader.readline() if self.peer_guard is None
                               else await _read_attested_async(reader))
                        if not raw.endswith(b"\n") or len(raw) > 16384:
                            raise NetworkUnavailable("network_response_invalid")
                        result = json.loads(raw)
                        if not isinstance(result, dict) or result.get("ok") is not True:
                            # Helper errors are a fixed vocabulary, never raw D-Bus text.
                            code = result.get("error") if isinstance(result, dict) else None
                            allowed = {"busy", "invalid_request", "not_found", "not_ready", "expired", "conflict", "network_failed", "permission_denied"}
                            raise NetworkUnavailable(code if code in allowed else "network_unavailable")
                        if not isinstance(result.get("result"), dict):
                            raise NetworkUnavailable("network_response_invalid")
                        return result["result"]
                except asyncio.CancelledError:
                    cancelled = True
                    raise
                finally:
                    closed = True
                    await _close_writer_owned(writer, cancelled=cancelled)
        except asyncio.CancelledError:
            cancelled = True
            raise
        except NetworkUnavailable:
            raise
        except Exception:
            raise NetworkUnavailable("network_unavailable") from None
        finally:
            if writer is not None and not closed:
                try:
                    await _close_writer_owned(writer, cancelled=cancelled)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    raise NetworkUnavailable("network_unavailable") from None
