"""SoftAP handoff qualification: in-memory NM, no D-Bus, socket or radio."""
from __future__ import annotations

import json
import stat
from uuid import uuid4

import pytest

from tests.test_network_helper import FakeNM, PowerLoss, begin_request, error, helper, operation


@pytest.fixture(autouse=True)
def inky_env():
    # This standalone system helper must not import or initialize the app DB.
    yield


@pytest.fixture
def state(tmp_path):
    journal = helper.Journal(tmp_path / "network")
    nm, clock = FakeNM(), [1000.0]
    nm.journal = journal
    return helper.Provisioner(nm, journal, monotonic=lambda: clock[0]), nm, clock


def prepare_request():
    return begin_request() | {"op": "prepare"}


def assert_no_durable_secrets(engine, request):
    for path in engine.journal.directory.iterdir():
        raw = path.read_bytes()
        assert request["password"].encode() not in raw
        assert request["ssid"].encode() not in raw
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def assert_no_retained_secrets(engine, request):
    # Include nested RAM containers without prescribing their implementation.
    assert request["password"] not in repr(vars(engine))
    assert request["ssid"] not in repr(vars(engine))


def test_prepare_ack_is_durable_before_handoff_and_has_no_nm_effect(state):
    engine, nm, clock = state
    request = prepare_request()
    result = engine.handle(request)
    assert result == {"id": request["id"], "state": "connecting", "addresses": [], "remaining_seconds": 30, "phase": "prepared"}
    row = engine.journal.get(request["id"])
    assert row["phase"] == "staged" and row["state"] == "connecting"
    assert row["checkpoint"] is None and row["previous_uuid"] is None
    assert helper.Journal(engine.journal.directory).get(request["id"]) == row
    assert nm.calls == [] and not nm.checkpoints and not nm.profiles
    assert_no_durable_secrets(engine, request)
    clock[0] += 7
    status = engine.handle(operation(request, "status"))
    assert status["state"] == "connecting" and status["remaining_seconds"] == 23 and status["phase"] == "prepared"
    assert engine.journal.get(request["id"])["phase"] == "staged"
    assert nm.calls == []


@pytest.mark.parametrize("mutation", [
    {"unknown": True}, {"id": "bad"}, {"owner_id": "bad"}, {"security": "open"},
    {"ssid": ""}, {"ssid": "é" * 17}, {"ssid": "bad\x00ssid"},
    {"ssid": "\ud800"}, {"password": "tiny"}, {"password": "g" * 64},
    {"password": "bad\x00password"}, {"password": "\ud800"},
])
def test_prepare_uses_begin_credential_validation_before_any_effect(state, mutation):
    engine, nm, _ = state
    request = prepare_request() | mutation
    error("invalid_request", lambda: engine.handle(request))
    assert engine.journal.records == [] and nm.calls == []


@pytest.mark.parametrize("op", ["activate", "settled"])
def test_private_handoff_operations_have_exact_bounded_schema(op):
    request = operation(begin_request(), op)
    assert helper.parse_request(json.dumps(request).encode() + b"\n") == request
    for mutation in ({"unknown": True}, {"id": "bad"}, {"owner_id": "bad"}, {"password": "unused"}):
        error("invalid_request", lambda mutation=mutation: helper.validate_request(request | mutation))


def test_prepare_and_begin_share_one_canonical_hmac_intent(state):
    engine, nm, clock = state
    request = prepare_request()
    first = engine.handle(request)
    row = engine.journal.get(request["id"])
    assert row["intent"] == engine.journal.intention(request | {"op": "begin"})
    clock[0] += 5
    for op in ("prepare", "begin"):
        replay = engine.handle(request | {"op": op})
        assert replay["state"] == first["state"] and replay["remaining_seconds"] == 25
    assert engine.journal.get(request["id"]) == row
    assert nm.calls == []
    error("conflict", lambda: engine.handle(request | {"password": "Different-password"}))
    error("busy", lambda: engine.handle(prepare_request()))
    assert nm.calls == []


@pytest.mark.parametrize("op", ["prepare", "begin", "activate", "status", "cancel", "confirm", "settled"])
def test_handoff_owner_is_required_without_advancing_another_owners_transaction(state, op):
    engine, nm, _ = state
    request = prepare_request()
    engine.handle(request)
    wrong = (request if op in {"prepare", "begin"} else operation(request, op)) | {"op": op, "owner_id": str(uuid4())}
    error("not_found", lambda: engine.handle(wrong))
    assert engine.journal.get(request["id"])["phase"] == "staged"
    assert nm.calls == []


