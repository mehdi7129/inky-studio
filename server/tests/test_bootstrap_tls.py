"""Actual TLS records on in-memory BIOs; no radio, wall-clock or OS mutation."""
import asyncio
import json
import ssl
import struct

import pytest

from inky_web.provisioning.bootstrap_tls import (
    BOOTSTRAP_ALPN,
    BootstrapTLSContext,
    BootstrapTLSPeer,
)
from inky_web.provisioning.identity import load_or_create_identity
from inky_web.provisioning.transport import MAX_BUFFER, TLSPeer, TransportError


class Client:
    def __init__(self, identity, protocols, version=ssl.TLSVersion.TLSv1_3):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = context.maximum_version = version
        context.load_verify_locations(cadata=identity.cert_pem.decode())
        if protocols is not None:
            context.set_alpn_protocols(protocols)
        self.input, self.output = ssl.MemoryBIO(), ssl.MemoryBIO()
        self.tls = context.wrap_bio(self.input, self.output, server_hostname=identity.server_name)

    def handshake(self, peer):
        for _ in range(20):
            done = False
            try:
                self.tls.do_handshake()
                done = True
            except ssl.SSLWantReadError:
                pass
            if self.output.pending:
                peer.feed(self.output.read())
            if peer.outgoing.pending:
                self.input.write(peer.outgoing.read())
            if done and peer.authenticated:
                return
        pytest.fail("TLS handshake did not converge")

    def write(self, message):
        raw = json.dumps(message).encode()
        self.tls.write(struct.pack("!I", len(raw)) + raw)
        return self.output.read()


async def test_bootstrap_negotiates_before_synthetic_dispatch_and_returns_reply(tmp_path):
    identity = load_or_create_identity(tmp_path)
    seen = []

    async def handler(message):
        seen.append(message)
        return {"synthetic": "reply"}

    peer = BootstrapTLSPeer(BootstrapTLSContext(identity), handler)
    client = Client(identity, [BOOTSTRAP_ALPN])
    client.handshake(peer)
    assert client.tls.version() == "TLSv1.3"
    assert client.tls.selected_alpn_protocol() == BOOTSTRAP_ALPN
    assert peer.authenticated and not seen
    peer.feed(client.write({"synthetic": "probe"}))
    await asyncio.sleep(0)
    client.input.write(peer.take(MAX_BUFFER))
    reply = client.tls.read(4096)
    assert len(reply) == struct.unpack("!I", reply[:4])[0] + 4
    assert json.loads(reply[4:]) == {"synthetic": "reply"}
    assert seen == [{"synthetic": "probe"}]
    # No resumption tickets are issued, even after application data exchange.
    assert not client.tls.session.has_ticket
    peer.close()


@pytest.mark.parametrize("protocols", [None, [], ["http/1.1"], ["inky-bootstrap/2"]])
async def test_bootstrap_rejects_missing_or_wrong_alpn_before_dispatch(tmp_path, protocols):
    identity = load_or_create_identity(tmp_path)
    seen = []

    async def handler(message):
        seen.append(message)
        return {}

    peer = BootstrapTLSPeer(BootstrapTLSContext(identity), handler)
    client = Client(identity, protocols)
    with pytest.raises(TransportError):
        client.handshake(peer)
    assert peer.closed and not peer.authenticated and not seen
    assert peer.task is None and not peer.plaintext and not peer.reply


async def test_bootstrap_rejects_tls12_and_modified_handshake(tmp_path):
    identity = load_or_create_identity(tmp_path)

    async def never_dispatch(_):
        pytest.fail("Rejected handshake dispatched an application command")

    for legacy in [True, False]:
        peer = BootstrapTLSPeer(BootstrapTLSContext(identity), never_dispatch)
        client = Client(identity, [BOOTSTRAP_ALPN],
                        ssl.TLSVersion.TLSv1_2 if legacy else ssl.TLSVersion.TLSv1_3)
        if legacy:
            with pytest.raises(TransportError):
                client.handshake(peer)
        else:
            with pytest.raises(ssl.SSLWantReadError):
                client.tls.do_handshake()
            peer.feed(client.output.read())
            client.input.write(peer.outgoing.read())
            client.tls.do_handshake()
            finished = bytearray(client.output.read())
            finished[-1] ^= 1
            with pytest.raises(TransportError):
                peer.feed(finished)
        assert peer.closed and not peer.authenticated and peer.task is None


@pytest.mark.parametrize("protocols", [None, ["inky-bootstrap/2"]])
async def test_wrong_profile_cannot_pipeline_command_with_finished(tmp_path, protocols):
    identity = load_or_create_identity(tmp_path)
    seen = []

    async def handler(message):
        seen.append(message)
        return {}

    peer = BootstrapTLSPeer(BootstrapTLSContext(identity), handler)
    client = Client(identity, protocols)
    with pytest.raises(ssl.SSLWantReadError):
        client.tls.do_handshake()
    peer.feed(client.output.read())
    client.input.write(peer.outgoing.read())
    client.tls.do_handshake()
    # The pending Finished and the encrypted command reach the server together.
    # Even buffered application data must not be read before profile validation.
    combined = client.write({"synthetic": "pipelined probe"})
    with pytest.raises(TransportError):
        peer.feed(combined)
    await asyncio.sleep(0)
    assert peer.closed and not peer.authenticated and not seen
    assert peer.task is None and not peer.plaintext and not peer.reply


async def test_bootstrap_refuses_plaintext_or_altered_application_record(tmp_path):
    identity = load_or_create_identity(tmp_path)
    seen = []

    async def handler(message):
        seen.append(message)
        return {}

    for handshake in [False, True]:
        peer = BootstrapTLSPeer(BootstrapTLSContext(identity), handler)
        client = Client(identity, [BOOTSTRAP_ALPN])
        if handshake:
            client.handshake(peer)
            data = bytearray(client.write({"synthetic": "probe"}))
            data[-1] ^= 1
        else:
            data = b'\0\0\0\x10{"op":"status"}'
        with pytest.raises(TransportError):
            peer.feed(bytes(data))
        assert peer.closed and not seen and peer.task is None


async def test_normal_peer_policy_is_unchanged_and_has_no_bootstrap_alpn(tmp_path):
    identity = load_or_create_identity(tmp_path)

    async def handler(message):
        return message

    for protocols in [None, [BOOTSTRAP_ALPN]]:
        peer = TLSPeer(identity.ssl_context(), handler)
        client = Client(identity, protocols)
        client.handshake(peer)
        assert peer.authenticated and client.tls.selected_alpn_protocol() is None
        # A real bootstrap client must reject this missing ALPN; a normal v1
        # client keeps its historical behavior (no mandatory ALPN retrofit).
        peer.close()
    with pytest.raises(TypeError, match="dedicated bootstrap"):
        BootstrapTLSPeer(identity.ssl_context(), handler)


async def test_partial_handshake_cannot_dispatch_or_exceed_existing_bounds(tmp_path):
    identity = load_or_create_identity(tmp_path)
    seen = []

    async def handler(message):
        seen.append(message)
        return {}

    peer = BootstrapTLSPeer(BootstrapTLSContext(identity), handler)
    client = Client(identity, [BOOTSTRAP_ALPN])
    with pytest.raises(ssl.SSLWantReadError):
        client.tls.do_handshake()
    first = client.output.read()
    peer.feed(first[:4])
    assert not peer.authenticated and peer.task is None and not seen
    with pytest.raises(TransportError):
        peer.feed(b"x" * MAX_BUFFER)
    assert peer.closed and not seen
