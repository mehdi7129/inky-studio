"""Isolated bootstrap TLS primitive; not registered with BlueZ or the runtime.

This establishes a separate TLS profile, NOT phone ownership or authority to
set the clock. A future bounded dispatcher must authenticate every operation.
No certificate issuance, clock mutation, Wi-Fi or claim is implemented here.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from .identity import Identity
from .transport import TLSPeer, TransportError

BOOTSTRAP_ALPN = "inky-bootstrap/1"


class BootstrapTLSContext:
    """A fresh server-only TLS 1.3 context with mandatory bootstrap negotiation.

    The identity remains responsible for durable key/certificate persistence.
    Loading an expired server leaf does not relax any remote-client trust rule:
    only the separately pinned bootstrap client may disregard its date flags.
    """

    def __init__(self, identity: Identity):
        self._context = identity.ssl_context()
        self._context.set_alpn_protocols([BOOTSTRAP_ALPN])


class BootstrapTLSPeer(TLSPeer):
    """Bounded MemoryBIO peer for a dedicated bootstrap handler only.

    There is deliberately no GATT registration or normal-runtime fallback.
    A successful handshake authenticates the frame to a pinned client; it does
    not authenticate that client. The supplied handler still needs owner/QR
    authorization and the future bootstrap-only command allowlist.
    """

    def __init__(self, context: BootstrapTLSContext,
                 handler: Callable[[dict], Awaitable[dict]]):
        if not isinstance(context, BootstrapTLSContext):
            raise TypeError("A dedicated bootstrap TLS context is required")
        super().__init__(context._context, handler)

    def _check_handshake(self) -> None:
        # Python/OpenSSL can complete TLS without an agreed ALPN. Refuse that
        # case before setting authenticated, reading data or scheduling handler.
        if self.tls.selected_alpn_protocol() != BOOTSTRAP_ALPN:
            raise TransportError("Profil de connexion incorrect")
