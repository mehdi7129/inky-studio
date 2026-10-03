"""Failure paths cross real controller, API, queue and event bus; no GPIO."""
from __future__ import annotations

import builtins
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from inky_web.inky.display import DisplayController
from inky_web.inky.errors import DisplayUnavailableError
from inky_web.services import history, photos, queue, scheduler


def install_auto(monkeypatch, driver=None, error=None):
    package = ModuleType("inky")
    package.__path__ = []
    module = ModuleType("inky.auto")
    module.auto = Mock(return_value=driver, side_effect=error)
    monkeypatch.setitem(sys.modules, "inky", package)
    monkeypatch.setitem(sys.modules, "inky.auto", module)
    return module.auto


def test_mock_does_not_import_or_access_hardware(monkeypatch):
    original = builtins.__import__

    def importing(name, *args, **kwargs):
        assert name != "inky" and not name.startswith("inky.")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", importing)
    monkeypatch.setattr("inky_web.inky.display.platform.system", lambda: "Linux")
    display = DisplayController(mode="mock")
    display.initialize()
    assert display.info()["is_mock"] is True
    assert display.status()["state"] == "mock"


@pytest.mark.parametrize("failure", [ImportError("missing package"), OSError("private GPIO path"), SystemExit(1)])
def test_hardware_initialization_error_never_falls_back(monkeypatch, failure):
    auto = install_auto(monkeypatch, error=failure)
    display = DisplayController(mode="hardware")
    display.initialize()
    display.initialize()  # no automatic hardware retry after a fault
    assert auto.call_count == 1
    assert display.is_mock is False
    assert display.status()["state"] == "error"
    assert display.status()["error"]["code"] == "display_unavailable"
    assert "private" not in str(display.status())
    for read in (lambda: display.spec, display.info):
        with pytest.raises(DisplayUnavailableError):
            read()


@pytest.mark.parametrize(("system", "expected"), [("Linux", "hardware"), ("Darwin", "mock")])
def test_auto_resolves_by_platform_without_fallback(monkeypatch, system, expected):
    monkeypatch.setattr("inky_web.inky.display.platform.system", lambda: system)
    display = DisplayController(mode="auto")
    assert display.status()["mode"] == expected
    assert display.is_mock is (expected == "mock")


def test_invalid_mode_and_profile_are_configuration_errors(monkeypatch):
    with pytest.raises(ValueError):
        DisplayController(mode="hardwrae")
    monkeypatch.setenv("INKY_STUDIO_DISPLAY_PROFILE", "unknown")
    with pytest.raises(ValueError):
        DisplayController()
    monkeypatch.setenv("INKY_STUDIO_DISPLAY_PROFILE", "ac073-800x480")
    with pytest.raises(ValueError):
        DisplayController(mode="mock")


def ac073_driver(monkeypatch, *, color=4, width=800, height=480, variant=20, module="inky.inky_ac073tc1a"):
    eeprom = SimpleNamespace(width=width, height=height, display_variant=variant, color=color)
    driver = type("Inky", (), {"__module__": module, "width": 800, "height": 480, "eeprom": eeprom})()
    install_auto(monkeypatch, driver=driver)
    monkeypatch.setattr("inky_web.inky.display.version", lambda name: "2.3.0")
    return driver


@pytest.mark.parametrize("color", [4, 5])
def test_explicit_bench_profile_preserves_raw_eeprom_and_uses_driver_palette(monkeypatch, color):
    driver = ac073_driver(monkeypatch, color=color)
    before = dict(vars(driver.eeprom))
    monkeypatch.setenv("INKY_STUDIO_DISPLAY_PROFILE", "ac073-800x480")
    display = DisplayController(mode="hardware")
    display.initialize()
    assert display.info()["colors"] == 7
    assert display.info()["is_mock"] is False
    assert vars(driver.eeprom) == before
    assert display.status()["driver"]["color_raw"] == color
    assert display.status()["busy_monitor"] == "ac073_2.3.0"


def test_unmapped_color_requires_explicit_profile(monkeypatch):
    ac073_driver(monkeypatch)
    display = DisplayController(mode="hardware")
    display.initialize()
    assert display.status()["state"] == "error"
    assert display.status()["driver"]["color_raw"] == 4
    with pytest.raises(DisplayUnavailableError):
        display.info()


@pytest.mark.parametrize("overrides", [
    {"width": 600}, {"height": 448}, {"variant": 26}, {"color": 6},
    {"width": 800.0}, {"height": 480.0}, {"variant": 20.0}, {"color": 4.0},
    {"module": "inky.inky_e673"},
])
def test_bench_profile_rejects_mismatching_or_noninteger_tuple(monkeypatch, overrides):
    ac073_driver(monkeypatch, **overrides)
    monkeypatch.setenv("INKY_STUDIO_DISPLAY_PROFILE", "ac073-800x480")
    display = DisplayController(mode="hardware")
    display.initialize()
    assert display.status()["state"] == "error"
    assert display.is_mock is False


def test_busy_observer_rejects_unqualified_library_upgrade(monkeypatch):
    ac073_driver(monkeypatch, color=5)
    monkeypatch.setattr("inky_web.inky.display.version", lambda name: "2.4.0")
    display = DisplayController(mode="hardware")
    display.initialize()
    assert display.status()["state"] == "error"
    assert display.status()["driver"]["inky_version"] == "2.4.0"