def test_activate_observes_post_ap_nm_identity_then_creates_one_checkpoint(state, monkeypatch):
    engine, nm, clock = state
    request = prepare_request()
    engine.handle(request)
    # The AP disappears before activation. It must never become rollback target.
    previous = str(uuid4())
    nm.previous = previous
    nm.current.update(uuid=previous, active_path="/active/post-ap")
    nm.service_instance = "new-boot:nm-post-ap"
    clock[0] += 20
    activate = nm.activate_new

    def checked_activate(row, ssid, password):
        assert row["previous_uuid"] == previous
        assert row["instance"] == "new-boot:nm-post-ap"
        assert ssid == request["ssid"] and password == request["password"]
        durable = helper.Journal(engine.journal.directory).get(request["id"])
        assert durable["phase"] == "activating" and durable["checkpoint"] is not None
        activate(row, ssid, password)

    monkeypatch.setattr(nm, "activate_new", checked_activate)
    result = engine.handle(operation(request, "activate"))
    assert result["state"] == "connecting" and result["remaining_seconds"] == 180
    assert nm.calls.index("snapshot") < nm.calls.index("checkpoint_create") < nm.calls.index("activate_new")
    assert nm.calls.count("checkpoint_create") == nm.calls.count("activate_new") == 1
    for op in ("activate", "prepare", "begin"):
        replay = request | {"op": op} if op in {"prepare", "begin"} else operation(request, op)
        assert engine.handle(replay)["state"] == "connecting"
    assert nm.calls.count("checkpoint_create") == nm.calls.count("activate_new") == 1
    assert_no_durable_secrets(engine, request)


@pytest.mark.parametrize("finish", ["expiry", "cancel", "cancel_pending", "cancel_owner", "restart"])
def test_unactivated_prepare_finishes_without_touching_network_and_erases_secrets(state, finish):
    engine, nm, clock = state
    request = prepare_request()
    engine.handle(request)
    if finish == "expiry":
        clock[0] += 30
        engine.tick()
    elif finish == "restart":
        nm.journal = helper.Journal(engine.journal.directory)
        engine = helper.Provisioner(nm, nm.journal, monotonic=lambda: clock[0])
    elif finish == "cancel_pending":
        assert engine.handle({"op": finish}) == {"cancelled": True}
    elif finish == "cancel_owner":
        assert engine.handle({"op": finish, "owner_id": request["owner_id"]}) == {"cancelled": True}
    else:
        assert engine.handle(operation(request, "cancel"))["state"] == "rolled_back"
    result = engine.handle(operation(request, "status"))
    assert result["state"] == "rolled_back" and result["remaining_seconds"] == 0
    assert engine.journal.active() is None
    assert nm.calls == [] and nm.current["uuid"] == nm.previous
    assert_no_retained_secrets(engine, request)
    assert_no_durable_secrets(engine, request)
    assert engine.handle(operation(request, "activate"))["state"] == "rolled_back"
    assert nm.calls == []


def test_expired_prepare_cannot_be_reactivated_or_extended_by_replay(state):
    engine, nm, clock = state
    request = prepare_request()
    engine.handle(request)
    clock[0] += 30
    for command in (operation(request, "activate"), request, request | {"op": "begin"}):
        assert engine.handle(command)["state"] == "rolled_back"
    assert nm.calls == []
    assert_no_retained_secrets(engine, request)


def test_prepare_journal_failure_returns_no_ack_and_no_network_effect(state, monkeypatch):
    engine, nm, _ = state
    request = prepare_request()

    def unwritable(_row):
        raise OSError("synthetic disk error")

    monkeypatch.setattr(engine.journal, "put", unwritable)
    error("not_ready", lambda: engine.handle(request))
    assert nm.calls == []
    assert_no_retained_secrets(engine, request)


