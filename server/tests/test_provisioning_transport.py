"""Exercise actual OpenSSL records through the same exchange used by BlueZ."""
import asyncio
import json
import ssl
import struct

import pytest

from inky_web.provisioning.identity import load_or_create_identity
from inky_web.provisioning.transport import (
    CERTIFICATE_UUIDS,
    DATA,
    HEADER,
    IDENTITY_UUID,
    GATTTransport,
    TransportError,
)


def test_public_identity_fits_real_att_attribute_limits(tmp_path):
    from inky_web.provisioning.bluez import Characteristic

    identity = load_or_create_identity(tmp_path / "private")
    metadata = Characteristic(IDENTITY_UUID, None, identity).identity_value
    chunks = [Characteristic(uuid, None, identity).identity_value for uuid in CERTIFICATE_UUIDS]
    assert all(len(value) <= 512 for value in [metadata, *chunks])
    assert json.loads(metadata)["cert_length"] == sum(map(len, chunks))
    assert b"".join(chunks) == identity.cert_der


class Client:
    def __init__(self, transport, identity, device="/test/one", mtu=23):
        self.transport, self.device, self.mtu = transport, device, mtu
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ctx.maximum_version = ssl.TLSVersion.TLSv1_3
        ctx.load_verify_locations(cadata=identity.cert_pem.decode() if isinstance(identity.cert_pem, bytes) else identity.cert_pem)
        self.rx, self.tx = ssl.MemoryBIO(), ssl.MemoryBIO()
        self.tls = ctx.wrap_bio(self.rx, self.tx, server_hostname=identity.server_name)
        self.sequence = 0
        self.last = b""
        transport.write(device, b"\0" + b"n" * 16, mtu)
        assert transport.read(device) == b"\0" + b"n" * 16

    def exchange(self):
        self.sequence += 1
        packet = HEADER.pack(DATA, self.sequence, self.sequence - 1) + self.tx.read(self.mtu - 3 - HEADER.size)
        self.transport.write(self.device, packet, self.mtu)
        # Duplicate write/read must never consume another byte or feed TLS twice.
        self.transport.write(self.device, packet, self.mtu)
        response = self.transport.read(self.device)
        assert response == self.transport.read(self.device)
        assert HEADER.unpack_from(response) == (DATA, self.sequence, self.sequence)
        assert len(response) <= self.mtu - 3
        self.rx.write(response[HEADER.size:])
        self.last = packet

    async def handshake(self):
        for _ in range(4000):
            try:
                self.tls.do_handshake()
                while self.tx.pending:
                    self.exchange()
                return
            except ssl.SSLWantReadError:
                self.exchange()
                await asyncio.sleep(0)
        pytest.fail("Handshake did not finish")

    async def command(self, payload):
        raw = json.dumps(payload).encode()
        self.tls.write(struct.pack("!I", len(raw)) + raw)
        received = bytearray()
        for _ in range(4000):
            self.exchange()
            await asyncio.sleep(0)
            try:
                received.extend(self.tls.read(20000))
            except ssl.SSLWantReadError:
                continue
            if len(received) >= 4 and len(received) == struct.unpack("!I", received[:4])[0] + 4:
                return json.loads(received[4:])
        pytest.fail("Command did not finish")


@pytest.mark.parametrize("mtu", [23, 247])
async def test_real_tls_fragmented_and_retried(tmp_path, mtu):
    seen = []

    async def handler(value):
        seen.append(value)
        return {"echo": value}

    identity = load_or_create_identity(tmp_path / "private")
    transport = GATTTransport(identity.ssl_context(), handler)
    client = Client(transport, identity, mtu=mtu)
    await client.handshake()
    value = {"synthetic": "test" * 150}
    assert await client.command(value) == {"echo": value}
    assert seen == [value]
    assert client.tls.version() == "TLSv1.3"
    transport.close()


