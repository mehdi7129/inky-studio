"""Unit tests for the scheduler's next-fire computation."""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from inky_web.models import ChangeMode, Settings
from inky_web.services.scheduler import _compute_next_change


def _at(hour: int, minute: int = 0, day_offset: int = 0) -> float:
    base = datetime(2026, 5, 24, hour, minute, 0)
    return (base + timedelta(days=day_offset)).timestamp()


def test_manual_mode_returns_none():
    cfg = Settings(change_mode=ChangeMode.manual)
    assert _compute_next_change(cfg, None, now=_at(12)) is None


def test_interval_mode_first_run_fires_now():
    cfg = Settings(change_mode=ChangeMode.interval, change_interval_minutes=30)
    now = _at(12)
    assert _compute_next_change(cfg, None, now=now) == now


def test_interval_mode_after_last_display():
    cfg = Settings(change_mode=ChangeMode.interval, change_interval_minutes=15)
    last = _at(12)
    assert _compute_next_change(cfg, last, now=last + 60) == last + 15 * 60


def test_daily_mode_never_displayed_before_hour():
    cfg = Settings(change_mode=ChangeMode.daily, change_hour=5)
    now = _at(3)  # 3 AM, change_hour is 5
    assert _compute_next_change(cfg, None, now=now) == _at(5)


def test_daily_mode_never_displayed_after_hour():
    cfg = Settings(change_mode=ChangeMode.daily, change_hour=5)
    now = _at(8)  # 8 AM, change_hour is 5 (already passed today)
    assert _compute_next_change(cfg, None, now=now) == _at(5)


def test_daily_mode_last_displayed_before_today_window():
    cfg = Settings(change_mode=ChangeMode.daily, change_hour=5)
    last = _at(2)  # last displayed at 2 AM today
    now = _at(4)   # now 4 AM — window at 5 hasn't fired yet
    assert _compute_next_change(cfg, last, now=now) == _at(5)


def test_daily_mode_last_displayed_after_today_window():
    cfg = Settings(change_mode=ChangeMode.daily, change_hour=5)
    last = _at(6)  # last displayed at 6 AM (after today's 5 AM window)
    now = _at(9)
    assert _compute_next_change(cfg, last, now=now) == _at(5, day_offset=1)


@pytest.mark.asyncio
async def test_first_daily_tick_displays_queued_photo(data_dir, png_factory, monkeypatch):
    from inky_web.events import EventBus
    from inky_web.inky.display import DisplayController
    from inky_web.services import history, photos, queue, scheduler

    photo, _ = photos.save(content=png_factory(), original_filename="first.png")
    queue.add(photo.id)
    monkeypatch.setattr(scheduler.time, "time", lambda: _at(5, 1))
    display = DisplayController()
    display.display_image = Mock()
    await scheduler.Scheduler(display, EventBus())._tick()

    display.display_image.assert_called_once()
    assert history.current().photo.id == photo.id
    assert queue.count() == 0


@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.asyncio
async def test_failed_display_preserves_queue(data_dir, png_factory, monkeypatch, automatic):
    from inky_web.events import EventBus
    from inky_web.inky.display import DisplayController
    from inky_web.services import history, photos, queue, scheduler

    photo, _ = photos.save(content=png_factory(), original_filename="retry.png")
    queue.add(photo.id)
    display = DisplayController()
    display.display_image = Mock(side_effect=OSError("display unavailable"))
    bus = EventBus()
    monkeypatch.setattr(scheduler.time, "time", lambda: _at(5, 1))
    action = scheduler.Scheduler(display, bus)._tick if automatic else lambda: scheduler.trigger_next(display, bus)

    with pytest.raises(OSError, match="display unavailable"):
        await action()
    assert [entry.photo.id for entry in queue.list_all()] == [photo.id]
    assert history.current() is None

    display.display_image.side_effect = None
    await action()
    assert queue.count() == 0
    assert history.current().photo.id == photo.id


@pytest.mark.asyncio
async def test_concurrent_next_consumes_each_photo_once(data_dir, png_factory):
    from inky_web.events import EventBus
    from inky_web.inky.display import DisplayController
    from inky_web.services import history, photos, queue, scheduler

    photo_ids = []
    for red in range(6):
        photo, _ = photos.save(content=png_factory(color=(red, 0, 0)), original_filename=f"{red}.png")
        queue.add(photo.id)
        photo_ids.append(photo.id)
    display = DisplayController()
    display.display_image = Mock()
    bus = EventBus()

    await asyncio.gather(*(scheduler.trigger_next(display, bus) for _ in photo_ids))

    assert queue.count() == 0
    assert [entry.photo.id for entry in reversed(history.list_recent())] == photo_ids


@pytest.mark.parametrize("day", [datetime(2026, 3, 28), datetime(2026, 10, 24)])
def test_daily_next_change_keeps_local_hour_across_dst(day):
    old_tz = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Paris"
    time.tzset()
    try:
        cfg = Settings(change_hour=5)
        last = day.replace(hour=5).timestamp()
        now = day.replace(hour=6).timestamp()
        result = datetime.fromtimestamp(_compute_next_change(cfg, last, now))
        assert result == (day + timedelta(days=1)).replace(hour=5)
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()
