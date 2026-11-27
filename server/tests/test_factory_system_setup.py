"""Mac lifecycle with real durable owners/certificates and inert OS/radio fixtures."""
from __future__ import annotations

import asyncio
import copy
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from inky_web import auth
from inky_web.provisioning import system_setup_wire as wire
from inky_web.provisioning.bootstrap_identity import ClockResult
from inky_web.provisioning.factory_continuation import FactoryContinuationRuntime, SetupSession
from inky_web.provisioning.first_boot import FirstBootCoordinator
from inky_web.provisioning.network import NetworkUnavailable
from inky_web.provisioning.ownership import OwnershipError, credential_epoch
from inky_web.provisioning.system_setup_ipc import SetupUnavailable
from tests.test_bootstrap_runtime import FakeBlueZ, FakeOS
from tests.test_bootstrap_runtime import FakeDisplay as BootstrapDisplay


class FakeDisplay(BootstrapDisplay):
    @property
    def reserved(self):
        return self.reservation

    def begin_shutdown(self):
        self.closing = True

BOOT = "00000000-0000-0000-0000-000000000001"
ORIGIN = "https://inky-" + "a" * 32 + ".local:8443"


class Native:
    def __init__(self):
        self.calls, self.channels = [], []
        self.workflow = self.operation = self.completion = None
        self.live = {"boot_id": BOOT, "readiness": "wlan_closed", "https_origin": None,
                     "origin_status": "unavailable", "clock_status": "not_attested_current_boot", "network": None}
        self.apply_entered, self.release = asyncio.Event(), asyncio.Event()
        self.release.set()
        self.resume_error = False

    def snapshot(self):
        return copy.deepcopy({"workflow": self.workflow, "state": "completed" if self.completion else
            self.operation["state"] if self.operation else "not_started",
            "latest_operation_id": self.operation["operation_id"] if self.operation else None,
            "operation": self.operation, "completion": self.completion, "live": self.live, "network_head": None})

    async def inspect(self, workflow):
        self.calls.append("inspect")
        self.workflow = workflow
        return self.snapshot()

    async def status(self, operation_id):
        self.calls.append("status")
        if self.operation is None or self.operation["operation_id"] != operation_id:
            raise SetupUnavailable("not_found")
        snap = self.snapshot()
        return {key: snap[key] for key in ("operation", "completion", "live", "network_head")}

    async def resume(self, completion_id):
        self.calls.append("resume")
        assert self.completion["completion_id"] == completion_id
        if self.resume_error:
            raise SetupUnavailable("network_unconfirmed")
        return {key: self.snapshot()[key] for key in ("completion", "live", "network_head")}

    async def open(self, binding):
        channel = Channel(self, binding)
        self.channels.append(channel)
        return channel


class Channel:
    def __init__(self, native, binding):
        self.native = native
        self.binding = {**binding, "boot_id": BOOT, "candidate_sha256": "c" * 64,
                        "context_sha256": "d" * 64, "main_invocation_id": "1" * 32}
        self.closed = self.drained = False
        self.drain_release = asyncio.Event()
        self.drain_release.set()

    def close(self):
        self.closed = True

    async def drain(self):
        self.close()
        await self.drain_release.wait()
        self.drained = True

    async def call(self, operation, **args):
        assert not self.closed
        self.native.calls.append(operation)
        if operation == "setup.challenge":
            return {**args, "challenge_id": str(uuid4()), "nonce": "9" * 64,
                    "issued_boottime_ns": 1, "expires_boottime_ns": 30_000_000_001,
                    "binding": self.binding.copy()}
        if operation == "setup.apply":
            n = self.native
            n.operation = {"operation_id": args["operation_id"], "binding": self.binding.copy(),
                           "state": "pending", "receipt": None}
            n.apply_entered.set()
            await n.release.wait()
            if self.closed:
                n.operation["state"] = "uncertain"
                raise SetupUnavailable("session_closed")
            receipt = {"binding": self.binding.copy(), "clock": {"utc_seconds": args["utc_seconds"]}}
            n.operation.update(state="effects_completed", receipt=receipt)
            n.live.update(readiness="country_radio_ready", clock_status="owner_asserted_current_boot")
            return copy.deepcopy(n.operation)
        if operation == "setup.complete":
            assert self.native.live["network"]["state"] == "committed"
            self.native.completion = {"completion_id": str(uuid4()), "workflow": self.native.workflow,
                "owner_id": self.binding["owner_id"], "claim_request_id": self.binding["claim_request_id"],
                "credential_epoch": self.binding["credential_epoch"], "operation_id": args["operation_id"],
                "publication": args["publication"]}
            return copy.deepcopy(self.native.completion)
        raise AssertionError(operation)


