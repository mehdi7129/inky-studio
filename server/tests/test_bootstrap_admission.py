"""Real SQLite/PNG lifetimes; admission and radio are synthetic, not OS grants."""
from __future__ import annotations

import asyncio
import sqlite3
import threading
from contextlib import contextmanager

import pytest

from inky_web.provisioning import bootstrap_screen
from inky_web.provisioning.factory import FactoryRecoveryRequired, FactoryState

from .test_bootstrap_runtime import (
    EPOCH,
    FakeBlueZ,
    FakeDisplay,
    claim_message,
    start_with_token,
)
from .test_bootstrap_runtime import (
    factory as factory,
)
from .test_bootstrap_runtime import (
    inky_env as inky_env,
)
from .test_bootstrap_screen import PAYLOAD


class Admission:
    def __init__(self):
        self.invalid = threading.Event()

    def epoch(self):
        if self.invalid.is_set():
            raise RuntimeError("private OS graph detail")
        return EPOCH


@pytest.mark.parametrize("operation", ["reserve", "qr", "status"])
def test_invalid_admission_starts_no_screen_operation(tmp_path, operation):
    gate, display = Admission(), FakeDisplay()
    gate.invalid.set()
    target = bootstrap_screen.BootstrapScreen(display, tmp_path, verify_epoch=gate.epoch)
    with pytest.raises(FactoryRecoveryRequired) as error:
        if operation == "reserve":
            target.reserve()
        elif operation == "qr":
            target.show_qr(PAYLOAD)
        else:
            target.show_status(adopted=True)
    assert "private" not in str(error.value)
    assert display.reservation is None and not display.images and not list(tmp_path.iterdir())
    target.release()  # Cleanup must not ask for a new positive admission.


@pytest.mark.parametrize("operation", ["qr", "status"])
def test_invalidation_during_render_submits_no_spi(tmp_path, monkeypatch, operation):
    gate, display = Admission(), FakeDisplay()
    name = "render_qr" if operation == "qr" else "render_status"
    render = getattr(bootstrap_screen, name)

    def invalidate(*args, **kwargs):
        image = render(*args, **kwargs)
        gate.invalid.set()
        return image

    monkeypatch.setattr(bootstrap_screen, name, invalidate)
    target = bootstrap_screen.BootstrapScreen(display, tmp_path, verify_epoch=gate.epoch)
    with pytest.raises(FactoryRecoveryRequired):
        if operation == "qr":
            target.show_qr(PAYLOAD)
        else:
            target.show_status(adopted=True)
    assert not display.images and not list(tmp_path.iterdir())
    target.release()
    assert display.reservation is None


@pytest.mark.parametrize("epoch", [None, 0, "bad", "a" * 63])
def test_malformed_checked_epoch_never_submits_screen(tmp_path, epoch):
    display = FakeDisplay()
    target = bootstrap_screen.BootstrapScreen(display, tmp_path, verify_epoch=lambda: epoch)
    with pytest.raises(FactoryRecoveryRequired):
        target.show_qr(PAYLOAD)
    assert not display.images and display.reservation is None


async def test_invalidation_after_qr_refresh_blocks_bluez(factory, monkeypatch):
    runtime, display = factory[-1], factory[-2]
    gate = Admission()
    runtime.verify_epoch = gate.epoch
    real_refresh = display.display_image

    def refresh_then_invalidate(*args, **kwargs):
        real_refresh(*args, **kwargs)
        gate.invalid.set()

    monkeypatch.setattr(display, "display_image", refresh_then_invalidate)
    with pytest.raises(FactoryRecoveryRequired):
        await runtime.start()
    assert len(display.images) == 1
    assert not runtime.bluez.started and runtime.bluez.stopped
    assert not runtime.available and not runtime.operations.tasks
    assert runtime.owners._closed and display.reservation is None


async def test_invalidation_during_bluez_registration_drains_before_unregister(factory):
    runtime, display = factory[-1], factory[-2]
    gate, entered, release, events = Admission(), asyncio.Event(), asyncio.Event(), []
    runtime.verify_epoch = gate.epoch

    class Registration(FakeBlueZ):
        async def start(self):
            events.append("register-start")
            entered.set()
            await release.wait()
            self.started = True
            events.append("register-complete")

        async def stop(self):
            assert self.started
            events.append("unregister")
            await super().stop()

    runtime.server_factory = Registration
    startup = asyncio.create_task(runtime.start())
    await asyncio.wait_for(entered.wait(), 3)
    gate.invalid.set()
    await asyncio.sleep(0)
    assert not startup.done() and not runtime.bluez.stopped
    assert display.reservation is not None and not runtime.owners._closed
    release.set()
    with pytest.raises(FactoryRecoveryRequired):
        await startup
    assert events == ["register-start", "register-complete", "unregister"]
    assert not runtime.available and not runtime.operations.tasks
    assert display.reservation is None and runtime.owners._closed


