"""Direct OS admission callbacks across fresh tasks, threads and IPC.

Sockets, files, SQLite and inter-process flock are real; the OS proof, peer
identity and radio/display are deliberate portable doubles, never qualification
of an installed helper graph, PIDFD support or physical first boot.
"""
from __future__ import annotations

import asyncio
import copy
import json
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from types import SimpleNamespace
from uuid import uuid4

import pytest

from inky_web.provisioning import factory_phase_a as phase
from inky_web.provisioning import factory_runtime, factory_writer
from inky_web.provisioning import initialization_ipc as ipc
from inky_web.provisioning.bootstrap_identity import (
    PREPARED_IDENTITY_FILENAME,
    PreparedFactoryIdentity,
)

from .test_factory_phase_a import admission as admission
from .test_factory_phase_a import assert_closed, production_runtime, run, snapshot, terminal
from .test_factory_phase_a import configured as configured
from .test_factory_phase_a import harness as harness
from .test_factory_phase_a import inky_env as inky_env
from .test_factory_phase_a import record as record
from .test_initialization_ipc import encode, success
from .test_initialization_ipc import root_peer as root_peer
from .test_initialization_ipc import serve as serve


def connect(harness, serve, monkeypatch, *, invalidate=None, block_begin=None):
    state = {"status": "authorized"}
    receipt = {"receipt_id": str(uuid4()), "digest": "d" * 64}
    proofs, constructions = [], []

    def handler(connection, request):
        nonlocal state
        assert not harness.admission.child_available()
        if request["op"] == "initialization.inspect":
            response = state
        else:
            state = {"status": "consumed", "intent": request["intent"], "receipt": receipt}
            response = state | {"status": "newly_consumed"}
        if invalidate == request["op"]:
            harness.validity[0] = False
        connection.sendall(encode(success(request, copy.deepcopy(response))))
        if block_begin is not None and request["op"] == "initialization.begin":
            block_begin[0].set()
            assert block_begin[1].wait(5)

    @contextmanager
    def guard(connection):
        assert connection.fileno() >= 0 and not harness.admission.child_available()
        proof = {"closed": False, "thread": threading.get_ident()}
        proofs.append(proof)
        try:
            yield
        finally:
            assert connection.fileno() == -1
            assert not harness.admission.child_available()
            proof["closed"] = True

    harness.peer_guard = guard
    server = serve(handler)

    def client(*args, **hooks):
        assert not args and hooks == {"peer_guard": guard}
        constructions.append(True)
        return ipc.InitializationIPCClient(server.path, **hooks)

    monkeypatch.setattr(factory_runtime, "InitializationIPCClient", client)
    return SimpleNamespace(server=server, proofs=proofs, constructions=constructions,
                           state=lambda: copy.deepcopy(state))


@pytest.mark.parametrize("missing", ["admission", "peer", "both"])
async def test_runner_requires_both_explicit_hooks_before_any_effect(harness, missing):
    before = snapshot(harness.configured.root)
    await terminal(phase.serve_factory_phase_a(
        harness.data, stop_requested=harness.stop, display_factory=harness.display_factory,
        runtime_factory=harness.runtime_factory,
        admission_check=None if missing in {"admission", "both"} else harness.check,
        initialization_peer_guard=None if missing in {"peer", "both"} else harness.peer_guard,
    ), "factory_runtime_refused")
    assert not harness.events and not harness.prepared and not harness.checks
    assert not harness.configured.adapter.inspect_calls
    assert snapshot(harness.configured.root) == before
    assert_closed(harness)


@pytest.mark.parametrize("hooks", [
    {"admission_check": lambda: None},
    {"initialization_peer_guard": lambda *_: None},
    {"admission_check": False, "initialization_peer_guard": lambda *_: None},
    {"admission_check": lambda: None, "initialization_peer_guard": False},
])
def test_prepare_rejects_partial_or_invalid_hooks_before_epoch_or_ipc(configured, monkeypatch, hooks):
    config = factory_runtime.select_runtime(configured.data)
    before = snapshot(configured.root)
    monkeypatch.setattr(factory_runtime, "_verified_epoch", lambda *_: pytest.fail("Invalid hook read epoch"))
    monkeypatch.setattr(factory_runtime, "InitializationIPCClient", lambda **_: pytest.fail("Invalid hook used IPC"))
    with pytest.raises(factory_runtime.FactoryRuntimeError, match="^factory_runtime_refused$"):
        factory_runtime.prepare_factory(config, **hooks)
    assert snapshot(configured.root) == before and not configured.adapter.inspect_calls


