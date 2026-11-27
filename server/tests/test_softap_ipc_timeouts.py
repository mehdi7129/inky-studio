"""Virtual deadlines around real Unix requests, replies and peer-proof drains."""
import asyncio

import pytest

from inky_web.provisioning import system_setup_ipc as ipc
from tests.test_softap_ipc import access_point
from tests.test_system_setup_ipc import BOOT, applied, observed, owner, proof, snapshot, uid
from tests.test_system_setup_ipc import unix_service as unix_service


class VirtualClock:
    def __init__(self, loop):
        self.now = loop.time()

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def arguments(operation, binding):
    if operation == "setup.apply":
        return {"operation_id": uid(), "supersedes_operation_id": None,
                "challenge_id": uid(), "nonce": "a" * 64,
                "utc_seconds": 1790000000, "country": "FR"}
    return {"workflow": ipc._workflow(binding)}


def response(operation, request, binding):
    if operation == "setup.apply":
        return applied(request, observed(binding))
    if operation == "setup.inspect":
        return snapshot(ipc._workflow(binding))
    result = access_point()
    if operation == "setup.ap.stop":
        result["state"] = "stopped"
    return result


@pytest.mark.parametrize("operation,delay", [
    ("setup.ap.start", 20), ("setup.ap.start", 150), ("setup.ap.start", 179),
    ("setup.ap.stop", 20), ("setup.ap.stop", 59),
    ("setup.ap.status", 20), ("setup.ap.status", 59),
    ("setup.apply", 50), ("setup.inspect", 14),
])
async def test_response_after_virtual_delay_is_still_valid(unix_service, monkeypatch, operation, delay):
    binding, events = owner(), []
    received, release = asyncio.Event(), asyncio.Event()
    async def serve(request):
        if request["op"] == "setup.open":
            return {"binding": observed(binding)}
        received.set()
        await release.wait()
        return response(operation, request, binding)
    path, requests = await unix_service(serve)
    channel = await ipc.SystemSetupClient(path, peer_guard=proof(events), boot_id=lambda: BOOT).open(binding)
    try:
        loop = asyncio.get_running_loop()
        clock = VirtualClock(loop)
        with monkeypatch.context() as patch:
            patch.setattr(loop, "time", clock)
            pending = asyncio.create_task(channel.call(operation, **arguments(operation, binding)))
            await received.wait()
            clock.advance(delay)
            # Let actual expired timer handles run before delivering any bytes.
            # With the old 15 second AP budget these requests close here.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert not pending.done()
            release.set()
            result = await pending
        assert len(requests) == 2 and not channel.closed
        assert events == ["entered"]
        if operation.startswith("setup.ap."):
            assert result["boot_id"] == BOOT and result["port"] == 9443
        elif operation == "setup.apply":
            assert result["receipt"]["clock"]["utc_seconds"] == 1790000000
        else:
            assert result["state"] == "not_started"
    finally:
        release.set()
        await channel.drain()
    assert events == ["entered", "released"]


@pytest.mark.parametrize("operation,delay", [
    ("setup.ap.start", 181), ("setup.ap.stop", 61), ("setup.ap.status", 61),
    ("setup.apply", 56), ("setup.inspect", 16),
])
async def test_virtual_deadline_expiry_closes_channel_and_keeps_proof_owned(
        unix_service, monkeypatch, operation, delay):
    binding, events = owner(), []
    received, release = asyncio.Event(), asyncio.Event()
    async def serve(request):
        if request["op"] == "setup.open":
            return {"binding": observed(binding)}
        received.set()
        await release.wait()
        return response(operation, request, binding)
    path, requests = await unix_service(serve)
    channel = await ipc.SystemSetupClient(path, peer_guard=proof(events), boot_id=lambda: BOOT).open(binding)
    try:
        loop = asyncio.get_running_loop()
        clock = VirtualClock(loop)
        with monkeypatch.context() as patch:
            patch.setattr(loop, "time", clock)
            pending = asyncio.create_task(channel.call(operation, **arguments(operation, binding)))
            await received.wait()
            clock.advance(delay)
            with pytest.raises(ipc.SetupUnavailable, match="^unavailable$"):
                await pending
        assert len(requests) == 2 and channel.closed
        assert events == ["entered"]  # proof remains held until explicit drain
        with pytest.raises(ipc.SetupUnavailable, match="session_closed"):
            await channel.call(operation, **arguments(operation, binding))
    finally:
        release.set()
        await channel.drain()
    assert events == ["entered", "released"]
