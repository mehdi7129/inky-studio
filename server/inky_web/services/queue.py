"""Queue management — ordered list of photos waiting to be displayed."""
from __future__ import annotations

import logging
import time

from inky_web.db import connection
from inky_web.models import Photo, QueueEntry

logger = logging.getLogger(__name__)


def _row_to_entry(row) -> QueueEntry:
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
    return QueueEntry(
        id=row["queue_id"],
        position=row["position"],
        added_at=row["added_at"],
        photo=photo,
    )


def list_all() -> list[QueueEntry]:
    sql = """
        SELECT q.id AS queue_id, q.position, q.added_at,
               p.id AS photo_id, p.sha256, p.original_filename, p.mime,
               p.width, p.height, p.size_bytes, p.created_at AS photo_created_at
        FROM queue q
        JOIN photos p ON p.id = q.photo_id
        ORDER BY q.position ASC
    """
    with connection() as conn:
        return [_row_to_entry(row) for row in conn.execute(sql)]


def _next_position(conn) -> int:
    row = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 AS n FROM queue").fetchone()
    return int(row["n"])


def add(photo_id: str) -> QueueEntry:
    now = time.time()
    with connection() as conn:
        existing = conn.execute("SELECT id FROM queue WHERE photo_id = ?", (photo_id,)).fetchone()
        if existing:
            logger.info("Photo %s already in queue (entry %s) — no-op", photo_id, existing["id"])
        else:
            position = _next_position(conn)
            conn.execute(
                "INSERT INTO queue (photo_id, position, added_at) VALUES (?, ?, ?)",
                (photo_id, position, now),
            )
    entry = _entry_for_photo(photo_id)
    if entry is None:  # pragma: no cover — race only
        raise RuntimeError(f"Queue entry for photo {photo_id} disappeared after insert")
    return entry


def _entry_for_photo(photo_id: str) -> QueueEntry | None:
    sql = """
        SELECT q.id AS queue_id, q.position, q.added_at,
               p.id AS photo_id, p.sha256, p.original_filename, p.mime,
               p.width, p.height, p.size_bytes, p.created_at AS photo_created_at
        FROM queue q JOIN photos p ON p.id = q.photo_id
        WHERE q.photo_id = ?
    """
    with connection() as conn:
        row = conn.execute(sql, (photo_id,)).fetchone()
        return _row_to_entry(row) if row else None


def remove(photo_id: str) -> bool:
    with connection() as conn:
        cursor = conn.execute("DELETE FROM queue WHERE photo_id = ?", (photo_id,))
        return cursor.rowcount > 0


def reorder(photo_ids: list[str]) -> list[QueueEntry]:
    """Set the queue order to match the given photo_ids (in order).

    Any photo_id not currently in the queue is ignored. Any queue entry whose
    photo_id is missing from the input is moved to the end, preserving its
    relative order — this makes the API tolerant of stale clients.
    """
    with connection() as conn:
        existing = {
            row["photo_id"]: row["id"]
            for row in conn.execute("SELECT id, photo_id FROM queue ORDER BY position ASC")
        }
        ordered_known = [pid for pid in photo_ids if pid in existing]
        rest = [pid for pid in existing if pid not in set(ordered_known)]
        final = ordered_known + rest

        for new_position, pid in enumerate(final):
            conn.execute(
                "UPDATE queue SET position = ? WHERE id = ?",
                (new_position, existing[pid]),
            )
    return list_all()


def pop_next() -> QueueEntry | None:
    """Remove and return the head of the queue (lowest position)."""
    sql = """
        SELECT q.id AS queue_id, q.position, q.added_at,
               p.id AS photo_id, p.sha256, p.original_filename, p.mime,
               p.width, p.height, p.size_bytes, p.created_at AS photo_created_at
        FROM queue q JOIN photos p ON p.id = q.photo_id
        ORDER BY q.position ASC LIMIT 1
    """
    with connection() as conn:
        row = conn.execute(sql).fetchone()
        if row is None:
            return None
        entry = _row_to_entry(row)
        conn.execute("DELETE FROM queue WHERE id = ?", (entry.id,))
        return entry


def count() -> int:
    with connection() as conn:
        return int(conn.execute("SELECT COUNT(*) AS n FROM queue").fetchone()["n"])
