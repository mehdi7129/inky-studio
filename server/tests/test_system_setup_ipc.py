"""Actual Unix streams with injected proofs; no native peer qualification."""
import asyncio
import json
import socket
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

from inky_web.provisioning import system_setup_ipc as ipc

BOOT = "11111111-1111-4111-8111-111111111111"


def uid():
    return str(uuid4())


def owner():
    return {"initialization_intent": uid(), "initialization_receipt_digest": "1" * 64,
            "frame_id": uid(), "spki_sha256": "2" * 64, "credential_epoch": "3" * 64,
            "owner_id": uid(), "claim_request_id": uid(), "session_id": uid()}


def observed(value):
    return {**value, "boot_id": BOOT, "candidate_sha256": "4" * 64,
            "context_sha256": "5" * 64, "main_invocation_id": "6" * 32}


def snapshot(workflow):
    live = {"boot_id": BOOT, "candidate_sha256": "4" * 64, "context_sha256": "5" * 64,
            "readiness": "wlan_closed", "clock_status": "not_attested_current_boot",
            "country_receipt_sha256": None, "radio_receipt_sha256": None,
            "https_origin": None, "origin_status": "unavailable", "network": None}
    return {"workflow": workflow, "state": "not_started", "latest_operation_id": None,
            "operation": None, "completion": None, "live": live, "network_head": None}


@pytest.fixture
async def unix_service():
    servers, tasks = [], set()
    directory = tempfile.TemporaryDirectory(prefix="inky-setup-", dir="/tmp")
    async def create(callback):
        path, requests = str(Path(directory.name) / str(len(servers))), []
        async def serve(reader, writer):
            task = asyncio.current_task()
            tasks.add(task)
            try:
                while raw := await reader.readline():
                    request = json.loads(raw)
                    requests.append(request)
                    result = await callback(request)
                    if result is None:
                        continue
                    output = result if isinstance(result, bytes) else json.dumps(
                        {"v": 1, "id": request["id"], "ok": True, "result": result}).encode() + b"\n"
                    writer.write(output)
                    await writer.drain()
            except (ConnectionError, asyncio.CancelledError):
                pass
            finally:
                writer.close()
                await writer.wait_closed()
                tasks.discard(task)
        server = await asyncio.start_unix_server(serve, path)
        servers.append(server)
        return path, requests
    yield create
    for server in servers:
        server.close()
        await server.wait_closed()
    for task in tuple(tasks):
        task.cancel()
    await asyncio.gather(*tuple(tasks), return_exceptions=True)
    directory.cleanup()


def proof(events):
    @contextmanager
    def guard(connection):
        assert connection.fileno() >= 0
        assert connection.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) == socket.SOCK_STREAM
        events.append("entered")
        try:
            yield
        finally:
            assert connection.fileno() == -1
            events.append("released")
    return guard


async def test_persistent_owner_channel_and_guard_lifetime(unix_service):
    binding, events = owner(), []
    async def respond(request):
        if request["op"] == "setup.open":
            return {"binding": observed(request["args"]["binding"])}
        return {**request["args"], "challenge_id": uid(), "nonce": "a" * 64,
                "issued_boottime_ns": 100, "expires_boottime_ns": 30_000_000_100,
                "binding": observed(binding)}
    path, requests = await unix_service(respond)
    channel = await ipc.SystemSetupClient(path, peer_guard=proof(events), boot_id=lambda: BOOT).open(binding)
    assert events == ["entered"]
    challenge = await channel.call("setup.challenge", operation_id=uid(), supersedes_operation_id=None)
    assert challenge["binding"]["session_id"] == binding["session_id"]
    assert len(requests) == 2
    channel.close()
    with pytest.raises(ipc.SetupUnavailable, match="session_closed"):
        await channel.call("setup.challenge", operation_id=uid(), supersedes_operation_id=None)
    await channel.drain()
    assert events == ["entered", "released"]


@pytest.mark.parametrize("mode", ["missing", "raise", "boolean"])
async def test_proof_refusal_before_bytes(unix_service, mode):
    async def respond(_):
        pytest.fail("No bytes may precede proof")
    path, requests = await unix_service(respond)
    @contextmanager
    def rejected(_):
        if mode == "raise":
            raise ValueError("private proof diagnostic")
        yield True
    with pytest.raises(ipc.SetupUnavailable, match="^unavailable$"):
        await ipc.SystemSetupClient(path, peer_guard=None if mode == "missing" else rejected,
                                    boot_id=lambda: BOOT).open(owner())
    assert not requests