@pytest.mark.parametrize("return_value", [False, True, "e" * 64, object()])
@pytest.mark.parametrize("entry", ["runner", "prepare"])
async def test_admission_checker_must_return_exactly_none_before_effects(harness, monkeypatch, return_value, entry):
    before = snapshot(harness.configured.root)
    harness.check = lambda: return_value
    if entry == "runner":
        await terminal(run(harness), "factory_runtime_refused")
        assert harness.stop.is_set()
    else:
        config = factory_runtime.select_runtime(harness.data)
        monkeypatch.setattr(factory_runtime, "_verified_epoch", lambda *_: pytest.fail("Bad return read epoch"))
        with pytest.raises(factory_runtime.FactoryRuntimeError, match="^factory_runtime_refused$"):
            factory_runtime.prepare_factory(config, admission_check=harness.check,
                                            initialization_peer_guard=harness.peer_guard)
    assert not harness.events and not harness.prepared and not harness.configured.adapter.inspect_calls
    assert snapshot(harness.configured.root) == before
    assert_closed(harness)


async def test_direct_callback_survives_fresh_context_and_threads_without_grant_cache(harness):
    ambient = ContextVar("synthetic_parent_grant", default="fresh")
    ambient.set("parent-only")
    seen = []
    check = harness.check

    def direct():
        seen.append((ambient.get(), threading.get_ident()))
        check()

    harness.check = direct
    await terminal(run(harness))
    assert seen and {value for value, _thread in seen} == {"fresh"}
    assert len({thread for _value, thread in seen}) >= 2
    assert harness.prepared and harness.checks
    assert_closed(harness)


async def test_invalid_graph_before_start_creates_no_ipc_or_state(harness):
    harness.validity[0] = False
    before = snapshot(harness.configured.root)
    await terminal(run(harness), "factory_runtime_refused")
    assert harness.checks and harness.stop.is_set()
    assert not harness.events and not harness.prepared and not harness.configured.adapter.inspect_calls
    assert snapshot(harness.configured.root) == before
    assert_closed(harness)


async def test_real_inspect_then_graph_invalidation_refuses_before_identity_or_begin(
    harness, serve, root_peer, monkeypatch,
):
    transport = connect(harness, serve, monkeypatch, invalidate="initialization.inspect")
    await terminal(run(harness), "factory_runtime_refused")
    assert [request["op"] for request in transport.server.requests] == ["initialization.inspect"]
    assert transport.state() == {"status": "authorized"}
    assert len(root_peer) == len(transport.proofs) == 1 and transport.proofs[0]["closed"]
    assert not list((harness.data / "provisioning").glob("*.json"))
    assert not (harness.data / "provisioning" / "ownership.sqlite3").exists()
    assert not harness.events and harness.stop.is_set()
    assert_closed(harness)


async def test_real_begin_then_graph_invalidation_is_uncertain_without_new_ledger_or_retry(
    harness, serve, root_peer, monkeypatch,
):
    transport = connect(harness, serve, monkeypatch, invalidate="initialization.begin")
    await terminal(run(harness), "factory_runtime_uncertain")
    assert [request["op"] for request in transport.server.requests] == ["initialization.inspect", "initialization.begin"]
    consumed = transport.state()
    assert consumed["status"] == "consumed"
    prepared = json.loads((harness.data / "provisioning" / "bootstrap-identity.json").read_text())
    assert prepared["initialization_intent"] == consumed["intent"]
    assert not (harness.data / "provisioning" / "ownership.sqlite3").exists()
    assert len(root_peer) == len(transport.proofs) == 2 and all(proof["closed"] for proof in transport.proofs)
    assert not harness.events and not harness.prepared and harness.stop.is_set()
    assert_closed(harness)


