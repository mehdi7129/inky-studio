"""Opt-in initialization journal, terminal claim and explicit recovery boundaries.

All receipts and identities are synthetic local assertions. These tests do not
qualify a root-owned receipt adapter, real identity files, boot, BLE or hardware.
"""
from __future__ import annotations

import secrets
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4

import pytest

from inky_web.provisioning import ownership
from inky_web.provisioning.factory import (
    FactoryIdentity,
    FactoryRecoveryRequired,
    FactoryState,
    InitializationReceipt,
)


@dataclass
class FactoryFixture:
    directory: Path
    receipt: InitializationReceipt
    identity: FactoryIdentity
    epoch: str = "a" * 64

    def create(self):
        return ownership.OwnershipStore.create_factory(
            self.directory, lambda: self.epoch, receipt=self.receipt,
            expected_identity=self.identity,
        )

    def reopen(self, **overrides):
        parameters = {"receipt": self.receipt, "expected_identity": self.identity}
        parameters.update(overrides)
        return ownership.OwnershipStore.reopen_factory(
            self.directory, lambda: self.epoch, **parameters,
        )

    def ready(self):
        store = self.create()
        store.mark_factory_ready(self.identity)
        return store


@pytest.fixture
def factory(tmp_path):
    return FactoryFixture(tmp_path / "private", InitializationReceipt(str(uuid4()), "1" * 64),
                          FactoryIdentity(str(uuid4()), "2" * 64))


def phone():
    return str(uuid4()), secrets.token_hex(32), str(uuid4())


def claim(store, factory):
    owner_id, token, request_id = phone()
    qr = store.open_factory_window()
    result = store.claim(qr, owner_id, token, request_id, factory.epoch)
    return qr, owner_id, token, request_id, result


def assert_error(code, operation):
    with pytest.raises(ownership.OwnershipError) as error:
        operation()
    assert error.value.code == code


def database_snapshot(store):
    with sqlite3.connect(store.path) as connection:
        return "\n".join(connection.iterdump())


def test_explicit_creation_journals_pending_then_confirms_same_identity(factory):
    store = factory.create()
    status = store.factory_status()
    assert status.state == FactoryState.PENDING
    assert status.identity == factory.identity
    assert status.first_owner_id is None
    assert_error("factory_not_ready", store.open_factory_window)
    assert_error("factory_not_ready", store.open_window)
    assert_error("factory_not_ready", lambda: store.claim("3" * 64, *phone(), factory.epoch))
    assert store.mark_factory_ready(factory.identity).state == FactoryState.FACTORY
    assert store.mark_factory_ready(factory.identity).state == FactoryState.FACTORY
    assert_error("factory_window_required", store.open_window)
    assert store.open_factory_window().value
    with sqlite3.connect(store.path) as connection:
        row = connection.execute("SELECT receipt_id, receipt_digest, frame_id, spki_sha256, state "
                                 "FROM factory_initialization").fetchone()
        assert row == (factory.receipt.receipt_id, factory.receipt.digest, factory.identity.frame_id,
                       factory.identity.spki_sha256, "factory")


def test_pending_reopen_resumes_same_intent_without_new_identity(factory):
    factory.create()
    reopened = factory.reopen()
    assert reopened.factory_status().state == FactoryState.PENDING
    assert reopened.mark_factory_ready(factory.identity).state == FactoryState.FACTORY


def test_ready_requires_same_identity_and_leaves_pending_unchanged(factory):
    store = factory.create()
    before = database_snapshot(store)
    with pytest.raises(FactoryRecoveryRequired):
        store.mark_factory_ready(replace(factory.identity, spki_sha256="3" * 64))
    assert database_snapshot(store) == before
    assert store.factory_status().state == FactoryState.PENDING


@pytest.mark.parametrize("change", ["receipt_id", "receipt_digest", "frame_id", "spki"])
def test_reopen_mismatched_binding_preserves_database_and_existing_window(factory, change):
    store = factory.ready()
    store.open_factory_window()
    before = database_snapshot(store)
    receipt, identity = factory.receipt, factory.identity
    if change == "receipt_id":
        receipt = replace(receipt, receipt_id=str(uuid4()))
    elif change == "receipt_digest":
        receipt = replace(receipt, digest="4" * 64)
    elif change == "frame_id":
        identity = replace(identity, frame_id=str(uuid4()))
    else:
        identity = replace(identity, spki_sha256="4" * 64)
    with pytest.raises(FactoryRecoveryRequired) as error:
        factory.reopen(receipt=receipt, expected_identity=identity)
    assert error.value.state == FactoryState.RECOVERY
    assert database_snapshot(store) == before


