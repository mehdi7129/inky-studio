"""Integration tests for the queue endpoints via TestClient."""
from __future__ import annotations


def _upload(client, png_factory, *, color, name="x.png"):
    return client.post(
        "/api/queue",
        files={"file": (name, png_factory(800, 480, color=color), "image/png")},
    )


def test_upload_creates_photo_and_queue_entry(client, png_factory):
    response = _upload(client, png_factory, color=(1, 2, 3))
    assert response.status_code == 201
    payload = response.json()
    assert payload["already_existed"] is False
    assert payload["photo"]["width"] == 800
    assert payload["queue_entry"]["photo"]["id"] == payload["photo"]["id"]


def test_upload_rejects_wrong_size(client, png_factory):
    response = client.post(
        "/api/queue",
        files={"file": ("bad.png", png_factory(640, 480, color=(5, 5, 5)), "image/png")},
    )
    assert response.status_code == 400
    assert "does not match display" in response.json()["detail"]


def test_upload_dedupes_identical_payload(client, png_factory):
    first = _upload(client, png_factory, color=(7, 7, 7))
    second = _upload(client, png_factory, color=(7, 7, 7), name="dup.png")
    assert second.status_code == 201
    assert second.json()["already_existed"] is True
    assert first.json()["photo"]["id"] == second.json()["photo"]["id"]


def test_list_returns_in_order(client, png_factory):
    _upload(client, png_factory, color=(10, 0, 0))
    _upload(client, png_factory, color=(20, 0, 0))
    listing = client.get("/api/queue").json()
    assert len(listing) == 2
    assert listing[0]["position"] < listing[1]["position"]


def test_delete_removes_entry(client, png_factory):
    upload = _upload(client, png_factory, color=(30, 0, 0)).json()
    photo_id = upload["photo"]["id"]
    response = client.delete(f"/api/queue/{photo_id}")
    assert response.status_code == 204
    assert client.get("/api/queue").json() == []


def test_delete_unknown_returns_404(client):
    assert client.delete("/api/queue/unknown-id").status_code == 404


def test_reorder_changes_positions(client, png_factory):
    p1 = _upload(client, png_factory, color=(40, 0, 0)).json()["photo"]["id"]
    p2 = _upload(client, png_factory, color=(50, 0, 0)).json()["photo"]["id"]
    p3 = _upload(client, png_factory, color=(60, 0, 0)).json()["photo"]["id"]

    response = client.post("/api/queue/reorder", json={"photo_ids": [p3, p1, p2]})
    assert response.status_code == 200
    order = [e["photo"]["id"] for e in response.json()]
    assert order == [p3, p1, p2]
