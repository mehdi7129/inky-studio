"""Opt-in initialization adapter for the separately owned InkyOS root service.

The disabled-by-default factory guard is its only startup caller. The kernel's connected-peer
credentials, not a socket filename or a readable receipt, establish the local
server's identity. Every operation uses a new connection and is attempted once.
"""
from __future__ import annotations

import json
import socket
import struct
import sys
import time
from uuid import uuid4

from .connected_peer import ConnectedPeerGuard, connected_peer_scope
from .first_boot import _receipt_response
from .identity import canonical_uuid

SOCKET_PATH = "/run/inkyos-bootstrap/control.sock"
DEADLINE_SECONDS = 3.0
MAX_REQUEST_BYTES = 1024
MAX_RESPONSE_BYTES = 2048
ERROR_CODES = frozenset({"invalid_request", "forbidden", "unavailable", "intent_conflict",
                         "initialization_uncertain"})
_DEFINITE_REFUSALS = frozenset({"invalid_request", "forbidden", "intent_conflict"})


class InitializationIPCError(Exception):
    """A fixed public error, without socket paths, receipt contents or raw input.

    ``begin_submitted`` also covers a partial/failed send: the peer may already
    have received the request. ``uncertain`` never authorizes creating a store.
    FirstBootCoordinator deliberately treats every failed begin conservatively,
    including a refusal that this narrower transport can identify.
    """

    def __init__(self, code: str, *, begin_submitted: bool = False, uncertain: bool = False):
        if code not in ERROR_CODES:
            code = "unavailable"
        self.code = code
        self.begin_submitted = begin_submitted
        self.uncertain = uncertain
        super().__init__(code)


def _verify_server_peer(connection: socket.socket) -> None:
    """Only Linux SO_PEERCRED is qualified; every other platform refuses."""
    if sys.platform != "linux" or not hasattr(socket, "SO_PEERCRED"):
        raise InitializationIPCError("forbidden")
    credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    if len(credentials) != struct.calcsize("3i"):
        raise InitializationIPCError("forbidden")
    _pid, uid, _gid = struct.unpack("3i", credentials)
    if uid != 0:
        raise InitializationIPCError("forbidden")


def _remaining(connection: socket.socket, deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    connection.settimeout(remaining)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError


def _read_response(connection: socket.socket, deadline: float) -> dict:
    raw = bytearray()
    while True:
        _remaining(connection, deadline)
        chunk = connection.recv(MAX_RESPONSE_BYTES + 1 - len(raw))
        if not chunk:
            break
        raw.extend(chunk)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError
        # One exact JSONL value, no second line or bytes following its newline.
        if b"\n" in raw and raw.find(b"\n") != len(raw) - 1:
            raise ValueError
    if not raw.endswith(b"\n") or raw.count(b"\n") != 1:
        raise ValueError
    value = json.loads(bytes(raw[:-1]).decode("utf-8"), object_pairs_hook=_unique_object,
                       parse_constant=_reject_constant, parse_float=_reject_constant)
    if type(value) is not dict:
        raise ValueError
    return value


class InitializationIPCClient:
    """Synchronous InitializationAdapter; the optional path is local-only.

    There is no environment override, cached grant, retry, root-file read or
    fallback to a weaker transport. It performs no clock/country/network action.
    """

    def __init__(self, path: str = SOCKET_PATH, *, peer_guard: ConnectedPeerGuard | None = None):
        self.path = path
        self.peer_guard = peer_guard

    def inspect_initialization(self) -> dict:
        return self._call("initialization.inspect")

    def begin_initialization(self, intent: str) -> dict:
        try:
            canonical_uuid(intent)
        except (TypeError, ValueError, AttributeError):
            raise InitializationIPCError("invalid_request") from None
        return self._call("initialization.begin", intent=intent)

    def _call(self, operation: str, *, intent: str | None = None) -> dict:
        begin_submitted = False
        deadline = time.monotonic() + DEADLINE_SECONDS
        request_id = str(uuid4())
        request = {"v": 1, "id": request_id, "op": operation}
        if intent is not None:
            request["intent"] = intent
        try:
            raw = json.dumps(request, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
            if len(raw) > MAX_REQUEST_BYTES:
                raise InitializationIPCError("invalid_request")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                _remaining(connection, deadline)
                connection.connect(self.path)
                _verify_server_peer(connection)
                with connected_peer_scope(connection, self.peer_guard):
                    try:
                        _remaining(connection, deadline)
                        # Mark before sendall: an exception may follow a partial send.
                        begin_submitted = operation == "initialization.begin"
                        connection.sendall(raw)
                        value = _read_response(connection, deadline)
                        if (type(value.get("v")) is not int or value["v"] != 1
                                or value.get("id") != request_id or type(value.get("ok")) is not bool):
                            raise ValueError
                        if value["ok"]:
                            if set(value) != {"v", "id", "ok", "result"}:
                                raise ValueError
                            _, returned_intent, _ = _receipt_response(value["result"], inspect=intent is None)
                            if intent is not None and returned_intent != intent:
                                raise ValueError
                            return value["result"]
                        if (set(value) != {"v", "id", "ok", "error"}
                                or type(value.get("error")) is not str or value["error"] not in ERROR_CODES):
                            raise ValueError
                        code = value["error"]
                        raise InitializationIPCError(code, begin_submitted=begin_submitted,
                                                     uncertain=begin_submitted and code not in _DEFINITE_REFUSALS)
                    finally:
                        # The OS proof outlives validation and the actual socket.
                        connection.close()
        except InitializationIPCError:
            raise
        except Exception:
            raise InitializationIPCError(
                "initialization_uncertain" if begin_submitted else "unavailable",
                begin_submitted=begin_submitted, uncertain=begin_submitted,
            ) from None
