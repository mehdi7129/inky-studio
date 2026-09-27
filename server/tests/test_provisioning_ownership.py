"""Adoption durability, replay protection, expiry and password epoch ordering."""
from __future__ import annotations

import secrets
import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from uuid import uuid4

import pytest

from inky_web.provisioning import ownership


@dataclass
class Clock:
    wall: float = 1_800_000_000.0
    mono: float = 1000.0

    def advance(self, seconds):
        self.wall += seconds
        self.mono += seconds


@pytest.fixture
def state(tmp_path):
    clock, epoch = Clock(), ["a" * 64]
    store = ownership.OwnershipStore(tmp_path, lambda: epoch[0], clock=lambda: clock.wall, monotonic=lambda: clock.mono)
    return store, epoch, clock


def credentials():
    return str(uuid4()), secrets.token_hex(32), str(uuid4())


def adopt(state):
    store, epoch, _ = state
    owner_id, token, request_id = credentials()
    qr = store.open_window()
    result = store.claim(qr, owner_id, token, request_id, epoch[0])
    return owner_id, token, request_id, qr, result


def assert_error(code, operation):
    with pytest.raises(ownership.OwnershipError) as error:
        operation()
    assert error.value.code == code


def test_private_fullsync_storage_and_hashes_only(state):
    store, epoch, _ = state
    owner_id, token, request_id, qr, _ = adopt(state)
    assert store.authenticate(owner_id, token).epoch == epoch[0]
    assert store.status(owner_id, token, request_id).claimed
    assert stat.S_IMODE(store.directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    with store._connection() as connection:
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert connection.execute("PRAGMA fullfsync").fetchone()[0] == 1
    contents = store.path.read_bytes()
    assert token.encode() not in contents and qr.value.encode() not in contents
    assert token not in repr(store.status(owner_id, token))


def test_wrong_qr_token_cannot_consume_window(state):
    store, epoch, _ = state
    qr = store.open_window()
    owner_id, token, request_id = credentials()
    assert_error("unauthorized", lambda: store.claim("0" * 64, owner_id, token, request_id, epoch[0]))
    assert store.claim(qr, owner_id, token, request_id, epoch[0]).owner_id == owner_id


def test_wrong_owner_and_unknown_request_do_not_reveal_result(state):
    store, _, _ = state
    owner_id, token, _, _, _ = adopt(state)
    assert_error("unauthorized", lambda: store.authenticate(owner_id, "0" * 64))
    assert_error("unauthorized", lambda: store.authenticate(str(uuid4()), token))
    assert_error("request_not_found", lambda: store.status(owner_id, token, str(uuid4())))


@pytest.mark.parametrize("ttl", [0, -1, 601, float("inf"), float("nan"), True, "600"])
def test_window_ttl_is_bounded(state, ttl):
    assert_error("invalid_ttl", lambda: state[0].open_window(ttl))


def test_only_one_active_window_and_expiry(state):
    store, epoch, clock = state
    qr = store.open_window(10)
    assert_error("window_active", store.open_window)
    clock.advance(10)
    owner_id, token, request_id = credentials()
    assert_error("qr_unavailable", lambda: store.claim(qr, owner_id, token, request_id, epoch[0]))
    assert store.open_window().value != qr.value


def test_clock_rollback_invalidates_without_later_resurrection(state):
    store, epoch, clock = state
    qr = store.open_window()
    clock.wall -= 1
    owner_id, token, request_id = credentials()
    assert_error("qr_unavailable", lambda: store.claim(qr, owner_id, token, request_id, epoch[0]))
    clock.wall += 2
    assert_error("qr_unavailable", lambda: store.claim(qr, owner_id, token, request_id, epoch[0]))


def test_monotonic_deadline_survives_wall_clock_stall(state):
    store, epoch, clock = state
    qr = store.open_window()
    clock.mono += 601
    owner_id, token, request_id = credentials()
    assert_error("qr_unavailable", lambda: store.claim(qr, owner_id, token, request_id, epoch[0]))


def test_restart_invalidates_qr_but_retains_ownership(state):
    store, epoch, clock = state
    owner_id, token, _, _, _ = adopt(state)
    pending = store.open_window()
    new_owner, new_token, request_id = credentials()
    reopened = ownership.OwnershipStore(store.directory, lambda: epoch[0], clock=lambda: clock.wall, monotonic=lambda: clock.mono)
    assert reopened.authenticate(owner_id, token).owner_id == owner_id
    assert_error("qr_unavailable", lambda: reopened.claim(pending, new_owner, new_token, request_id, epoch[0]))


def test_lost_reply_identical_retry_after_restart(state):
    store, epoch, _ = state
    owner_id, token, request_id, qr, result = adopt(state)
    store = ownership.OwnershipStore(store.directory, lambda: epoch[0])
    assert store.claim(qr, owner_id, token, request_id, epoch[0]) == result
    assert store.status(owner_id, token, request_id).owner_id == owner_id
    assert_error("request_conflict", lambda: store.claim("0" * 64, owner_id, token, request_id, epoch[0]))
    assert_error("unauthorized", lambda: store.claim(qr, owner_id, "0" * 64, request_id, epoch[0]))


def test_request_id_cannot_bind_another_intention(state):
    store, epoch, _ = state
    _, _, request_id, _, _ = adopt(state)
    qr = store.open_window()
    owner_id, token, _ = credentials()
    assert_error("request_conflict", lambda: store.claim(qr, owner_id, token, request_id, epoch[0]))


def test_concurrent_claim_consumes_window_exactly_once(state):
    store, epoch, _ = state
    qr = store.open_window()

    def attempt(_):
        owner_id, token, request_id = credentials()
        try:
            return store.claim(qr, owner_id, token, request_id, epoch[0])
        except ownership.OwnershipError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sum(isinstance(result, ownership.ClaimResult) for result in results) == 1
    assert "qr_unavailable" in results


def test_maximum_eight_current_owners(state):
    store, epoch, _ = state
    for _ in range(8):
        adopt(state)
    qr = store.open_window()
    owner_id, token, request_id = credentials()
    assert_error("owner_capacity", lambda: store.claim(qr, owner_id, token, request_id, epoch[0]))


def test_bounded_history_keeps_original_claim_receipt(state, monkeypatch):
    monkeypatch.setattr(ownership, "MAX_HISTORY", 2)
    store, epoch, _ = state
    owner_id, token, request_id, qr, result = adopt(state)
    adopt(state)
    adopt(state)
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 2
    assert store.claim(qr, owner_id, token, request_id, epoch[0]) == result


def test_revoke_prevents_authentication_replay_and_reactivation(state):
    store, epoch, _ = state
    owner_id, token, request_id, qr, _ = adopt(state)
    store.revoke(owner_id)
    store.revoke(owner_id)
    assert_error("unauthorized", lambda: store.authenticate(owner_id, token))
    assert_error("unauthorized", lambda: store.claim(qr, owner_id, token, request_id, epoch[0]))
    assert_error("unauthorized", lambda: store.prepare_password_rotation(epoch[0], "b" * 64, owner_id))


def test_epoch_preparation_before_and_after_password_write(state):
    store, epoch, _ = state
    caller, token, _, _, _ = adopt(state)
    other, other_token, _, _, _ = adopt(state)
    old, new = epoch[0], "b" * 64
    store.prepare_password_rotation(old, new, caller)
    # Preparation committed, but password persistence has not happened (or failed).
    assert store.authenticate(caller, token).epoch == old
    assert store.authenticate(other, other_token).epoch == old
    # Password rename succeeds. No post-write callback is needed.
    epoch[0] = new
    assert store.authenticate(caller, token).epoch == new
    assert_error("unauthorized", lambda: store.authenticate(other, other_token))
    reopened = ownership.OwnershipStore(store.directory, lambda: epoch[0])
    assert reopened.authenticate(caller, token).epoch == new
    assert_error("unauthorized", lambda: reopened.authenticate(other, other_token))


def test_rotation_without_authenticated_owner_preserves_nobody(state):
    store, epoch, _ = state
    owner_id, token, _, _, _ = adopt(state)
    store.prepare_password_rotation(epoch[0], "b" * 64, None)
    epoch[0] = "b" * 64
    assert_error("unauthorized", lambda: store.authenticate(owner_id, token))


def test_failed_preparation_does_not_change_access(state):
    store, epoch, _ = state
    owner_id, token, _, _, _ = adopt(state)
    assert_error("epoch_changed", lambda: store.prepare_password_rotation("c" * 64, "b" * 64, owner_id))
    assert store.authenticate(owner_id, token).epoch == epoch[0]


def test_abandoned_preparations_are_bounded_and_not_reactivated(state):
    store, epoch, _ = state
    owner_id, token, _, _, _ = adopt(state)
    store.prepare_password_rotation(epoch[0], "b" * 64, owner_id)
    store.prepare_password_rotation(epoch[0], "c" * 64, owner_id)
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM allowed_epochs").fetchone()[0] == 2
    store.prepare_password_rotation(epoch[0], "c" * 64, None)
    epoch[0] = "c" * 64
    assert_error("unauthorized", lambda: store.authenticate(owner_id, token))


def test_window_cannot_cross_password_epoch(state):
    store, epoch, _ = state
    qr = store.open_window()
    old = epoch[0]
    epoch[0] = "b" * 64
    owner_id, token, request_id = credentials()
    assert_error("epoch_changed", lambda: store.claim(qr, owner_id, token, request_id, old))
    assert_error("qr_unavailable", lambda: store.claim(qr, owner_id, token, request_id, epoch[0]))


@pytest.mark.parametrize("data", [b"", b"not a sqlite database"])
def test_corrupt_existing_store_is_not_reset(tmp_path, data):
    path = tmp_path / "ownership.sqlite3"
    path.write_bytes(data)
    with pytest.raises(ownership.OwnershipStorageError):
        ownership.OwnershipStore(tmp_path, lambda: "a" * 64)
    assert path.read_bytes() == data


def test_credential_epoch_uses_verifier_not_password():
    salt, digest = bytes(range(16)), bytes(range(32))
    first = ownership.credential_epoch(salt, digest)
    assert len(first) == 64
    assert first == ownership.credential_epoch(salt, digest)
    assert first != ownership.credential_epoch(bytes(reversed(salt)), digest)
