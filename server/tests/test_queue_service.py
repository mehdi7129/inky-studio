"""Unit tests for the queue service."""
from __future__ import annotations

import pytest


def _save(png_factory, *, color):
    from inky_web.services import photos
    p, _ = photos.save(
        content=png_factory(800, 480, color=color),
        original_filename=f"c-{color[0]}.png",
        expected_size=(800, 480),
    )
    return p


def test_add_appends_to_end(data_dir, png_factory):
    from inky_web.services import queue

    p1 = _save(png_factory, color=(10, 0, 0))
    p2 = _save(png_factory, color=(20, 0, 0))
    queue.add(p1.id)
    queue.add(p2.id)

    entries = queue.list_all()
    assert [e.photo.id for e in entries] == [p1.id, p2.id]
    assert entries[0].position < entries[1].position


def test_add_same_photo_is_noop(data_dir, png_factory):
    from inky_web.services import queue

    p = _save(png_factory, color=(30, 0, 0))
    queue.add(p.id)
    queue.add(p.id)

    assert queue.count() == 1


def test_pop_next_returns_head_and_advances(data_dir, png_factory):
    from inky_web.services import queue

    p1 = _save(png_factory, color=(40, 0, 0))
    p2 = _save(png_factory, color=(50, 0, 0))
    queue.add(p1.id)
    queue.add(p2.id)

    head = queue.pop_next()
    assert head is not None and head.photo.id == p1.id
    remaining = queue.list_all()
    assert [e.photo.id for e in remaining] == [p2.id]


def test_pop_next_on_empty_queue_returns_none(data_dir):
    from inky_web.services import queue

    assert queue.pop_next() is None


def test_remove_drops_specific_entry(data_dir, png_factory):
    from inky_web.services import queue

    p1 = _save(png_factory, color=(60, 0, 0))
    p2 = _save(png_factory, color=(70, 0, 0))
    queue.add(p1.id)
    queue.add(p2.id)

    assert queue.remove(p1.id) is True
    assert [e.photo.id for e in queue.list_all()] == [p2.id]


def test_reorder_respects_input_order(data_dir, png_factory):
    from inky_web.services import queue

    p1 = _save(png_factory, color=(80, 0, 0))
    p2 = _save(png_factory, color=(90, 0, 0))
    p3 = _save(png_factory, color=(100, 0, 0))
    queue.add(p1.id)
    queue.add(p2.id)
    queue.add(p3.id)

    queue.reorder([p3.id, p1.id, p2.id])
    assert [e.photo.id for e in queue.list_all()] == [p3.id, p1.id, p2.id]


def test_reorder_with_stale_ids_pushes_unmentioned_to_end(data_dir, png_factory):
    from inky_web.services import queue

    p1 = _save(png_factory, color=(110, 0, 0))
    p2 = _save(png_factory, color=(120, 0, 0))
    p3 = _save(png_factory, color=(130, 0, 0))
    queue.add(p1.id)
    queue.add(p2.id)
    queue.add(p3.id)

    # client only knows about p1 + p3 (missed an upload)
    queue.reorder([p3.id, p1.id])
    order = [e.photo.id for e in queue.list_all()]
    assert order[0] == p3.id
    assert order[1] == p1.id
    assert p2.id in order  # p2 still present, just at end


def test_deleting_photo_cascades_to_queue(data_dir, png_factory):
    from inky_web.services import photos, queue

    p = _save(png_factory, color=(140, 0, 0))
    queue.add(p.id)
    assert queue.count() == 1
    photos.delete(p.id)
    assert queue.count() == 0