def test_reopen_absent_directory_does_not_create_it(factory):
    with pytest.raises(FactoryRecoveryRequired):
        factory.reopen()
    assert not factory.directory.exists()


def test_reopen_absent_database_does_not_create_one(factory):
    factory.directory.mkdir()
    with pytest.raises(FactoryRecoveryRequired):
        factory.reopen()
    assert not (factory.directory / "ownership.sqlite3").exists()


@pytest.mark.parametrize("contents", [b"", b"broken sqlite", b"SQLite format 3\x00incomplete"])
def test_corrupt_or_interrupted_creation_is_preserved(factory, contents):
    factory.directory.mkdir()
    path = factory.directory / "ownership.sqlite3"
    path.write_bytes(contents)
    for operation in (factory.reopen, factory.create):
        with pytest.raises(FactoryRecoveryRequired):
            operation()
        assert path.read_bytes() == contents


def test_repeated_creation_cannot_replace_pending_or_ready_or_adopted(factory):
    store = factory.create()
    for state in (FactoryState.PENDING, FactoryState.FACTORY, FactoryState.ADOPTED):
        before = database_snapshot(store)
        with pytest.raises(FactoryRecoveryRequired):
            factory.create()
        assert database_snapshot(store) == before
        assert store.factory_status().state == state
        if state == FactoryState.PENDING:
            store.mark_factory_ready(factory.identity)
        elif state == FactoryState.FACTORY:
            claim(store, factory)


def test_no_legacy_promotion_or_factory_access_by_default_constructor(factory):
    legacy = ownership.OwnershipStore(factory.directory, lambda: factory.epoch)
    old_qr = legacy.open_window()
    before = database_snapshot(legacy)
    for operation in (factory.create, factory.reopen):
        with pytest.raises(FactoryRecoveryRequired):
            operation()
        assert database_snapshot(legacy) == before
    assert_error("factory_not_enabled", legacy.factory_status)
    assert_error("factory_not_enabled", legacy.open_factory_window)
    # Legacy ownership remains functional and was not silently migrated.
    assert legacy.claim(old_qr, *phone(), factory.epoch).owner_id


@pytest.mark.parametrize("downgraded_version", [False, True])
def test_legacy_open_refuses_factory_before_invalidating_window(factory, downgraded_version):
    store = factory.ready()
    store.open_factory_window()
    if downgraded_version:
        with sqlite3.connect(store.path) as connection:
            connection.execute("PRAGMA user_version = 1")
    before = database_snapshot(store)
    with pytest.raises(ownership.OwnershipStorageError):
        ownership.OwnershipStore(factory.directory, lambda: factory.epoch)
    assert database_snapshot(store) == before


def test_claim_receipt_and_terminal_adoption_are_atomic(factory):
    store = factory.ready()
    qr, owner_id, token, request_id, result = claim(store, factory)
    status = store.factory_status()
    assert status.state == FactoryState.ADOPTED
    assert status.identity == factory.identity
    assert status.first_owner_id == owner_id
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM owners").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM allowed_epochs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM window").fetchone()[0] == 0
    assert store.authenticate(owner_id, token).epoch == factory.epoch
    assert store.claim(qr, owner_id, token, request_id, factory.epoch) == result
    assert_error("factory_unavailable", store.open_factory_window)


def test_failed_adopted_write_rolls_back_owner_receipt_and_keeps_qr(factory):
    store = factory.ready()
    qr = store.open_factory_window()
    owner_id, token, request_id = phone()
    with sqlite3.connect(store.path) as connection:
        connection.execute("CREATE TRIGGER reject_adoption BEFORE UPDATE ON factory_initialization "
                           "WHEN NEW.state = 'adopted' BEGIN SELECT RAISE(ABORT, 'injected'); END")
    before = database_snapshot(store)
    with pytest.raises(FactoryRecoveryRequired):
        store.claim(qr, owner_id, token, request_id, factory.epoch)
    assert database_snapshot(store) == before
    assert store.factory_status().state == FactoryState.FACTORY
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM owners").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0
        connection.execute("DROP TRIGGER reject_adoption")
    # Removing the injected failure leaves the original proof usable.
    assert store.claim(qr, owner_id, token, request_id, factory.epoch).owner_id == owner_id
    assert store.factory_status().state == FactoryState.ADOPTED