def test_display_diagnostics_are_not_public(client, monkeypatch):
    monkeypatch.setenv("INKY_STUDIO_DISABLE_AUTH", "0")
    assert client.get("/api/display/status").status_code == 401


def test_initialization_fault_keeps_health_and_diagnostics_but_blocks_api(monkeypatch, png_factory):
    from inky_web.main import app

    monkeypatch.setenv("INKY_STUDIO_DISPLAY_MODE", "hardware")
    install_auto(monkeypatch, error=OSError("private device path"))
    with TestClient(app) as client:
        client.portal.call(app.state.scheduler.stop)
        assert client.get("/api/health").status_code == 200
        status = client.get("/api/display/status")
        assert status.status_code == 200
        assert status.json()["is_mock"] is False
        assert "width" not in status.json()
        for endpoint in ("/api/state", "/api/display"):
            response = client.get(endpoint)
            assert response.status_code == 503
            assert "private" not in response.text
        for endpoint in ("/api/display/next", "/api/display/previous"):
            assert client.post(endpoint).status_code == 503  # even an empty queue
        response = client.post("/api/queue", files={"file": ("test.png", png_factory(), "image/png")})
        assert response.status_code == 503
        assert queue.count() == 0 and history.current() is None


def test_refresh_error_503_preserves_queue_and_no_success_event(client, png_factory):
    from inky_web.main import app

    photo, _ = photos.save(content=png_factory(), original_filename="retained.png")
    queue.add(photo.id)
    driver = SimpleNamespace(set_image=Mock(), show=Mock(side_effect=SystemExit(1)))
    display = app.state.display
    display._impl, display._is_mock = driver, False
    display._observations = [{"phase": "refresh", "outcome": "edge_received"}]
    app.state.bus.broadcast = Mock()

    response = client.post("/api/display/next")
    assert response.status_code == 503
    assert response.json()["code"] == "display_refresh_failed"
    assert [entry.photo.id for entry in queue.list_all()] == [photo.id]
    assert history.current() is None
    assert [call.args[0] for call in app.state.bus.broadcast.call_args_list] == ["display_error"]
    assert client.get("/api/state").status_code == 503
    assert client.post("/api/display/next").status_code == 503
    assert driver.show.call_count == 1  # sticky failure prevents retry
    assert client.get("/api/display/status").json()["error"]["code"] == "display_refresh_failed"


@pytest.mark.parametrize(("outcome", "code"), [("edge_timeout", "display_busy_timeout"), ("held_high_unverified", "display_busy_unverified")])
def test_busy_fault_is_deferred_until_sequence_return_and_preserves_queue(
    client, png_factory, outcome, code,
):
    from inky_web.main import app

    photo, _ = photos.save(content=png_factory(), original_filename="retained.png")
    queue.add(photo.id)
    trace = []
    display = app.state.display
    display._impl = SimpleNamespace(set_image=Mock())
    display._is_mock = False
    observations = [
        {"phase": phase, "timeout": timeout, "outcome": outcome if phase == "refresh" else "edge_received", "sequence": seq}
        for seq, (phase, timeout) in enumerate(zip(("setup", "power_on", "refresh", "power_off"), (1, .4, 45, .4), strict=True), 1)
    ]

    def run_show():
        trace.extend(["refresh", "power_off", "power_off_wait", "return"])
        return observations

    display._busy_observer = SimpleNamespace(run_show=run_show, observations=observations)
    response = client.post("/api/display/next")
    assert trace[-1] == "return"
    assert response.status_code == 503
    assert response.json()["code"] == code
    assert queue.count() == 1 and history.current() is None
    assert client.get("/api/display/status").json()["observations"][2]["outcome"] == outcome


@pytest.mark.asyncio
async def test_automatic_refresh_fault_notifies_without_consuming_queue(data_dir, png_factory, monkeypatch):
    from inky_web.events import EventBus

    photo, _ = photos.save(content=png_factory(), original_filename="retained.png")
    queue.add(photo.id)
    display = DisplayController(mode="mock")
    display._impl = SimpleNamespace(set_image=Mock(), show=Mock(side_effect=OSError()))
    display._is_mock = False
    bus = EventBus()
    bus.broadcast = Mock()
    runner = scheduler.Scheduler(display, bus)
    monkeypatch.setattr(scheduler, "_compute_next_change", lambda *args: 0)
    # _advance is the actual automatic path after its clock becomes due.
    with pytest.raises(DisplayUnavailableError):
        runner._advance("auto")
    assert queue.count() == 1 and history.current() is None
    assert [call.args[0] for call in bus.broadcast.call_args_list] == ["display_error"]


def test_diagnostics_do_not_wait_on_hardware_lock_and_second_refresh_cannot_overlap(data_dir, png_factory):
    photo, _ = photos.save(content=png_factory(), original_filename="photo.png")
    entered, release = Event(), Event()

    def show():
        entered.set()
        assert release.wait(3)
        raise OSError("hardware failure")

    display = DisplayController(mode="mock")
    driver = SimpleNamespace(set_image=Mock(), show=Mock(side_effect=show))
    display._impl, display._is_mock = driver, False
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(display.display_image, photos.path_for(photo.id))
        try:
            assert entered.wait(3)
            assert display.status()["state"] == "busy"
            assert display.status()["observations"] == []
            second = pool.submit(display.display_image, photos.path_for(photo.id))
            assert driver.show.call_count == 1
        finally:
            release.set()
        for future in (first, second):
            with pytest.raises(DisplayUnavailableError):
                future.result(timeout=3)
    assert driver.show.call_count == 1
