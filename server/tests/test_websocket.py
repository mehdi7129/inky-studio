"""Integration test for the WebSocket event broadcast."""
from __future__ import annotations


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
