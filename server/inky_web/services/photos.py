"""Photo storage — files on disk, metadata in SQLite, sha256-based dedupe."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from sqlite3 import Connection

from PIL import Image

from inky_web.db import connection, photos_dir, transaction
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
            width, height = img.size
            fmt = (img.format or "").upper()
            if expected_size is not None and (width, height) != expected_size:
                raise PhotoValidationError(
                    f"Image size {width}x{height} does not match display {expected_size[0]}x{expected_size[1]}"
                )
            img.verify()
        with Image.open(BytesIO(content)) as img:
            # PNG verify() checks chunk integrity, not whether pixels decode.
            # Enforce panel dimensions before allocating the decoded image.
            img.load()
    except PhotoValidationError:
        raise
    except Exception as exc:
        raise PhotoValidationError(f"Not a valid image: {exc}") from exc

    if fmt == "PNG":
        mime = "image/png"
    elif fmt in {"JPEG", "JPG"}:
        mime = "image/jpeg"
    else:
        raise PhotoValidationError(f"Unsupported format '{fmt}' — expected PNG or JPEG")

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


@contextmanager
def storage_transaction() -> Iterator[tuple[Connection, list[Path]]]:
    """Undo filesystem additions after a transaction rollback or a failed write."""
    created: list[Path] = []
    try:
        with transaction() as conn:
            yield conn, created
    except BaseException:
        if created:
            try:
                with transaction() as conn:
                    for path in created:
                        if conn.execute("SELECT 1 FROM photos WHERE id = ?", (path.stem,)).fetchone() is None:
                            path.unlink(missing_ok=True)
            except Exception:
                # A failed database read cannot establish that a file is unreferenced.
                logger.warning("Photo staging cleanup deferred until restart")
        raise


def recover_upload_files() -> None:
    """Called under the startup writer guard before serving frame requests."""
    with transaction() as conn:
        known = {row["id"] for row in conn.execute("SELECT id FROM photos")}
        for path in photos_dir().iterdir():
            if path.name.startswith(".inky-upload-") or (
                re.fullmatch(r"[0-9a-f]{12}\.png", path.name) and path.stem not in known
            ):
                if path.is_file():
                    path.unlink(missing_ok=True)


def prepare(content: bytes, expected_size: tuple[int, int] | None) -> tuple[int, int, str]:
    if not content:
        raise PhotoValidationError("Empty payload")
    width, height, mime = _validate_image(content, expected_size)
    if mime != "image/png":
        raise PhotoValidationError("Only PNG uploads are accepted — the browser must convert before upload")
    return width, height, mime


def save_prepared(conn: Connection, created: list[Path], *, content: bytes, sha: str,
                  original_filename: str, dimensions: tuple[int, int, str]) -> tuple[Photo, bool]:
    row = conn.execute("SELECT * FROM photos WHERE sha256 = ?", (sha,)).fetchone()
    if row is not None:
        return _row_to_photo(row), True

    width, height, mime = dimensions
    destination = path_for(uuid.uuid4().hex[:12])
    while destination.exists() or conn.execute("SELECT 1 FROM photos WHERE id = ?", (destination.stem,)).fetchone():
        destination = path_for(uuid.uuid4().hex[:12])
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".inky-upload-", delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, destination)
        created.append(destination)
        descriptor = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    photo = Photo(id=destination.stem, sha256=sha, original_filename=original_filename,
                  mime=mime, width=width, height=height, size_bytes=len(content), created_at=time.time())
    conn.execute(
        """INSERT INTO photos
           (id, sha256, original_filename, mime, width, height, size_bytes, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (photo.id, photo.sha256, photo.original_filename, photo.mime, photo.width,
         photo.height, photo.size_bytes, photo.created_at),
    )
    return photo, False


def save(*, content: bytes, original_filename: str,
         expected_size: tuple[int, int] | None = None) -> tuple[Photo, bool]:
    dimensions = prepare(content, expected_size)
    with storage_transaction() as (conn, created):
        return save_prepared(conn, created, content=content, sha=hashlib.sha256(content).hexdigest(),
                             original_filename=original_filename, dimensions=dimensions)


def delete(photo_id: str) -> bool:
    """Remove a photo (cascades to queue + history). Returns True if it existed."""
    path = path_for(photo_id)
    with connection() as conn:
        cursor = conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
        deleted = cursor.rowcount > 0
    if deleted and path.exists():
        path.unlink()
    return deleted