class Network:
    async def call(self, operation, **args):
        return {"ready": True} if operation == "health" else {"id": args.get("id"), "state": "committed"}

    def cancel_pending_sync(self):
        pass


class Normal:
    def __init__(self, runtime):
        self.runtime = runtime

    async def start(self):
        await self.runtime.provisioning.start()

    async def stop(self):
        await self.runtime.provisioning.stop()


@pytest.fixture
async def adopted(tmp_path, monkeypatch):
    monkeypatch.delenv("INKY_STUDIO_DISABLE_AUTH", raising=False)
    credentials = auth.reset_credentials(tmp_path)
    def epoch():
        c = auth._parse_record(credentials.path, auth._read_record(credentials.path))
        return credential_epoch(c.salt, c.digest)
    directory = tmp_path / "provisioning"
    coordinator = FirstBootCoordinator(directory, FakeOS(), epoch)
    result = coordinator.initialize()
    claim_id, owner = str(uuid4()), str(uuid4())
    token = result.ownership.open_factory_window(expected_epoch=epoch())
    result.ownership.claim(token.value, owner, "b" * 64, claim_id, epoch())
    native, display = Native(), FakeDisplay()
    runtime = FactoryContinuationRuntime(result, epoch, display, directory, system_setup=native,
        network=Network(), server_factory=FakeBlueZ, normal_service_factory=Normal)
    await runtime.start()
    session = SetupSession()
    runtime._sessions.add(session)
    def request(operation, **args):
        return {"v": 2, "id": str(uuid4()), "op": "system_setup." + operation,
                "owner_id": owner, "owner_token": "b" * 64, "claim_request_id": claim_id, **args}
    value = SimpleNamespace(runtime=runtime, result=result, native=native, session=session,
        request=request, directory=directory, display=display, coordinator=coordinator,
        credentials=credentials, epoch=epoch, owner=owner, claim_id=claim_id)
    yield value
    await runtime.stop()
    result.ownership.close()


async def command(v, operation, **args):
    message = v.request(operation, **args)
    reply = await v.runtime._setup_command(v.session, message)
    wire.validate_response(reply, operation=message["op"], context={"rpc_id": message["id"], **message})
    return reply


async def challenge(v):
    assert (await command(v, "negotiate", versions=[2]))["ok"]
    op_id = str(uuid4())
    reply = await command(v, "challenge", op_id=op_id, supersedes_op_id=None)
    assert reply["ok"]
    return {"op_id": op_id, "challenge_id": reply["result"]["challenge_id"],
            "nonce": reply["result"]["nonce"], "utc_seconds": 1792152000, "country": "FR"}


async def apply(v):
    args = await challenge(v)
    assert (await command(v, "apply", **args))["result"]["durability"] == "not_confirmed"
    await v.runtime.operations.drain()
    return args


async def complete(v):
    args = await apply(v)
    v.session = SetupSession()
    v.runtime._sessions.add(v.session)
    await command(v, "negotiate", versions=[2])
    v.native.live.update(readiness="network_ready", https_origin=ORIGIN, origin_status="avahi_current",
                        network={"id": str(uuid4()), "state": "committed"})
    reply = await command(v, "continue", op_id=args["op_id"])
    assert reply["result"]["action"] == "completion_finalized", reply
    return args


