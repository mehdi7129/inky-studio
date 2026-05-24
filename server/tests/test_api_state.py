"""Integration tests for the /api/state aggregate endpoint."""
from __future__ import annotations


def test_state_empty(client):
    state = client.get("/api/state").json()
    assert state["display"]["is_mock"] is True
    assert state["display"]["width"] == 800
    assert state["display"]["height"] == 480
    assert state["queue_count"] == 0
    assert state["current"] is None


def test_state_reflects_queue_and_current(client, png_factory):
    upload_payload = client.post(
        "/api/queue",
        files={"file": ("a.png", png_factory(800, 480, color=(8, 0, 0)), "image/png")},
    ).json()
    assert client.get("/api/state").json()["queue_count"] == 1

    client.post("/api/display/next")
    state = client.get("/api/state").json()
    assert state["queue_count"] == 0
    assert state["current"]["photo"]["id"] == upload_payload["photo"]["id"]
