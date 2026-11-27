"""Real loopback TCP/OpenSSL records, with no radio or OS effects."""
import asyncio
import base64
import json
import ssl
import struct
from uuid import uuid4

import pytest

from inky_web.provisioning import softap_wire as wire
from inky_web.provisioning.bootstrap_tls import BootstrapTLSContext
from inky_web.provisioning.identity import load_or_create_identity
from inky_web.provisioning.softap_transport import SoftAPServer, SoftAPTransport
from inky_web.provisioning.transport import BOOTSTRAP_PROFILE, NORMAL_PROFILE, TLSPeer


async def connect(server, identity, *, bootstrap=False, alpn=True):
    port = server.server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    length = struct.unpack("!I", await reader.readexactly(4))[0]
    assert 1 <= length <= 4096
    preface = json.loads(await reader.readexactly(length))
    assert preface == {"v": 1, "p": "bootstrap" if bootstrap else "normal",
                       "id": identity.frame_id, "c": base64.b64encode(identity.cert_der).decode()}
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
    context.load_verify_locations(cadata=identity.cert_pem.decode())
    if bootstrap and alpn:
        context.set_alpn_protocols(["inky-bootstrap/1"])
    await writer.start_tls(context, server_hostname=identity.server_name)
    return reader, writer


async def rpc(reader, writer, message):
    raw = json.dumps(message).encode()
    writer.write(struct.pack("!I", len(raw)) + raw)
    await writer.drain()
    async with asyncio.timeout(2):
        length = struct.unpack("!I", await reader.readexactly(4))[0]
        return json.loads(await reader.readexactly(length))


@pytest.mark.parametrize("bootstrap", [False, True])
async def test_real_tcp_tls_profiles(tmp_path, bootstrap):
    identity = load_or_create_identity(tmp_path / "identity")
    seen = []
    async def handler(message):
        seen.append(message)
        return {"echo": message}
    profile = BOOTSTRAP_PROFILE if bootstrap else NORMAL_PROFILE
    context = BootstrapTLSContext(identity) if bootstrap else identity.ssl_context()
    transport = SoftAPTransport(context, handler, profile=profile)
    server = SoftAPServer(transport, identity, profile=profile, host="127.0.0.1", port=0)
    await server.start()
    try:
        reader, writer = await connect(server, identity, bootstrap=bootstrap)
        for message in ({"hello": "inert"}, {"id": str(uuid4()), "bytes": "x" * 8000}):
            assert await rpc(reader, writer, message) == {"echo": message}
        assert len(seen) == 2
        writer.close()
        await writer.wait_closed()
    finally:
        await asyncio.wait_for(server.stop(), 2)
    assert not server.connections and not transport.peers


async def test_bootstrap_requires_alpn_before_dispatch(tmp_path):
    identity = load_or_create_identity(tmp_path / "identity")
    seen = []
    async def handler(message):
        seen.append(message)
        return {"ok": True}
    transport = SoftAPTransport(BootstrapTLSContext(identity), handler, profile=BOOTSTRAP_PROFILE)
    server = SoftAPServer(transport, identity, profile=BOOTSTRAP_PROFILE, host="127.0.0.1", port=0)
    await server.start()
    try:
        reader, writer = await connect(server, identity, bootstrap=True, alpn=False)
        with pytest.raises((asyncio.IncompleteReadError, ConnectionError, ssl.SSLError)):
            await rpc(reader, writer, {"secret": "synthetic"})
        assert seen == []
        writer.close()
    finally:
        await server.stop()


async def test_response_drain_callback_runs_after_reply(tmp_path):
    identity = load_or_create_identity(tmp_path / "identity")
    drained = asyncio.Event()
    class Peer(TLSPeer):
        async def response_drained(self):
            assert not self.reply
            drained.set()
    async def handler(message):
        return {"ok": True}
    transport = SoftAPTransport(identity.ssl_context(), handler, peer_factory=Peer)
    server = SoftAPServer(transport, identity, host="127.0.0.1", port=0)
    await server.start()
    try:
        reader, writer = await connect(server, identity)
        assert not drained.is_set()
        assert await rpc(reader, writer, {}) == {"ok": True}
        await asyncio.wait_for(drained.wait(), 1)
        writer.close()
    finally:
        await server.stop()


async def test_connection_limit_stop_and_no_plaintext_dispatch(tmp_path):
    identity = load_or_create_identity(tmp_path / "identity")
    seen = []
    async def handler(message):
        seen.append(message)
        return {}
    transport = SoftAPTransport(identity.ssl_context(), handler)
    server = SoftAPServer(transport, identity, host="127.0.0.1", port=0)
    await server.start()
    port = server.server.sockets[0].getsockname()[1]
    connections = [await asyncio.open_connection("127.0.0.1", port) for _ in range(3)]
    try:
        assert await asyncio.wait_for(connections[2][0].read(), 1) == b""
        connections[0][1].write(b'{"owner_token":"synthetic"}')
        await connections[0][1].drain()
        await asyncio.sleep(0.01)
        assert seen == []
    finally:
        await server.stop()
        for _, writer in connections:
            writer.close()
    assert not server.connections


def test_qr_closed_and_explicit_softap_profile():
    raw = wire.encode_qr(str(uuid4()), "a" * 64, "b" * 64, "Inky-1234ABCD", "x" * 32)
    parsed = wire.decode_qr(raw.encode())
    assert parsed["p"] == "softap" and parsed["v"] == 3
    for patch in ({"v": 3.0}, {"v": True}, {"p": "bootstrap"},
                  {"u": "tcp://evil:9443"}, {"s": "bad\nssid"},
                  {"w": "short"}, {"extra": 1}):
        with pytest.raises(wire.wire.WireError):
            wire.decode_qr(json.dumps({**parsed, **patch}).encode())


@pytest.mark.parametrize("certificate", [b"", b"x" * 2049, "not-bytes"])
def test_preface_certificate_is_bounded(certificate):
    with pytest.raises(wire.wire.WireError):
        wire.encode_preface(str(uuid4()), certificate, bootstrap=True)
