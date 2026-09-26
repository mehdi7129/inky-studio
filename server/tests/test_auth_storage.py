"""Credential persistence and bounded authentication state."""
from __future__ import annotations

import json
import stat

import pytest

from inky_web import auth


@pytest.mark.parametrize("stored", [[], None, {}, {"password": None}, {"password": 123}, {"password": ""}])
def test_invalid_credential_schema_is_recovered(tmp_path, stored):
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps(stored))
    credentials = auth.load_or_create_credentials(tmp_path)
    assert len(credentials.password) == 10
    assert json.loads(path.read_text())["password"] == credentials.password
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_failed_password_reset_preserves_previous_credentials(tmp_path, monkeypatch):
    original = auth.load_or_create_credentials(tmp_path)

    def failed_replace(*args):
        raise OSError("simulated storage failure")

    monkeypatch.setattr(auth.os, "replace", failed_replace)
    with pytest.raises(OSError, match="storage failure"):
        auth.reset_credentials(tmp_path)
    assert auth.load_or_create_credentials(tmp_path).password == original.password
    assert not list(tmp_path.glob(".credentials-*"))


def test_valid_credentials_are_reused(tmp_path):
    first = auth.load_or_create_credentials(tmp_path)
    assert auth.load_or_create_credentials(tmp_path).password == first.password
    assert auth.reset_credentials(tmp_path).password != first.password


def test_rate_limiter_bounds_rejected_attempt_storage_and_expires(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(auth.time, "monotonic", lambda: now[0])
    limiter = auth.LoginRateLimiter(window_seconds=60, max_attempts=5)
    assert all(limiter.record_and_check("ip") for _ in range(5))
    for _ in range(10000):
        assert not limiter.record_and_check("ip")
    assert len(limiter._attempts["ip"]) == 5
    assert limiter.record_and_check("other-ip")
    now[0] += 60
    assert limiter.record_and_check("ip")


def test_expired_sessions_are_rejected_and_pruned(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(auth.time, "time", lambda: now[0])
    sessions = auth.SessionStore()
    old = sessions.create()
    assert sessions.validate(old)
    now[0] += auth.SESSION_TTL_SECONDS
    assert not sessions.validate(old)
    unvisited = sessions.create()
    now[0] += auth.SESSION_TTL_SECONDS
    newest = sessions.create()
    assert unvisited not in sessions._sessions
    assert sessions.validate(newest)
