"""File retrieval, including missing metadata and storage."""
from __future__ import annotations

from inky_web.services.photos import path_for


def test_uploaded_photo_is_served_unchanged(client, png_factory):
    payload = png_factory(800, 480)
    uploaded = client.post("/api/queue", files={"file": ("été.png", payload, "image/png")})
    photo_id = uploaded.json()["photo"]["id"]
    response = client.get(f"/api/photos/{photo_id}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == payload


def test_unknown_photo_returns_404(client):
    assert client.get("/api/photos/unknown-photo").status_code == 404


def test_missing_photo_file_returns_410(client, png_factory):
    uploaded = client.post("/api/queue", files={"file": ("gone.png", png_factory(), "image/png")})
    photo_id = uploaded.json()["photo"]["id"]
    path_for(photo_id).unlink()
    assert client.get(f"/api/photos/{photo_id}").status_code == 410