async def test_apply_ack_fast_owned_exact_intent_and_handoff(adopted):
    v = adopted
    args = await challenge(v)
    v.native.release.clear()
    reply = await asyncio.wait_for(command(v, "apply", **args), 0.5)
    assert reply["result"]["submission"] == "registered"
    await v.native.apply_entered.wait()
    assert not (v.directory / "identity.json").exists()
    intent = json.loads((v.directory / "system-setup-intents.json").read_text())["intents"][args["op_id"]]
    assert intent["utc_seconds"] == args["utc_seconds"] and "owner_token" not in intent
    assert (await command(v, "status", op_id=args["op_id"]))["result"]["state"] == "applying"
    assert (await command(v, "apply", **{**args, "utc_seconds": args["utc_seconds"] + 1}))["error"] == "request_conflict"
    v.native.release.set()
    await v.runtime.operations.drain()
    assert v.runtime.identity.frame_id == v.result.prepared_identity.frame_id
    assert v.runtime.provisioning.owners is v.result.ownership
    assert v.runtime.provisioning.network is v.runtime.network
    assert v.runtime.provisioning.display is v.display
    assert not v.session.active and all(channel.drained for channel in v.native.channels)


async def test_disconnect_keeps_uncertain_and_never_publishes_or_replays(adopted):
    v = adopted
    args = await challenge(v)
    v.native.release.clear()
    await command(v, "apply", **args)
    await v.native.apply_entered.wait()
    v.session.close()
    v.native.release.set()
    await v.runtime.operations.drain()
    assert not (v.directory / "identity.json").exists()
    assert v.native.operation["state"] == "uncertain"
    v.session = SetupSession()
    v.runtime._sessions.add(v.session)
    assert (await command(v, "negotiate", versions=[2]))["result"]["latest_operation_id"] == args["op_id"]
    assert (await command(v, "status", op_id=args["op_id"]))["result"]["next_step"] == "recover_explicit"
    before = list(v.native.calls)
    assert (await command(v, "continue", op_id=args["op_id"]))["error"] == "recovery_required"
    assert v.native.calls[len(before):] == ["status"]


async def test_handoff_waits_for_channel_guard_drain(adopted):
    v = adopted
    args = await challenge(v)
    channel = v.native.channels[-1]
    channel.drain_release.clear()
    await command(v, "apply", **args)
    for _ in range(1000):
        if channel.closed:
            break
        await asyncio.sleep(0.001)
    assert channel.closed and not channel.drained
    assert v.runtime.normal_service is None and v.runtime.provisioning is None
    channel.drain_release.set()
    await v.runtime.operations.drain()
    assert channel.drained and v.runtime.provisioning.available


@pytest.mark.parametrize("field,replacement,error", [
    ("owner_token", "f" * 64, "unauthorized"),
    ("claim_request_id", "00000000-0000-0000-0000-000000000099", "request_not_found"),
    ("owner_id", "00000000-0000-0000-0000-000000000098", "unauthorized"),
])
async def test_claim_bound_authority_before_os_read(adopted, field, replacement, error):
    v = adopted
    message = {**v.request("negotiate", versions=[2]), field: replacement}
    before = len(v.native.calls)
    assert (await v.runtime._setup_command(v.session, message))["error"] == error
    assert len(v.native.calls) == before


async def test_negotiate_observed_null_not_swallowed_error(adopted):
    v = adopted
    assert (await command(v, "negotiate", versions=[2]))["result"]["latest_operation_id"] is None
    async def unavailable(_):
        raise SetupUnavailable("unavailable")
    v.runtime.system_setup.inspect = unavailable
    assert (await command(v, "negotiate", versions=[2]))["error"] == "unavailable"


async def test_wait_origin_allows_ble_wifi_but_blocks_lan(adopted):
    v = adopted
    args = await apply(v)
    v.session = SetupSession()
    await command(v, "negotiate", versions=[2])
    assert (await command(v, "status", op_id=args["op_id"]))["result"]["next_step"] == "wait_origin"
    await v.runtime._network_admission()
    with pytest.raises(NetworkUnavailable):
        await v.runtime._network_admission(lan=True)
    assert (await v.runtime.provisioning.command({"v": 1, "id": str(uuid4()), "op": "wifi.scan",
        "owner_id": v.owner, "owner_token": "b" * 64}))["ok"]