@pytest.mark.parametrize("stage", ["create", "reopen", "verify"])
async def test_graph_loss_during_identity_preparation_refuses_before_consuming_begin(
    harness, serve, root_peer, monkeypatch, stage,
):
    directory = harness.data / "provisioning"
    preserved = []
    if stage == "reopen":
        PreparedFactoryIdentity.create(directory, initialization_intent=str(uuid4()))

    if stage in {"create", "reopen"}:
        original = getattr(PreparedFactoryIdentity, stage)

        def prepare_identity(*args, **kwargs):
            result = original(*args, **kwargs)
            preserved.append((directory / PREPARED_IDENTITY_FILENAME).read_bytes())
            harness.validity[0] = False
            return result

        monkeypatch.setattr(PreparedFactoryIdentity, stage, prepare_identity)
    else:
        original = PreparedFactoryIdentity.verify_current_or_unpublished

        def verify_identity(self):
            result = original(self)
            preserved.append((directory / PREPARED_IDENTITY_FILENAME).read_bytes())
            harness.validity[0] = False
            return result

        monkeypatch.setattr(PreparedFactoryIdentity, "verify_current_or_unpublished", verify_identity)

    transport = connect(harness, serve, monkeypatch)
    await terminal(run(harness), "factory_runtime_refused")
    assert [request["op"] for request in transport.server.requests] == ["initialization.inspect"]
    assert transport.state() == {"status": "authorized"}
    assert preserved and (directory / PREPARED_IDENTITY_FILENAME).read_bytes() == preserved[-1]
    assert not (directory / "ownership.sqlite3").exists()
    assert len(root_peer) == len(transport.proofs) == 1 and transport.proofs[0]["closed"]
    assert not harness.events and not harness.prepared and harness.stop.is_set()
    assert_closed(harness)


async def test_invalid_graph_after_preparation_closes_real_store_without_display(harness, monkeypatch):
    prepare = phase.prepare_factory

    def finish(config, **hooks):
        result = prepare(config, **hooks)
        harness.validity[0] = False
        return result

    monkeypatch.setattr(phase, "prepare_factory", finish)
    await terminal(run(harness), "factory_runtime_refused")
    assert len(harness.prepared) == 1 and not harness.events and harness.stop.is_set()
    assert_closed(harness)


@pytest.mark.parametrize("cancel", [False, True])
async def test_invalid_graph_after_consumed_begin_drains_real_socket_under_parent_guard_exit(
    harness, serve, root_peer, monkeypatch, cancel,
):
    entered, release = threading.Event(), threading.Event()
    transport = connect(harness, serve, monkeypatch, invalidate="initialization.begin",
                        block_begin=(entered, release))
    with factory_writer.main_writer_guard():
        task = asyncio.create_task(run(harness))
        assert await asyncio.to_thread(entered.wait, 5)
    assert len(harness.admission.acquisitions) == 2 and len(harness.admission.releases) == 1
    try:
        for _ in range(5):
            if cancel:
                task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and not harness.admission.child_available()
        assert len(transport.proofs) == 2 and not transport.proofs[-1]["closed"]
        assert not harness.events
    finally:
        release.set()
    if cancel:
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await terminal(task, "factory_runtime_uncertain")
    assert all(proof["closed"] for proof in transport.proofs) and len(root_peer) == 2
    assert transport.state()["status"] == "consumed" and not harness.events
    assert not (harness.data / "provisioning" / "ownership.sqlite3").exists()
    assert_closed(harness)


async def test_store_credential_verifier_retains_os_callback_inside_sqlite_claim(
    harness, monkeypatch,
):
    candidate = production_runtime(harness, monkeypatch)
    task, runtime = await candidate.start()
    original = runtime.owners.claim
    verified = []

    def before_store(*args, **kwargs):
        # Runtime's preflight already passed. The real store must invoke its
        # own retained production credential callback inside the transaction.
        harness.validity[0] = False
        verified.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime.owners, "claim", before_store)
    reply = await runtime.command({
        "v": 1, "id": str(uuid4()), "op": "bootstrap.claim", "owner_id": str(uuid4()),
        "owner_token": "b" * 64, "claim_token": candidate.payloads[-1]["t"],
    })
    assert verified and reply["ok"] is False and reply["error"] in {"recovery_required", "unavailable"}
    await terminal(task, "factory_runtime_refused")
    import sqlite3

    with sqlite3.connect(harness.data / "provisioning" / "ownership.sqlite3") as connection:
        assert connection.execute("SELECT owner_id FROM owners").fetchall() == []
        assert connection.execute("SELECT state FROM factory_initialization").fetchall() == [("factory",)]
    assert runtime.display.closing and candidate.radios[-1].stopped and not runtime.operations.tasks
    assert_closed(harness)
