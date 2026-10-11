"""Bootstrap OpenSSL/GATT exchanges, without BlueZ or a physical radio."""
import asyncio
import json
import ssl
import struct

import pytest

from inky_web.provisioning.bluez import Advertisement, BlueZServer, Characteristic, Service
from inky_web.provisioning.bootstrap_runtime import BootstrapApplicationPeer
from inky_web.provisioning.bootstrap_tls import BOOTSTRAP_ALPN, BootstrapTLSContext
from inky_web.provisioning.bootstrap_wire import WireError, decode_metadata, validate_request
from inky_web.provisioning.identity import load_or_create_identity
from inky_web.provisioning.transport import (
    BOOTSTRAP_PROFILE,
    DATA,
    HEADER,
    NORMAL_PROFILE,
    GATTTransport,
    TLSPeer,
    TransportError,
)


class Client:
    def __init__(self, transport, identity, *, mtu=247, protocols=(BOOTSTRAP_ALPN,),
                 version=ssl.TLSVersion.TLSv1_3):
        self.transport, self.mtu = transport, mtu
        self.device, self.sequence = "/synthetic/one", 0
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = context.maximum_version = version
        context.load_verify_locations(cadata=identity.cert_pem.decode())
        if protocols is not None:
            context.set_alpn_protocols(list(protocols))
        self.rx, self.tx = ssl.MemoryBIO(), ssl.MemoryBIO()
        self.tls = context.wrap_bio(self.rx, self.tx, server_hostname=identity.server_name)
        self.last = b"\0" + b"s" * 16
        transport.write(self.device, self.last, mtu)
        assert transport.read(self.device) == self.last

    def exchange(self):
        self.sequence += 1
        capacity = min(244, self.mtu - 3)
        self.last = HEADER.pack(DATA, self.sequence, self.sequence - 1) + self.tx.read(capacity - 5)
        self.transport.write(self.device, self.last, self.mtu)
        response = self.transport.read(self.device)
        self.transport.write(self.device, self.last, self.mtu)
        assert self.transport.read(self.device) == response
        assert HEADER.unpack_from(response) == (DATA, self.sequence, self.sequence)
        assert len(response) <= capacity
        self.rx.write(response[5:])

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
        pytest.fail("Synthetic handshake did not converge")

    async def command(self, raw):
        self.tls.write(struct.pack("!I", len(raw)) + raw)
        received = bytearray()
        for _ in range(4000):
            self.exchange()
            await asyncio.sleep(0)
            try:
                received.extend(self.tls.read(20000))
            except ssl.SSLWantReadError:
                continue
            if len(received) >= 4 and len(received) == 4 + struct.unpack("!I", received[:4])[0]:
                return json.loads(received[4:])
        pytest.fail("Synthetic command did not converge")


def setup(tmp_path, handler, **kwargs):
    identity = load_or_create_identity(tmp_path)
    transport = GATTTransport(BootstrapTLSContext(identity), handler, profile=BOOTSTRAP_PROFILE,
                              peer_factory=BootstrapApplicationPeer)
    return identity, transport, Client(transport, identity, **kwargs)


@pytest.mark.parametrize("mtu", [23, 247, 517])
async def test_explicit_bootstrap_tls_records_fragment_retry_and_cap(tmp_path, mtu):
    seen = []

    async def handler(message):
        seen.append(message)
        return {"v": 1, "id": None, "ok": False, "error": "invalid_request"}

    _, transport, client = setup(tmp_path, handler, mtu=mtu)
    await client.handshake()
    assert client.tls.version() == "TLSv1.3"
    assert client.tls.selected_alpn_protocol() == BOOTSTRAP_ALPN
    assert await client.command(b'{"synthetic":"probe"}') == {
        "v": 1, "id": None, "ok": False, "error": "invalid_request",
    }
    assert seen == [{"synthetic": "probe"}]
    assert not client.tls.session.has_ticket
    transport.close()


@pytest.mark.parametrize("protocols", [None, (), ("http/1.1",), ("inky-bootstrap/2",)])
async def test_wrong_or_absent_alpn_never_dispatches(tmp_path, protocols):
    seen = []

    async def handler(message):
        seen.append(message)
        return {}

    _, transport, client = setup(tmp_path, handler, protocols=protocols)
    with pytest.raises(TransportError):
        await client.handshake()
    assert not seen and not transport.sessions


async def test_tls12_never_dispatches(tmp_path):
    async def never(_):
        pytest.fail("TLS1.2 must never dispatch")

    _, transport, client = setup(tmp_path, never, version=ssl.TLSVersion.TLSv1_2)
    with pytest.raises(TransportError):
        await client.handshake()
    assert not transport.sessions


@pytest.mark.parametrize("raw", [
    b'{"v":1,"v":1}', b'{"v":NaN}', b'{"secret":"\\ud800"}',
    b'{"v":' + b'[' * 33 + b'0' + b']' * 33 + b'}', b'[]',
    '{"v":1}'.encode("utf-16"),
])
async def test_encoding_ambiguity_closes_before_application_dispatch(tmp_path, raw):
    seen = []

    async def handler(message):
        seen.append(message)
        return {}

    _, transport, client = setup(tmp_path, handler)
    await client.handshake()
    with pytest.raises(TransportError):
        await client.command(raw)
    assert not seen and not transport.sessions


