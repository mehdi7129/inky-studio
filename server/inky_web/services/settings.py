"""Settings — typed key/value store backed by the settings table."""
from __future__ import annotations

import json
import logging

from inky_web.db import connection
from inky_web.models import ChangeMode, ColorMode, Settings, SettingsUpdate

logger = logging.getLogger(__name__)

_DEFAULTS = Settings()


def _read_all() -> dict[str, str]:
    with connection() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {row["key"]: row["value"] for row in rows}


def get() -> Settings:
    raw = _read_all()
    if not raw:
        return _DEFAULTS.model_copy()
    data: dict[str, object] = {}
    for key, value in raw.items():
        try:
            data[key] = json.loads(value)
        except json.JSONDecodeError:
            logger.warning("Bad JSON for setting %s — using default", key)
    return Settings(**{**_DEFAULTS.model_dump(), **data})


def update(patch: SettingsUpdate) -> Settings:
    current = get()
    merged = current.model_copy(update={k: v for k, v in patch.model_dump(exclude_none=True).items()})
    with connection() as conn:
        for key, value in merged.model_dump().items():
            if isinstance(value, (ColorMode, ChangeMode)):
                value = value.value
            conn.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, json.dumps(value)),
            )
    return merged