async def test_invalid_admission_refuses_claim_before_ledger_effect(factory, monkeypatch):
    gate, runtime = Admission(), factory[-1]
    runtime.verify_epoch = gate.epoch
    runtime.owners._credential_epoch = gate.epoch
    token = await start_with_token(factory, monkeypatch)
    gate.invalid.set()
    reply = await runtime.command(claim_message(token))
    assert reply["error"] == "recovery_required" and "private" not in str(reply)
    assert not runtime.available
    assert runtime.owners.factory_status().state == FactoryState.FACTORY
    await runtime.stop()


async def test_invalid_after_durable_claim_closes_admission_without_new_status_refresh(factory, monkeypatch):
    gate, runtime, display = Admission(), factory[-1], factory[-2]
    runtime.verify_epoch = gate.epoch
    runtime.owners._credential_epoch = gate.epoch
    token = await start_with_token(factory, monkeypatch)
    real_claim = runtime.owners.claim

    def committed(*args, **kwargs):
        result = real_claim(*args, **kwargs)
        gate.invalid.set()
        return result

    monkeypatch.setattr(runtime.owners, "claim", committed)
    claim = claim_message(token)
    reply = await runtime.command(claim)
    assert reply["error"] == "recovery_required" and not runtime.available
    assert len(display.images) == 1  # Initial QR only; no newly admitted status SPI.
    state = runtime.owners.factory_status()
    assert state.state == FactoryState.ADOPTED and state.first_owner_id == claim["owner_id"]
    await runtime.stop()
    with sqlite3.connect(factory[0] / "ownership.sqlite3") as database:
        assert database.execute("SELECT claim_request_id FROM owners").fetchone()[0] == claim["id"]


async def test_invalid_graph_and_repeated_stop_cancellation_drain_real_open_claim_transaction(factory, monkeypatch):
    gate, runtime, display = Admission(), factory[-1], factory[-2]
    runtime.verify_epoch = gate.epoch
    runtime.owners._credential_epoch = gate.epoch
    token = await start_with_token(factory, monkeypatch)
    claim = claim_message(token)
    entered, release = threading.Event(), threading.Event()
    real_transaction, held = runtime.owners._transaction, [False]

    @contextmanager
    def before_commit():
        with real_transaction() as database:
            yield database
            row = database.execute("SELECT owner_id FROM owners WHERE owner_id = ?",
                                   (claim["owner_id"],)).fetchone()
            if row is not None and not held[0]:
                held[0] = True
                entered.set()  # INSERTs have run on this real connection; COMMIT has not.
                assert release.wait(5)

    monkeypatch.setattr(runtime.owners, "_transaction", before_commit)
    caller = asyncio.create_task(runtime.command(claim))
    assert await asyncio.to_thread(entered.wait, 3)
    gate.invalid.set()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    stopping = asyncio.create_task(runtime.stop())
    await asyncio.sleep(0)
    for _ in range(2):
        stopping.cancel()
        await asyncio.sleep(0)
    assert not stopping.done() and not runtime.owners._closed
    assert runtime.operations.tasks and display.reservation is not None
    assert (await runtime.command(claim))["error"] == "service_stopping"
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await stopping
    assert runtime.owners._closed and display.reservation is None and not runtime.operations.tasks
    with sqlite3.connect(factory[0] / "ownership.sqlite3") as database:
        state = database.execute("SELECT state, first_owner_id FROM factory_initialization").fetchone()
        assert state == ("adopted", claim["owner_id"])
        assert database.execute("SELECT claim_request_id FROM owners").fetchone()[0] == claim["id"]


async def test_invalid_graph_with_spi_admitted_finishes_refresh_before_release(factory, monkeypatch):
    gate, runtime, display = Admission(), factory[-1], factory[-2]
    runtime.verify_epoch = gate.epoch
    runtime.owners._credential_epoch = gate.epoch
    token = await start_with_token(factory, monkeypatch)
    display.entered.clear()
    display.block = threading.Event()
    caller = asyncio.create_task(runtime.command(claim_message(token)))
    assert await asyncio.to_thread(display.entered.wait, 3)
    gate.invalid.set()
    stopping = asyncio.create_task(runtime.stop())
    await asyncio.sleep(0)
    for _ in range(2):
        stopping.cancel()
        await asyncio.sleep(0)
    assert not stopping.done() and display.active == 1 and display.reservation is not None
    assert not runtime.owners._closed
    display.block.set()
    with pytest.raises(asyncio.CancelledError):
        await stopping
    await caller
    assert display.active == 0 and len(display.images) == 2 and display.reservation is None
    assert runtime.owners._closed and not runtime.operations.tasks