async def test_reboot_completion_no_owner_no_factory_init_preserves_photo(adopted):
    v = adopted
    await complete(v)
    cert = v.runtime.identity.cert_der
    image = v.directory.parent / "last-photo.png"
    image.write_bytes(b"existing photo bytes")
    v.result.ownership.revoke(v.owner)
    before = list(v.native.calls)
    await v.runtime.stop()
    v.result.ownership.close()
    v.coordinator.adapter.begin_initialization = lambda _: pytest.fail("Factory init replay")
    reopened = v.coordinator.initialize(resume_consumed=True)
    display = FakeDisplay()
    v.native.resume_error = True
    runtime = FactoryContinuationRuntime(reopened, v.epoch, display, v.directory,
        system_setup=v.native, network=Network(), server_factory=FakeBlueZ, normal_service_factory=Normal)
    try:
        await runtime.start()
        assert runtime.historical_completed() and runtime.identity.cert_der == cert
        assert runtime.https_origin() is None and not display.images
        assert image.read_bytes() == b"existing photo bytes"
        assert "setup.apply" not in v.native.calls[len(before):]
        assert "resume" in v.native.calls[len(before):]
    finally:
        await runtime.stop()
        reopened.ownership.close()


async def test_data_only_finishes_durable_candidate_exact_bytes(adopted, monkeypatch):
    v = adopted
    prepared = v.result.prepared_identity
    op_id = str(uuid4())
    original = prepared.__class__._publish_candidate
    def lost(_self, _operation):
        raise OSError("publication interrupted")
    monkeypatch.setattr(prepared.__class__, "_publish_candidate", lost)
    with pytest.raises(OSError):
        prepared.publish_initial(operation_id=op_id, clock_result=ClockResult(op_id, 1792152000))
    candidate = json.loads((v.directory / "bootstrap-identity.json").read_text())["operations"][0]["candidate_cert_pem"].encode()
    monkeypatch.setattr(prepared.__class__, "_publish_candidate", original)
    v.native.operation = {"operation_id": op_id, "state": "effects_completed", "receipt": None,
        "binding": {**v.runtime.workflow, "owner_id": v.owner, "claim_request_id": v.claim_id}}
    await command(v, "negotiate", versions=[2])
    assert (await command(v, "continue", op_id=op_id))["result"]["action"] == "publication_finalized"
    await v.runtime.operations.drain()
    assert v.runtime.identity.cert_pem == candidate and "setup.apply" not in v.native.calls


async def test_recovery_operation_keeps_initial_publication_provenance(adopted):
    v = adopted
    first = await apply(v)
    initial, cert = v.result.prepared_identity.initial_publication(), v.runtime.identity.cert_der
    v.session = SetupSession()
    v.runtime._sessions.add(v.session)
    await command(v, "negotiate", versions=[2])
    new_id = str(uuid4())
    reply = await command(v, "challenge", op_id=new_id, supersedes_op_id=first["op_id"])
    await command(v, "apply", op_id=new_id, challenge_id=reply["result"]["challenge_id"],
                  nonce=reply["result"]["nonce"], utc_seconds=1792152001, country="FR")
    await v.runtime.operations.drain()
    v.native.live.update(readiness="network_ready", https_origin=ORIGIN, origin_status="avahi_current",
                        network={"id": str(uuid4()), "state": "committed"})
    assert (await command(v, "continue", op_id=new_id))["result"]["action"] == "completion_finalized"
    assert v.native.completion["operation_id"] == new_id
    assert v.native.completion["publication"] == initial
    assert initial["publication_operation_id"] != new_id and v.runtime.identity.cert_der == cert


