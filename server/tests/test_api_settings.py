"""Integration tests for the settings endpoint."""
from __future__ import annotations


def test_default_settings(client):
    payload = client.get("/api/settings").json()
    assert payload["change_mode"] == "daily"
    assert payload["change_hour"] == 5
    assert payload["saturation"] == 1.0  # 1.0 = faithful (panel's measured palette)
    assert "color_mode" not in payload  # colour modes were removed (auto per panel)


def test_update_saturation(client):
    # 0..2: <=1 drives Pimoroni saturation, >1 adds a source vibrance boost.
    for value in (0.8, 1.5, 2.0):
        payload = client.post("/api/settings", json={"saturation": value}).json()
        assert payload["saturation"] == value
    assert client.get("/api/settings").json()["saturation"] == 2.0


def test_validation_rejects_bad_saturation(client):
    assert client.post("/api/settings", json={"saturation": 2.5}).status_code == 422
    assert client.post("/api/settings", json={"saturation": -0.1}).status_code == 422


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
