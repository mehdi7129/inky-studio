"""Bounded structured client for the separately privileged network helper."""
from __future__ import annotations

import asyncio
import json
import os
import socket


class NetworkUnavailable(Exception):
    pass


class NetworkClient:
    def __init__(self, path: str | None = None):
        self.path = path or os.environ.get("INKY_NETWORK_SOCKET", "/run/inky-network/control.sock")

    def cancel_pending_sync(self) -> None:
        """Called only by the password-rotation worker, after password proof.

        Complete rollback before committing the credential epoch. Failure aborts
        rotation: a previously confirmed but unfinished activation cannot later
        commit on behalf of a newly revoked owner.
        """
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(15)
                connection.connect(self.path)
                connection.sendall(b'{"op":"cancel_pending"}\n')
                with connection.makefile("rb") as source:
                    raw = source.readline(16385)
                if len(raw) > 16384 or not raw.endswith(b"\n"):
                    raise ValueError
                result = json.loads(raw)
                if result.get("ok") is not True or type(result.get("result", {}).get("cancelled")) is not bool:
                    raise ValueError
        except (OSError, ValueError, AttributeError, TypeError):
            raise NetworkUnavailable("network_unavailable") from None

    async def call(self, operation: str, **arguments) -> dict:
        writer = None
        try:
            async with asyncio.timeout(20):
                reader, writer = await asyncio.open_unix_connection(self.path, limit=16385)
                payload = json.dumps({"op": operation, **arguments}, separators=(",", ":"), allow_nan=False).encode()
                if len(payload) > 8192:
                    raise NetworkUnavailable("network_request_invalid")
                writer.write(payload + b"\n")
                await writer.drain()
                raw = await reader.readline()
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
        except (OSError, ValueError, TimeoutError, asyncio.IncompleteReadError):
            raise NetworkUnavailable("network_unavailable") from None
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
