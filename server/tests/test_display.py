"""Exercise the real controller with an in-memory driver, without touching GPIO."""
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import ModuleType

import pytest

from inky_web.inky.display import DisplayController
from inky_web.services import photos


@pytest.mark.parametrize(
    ("module", "width", "height", "model", "colors"),
    [
        ("inky.inky_ac073tc1a", 800, 480, 'Inky Impression 7.3" (7-color)', 7),
        ("inky.inky_e673", 800, 480, 'Inky Impression 7.3" (Spectra 6)', 6),
        ("inky.inky_el133uf1", 1600, 1200, 'Inky Impression 13.3" (Spectra 6)', 6),
        ("inky.inky_uc8159", 600, 448, 'Inky Impression 5.7" (7-color)', 7),
        ("inky.inky_uc8159", 640, 400, 'Inky Impression 4" (7-color)', 7),
    ],
)
def test_detected_driver_metadata_matches_pimoroni_230(
    monkeypatch, module, width, height, model, colors,
):
    """Drivers in the pinned wheel expose dimensions, but no name/colour_count.

    Exercise the normal auto-detection path without importing Linux dependencies
    or refreshing a physical panel. Expected panel families and dimensions come
    from inky 2.3.0's EEPROM auto mapping and driver palettes.
    """
    driver = type("Inky", (), {"__module__": module, "width": width, "height": height})()
    package = ModuleType("inky")
    package.__path__ = []
    auto_module = ModuleType("inky.auto")
    auto_calls = []

    def auto(**kwargs):
        auto_calls.append(kwargs)
        return driver

    auto_module.auto = auto
    monkeypatch.setitem(sys.modules, "inky", package)
    monkeypatch.setitem(sys.modules, "inky.auto", auto_module)
    monkeypatch.setattr("inky_web.inky.display.platform.system", lambda: "Linux")

    display = DisplayController()
    display.initialize()

    assert auto_calls == [{"ask_user": False, "verbose": False}]
    assert display.info() == {
        "model": model,
        "width": width,
        "height": height,
        "colors": colors,
        "is_mock": False,
    }


def test_hardware_buffer_and_refresh_are_serialized(data_dir, png_factory):
    first, _ = photos.save(content=png_factory(color=(10, 0, 0)), original_filename="first.png")
    second, _ = photos.save(content=png_factory(color=(20, 0, 0)), original_filename="second.png")
    first_entered, second_entered, release_first, second_started = (Event() for _ in range(4))

    class Driver:
        buffer = None

        def __init__(self):
            self.shown = []

        def set_image(self, img, **kwargs):
            self.buffer = img.getpixel((0, 0))
            if self.buffer == (10, 0, 0):
                first_entered.set()
                assert release_first.wait(3)
            else:
                second_entered.set()

        def show(self):
            self.shown.append(self.buffer)

    driver = Driver()
    display = DisplayController()
    display._impl = driver
    display._is_mock = False

    def show_second():
        second_started.set()
        display.display_image(photos.path_for(second.id))

    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(display.display_image, photos.path_for(first.id))
        try:
            assert first_entered.wait(3)
            two = pool.submit(show_second)
            assert second_started.wait(3)
            assert not second_entered.wait(0.1)
        finally:
            release_first.set()
        one.result(timeout=3)
        two.result(timeout=3)

    assert driver.shown == [(10, 0, 0), (20, 0, 0)]
