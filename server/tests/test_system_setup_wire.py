"""Closed v2 grammar, exact lexical integers and transport conversion."""
import json
from uuid import uuid4

import pytest

from inky_web.provisioning import system_setup_wire as wire


def request():
    return {"v": 2, "id": str(uuid4()), "op": "system_setup.apply", "owner_id": str(uuid4()),
        "owner_token": "a" * 64, "claim_request_id": str(uuid4()), "op_id": str(uuid4()),
        "challenge_id": str(uuid4()), "nonce": "b" * 64, "utc_seconds": 1792152000, "country": "FR"}


def test_wire_decode_normalizes_integer_for_strict_ipc():
    from inky_web.provisioning.system_setup_ipc import _REQUESTS, _validate
    message = wire.decode_request(json.dumps(request()).encode())
    assert type(message["utc_seconds"]) is int
    args = {"operation_id": message["op_id"], "supersedes_operation_id": None,
            **{key: message[key] for key in ("challenge_id", "nonce", "utc_seconds", "country")}}
    _validate({"v": 1, "id": str(uuid4()), "op": "setup.apply", "args": args}, _REQUESTS["setup.apply"])


@pytest.mark.parametrize("lexeme", ["-0", "1792152000.0", "1.792152e9", "true", "NaN", "4102444800", "1767225599"])
def test_rejects_noncanonical_or_out_of_range_utc(lexeme):
    raw = json.dumps(request()).replace('1792152000', lexeme).encode()
    with pytest.raises(wire.WireError):
        wire.decode_request(raw)


@pytest.mark.parametrize("change", [lambda x: x.update(op=[]), lambda x: x.update(op={}),
    lambda x: x.update(extra="secret"), lambda x: x.update(v=True), lambda x: x.update(country="fr"),
    lambda x: x.update(country="ZZZ"), lambda x: x.update(owner_token="F" * 64),
    lambda x: x.update(op_id=x["owner_id"].upper()), lambda x: x.pop("country")])
def test_closed_requests(change):
    message = request()
    change(message)
    with pytest.raises(wire.WireError):
        wire.validate_request(message)


@pytest.mark.parametrize("value", [None, [], {"v": True}, {"v": 2, "ok": False, "id": None, "error": []}])
def test_malformed_responses_fail_fixed(value):
    with pytest.raises((wire.WireError, TypeError)):
        wire.validate_response(value, operation="system_setup.apply", context={})


@pytest.mark.parametrize("value", ["http://frame.local:8443", "https://x:99999", "https://x/path", "https://u:p@x", "https://x/#f"])
def test_origin_rejects_bad_urls(value):
    with pytest.raises(wire.WireError):
        wire.origin(value)


from tests.test_system_setup_ipc import unix_service  # noqa: E402,F401


async def test_framed_tls_decode_reaches_real_strict_ipc(unix_service, tmp_path):  # noqa: F811
    import asyncio
    import struct

    from inky_web.provisioning import system_setup_ipc as ipc
    from inky_web.provisioning.bootstrap_runtime import BootstrapApplicationPeer
    from inky_web.provisioning.bootstrap_tls import BOOTSTRAP_ALPN, BootstrapTLSContext
    from inky_web.provisioning.identity import load_or_create_identity
    from inky_web.provisioning.transport import MAX_BUFFER
    from tests.test_bootstrap_tls import Client
    from tests.test_system_setup_ipc import BOOT, applied, observed, owner, proof

    binding, events = owner(), []
    async def respond(envelope):
        if envelope["op"] == "setup.open":
            return {"binding": observed(binding)}
        return applied(envelope, observed(binding))
    path, requests = await unix_service(respond)
    channel = await ipc.SystemSetupClient(path, peer_guard=proof(events), boot_id=lambda: BOOT).open(binding)
    identity = load_or_create_identity(tmp_path / "tls-fixture")
    message = request()
    async def handler(parsed):
        decoded = wire.validate_request(parsed)
        result = await channel.call("setup.apply", operation_id=decoded["op_id"], supersedes_operation_id=None,
            **{key: decoded[key] for key in ("challenge_id", "nonce", "utc_seconds", "country")})
        assert result["state"] == "effects_completed"
        return wire.response(decoded["id"], {"op_id": decoded["op_id"], "state": "applying",
            "submission": "registered", "durability": "not_confirmed", "frame_id": binding["frame_id"],
            "owner_id": decoded["owner_id"], "claim_request_id": decoded["claim_request_id"], "next_step": "status"})
    peer = BootstrapApplicationPeer(BootstrapTLSContext(identity), handler)
    client = Client(identity, [BOOTSTRAP_ALPN])
    try:
        client.handshake(peer)
        peer.feed(client.write(message))
        for _ in range(500):
            if peer.task is None:
                break
            await asyncio.sleep(0.001)
        client.input.write(peer.take(MAX_BUFFER))
        raw = client.tls.read(MAX_BUFFER)
        assert struct.unpack("!I", raw[:4])[0] == len(raw) - 4
        assert wire.decode_response(raw[4:], operation=message["op"],
            context={"rpc_id": message["id"], "op_id": message["op_id"]})["ok"]
        assert type(requests[-1]["args"]["utc_seconds"]) is int
        assert requests[-1]["args"]["utc_seconds"] == message["utc_seconds"]
    finally:
        peer.close()
        await channel.drain()
