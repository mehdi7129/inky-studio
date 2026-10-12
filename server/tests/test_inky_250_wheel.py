"""Real PyPI wheel/EEPROM/driver code; no installation or physical GPIO/SPI.

CI downloads the hash-locked wheel before pytest. Tests perform no network I/O
and load the verified archive itself with inert hardware ports. Packing tests
capture the buffers at _update without issuing SPI commands. This is not
evidence of a complete ARM64 dependency closure or a physical panel refresh.
"""
from __future__ import annotations

import ast
import base64
import csv
import hashlib
import importlib
import io
import json
import struct
import sys
import zipfile
from email.parser import Parser
from enum import Enum
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from tests.fixtures import inky_busy_250

SERVER = Path(__file__).resolve().parents[1]
PROVENANCE = json.loads((SERVER / "tests/fixtures/inky_250_provenance.json").read_text())
WHEEL_SHA256 = "8589ad753b094ec5da482c090f88d5e8560457f15502221517993dc01b021573"

# EEPROM variant, logical width/height, real driver module, palette size.
PANELS = [
    (25, 600, 400, "inky_e640", 6),
    (22, 800, 480, "inky_e673", 6),
    (26, 800, 480, "inky_e673", 6),
    (21, 1600, 1200, "inky_el133uf1", 6),
    (27, 1600, 1200, "inky_el133uf1", 6),
    (20, 800, 480, "inky_ac073tc1a", 7),
    (14, 600, 448, "inky_uc8159", 7),
    (15, 640, 400, "inky_uc8159", 7),
    (16, 640, 400, "inky_uc8159", 7),
]
PANEL_IDS = [f"variant-{panel[0]}" for panel in PANELS]
BUSY_MODULES = {
    "ac073": "inky_ac073tc1a",
    "uc8159": "inky_uc8159",
    "e640": "inky_e640",
    "e673": "inky_e673",
    "el133uf1": "inky_el133uf1",
}
SPECTRA_RGB = [(0, 0, 0), (255, 255, 255), (255, 255, 0),
              (255, 0, 0), (0, 0, 255), (0, 255, 0)]
SEVEN_RGB = [(0, 0, 0), (255, 255, 255), (0, 255, 0),
             (0, 0, 255), (255, 0, 0), (255, 255, 0), (255, 140, 0)]