@pytest.mark.parametrize("phase", ["prepared", "waiting"])
def test_uncertain_activation_journal_write_erases_secrets_and_stops_nm_effects(state, monkeypatch, phase):
    engine, nm, _ = state
    request = prepare_request()
    engine.handle(request)
    put = engine.journal.put

    def uncertain_after_write(row):
        put(row)
        if row["phase"] == phase:
            raise OSError("synthetic uncertain durable write")

    monkeypatch.setattr(engine.journal, "put", uncertain_after_write)
    error("network_failed", lambda: engine.handle(operation(request, "activate")))
    assert not engine.ready
    assert helper.Journal(engine.journal.directory).get(request["id"])["phase"] == phase
    expected = ["snapshot"] if phase == "prepared" else ["snapshot", "checkpoint_create", "activate_new"]
    assert nm.calls == expected
    assert engine._prepared_request is None and engine._password is None
    assert_no_retained_secrets(engine, request)
    assert_no_durable_secrets(engine, request)
    engine.tick()
    error("not_ready", lambda: engine.handle(operation(request, "activate")))
    assert nm.calls == expected  # No rollback or duplicate mutation after uncertainty.


def test_power_loss_after_prepare_write_recovers_without_nm_cleanup(state, monkeypatch):
    engine, nm, clock = state
    request = prepare_request()
    put = engine.journal.put

    def crash(row):
        put(row)
        raise PowerLoss()

    monkeypatch.setattr(engine.journal, "put", crash)
    with pytest.raises(PowerLoss):
        engine.handle(request)
    nm.journal = helper.Journal(engine.journal.directory)
    recovered = helper.Provisioner(nm, nm.journal, monotonic=lambda: clock[0])
    assert recovered.handle(operation(request, "status"))["state"] == "rolled_back"
    assert nm.calls == []
    assert_no_retained_secrets(recovered, request)


def test_legacy_prepared_crash_still_runs_targeted_nm_cleanup(state, monkeypatch):
    engine, nm, clock = state
    request = begin_request()
    create = nm.checkpoint_create

    def lost_after_checkpoint_effect():
        create()
        raise PowerLoss()

    monkeypatch.setattr(nm, "checkpoint_create", lost_after_checkpoint_effect)
    with pytest.raises(PowerLoss):
        engine.handle(request)
    durable = helper.Journal(engine.journal.directory).get(request["id"])
    assert durable["phase"] == "prepared" and durable["checkpoint"] is None
    assert nm.checkpoints
    nm.calls.clear()
    nm.journal = helper.Journal(engine.journal.directory)
    recovered = helper.Provisioner(nm, nm.journal, monotonic=lambda: clock[0])
    assert recovered.handle(operation(request, "status"))["state"] == "rolled_back"
    # Legacy prepared is write-ahead for an NM mutation, unlike new staged.
    assert "delete_profile" in nm.calls and "snapshot" in nm.calls


def test_legacy_begin_still_activates_immediately_with_180_second_checkpoint(state):
    engine, nm, _ = state
    request = begin_request()
    result = engine.handle(request)
    assert result == {"id": request["id"], "state": "connecting", "addresses": [], "remaining_seconds": 180}
    assert engine.journal.get(request["id"])["phase"] == "waiting"
    assert nm.calls.count("checkpoint_create") == nm.calls.count("activate_new") == 1


def test_prepare_replay_cannot_stage_or_duplicate_a_legacy_begin(state):
    engine, nm, _ = state
    request = begin_request()
    expected = engine.handle(request)
    assert engine.handle(request | {"op": "prepare"}) == expected
    assert engine.journal.get(request["id"])["phase"] == "waiting"
    assert nm.calls.count("checkpoint_create") == nm.calls.count("activate_new") == 1


class ObservedNM(FakeNM):
    """Exercise the real settled observer over synthetic NM properties."""

    factory_settled = helper.NetworkManagerAdapter.factory_settled

    def __init__(self):
        super().__init__()
        self._factory_scan = None

    def properties(self, _path, interface):
        if interface == helper.NM:
            return {"Checkpoints": list(self.checkpoints)}
        if interface == helper.NM + ".Device":
            disconnected = self.current["uuid"] is None and self.current["active_path"] == "/"
            return {"Managed": True, "State": 30 if disconnected else (100 if self.current["activated"] else 40),
                    "ActiveConnection": self.current["active_path"]}
        if interface == helper.NM + ".Connection.Active":
            return {"State": 2 if self.current["activated"] else 1, "Uuid": self.current["uuid"]}
        raise AssertionError("unexpected NM observation")

    def _profile(self, profile_uuid, _transaction_id=None):
        return self.profiles.get(profile_uuid)

    def checkpoint_rollback(self, path):
        self.called("checkpoint_rollback", "rolling_back")
        self.checkpoints.remove(path)
        self.current.update(uuid=None, active_path="/", activated=False, addresses=[])

    def restore_previous(self, previous_uuid):
        self.called("restore_previous", "rolling_back")
        assert previous_uuid == self.previous
        self.current.update(uuid=previous_uuid, active_path="/active/restored", activated=False, addresses=[])
        return "/active/restored"


