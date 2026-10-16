"""Real AC073 observer/controller/API, with only GPIO, SPI and time inert."""
from __future__ import annotations

import asyncio
import os
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from inky_web.db import data_dir
from inky_web.inky.confirmation import NAME, ConfirmationBarrier
from inky_web.inky.display import DisplayController
from inky_web.inky.errors import DisplayConfirmationPending, DisplayUnavailableError
from inky_web.models import SettingsUpdate
from inky_web.provisioning import screen
from inky_web.services import history, photos, queue, scheduler, settings
from tests.test_display_busy import Value
from tests.test_display_busy import driver_factory as driver_factory
from tests.test_display_hardware import install_auto


def controlled(monkeypatch, driver_factory, *, phases=None):
    driver, gpio, trace = driver_factory(phases or [(Value.ACTIVE, None)] * 4)
    type(driver).__module__ = "inky.inky_ac073tc1a"
    driver.width, driver.height = 800, 480
    driver.eeprom = SimpleNamespace(width=800, height=480, display_variant=20, color=4)
    driver.set_image = Mock()
    install_auto(monkeypatch, driver=driver)
    monkeypatch.setenv("INKY_STUDIO_DISPLAY_PROFILE", "ac073-800x480")
    monkeypatch.setattr("inky_web.inky.display.version", lambda name: "2.3.0")
    display = DisplayController(mode="hardware")
    display.initialize()
    original_show = driver.show

    def show():
        assert ConfirmationBarrier(data_dir()).load() == "in_progress"
        return original_show()

    driver.show = show
    return display, driver, gpio, trace


def attach(client, display):
    client.app.state.display = display
    client.app.state.scheduler = scheduler.Scheduler(display, client.app.state.bus)
    client.app.state.bus.broadcast = Mock()


@pytest.mark.filterwarnings("ignore:Busy Wait")
def test_fallback_keeps_photo_allows_upload_and_manual_edge_then_resumes_auto(client, png_factory, monkeypatch, driver_factory):
    display, driver, gpio, trace = controlled(monkeypatch, driver_factory)
    attach(client, display)
    monkeypatch.setenv("INKY_STUDIO_DISABLE_AUTH", "0")
    assert client.get("/api/display/status").status_code == 401
    password = client.app.state.auth_service.credentials.bootstrap_password
    assert client.post("/api/auth/login", json={"password": password}).status_code == 200
    image = png_factory()
    uploaded = client.post("/api/queue", files={"file": ("first.png", image, "image/png")})
    photo_id = uploaded.json()["photo"]["id"]
    result = client.post("/api/display/next")
    assert result.status_code == 503 and result.json()["code"] == "display_confirmation_pending"
    assert "manuellement" in result.json()["detail"] and "redémarr" not in result.text
    status = client.get("/api/display/status").json()
    assert status["state"] == "ready" and status["error"] is None
    assert status["confirmation"] == "pending" and status["automatic_rotation_paused"]
    assert status["warning"] == result.json()
    assert [item["outcome"] for item in status["observations"]] == ["held_high_unverified"] * 4
    assert trace[-1] == ("show_returned",)
    assert driver.show_calls == 1
    assert photos.path_for(photo_id).read_bytes() == image
    assert queue.count() == 1 and history.current() is None
    assert client.get("/api/state").json()["current"] is None
    assert client.get("/api/display").status_code == 200
    assert client.post("/api/queue", files={"file": ("second.png", png_factory(color=(0, 1, 0)), "image/png")}).status_code == 201
    settings.update(SettingsUpdate(change_mode="interval", change_interval_minutes=1))
    runner = client.app.state.scheduler
    assert runner.next_change_at() is None
    for _ in range(2):
        client.portal.call(runner._tick)
        runner._advance("auto")
        with pytest.raises(DisplayConfirmationPending):
            display.display_image(photos.path_for(photo_id))
    assert driver.show_calls == 1 and queue.count() == 2 and history.current() is None
    gpio.phases, gpio.index = [(Value.INACTIVE, True)] * 4, -1
    assert client.post("/api/display/next").status_code == 202
    assert driver.show_calls == 2 and queue.count() == 1
    assert history.current().photo.id == photo_id
    assert display.pending_confirmation is None and not display.automatic_rotation_paused
    assert ConfirmationBarrier(data_dir()).load() is None
    assert runner.next_change_at() is not None
    assert [call.args[0] for call in client.app.state.bus.broadcast.call_args_list].count("display_changed") == 1


