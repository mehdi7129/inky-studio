"""Integration test for the WebSocket event broadcast."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

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
