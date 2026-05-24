"""History log — append-only record of every display event."""
from __future__ import annotations

import logging
import time
from typing import Literal

from inky_web.db import connection
from inky_web.models import HistoryEntry, Photo

logger = logging.getLogger(__name__)

Source = Literal["auto", "manual_next", "manual_previous", "recycle", "upload"]


def _row_to_entry(row) -> HistoryEntry:
    photo = Photo(
        id=row["photo_id"],
        sha256=row["sha256"],
        original_filename=row["original_filename"],
        mime=row["mime"],
        width=row["width"],
        height=row["height"],
        size_bytes=row["size_bytes"],
        created_at=row["photo_created_at"],
    )
    return HistoryEntry(
        id=row["history_id"],
        displayed_at=row["displayed_at"],
        source=row["source"],
        photo=photo,
    )


_BASE_SELECT = """
    SELECT h.id AS history_id, h.displayed_at, h.source,
           p.id AS photo_id, p.sha256, p.original_filename, p.mime,
           p.width, p.height, p.size_bytes, p.created_at AS photo_created_at
    FROM history h JOIN photos p ON p.id = h.photo_id
"""


def record(photo_id: str, source: Source) -> HistoryEntry:
    now = time.time()
    with connection() as conn:
        cursor = conn.execute(
            "INSERT INTO history (photo_id, displayed_at, source) VALUES (?, ?, ?)",
            (photo_id, now, source),
        )
        history_id = cursor.lastrowid
    sql = _BASE_SELECT + " WHERE h.id = ?"
    with connection() as conn:
        row = conn.execute(sql, (history_id,)).fetchone()
    return _row_to_entry(row)


def current() -> HistoryEntry | None:
    sql = _BASE_SELECT + " ORDER BY h.displayed_at DESC LIMIT 1"
    with connection() as conn:
        row = conn.execute(sql).fetchone()
        return _row_to_entry(row) if row else None


def previous_to(history_id: int) -> HistoryEntry | None:
    sql = _BASE_SELECT + " WHERE h.id < ? ORDER BY h.id DESC LIMIT 1"
    with connection() as conn:
        row = conn.execute(sql, (history_id,)).fetchone()
        return _row_to_entry(row) if row else None


def list_recent(limit: int = 100, offset: int = 0) -> list[HistoryEntry]:
    sql = _BASE_SELECT + " ORDER BY h.displayed_at DESC LIMIT ? OFFSET ?"
    with connection() as conn:
        return [_row_to_entry(row) for row in conn.execute(sql, (limit, offset))]


def oldest_unique_photo_id_excluding(exclude_photo_id: str | None) -> str | None:
    """Find the photo least-recently displayed, excluding the current one.

    Used when the queue empties: we recycle photos from the history, oldest
    first, so the rotation keeps going.
    """
    sql = """
        SELECT photo_id, MAX(displayed_at) AS last_shown
        FROM history
        WHERE (? IS NULL OR photo_id <> ?)
        GROUP BY photo_id
        ORDER BY last_shown ASC
        LIMIT 1
    """
    with connection() as conn:
        row = conn.execute(sql, (exclude_photo_id, exclude_photo_id)).fetchone()
        return row["photo_id"] if row else None


def count() -> int:
    with connection() as conn:
        return int(conn.execute("SELECT COUNT(*) AS n FROM history").fetchone()["n"])
