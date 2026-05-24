"""Integration tests for the settings endpoint."""
from __future__ import annotations


def test_default_settings(client):
    payload = client.get("/api/settings").json()
    assert payload["color_mode"] == "spectra_palette"
    assert payload["change_mode"] == "daily"
    assert payload["change_hour"] == 5


def test_partial_update(client):
    response = client.post("/api/settings", json={"color_mode": "warmth_boost"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["color_mode"] == "warmth_boost"
    assert payload["change_hour"] == 5

    # Confirms persistence across GET
    assert client.get("/api/settings").json()["color_mode"] == "warmth_boost"


def test_validation_rejects_bad_hour(client):
    assert client.post("/api/settings", json={"change_hour": 99}).status_code == 422
