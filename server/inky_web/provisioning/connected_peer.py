"""Injected proof for the peer of the actual connected transport.

The owning OS supplies the proof and its lifetime. This seam does not identify
the sender of each message, acquire PIDFDs or authorize any service itself.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Protocol


class ConnectedSocket(Protocol):
    """Socket operations available on socket.socket and asyncio TransportSocket."""

    def fileno(self) -> int: ...

    def getsockopt(self, level: int, optname: int, buflen: int = ...) -> int | bytes: ...


ConnectedPeerGuard = Callable[[ConnectedSocket], AbstractContextManager[None]]


class ConnectedPeerError(Exception):
    """Fixed internal error; a guard must never publish its private diagnostics."""


@contextmanager
def connected_peer_scope(
    connection: ConnectedSocket, guard: ConnectedPeerGuard | None,
) -> Iterator[None]:
    """Retain the injected proof; never permit it to suppress a transport error."""
    if guard is None:
        yield
        return
    try:
        manager = guard(connection)
        entered = manager.__enter__()
    except Exception:
        raise ConnectedPeerError("connected_peer_unavailable") from None
    if entered is not None:
        # CM[None] is an exact contract, not a truthy readiness snapshot. The
        # manager did enter, so release its acquired proof before refusing.
        try:
            manager.__exit__(None, None, None)
        except Exception:
            pass
        raise ConnectedPeerError("connected_peer_unavailable") from None
    try:
        yield
    except BaseException as error:
        try:
            manager.__exit__(type(error), error, error.__traceback__)
        except Exception:
            # Cancellation still owns its drain. A failed guard cannot turn it
            # into success or replace it with private diagnostics.
            if not isinstance(error, Exception):
                raise error from None
            raise ConnectedPeerError("connected_peer_unavailable") from None
        raise
    else:
        try:
            manager.__exit__(None, None, None)
        except Exception:
            raise ConnectedPeerError("connected_peer_unavailable") from None