@pytest.mark.filterwarnings("ignore:Busy Wait")
def test_pending_survives_new_controller_and_blocks_welcome_and_provisioning_restore(client, png_factory, monkeypatch, driver_factory, tmp_path):
    display, driver, gpio, _ = controlled(monkeypatch, driver_factory)
    attach(client, display)
    photo, _ = photos.save(content=png_factory(), original_filename="kept.png")
    queue.add(photo.id)
    assert client.post("/api/display/next").status_code == 503
    previous_token = display.pending_confirmation
    restarted = DisplayController(mode="hardware")
    restarted.initialize()
    attach(client, restarted)
    assert restarted.status()["state"] == "ready"
    assert restarted.status()["error"] is None
    assert restarted.automatic_rotation_paused
    with pytest.raises(DisplayConfirmationPending):
        restarted.display_image(photos.path_for(photo.id), retry_confirmation=previous_token)
    from inky_web import welcome
    monkeypatch.setattr(welcome, "_detect_ip", lambda: "192.168.1.120")
    with pytest.raises(DisplayConfirmationPending):
        welcome.show_welcome(restarted)
    private = tmp_path / "provisioning"
    private.mkdir()
    marker = private / ".adoption-screen"
    marker.touch(mode=0o600)
    with pytest.raises(DisplayConfirmationPending):
        screen.restore(restarted, private)
    assert marker.exists() and not restarted.reserved
    client.portal.call(client.app.state.scheduler._tick)
    assert driver.show_calls == 1
    gpio.phases, gpio.index = [(Value.INACTIVE, True)] * 4, -1
    assert client.post("/api/display/next").status_code == 202
    assert driver.show_calls == 2 and history.current().photo.id == photo.id


@pytest.mark.parametrize("kind", ["in_progress", "malformed", "permissions", "symlink"])
def test_interrupted_or_unsafe_barrier_blocks_new_controller_without_show(kind, data_dir, monkeypatch, driver_factory, png_factory):
    barrier = ConfirmationBarrier(data_dir)
    path = data_dir / NAME
    if kind == "in_progress":
        barrier.write("in_progress")
    elif kind == "permissions":
        barrier.write("pending")
        path.chmod(0o644)
    elif kind == "symlink":
        target = data_dir / "untouched"
        target.write_bytes(b"private")
        path.symlink_to(target)
    else:
        path.write_bytes(b"malformed")
        path.chmod(0o600)
    display, driver, _, _ = controlled(monkeypatch, driver_factory)
    assert display.status()["state"] == "error"
    code = "display_confirmation_interrupted" if kind == "in_progress" else "display_confirmation_storage_failed"
    assert display.status()["error"]["code"] == code
    with pytest.raises(DisplayUnavailableError):
        display.display_image(data_dir / "unused.png")
    assert driver.show_calls == 0


@pytest.mark.parametrize("failure", ["before_show", "pending_commit", "pending_sync", "clear", "clear_sync"])
@pytest.mark.filterwarnings("ignore:Busy Wait")
def test_barrier_io_failure_prevents_ack_and_restart_never_retries(client, png_factory, monkeypatch, driver_factory, failure):
    phases = [(Value.INACTIVE, True)] * 4 if failure in {"clear", "clear_sync"} else [(Value.ACTIVE, None)] * 4
    display, driver, _, _ = controlled(monkeypatch, driver_factory, phases=phases)
    attach(client, display)
    photo, _ = photos.save(content=png_factory(), original_filename="retained.png")
    queue.add(photo.id)
    with monkeypatch.context() as patch:
        original_fsync, original_unlink = os.fsync, os.unlink
        calls = 0

        def fsync(fd):
            nonlocal calls
            calls += 1
            fail_call = 1 if failure == "before_show" else 4 if failure == "pending_sync" else 3
            if calls == fail_call and failure != "clear":
                raise OSError("synthetic storage failure")
            return original_fsync(fd)

        def unlink(path, *args, **kwargs):
            if path == NAME and failure == "clear":
                raise OSError("synthetic clear failure")
            return original_unlink(path, *args, **kwargs)

        patch.setattr(os, "fsync", fsync)
        patch.setattr(os, "unlink", unlink)
        response = client.post("/api/display/next")
    assert response.status_code == 503
    assert response.json()["code"] == "display_confirmation_storage_failed"
    assert display.status()["state"] == "error"
    assert queue.count() == 1 and history.current() is None
    assert driver.show_calls == (0 if failure == "before_show" else 1)
    if failure != "before_show":
        restarted = DisplayController(mode="hardware")
        restarted.initialize()
        if failure == "pending_sync":
            assert restarted.status()["error"] is None
            assert restarted.automatic_rotation_paused
            with pytest.raises(DisplayConfirmationPending):
                restarted.display_image(photos.path_for(photo.id))
            assert driver.show_calls == 1
            return
        assert restarted.status()["error"]["code"] == "display_confirmation_interrupted"
        with pytest.raises(DisplayUnavailableError):
            restarted.display_image(photos.path_for(photo.id))
        assert driver.show_calls == 1