@pytest.mark.parametrize("mode", ["extra", "boot", "identity", "float", "double", "oversize", "duplicate", "nan"])
async def test_corrupt_open_refused_and_closed(unix_service, mode):
    binding, events = owner(), []
    async def respond(request):
        result = {"binding": observed(binding)}
        if mode == "extra":
            result["extra"] = 1
        elif mode == "boot":
            result["binding"]["boot_id"] = uid()
        elif mode == "identity":
            result["binding"]["session_id"] = uid()
        raw = json.dumps({"v": 1, "id": request["id"], "ok": True, "result": result}).encode()
        if mode == "float":
            raw = raw.replace(b'"v": 1', b'"v": 1.0')
        elif mode == "double":
            raw += b"\n{}"
        elif mode == "oversize":
            raw = b" " * 16385 + raw
        elif mode == "duplicate":
            raw = raw.replace(b'"v": 1', b'"v": 1, "v": 1')
        elif mode == "nan":
            raw = raw.replace(b'"v": 1', b'"v": NaN')
        return raw + b"\n"
    path, _ = await unix_service(respond)
    with pytest.raises(ipc.SetupUnavailable):
        await ipc.SystemSetupClient(path, peer_guard=proof(events), boot_id=lambda: BOOT).open(binding)
    assert events == ["entered", "released"]


async def test_independent_readonly_and_caller_cancellation_does_not_abandon_rpc(unix_service):
    binding, events, release, admitted = owner(), [], asyncio.Event(), asyncio.Event()
    async def respond(request):
        if request["op"] == "setup.open":
            return {"binding": observed(binding)}
        if request["op"] == "setup.challenge":
            admitted.set()
            await release.wait()
            return {**request["args"], "challenge_id": uid(), "nonce": "a" * 64,
                    "issued_boottime_ns": 100, "expires_boottime_ns": 30_000_000_100,
                    "binding": observed(binding)}
        return snapshot(request["args"]["workflow"])
    path, requests = await unix_service(respond)
    client = ipc.SystemSetupClient(path, peer_guard=proof(events), boot_id=lambda: BOOT)
    channel = await client.open(binding)
    work = asyncio.create_task(channel.call("setup.challenge", operation_id=uid(), supersedes_operation_id=None))
    await admitted.wait()
    assert (await client.inspect(ipc._workflow(binding)))["state"] == "not_started"
    assert events == ["entered", "entered", "released"]
    work.cancel()
    with pytest.raises(asyncio.CancelledError):
        await work
    assert channel._pending
    release.set()
    await asyncio.gather(*tuple(channel._pending))
    await channel.drain()
    assert len(requests) == 3 and events[-1] == "released"


async def test_close_immediate_eof_then_drain(unix_service):
    binding, events, admitted = owner(), [], asyncio.Event()
    async def respond(request):
        if request["op"] == "setup.open":
            return {"binding": observed(binding)}
        admitted.set()
        return None
    path, _ = await unix_service(respond)
    channel = await ipc.SystemSetupClient(path, peer_guard=proof(events), boot_id=lambda: BOOT).open(binding)
    work = asyncio.create_task(channel.call("setup.challenge", operation_id=uid(), supersedes_operation_id=None))
    await admitted.wait()
    channel.close()
    assert events == ["entered"]
    await channel.drain()
    with pytest.raises(ipc.SetupUnavailable):
        await work
    assert events == ["entered", "released"]


@pytest.mark.parametrize("raw", [b'{"a":-0}\n', b'{"a":1e0}\n', b'{"a":true,"a":1}\n', b'{"a":1}\n{}\n'])
def test_strict_lexemes(raw):
    with pytest.raises(ipc.SetupUnavailable):
        ipc._decode(raw)


def test_nested_hash_corruption_is_not_integrity():
    receipt = {"schema_version": 1, "clock": {"utc_seconds": 1790000000}}
    receipt["record_sha256"] = ipc.canonical_hash(receipt)
    ipc._integrity(receipt)
    receipt["clock"]["utc_seconds"] += 1
    with pytest.raises(ipc.SetupUnavailable):
        ipc._integrity(receipt)


def seal(value):
    return {**value, "record_sha256": ipc.canonical_hash(value)}


