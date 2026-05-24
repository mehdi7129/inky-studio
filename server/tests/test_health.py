"""Smoke test — confirms FastAPI starts and the mock display responds."""
from __future__ import annotations

from fastapi.testclient import TestClient

from inky_web.main import app


def test_health_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


def test_display_state_returns_mock_off_pi() -> None:
    with TestClient(app) as client:
        response = client.get("/api/display")
        assert response.status_code == 200
        payload = response.json()
        assert payload["is_mock"] is True
        assert payload["width"] > 0
        assert payload["height"] > 0
