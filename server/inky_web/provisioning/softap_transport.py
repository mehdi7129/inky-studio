"""Bounded TCP carrier for the existing pinned TLS peers and RPC grammar.

The preface is untrusted. Clients must pin the QR key and validate the TLS
handshake before sending a claim, owner token or domestic Wi-Fi credentials.
No BlueZ, HTTP plaintext or certificate/date bypass is introduced here.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress

from .bootstrap_tls import BootstrapTLSContext, BootstrapTLSPeer
from .softap_wire import encode_preface
from .transport import BOOTSTRAP_PROFILE, MAX_BUFFER, NORMAL_PROFILE, TLSPeer, TransportError


class SoftAPTransport:
    def __init__(self, context, handler, *, profile=NORMAL_PROFILE, peer_factory=None):
        if profile not in (NORMAL_PROFILE, BOOTSTRAP_PROFILE):
            raise ValueError("Unknown transport profile")
        if profile == BOOTSTRAP_PROFILE:
            if not isinstance(context, BootstrapTLSContext):
                raise TypeError("A dedicated bootstrap TLS context is required")
            peer_factory = peer_factory or BootstrapTLSPeer
        else:
            import ssl
            if not isinstance(context, ssl.SSLContext):
                raise TypeError("A normal TLS context is required")
            peer_factory = peer_factory or TLSPeer
        self.context, self.handler, self.profile = context, handler, profile
        self.peer_factory = peer_factory
        self.peers = set()
        self.closed = False

    def close(self):
        self.closed = True
        for peer in tuple(self.peers):
            peer.close()


class SoftAPServer:
    """Same injected lifecycle as BlueZServer; one TLS session per TCP stream."""

    def __init__(self, transport, identity, *, profile=NORMAL_PROFILE,
                 host=None, port=9443):
        if not isinstance(transport, SoftAPTransport) or profile != transport.profile:
            raise TypeError("A dedicated SoftAP transport is required")
        self.transport, self.identity, self.profile = transport, identity, profile
        self.host = host or ("192.168.4.1" if profile == BOOTSTRAP_PROFILE else "0.0.0.0")
        self.port = port
        self.server = None
        self.connections = {}
        self.stopping = False

    async def start(self):
        if self.server is not None or self.stopping:
            raise RuntimeError("SoftAP listener cannot be restarted")
        # The normal listener also accepts authenticated LAN recovery after the
        # AP disappears. The OS owns interface/firewall exposure, never QR data.
        self.server = await asyncio.start_server(self._accept, self.host, self.port,
                                                 limit=MAX_BUFFER)

    async def _accept(self, reader, writer):
        task = asyncio.current_task()
        if self.stopping or self.transport.closed or len(self.connections) >= 2:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()
            return
        self.connections[task] = writer
        peer, reading = None, None
        try:
            peer = self.transport.peer_factory(self.transport.context, self.transport.handler)
            if self.profile == BOOTSTRAP_PROFILE and not isinstance(peer, BootstrapTLSPeer):
                raise TypeError("A dedicated bootstrap peer is required")
            self.transport.peers.add(peer)
            writer.write(encode_preface(self.identity.frame_id, self.identity.cert_der,
                                       bootstrap=self.profile == BOOTSTRAP_PROFILE))
            async with asyncio.timeout(10):
                await writer.drain()
            loop = asyncio.get_running_loop()
            touched = loop.time()
            reading = asyncio.create_task(reader.read(16384))
            while not self.stopping and not peer.closed:
                had_reply = bool(peer.reply)
                data = peer.take(MAX_BUFFER)
                if data:
                    writer.write(data)
                    async with asyncio.timeout(10):
                        await writer.drain()
                if had_reply and not peer.reply and not peer.closed:
                    # Effects that intentionally remove this radio are allowed
                    # only after the complete TLS reply reached the TCP drain.
                    drained = getattr(peer, "response_drained", None)
                    if drained is not None:
                        await drained()
                pending = {reading}
                if peer.task is not None:
                    pending.add(peer.task)
                timeout = (180 - (loop.time() - touched) if peer.authenticated
                           else 45 - (loop.time() - peer.created))
                if timeout <= 0:
                    raise TransportError("Session expirée")
                done, _ = await asyncio.wait(pending, timeout=timeout,
                                             return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    raise TransportError("Session expirée")
                if reading in done:
                    data = reading.result()
                    if not data:
                        break
                    touched = loop.time()
                    peer.feed(data)
                    reading = asyncio.create_task(reader.read(16384))
        except (Exception, asyncio.CancelledError):
            # No raw socket/TLS exception can contain private payload in a log.
            pass
        finally:
            if reading is not None:
                reading.cancel()
                await asyncio.gather(reading, return_exceptions=True)
            if peer is not None:
                peer.close()
                self.transport.peers.discard(peer)
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()
            self.connections.pop(task, None)

    async def stop(self):
        self.stopping = True
        self.transport.close()
        if self.server is not None:
            self.server.close()
        current = asyncio.current_task()
        tasks = []
        for task, writer in tuple(self.connections.items()):
            writer.close()
            if task is not current:
                task.cancel()
                tasks.append(task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self.server is not None:
            await self.server.wait_closed()
