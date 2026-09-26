"""Unit tests for the settings service."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier


def test_default_settings_when_empty(data_dir):
    from inky_web.models import ChangeMode
    from inky_web.services import settings

    s = settings.get()
    assert s.change_mode == ChangeMode.daily
    assert s.change_hour == 5


def test_update_persists_partial_change(data_dir):
    from inky_web.models import ChangeMode, SettingsUpdate
    from inky_web.services import settings

    new = settings.update(SettingsUpdate(change_mode=ChangeMode.manual))
    assert new.change_mode == ChangeMode.manual
    assert new.change_hour == 5  # untouched

    again = settings.get()
    assert again.change_mode == ChangeMode.manual
    assert again.change_hour == 5


def test_update_multiple_fields(data_dir):
    from inky_web.models import ChangeMode, SettingsUpdate
    from inky_web.services import settings

    new = settings.update(
        SettingsUpdate(change_mode=ChangeMode.interval, change_interval_minutes=30)
    )
    assert new.change_mode == ChangeMode.interval
    assert new.change_interval_minutes == 30


def test_concurrent_partial_updates_preserve_both_fields(data_dir, monkeypatch):
    from inky_web.models import SettingsUpdate
    from inky_web.services import settings

    original_get = settings.get
    barrier = Barrier(2)

    def read_at_same_time():
        value = original_get()
        barrier.wait(timeout=3)
        return value

    # Coordinates the original read/modify/write race without sleeps.
    monkeypatch.setattr(settings, "get", read_at_same_time)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(settings.update, SettingsUpdate(change_hour=9)),
            pool.submit(settings.update, SettingsUpdate(saturation=1.5)),
        ]
        for future in futures:
            future.result(timeout=3)

    saved = original_get()
    assert saved.change_hour == 9
    assert saved.saturation == 1.5
