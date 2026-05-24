"""Photo storage — files on disk, metadata in SQLite, sha256-based dedupe."""
from __future__ import annotations

import hashlib
import logging
import time
import uuid
from io import BytesIO
from pathlib import Path

from PIL import Image

from inky_web.db import connection, photos_dir
from inky_web.models import Photo

logger = logging.getLogger(__name__)

ALLOWED_MIME = {"image/png", "image/jpeg"}


class PhotoValidationError(ValueError):
    """Raised when a photo upload doesn't meet the size/format requirements."""


def _row_to_photo(row) -> Photo:
    return Photo(
        id=row["id"],
        sha256=row["sha256"],
        original_filename=row["original_filename"],
        mime=row["mime"],
        width=row["width"],
        height=row["height"],
        size_bytes=row["size_bytes"],
        created_at=row["created_at"],
    )


def _validate_image(content: bytes, expected_size: tuple[int, int] | None) -> tuple[int, int, str]:
    """Return (width, height, mime). Raises PhotoValidationError on bad input."""
    try:
        with Image.open(BytesIO(content)) as img:
            img.verify()
        with Image.open(BytesIO(content)) as img:
            width, height = img.size
            fmt = (img.format or "").upper()
    except Exception as exc:
        raise PhotoValidationError(f"Not a valid image: {exc}") from exc

    if fmt == "PNG":
        mime = "image/png"
    elif fmt in {"JPEG", "JPG"}:
        mime = "image/jpeg"
    else:
        raise PhotoValidationError(f"Unsupported format '{fmt}' — expected PNG or JPEG")

    if expected_size is not None and (width, height) != expected_size:
        raise PhotoValidationError(
            f"Image size {width}x{height} does not match display {expected_size[0]}x{expected_size[1]}"
        )

    return width, height, mime


def find_by_sha(sha256_hex: str) -> Photo | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM photos WHERE sha256 = ?", (sha256_hex,)).fetchone()
        return _row_to_photo(row) if row else None


def find_by_id(photo_id: str) -> Photo | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
        return _row_to_photo(row) if row else None


def path_for(photo_id: str) -> Path:
    return photos_dir() / f"{photo_id}.png"


def save(
    *,
    content: bytes,
    original_filename: str,
    expected_size: tuple[int, int] | None = None,
) -> tuple[Photo, bool]:
    """Persist a photo. Returns (photo, already_existed).

    If a photo with the same sha256 already exists, no file is written and the
    existing row is returned. The expected_size guard checks that the upload
    matches the connected display — pass None to skip the check (useful in tests).
    """
    if not content:
        raise PhotoValidationError("Empty payload")

    sha = hashlib.sha256(content).hexdigest()
    existing = find_by_sha(sha)
    if existing:
        logger.info("Dedupe hit on sha %s — reusing photo %s", sha[:12], existing.id)
        return existing, True

    width, height, mime = _validate_image(content, expected_size)
    if mime != "image/png":
        raise PhotoValidationError(
            "Only PNG uploads are accepted — the browser must convert before upload"
        )

    photo_id = uuid.uuid4().hex[:12]
    path = path_for(photo_id)
    path.write_bytes(content)

    now = time.time()
    photo = Photo(
        id=photo_id,
        sha256=sha,
        original_filename=original_filename,
        mime=mime,
        width=width,
        height=height,
        size_bytes=len(content),
        created_at=now,
    )

    with connection() as conn:
        conn.execute(
            """
            INSERT INTO photos
                (id, sha256, original_filename, mime, width, height, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                photo.id,
                photo.sha256,
                photo.original_filename,
                photo.mime,
                photo.width,
                photo.height,
                photo.size_bytes,
                photo.created_at,
            ),
        )
    logger.info("Saved photo %s (%s, %sx%s, %sB)", photo.id, original_filename, width, height, len(content))
    return photo, False


def delete(photo_id: str) -> bool:
    """Remove a photo (cascades to queue + history). Returns True if it existed."""
    path = path_for(photo_id)
    with connection() as conn:
        cursor = conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
        deleted = cursor.rowcount > 0
    if deleted and path.exists():
        path.unlink()
    return deleted
