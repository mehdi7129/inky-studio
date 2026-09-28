"""Bounded TLS 1.3 stream over acknowledged, per-peer GATT exchanges.

GATT notifications are deliberately not used: BlueZ broadcasts those to all
subscribers. A read returns only the response cached for its device, and never
consumes bytes. Every new write acknowledges the preceding response. Retrying
the same write is harmless; a different duplicate or missing sequence closes
the connection. Disconnect/reconnect requires a fresh RESET and TLS handshake.
"""
from __future__ import annotations

import asyncio
import json
import math
import ssl
import struct
import time
from collections.abc import Awaitable, Callable

SERVICE_UUID = "713b0001-8890-4cc9-a2bf-26f32c43db22"
IDENTITY_UUID = "713b0002-8890-4cc9-a2bf-26f32c43db22"
STREAM_UUID = "713b0003-8890-4cc9-a2bf-26f32c43db22"
CERTIFICATE_UUIDS = ("713b0004-8890-4cc9-a2bf-26f32c43db22", "713b0005-8890-4cc9-a2bf-26f32c43db22")
MAX_BUFFER = 65536
MAX_MESSAGE = 16384
MAX_JSON_DEPTH = 32
HEADER = struct.Struct("!BHH")
RESET = 0
DATA = 1
CLOSE = 2


