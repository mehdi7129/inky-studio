"""Unit tests for the history service."""
from __future__ import annotations

import time


def _save(png_factory, *, color):
    from inky_web.services import photos
    p, _ = photos.save(
        content=png_factory(800, 480, color=color),
        original_filename=f"h-{color[0]}.png",
        expected_size=(800, 480),
    )
    return p


def test_record_and_current(data_dir, png_factory):
    from inky_web.services import history

    p = _save(png_factory, color=(11, 0, 0))
    entry = history.record(p.id, source="auto")
    assert entry.photo.id == p.id
    assert history.current().photo.id == p.id


def test_current_returns_most_recent(data_dir, png_factory):
    from inky_web.services import history

    p1 = _save(png_factory, color=(12, 0, 0))
    p2 = _save(png_factory, color=(13, 0, 0))
    history.record(p1.id, source="auto")
    time.sleep(0.01)
    history.record(p2.id, source="auto")

    assert history.current().photo.id == p2.id


def test_previous_to_navigates_back(data_dir, png_factory):
    from inky_web.services import history

    p1 = _save(png_factory, color=(14, 0, 0))
    p2 = _save(png_factory, color=(15, 0, 0))
    e1 = history.record(p1.id, source="auto")
    e2 = history.record(p2.id, source="auto")

    assert history.previous_to(e2.id).id == e1.id
    assert history.previous_to(e1.id) is None


def test_oldest_unique_excludes_current(data_dir, png_factory):
    from inky_web.services import history

    p1 = _save(png_factory, color=(16, 0, 0))
    p2 = _save(png_factory, color=(17, 0, 0))
    history.record(p1.id, source="auto")
    time.sleep(0.01)
    history.record(p2.id, source="auto")

    assert history.oldest_unique_photo_id_excluding(p2.id) == p1.id
    assert history.oldest_unique_photo_id_excluding(p1.id) == p2.id


def test_list_recent_paginates(data_dir, png_factory):
    from inky_web.services import history

    for i in range(5):
        p = _save(png_factory, color=(20 + i, 0, 0))
        history.record(p.id, source="auto")
        time.sleep(0.005)

    page1 = history.list_recent(limit=2, offset=0)
    page2 = history.list_recent(limit=2, offset=2)
    assert len(page1) == 2 and len(page2) == 2
    assert page1[0].displayed_at > page2[0].displayed_at
