"""Real durable store and thread/SPI lifetime; fake OS/radio/display only."""
import asyncio
import copy
import json
import threading
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image

from inky_web.provisioning.bootstrap_identity import PREPARED_IDENTITY_FILENAME, ClockResult
from inky_web.provisioning.bootstrap_runtime import BootstrapRuntime
from inky_web.provisioning.factory import FactoryRecoveryRequired, FactoryState
from inky_web.provisioning.first_boot import FirstBootCoordinator

EPOCH = "e" * 64


@pytest.fixture(autouse=True)
def inky_env(tmp_path, monkeypatch):
    """Do not initialize a normal database or turn application auth off."""
    monkeypatch.setenv("INKY_STUDIO_DATA_DIR", str(tmp_path / "normal-state"))
    monkeypatch.delenv("INKY_STUDIO_DISABLE_AUTH", raising=False)
    from inky_web import auth, db
    from inky_web.provisioning import identity

    def forbidden(*_args, **_kwargs):
        pytest.fail("Bootstrap admitted normal application state")

    monkeypatch.setattr(db, "init_db", forbidden)
    monkeypatch.setattr(db, "data_dir", forbidden)
    monkeypatch.setattr(auth, "load_or_create_credentials", forbidden)
    monkeypatch.setattr(identity, "load_or_create_identity", forbidden)
    yield tmp_path
    assert not (tmp_path / "normal-state").exists()


class FakeOS:
    def __init__(self):
        self.state = {"status": "authorized"}
        self.receipt = {"receipt_id": str(uuid4()), "digest": "d" * 64}

    def inspect_initialization(self):
        return copy.deepcopy(self.state)

    def begin_initialization(self, intent):
        status = "newly_consumed" if self.state["status"] == "authorized" else "already_consumed"
        self.state = {"status": "consumed", "intent": intent, "receipt": self.receipt.copy()}
        return {**copy.deepcopy(self.state), "status": status}


class FakeDisplay:
    def __init__(self):
        self.spec = SimpleNamespace(width=800, height=480)
        self.closing = False
        self.reservation = None
        self.images = []
        self.lock = threading.RLock()
        self.block = None
        self.entered = threading.Event()
        self.failed = False
        self.active = 0
        self.max_active = 0

    @contextmanager
    def operation(self):
        with self.lock:
            yield

    def reserve(self, value):
        assert self.reservation in (None, value)
        self.reservation = value

    def release(self, value):
        with self.lock:
            assert self.active == 0
            if self.reservation == value:
                self.reservation = None

    def display_image(self, path, **_):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.entered.set()
        try:
            if self.block:
                assert self.block.wait(10)
            if self.failed:
                raise OSError("private display detail")
            with Image.open(path) as image:
                self.images.append(image.copy())
        finally:
            self.active -= 1


class FakeBlueZ:
    def __init__(self, transport, identity, **_):
        self.transport, self.identity = transport, identity
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.transport.close()
        self.stopped = True


@pytest.fixture
def factory(tmp_path):
    directory, os_adapter, epoch = tmp_path / "private", FakeOS(), [EPOCH]
    coordinator = FirstBootCoordinator(directory, os_adapter, lambda: epoch[0], clock=lambda: 0.0)
    result = coordinator.initialize()
    display = FakeDisplay()
    runtime = BootstrapRuntime(result, lambda: epoch[0], display, directory, server_factory=FakeBlueZ)
    return directory, os_adapter, epoch, coordinator, result, display, runtime


def claim_message(token, *, owner=None, request=None):
    return {"v": 1, "id": request or str(uuid4()), "op": "bootstrap.claim",
            "owner_id": owner or str(uuid4()), "owner_token": "b" * 64, "claim_token": token}


def status_message(claim, **changes):
    return {"v": 1, "id": str(uuid4()), "op": "bootstrap.status",
            "owner_id": claim["owner_id"], "owner_token": claim["owner_token"],
            "claim_request_id": claim["id"], **changes}