def applied(request, binding):
    args = request["args"]
    digest = ipc.canonical_hash({"workflow": ipc._workflow(binding), **{key: binding[key] for key in
                                ("owner_id", "claim_request_id", "credential_epoch")}, **args})
    gate = seal({"boot_id": BOOT, "candidate_sha256": "4" * 64, "closed_boottime_ns": 1,
                 "nm_wireless_enabled": False, "wlan_soft_blocked": True,
                 "restore_policy": "systemd-rfkill-masked"})
    clock = {"utc_seconds": args["utc_seconds"], "effect_start_boottime_ns": 2,
             "effect_end_boottime_ns": 3, "read_start_boottime_ns": 4, "read_end_boottime_ns": 5,
             "realtime_ns": args["utc_seconds"] * 10**9, "error_lower_ns": -3,
             "error_upper_ns": -1, "time_policy_sha256": "7" * 64}
    country = {"requested_country": "FR", "firmware_country": "FR", "firmware_ccode": "FR",
               "firmware_revision": 0, "global_country": "FR", "phy_label": "FR", "wiphy_index": 0,
               "interface": "wlan0", "channel_evidence_sha256": "8" * 64, "observed_boottime_ns": 6}
    radio = {"wireless_enabled": True, "wlan_soft_blocked": False, "wlan_hard_blocked": False,
             "wiphy_index": 0, "interface": "wlan0", "nm_unique_owner": ":1.2", "observed_boottime_ns": 7}
    receipt = seal({"schema_version": 1, "operation_id": args["operation_id"],
                    "request_sha256": digest, "binding": binding, "gate": gate,
                    "clock": clock, "country": country, "radio": radio})
    return {"operation_id": args["operation_id"], "state": "effects_completed", "request_sha256": digest,
            "binding": binding, "supersedes_operation_id": args["supersedes_operation_id"], "receipt": receipt}


@pytest.mark.parametrize("mode", ["valid", "historic", "hash", "binding", "utc", "country", "bounds", "boolean", "negative_zero"])
async def test_apply_full_receipt_and_historical_retry(unix_service, mode):
    binding, events = owner(), []
    async def respond(request):
        if request["op"] == "setup.open":
            return {"binding": observed(binding)}
        result = applied(request, observed(binding))
        receipt = result["receipt"]
        if mode == "historic":
            result["state"] = "superseded"
            result["binding"] = {**result["binding"], "session_id": uid(), "boot_id": uid()}
            receipt["binding"] = result["binding"]
            receipt["gate"]["boot_id"] = result["binding"]["boot_id"]
            receipt["gate"]["record_sha256"] = ipc.canonical_hash(receipt["gate"], exclude="record_sha256")
            receipt["record_sha256"] = ipc.canonical_hash(receipt, exclude="record_sha256")
        elif mode == "hash":
            receipt["record_sha256"] = "0" * 64
        elif mode == "binding":
            result["binding"] = {**result["binding"], "owner_id": uid()}
        elif mode in {"utc", "country", "bounds"}:
            if mode == "utc":
                receipt["clock"]["utc_seconds"] += 1
            elif mode == "country":
                receipt["country"]["requested_country"] = "DE"
            else:
                receipt["clock"]["error_lower_ns"] = 0
            receipt["record_sha256"] = ipc.canonical_hash(receipt, exclude="record_sha256")
        elif mode == "boolean":
            receipt["clock"]["utc_seconds"] = True
        elif mode == "negative_zero":
            raw = json.dumps({"v": 1, "id": request["id"], "ok": True, "result": result}).encode()
            return raw.replace(b'"firmware_revision": 0', b'"firmware_revision": -0') + b"\n"
        return result
    path, _ = await unix_service(respond)
    channel = await ipc.SystemSetupClient(path, peer_guard=proof(events), boot_id=lambda: BOOT).open(binding)
    args = {"operation_id": uid(), "supersedes_operation_id": None, "challenge_id": uid(),
            "nonce": "a" * 64, "utc_seconds": 1790000000, "country": "FR"}
    try:
        if mode in {"valid", "historic"}:
            result = await channel.call("setup.apply", **args)
            assert result["receipt"]["clock"]["utc_seconds"] == args["utc_seconds"]
            if mode == "historic":
                assert result["receipt"]["binding"] != channel.binding
        else:
            with pytest.raises(ipc.SetupUnavailable):
                await channel.call("setup.apply", **args)
    finally:
        await channel.drain()