async def test_decimal_version_remains_invalid_at_real_dispatch_boundary(tmp_path):
    async def handler(message):
        try:
            validate_request(message)
        except WireError:
            return {"v": 1, "id": message["id"], "ok": False, "error": "invalid_request"}
        pytest.fail("Decimal version must not be converted into an integer")

    _, transport, client = setup(tmp_path, handler)
    await client.handshake()
    raw = json.dumps({"v": 1.0, "id": "00000000-0000-4000-8000-000000000003",
                      "op": "bootstrap.claim", "owner_id": "00000000-0000-4000-8000-000000000002",
                      "owner_token": "b" * 64, "claim_token": "a" * 64}).encode()
    assert (await client.command(raw))["error"] == "invalid_request"
    transport.close()


@pytest.mark.parametrize("failure", ["exception", "malformed", "nonfinite", "wrong-correlation"])
async def test_bootstrap_handler_failure_closes_without_normal_fallback(tmp_path, failure):
    async def handler(_):
        if failure == "exception":
            raise OSError("private handler detail")
        if failure == "malformed":
            return {"ok": False, "error": "request_failed"}
        if failure == "nonfinite":
            return {"v": 1, "id": None, "ok": False, "error": float("nan")}
        return {"v": 1, "id": "00000000-0000-4000-8000-000000000004",
                "ok": False, "error": "invalid_request"}

    _, transport, client = setup(tmp_path, handler)
    await client.handshake()
    with pytest.raises(TransportError):
        await client.command(b'{"synthetic":"probe"}')
    assert not transport.sessions
    assert not client.rx.pending


async def test_bootstrap_producer_null_id_closes_when_request_id_is_readable(tmp_path):
    async def handler(_):
        return {"v": 1, "id": None, "ok": False, "error": "invalid_request"}

    _, transport, client = setup(tmp_path, handler)
    await client.handshake()
    # Even an invalid schema preserves a readable canonical request identifier.
    raw = b'{"id":"00000000-0000-4000-8000-000000000003","synthetic":"probe"}'
    with pytest.raises(TransportError):
        await client.command(raw)
    assert not transport.sessions
    assert not client.rx.pending


def test_bootstrap_handshake_deadline_sweeps_silent_and_retrying_peers(tmp_path, monkeypatch):
    from inky_web.provisioning import transport as module

    now = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    identity = load_or_create_identity(tmp_path)
    transport = GATTTransport(BootstrapTLSContext(identity), lambda _: None, profile=BOOTSTRAP_PROFILE)
    reset = b"\0" + b"s" * 16
    transport.write("/one", reset)
    transport.write("/two", reset)
    now[0] = 44
    assert transport.read("/one") == reset
    transport.write("/one", reset)  # retry cannot extend the absolute deadline
    now[0] = 45
    transport.expire()
    assert not transport.sessions
    transport.write("/three", reset)
    assert len(transport.sessions) == 1
    transport.close()


@pytest.mark.parametrize("frame,mtu", [(b"\0" + b"s" * 16, 22), (b"x" * 245, 517)])
def test_bootstrap_refuses_mtu_or_oversized_write(tmp_path, frame, mtu):
    identity = load_or_create_identity(tmp_path)
    transport = GATTTransport(BootstrapTLSContext(identity), lambda _: None, profile=BOOTSTRAP_PROFILE)
    transport.write("/one", b"\0" + b"s" * 16)
    with pytest.raises(TransportError):
        transport.write("/one", frame, mtu)
    assert not transport.sessions


def test_profile_bound_constructor_and_public_metadata_do_not_cross(tmp_path):
    identity = load_or_create_identity(tmp_path)
    with pytest.raises(TypeError):
        GATTTransport(identity.ssl_context(), lambda _: None, profile=BOOTSTRAP_PROFILE)
    with pytest.raises(TypeError):
        GATTTransport(BootstrapTLSContext(identity), lambda _: None)
    transport = GATTTransport(BootstrapTLSContext(identity), lambda _: None, profile=BOOTSTRAP_PROFILE)
    with pytest.raises(TypeError):
        broken = GATTTransport(BootstrapTLSContext(identity), lambda _: None,
                               profile=BOOTSTRAP_PROFILE, peer_factory=lambda *_: TLSPeer(identity.ssl_context(), lambda _: None))
        broken.write("/one", b"\0" + b"s" * 16)
    with pytest.raises(ValueError):
        BlueZServer(transport, identity, profile=NORMAL_PROFILE)
    public = Characteristic(BOOTSTRAP_PROFILE.identity, transport, identity, BOOTSTRAP_PROFILE).identity_value
    parts = [Characteristic(uuid, transport, identity, BOOTSTRAP_PROFILE).identity_value
             for uuid in BOOTSTRAP_PROFILE.certificates]
    assert decode_metadata(public)["cert_length"] == len(identity.cert_der)
    assert b"".join(parts) == identity.cert_der and len(public) <= 128
    assert set(BOOTSTRAP_PROFILE.certificates).isdisjoint(NORMAL_PROFILE.certificates)
    assert Service(BOOTSTRAP_PROFILE).UUID == BOOTSTRAP_PROFILE.service
    assert Advertisement(BOOTSTRAP_PROFILE).ServiceUUIDs == [BOOTSTRAP_PROFILE.service]
    assert Service().UUID == NORMAL_PROFILE.service
    transport.close()
