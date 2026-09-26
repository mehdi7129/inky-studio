"""Integration test for the WebSocket event broadcast."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from inky_web.api.ws import websocket_endpoint
from inky_web.events import EventBus


def test_ws_receives_queue_updated_on_upload(client, png_factory):
    with client.websocket_connect("/api/ws") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"

        client.post(
            "/api/queue",
            files={"file": ("ws.png", png_factory(800, 480, color=(9, 0, 0)), "image/png")},
        )

        events: list[dict] = []
        for _ in range(4):
            events.append(ws.receive_json())
            if any(e["type"] == "queue_updated" for e in events):
                break

        assert any(e["type"] == "queue_updated" for e in events)


async def test_idle_disconnect_releases_subscription():
    bus = EventBus()

    class DisconnectedWebSocket:
        app = SimpleNamespace(state=SimpleNamespace(bus=bus))
        cookies = {}

        async def accept(self):
            pass

        async def send_json(self, value):
            assert value["type"] == "hello"

        async def receive(self):
            return {"type": "websocket.disconnect", "code": 1000}

    await asyncio.wait_for(websocket_endpoint(DisconnectedWebSocket()), timeout=1)
    assert not bus._subscribers


async def test_repeated_cancellation_releases_subscription():
    bus = EventBus()
    receive_started = asyncio.Event()
    receive_cleanup_started = asyncio.Event()
    allow_receive_cleanup = asyncio.Event()

    class CancelledWebSocket:
        app = SimpleNamespace(state=SimpleNamespace(bus=bus))
        cookies = {}

        async def accept(self):
            pass

        async def send_json(self, value):
            assert value["type"] == "hello"

        async def receive(self):
            receive_started.set()
            try:
                await asyncio.Future()
            finally:
                # Keep the receive task alive until the endpoint is cancelled
                # a second time while awaiting its children's cleanup.
                receive_cleanup_started.set()
                await allow_receive_cleanup.wait()

    task = asyncio.create_task(websocket_endpoint(CancelledWebSocket()))
    try:
        await asyncio.wait_for(receive_started.wait(), timeout=1)
        task.cancel()
        await asyncio.wait_for(receive_cleanup_started.wait(), timeout=1)
        task.cancel()
        allow_receive_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert not bus._subscribers
    finally:
        allow_receive_cleanup.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