async def test_factory_photo_new_credential_no_cookie_authority(adopted):
    import hashlib

    import httpx
    from fastapi import FastAPI

    from inky_web.api.photo_access import router
    from inky_web.main import AuthMiddleware
    from inky_web.photo_access import PhotoAccessStore

    v = adopted
    args = await complete(v)
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(router, prefix="/api")
    sessions = auth.SessionStore()
    service = auth.CredentialService(v.credentials, sessions)
    epoch = hashlib.sha256(b"inky-photo-epoch-v1\0" + v.credentials.salt + v.credentials.digest).hexdigest()
    value = PhotoAccessStore(v.directory.parent / "photo-access", lambda: epoch, gate=service._lock)
    app.state.sessions, app.state.auth_service = sessions, service
    app.state.photo_access, app.state.photo_access_limiter = value, auth.LoginRateLimiter(max_attempts=30)
    app.state.frame_identity, app.state.factory_continuation = v.runtime.identity, v.runtime
    app.state.photo_access_origin = v.runtime.https_origin
    headers = {"x-inky-owner-id": v.owner, "x-inky-owner-token": "b" * 64}
    body = {"device_id": str(uuid4()), "device_token": "c" * 64, "request_id": v.claim_id,
            "claim_request_id": v.claim_id, "setup_op_id": args["op_id"]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client:
        response = await client.post("/api/auth/factory-device-enroll", json=body, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["role"] == "owner"
        assert response.headers["cache-control"] == "no-store" and "set-cookie" not in response.headers
        retry = await client.post("/api/auth/factory-device-enroll", json=body, headers=headers)
        assert retry.json() == response.json()
        assert value.authenticate(body["device_id"], body["device_token"]).role == "owner"
        denied = await client.post("/api/auth/factory-device-enroll", json=body,
                                  headers={"cookie": "inky_session=whatever"})
        assert denied.status_code == 401
        alias = await client.post("/api/auth/factory-device-enroll", json={**body, "device_token": "b" * 64}, headers=headers)
        assert alias.status_code == 422
        plain = await client.post("http://other.invalid/api/auth/factory-device-enroll", json=body, headers=headers)
        assert plain.status_code == 403
        v.native.live.update(https_origin=None, origin_status="unavailable")
        wait = await client.post("/api/auth/factory-device-enroll", json=body, headers=headers)
        assert wait.status_code == 409


async def test_normal_service_death_calls_actual_outer_stop(monkeypatch):
    from inky_web.main import FactoryNormalService
    stopped, failed = asyncio.Event(), asyncio.Event()
    factory = SimpleNamespace(request_stop=stopped.set)
    async def run(service):
        service.ready.set()
        await failed.wait()
        raise RuntimeError("listener closed")
    monkeypatch.setattr(FactoryNormalService, "_run", run)
    service = FactoryNormalService(factory)
    await service.start()
    failed.set()
    await asyncio.wait_for(stopped.wait(), 1)
    with pytest.raises(RuntimeError):
        await service.stop()


async def test_explicit_data_only_does_not_restore_initial_der_over_renewal(adopted):
    v = adopted
    await apply(v)
    old = v.runtime.identity
    # Use real existing normal renewal builder, advancing past renewal margin.
    from datetime import timedelta
    renewed = old.refresh_certificate_if_needed(now=old.issued_at + timedelta(days=350))
    before = renewed.cert_der
    v.result.prepared_identity.continue_initial_publication()
    current = v.result.prepared_identity.load_current_identity()
    assert current.cert_der == before


async def test_reconnect_after_unsubmitted_challenge_negotiates_again(adopted):
    v = adopted
    await challenge(v)
    v.session.close()
    v.session = SetupSession()
    original = v.native.inspect
    async def challenged(workflow):
        snapshot = await original(workflow)
        return {**snapshot, "state": "challenged", "latest_operation_id": str(uuid4()), "operation": None}
    v.native.inspect = challenged
    reply = await command(v, "negotiate", versions=[2])
    assert reply["ok"] and reply["result"]["latest_operation_id"] is None
    assert "setup.apply" not in v.native.calls


async def test_normal_bind_failure_is_runtime_error_and_drains_started_listener(adopted, monkeypatch):
    from contextlib import asynccontextmanager

    import uvicorn

    from inky_web import main

    v = adopted
    await apply(v)
    stopped = asyncio.Event()
    factory = SimpleNamespace(identity=v.runtime.identity, provisioning=v.runtime.provisioning,
                              request_stop=stopped.set)
    @asynccontextmanager
    async def lifespan(*_args, **_kwargs):
        yield
    monkeypatch.setattr(main, "_legacy_lifespan", lifespan)
    events = []
    async def serve(server, sockets=None):
        if server.config.port == 8443:
            raise SystemExit(1)
        server.started = True
        while not server.should_exit:
            await asyncio.sleep(0)
    async def shutdown(server, sockets=None):
        events.append((server.config.port, "drained"))
    monkeypatch.setattr(uvicorn.Server, "serve", serve)
    monkeypatch.setattr(uvicorn.Server, "shutdown", shutdown)
    service = main.FactoryNormalService(factory)
    with pytest.raises(RuntimeError):
        await service.start()
    assert stopped.is_set() and (8000, "drained") in events
    with pytest.raises(RuntimeError):
        await service.stop()


@pytest.mark.parametrize("event", ["reset", "disconnect", "close", "expire"])
async def test_actual_gatt_peer_invalidates_context_and_ipc_on_all_events(adopted, event):
    v = adopted
    transport = v.runtime.transport
    transport.write("phone", b"\0" + b"1" * 16)
    peer = transport.sessions["phone"].peer
    v.session = peer.session
    await command(v, "negotiate", versions=[2])
    await command(v, "challenge", op_id=str(uuid4()), supersedes_op_id=None)
    channel = peer.session.channel
    old_generation = peer.session.generation
    if event == "reset":
        transport.write("phone", b"\0" + b"2" * 16)
        assert transport.sessions["phone"].peer.session.generation > old_generation
    elif event == "disconnect":
        transport.disconnect("phone")
    elif event == "close":
        transport.write("phone", b"\2")
    else:
        transport.sessions["phone"].touched -= 181
        transport.expire()
    await v.runtime.operations.drain()
    assert not peer.session.active and channel.closed and channel.drained


async def test_postcompletion_recovery_never_promotes_new_uncertain_op(adopted):
    v = adopted
    old_args = await complete(v)
    old_completion = copy.deepcopy(v.native.completion)
    v.session = SetupSession()
    v.runtime._sessions.add(v.session)
    await command(v, "negotiate", versions=[2])
    new_id = str(uuid4())
    reply = await command(v, "challenge", op_id=new_id, supersedes_op_id=old_args["op_id"])
    v.native.release.clear()
    await command(v, "apply", op_id=new_id, challenge_id=reply["result"]["challenge_id"],
                  nonce=reply["result"]["nonce"], utc_seconds=1792152001, country="FR")
    await v.native.apply_entered.wait()
    for _ in range(1000):
        if v.native.operation["operation_id"] == new_id:
            break
        await asyncio.sleep(0.001)
    status = await command(v, "status", op_id=new_id)
    assert status["result"]["state"] == "applying" and status["result"]["completion_id"] is None
    with pytest.raises(OwnershipError):
        await v.runtime.authorize_photo(v.owner, "b" * 64, v.claim_id, old_args["op_id"])
    v.native.release.set()
    await v.runtime.operations.drain()
    status = await command(v, "status", op_id=new_id)
    assert status["result"]["state"] == "wifi_pending" and status["result"]["completion_id"] is None
    v.native.live["readiness"] = "network_ready"
    reply = await command(v, "continue", op_id=new_id)
    assert reply["result"]["state"] == "complete"
    assert reply["result"]["completion_id"] != old_completion["completion_id"]
    assert v.native.completion["publication"] == old_completion["publication"]


async def test_injected_normal_core_initializes_neither_screen_owner_nor_welcome(adopted, monkeypatch):
    from inky_web import main, welcome
    from inky_web.inky.display import DisplayController
    from inky_web.provisioning.runtime import ProvisioningRuntime

    v = adopted
    await apply(v)
    display = DisplayController()
    display.initialize()
    shutdown = display.shutdown
    def forbidden(*_args, **_kwargs):
        pytest.fail("Transferred normal core recreated a prerequisite")
    monkeypatch.setattr(display, "initialize", forbidden)
    monkeypatch.setattr(display, "shutdown", forbidden)
    monkeypatch.setattr(auth, "load_or_create_credentials", forbidden)
    monkeypatch.setattr(welcome, "show_welcome", forbidden)
    provisioning = ProvisioningRuntime(v.directory, auth.CredentialService(v.credentials, auth.SessionStore()),
        display, v.runtime.identity, owners=v.result.ownership, network=v.runtime.network,
        owns_store=False, server_factory=FakeBlueZ, renew_certificate=False)
    factory = SimpleNamespace(display=display, provisioning=provisioning, https_origin=lambda: None,
                              prepare_rotation=provisioning.prepare_rotation)
    try:
        async with main._legacy_lifespan(main.app, factory=factory):
            assert main.app.state.display is display
            assert main.app.state.provisioning.owners is v.result.ownership
            assert main.app.state.provisioning.network is v.runtime.network
            assert main.app.state.photo_access is not None
        assert v.result.ownership.factory_status().first_owner_id == v.owner
    finally:
        shutdown()


async def test_fresh_qrv2_claim_enters_negotiated_setup_without_normal_creation(tmp_path, monkeypatch):
    monkeypatch.delenv("INKY_STUDIO_DISABLE_AUTH", raising=False)
    credentials = auth.reset_credentials(tmp_path)
    epoch = credential_epoch(credentials.salt, credentials.digest)
    directory = tmp_path / "provisioning"
    result = FirstBootCoordinator(directory, FakeOS(), lambda: epoch).initialize()
    display, native = FakeDisplay(), Native()
    runtime = FactoryContinuationRuntime(result, lambda: epoch, display, directory,
        system_setup=native, network=Network(), server_factory=FakeBlueZ, normal_service_factory=Normal)
    payloads = []
    original = runtime.screen.show_qr
    def capture(payload):
        payloads.append(json.loads(payload))
        original(payload)
    monkeypatch.setattr(runtime.screen, "show_qr", capture)
    try:
        await runtime.start()
        assert payloads[0]["v"] == 2 and not (directory / "identity.json").exists()
        claim = {"v": 1, "id": str(uuid4()), "op": "bootstrap.claim", "owner_id": str(uuid4()),
                 "owner_token": "b" * 64, "claim_token": payloads[0]["t"]}
        assert (await runtime.command(claim))["result"]["next_step"] == "system_setup"
        session = SetupSession()
        request = {"v": 2, "id": str(uuid4()), "op": "system_setup.negotiate", "versions": [2],
                   "owner_id": claim["owner_id"], "owner_token": claim["owner_token"], "claim_request_id": claim["id"]}
        assert (await runtime._setup_command(session, request))["result"]["selected_version"] == 2
        assert not (directory / "identity.json").exists()
    finally:
        await runtime.stop()
        result.ownership.close()


async def test_recovery_challenge_drains_already_admitted_wifi_work(adopted):
    v = adopted
    await apply(v)
    v.session = SetupSession()
    v.runtime._sessions.add(v.session)
    await command(v, "negotiate", versions=[2])
    entered, release = asyncio.Event(), asyncio.Event()
    async def network_call(operation, **_args):
        assert operation == "begin"
        entered.set()
        await release.wait()
        return {"state": "pending"}
    v.runtime.network.call = network_call
    wifi = asyncio.create_task(v.runtime.provisioning.command({"v": 1, "id": str(uuid4()), "op": "wifi.begin",
        "owner_id": v.owner, "owner_token": "b" * 64, "ssid": "fixture", "security": "open", "password": ""}))
    await entered.wait()
    count = v.native.calls.count("setup.challenge")
    challenge_task = asyncio.create_task(command(v, "challenge", op_id=str(uuid4()), supersedes_op_id=None))
    await asyncio.sleep(0.02)
    assert not challenge_task.done() and v.native.calls.count("setup.challenge") == count
    release.set()
    assert (await wifi)["ok"]
    assert (await challenge_task)["ok"]
    assert v.native.calls.count("setup.challenge") == count + 1


async def test_password_rotation_closes_setup_context_before_credential_replace(adopted):
    v = adopted
    await complete(v)
    v.session = SetupSession()
    v.runtime._sessions.add(v.session)
    await command(v, "negotiate", versions=[2])
    await command(v, "challenge", op_id=str(uuid4()), supersedes_op_id=None)
    channel = v.session.channel
    old_bytes = v.credentials.path.read_bytes()
    replacement = auth._new_credentials(v.directory.parent, "replacement-password", bootstrap=False)
    await asyncio.to_thread(v.runtime.prepare_rotation, replacement, v.owner)
    assert v.credentials.path.read_bytes() == old_bytes
    assert not v.session.active and channel.closed
    await v.runtime.operations.drain()
    assert channel.drained
