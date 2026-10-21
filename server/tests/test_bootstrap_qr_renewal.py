"""Factory QR renewal with real ownership storage and inert, distinct clocks.

The clock advances inside a real screen render without waiting for the 600s
window. Only the timer's sleep is replaced; runtime tasks, SQLite commits,
thread drains and the existing image renderer execute normally.
"""
from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest

from inky_web.provisioning import bootstrap_runtime
from inky_web.provisioning.bootstrap_identity import ClockResult
from inky_web.provisioning.bootstrap_runtime import BootstrapRuntime
from inky_web.provisioning.factory import FactoryRecoveryRequired, FactoryState
from inky_web.provisioning.factory_continuation import FactoryContinuationRuntime
from inky_web.provisioning.first_boot import FirstBootCoordinator
from inky_web.provisioning.ownership import OwnershipError
from tests.test_bootstrap_runtime import (
    EPOCH,
    FakeBlueZ,
    FakeDisplay,
    FakeOS,
    claim_message,
    status_message,
)
from tests.test_factory_system_setup import Native, Network


class ManualClocks:
    """Wall time and the two monotonic epochs intentionally differ."""

    def __init__(self):
        self.elapsed = 0.0
        self.wall_shift = 0.0
        self.owner_shift = 0.0
        self.waits = asyncio.Queue()
        self.pending = []

    def wall(self):
        return 1_790_000_000.0 + self.elapsed + self.wall_shift

    def owner(self):
        return 50.0 + self.elapsed + self.owner_shift

    def runtime(self):
        return 10_000.0 + self.elapsed

    def elapse(self, seconds):
        # Screen rendering calls this from a worker thread before any next
        # timer is registered. Future completion stays on the asyncio thread.
        self.elapsed += seconds

    def advance(self, seconds):
        self.elapse(seconds)
        for deadline, future in self.pending:
            if not future.done() and deadline <= self.runtime():
                future.set_result(None)

    async def sleep(self, delay):
        if delay <= 0:
            await asyncio.sleep(0)
            return
        future = asyncio.get_running_loop().create_future()
        deadline = self.runtime() + delay
        self.pending.append((deadline, future))
        self.waits.put_nowait((delay, deadline))
        await future

    async def next_wait(self):
        return await asyncio.wait_for(self.waits.get(), 5)


@pytest.fixture(params=["parent", "continuation"])
async def factory_qr(tmp_path, monkeypatch, request):
    monkeypatch.setenv("INKY_STUDIO_DATA_DIR", str(tmp_path / "normal-state"))
    monkeypatch.delenv("INKY_STUDIO_DISABLE_AUTH", raising=False)
    clocks = ManualClocks()
    # Replace this module's reference, never asyncio.sleep process-wide.
    clock_asyncio = SimpleNamespace(**vars(asyncio))
    clock_asyncio.sleep = clocks.sleep
    monkeypatch.setattr(bootstrap_runtime, "asyncio", clock_asyncio)
    directory = tmp_path / "private"
    epoch = [EPOCH]
    coordinator = FirstBootCoordinator(
        directory, FakeOS(), lambda: epoch[0], clock=clocks.wall, monotonic=clocks.owner,
    )
    result = coordinator.initialize()
    display = FakeDisplay()
    kwargs = {"server_factory": FakeBlueZ, "monotonic": clocks.runtime}
    if request.param == "continuation":
        runtime = FactoryContinuationRuntime(
            result, lambda: epoch[0], display, directory,
            system_setup=Native(), network=Network(), **kwargs,
        )
    else:
        runtime = BootstrapRuntime(result, lambda: epoch[0], display, directory, **kwargs)
    payloads = []
    durations = []
    original = runtime.screen.show_qr

    def observe(payload):
        payloads.append(json.loads(payload))
        original(payload)
        if durations:
            clocks.elapse(durations.pop(0))

    monkeypatch.setattr(runtime.screen, "show_qr", observe)
    value = SimpleNamespace(
        runtime=runtime, result=result, clocks=clocks, payloads=payloads,
        durations=durations, display=display, epoch=epoch,
    )
    try:
        yield value
    finally:
        # A failure injection is scoped inside each test and restored before
        # the real lifecycle drain; teardown must not hide cleanup failures.
        await runtime.stop()
        result.ownership.close()