@pytest.fixture
def observed_state(tmp_path):
    nm, clock = ObservedNM(), [1000.0]
    nm.journal = helper.Journal(tmp_path / "observed-network")
    return helper.Provisioner(nm, nm.journal, monotonic=lambda: clock[0]), nm, clock


def test_settled_waits_for_observed_async_rollback_not_terminal_journal(observed_state):
    engine, nm, _ = observed_state
    request = prepare_request()
    engine.handle(request)
    assert engine.handle(operation(request, "settled")) == {"id": request["id"], "settled": False}
    engine.handle(operation(request, "activate"))
    assert engine.handle(operation(request, "cancel"))["state"] == "rolled_back"
    assert engine.journal.get(request["id"])["phase"] == "rolled_back"
    before = list(nm.calls)
    assert engine.handle(operation(request, "settled")) == {"id": request["id"], "settled": False}
    assert nm.calls == before
    nm.finish_activation()
    assert engine.handle(operation(request, "settled")) == {"id": request["id"], "settled": True}
    assert nm.calls == before


def test_settled_terminal_transaction_cannot_authorize_ap_while_another_is_staged(observed_state):
    engine, nm, _ = observed_state
    first, second = prepare_request(), prepare_request()
    engine.handle(first)
    engine.handle(operation(first, "activate"))
    engine.handle(operation(first, "cancel"))
    nm.finish_activation()
    assert engine.handle(operation(first, "settled"))["settled"] is True
    engine.handle(second)
    assert engine.journal.active()["id"] == second["id"]
    assert engine.journal.active()["phase"] == "staged"
    calls = list(nm.calls)
    assert engine.handle(operation(first, "settled")) == {"id": first["id"], "settled": False}
    assert engine.journal.active()["id"] == second["id"] and nm.calls == calls


def test_settled_cannot_borrow_cleanup_proof_from_another_transaction(observed_state):
    engine, nm, _ = observed_state
    first, second = prepare_request(), prepare_request()
    foreign_cleanup = None
    for request in (first, second):
        engine.handle(request)
        engine.handle(operation(request, "activate"))
        engine.handle(operation(request, "cancel"))
        foreign_cleanup = engine._factory_cleanup.copy()
        nm.finish_activation()
        assert engine.handle(operation(request, "settled"))["settled"] is True
    assert engine.journal.active() is None
    # Successful observation normally releases this cache. Inject a stale
    # foreign cache explicitly to exercise the defensive transaction-ID guard.
    engine._factory_cleanup = foreign_cleanup
    assert engine._factory_cleanup["id"] == second["id"]
    calls = list(nm.calls)
    assert engine.handle(operation(first, "settled")) == {"id": first["id"], "settled": False}
    assert nm.calls == calls


def test_second_handoff_survives_ap_return_after_first_rollback_is_observed(observed_state):
    engine, nm, _ = observed_state
    first, second = prepare_request(), prepare_request()
    engine.handle(first)
    engine.handle(operation(first, "activate"))
    engine.handle(operation(first, "cancel"))
    nm.finish_activation()
    assert engine.handle(operation(first, "settled"))["settled"] is True
    assert engine._factory_cleanup is None

    # A different attested writer returns the AP only after settled=true.
    nm.current.update(uuid=str(uuid4()), active_path="/active/returned-ap",
                      activated=True, addresses=["192.168.4.1"])
    calls = list(nm.calls)
    assert engine.handle(second)["phase"] == "prepared"
    assert nm.calls == calls  # Preparing B must not try to restore A's station.
    # OS stops the AP before activating the next station intent.
    nm.current.update(uuid=None, active_path="/", activated=False, addresses=[])
    engine.handle(operation(second, "activate"))
    assert engine.journal.get(second["id"])["previous_uuid"] is None
    restore_count = nm.calls.count("restore_previous")
    engine.handle(operation(second, "cancel"))
    assert engine._factory_cleanup["id"] == second["id"]
    assert nm.calls.count("restore_previous") == restore_count
    assert engine.handle(operation(second, "settled")) == {"id": second["id"], "settled": True}
    assert engine._factory_cleanup is None