async def start_with_token(factory, monkeypatch):
    runtime = factory[-1]
    payloads = []
    original = runtime.screen.show_qr

    def observe(payload):
        payloads.append(json.loads(payload))
        original(payload)

    monkeypatch.setattr(runtime.screen, "show_qr", observe)
    await runtime.start()
    return payloads[0]["t"]


async def test_claim_replay_and_status_use_only_durable_store(factory, monkeypatch):
    directory, _, _, _, result, display, runtime = factory
    token = await start_with_token(factory, monkeypatch)
    message = claim_message(token)
    reply = await runtime.command(message)
    assert reply == {"v": 1, "id": message["id"], "ok": True, "result": {
        "frame_id": result.prepared_identity.frame_id, "owner_id": message["owner_id"],
        "claim_request_id": message["id"], "factory_state": "adopted", "next_step": "system_setup",
    }}
    assert result.ownership.factory_status().state == FactoryState.ADOPTED
    assert await runtime.command(message) == reply
    status = status_message(message)
    recovered = await runtime.command(status)
    assert recovered["id"] == status["id"] and recovered["result"] == reply["result"]
    assert display.max_active == 1 and not (directory / "identity.json").exists()
    assert not list(directory.glob(".adoption*"))
    await runtime.stop()
    assert display.reservation is None and not runtime.operations.tasks


async def test_two_phones_select_one_winner_and_never_gain_phase_b(factory, monkeypatch):
    token = await start_with_token(factory, monkeypatch)
    runtime = factory[-1]
    first, second = claim_message(token), claim_message(token)
    replies = await asyncio.gather(runtime.command(first), runtime.command(second))
    assert sum(reply["ok"] for reply in replies) == 1
    loser = second if replies[0]["ok"] else first
    assert (await runtime.command(status_message(loser)))["error"] == "unauthorized"
    for op in ("claim", "status", "wifi.scan", "wifi.begin", "bootstrap.time", "owner.revoke"):
        assert (await runtime.command({**first, "op": op}))["error"] == "invalid_request"
    await runtime.stop()


async def test_status_authenticates_before_receipt_existence(factory, monkeypatch):
    token = await start_with_token(factory, monkeypatch)
    runtime = factory[-1]
    claim = claim_message(token)
    await runtime.command(claim)
    wrong_id = status_message(claim, claim_request_id=str(uuid4()))
    assert (await runtime.command(wrong_id))["error"] == "request_not_found"
    assert (await runtime.command({**wrong_id, "owner_token": "a" * 64}))["error"] == "unauthorized"
    assert (await runtime.command({**claim, "claim_token": "c" * 64}))["error"] == "request_conflict"
    await runtime.stop()


async def test_reboot_adopted_reuses_key_receipt_and_opens_no_qr(factory, monkeypatch):
    directory, _, epoch, coordinator, result, display, runtime = factory
    token = await start_with_token(factory, monkeypatch)
    claim = claim_message(token)
    reply = await runtime.command(claim)
    key = result.prepared_identity.binding
    await runtime.stop()
    reopened = coordinator.initialize()
    assert reopened.prepared_identity.binding == key
    second = BootstrapRuntime(reopened, lambda: epoch[0], display, directory, server_factory=FakeBlueZ)
    monkeypatch.setattr(second.owners, "open_factory_window", lambda **_: pytest.fail("Adopted reopens no QR"))
    await second.start()
    assert (await second.command(status_message(claim)))["result"] == reply["result"]
    await second.stop()


async def test_reboot_unclaimed_invalidates_old_qr(factory, monkeypatch):
    directory, _, epoch, coordinator, _, display, runtime = factory
    token = await start_with_token(factory, monkeypatch)
    await runtime.stop()
    reopened = coordinator.initialize()
    second = BootstrapRuntime(reopened, lambda: epoch[0], display, directory, server_factory=FakeBlueZ)
    await second.start()
    assert (await second.command(claim_message(token)))["error"] == "unauthorized"
    await second.stop()


