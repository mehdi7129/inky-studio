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
from datetime import datetime, timedelta

from fastapi import HTTPException

from inky_web.events import EventBus
from inky_web.inky.display import DisplayController
from inky_web.inky.errors import DisplayUnavailableError
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
        self.request_stop()
        if self._task is not None:
            await self._task
            self._task = None
        logger.info("Scheduler stopped")

    def request_stop(self) -> None:
        """Stop producing work without waiting for an already admitted refresh."""
        self._stop.set()

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
        with self._display.operation():
            self._display.require_available()
            if self._display.reserved:
                return
            # A manual refresh can complete while this worker waits for the display.
            cfg = settings.get()
            current = history.current()
            now = time.time()
            next_at = _compute_next_change(cfg, current.displayed_at if current else None, now)
            if next_at is None or now < next_at:
                return
            _advance(self._display, self._bus, source=source, recycle_source="recycle")


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

    today = datetime.fromtimestamp(now).replace(
        hour=cfg.change_hour, minute=0, second=0, microsecond=0
    )
    today_window = today.timestamp()

    if last_displayed_at is None:
        return today_window
    if last_displayed_at < today_window:
        return today_window
    return (today + timedelta(days=1)).timestamp()


async def trigger_next(display: DisplayController, bus: EventBus) -> None:
    """Manual next — same logic as scheduler tick but with source=manual_next."""
    await asyncio.to_thread(_manual_next, display, bus)


def _manual_next(display: DisplayController, bus: EventBus) -> None:
    with display.operation():
        _require_available(display)
        _advance(display, bus, source="manual_next", recycle_source="manual_next")


def _advance(display: DisplayController, bus: EventBus, *, source: str, recycle_source: str) -> None:
    while (entry := queue.peek_next()) is not None:
        if not path_for(entry.photo.id).exists():
            # A permanently missing source must not block every later photo.
            # Keep its metadata; only remove this unusable queue entry. Errors
            # from the actual driver below still propagate and preserve queue.
            logger.warning("Photo file missing for %s — skipping queue entry %s", entry.photo.id, entry.id)
            queue.remove_entry(entry.id)
            bus.broadcast("queue_updated", {
                "action": "skipped", "photo_id": entry.photo.id, "reason": "file_missing",
            })
            continue
        _show(display, bus, entry.photo.id, source=source)
        queue.remove_entry(entry.id)
        bus.broadcast("queue_updated", {"action": "popped", "photo_id": entry.photo.id})
        return
    current_entry = history.current()
    recycled = history.oldest_unique_photo_id_excluding(
        current_entry.photo.id if current_entry else None
    )
    if recycled is None:
        return
    _show(display, bus, recycled, source=recycle_source)


async def trigger_previous(display: DisplayController, bus: EventBus) -> None:
    await asyncio.to_thread(_manual_previous, display, bus)


def _manual_previous(display: DisplayController, bus: EventBus) -> None:
    with display.operation():
        _require_available(display)
        prev = history.previous()
        if prev is not None:
            _show(
                display, bus, prev.photo.id,
                source="manual_previous", navigation_history_id=prev.id,
            )


def _require_available(display: DisplayController) -> None:
    display.require_available()
    if display.reserved:
        raise HTTPException(status_code=409, detail="Termine la connexion Bluetooth avant de changer de photo")


def _show(
    display: DisplayController, bus: EventBus, photo_id: str, source: str,
    *, navigation_history_id: int | None = None,
) -> None:
    path = path_for(photo_id)
    if not path.exists():
        raise FileNotFoundError(f"Photo file missing for {photo_id}")
    try:
        display.display_image(path, saturation=settings.get().saturation)
    except DisplayUnavailableError as exc:
        bus.broadcast("display_error", exc.payload())
        raise
    entry = history.record(
        photo_id, source=source, navigation_history_id=navigation_history_id,  # type: ignore[arg-type]
    )
    bus.broadcast(
        "display_changed",
        {"history_id": entry.id, "photo_id": photo_id, "source": source},
    )
