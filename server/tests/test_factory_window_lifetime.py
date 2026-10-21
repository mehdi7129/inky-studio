"""Local remaining-TTL contract; no QR secret or new wire/schema surface."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from inky_web.provisioning.factory import FactoryRecoveryRequired
from inky_web.provisioning.first_boot import FirstBootCoordinator
from inky_web.provisioning.ownership import OwnershipError
from tests.test_bootstrap_runtime import EPOCH, FakeOS


@pytest.fixture
def window(tmp_path):
    clocks = SimpleNamespace(wall=1_790_000_000.0, monotonic=50.0)
    epoch = [EPOCH]
    result = FirstBootCoordinator(
        tmp_path / "private", FakeOS(), lambda: epoch[0],
        clock=lambda: clocks.wall, monotonic=lambda: clocks.monotonic,
    ).initialize()
    store = result.ownership
    token = store.open_factory_window(expected_epoch=EPOCH)
    try:
        yield SimpleNamespace(store=store, clocks=clocks, epoch=epoch, token=token)
    finally:
        store.close()


def remaining(v, *, epoch=EPOCH):
    value = v.store.factory_window_remaining(expected_epoch=epoch)
    assert type(value) is float
    return value


def test_remaining_uses_shorter_clock_and_never_extends_original_ttl(window):
    v = window
    assert remaining(v) == pytest.approx(600)
    deadline = v.store._window_deadline
    v.clocks.wall += 40
    v.clocks.monotonic += 125
    assert remaining(v) == pytest.approx(475)
    assert remaining(v) == pytest.approx(475)
    v.clocks.wall += 150
    assert remaining(v) == pytest.approx(410)
    assert v.store._window_deadline == deadline == pytest.approx(650)


@pytest.mark.parametrize("expired_clock", ["wall", "monotonic"])
def test_either_clock_can_expire_the_current_window(window, expired_clock):
    v = window
    setattr(v.clocks, expired_clock, getattr(v.clocks, expired_clock) + 600)
    assert remaining(v) == 0.0
    assert remaining(v) == 0.0


def test_rotation_reports_only_current_window_and_old_token_cannot_claim(window):
    v = window
    v.clocks.wall += 600
    v.clocks.monotonic += 600
    assert remaining(v) == 0.0
    v.store.close_window()
    replacement = v.store.open_factory_window(expected_epoch=EPOCH)
    assert replacement.value != v.token.value
    assert remaining(v) == pytest.approx(600)
    with pytest.raises(OwnershipError) as caught:
        v.store.claim(v.token, str(uuid4()), "b" * 64, str(uuid4()), EPOCH)
    assert caught.value.code == "unauthorized"
    assert remaining(v) == pytest.approx(600)


def test_expired_claim_does_not_make_normal_expiry_indistinguishable_from_corruption(window):
    v = window
    v.clocks.wall += 600
    v.clocks.monotonic += 600
    with pytest.raises(OwnershipError) as caught:
        v.store.claim(v.token, str(uuid4()), "b" * 64, str(uuid4()), EPOCH)
    assert caught.value.code == "qr_unavailable"
    assert remaining(v) == 0.0


@pytest.mark.parametrize("invalidated_by", ["wall_rollback", "changed_epoch"])
def test_invalidated_claim_stays_refused_after_clock_or_epoch_is_restored(window, invalidated_by):
    v = window
    if invalidated_by == "wall_rollback":
        v.clocks.wall -= 1
        expected_epoch = EPOCH
    else:
        v.epoch[0] = "f" * 64
        expected_epoch = v.epoch[0]
    with pytest.raises(OwnershipError) as caught:
        v.store.claim(v.token, str(uuid4()), "b" * 64, str(uuid4()), expected_epoch)
    assert caught.value.code == "qr_unavailable" and v.store._window_deadline is None
    v.clocks.wall = 1_790_000_000.0
    v.epoch[0] = EPOCH
    with pytest.raises(OwnershipError) as caught:
        remaining(v)
    assert caught.value.code == "qr_unavailable"


@pytest.mark.parametrize("clock_name", ["wall", "monotonic"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_clock_is_a_refusal_and_never_ordinary_expiry(window, clock_name, bad):
    setattr(window.clocks, clock_name, bad)
    with pytest.raises(OwnershipError) as caught:
        remaining(window)
    assert caught.value.code == "invalid_clock"


def test_wall_rollback_after_observation_is_not_an_expired_window(window):
    v = window
    v.clocks.wall += 120
    v.clocks.monotonic += 120
    assert remaining(v) == pytest.approx(480)
    v.clocks.wall -= 1
    with pytest.raises(OwnershipError) as caught:
        remaining(v)
    assert caught.value.code == "invalid_clock"


def test_missing_window_is_a_refusal_instead_of_an_expiry_signal(window):
    window.store.close_window()
    with pytest.raises(OwnershipError) as caught:
        remaining(window)
    assert caught.value.code == "qr_unavailable"


def test_adoption_never_returns_permission_to_open_a_factory_window(window):
    v = window
    v.store.claim(v.token, str(uuid4()), "b" * 64, str(uuid4()), EPOCH)
    with pytest.raises(OwnershipError) as caught:
        remaining(v)
    assert caught.value.code == "factory_unavailable"


@pytest.mark.parametrize("change_current", [False, True])
def test_epoch_mismatch_is_a_refusal_instead_of_an_expiry_signal(window, change_current):
    v = window
    if change_current:
        v.epoch[0] = "f" * 64
    with pytest.raises(OwnershipError) as caught:
        remaining(v, epoch="f" * 64)
    assert caught.value.code == "epoch_changed"


@pytest.mark.parametrize("column,value", [
    ("created_at", "invalid"),
    ("expires_at", "invalid"),
    ("epoch", "invalid"),
    ("token_hash", "invalid"),
])
def test_malformed_window_never_returns_a_renewal_signal(window, column, value):
    # Column names come solely from this closed parameter list.
    with window.store._transaction() as connection:
        connection.execute(f"UPDATE window SET {column} = ? WHERE id = 1", (value,))
    with pytest.raises(FactoryRecoveryRequired):
        remaining(window)