class TransportError(Exception):
    """Public errors never include TLS bytes, JSON inputs or credentials."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("Non-finite JSON number")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number")
    return number


def _check_depth(message):
    # Keep the limit independent of the interpreter's recursion setting, and
    # never recursively walk data supplied by an unauthenticated TLS peer.
    pending = [(message, 1)]
    while pending:
        value, depth = pending.pop()
        if isinstance(value, (dict, list)):
            if depth > MAX_JSON_DEPTH:
                raise ValueError("JSON nesting limit exceeded")
            children = value.values() if isinstance(value, dict) else value
            pending.extend((child, depth + 1) for child in children)


class TLSPeer:
    def __init__(self, context: ssl.SSLContext, handler: Callable[[dict], Awaitable[dict]]):
        self.incoming = ssl.MemoryBIO()
        self.outgoing = ssl.MemoryBIO()
        self.tls = context.wrap_bio(self.incoming, self.outgoing, server_side=True)
        self.handler = handler
        self.authenticated = False  # TLS established; owner auth is per command.
        self.closed = False
        self.plaintext = bytearray()
        self.reply = bytearray()
        self.task: asyncio.Task | None = None
        self.created = time.monotonic()

    def feed(self, data: bytes) -> None:
        if self.closed or self.incoming.pending + len(data) > MAX_BUFFER:
            self.close()
            raise TransportError("Flux indisponible")
        self.incoming.write(data)
        self.pump()

    def pump(self) -> None:
        if self.closed:
            raise TransportError("Session fermée")
        try:
            if not self.authenticated:
                if time.monotonic() - self.created > 45:
                    raise TransportError("Délai de connexion dépassé")
                self.tls.do_handshake()
                self._check_handshake()
                self.authenticated = True
            if self.reply:
                written = self.tls.write(self.reply)
                del self.reply[:written]
            # Exactly one application command at a time. A second request while
            # its predecessor is running is rejected, rather than queued forever.
            while True:
                chunk = self.tls.read(min(4096, MAX_MESSAGE + 4))
                if not chunk:
                    raise TransportError("Session fermée")
                self.plaintext.extend(chunk)
                if len(self.plaintext) > MAX_MESSAGE + 4:
                    raise TransportError("Commande trop longue")
                if len(self.plaintext) < 4:
                    continue
                length = struct.unpack("!I", self.plaintext[:4])[0]
                if not 1 <= length <= MAX_MESSAGE:
                    raise TransportError("Taille de commande invalide")
                if len(self.plaintext) < length + 4:
                    continue
                if len(self.plaintext) != length + 4 or self.task is not None or self.reply:
                    raise TransportError("Commande déjà en cours")
                try:
                    # UTF-8 is the wire encoding. Python's default JSON decoder
                    # otherwise accepts UTF-16/32, duplicate names and NaN/Inf.
                    message = json.loads(self.plaintext[4:].decode("utf-8"),
                                         object_pairs_hook=_unique_object,
                                         parse_constant=_reject_constant,
                                         parse_float=_finite_float)
                    _check_depth(message)
                except (ValueError, UnicodeError, RecursionError):
                    raise TransportError("Commande invalide") from None
                self.plaintext.clear()
                if not isinstance(message, dict):
                    raise TransportError("Commande invalide")
                self.task = asyncio.create_task(self._dispatch(message))
        except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
            pass
        except (ssl.SSLError, TransportError):
            self.close()
            raise TransportError("Échange sécurisé interrompu") from None
        if self.outgoing.pending > MAX_BUFFER:
            self.close()
            raise TransportError("Sortie saturée")

    def _check_handshake(self) -> None:
        """Profile-specific checks, before reading or dispatching any plaintext.

        The existing v1 transport has no ALPN requirement. A distinct bootstrap
        peer overrides this hook; normal clients never select it implicitly.
        """

    async def _dispatch(self, message: dict) -> None:
        try:
            result = await self.handler(message)
            encoded = json.dumps(result, separators=(",", ":"), allow_nan=False).encode()
            if len(encoded) > MAX_MESSAGE:
                raise TransportError("Réponse trop longue")
            if not self.closed:
                self.reply.extend(struct.pack("!I", len(encoded)) + encoded)
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self.closed:
                encoded = b'{"ok":false,"error":"request_failed"}'
                self.reply.extend(struct.pack("!I", len(encoded)) + encoded)
        finally:
            self.task = None

    def take(self, capacity: int) -> bytes:
        self.pump()
        return self.outgoing.read(capacity)

    def close(self) -> None:
        self.closed = True
        if self.task is not None:
            self.task.cancel()
        self.plaintext.clear()
        self.reply.clear()


class GATTSession:
    def __init__(self, peer: TLSPeer, nonce: bytes):
        self.peer = peer
        self.last_write = bytes([RESET]) + nonce
        self.response = self.last_write
        self.sequence = 0
        self.touched = time.monotonic()

    def exchange(self, frame: bytes, max_response: int) -> None:
        if frame == self.last_write:
            return  # ATT retry: response and TLS input are unchanged.
        if len(frame) < HEADER.size or frame[0] != DATA:
            raise TransportError("Fragment invalide")
        _, sequence, ack = HEADER.unpack_from(frame)
        if sequence != self.sequence + 1 or ack != self.sequence or sequence >= 65535:
            raise TransportError("Séquence invalide")
        self.peer.feed(frame[HEADER.size:])
        response = self.peer.take(max_response - HEADER.size)
        self.response = HEADER.pack(DATA, sequence, sequence) + response
        self.sequence = sequence
        self.last_write = frame
        self.touched = time.monotonic()


class GATTTransport:
    """Device paths are supplied by BlueZ, never by the remote payload."""

    def __init__(self, context: ssl.SSLContext, handler: Callable[[dict], Awaitable[dict]]):
        self.context = context
        self.handler = handler
        self.sessions: dict[str, GATTSession] = {}

    def write(self, device: str, frame: bytes, mtu: int = 23) -> None:
        self.expire()
        if not device or not 1 <= len(frame) <= min(512, max(20, mtu - 3)):
            raise TransportError("Fragment invalide")
        if frame[0] == CLOSE and len(frame) == 1:
            self.disconnect(device)
            return
        if frame[0] == RESET and len(frame) == 17:
            existing = self.sessions.get(device)
            if existing and existing.sequence == 0 and existing.last_write == frame:
                return
            self.disconnect(device)
            if len(self.sessions) >= 2:
                raise TransportError("Cadre occupé")
            self.sessions[device] = GATTSession(TLSPeer(self.context, self.handler), frame[1:])
            return
        session = self.sessions.get(device)
        if session is None:
            raise TransportError("Connexion requise")
        try:
            # Never require long ATT reads: response always fits a single value.
            session.exchange(frame, max_response=min(244, max(20, mtu - 3)))
        except Exception:
            self.disconnect(device)
            raise

    def read(self, device: str, offset: int = 0) -> bytes:
        self.expire()
        session = self.sessions.get(device)
        if session is None or not 0 <= offset <= len(session.response):
            raise TransportError("Connexion requise")
        return session.response[offset:]

    def disconnect(self, device: str) -> None:
        session = self.sessions.pop(device, None)
        if session is not None:
            session.peer.close()

    def expire(self) -> None:
        now = time.monotonic()
        for device, session in list(self.sessions.items()):
            if now - session.touched > 180 or session.peer.closed:
                self.disconnect(device)

    def close(self) -> None:
        for device in list(self.sessions):
            self.disconnect(device)
