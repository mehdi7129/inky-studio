"""Unit tests for the scheduler's next-fire computation."""
from __future__ import annotations

from datetime import datetime, timedelta

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
    assert _compute_next_change(cfg, None, now=now) == _at(5, day_offset=1)


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