async def test_peers_isolated_and_reconnect_starts_new_tls(tmp_path):
    async def handler(value):
        return value

    identity = load_or_create_identity(tmp_path / "private")
    transport = GATTTransport(identity.ssl_context(), handler)
    first = Client(transport, identity, "/test/one")
    second = Client(transport, identity, "/test/two")
    await asyncio.gather(first.handshake(), second.handshake())
    results = await asyncio.gather(first.command({"one": 1}), second.command({"two": 2}))
    assert results == [{"one": 1}, {"two": 2}]
    with pytest.raises(TransportError):
        Client(transport, identity, "/test/three")
    transport.disconnect("/test/one")
    with pytest.raises(TransportError):
        transport.read("/test/one")
    first = Client(transport, identity, "/test/one")
    await first.handshake()
    assert await first.command({"new": True}) == {"new": True}
    transport.close()


async def test_changed_duplicate_fails_closed(tmp_path):
    identity = load_or_create_identity(tmp_path / "private")
    transport = GATTTransport(identity.ssl_context(), lambda _: None)
    client = Client(transport, identity)
    await client.handshake()
    changed = client.last[:-1] + bytes([client.last[-1] ^ 1])
    with pytest.raises(TransportError):
        transport.write(client.device, changed)
    assert client.device not in transport.sessions


async def test_altered_tls_record_never_dispatches(tmp_path):
    seen = []

    async def handler(value):
        seen.append(value)
        return value

    identity = load_or_create_identity(tmp_path / "private")
    transport = GATTTransport(identity.ssl_context(), handler)
    client = Client(transport, identity, mtu=247)
    await client.handshake()
    client.tls.write(b'\0\0\0\2{}')
    ciphertext = bytearray(client.tx.read())
    ciphertext[-1] ^= 1
    client.sequence += 1
    with pytest.raises(TransportError):
        transport.write(client.device, HEADER.pack(DATA, client.sequence, client.sequence - 1) + ciphertext, 247)
    assert not seen
    assert client.device not in transport.sessions


@pytest.mark.parametrize("raw", [
    b'{"op":"status","op":"owner.revoke"}',
    b'{"nested":{"owner_id":"one","owner_id":"two"}}',
    b'{"value":NaN}',
    b'{"value":Infinity}',
    b'{"value":-Infinity}',
    b'{"value":1e9999}',
    b'{"value":' + b'[' * 1500 + b'0' + b']' * 1500 + b'}',
    '{"value":"synthetic"}'.encode("utf-16"),
], ids=["duplicate_root", "duplicate_nested", "nan", "infinity", "negative_infinity", "overflow", "deep", "utf16"])
async def test_ambiguous_or_invalid_json_closes_tls_without_dispatch(tmp_path, raw):
    seen = []

    async def handler(value):
        seen.append(value)
        return value

    identity = load_or_create_identity(tmp_path / "private")
    transport = GATTTransport(identity.ssl_context(), handler)
    client = Client(transport, identity, mtu=247)
    await client.handshake()
    client.tls.write(struct.pack("!I", len(raw)) + raw)
    with pytest.raises(TransportError) as error:
        while client.tx.pending:
            client.exchange()
    assert "owner_id" not in str(error.value)
    assert not seen
    assert client.device not in transport.sessions


async def test_invalid_json_from_one_peer_does_not_close_another(tmp_path):
    async def handler(value):
        return value

    identity = load_or_create_identity(tmp_path / "private")
    transport = GATTTransport(identity.ssl_context(), handler)
    first = Client(transport, identity, "/test/one", mtu=247)
    second = Client(transport, identity, "/test/two", mtu=247)
    await asyncio.gather(first.handshake(), second.handshake())
    raw = b'{"duplicate":1,"duplicate":2}'
    first.tls.write(struct.pack("!I", len(raw)) + raw)
    with pytest.raises(TransportError):
        first.exchange()
    assert await second.command({"finite": 1.5, "nested": {"valid": True}}) == {"finite": 1.5, "nested": {"valid": True}}
    transport.close()
