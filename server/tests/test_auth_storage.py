"""Credential persistence and bounded authentication state."""
from __future__ import annotations

import json
import stat
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from inky_web import auth


@pytest.mark.parametrize("stored", [[], None, {}, {"password": None}, {"password": 123}, {"password": ""}])
def test_invalid_credential_schema_fails_closed_without_reset(tmp_path, stored):
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps(stored))
    before = path.read_bytes()
    with pytest.raises(auth.CredentialFormatError):
        auth.load_or_create_credentials(tmp_path)
    assert path.read_bytes() == before


def test_failed_password_reset_preserves_previous_credentials(tmp_path, monkeypatch):
    original = auth.load_or_create_credentials(tmp_path)

    def failed_replace(*args):
        raise OSError("simulated storage failure")

    monkeypatch.setattr(auth.os, "replace", failed_replace)
    with pytest.raises(auth.CredentialStorageError) as error:
        auth.reset_credentials(tmp_path)
    assert not error.value.committed
    assert auth.load_or_create_credentials(tmp_path).verify(original.bootstrap_password)
    assert not list(tmp_path.glob(".credentials-*"))


def test_valid_credentials_are_reused(tmp_path):
    first = auth.load_or_create_credentials(tmp_path)
    assert auth.load_or_create_credentials(tmp_path).bootstrap_password == first.bootstrap_password
    assert len(first.bootstrap_password) == 16
    assert stat.S_IMODE(first.path.stat().st_mode) == 0o600
    assert auth.reset_credentials(tmp_path).bootstrap_password != first.bootstrap_password


@pytest.mark.parametrize("password", ["short", "mot-de-passe-é🔐"])
def test_legacy_migration_preserves_password_but_discards_cleartext(tmp_path, password):
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps({"password": password}))
    credentials = auth.load_or_create_credentials(tmp_path)
    assert credentials.verify(password)
    assert credentials.bootstrap_password is None
    assert auth.display_password(tmp_path) is None
    record = json.loads(path.read_text())
    assert "password" not in record and "bootstrap_password" not in record
    assert password not in path.read_text()
    assert record["algorithm"] == "scrypt"
    assert auth.load_or_create_credentials(tmp_path).verify(password)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_equal_passwords_get_distinct_hashes_and_salts(tmp_path):
    first = auth._new_credentials(tmp_path, "same-password")
    second = auth._new_credentials(tmp_path, "same-password")
    assert first.digest != second.digest
    assert first.salt != second.salt
    assert first.verify("same-password") and second.verify("same-password")
    assert "same-password" not in repr(first)


@pytest.mark.parametrize("mutation", [
    {"n": 2**40}, {"salt": "ab"}, {"hash": "not-hex"}, {"version": 99},
    {"bootstrap_password": "different-password"},
])
def test_corrupt_hash_or_parameters_never_silently_regenerate(tmp_path, mutation):
    first = auth.load_or_create_credentials(tmp_path)
    record = first.record() | mutation
    first.path.write_text(json.dumps(record))
    with pytest.raises(auth.CredentialFormatError):
        auth.load_or_create_credentials(tmp_path)
    assert json.loads(first.path.read_text()) == record


@pytest.mark.parametrize("phase", ["fsync", "replace"])
def test_storage_failure_during_rotation_preserves_memory_file_and_sessions(tmp_path, monkeypatch, phase):
    initial = auth.load_or_create_credentials(tmp_path)
    sessions = auth.SessionStore()
    service = auth.CredentialService(initial, sessions)
    token = service.login(initial.bootstrap_password)
    old_bytes = initial.path.read_bytes()

    def fail(*args):
        raise OSError("simulated full disk")

    monkeypatch.setattr(auth.os, phase, fail)
    with pytest.raises(HTTPException) as error:
        service.change_password(token, initial.bootstrap_password, "new-password")
    assert error.value.status_code == 503
    assert sessions.validate(token)
    assert service.credentials is initial
    assert initial.path.read_bytes() == old_bytes
    assert not list(tmp_path.glob(".credentials-*"))


def test_post_rename_sync_failure_revokes_sessions_and_matches_visible_file(tmp_path, monkeypatch):
    initial = auth.load_or_create_credentials(tmp_path)
    sessions = auth.SessionStore()
    service = auth.CredentialService(initial, sessions)
    token = service.login(initial.bootstrap_password)

    def fail(path):
        raise OSError("directory sync failed after rename")

    monkeypatch.setattr(auth, "_sync_directory", fail)
    with pytest.raises(HTTPException) as error:
        service.change_password(token, initial.bootstrap_password, "new-password")
    assert error.value.status_code == 503
    assert "nouveau" in error.value.detail
    assert not sessions.validate(token)
    assert service.credentials.verify("new-password")
    assert auth.load_or_create_credentials(tmp_path).verify("new-password")
    assert not service.credentials.verify(initial.bootstrap_password)


def test_rotation_serializes_queued_old_login_and_second_rotation(tmp_path, monkeypatch):
    initial = auth.load_or_create_credentials(tmp_path)
    sessions = auth.SessionStore()
    service = auth.CredentialService(initial, sessions)
    token = service.login(initial.bootstrap_password)
    entered_write, finish_write = threading.Event(), threading.Event()
    login_started, rotation_started = threading.Event(), threading.Event()
    original_write = auth._write_credentials

    def held_write(credentials):
        entered_write.set()
        assert finish_write.wait(5)
        original_write(credentials)

    def old_login():
        login_started.set()
        return service.login(initial.bootstrap_password)

    def second_rotation():
        rotation_started.set()
        return service.change_password(token, initial.bootstrap_password, "other-password")

    monkeypatch.setattr(auth, "_write_credentials", held_write)
    with ThreadPoolExecutor(max_workers=3) as pool:
        rotation = pool.submit(service.change_password, token, initial.bootstrap_password, "new-password")
        try:
            assert entered_write.wait(5)
            login = pool.submit(old_login)
            other = pool.submit(second_rotation)
            assert login_started.wait(5) and rotation_started.wait(5)
            assert not login.done() and not other.done()
        finally:
            finish_write.set()
        new_token = rotation.result(timeout=5)
        for future in (login, other):
            with pytest.raises(HTTPException) as error:
                future.result(timeout=5)
            assert error.value.status_code == 401
    assert not sessions.validate(token)
    assert sessions.validate(new_token)
    assert len(sessions._sessions) == 1
    assert auth.load_or_create_credentials(tmp_path).verify("new-password")


def test_legacy_cli_password_is_read_only_and_missing_credentials_stay_missing(tmp_path):
    path = tmp_path / "credentials.json"
    with pytest.raises(FileNotFoundError):
        auth.display_password(tmp_path)
    assert not path.exists()
    path.write_text('{"password":"existing-secret"}')
    before = path.read_bytes()
    assert auth.display_password(tmp_path) == "existing-secret"
    assert path.read_bytes() == before


def test_startup_protects_legacy_welcome_images(tmp_path):
    for name in ("welcome_preview.png", "_welcome_tmp.png"):
        artifact = tmp_path / name
        artifact.write_bytes(b"legacy welcome image")
        artifact.chmod(0o644)
    auth.load_or_create_credentials(tmp_path)
    for name in ("welcome_preview.png", "_welcome_tmp.png"):
        assert stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o600


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