def test_next_prepare_is_busy_until_previous_restore_is_actually_observed(observed_state):
    engine, nm, _ = observed_state
    first, second = prepare_request(), prepare_request()
    engine.handle(first)
    engine.handle(operation(first, "activate"))
    engine.handle(operation(first, "cancel"))
    assert not nm.current["activated"] and engine.journal.active() is None
    before = engine.journal.path.read_bytes()
    calls = list(nm.calls)
    error("busy", lambda: engine.handle(second))
    assert engine.journal.path.read_bytes() == before
    assert engine.journal.get(second["id"]) is None and nm.calls == calls
    assert engine._factory_cleanup["id"] == first["id"]
    assert engine._prepared_request is None and engine._password is None
    nm.finish_activation()
    assert engine.handle(second)["phase"] == "prepared"
    assert engine._factory_cleanup is None
    assert engine.journal.active()["id"] == second["id"]


def test_settled_refuses_legacy_checkpoint_orphan_after_crash_before_journal(observed_state, monkeypatch):
    engine, nm, clock = observed_state
    request = begin_request()
    create = nm.checkpoint_create

    def crash_after_nm_checkpoint_creation():
        create()
        raise PowerLoss()

    monkeypatch.setattr(nm, "checkpoint_create", crash_after_nm_checkpoint_creation)
    with pytest.raises(PowerLoss):
        engine.handle(request)
    nm.journal = helper.Journal(engine.journal.directory)
    assert nm.journal.active()["phase"] == "prepared"
    assert nm.journal.active()["checkpoint"] is None and nm.checkpoints
    recovered = helper.Provisioner(nm, nm.journal, monotonic=lambda: clock[0])
    assert recovered.journal.get(request["id"])["phase"] == "rolled_back"
    assert nm.current["uuid"] == nm.previous and nm.current["activated"]
    # The old observer accepts the restored station because its row never
    # learned the checkpoint path. SoftAP must also observe NM's whole list.
    assert nm.factory_settled(recovered._factory_cleanup, None) is True
    assert recovered.handle(operation(request, "settled")) == {"id": request["id"], "settled": False}
    nm.checkpoints.clear()  # Simulate NM's independent bounded expiry.
    assert recovered.handle(operation(request, "settled")) == {"id": request["id"], "settled": True}


@pytest.mark.parametrize("remaining", ["wrong_uuid", "wrong_path", "created_profile", "checkpoint"])
def test_settled_rejects_incomplete_or_unrelated_observations(observed_state, remaining):
    engine, nm, _ = observed_state
    request = prepare_request()
    engine.handle(request)
    engine.handle(operation(request, "activate"))
    engine.handle(operation(request, "cancel"))
    nm.finish_activation()
    cleanup = engine._factory_cleanup
    if remaining == "wrong_uuid":
        nm.current["uuid"] = str(uuid4())
    elif remaining == "wrong_path":
        nm.current["active_path"] = "/active/stale-previous"
    elif remaining == "created_profile":
        nm.profiles[cleanup["profile_uuid"]] = {"saved": False, "bound": True}
    else:
        nm.checkpoints.add(cleanup["checkpoint"])
    assert engine.handle(operation(request, "settled")) == {"id": request["id"], "settled": False}


def test_settled_old_adapter_without_observer_cannot_invent_authority(state):
    engine, nm, _ = state
    request = prepare_request()
    engine.handle(request)
    engine.handle(operation(request, "activate"))
    engine.handle(operation(request, "cancel"))
    assert not hasattr(nm, "factory_settled")
    assert engine.handle(operation(request, "settled")) == {"id": request["id"], "settled": False}


def test_settled_observer_error_is_bounded_and_never_says_ready(observed_state, monkeypatch):
    engine, nm, _ = observed_state
    request = prepare_request()
    engine.handle(request)
    engine.handle(operation(request, "activate"))
    engine.handle(operation(request, "cancel"))

    def unavailable(*_args):
        raise RuntimeError("synthetic private NetworkManager details")

    monkeypatch.setattr(nm, "factory_settled", unavailable)
    assert engine.handle(operation(request, "settled")) == {"id": request["id"], "settled": False}


@pytest.mark.parametrize("op", ["activate", "settled"])
def test_handoff_missing_transaction_fails_closed(state, op):
    engine, nm, _ = state
    error("not_found", lambda: engine.handle(operation(begin_request(), op)))
    assert nm.calls == []