def _verified_wheel() -> Path:
    wheel = SERVER / ".test-wheels" / PROVENANCE["wheel"]
    if not wheel.is_file():
        pytest.fail(
            "Missing Inky test wheel. Before pytest, run from server: "
            "python -m pip download --no-deps --require-hashes "
            "-r tests/fixtures/inky_250_requirement.txt -d .test-wheels"
        )
    assert PROVENANCE["sha256"] == WHEEL_SHA256
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == WHEEL_SHA256
    with zipfile.ZipFile(wheel) as archive:
        records = list(csv.reader(io.StringIO(archive.read(
            "inky-2.5.0.dist-info/RECORD").decode())))
        assert {name for name, _, _ in records} == set(archive.namelist())
        for name, digest, size in records:
            if name.endswith("/RECORD"):
                assert not digest and not size
                continue
            content = archive.read(name)
            expected = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
            assert digest == f"sha256={expected}", name
            assert int(size) == len(content), name
        for name, expected in PROVENANCE["module_sha256"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected, name
    return wheel


class _Value(Enum):
    INACTIVE = 0
    ACTIVE = 1


class _Direction(Enum):
    INPUT = 0
    OUTPUT = 1


class _Bias(Enum):
    DISABLED = 0
    PULL_UP = 1


class _Edge(Enum):
    RISING = 0
    FALLING = 1
    BOTH = 2


def _forbidden(*_args, **_kwargs):
    pytest.fail("Wheel conformance must not open GPIO/SPI or start a hardware refresh")


@pytest.fixture
def upstream(monkeypatch):
    wheel = _verified_wheel()
    # Restore any previously imported Inky package when the fixture exits.
    for name in tuple(sys.modules):
        if name == "inky" or name.startswith("inky."):
            monkeypatch.delitem(sys.modules, name)

    line = ModuleType("gpiod.line")
    line.Value, line.Direction, line.Bias, line.Edge = _Value, _Direction, _Bias, _Edge
    gpio = ModuleType("gpiod")
    gpio.line, gpio.LineSettings = line, _forbidden
    device = ModuleType("gpiodevice")
    device.find_chip_by_platform = device.check_pins_available = device.wait_for_edge = _forbidden
    spi = ModuleType("spidev")
    spi.SpiDev = _forbidden
    state = {"raw": b"", "reads": 0}

    class EEPROMBus:
        def __init__(self, number):
            assert number == 1

        def write_i2c_block_data(self, address, register, values):
            assert (address, register, values) == (0x50, 0, [0])

        def read_i2c_block_data(self, address, register, length):
            assert (address, register, length) == (0x50, 0, 29)
            state["reads"] += 1
            return list(state["raw"])

    smbus = ModuleType("smbus2")
    smbus.SMBus = EEPROMBus
    for name, module in (("gpiod", gpio), ("gpiod.line", line), ("gpiodevice", device),
                         ("spidev", spi), ("smbus2", smbus)):
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.syspath_prepend(str(wheel))
    try:
        package = importlib.import_module("inky")
        auto = importlib.import_module("inky.auto")
        eeprom = importlib.import_module("inky.eeprom")
        assert package.__version__ == "2.5.0"
        for name, module in sys.modules.items():
            if name == "inky" or name.startswith("inky."):
                assert str(module.__file__).startswith(f"{wheel}/"), name

        def raw_eeprom(variant, width, height, color):
            state["raw"] = struct.pack("<HHBBB22p", width, height, color, 12, variant,
                                       b"2026-10-12 00:00:00")
            state["reads"] = 0

        def display(panel, *, raw_color=None):
            variant, width, height, _module, colors = panel
            raw_eeprom(variant, width, height, raw_color if raw_color is not None else 6 if colors == 6 else 5)
            return auto.auto(ask_user=False, verbose=False)

        yield SimpleNamespace(package=package, auto=auto, eeprom=eeprom, state=state,
                              raw_eeprom=raw_eeprom, display=display)
    finally:
        for name in tuple(sys.modules):
            if name == "inky" or name.startswith("inky."):
                sys.modules.pop(name, None)


def test_cached_artifact_is_the_official_hash_locked_wheel():
    with zipfile.ZipFile(_verified_wheel()) as archive:
        metadata = Parser().parsestr(archive.read("inky-2.5.0.dist-info/METADATA").decode())
        assert (metadata["Name"], metadata["Version"], metadata["Requires-Python"]) == (
            "inky", "2.5.0", ">=3.9")
        assert "gpiodevice>=0.1.0" in metadata.get_all("Requires-Dist")
        assert "MIT License" in archive.read(PROVENANCE["license"]).decode()
    requirement = (SERVER / "tests/fixtures/inky_250_requirement.txt").read_text()
    assert f"inky==2.5.0 --hash=sha256:{WHEEL_SHA256}" in requirement


@pytest.mark.parametrize("family,module_name", BUSY_MODULES.items())
def test_busy_fixture_methods_constants_and_pin_match_the_real_wheel(upstream, family, module_name):
    # Concordance of source, not execution of the native gpiodevice helper or
    # GPIO/SPI acquisition. Inert BUSY collaborators remain a separate proof.
    module = importlib.import_module(f"inky.{module_name}")
    wheel = _verified_wheel()
    assert str(module.__file__).startswith(f"{wheel}/")
    source_path = f"inky/{module_name}.py"
    with zipfile.ZipFile(wheel) as archive:
        source = archive.read(source_path)
    assert hashlib.sha256(source).hexdigest() == inky_busy_250.FILE_SHA256[family]
    assert inky_busy_250.FILE_SHA256[family] == PROVENANCE["module_sha256"][source_path]

    real_class = next(node for node in ast.parse(source).body
                      if isinstance(node, ast.ClassDef) and node.name == "Inky")
    fixture_class, = ast.parse(inky_busy_250.SOURCES[family]).body
    relevant = {"_busy_wait", "_refresh_wait", "_update"}
    real_methods = {node.name: node for node in real_class.body
                    if isinstance(node, ast.FunctionDef) and node.name in relevant}
    fixture_methods = {node.name: node for node in fixture_class.body}
    assert fixture_methods.keys() == real_methods.keys()
    for name, method in fixture_methods.items():
        assert ast.dump(method, include_attributes=False) == ast.dump(
            real_methods[name], include_attributes=False), (family, name)

    constant_names = {node.id for method in fixture_methods.values() for node in ast.walk(method)
                      if isinstance(node, ast.Name) and node.id.isupper()}
    assert inky_busy_250.CONSTANTS[family] == {
        name: getattr(module, name) for name in constant_names
    }
    assert inky_busy_250.BUSY_PINS[family] == module.BUSY_PIN
    initializer = next(node for node in real_class.body
                       if isinstance(node, ast.FunctionDef) and node.name == "__init__")
    defaults = dict(zip([arg.arg for arg in initializer.args.args[-len(initializer.args.defaults):]],
                        initializer.args.defaults, strict=True))
    assert ast.dump(defaults["busy_pin"], include_attributes=False) == ast.dump(
        ast.Name(id="BUSY_PIN", ctx=ast.Load()), include_attributes=False)


@pytest.mark.parametrize("panel", PANELS, ids=PANEL_IDS)
def test_real_auto_reads_raw_eeprom_and_constructs_real_driver(upstream, panel):
    variant, width, height, module, colors = panel
    driver = upstream.display(panel)
    assert type(driver).__module__ == f"inky.{module}"
    assert (driver.width, driver.height, driver.resolution, driver.rotation) == (
        width, height, (width, height), 0)
    assert (driver.cols, driver.rows) == (width, height)
    assert driver.buf.shape == (height, width)
    assert (driver.eeprom.width, driver.eeprom.height, driver.eeprom.display_variant,
            driver.eeprom.color) == (width, height, variant, 6 if colors == 6 else 5)
    assert driver.eeprom.get_color() == ("spectra6" if colors == 6 else "7colour")
    assert upstream.state["reads"] == 2  # Real auto read and real constructor read.


@pytest.mark.parametrize("panel", PANELS, ids=PANEL_IDS)
def test_studio_controller_accepts_the_real_autodetected_250_driver(upstream, panel):
    from inky_web.inky.display import DisplayController

    variant, width, height, module, colors = panel
    upstream.raw_eeprom(variant, width, height, 6 if colors == 6 else 5)
    display = DisplayController(mode="hardware")
    display.initialize()
    info, status = display.info(), display.status()
    assert (info["width"], info["height"], info["colors"], info["is_mock"]) == (
        width, height, colors, False)
    assert status["state"] == "ready"
    assert status["driver"]["module"] == f"inky.{module}"
    assert status["driver"]["display_variant"] == variant
    assert status["driver"]["inky_version"] == "2.5.0"
    assert status["busy_monitor"] == f"{module.removeprefix('inky_').replace('tc1a', '')}_2.5.0"
    assert upstream.state["reads"] == 2


def test_studio_explicit_ac073_bench_keeps_the_real_unmapped_eeprom(upstream, monkeypatch):
    from inky_web.inky.display import DisplayController

    upstream.raw_eeprom(20, 800, 480, 4)
    original = upstream.state["raw"]
    monkeypatch.setenv("INKY_STUDIO_DISPLAY_PROFILE", "ac073-800x480")
    display = DisplayController(mode="hardware")
    display.initialize()
    assert display.info()["colors"] == 7
    assert display.status()["driver"]["color_raw"] == 4
    assert display.status()["driver"]["color_interpretation"] == "unmapped"
    assert upstream.state["raw"] == original


@pytest.mark.parametrize("raw,meaning", [(4, None), (5, "7colour"), (6, "spectra6")])
def test_raw_eeprom_color_mapping_is_not_rewritten(upstream, raw, meaning):
    upstream.raw_eeprom(20, 800, 480, raw)
    original = upstream.state["raw"]
    driver = upstream.auto.auto(ask_user=False, verbose=False)
    assert type(driver).__module__ == "inky.inky_ac073tc1a"
    assert driver.eeprom.color == raw and driver.eeprom.get_color() == meaning
    assert upstream.state["raw"] == original


@pytest.mark.parametrize("panel", PANELS, ids=PANEL_IDS)
@pytest.mark.parametrize("saturation", [0.0, 1.0])
def test_real_rgb_quantization_preserves_palette_order_and_native_codes(upstream, panel, saturation):
    driver = upstream.display(panel)
    colors = panel[4]
    pure = SPECTRA_RGB if colors == 6 else SEVEN_RGB
    assert driver._palette_blend(0)[:colors * 3] == [value for rgb in pure for value in rgb]
    palette = driver._palette_blend(saturation)
    pixels = np.zeros((driver.height, driver.width, 3), dtype=np.uint8)
    cuts = np.linspace(0, driver.width, colors + 1, dtype=int)
    for index in range(colors):
        pixels[:, cuts[index]:cuts[index + 1], :] = palette[index * 3:index * 3 + 3]
    driver.set_image(Image.fromarray(pixels), saturation=saturation)
    expected_codes = [0, 1, 2, 3, 5, 6] if colors == 6 else list(range(7))
    centers = [(int(cuts[index]) + int(cuts[index + 1])) // 2 for index in range(colors)]
    assert driver.buf[driver.height // 2, centers].tolist() == expected_codes
    assert set(np.unique(driver.buf)) <= set(expected_codes)


@pytest.mark.parametrize("panel", PANELS, ids=PANEL_IDS)
def test_real_show_preserves_logical_orientation_or_rotates_and_splits_panel(upstream, panel, monkeypatch):
    driver = upstream.display(panel)
    driver.buf[0, 0], driver.buf[0, -1] = 1, 2
    driver.buf[-1, 0], driver.buf[-1, -1] = 3, 6
    calls = []
    monkeypatch.setattr(driver, "_update", lambda *buffers: calls.append(buffers))
    if panel[3] == "inky_el133uf1":
        # Mark both sides of the physical controller split, after clockwise rotation.
        driver.buf[600, 0], driver.buf[599, 0] = 5, 2
        driver.buf[600, -1], driver.buf[599, -1] = 1, 3
    driver.show()
    assert len(calls) == 1
    buffers = calls[0]
    if panel[3] == "inky_el133uf1":
        assert len(buffers) == 2
        left, right = buffers
        assert len(left) == len(right) == 1600 * 600 // 2
        assert (left[0], left[299], left[-300], left[-1]) == (0x30, 0x05, 0x60, 0x01)
        assert (right[0], right[299], right[-300], right[-1]) == (0x20, 0x01, 0x30, 0x02)
    else:
        assert len(buffers) == 1
        packed, = buffers
        assert len(packed) == driver.width * driver.height // 2
        if panel[3] == "inky_e640":
            assert (packed[0], packed[199], packed[-200], packed[-1]) == (0x30, 0x01, 0x60, 0x02)
        else:
            stride = driver.width // 2
            assert (packed[0], packed[stride - 1], packed[-stride], packed[-1]) == (
                0x10, 0x02, 0x30, 0x06)


@pytest.mark.parametrize("panel", PANELS, ids=PANEL_IDS)
def test_real_set_image_rejects_wrong_panel_dimensions(upstream, panel):
    driver = upstream.display(panel)
    with pytest.raises(ValueError, match="Image must be"):
        driver.set_image(Image.new("RGB", (driver.width - 1, driver.height)), saturation=1.0)


def test_real_auto_refuses_unknown_eeprom_variant(upstream):
    upstream.raw_eeprom(99, 800, 480, 6)
    with pytest.raises(RuntimeError, match="Can't find a driver"):
        upstream.auto.auto(ask_user=False, verbose=False)