def test_lost_claim_reply_is_recoverable_after_restart(factory):
    store = factory.ready()
    qr, owner_id, token, request_id, result = claim(store, factory)
    reopened = factory.reopen()
    assert reopened.claim(qr, owner_id, token, request_id, factory.epoch) == result
    assert reopened.status(owner_id, token, request_id).claimed
    assert reopened.factory_status().state == FactoryState.ADOPTED
    assert_error("unauthorized", lambda: reopened.claim(qr, owner_id, "0" * 64, request_id, factory.epoch))
    assert_error("factory_unavailable", reopened.open_factory_window)


def test_last_owner_revoked_and_epoch_rotated_never_reopens_factory(factory):
    store = factory.ready()
    qr, owner_id, token, request_id, _ = claim(store, factory)
    store.revoke(owner_id)
    store.prepare_password_rotation(factory.epoch, "b" * 64)
    factory.epoch = "b" * 64
    reopened = factory.reopen()
    assert reopened.factory_status().state == FactoryState.ADOPTED
    assert reopened.factory_status().first_owner_id == owner_id
    assert_error("unauthorized", lambda: reopened.authenticate(owner_id, token))
    assert_error("factory_unavailable", reopened.open_factory_window)
    assert_error("unauthorized", lambda: reopened.claim(qr, owner_id, token, request_id, factory.epoch))
    assert reopened.mark_factory_ready(factory.identity).state == FactoryState.ADOPTED
    # Existing privileged photo-session enrollment remains possible without
    # reopening the factory policy or replacing the permanent first-owner tombstone.
    admin_qr = reopened.open_window()
    new_owner, new_token, new_request = phone()
    reopened.claim(admin_qr, new_owner, new_token, new_request, factory.epoch)
    assert reopened.authenticate(new_owner, new_token).owner_id == new_owner
    assert reopened.factory_status().first_owner_id == owner_id


def test_password_epoch_change_before_claim_does_not_adopt(factory):
    store = factory.ready()
    qr = store.open_factory_window()
    old_epoch = factory.epoch
    factory.epoch = "b" * 64
    assert_error("epoch_changed", lambda: store.claim(qr, *phone(), old_epoch))
    assert_error("qr_unavailable", lambda: store.claim(qr, *phone(), factory.epoch))
    assert store.factory_status().state == FactoryState.FACTORY


def test_restart_invalidates_factory_qr_without_changing_initialization(factory):
    store = factory.ready()
    qr = store.open_factory_window()
    reopened = factory.reopen()
    assert reopened.factory_status().state == FactoryState.FACTORY
    assert_error("qr_unavailable", lambda: reopened.claim(qr, *phone(), factory.epoch))
    new_qr = reopened.open_factory_window()
    assert new_qr.value != qr.value


