"""Durable owner ledger and real setup transition; inert OS/radio edges only."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from inky_web.provisioning.factory_continuation import SetupSession
from inky_web.provisioning.network import NetworkUnavailable
from tests.test_factory_system_setup import ORIGIN, apply, command
from tests.test_factory_system_setup import adopted as adopted


class AP:
    def __init__(self, calls):
        self.calls = calls
    def encode_qr(self, frame_id, pin, token):
        return "inert"
    async def start(self, workflow, *, channel=None):
        assert channel is not None and not channel.closed
        self.calls.append("ap.start")
    async def stop(self, *, channel=None):
        if channel is not None:
            assert not channel.closed
        self.calls.append("ap.stop")


class Network:
    def __init__(self, *, state="committed", settled=True):
        self.calls = []
        self.state, self.settled = state, settled
        self.activated = asyncio.Event()
    async def call(self, operation, **arguments):
        self.calls.append(operation)
        if operation == "prepare":
            self.activated.clear()
            return {"id": arguments["id"], "state": "connecting", "phase": "prepared",
                    "addresses": [], "remaining_seconds": 30}
        if operation == "activate":
            self.activated.set()
        if operation == "confirm":
            self.state = "committed"
        if operation == "settled":
            if getattr(self, "on_settled", None) is not None:
                self.on_settled()
            settled = self.settled.pop(0) if isinstance(self.settled, list) else self.settled
            return {"id": arguments["id"], "settled": settled}
        if operation == "cancel":
            return {"id": arguments["id"], "state": "rolled_back"}
        if not self.activated.is_set():
            return {"id": arguments["id"], "state": "connecting", "phase": "prepared",
                    "addresses": [], "remaining_seconds": 30}
        return {"id": arguments["id"], "state": self.state, "addresses": [], "remaining_seconds": 180}
    def cancel_pending_sync(self):
        self.calls.append("cancel_pending")


async def prepared(v, *, state="committed", settled=True):
    network = Network(state=state, settled=settled)
    ap = AP(network.calls)
    v.runtime.network = network
    await apply(v)
    v.runtime.softap = v.runtime.provisioning.wifi_handoff = ap
    v.native.live.update(https_origin=ORIGIN, origin_status="avahi_current")
    session = SetupSession()
    v.runtime._sessions.add(session)
    base = {"v": 1, "owner_id": v.owner, "owner_token": "b" * 64}
    tx = str(uuid4())
    message = {**base, "id": tx, "op": "wifi.prepare", "ssid": "synthetic-home",
               "security": "wpa2", "password": "synthetic-password"}
    reply = await v.runtime.session_command(session, message, v.runtime.provisioning.command)
    assert reply["ok"], reply
    assert reply["result"]["phase"] == "prepared"
    assert reply["result"]["expected_https_origin"] == ORIGIN
    assert v.runtime.identity.frame_id.replace("-", "") not in ORIGIN
    assert network.calls == ["prepare"]
    return session, network, {**base, "id": str(uuid4()), "op": "wifi.activate", "transaction_id": tx}


async def activation(v, session, message):
    reply = await v.runtime.session_command(session, message, v.runtime.provisioning.command)
    assert reply["ok"], reply
    assert reply["result"]["phase"] == "activation_requested"
    return reply


async def test_prepare_and_explicit_activate_are_separate_and_drain_owned(adopted):
    v = adopted
    session, network, message = await prepared(v)
    await activation(v, session, message)
    assert network.calls == ["prepare", "status"]
    assert len(v.runtime.operations.tasks) == 1
    session.after_response()
    await v.runtime.operations.drain()
    assert network.calls == ["prepare", "status", "ap.stop", "activate", "status"]
    assert not v.runtime._handoff_channels


async def test_lost_activate_reply_before_drain_keeps_ap(adopted):
    v = adopted
    session, network, message = await prepared(v)
    await activation(v, session, message)
    session.close()
    await v.runtime.operations.drain()
    assert network.calls == ["prepare", "status"]


@pytest.mark.parametrize("settled", [True, False])
async def test_rollback_must_settle_before_same_owner_ap_recovery(adopted, monkeypatch, settled):
    if not settled:
        from inky_web.provisioning import factory_continuation
        monkeypatch.setattr(factory_continuation, "_SOFTAP_SETTLE_SECONDS", 0.03)
        monkeypatch.setattr(factory_continuation, "_SOFTAP_SETTLE_RETRY_SECONDS", 0.01)
    v = adopted
    session, network, message = await prepared(v, state="rolled_back", settled=settled)
    await activation(v, session, message)
    session.after_response()
    await v.runtime.operations.drain()
    assert network.calls[:5] == ["prepare", "status", "ap.stop", "activate", "status"]
    assert ("ap.start" in network.calls) is settled
    if settled:
        assert network.calls[-2:] == ["settled", "ap.start"]
    assert not v.runtime._handoff_channels


async def test_epoch_owner_rechecked_before_effect_after_reply(adopted):
    v = adopted
    session, network, message = await prepared(v)
    await activation(v, session, message)
    v.result.ownership.revoke(v.owner)
    session.after_response()
    await v.runtime.operations.drain()
    assert network.calls == ["prepare", "status"]


async def test_softap_confirm_precedes_origin_commit_but_photo_stays_closed(adopted):
    v = adopted
    session, network, message = await prepared(v, state="awaiting_confirmation")
    assert v.runtime.https_origin() is None
    result = await v.runtime.provisioning.confirm(v.owner, "b" * 64, message["transaction_id"])
    assert result["state"] == "connecting"  # inert helper was never activated
    assert network.calls[-1] == "confirm"
    assert v.runtime.https_origin() is None
    with pytest.raises(NetworkUnavailable):
        await v.runtime.authorize_photo(v.owner, "b" * 64, v.claim_id, str(uuid4()))


async def test_softap_never_accepts_legacy_begin(adopted):
    v = adopted
    session, network, _ = await prepared(v)
    message = {"v": 1, "id": str(uuid4()), "op": "wifi.begin", "owner_id": v.owner,
               "owner_token": "b" * 64, "ssid": "synthetic", "security": "open", "password": None}
    result = await v.runtime.provisioning.command(message)
    assert result["error"] == "invalid_request"
    assert network.calls == ["prepare"]


async def test_two_failed_wifi_attempts_return_to_same_owner_ap(adopted):
    v = adopted
    session, network, message = await prepared(v, state="rolled_back")
    for attempt in range(2):
        if attempt:
            transaction = str(uuid4())
            response = await v.runtime.provisioning.command({"v": 1, "id": transaction,
                "op": "wifi.prepare", "owner_id": v.owner, "owner_token": "b" * 64,
                "ssid": "synthetic-second-home", "security": "open", "password": None})
            assert response["ok"]
            message = {**message, "id": str(uuid4()), "transaction_id": transaction}
        await activation(v, session, message)
        session.after_response()
        await v.runtime.operations.drain()
    assert network.calls.count("activate") == 2
    assert network.calls.count("settled") == network.calls.count("ap.start") == 2
    assert len(v.runtime._handoffs) == 1  # bounded: completed A removed before B


async def test_delayed_settled_observation_is_awaited_before_ap_restart(adopted):
    v = adopted
    session, network, message = await prepared(v, state="rolled_back", settled=[False, False, True])
    await activation(v, session, message)
    session.after_response()
    await v.runtime.operations.drain()
    assert network.calls[-4:] == ["settled", "settled", "settled", "ap.start"]


async def test_owner_revocation_while_waiting_settled_never_reopens_ap(adopted):
    v = adopted
    session, network, message = await prepared(v, state="rolled_back", settled=False)
    network.on_settled = lambda: v.result.ownership.revoke(v.owner)
    await activation(v, session, message)
    session.after_response()
    await v.runtime.operations.drain()
    assert network.calls.count("settled") == 1
    assert "ap.start" not in network.calls


async def test_status_recovery_returns_observed_origin_and_terminal_needs_none(adopted):
    v = adopted
    session, network, message = await prepared(v)
    status = {**message, "id": str(uuid4()), "op": "wifi.status"}
    reply = await v.runtime.provisioning.command(status)
    assert reply["result"]["expected_https_origin"] == ORIGIN
    network.activated.set()
    network.state = "failed"
    v.native.live.update(https_origin=None, origin_status="unavailable")
    reply = await v.runtime.provisioning.command(status)
    assert reply["ok"] and reply["result"]["state"] == "failed"
    assert "expected_https_origin" not in reply["result"]


@pytest.mark.parametrize("delivered", [True, False])
async def test_recovered_publication_transition_waits_for_continue_reply(adopted, monkeypatch, delivered):
    v = adopted
    start_normal = v.runtime._start_normal
    async def leave_bootstrap(_identity):
        pass  # model publication committed but apply reply lost before drain
    monkeypatch.setattr(v.runtime, "_start_normal", leave_bootstrap)
    args = await apply(v)
    started = asyncio.Event()
    async def observed_start(identity):
        started.set()
        await start_normal(identity)
    monkeypatch.setattr(v.runtime, "_start_normal", observed_start)
    v.runtime.softap = AP([])
    assert (await command(v, "negotiate", versions=[2]))["ok"]
    response = await command(v, "continue", op_id=args["op_id"])
    assert response["result"]["action"] == "publication_finalized"
    await asyncio.sleep(0)
    assert not started.is_set()
    if delivered:
        v.session.after_response()
    else:
        v.session.close()
    await v.runtime.operations.drain()
    assert started.is_set() is delivered
