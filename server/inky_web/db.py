"""SQLite connection + schema bootstrap.

Single-file DB at <data_dir>/inky_studio.db. Photos are stored as files in
<data_dir>/photos/<id>.png so the DB stays small and we don't load image
bytes into memory when listing.

`data_dir` defaults to ``server/data/`` but can be overridden with the
``INKY_STUDIO_DATA_DIR`` environment variable — tests rely on this to redirect
to a tmp directory.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
    id                TEXT PRIMARY KEY,
    sha256            TEXT NOT NULL UNIQUE,
    original_filename TEXT NOT NULL,
    mime              TEXT NOT NULL,
    width             INTEGER NOT NULL,
    height            INTEGER NOT NULL,
    size_bytes        INTEGER NOT NULL,
    created_at        REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS queue (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id  TEXT NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    position  INTEGER NOT NULL,
    added_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_queue_position ON queue(position);

CREATE TABLE IF NOT EXISTS history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id      TEXT NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    displayed_at  REAL NOT NULL,
    source        TEXT NOT NULL DEFAULT 'auto'
);
CREATE INDEX IF NOT EXISTS idx_history_time ON history(displayed_at DESC);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""


def data_dir() -> Path:
    raw = os.environ.get("INKY_STUDIO_DATA_DIR")
    if raw:
        path = Path(raw).expanduser()
    else:
        path = Path(__file__).resolve().parent.parent / "data"
    path.mkdir(parents=True, exist_ok=True)
    (path / "photos").mkdir(exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "inky_studio.db"


def photos_dir() -> Path:
    return data_dir() / "photos"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    """Yield a short-lived connection. Caller is responsible for transactions."""
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Create tables on first run. Safe to call repeatedly."""
    with connection() as conn:
        conn.executescript(SCHEMA)
    logger.info("Database initialized at %s", db_path())