def test_two_concurrent_phones_get_one_terminal_claim(factory):
    store = factory.ready()
    qr = store.open_factory_window()

    def attempt(_):
        owner_id, token, request_id = phone()
        try:
            result = store.claim(qr, owner_id, token, request_id, factory.epoch)
            return result, owner_id, token, request_id
        except ownership.OwnershipError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    winners = [result for result in results if isinstance(result, tuple)]
    assert len(winners) == 1 and "qr_unavailable" in results
    result, owner_id, token, request_id = winners[0]
    reopened = factory.reopen()
    assert reopened.factory_status().first_owner_id == owner_id
    assert reopened.claim(qr, owner_id, token, request_id, factory.epoch) == result
    with sqlite3.connect(reopened.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM owners").fetchone()[0] == 1


@pytest.mark.parametrize("mutation", [
    "DELETE FROM factory_initialization",
    "UPDATE factory_initialization SET state = 'unknown'",
    "UPDATE factory_initialization SET state = 'adopted', first_owner_id = NULL",
    "UPDATE factory_initialization SET state = 'adopted', first_owner_id = '00000000-0000-0000-0000-000000000001'",
    "UPDATE factory_initialization SET receipt_digest = ''",
    "UPDATE factory_initialization SET frame_id = 'invalid'",
    "UPDATE factory_initialization SET spki_sha256 = ''",
    "UPDATE factory_initialization SET state = 'pending'",  # An extant window contradicts pending.
    "DROP TABLE factory_initialization",
])
def test_semantically_corrupt_valid_sqlite_requires_recovery_without_repair(factory, mutation):
    store = factory.ready()
    store.open_factory_window()
    with sqlite3.connect(store.path) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(mutation)
    before = store.path.read_bytes()
    with pytest.raises(FactoryRecoveryRequired):
        factory.reopen()
    assert store.path.read_bytes() == before


def test_existing_owner_cannot_be_hidden_by_reverting_to_factory(factory):
    store = factory.ready()
    claim(store, factory)
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE factory_initialization SET state = 'factory', first_owner_id = NULL")
    before = store.path.read_bytes()
    with pytest.raises(FactoryRecoveryRequired):
        factory.reopen()
    assert store.path.read_bytes() == before


def test_adopted_missing_first_owner_is_recovery_not_empty_factory(factory):
    store = factory.ready()
    claim(store, factory)
    with sqlite3.connect(store.path) as connection:
        connection.execute("DELETE FROM requests")
        connection.execute("DELETE FROM allowed_epochs")
        connection.execute("DELETE FROM owners")
    before = store.path.read_bytes()
    with pytest.raises(FactoryRecoveryRequired):
        factory.reopen()
    assert store.path.read_bytes() == before


def test_active_handle_checks_durable_binding_before_mark_ready(factory):
    store = factory.create()
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE factory_initialization SET spki_sha256 = ?", ("9" * 64,))
    before = store.path.read_bytes()
    with pytest.raises(FactoryRecoveryRequired):
        store.mark_factory_ready(factory.identity)
    assert store.path.read_bytes() == before


def test_deleted_database_is_not_recreated_by_live_factory_handle(factory):
    store = factory.ready()
    store.path.unlink()
    with pytest.raises(FactoryRecoveryRequired):
        store.open_factory_window()
    assert not store.path.exists()
    with pytest.raises(FactoryRecoveryRequired):
        factory.reopen()
    assert not store.path.exists()


def test_symlink_database_is_not_opened_or_replaced(factory, tmp_path):
    store = factory.ready()
    original = tmp_path / "saved.sqlite3"
    store.path.rename(original)
    store.path.symlink_to(original)
    before = original.read_bytes()
    for operation in (factory.reopen, store.factory_status):
        with pytest.raises(FactoryRecoveryRequired):
            operation()
    assert original.read_bytes() == before and store.path.is_symlink()


def test_live_factory_handle_rejects_fifo_without_waiting_for_writer(tmp_path):
    # Keep this regression in a subprocess: removing O_NONBLOCK must fail by
    # timeout, never hang the test runner at the FIFO's read-only open.
    program = """
import os
import stat
import sys
from pathlib import Path
from uuid import uuid4
from inky_web.provisioning.factory import FactoryIdentity, FactoryRecoveryRequired, InitializationReceipt
from inky_web.provisioning.ownership import OwnershipStore

directory = Path(sys.argv[1])
identity = FactoryIdentity(str(uuid4()), "2" * 64)
store = OwnershipStore.create_factory(
    directory, lambda: "a" * 64,
    receipt=InitializationReceipt(str(uuid4()), "1" * 64), expected_identity=identity,
)
store.mark_factory_ready(identity)
saved = directory / "saved.sqlite3"
before = store.path.read_bytes()
store.path.rename(saved)
os.mkfifo(store.path, 0o600)
try:
    store.factory_status()
except FactoryRecoveryRequired:
    assert stat.S_ISFIFO(store.path.stat().st_mode)
    assert saved.read_bytes() == before
    print("recovery")
else:
    raise AssertionError("A FIFO was accepted as factory storage")
"""
    result = subprocess.run([sys.executable, "-c", program, str(tmp_path / "private")],
                            capture_output=True, text=True, timeout=5, check=True)
    assert result.stdout.strip() == "recovery"


@pytest.mark.parametrize("factory_type, arguments", [
    (InitializationReceipt, ("not-a-uuid", "1" * 64)),
    (InitializationReceipt, (str(uuid4()), b"1" * 64)),
    (InitializationReceipt, (str(uuid4()), "G" * 64)),
    (FactoryIdentity, ("not-a-uuid", "2" * 64)),
    (FactoryIdentity, (str(uuid4()), "2" * 63)),
    (FactoryIdentity, (str(uuid4()), "2" * 64 + "\n")),
])
def test_internal_assertions_require_strict_uuid_and_digest(factory_type, arguments):
    with pytest.raises(ValueError):
        factory_type(*arguments)


def test_no_mapping_or_implicit_enablement_and_receipt_repr_is_redacted(factory):
    with pytest.raises(ValueError):
        factory.reopen(receipt={"receipt_id": factory.receipt.receipt_id, "digest": factory.receipt.digest})
    assert factory.receipt.digest not in repr(factory.receipt)
    assert not factory.directory.exists()
