"""Unit tests for the settings service."""
from __future__ import annotations


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