def completed_snapshot(binding):
    args = {"operation_id": uid(), "supersedes_operation_id": None, "challenge_id": uid(),
            "nonce": "a" * 64, "utc_seconds": 1790000000, "country": "FR"}
    operation = applied({"args": args}, observed(binding))
    workflow = ipc._workflow(binding)
    publication = {"publication_operation_id": args["operation_id"], "initial_setup_operation_id": args["operation_id"],
                   "initial_certificate_sha256": "7" * 64, "frame_id": binding["frame_id"], "spki_sha256": binding["spki_sha256"]}
    completion = seal({"completion_id": uid(), "workflow": workflow, "owner_id": binding["owner_id"],
        "claim_request_id": binding["claim_request_id"], "credential_epoch": binding["credential_epoch"],
        "operation_id": args["operation_id"], "effect_receipt_sha256": operation["receipt"]["record_sha256"],
        "publication": publication, "country": "FR", "created_boot_id": BOOT,
        "initial_profile_uuid": uid(), "initial_network_transaction_id": uid()})
    network = {"id": uid(), "owner_id": binding["owner_id"], "state": "committed", "profile_uuid": uid(),
        "device": "wlan0", "nm_unique_owner": ":1.42", "boot_id": BOOT, "ipv4": ["192.0.2.10"],
        "active_profile_uuid": None, "profile_persistent": True, "commit_boot_id": uid(),
        "commit_nm_unique_owner": ":1.7"}
    network["active_profile_uuid"] = network["profile_uuid"]
    network["observation_sha256"] = ipc.canonical_hash(network)
    head = seal({"completion_id": completion["completion_id"], "revision": 1,
        "profile_uuid": completion["initial_profile_uuid"], "network_transaction_id": completion["initial_network_transaction_id"],
        "owner_id": binding["owner_id"], "country": "FR", "updated_boot_id": uid(),
        "source_observation_sha256": "8" * 64})
    result = snapshot(workflow)
    result.update(state="completed", operation=operation, completion=completion,
                  latest_operation_id=args["operation_id"], network_head=head)
    result["live"].update(readiness="network_ready", network=network)
    return result


@pytest.mark.parametrize("operation", ["setup.inspect", "setup.status", "setup.resume"])
async def test_readonly_historical_network_head_distinct_from_live(unix_service, operation):
    binding, events = owner(), []
    snap = completed_snapshot(binding)
    async def respond(request):
        if operation == "setup.inspect":
            return snap
        return {key: snap[key] for key in ("operation", "completion", "live", "network_head")
                if operation == "setup.status" or key != "operation"}
    path, _ = await unix_service(respond)
    client = ipc.SystemSetupClient(path, peer_guard=proof(events), boot_id=lambda: BOOT)
    if operation == "setup.inspect":
        result = await client.inspect(ipc._workflow(binding))
    elif operation == "setup.status":
        result = await client.status(snap["operation"]["operation_id"])
    else:
        with pytest.raises(ipc.SetupUnavailable):
            await client.resume(snap["completion"]["completion_id"])
        return
    assert result["network_head"]["profile_uuid"] != result["live"]["network"]["profile_uuid"]
    assert events == ["entered", "released"]


@pytest.mark.parametrize("state", ["pending", "uncertain", "effects_completed", "completed"])
async def test_historical_completion_does_not_complete_new_operation(unix_service, state):
    binding, events = owner(), []
    snap = completed_snapshot(binding)
    args = {"operation_id": uid(), "supersedes_operation_id": snap["operation"]["operation_id"],
            "challenge_id": uid(), "nonce": "a" * 64, "utc_seconds": 1790000001, "country": "FR"}
    operation = applied({"args": args}, observed(binding))
    if state in {"pending", "uncertain"}:
        operation.update(state=state, receipt=None)
    snap.update(operation=operation, latest_operation_id=operation["operation_id"], state=state)
    async def respond(_request):
        return snap
    path, _ = await unix_service(respond)
    client = ipc.SystemSetupClient(path, peer_guard=proof(events), boot_id=lambda: BOOT)
    if state == "completed":
        with pytest.raises(ipc.SetupUnavailable):
            await client.inspect(ipc._workflow(binding))
    else:
        result = await client.inspect(ipc._workflow(binding))
        assert result["completion"]["operation_id"] != result["operation"]["operation_id"]
        assert result["state"] == state
