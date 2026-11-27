"""Exercise 2.6.0 EEPROM autodetection with actual driver code and inert buses."""

import hashlib
import zipfile

import pytest

from inky_web.inky.display import PIMORONI_AUTO_PROFILE, DisplayController
from inky_web.inky.errors import DisplayUnavailableError
from tests.test_inky_250_wheel import _load_upstream, _verified_wheel

PANELS = [
    (1, "phat", 212, 104, 2), (4, "phat", 212, 104, 1), (5, "phat", 212, 104, 3),
    (10, "phat", 250, 122, 1), (11, "phat", 250, 122, 2), (12, "phat", 250, 122, 3),
    (2, "what", 400, 300, 3), (3, "what", 400, 300, 1),
    (6, "what", 400, 300, 2), (7, "what", 400, 300, 2), (8, "what", 400, 300, 2),
    (17, "inky_ssd1683", 400, 300, 1), (18, "inky_ssd1683", 400, 300, 2),
    (19, "inky_ssd1683", 400, 300, 3),
    (14, "inky_uc8159", 600, 448, 5), (15, "inky_uc8159", 640, 400, 5),
    (16, "inky_uc8159", 640, 400, 5),
    (20, "inky_ac073tc1a", 800, 480, 4), (20, "inky_ac073tc1a", 800, 480, 5),
    (21, "inky_el133uf1", 1600, 1200, 6), (27, "inky_el133uf1", 1600, 1200, 6),
    (22, "inky_e673", 800, 480, 6), (26, "inky_e673", 800, 480, 6),
    (23, "inky_jd79661", 250, 122, 7), (24, "inky_jd79668", 400, 300, 7),
    (25, "inky_e640", 600, 400, 6), (28, "inky_ssd2683", 400, 300, 7),
]


@pytest.mark.parametrize("variant,module,width,height,color", PANELS)
def test_universal_profile_accepts_the_official_eeprom_route(monkeypatch, variant, module, width, height, color):
    with _load_upstream(monkeypatch, "2.6.0") as upstream:
        upstream.raw_eeprom(variant, width, height, color)
        monkeypatch.setenv("INKY_STUDIO_DISPLAY_PROFILE", PIMORONI_AUTO_PROFILE)
        controller = DisplayController(mode="hardware")
        controller.initialize()
        controller.require_available()
        assert controller.spec.width == width
        assert controller.spec.height == height
        diagnostics = controller.status()["driver"]
        assert diagnostics["display_variant"] == variant
        assert diagnostics["module"] == f"inky.{module}"
        assert diagnostics["inky_version"] == "2.6.0"
        assert controller._allow_ac073_timed_wait is (variant == 20)


@pytest.mark.parametrize("variant,width,height,color", [(26, 640, 400, 6), (99, 800, 480, 6), (20, 800, 480, 6)])
def test_invalid_identity_in_universal_profile_is_never_simulated(monkeypatch, variant, width, height, color):
    with _load_upstream(monkeypatch, "2.6.0") as upstream:
        upstream.raw_eeprom(variant, width, height, color)
        monkeypatch.setenv("INKY_STUDIO_DISPLAY_PROFILE", PIMORONI_AUTO_PROFILE)
        controller = DisplayController(mode="hardware")
        controller.initialize()
        with pytest.raises(DisplayUnavailableError):
            controller.require_available()
        assert controller.status()["state"] == "error"
        assert not controller.is_mock


def test_legacy_spi_guard_can_use_the_unchanged_official_ac073_source():
    path = "inky/inky_ac073tc1a.py"
    with zipfile.ZipFile(_verified_wheel()) as legacy, zipfile.ZipFile(_verified_wheel("2.6.0")) as current:
        assert hashlib.sha256(current.read(path)).hexdigest() == "07ef76f3854d279e19cc082b5bc96b8bc20b6aed967747357e5dff4cb9c65324"
        assert legacy.read(path) == current.read(path)
        assert legacy.read("inky/inky_uc8159.py") == current.read("inky/inky_uc8159.py")
