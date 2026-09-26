"""Event delivery stays on each subscriber's asyncio event loop."""
from __future__ import annotations

import asyncio

from inky_web.events import EventBus


async def test_worker_thread_wakes_waiting_subscriber():
    loop = asyncio.get_running_loop()
    old_debug = loop.get_debug()
    loop.set_debug(True)
    bus = EventBus()
    queue = bus.subscribe()
    try:
        received = asyncio.create_task(queue.get())
        await asyncio.sleep(0)
        await asyncio.to_thread(bus.broadcast, "display_changed", {"photo_id": "example"})
        event = await asyncio.wait_for(received, timeout=1)
        assert event == {"type": "display_changed", "payload": {"photo_id": "example"}}
    finally:
        bus.unsubscribe(queue)
        loop.set_debug(old_debug)


async def test_unsubscribe_drops_pending_worker_delivery():
    bus = EventBus()
    queue = bus.subscribe()
    bus.unsubscribe(queue)
    await asyncio.to_thread(bus.broadcast, "queue_updated")
    assert queue.empty()


async def test_slow_subscriber_cannot_block_other_subscribers():
    bus = EventBus(queue_maxsize=1)
    slow = bus.subscribe()
    fast = bus.subscribe()
    bus.broadcast("queue_updated", {"sequence": 1})
    await fast.get()
    bus.broadcast("queue_updated", {"sequence": 2})
    assert (await fast.get())["payload"]["sequence"] == 2
    assert slow.qsize() == 1