@pytest.mark.parametrize("mutation", ["timeout", "exception", "phase", "duration", "extra", "unknown_outcome"])
@pytest.mark.filterwarnings("ignore:Busy Wait")
def test_true_faults_and_unrecognized_sequences_remain_sticky(client, png_factory, monkeypatch, driver_factory, mutation):
    phases = [(Value.ACTIVE, None)] * 4
    if mutation == "timeout":
        phases[2] = (Value.INACTIVE, False)
    if mutation == "exception":
        phases[2] = (OSError("private GPIO failure"), None)
    display, driver, _, _ = controlled(monkeypatch, driver_factory, phases=phases)
    attach(client, display)
    if mutation in {"phase", "duration", "extra", "unknown_outcome"}:
        original = display._busy_observer.run_show

        def observe():
            result = original()
            if mutation == "phase":
                result[0]["phase"] = "unknown"
            elif mutation == "duration":
                result[0]["timeout"] = 2
            elif mutation == "extra":
                result.append(dict(result[-1]))
            else:
                result[0]["outcome"] = "edge_unverified"
            return result

        display._busy_observer.run_show = observe
    photo, _ = photos.save(content=png_factory(), original_filename="kept.png")
    queue.add(photo.id)
    response = client.post("/api/display/next")
    assert response.status_code == 503
    expected = "display_busy_timeout" if mutation == "timeout" else "display_refresh_failed" if mutation == "exception" else "display_busy_unverified"
    assert response.json()["code"] == expected
    assert display.status()["state"] == "error"
    assert client.post("/api/display/next").status_code == 503
    assert driver.show_calls == 1 and queue.count() == 1 and history.current() is None
    restarted = DisplayController(mode="hardware")
    restarted.initialize()
    assert restarted.status()["error"]["code"] == "display_confirmation_interrupted"


@pytest.mark.asyncio
@pytest.mark.filterwarnings("ignore:Busy Wait")
async def test_manual_request_queued_before_fallback_cannot_retry_it(monkeypatch, driver_factory, png_factory):
    display, driver, _, _ = controlled(monkeypatch, driver_factory)
    photo, _ = photos.save(content=png_factory(), original_filename="kept.png")
    queue.add(photo.id)
    started, release = Event(), Event()
    executor = ThreadPoolExecutor(max_workers=1)
    loop = asyncio.get_running_loop()
    old_executor = loop._default_executor
    loop.set_default_executor(executor)
    held = executor.submit(lambda: (started.set(), release.wait(3)))
    try:
        assert started.wait(3)
        waiting = asyncio.create_task(scheduler.trigger_next(display, Mock()))
        await asyncio.sleep(0)  # admission captures None before to_thread is scheduled
        with pytest.raises(DisplayConfirmationPending):
            display.display_image(photos.path_for(photo.id))
        release.set()
        with pytest.raises(DisplayConfirmationPending):
            await waiting
        assert driver.show_calls == 1 and queue.count() == 1 and history.current() is None
    finally:
        release.set()
        held.result(timeout=3)
        loop._default_executor = old_executor
        executor.shutdown(wait=True)


def test_explicit_pending_seed_is_private_idempotent_and_refuses_interrupted(data_dir):
    command = [sys.executable, "-m", "inky_web.inky.confirmation", "--seed-pending"]
    first = subprocess.run(command, capture_output=True, text=True)
    assert first.returncode == 0 and '"display_commands_sent":0' in first.stdout
    path = data_dir / NAME
    original = path.read_bytes()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert subprocess.run(command, capture_output=True).returncode == 0
    assert path.read_bytes() == original
    ConfirmationBarrier(data_dir).write("in_progress")
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert ConfirmationBarrier(data_dir).load() == "in_progress"
