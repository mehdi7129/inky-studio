"""Local coordinator only: fake OS receipt and credential verifier, real files.

No OS adapter, password creation, wall-clock setter, radio, QR display or runtime
is qualified here. Claim calls only exercise the existing local ownership store.
"""
from __future__ import annotations

import copy
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from inky_web.provisioning import first_boot
from inky_web.provisioning.bootstrap_identity import (
    PREPARED_IDENTITY_FILENAME,
    ClockResult,
    PreparedFactoryIdentity,
    certificate_sha256,
)
from inky_web.provisioning.factory import FactoryState
from inky_web.provisioning.first_boot import (
    FirstBootCoordinator,
    FirstBootRefused,
    FirstBootUncertain,
)
from inky_web.provisioning.identity import load_or_create_identity
from inky_web.provisioning.ownership import OwnershipError, OwnershipStore

EPOCH = "e" * 64


class FakeOS:
    def __init__(self):
        self.state = {"status": "authorized"}
        self.receipt = {"receipt_id": str(uuid4()), "digest": "a" * 64}
        self.inspect_calls = 0
        self.begin_calls = []
        self.on_begin = None
        self.inspect_override = None
        self._lock = threading.Lock()

    def inspect_initialization(self):
        with self._lock:
            self.inspect_calls += 1
            if self.inspect_override is not None:
                return self.inspect_override()
            return copy.deepcopy(self.state)

    def begin_initialization(self, intent):
        with self._lock:
            self.begin_calls.append(intent)
            if self.state["status"] == "authorized":
                self.state = {"status": "consumed", "intent": intent, "receipt": self.receipt.copy()}
                status = "newly_consumed"
            else:
                assert self.state["intent"] == intent
                status = "already_consumed"
            result = {**copy.deepcopy(self.state), "status": status}
            return self.on_begin(result) if self.on_begin else result


@pytest.fixture
def setup(tmp_path):
    directory = tmp_path / "private"
    adapter = FakeOS()
    epoch = [EPOCH]
    coordinator = FirstBootCoordinator(directory, adapter, lambda: epoch[0], clock=lambda: 0.0)
    return directory, adapter, epoch, coordinator


def snapshot(directory):
    return {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}


def adopt(result, epoch=EPOCH):
    owner, token, request = str(uuid4()), "b" * 64, str(uuid4())
    qr = result.ownership.open_factory_window()
    result.ownership.claim(qr, owner, token, request, epoch)
    return owner, token, request


def test_new_authority_persists_identity_before_consumption_and_marks_ready_without_time(setup):
    directory, adapter, _, coordinator = setup

    def inspect_prepared(reply):
        prepared = PreparedFactoryIdentity.reopen(directory, expected_intent=reply["intent"])
        assert prepared.binding
        assert not (directory / "ownership.sqlite3").exists()
        return reply

    adapter.on_begin = inspect_prepared
    result = coordinator.initialize()
    assert result.status.state == FactoryState.FACTORY
    assert result.status.identity == result.prepared_identity.binding
    assert adapter.inspect_calls == 1 and adapter.begin_calls == [result.prepared_identity.initialization_intent]
    assert not (directory / "identity.json").exists()
    with sqlite3.connect(directory / "ownership.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM window").fetchone() == (0,)
    assert (directory / ".first-boot.lock").stat().st_mode & 0o777 == 0o600


def test_prepared_authorized_restart_reuses_intent_and_key(setup, monkeypatch):
    directory, adapter, _, coordinator = setup
    prepared = PreparedFactoryIdentity.create(directory, initialization_intent=str(uuid4()))
    before = (directory / PREPARED_IDENTITY_FILENAME).read_bytes()
    monkeypatch.setattr(first_boot, "uuid4", lambda: pytest.fail("Intent must never be regenerated"))
    result = coordinator.initialize()
    assert result.prepared_identity.binding == prepared.binding
    assert adapter.begin_calls == [prepared.initialization_intent]
    assert (directory / PREPARED_IDENTITY_FILENAME).read_bytes() == before