async def expire(v, *, elapsed=600):
    timer = v.runtime._window_task
    assert timer is not None
    v.clocks.advance(elapsed)
    await asyncio.wait_for(asyncio.shield(timer), 5)


async def test_slow_screen_uses_remaining_store_ttl_with_distinct_clock_epochs(factory_qr):
    v = factory_qr
    v.durations.append(185)
    await v.runtime.start()
    delay, deadline = await v.clocks.next_wait()
    assert delay == pytest.approx(415)
    assert deadline == pytest.approx(10_600)
    assert v.result.ownership._window_deadline == pytest.approx(650)
    assert len(v.payloads) == 1 and v.runtime.available and v.runtime.bluez.started
    await expire(v, elapsed=415)
    delay, deadline = await v.clocks.next_wait()
    assert delay == pytest.approx(600)
    assert deadline == pytest.approx(11_200)
    assert len(v.payloads) == 2


async def test_timer_automatically_rotates_qr_and_only_new_token_can_claim(factory_qr):
    v = factory_qr
    await v.runtime.start()
    assert (await v.clocks.next_wait())[0] == pytest.approx(600)
    initial = v.payloads[0]
    await expire(v)
    assert (await v.clocks.next_wait())[0] == pytest.approx(600)
    replacement = v.payloads[1]
    assert replacement["t"] != initial["t"]
    assert replacement["id"] == initial["id"] and replacement["k"] == initial["k"]
    assert v.runtime.available and v.runtime._admitting and v.display.max_active == 1
    stale_claim = claim_message(initial["t"])
    assert (await v.runtime.command(stale_claim)) == {
        "v": 1, "id": stale_claim["id"], "ok": False, "error": "unauthorized",
    }
    claim = claim_message(replacement["t"])
    reply = await v.runtime.command(claim)
    assert reply["ok"] and reply["result"]["factory_state"] == "adopted"
    status = await v.runtime.command(status_message(claim))
    assert status["ok"] and status["result"] == reply["result"]
    assert v.result.ownership.factory_status().state == FactoryState.ADOPTED


async def test_claim_before_deadline_cancels_timer_and_stale_expiry_never_reopens(factory_qr):
    v = factory_qr
    await v.runtime.start()
    await v.clocks.next_wait()
    v.clocks.advance(599)
    claim = claim_message(v.payloads[0]["t"])
    reply = await v.runtime.command(claim)
    assert reply["ok"] and v.runtime._window_task is None
    v.clocks.advance(1000)
    # Model an expiry operation that was already queued behind the winning
    # durable claim, independent of cancellation of the timer itself.
    await v.runtime._expire_screen()
    assert len(v.payloads) == 1 and v.result.ownership._window_deadline is None
    status = await v.runtime.command(status_message(claim))
    assert status["ok"] and status["result"] == reply["result"]


async def test_early_timer_callback_preserves_live_token_and_original_deadline(factory_qr):
    v = factory_qr
    await v.runtime.start()
    await v.clocks.next_wait()
    v.runtime._cancel_window_timer()
    v.clocks.advance(40)
    await v.runtime._expire_screen()
    delay, deadline = await v.clocks.next_wait()
    assert delay == pytest.approx(560) and deadline == pytest.approx(10_600)
    assert len(v.payloads) == 1 and v.result.ownership._window_deadline == pytest.approx(650)
    assert (await v.runtime.command(claim_message(v.payloads[0]["t"])))["ok"]