async def test_display_failure_after_commit_keeps_owner_for_recovery(factory, monkeypatch):
    directory, _, epoch, coordinator, _, display, runtime = factory
    token = await start_with_token(factory, monkeypatch)
    claim = claim_message(token)
    display.failed = True
    reply = await runtime.command(claim)
    assert reply["error"] == "unavailable" and not runtime.available
    assert runtime.owners.factory_status().state == FactoryState.ADOPTED
    await runtime.stop()
    display.failed = False
    second = BootstrapRuntime(coordinator.initialize(), lambda: epoch[0], display, directory,
                              server_factory=FakeBlueZ)
    await second.start()
    assert (await second.command(status_message(claim)))["ok"]
    await second.stop()


async def test_display_failure_before_advertising_closes_window(factory, monkeypatch):
    *_, result, display, runtime = factory
    display.failed = True
    with pytest.raises(OSError, match="private display detail"):
        await runtime.start()
    assert not runtime.available and not runtime.bluez.started
    assert display.reservation is None and not runtime.operations.tasks
    assert result.ownership._closed


async def test_cancelled_claim_and_shutdown_drain_real_sqlite_work(factory, monkeypatch):
    token = await start_with_token(factory, monkeypatch)
    runtime, display = factory[-1], factory[-2]
    claim = claim_message(token)
    entered, release = threading.Event(), threading.Event()
    original = runtime.owners.claim

    def blocking(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)

    monkeypatch.setattr(runtime.owners, "claim", blocking)
    caller = asyncio.create_task(runtime.command(claim))
    assert await asyncio.to_thread(entered.wait, 2)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    stopping = asyncio.create_task(runtime.stop())
    await asyncio.sleep(0.02)
    assert not stopping.done() and display.reservation is not None
    assert runtime.operations.tasks and not runtime.owners._closed
    assert (await runtime.command(claim))["error"] == "service_stopping"
    release.set()
    await stopping
    assert not runtime.operations.tasks and display.reservation is None
    reopened = factory[3].initialize()
    assert reopened.ownership.status(claim["owner_id"], claim["owner_token"], claim["id"]).claimed
    reopened.ownership.close()


async def test_cancelled_stop_cannot_release_spi_before_refresh_completes(factory, monkeypatch):
    token = await start_with_token(factory, monkeypatch)
    runtime, display = factory[-1], factory[-2]
    display.entered.clear()
    display.block = threading.Event()
    caller = asyncio.create_task(runtime.command(claim_message(token)))
    assert await asyncio.to_thread(display.entered.wait, 2)
    stopping = asyncio.create_task(runtime.stop())
    stopping.cancel()
    # Cancellation before the coroutine starts does not invoke stop; repeat
    # with one event-loop turn so the test exercises its cancellation guard.
    with pytest.raises(asyncio.CancelledError):
        await stopping
    stopping = asyncio.create_task(runtime.stop())
    await asyncio.sleep(0)
    stopping.cancel()
    await asyncio.sleep(0.02)
    assert not stopping.done() and display.reservation is not None and display.active == 1
    display.block.set()
    with pytest.raises(asyncio.CancelledError):
        await stopping
    await caller
    assert display.reservation is None and display.active == 0 and not runtime.operations.tasks


async def test_epoch_change_inside_claim_and_corrupt_binding_fail_closed(factory, monkeypatch):
    token = await start_with_token(factory, monkeypatch)
    runtime, epoch = factory[-1], factory[2]
    original = runtime.owners.claim

    def change_epoch(*args):
        epoch[0] = "f" * 64
        return original(*args)

    monkeypatch.setattr(runtime.owners, "claim", change_epoch)
    assert (await runtime.command(claim_message(token)))["error"] == "epoch_changed"
    (factory[0] / PREPARED_IDENTITY_FILENAME).write_text("{}")
    reply = await runtime.command(claim_message(token))
    assert reply["error"] == "recovery_required" and not runtime.available
    await runtime.stop()


async def test_published_normal_identity_refuses_bootstrap_restart(factory):
    result, runtime = factory[4], factory[-1]
    operation = str(uuid4())
    result.prepared_identity.publish_initial(operation_id=operation,
        clock_result=ClockResult(operation, 1791712800))
    with pytest.raises(FactoryRecoveryRequired):
        await runtime.start()
    assert runtime.bluez is None and not runtime.available