def test_preparation_reply_loss_keeps_bundle_and_does_not_call_begin(setup, monkeypatch):
    directory, adapter, _, coordinator = setup
    original = PreparedFactoryIdentity.create

    def crash_after_prepare(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("synthetic sensitive material")

    with monkeypatch.context() as patch:
        patch.setattr(PreparedFactoryIdentity, "create", crash_after_prepare)
        with pytest.raises(FirstBootRefused) as error:
            coordinator.initialize()
    assert not error.value.begin_attempted and not adapter.begin_calls
    assert "sensitive" not in str(error.value)
    prepared = PreparedFactoryIdentity.reopen(directory)
    result = coordinator.initialize()
    assert result.prepared_identity.binding == prepared.binding
    assert adapter.begin_calls == [prepared.initialization_intent]


def test_consumption_reply_loss_never_recreates_missing_database(setup):
    directory, adapter, _, coordinator = setup

    def lose_reply(_):
        raise OSError("receipt secret")

    adapter.on_begin = lose_reply
    with pytest.raises(FirstBootUncertain) as error:
        coordinator.initialize()
    assert error.value.begin_attempted and "secret" not in str(error.value)
    prepared = PreparedFactoryIdentity.reopen(directory)
    adapter.on_begin = None
    with pytest.raises(FirstBootUncertain):
        coordinator.initialize()
    assert adapter.begin_calls == [prepared.initialization_intent] * 2
    assert not (directory / "ownership.sqlite3").exists()


def test_database_commit_reply_loss_resumes_pending_without_new_grant(setup, monkeypatch):
    directory, adapter, _, coordinator = setup
    original = OwnershipStore.create_factory

    def lose_reply(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("interrupted after DB commit")

    with monkeypatch.context() as patch:
        patch.setattr(OwnershipStore, "create_factory", lose_reply)
        with pytest.raises(FirstBootUncertain):
            coordinator.initialize()
    result = coordinator.initialize()
    assert result.status.state == FactoryState.FACTORY
    assert adapter.begin_calls == [result.prepared_identity.initialization_intent] * 2
    assert (directory / "ownership.sqlite3").exists()


@pytest.mark.parametrize("bad_epoch", [None, True, "", "A" * 64, "short"])
def test_invalid_persisted_credentials_leave_pending_and_can_resume(setup, bad_epoch):
    directory, _, epoch, coordinator = setup
    epoch[0] = bad_epoch
    with pytest.raises(FirstBootUncertain):
        coordinator.initialize()
    with sqlite3.connect(directory / "ownership.sqlite3") as connection:
        assert connection.execute("SELECT state FROM factory_initialization").fetchone() == ("pending",)
    epoch[0] = EPOCH
    assert coordinator.initialize().status.state == FactoryState.FACTORY


def test_credentials_exception_and_identity_change_before_ready_fail_closed(setup):
    directory, _, _, coordinator = setup

    def fail():
        raise OSError("verifier unavailable")

    coordinator.verify_credentials = fail
    with pytest.raises(FirstBootUncertain):
        coordinator.initialize()

    def delete_bundle():
        (directory / PREPARED_IDENTITY_FILENAME).unlink()
        return EPOCH

    coordinator.verify_credentials = delete_bundle
    with pytest.raises(FirstBootUncertain):
        coordinator.initialize()
    with sqlite3.connect(directory / "ownership.sqlite3") as connection:
        assert connection.execute("SELECT state FROM factory_initialization").fetchone() == ("pending",)


@pytest.mark.parametrize("reply", [None, {}, [], {"status": "missing"}, {"status": True},
    {"status": "authorized", "extra": 1}, {"status": "consumed"},
    {"status": "consumed", "intent": "not-canonical", "receipt": {}}])
def test_unknown_or_malformed_inspection_never_prepares_or_begins(setup, reply):
    directory, adapter, _, coordinator = setup
    adapter.inspect_override = lambda: reply
    with pytest.raises(FirstBootRefused):
        coordinator.initialize()
    assert not adapter.begin_calls
    assert not (directory / PREPARED_IDENTITY_FILENAME).exists()
    assert not (directory / "ownership.sqlite3").exists()


def test_inspection_failure_does_not_attempt_begin(setup):
    _, adapter, _, coordinator = setup

    def fail():
        raise OSError("OS refused or unavailable")

    adapter.inspect_override = fail
    with pytest.raises(FirstBootRefused):
        coordinator.initialize()
    assert adapter.inspect_calls == 1 and not adapter.begin_calls


@pytest.mark.parametrize("change", ["status", "intent", "uppercase_intent", "receipt_id", "digest", "extra", "null"])
def test_invalid_begin_reply_is_uncertain_and_cannot_create_database(setup, change):
    directory, adapter, _, coordinator = setup

    def invalid(reply):
        if change == "status":
            reply["status"] = "authorized"
        elif change == "intent":
            reply["intent"] = str(uuid4())
        elif change == "uppercase_intent":
            reply["intent"] = "AAAAAAAA-0000-4000-8000-000000000000"
        elif change == "receipt_id":
            reply["receipt"]["receipt_id"] = True
        elif change == "digest":
            reply["receipt"]["digest"] = "A" * 64
        elif change == "extra":
            reply["receipt"]["extra"] = "unexpected"
        else:
            return None
        return reply

    adapter.on_begin = invalid
    with pytest.raises(FirstBootUncertain):
        coordinator.initialize()
    assert len(adapter.begin_calls) == 1
    assert (directory / PREPARED_IDENTITY_FILENAME).exists()
    assert not (directory / "ownership.sqlite3").exists()


@pytest.mark.parametrize("change", ["receipt", "newly_consumed", "intent"])
def test_consumed_inspection_must_match_actual_begin_reply(setup, change):
    directory, adapter, _, coordinator = setup
    coordinator.initialize()
    before = snapshot(directory)

    def invalid(reply):
        if change == "receipt":
            reply["receipt"]["digest"] = "c" * 64
        elif change == "intent":
            reply["intent"] = str(uuid4())
        else:
            reply["status"] = "newly_consumed"
        return reply

    adapter.on_begin = invalid
    with pytest.raises(FirstBootUncertain):
        coordinator.initialize()
    assert snapshot(directory) == before


def test_consumed_os_intent_mismatch_refuses_before_begin(setup):
    directory, adapter, _, coordinator = setup
    coordinator.initialize()
    adapter.state["intent"] = str(uuid4())
    before = snapshot(directory)
    with pytest.raises(FirstBootRefused):
        coordinator.initialize()
    assert len(adapter.begin_calls) == 1 and snapshot(directory) == before


@pytest.mark.parametrize("damage", ["missing_bundle", "corrupt_bundle", "missing_db", "corrupt_db", "binding"])
def test_adopted_state_damage_never_reopens_factory_or_regenerates(setup, damage):
    directory, adapter, _, coordinator = setup
    result = coordinator.initialize()
    adopt(result)
    if damage == "missing_bundle":
        (directory / PREPARED_IDENTITY_FILENAME).unlink()
    elif damage == "corrupt_bundle":
        (directory / PREPARED_IDENTITY_FILENAME).write_bytes(b"corrupted")
    elif damage == "missing_db":
        (directory / "ownership.sqlite3").unlink()
    elif damage == "corrupt_db":
        (directory / "ownership.sqlite3").write_bytes(b"corrupted")
    else:
        with sqlite3.connect(directory / "ownership.sqlite3") as connection:
            connection.execute("UPDATE factory_initialization SET spki_sha256 = ?", ("c" * 64,))
    before = snapshot(directory)
    with pytest.raises((FirstBootRefused, FirstBootUncertain)):
        coordinator.initialize()
    assert snapshot(directory) == before
    assert set(adapter.begin_calls) == {result.prepared_identity.initialization_intent}


def test_adoption_revocation_last_owner_and_current_epoch_survive_restart(setup):
    _, adapter, epoch, coordinator = setup
    first = coordinator.initialize()
    owner, token, _ = adopt(first)
    resumed = coordinator.initialize()
    assert resumed.status.state == FactoryState.ADOPTED and resumed.status.first_owner_id == owner
    assert resumed.ownership.authenticate(owner, token).epoch == EPOCH
    resumed.ownership.prepare_password_rotation(EPOCH, "f" * 64, actor_owner_id=owner)
    epoch[0] = "f" * 64
    assert resumed.ownership.authenticate(owner, token).epoch == "f" * 64
    resumed.ownership.revoke(owner)
    last = coordinator.initialize()
    assert last.status.state == FactoryState.ADOPTED
    with pytest.raises(OwnershipError, match="unauthorized"):
        last.ownership.authenticate(owner, token)
    with pytest.raises(OwnershipError, match="factory_unavailable"):
        last.ownership.open_factory_window()
    assert len(adapter.begin_calls) == 3


def test_authorized_os_cannot_promote_existing_ownership_database(setup):
    directory, adapter, _, coordinator = setup
    OwnershipStore(directory, lambda: EPOCH)
    before = snapshot(directory)
    with pytest.raises(FirstBootRefused):
        coordinator.initialize()
    assert not adapter.begin_calls
    assert not (directory / PREPARED_IDENTITY_FILENAME).exists()
    assert {k: v for k, v in snapshot(directory).items() if k != ".first-boot.lock"} == before


@pytest.mark.parametrize("filename", [".first-boot.lock", ".bootstrap-identity.lock", ".identity.lock", ".ownership.lock", "ownership.sqlite3"])
@pytest.mark.parametrize("kind", ["fifo", "symlink", "directory"])
def test_unsafe_files_are_refused_before_begin_without_waiting_for_fifo(setup, filename, kind):
    directory, adapter, _, coordinator = setup
    directory.mkdir(mode=0o700)
    target = directory / filename
    if kind == "fifo":
        os.mkfifo(target, 0o600)
    elif kind == "symlink":
        target.symlink_to(directory / "missing")
    else:
        target.mkdir(mode=0o700)
    with pytest.raises(FirstBootRefused):
        coordinator.initialize()
    assert not adapter.begin_calls
    assert target.is_symlink() or target.exists()


def test_two_concurrent_coordinators_serialize_preparation_consumption_and_ready(setup):
    _, adapter, _, coordinator = setup
    verification_entered, release, second_entered = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def verify():
        calls.append("verify")
        if len(calls) == 1:
            verification_entered.set()
            assert release.wait(5)
        return EPOCH

    coordinator.verify_credentials = verify

    def second():
        second_entered.set()
        return coordinator.initialize()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(coordinator.initialize)
        assert verification_entered.wait(5)
        other = pool.submit(second)
        assert second_entered.wait(5)
        try:
            with pytest.raises(TimeoutError):
                other.result(timeout=0.05)
            assert adapter.inspect_calls == 1
        finally:
            release.set()
        results = [first.result(timeout=5), other.result(timeout=5)]
    assert results[0].prepared_identity.binding == results[1].prepared_identity.binding
    assert all(result.status.state == FactoryState.FACTORY for result in results)
    assert adapter.begin_calls == [results[0].prepared_identity.initialization_intent] * 2


def test_initialize_never_reads_wall_clock_or_opens_a_window(setup):
    _, _, _, coordinator = setup

    def unset_clock():
        pytest.fail("First boot must not read or require current wall time")

    coordinator.clock = coordinator.monotonic = unset_clock
    assert coordinator.initialize().status.state == FactoryState.FACTORY


def test_already_consumed_reply_after_authorized_inspection_cannot_create_database(setup):
    directory, adapter, _, coordinator = setup
    adapter.on_begin = lambda reply: {**reply, "status": "already_consumed"}
    with pytest.raises(FirstBootUncertain):
        coordinator.initialize()
    assert not (directory / "ownership.sqlite3").exists()
    assert (directory / PREPARED_IDENTITY_FILENAME).exists()


def test_ready_commit_reply_loss_reopens_factory_without_repeating_creation(setup, monkeypatch):
    _, adapter, _, coordinator = setup
    original = OwnershipStore.mark_factory_ready

    def lose_reply(store, binding):
        original(store, binding)
        raise OSError("interrupted after ready commit")

    with monkeypatch.context() as patch:
        patch.setattr(OwnershipStore, "mark_factory_ready", lose_reply)
        with pytest.raises(FirstBootUncertain):
            coordinator.initialize()
    resumed = coordinator.initialize()
    assert resumed.status.state == FactoryState.FACTORY
    assert adapter.begin_calls == [resumed.prepared_identity.initialization_intent] * 2


@pytest.mark.parametrize("damage", ["mode", "hardlink", "nonempty"])
def test_workflow_lock_must_be_private_single_link_and_empty(setup, damage):
    directory, adapter, _, coordinator = setup
    directory.mkdir(mode=0o700)
    lock = directory / ".first-boot.lock"
    lock.touch(mode=0o600)
    if damage == "mode":
        lock.chmod(0o644)
    elif damage == "hardlink":
        os.link(lock, directory / "other-lock-name")
    else:
        lock.write_bytes(b"unexpected")
    with pytest.raises(FirstBootRefused):
        coordinator.initialize()
    assert adapter.inspect_calls == 0 and not adapter.begin_calls


def publish_normal(prepared):
    operation = str(uuid4())
    return prepared.publish_initial(operation_id=operation,
                                    clock_result=ClockResult(operation, 1_800_000_000))


@pytest.mark.parametrize("repaired", [False, True])
def test_published_or_repaired_normal_identity_reopens_same_adopted_binding(setup, repaired):
    directory, _, _, coordinator = setup
    first = coordinator.initialize()
    owner, token, _ = adopt(first)
    publish_normal(first.prepared_identity)
    if repaired:
        current = first.prepared_identity.load_current_identity()
        operation = str(uuid4())
        first.prepared_identity.repair_existing(
            operation_id=operation, clock_result=ClockResult(operation, 1_900_000_000),
            expected_old_certificate_sha256=certificate_sha256(current))
    before = (directory / "identity.json").read_bytes()
    resumed = coordinator.initialize()
    assert resumed.status.state == FactoryState.ADOPTED
    assert resumed.prepared_identity.binding == first.prepared_identity.binding
    assert resumed.ownership.authenticate(owner, token).epoch == EPOCH
    assert (directory / "identity.json").read_bytes() == before


@pytest.mark.parametrize("damage", ["missing", "corrupt", "other_binding"])
def test_published_normal_identity_damage_requires_recovery_without_begin(setup, damage, tmp_path):
    directory, adapter, _, coordinator = setup
    first = coordinator.initialize()
    adopt(first)
    publish_normal(first.prepared_identity)
    path = directory / "identity.json"
    if damage == "missing":
        path.unlink()
    elif damage == "corrupt":
        path.write_bytes(b"corrupt normal identity")
    else:
        other = tmp_path / "other-identity"
        load_or_create_identity(other, now=datetime(2027, 1, 1, tzinfo=UTC))
        path.write_bytes((other / "identity.json").read_bytes())
    before = snapshot(directory)
    with pytest.raises(FirstBootRefused):
        coordinator.initialize()
    assert len(adapter.begin_calls) == 1
    assert snapshot(directory) == before


def test_pending_initial_publication_can_reopen_adopted_bootstrap_without_normal(setup, monkeypatch):
    directory, adapter, _, coordinator = setup
    first = coordinator.initialize()
    adopt(first)

    def interrupted_publish(*_args):
        raise OSError("after candidate journal, before normal publication")

    with monkeypatch.context() as patch:
        patch.setattr(PreparedFactoryIdentity, "_publish_candidate", interrupted_publish)
        with pytest.raises(OSError):
            publish_normal(first.prepared_identity)
    before = snapshot(directory)
    with sqlite3.connect(directory / "ownership.sqlite3") as connection:
        before_rows = list(connection.iterdump())
    resumed = coordinator.initialize()
    assert resumed.status.state == FactoryState.ADOPTED
    assert not (directory / "identity.json").exists()
    assert {k: v for k, v in snapshot(directory).items() if k != "ownership.sqlite3"} == {
        k: v for k, v in before.items() if k != "ownership.sqlite3"}
    with sqlite3.connect(directory / "ownership.sqlite3") as connection:
        assert list(connection.iterdump()) == before_rows
    assert adapter.begin_calls == [first.prepared_identity.initialization_intent] * 2


def test_credentials_callback_cannot_substitute_another_valid_prepared_binding(setup, tmp_path):
    directory, adapter, _, coordinator = setup

    def replace_prepared():
        prepared = PreparedFactoryIdentity.reopen(directory)
        other = tmp_path / "substituted-private"
        PreparedFactoryIdentity.create(other, initialization_intent=prepared.initialization_intent)
        (directory / PREPARED_IDENTITY_FILENAME).write_bytes((other / PREPARED_IDENTITY_FILENAME).read_bytes())
        return EPOCH

    coordinator.verify_credentials = replace_prepared
    with pytest.raises(FirstBootUncertain):
        coordinator.initialize()
    assert len(adapter.begin_calls) == 1
    with sqlite3.connect(directory / "ownership.sqlite3") as connection:
        assert connection.execute("SELECT state FROM factory_initialization").fetchone() == ("pending",)