async def test_queued_expiry_after_fail_closed_never_reopens(factory_qr):
    v = factory_qr
    await v.runtime.start()
    await v.clocks.next_wait()
    v.runtime._fail_closed()
    await expire(v)
    await v.runtime._expire_screen()
    assert len(v.payloads) == 1 and not v.runtime.available and not v.runtime._admitting
    assert v.runtime._window_task is None or v.runtime._window_task.done()


async def test_expired_scan_before_timer_does_not_disable_automatic_renewal(factory_qr):
    v = factory_qr
    await v.runtime.start()
    await v.clocks.next_wait()
    timer = v.runtime._window_task
    # Advance durable clocks while leaving the timer asleep to model a
    # command arriving before an already-due asyncio callback is scheduled.
    v.clocks.elapse(600)
    assert (await v.runtime.command(claim_message(v.payloads[0]["t"])))["error"] == "qr_unavailable"
    v.clocks.advance(0)
    await asyncio.wait_for(asyncio.shield(timer), 5)
    assert len(v.payloads) == 2 and v.runtime.available
    assert (await v.runtime.command(claim_message(v.payloads[1]["t"])))["ok"]


@pytest.mark.parametrize("invalidated_by", ["wall_rollback", "changed_epoch"])
async def test_invalidated_scan_cannot_become_ordinary_expiry_after_restoration(
    factory_qr, invalidated_by,
):
    v = factory_qr
    await v.runtime.start()
    await v.clocks.next_wait()
    if invalidated_by == "wall_rollback":
        v.clocks.wall_shift = -1
    else:
        v.epoch[0] = "f" * 64
    assert (await v.runtime.command(claim_message(v.payloads[0]["t"])))["error"] == "qr_unavailable"
    assert v.result.ownership._window_deadline is None
    v.clocks.wall_shift = 0
    v.epoch[0] = EPOCH
    await expire(v)
    assert len(v.payloads) == 1 and not v.runtime.available and not v.runtime._admitting
    assert v.runtime._window_task is None or v.runtime._window_task.done()


