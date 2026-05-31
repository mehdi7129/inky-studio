"""Integration tests for deleting history entries."""
from __future__ import annotations


def _seed(png_factory, color):
    from inky_web.services import history, photos

    p, _ = photos.save(
        content=png_factory(800, 480, color=color),
        original_filename=f"h-{color[0]}.png",
        expected_size=(800, 480),
    )
    return history.record(p.id, source="auto")


def test_delete_single_entry(client, png_factory):
    e1 = _seed(png_factory, (5, 0, 0))
    _seed(png_factory, (6, 0, 0))
    assert len(client.get("/api/history").json()) == 2

    assert client.delete(f"/api/history/{e1.id}").status_code == 204
    remaining = client.get("/api/history").json()
    assert len(remaining) == 1
    assert all(e["id"] != e1.id for e in remaining)


def test_clear_all(client, png_factory):
    _seed(png_factory, (7, 0, 0))
    _seed(png_factory, (8, 0, 0))
    assert client.delete("/api/history").status_code == 204
    assert client.get("/api/history").json() == []