async def test_disconnected_callers_do_not_free_global_admission_slots(factory, monkeypatch):
    token = await start_with_token(factory, monkeypatch)
    runtime = factory[-1]
    entered, release = threading.Event(), threading.Event()
    original = runtime.owners.claim
    calls = []

    def blocking(*args):
        calls.append(args)
        entered.set()
        assert release.wait(10)
        return original(*args)

    monkeypatch.setattr(runtime.owners, "claim", blocking)
    first = asyncio.create_task(runtime.command(claim_message(token)))
    assert await asyncio.to_thread(entered.wait, 2)
    second = asyncio.create_task(runtime.command(claim_message(token)))
    await asyncio.sleep(0)
    assert len(runtime.operations.tasks) == 2
    first.cancel()
    second.cancel()
    await asyncio.gather(first, second, return_exceptions=True)
    assert (await runtime.command(claim_message(token)))["error"] == "unavailable"
    assert len(calls) == 1 and len(runtime.operations.tasks) == 2
    release.set()
    await runtime.stop()
    assert len(calls) == 2 and not runtime.operations.tasks


async def test_stop_during_bluez_registration_unregisters_after_start(factory):
    runtime = factory[-1]
    entered, release = asyncio.Event(), asyncio.Event()
    events = []

    class BlockingBlueZ(FakeBlueZ):
        async def start(self):
            entered.set()
            await release.wait()
            events.append("registered")

        async def stop(self):
            events.append("unregistered")
            await super().stop()

    runtime.server_factory = BlockingBlueZ
    startup = asyncio.create_task(runtime.start())
    await entered.wait()
    stopping = asyncio.create_task(runtime.stop())
    await asyncio.sleep(0)
    assert not stopping.done() and not runtime.available
    release.set()
    await asyncio.gather(startup, stopping)
    assert events == ["registered", "unregistered"]
    assert not runtime.available and not runtime._admitting
    assert runtime.display.reservation is None


async def test_bad_verified_epoch_is_recovery_not_client_error(factory, monkeypatch):
    token = await start_with_token(factory, monkeypatch)
    runtime = factory[-1]
    runtime.verify_epoch = lambda: "private invalid credentials"
    reply = await runtime.command(claim_message(token))
    assert reply["error"] == "recovery_required" and not runtime.available
    assert "private" not in json.dumps(reply)
    await runtime.stop()


async def test_expired_window_cleanup_does_not_reopen_qr(factory, monkeypatch):
    token = await start_with_token(factory, monkeypatch)
    runtime = factory[-1]
    runtime._cancel_window_timer()
    await runtime._expire_window(runtime.monotonic() - 1)
    monkeypatch.setattr(runtime.owners, "open_factory_window", lambda **_: pytest.fail("Expiry must not reopen QR"))
    assert (await runtime.command(claim_message(token)))["error"] == "qr_unavailable"
    await runtime.stop()


@pytest.mark.parametrize("error_type", [FactoryRecoveryRequired, OSError])
async def test_window_cleanup_failure_closes_admission_immediately(factory, monkeypatch, error_type):
    token = await start_with_token(factory, monkeypatch)
    runtime = factory[-1]
    runtime._cancel_window_timer()
    runtime.transport.write("/synthetic/one", b"\0" + b"s" * 16)
    assert runtime.transport.sessions

    def corrupt_window():
        raise error_type()

    monkeypatch.setattr(runtime.owners, "close_window", corrupt_window)
    await runtime._expire_screen()
    assert not runtime.available and not runtime._admitting
    assert not runtime.transport.sessions
    assert (await runtime.command(claim_message(token)))["error"] == "service_stopping"
    # Shutdown still releases screen ownership if the corrupt durable store
    # cannot close; its recovery error remains visible to the lifecycle owner.
    with pytest.raises(error_type):
        await runtime.stop()
    assert runtime.bluez.stopped and runtime.display.reservation is None
