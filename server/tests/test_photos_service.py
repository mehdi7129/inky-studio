"""Unit tests for the photos service (CRUD + dedupe + validation)."""
from __future__ import annotations

import pytest


def test_save_persists_metadata_and_file(data_dir, png_factory):
    from inky_web.services import photos

    photo, already_existed = photos.save(
        content=png_factory(800, 480),
        original_filename="test.png",
        expected_size=(800, 480),
    )
    assert already_existed is False
    assert photo.width == 800
    assert photo.height == 480
    assert photo.mime == "image/png"
    assert photos.path_for(photo.id).exists()


def test_save_dedupes_by_sha256(data_dir, png_factory):
    from inky_web.services import photos

    content = png_factory(800, 480, color=(7, 7, 7))
    first, _ = photos.save(content=content, original_filename="a.png", expected_size=(800, 480))
    second, already = photos.save(content=content, original_filename="b.png", expected_size=(800, 480))

    assert already is True
    assert first.id == second.id


def test_save_rejects_jpeg(data_dir, jpeg_factory):
    from inky_web.services import photos
    from inky_web.services.photos import PhotoValidationError

    with pytest.raises(PhotoValidationError, match="Only PNG"):
        photos.save(
            content=jpeg_factory(800, 480),
            original_filename="x.jpg",
            expected_size=(800, 480),
        )


def test_save_rejects_wrong_size(data_dir, png_factory):
    from inky_web.services import photos
    from inky_web.services.photos import PhotoValidationError

    with pytest.raises(PhotoValidationError, match="does not match display"):
        photos.save(
            content=png_factory(640, 480),
            original_filename="wrong.png",
            expected_size=(800, 480),
        )


def test_save_rejects_empty_payload(data_dir):
    from inky_web.services import photos
    from inky_web.services.photos import PhotoValidationError

    with pytest.raises(PhotoValidationError, match="Empty"):
        photos.save(content=b"", original_filename="empty.png", expected_size=None)


def test_delete_removes_row_and_file(data_dir, png_factory):
    from inky_web.services import photos

    photo, _ = photos.save(
        content=png_factory(800, 480, color=(1, 2, 3)),
        original_filename="d.png",
        expected_size=(800, 480),
    )
    path = photos.path_for(photo.id)
    assert path.exists()

    assert photos.delete(photo.id) is True
    assert not path.exists()
    assert photos.find_by_id(photo.id) is None


def test_delete_returns_false_for_unknown(data_dir):
    from inky_web.services import photos

    assert photos.delete("does-not-exist") is False
