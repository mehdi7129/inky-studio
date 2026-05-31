"""Tests for the /api/system/update endpoints (no real update is performed)."""
from __future__ import annotations

from inky_web.services import updater


def test_get_update_status(client, monkeypatch):
    monkeypatch.setattr(
        updater,
        "get_status",
        lambda: {"current": "0.2.0", "latest": "0.3.0", "update_available": True},
    )
    resp = client.get("/api/system/update")
    assert resp.status_code == 200
    assert resp.json() == {"current": "0.2.0", "latest": "0.3.0", "update_available": True}


def test_post_update_starts(client, monkeypatch):
    started = {"called": False}

    async def fake_perform(emit, **kwargs):
        started["called"] = True

    monkeypatch.setattr(updater, "perform_update", fake_perform)
    client.app.state.updating = False
    resp = client.post("/api/system/update")
    assert resp.status_code == 202
    assert resp.json() == {"started": True}


def test_post_update_conflict_when_already_running(client):
    client.app.state.updating = True
    try:
        resp = client.post("/api/system/update")
        assert resp.status_code == 409
    finally:
        client.app.state.updating = False
