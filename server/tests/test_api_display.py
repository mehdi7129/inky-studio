"""Integration tests for the display action endpoints (next/previous)."""
from __future__ import annotations


def _upload(client, png_factory, *, color):
    return client.post(
        "/api/queue",
        files={"file": (f"c{color[0]}.png", png_factory(800, 480, color=color), "image/png")},
    ).json()


def test_next_pops_from_queue_and_records_history(client, png_factory):
    _upload(client, png_factory, color=(1, 0, 0))
    _upload(client, png_factory, color=(2, 0, 0))
    assert len(client.get("/api/queue").json()) == 2

    response = client.post("/api/display/next")
    assert response.status_code == 202
    assert len(client.get("/api/queue").json()) == 1

    history = client.get("/api/history").json()
    assert len(history) == 1
    assert history[0]["source"] == "manual_next"


def test_next_with_empty_queue_and_no_history_is_noop(client):
    response = client.post("/api/display/next")
    assert response.status_code == 202
    assert client.get("/api/history").json() == []


def test_next_recycles_history_when_queue_empty(client, png_factory):
    _upload(client, png_factory, color=(3, 0, 0))
    _upload(client, png_factory, color=(4, 0, 0))
    client.post("/api/display/next")
    client.post("/api/display/next")
    assert client.get("/api/queue").json() == []

    # Now queue is empty but we have 2 in history — next should recycle
    client.post("/api/display/next")
    history = client.get("/api/history").json()
    assert len(history) == 3
    assert history[0]["source"] == "manual_next"


def test_previous_navigates_back(client, png_factory):
    p1 = _upload(client, png_factory, color=(5, 0, 0))["photo"]["id"]
    p2 = _upload(client, png_factory, color=(6, 0, 0))["photo"]["id"]
    client.post("/api/display/next")
    client.post("/api/display/next")
    # current = p2

    client.post("/api/display/previous")
    history = client.get("/api/history").json()
    assert history[0]["source"] == "manual_previous"
    assert history[0]["photo"]["id"] == p1


def test_previous_with_no_history_is_noop(client):
    response = client.post("/api/display/previous")
    assert response.status_code == 202
    assert client.get("/api/history").json() == []