@pytest.mark.parametrize("clock_name", ["wall", "monotonic"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")],
                         ids=["nan", "positive_inf", "negative_inf"])
async def test_nonfinite_claim_invalidation_closes_callback_after_clock_restoration(
    factory_qr, clock_name, bad,
):
    v = factory_qr
    await v.runtime.start()
    await v.clocks.next_wait()
    shift_name = "wall_shift" if clock_name == "wall" else "owner_shift"
    setattr(v.clocks, shift_name, bad)
    assert (await v.runtime.command(claim_message(v.payloads[0]["t"])))["error"] == "qr_unavailable"
    setattr(v.clocks, shift_name, 0.0)
    v.clocks.advance(20)
    v.runtime._cancel_window_timer()
    # An early callback must distinguish invalidation from a still-live QR or
    # ordinary expiry; no 600-second timeout has occurred in either clock.
    await v.runtime._expire_screen()
    assert len(v.payloads) == 1 and not v.runtime.available and not v.runtime._admitting
    assert (await v.runtime.command(claim_message(v.payloads[0]["t"])))["error"] == "service_stopping"
    with pytest.raises(OwnershipError) as caught:
        v.result.ownership.factory_window_remaining(expected_epoch=EPOCH)
    assert caught.value.code == "qr_unavailable"
    assert v.runtime._window_task is None or v.runtime._window_task.done()


async def test_published_identity_never_reopens_a_factory_qr(factory_qr):
    v = factory_qr
    await v.runtime.start()
    await v.clocks.next_wait()
    operation = str(uuid4())
    v.result.prepared_identity.publish_initial(
        operation_id=operation, clock_result=ClockResult(operation, 1_792_152_000),
    )
    await expire(v)
    assert len(v.payloads) == 1
    assert not v.runtime.available and not v.runtime._admitting
    assert v.result.ownership._window_deadline is None


async def test_shutdown_cancels_waiting_timer_without_a_new_refresh(factory_qr):
    v = factory_qr
    await v.runtime.start()
    await v.clocks.next_wait()
    await v.runtime.stop()
    v.clocks.advance(2000)
    await asyncio.sleep(0)
    assert len(v.payloads) == 1 and v.runtime._window_task is None
    assert not v.runtime.available and not v.runtime.operations.tasks
    assert v.runtime.bluez.stopped and v.display.reservation is None


async def test_shutdown_during_refresh_drains_screen_before_releasing_it(factory_qr):
    v = factory_qr
    await v.runtime.start()
    await v.clocks.next_wait()
    v.display.entered.clear()
    v.display.block = threading.Event()
    v.clocks.advance(600)
    try:
        assert await asyncio.to_thread(v.display.entered.wait, 5)
        stopping = asyncio.create_task(v.runtime.stop())
        await asyncio.sleep(0)
        assert not stopping.done() and v.display.reservation is not None
        assert (await v.runtime.command(claim_message(v.payloads[0]["t"])))["error"] == "service_stopping"
    finally:
        v.display.block.set()
    await asyncio.wait_for(stopping, 5)
    assert len(v.payloads) == 2 and not v.runtime.operations.tasks
    assert v.runtime._window_task is None and not v.runtime.available
    assert v.runtime.bluez.stopped and v.display.reservation is None


@pytest.mark.parametrize("failure", ["display", "storage", "epoch"])
async def test_renewal_failure_closes_admission_and_does_not_retry_forever(
    factory_qr, monkeypatch, failure,
):
    v = factory_qr
    await v.runtime.start()
    await v.clocks.next_wait()
    token = v.payloads[0]["t"]
    with monkeypatch.context() as patch:
        if failure == "display":
            v.display.failed = True
        elif failure == "storage":
            def refused(**_):
                raise FactoryRecoveryRequired()
            patch.setattr(v.runtime.owners, "open_factory_window", refused)
        else:
            patch.setattr(v.runtime, "verify_epoch", lambda: "invalid-private-epoch")
        await expire(v)
        count = len(v.payloads)
        assert not v.runtime.available and not v.runtime._admitting
        assert (await v.runtime.command(claim_message(token)))["error"] == "service_stopping"
        assert not v.runtime.transport.sessions
        assert v.result.ownership._window_deadline is None
        v.clocks.advance(1800)
        await asyncio.sleep(0)
        assert len(v.payloads) == count
        assert v.runtime._window_task is None or v.runtime._window_task.done()
        assert not v.runtime.operations.tasks
    v.display.failed = False
    with pytest.raises(OwnershipError) as caught:
        v.runtime.owners.claim(token, str(uuid4()), "b" * 64, str(uuid4()), EPOCH)
    assert caught.value.code == "qr_unavailable"


async def test_refresh_that_exhausts_entire_ttl_never_advertises_or_retries(factory_qr):
    v = factory_qr
    v.durations.append(601)
    with pytest.raises((FactoryRecoveryRequired, OwnershipError)):
        await v.runtime.start()
    assert len(v.payloads) == 1
    assert not v.runtime.available and not v.runtime._admitting
    assert not v.runtime.bluez.started and v.runtime.bluez.stopped
    assert v.runtime._window_task is None and not v.runtime.operations.tasks
    assert v.display.reservation is None


async def test_slow_radio_registration_cannot_admit_a_qr_that_expired_after_show(factory_qr):
    v = factory_qr
    v.durations.append(599)

    class SlowBlueZ(FakeBlueZ):
        async def start(self):
            assert not v.runtime.available and not v.runtime._admitting
            await super().start()
            v.clocks.elapse(2)

    v.runtime.server_factory = SlowBlueZ
    with pytest.raises((FactoryRecoveryRequired, OwnershipError)):
        await v.runtime.start()
    assert len(v.payloads) == 1
    assert v.runtime.bluez.started and v.runtime.bluez.stopped
    assert not v.runtime.available and not v.runtime._admitting
    assert v.runtime._window_task is None and not v.runtime.operations.tasks
    assert v.result.ownership._window_deadline is None and v.display.reservation is None
