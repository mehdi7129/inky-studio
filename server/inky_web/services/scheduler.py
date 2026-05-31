"""Auto-rotation scheduler — picks the next photo at the configured cadence.

Runs as a single asyncio Task started in the FastAPI lifespan. Three modes
(from ``Settings.change_mode``):

- ``daily``   — change once per day at ``change_hour``
- ``interval``— change every ``change_interval_minutes`` minutes since the last
                successful display
- ``manual``  — no auto changes; user drives via /api/display/next

When the queue is empty, the scheduler recycles the photo least-recently shown
from history (oldest first), so the rotation keeps going indefinitely. If both
queue and history are empty, it logs a warning and waits for the next tick.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

from inky_web.events import EventBus
from inky_web.inky.display import DisplayController
from inky_web.models import ChangeMode
from inky_web.services import history, queue, settings
from inky_web.services.photos import path_for

logger = logging.getLogger(__name__)

TICK_SECONDS = 60.0  # check every minute — granularity is fine for hourly/daily cadence


class Scheduler:
    def __init__(self, display: DisplayController, bus: EventBus) -> None:
        self._display = display
        self._bus = bus
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="inky-scheduler")
        logger.info("Scheduler started")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None
        logger.info("Scheduler stopped")

    def next_change_at(self) -> float | None:
        """Return the unix timestamp of the next scheduled change, or None for manual mode."""
        cfg = settings.get()
        if cfg.change_mode == ChangeMode.manual:
            return None
        last = history.current()
        last_ts = last.displayed_at if last else None
        return _compute_next_change(cfg, last_ts, now=time.time())

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:  # noqa: BLE001
                logger.exception("Scheduler tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=TICK_SECONDS)
            except TimeoutError:
                continue

    async def _tick(self) -> None:
        cfg = settings.get()
        if cfg.change_mode == ChangeMode.manual:
            return

        last = history.current()
        last_ts = last.displayed_at if last else None
        now = time.time()
        next_at = _compute_next_change(cfg, last_ts, now=now)

        if next_at is None or now < next_at:
            return

        logger.info("Scheduler firing rotation (mode=%s)", cfg.change_mode.value)
        await asyncio.to_thread(self._advance, "auto")

    def _advance(self, source: str) -> None:
        next_entry = queue.pop_next()
        if next_entry is not None:
            photo_id = next_entry.photo.id
            self._show(photo_id, source=source)
            self._bus.broadcast("queue_updated", {"action": "popped", "photo_id": photo_id})
            return

        current_entry = history.current()
        recycled = history.oldest_unique_photo_id_excluding(
            current_entry.photo.id if current_entry else None
        )
        if recycled is None:
            logger.warning("Nothing to display — queue and history both empty")
            return
        self._show(recycled, source="recycle")

    def _show(self, photo_id: str, source: str) -> None:
        path = path_for(photo_id)
        if not path.exists():
            logger.error("Photo file missing for %s — skipping", photo_id)
            return
        self._display.display_image(path)
        entry = history.record(photo_id, source=source)  # type: ignore[arg-type]
        self._bus.broadcast(
            "display_changed",
            {"history_id": entry.id, "photo_id": photo_id, "source": source},
        )


def _compute_next_change(
    cfg, last_displayed_at: float | None, now: float
) -> float | None:
    """Return the unix timestamp at which the next change should fire."""
    if cfg.change_mode == ChangeMode.manual:
        return None

    if cfg.change_mode == ChangeMode.interval:
        if last_displayed_at is None:
            return now
        return last_displayed_at + cfg.change_interval_minutes * 60.0

    today_window = datetime.fromtimestamp(now).replace(
        hour=cfg.change_hour, minute=0, second=0, microsecond=0
    ).timestamp()

    if last_displayed_at is None:
        return today_window if today_window > now else today_window + 86400.0
    if last_displayed_at < today_window:
        return today_window
    return today_window + 86400.0


async def trigger_next(display: DisplayController, bus: EventBus) -> None:
    """Manual next — same logic as scheduler tick but with source=manual_next."""
    await asyncio.to_thread(_manual_next, display, bus)


def _manual_next(display: DisplayController, bus: EventBus) -> None:
    entry = queue.pop_next()
    if entry is not None:
        _show(display, bus, entry.photo.id, source="manual_next")
        bus.broadcast("queue_updated", {"action": "popped", "photo_id": entry.photo.id})
        return
    current_entry = history.current()
    recycled = history.oldest_unique_photo_id_excluding(
        current_entry.photo.id if current_entry else None
    )
    if recycled is None:
        return
    _show(display, bus, recycled, source="manual_next")


async def trigger_previous(display: DisplayController, bus: EventBus) -> None:
    await asyncio.to_thread(_manual_previous, display, bus)


def _manual_previous(display: DisplayController, bus: EventBus) -> None:
    cur = history.current()
    if cur is None:
        return
    prev = history.previous_to(cur.id)
    if prev is None:
        return
    _show(display, bus, prev.photo.id, source="manual_previous")


def _show(display: DisplayController, bus: EventBus, photo_id: str, source: str) -> None:
    path = path_for(photo_id)
    if not path.exists():
        logger.error("Photo file missing for %s — skipping", photo_id)
        return
    display.display_image(path)
    entry = history.record(photo_id, source=source)  # type: ignore[arg-type]
    bus.broadcast(
        "display_changed",
        {"history_id": entry.id, "photo_id": photo_id, "source": source},
    )
