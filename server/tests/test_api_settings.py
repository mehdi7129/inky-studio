"""Integration tests for the settings endpoint."""
from __future__ import annotations


def test_default_settings(client):
    payload = client.get("/api/settings").json()
    assert payload["change_mode"] == "daily"
    assert payload["change_hour"] == 5
    assert "color_mode" not in payload  # colour modes were removed (auto per panel)


def test_partial_update(client):
    response = client.post("/api/settings", json={"change_mode": "manual"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["change_mode"] == "manual"
    assert payload["change_hour"] == 5

    # Confirms persistence across GET
    assert client.get("/api/settings").json()["change_mode"] == "manual"


def test_validation_rejects_bad_hour(client):
    assert client.post("/api/settings", json={"change_hour": 99}).status_code == 422
