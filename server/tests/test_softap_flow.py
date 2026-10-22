"""Full first-owner workflow over real TCP/TLS and SQLite; OS effects are inert."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import ssl
import struct
from uuid import uuid4

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from inky_web import auth
from inky_web.provisioning.factory_continuation import FactoryContinuationRuntime
from inky_web.provisioning.first_boot import FirstBootCoordinator
from inky_web.provisioning.ownership import credential_epoch
from inky_web.provisioning.softap_transport import SoftAPServer
from inky_web.provisioning.softap_wire import encode_qr
from inky_web.provisioning.transport import NORMAL_PROFILE
from tests.test_bootstrap_runtime import FakeOS
from tests.test_factory_system_setup import ORIGIN, FakeDisplay, Native, Normal
from tests.test_factory_system_setup import adopted as adopted
from tests.test_softap_ipc_timeouts import VirtualClock
from tests.test_softap_runtime import Network
from tests.test_softap_runtime import activation as handoff_activation
from tests.test_softap_runtime import prepared as handoff_prepared
from tests.test_softap_transport import rpc


class AP:
    def __init__(self, calls):
        self.calls, self.qr = calls, None
    async def start(self, workflow, *, channel=None):
        self.calls.append("ap.start")
    async def stop(self, *, channel=None):
        self.calls.append("ap.stop")
    async def ensure_active(self):
        pass
    def encode_qr(self, frame_id, pin, token):
        raw = encode_qr(frame_id, pin, token, "Inky-1234abcd", "a" * 24)
        self.qr = json.loads(raw)
        return raw


async def connect(server, qr):
    port = server.server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    length = struct.unpack("!I", await reader.readexactly(4))[0]
    manifest = json.loads(await reader.readexactly(length))
    assert manifest["id"] == qr["id"]
    certificate = base64.b64decode(manifest["c"], validate=True)
    key = x509.load_der_x509_certificate(certificate).public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    assert hashlib.sha256(key).hexdigest() == qr["k"]
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # fixture explicitly pins actual TLS DER below
    context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
    if manifest["p"] == "bootstrap":
        context.set_alpn_protocols(["inky-bootstrap/1"])
    await writer.start_tls(context)
    assert writer.get_extra_info("ssl_object").getpeercert(binary_form=True) == certificate
    return reader, writer, manifest["p"]


async def test_qr_claim_setup_normal_prepare_activate_confirm_complete_photo(tmp_path):
    credentials = auth.reset_credentials(tmp_path)
    def epoch():
        record = auth._parse_record(credentials.path, auth._read_record(credentials.path))
        return credential_epoch(record.salt, record.digest)
    directory = tmp_path / "provisioning"
    result = FirstBootCoordinator(directory, FakeOS(), epoch).initialize()
    native, network = Native(), Network(state="awaiting_confirmation")
    ap = AP(network.calls)
    def server(transport, identity, *, profile=NORMAL_PROFILE):
        return SoftAPServer(transport, identity, profile=profile, host="127.0.0.1", port=0)
    runtime = FactoryContinuationRuntime(result, epoch, FakeDisplay(), directory,
        system_setup=native, network=network, softap=ap, server_factory=server,
        normal_service_factory=Normal)
    owner, claim_id, token = str(uuid4()), str(uuid4()), "b" * 64
    writers = []
    try:
        await runtime.start()
        assert ap.qr["v"] == 3 and network.calls == ["ap.start"]
        reader, writer, profile = await connect(runtime.bluez, ap.qr)
        writers.append(writer)
        assert profile == "bootstrap"
        reply = await rpc(reader, writer, {"v": 1, "id": claim_id, "op": "bootstrap.claim",
            "claim_token": ap.qr["t"], "owner_id": owner, "owner_token": token})
        assert reply["ok"] and reply["result"]["next_step"] == "system_setup"
        def setup(operation, **args):
            return {"v": 2, "id": str(uuid4()), "op": "system_setup." + operation,
                    "owner_id": owner, "owner_token": token, "claim_request_id": claim_id, **args}
        assert (await rpc(reader, writer, setup("negotiate", versions=[2])))["ok"]
        operation = str(uuid4())
        challenge = await rpc(reader, writer, setup("challenge", op_id=operation, supersedes_op_id=None))
        assert challenge["ok"], challenge
        clock = int(__import__("time").time())
        accepted = await rpc(reader, writer, setup("apply", op_id=operation,
            challenge_id=challenge["result"]["challenge_id"], nonce=challenge["result"]["nonce"],
            utc_seconds=clock, country="FR"))
        assert accepted["ok"] and accepted["result"]["durability"] == "not_confirmed"
        await runtime.operations.drain()
        native.live.update(https_origin=ORIGIN, origin_status="avahi_current")
        reader, writer, profile = await connect(runtime.provisioning.bluez, ap.qr)
        writers.append(writer)
        assert profile == "normal" and runtime.identity.spki_sha256 == ap.qr["k"]
        transaction = str(uuid4())
        base = {"v": 1, "owner_id": owner, "owner_token": token}
        prepared = await rpc(reader, writer, {**base, "id": transaction, "op": "wifi.prepare",
            "ssid": "synthetic-home", "security": "wpa2", "password": "synthetic-password"})
        assert prepared["ok"] and prepared["result"]["expected_https_origin"] == ORIGIN
        assert "activate" not in network.calls
        accepted = await rpc(reader, writer, {**base, "id": str(uuid4()), "op": "wifi.activate",
                                              "transaction_id": transaction})
        assert accepted["ok"] and accepted["result"]["phase"] == "activation_requested"
        await asyncio.wait_for(network.activated.wait(), 2)
        assert network.calls.index("ap.stop") < network.calls.index("activate")
        # Route-layer HTTPS/owner tests are separate; invoke that route's exact
        # authority here before native exposes committed station observation.
        assert runtime.https_origin() is None
        confirmed = await runtime.provisioning.confirm(owner, token, transaction)
        assert confirmed["state"] == "committed"
        await runtime.operations.drain()
        native.live.update(readiness="network_ready", network={"id": transaction, "state": "committed"})
        assert (await rpc(reader, writer, setup("negotiate", versions=[2])))["ok"]
        completed = await rpc(reader, writer, setup("continue", op_id=operation))
        assert completed["ok"] and completed["result"]["state"] == "complete"
        authority = await runtime.authorize_photo(owner, token, claim_id, operation)
        assert authority["owner_id"] == owner
    finally:
        await runtime.stop()
        for writer in writers:
            writer.close()
        result.ownership.close()


@pytest.mark.parametrize("invalid_apply", [False, True])
async def test_shutdown_drains_open_bootstrap_setup_channel(tmp_path, invalid_apply):
    credentials = auth.reset_credentials(tmp_path)
    def epoch():
        record = auth._parse_record(credentials.path, auth._read_record(credentials.path))
        return credential_epoch(record.salt, record.digest)
    directory = tmp_path / "provisioning"
    result = FirstBootCoordinator(directory, FakeOS(), epoch).initialize()
    native, network = Native(), Network()
    ap = AP(network.calls)
    def server(transport, identity, *, profile=NORMAL_PROFILE):
        return SoftAPServer(transport, identity, profile=profile, host="127.0.0.1", port=0)
    runtime = FactoryContinuationRuntime(result, epoch, FakeDisplay(), directory,
        system_setup=native, network=network, softap=ap, server_factory=server,
        normal_service_factory=Normal)
    writer = None
    try:
        await runtime.start()
        reader, writer, _ = await connect(runtime.bluez, ap.qr)
        owner, claim_id = str(uuid4()), str(uuid4())
        assert (await rpc(reader, writer, {"v": 1, "id": claim_id, "op": "bootstrap.claim",
            "claim_token": ap.qr["t"], "owner_id": owner, "owner_token": "b" * 64}))["ok"]
        def setup(operation, **args):
            return {"v": 2, "id": str(uuid4()), "op": "system_setup." + operation,
                    "owner_id": owner, "owner_token": "b" * 64, "claim_request_id": claim_id, **args}
        assert (await rpc(reader, writer, setup("negotiate", versions=[2])))["ok"]
        operation = str(uuid4())
        challenge = await rpc(reader, writer, setup("challenge", op_id=operation, supersedes_op_id=None))
        assert challenge["ok"]
        if invalid_apply:
            result_rpc = await rpc(reader, writer, setup("apply", op_id=operation,
                challenge_id=challenge["result"]["challenge_id"], nonce=challenge["result"]["nonce"],
                utc_seconds=1792152000, country="FR", extra="deliberately-invalid"))
            assert result_rpc["error"] == "invalid_request"
    finally:
        await runtime.stop()
        if writer is not None:
            writer.close()
        result.ownership.close()
    assert all(channel.drained for channel in native.channels)


async def test_recovery_ap_start_has_separate_budget_after_settled(adopted, monkeypatch):
    v = adopted
    session, network, message = await handoff_prepared(v, state="rolled_back")
    entered, release = asyncio.Event(), asyncio.Event()
    controller = v.runtime.softap
    async def slow_start(workflow, *, channel):
        assert not channel.closed
        entered.set()
        await release.wait()
        network.calls.append("ap.start")
    monkeypatch.setattr(controller, "start", slow_start)
    await handoff_activation(v, session, message)
    loop = asyncio.get_running_loop()
    clock = VirtualClock(loop)
    with monkeypatch.context() as patch:
        patch.setattr(loop, "time", clock)
        session.after_response()
        await entered.wait()
        clock.advance(31)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        task = v.runtime._handoffs[message["transaction_id"]]
        assert not task.done()  # the expired observation timer cannot cancel AP start
        release.set()
        await v.runtime.operations.drain()
    assert network.calls[-2:] == ["settled", "ap.start"]
    assert not v.runtime._handoff_channels


async def test_recovery_settled_observation_still_expires_without_ap_start(adopted, monkeypatch):
    v = adopted
    session, network, message = await handoff_prepared(v, state="rolled_back", settled=False)
    observed_settled = asyncio.Event()
    network.on_settled = observed_settled.set
    await handoff_activation(v, session, message)
    loop = asyncio.get_running_loop()
    clock = VirtualClock(loop)
    with monkeypatch.context() as patch:
        patch.setattr(loop, "time", clock)
        session.after_response()
        await observed_settled.wait()
        clock.advance(31)
        await v.runtime.operations.drain()
    assert network.calls.count("settled") == 1
    assert "ap.start" not in network.calls
    assert not v.runtime._handoff_channels


async def test_recovery_revalidates_owner_after_settled_before_ap_start(adopted):
    v = adopted
    session, network, message = await handoff_prepared(v, state="rolled_back", settled=True)
    network.on_settled = lambda: v.result.ownership.revoke(v.owner)
    await handoff_activation(v, session, message)
    session.after_response()
    await v.runtime.operations.drain()
    assert network.calls.count("settled") == 1
    assert "ap.start" not in network.calls
    assert not v.runtime._handoff_channels
