"""Pinned full AC073 show: inert ports, real packing/commands/BUSY/controller.

SPI call counts describe this inert Python boundary only. They neither measure
Pi throughput nor qualify the physical panel, kernel splitting or electrical CS.
"""
from __future__ import annotations

import importlib
import sys
from types import MethodType, SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from inky_web.inky.busy import BusyObserver
from inky_web.inky.confirmation import ConfirmationBarrier
from inky_web.inky.display import AC073_TIMED_WAIT_PROFILE, DisplayController
from inky_web.inky.errors import DisplayUnavailableError
from tests import test_inky_250_wheel as wheel
from tests.test_display_busy import EdgeEvent

PIXEL_BYTES = 192_000
PHASES = ("setup", "power_on", "refresh", "power_off")


class RecordingSPI:
    def __init__(self, trace, *, fail_bulk=False, fail_xfer_data=False, no_cs="normal"):
        self.trace, self.gpio = trace, None
        self.fail_bulk, self.fail_xfer_data = fail_bulk, fail_xfer_data
        self.no_cs_mode, self._no_cs = no_cs, False
        self.messages = []
        self.bulk_calls = []
        self.xfer_calls = 0
        self.payload = bytearray()
        self.current_xfers = self.current_bulk = 0
        self.max_speed_hz = None
        self.mode, self.bits_per_word = 0, 8
        self.cshigh = self.lsbfirst = self.threewire = self.loop = False

    @property
    def no_cs(self):
        if self.no_cs_mode == "missing":
            raise AttributeError("no_cs")
        return self._no_cs

    @no_cs.setter
    def no_cs(self, value):
        if self.no_cs_mode == "error":
            raise OSError("inert no_cs refusal")
        self._no_cs = False if self.no_cs_mode == "false" else value
        self.trace.append(("spi_no_cs", self._no_cs))

    def open(self, bus, channel):
        self.trace.append(("spi_open", bus, channel))

    def begin(self):
        self.payload = bytearray()
        self.current_xfers = self.current_bulk = 0

    def end(self):
        message = (self.gpio.dc, bytes(self.payload), self.current_xfers, self.current_bulk)
        self.messages.append(message)
        self.trace.append(("spi_message", message[0], message[1]))

    def xfer(self, values):
        assert self.gpio.cs == 0 and len(values) == 1
        if self.fail_xfer_data and self.gpio.dc == 1 and len(self.payload) == 4096:
            raise OSError("inert partial xfer")
        self.xfer_calls += 1
        self.current_xfers += 1
        self.payload.extend(values)
        return list(values)

    def writebytes2(self, values):
        assert self.gpio.cs == 0 and self.gpio.dc == 1
        self.bulk_calls.append(bytes(values))
        self.current_bulk += 1
        if self.fail_bulk:
            self.payload.extend(values[:4096])
            raise OSError("inert partial bulk")
        self.payload.extend(values)


class RecordingGPIO:
    def __init__(self, trace, spi, value_enum, *, held=True, timeout_phase=None):
        self.trace, self.spi, self.value_enum = trace, spi, value_enum
        self.held, self.timeout_phase = held, timeout_phase
        self.cs, self.dc = 1, 0
        self.busy_reads = 0
        self.phase = None
        self.cs_pin, self.dc_pin, self.busy_pin = 8, 22, 17
        spi.gpio = self

    def set_value(self, pin, value):
        self.trace.append(("gpio_set", pin, value.value))
        if pin == self.cs_pin:
            self.cs = value.value
            if self.cs == 0:
                self.spi.begin()
            else:
                self.spi.end()
        elif pin == self.dc_pin:
            self.dc = value.value

    def get_value(self, pin):
        assert pin == self.busy_pin
        self.phase = PHASES[self.busy_reads]
        self.busy_reads += 1
        value = self.value_enum.ACTIVE if self.held else self.value_enum.INACTIVE
        self.trace.append(("gpio_get", pin, self.phase, value.value))
        return value

    def wait_for_edge(self, request, pin, timeout):
        assert request is self and pin == self.busy_pin
        self.trace.append(("edge_wait", pin, self.phase, timeout))
        return None if self.phase == self.timeout_phase else EdgeEvent(line=pin)


@pytest.fixture
def real_ac073(monkeypatch):
    """Load hash/RECORD-verified wheel itself; do not replace command methods."""
    with wheel._load_upstream(monkeypatch) as loaded:
        module = importlib.import_module("inky.inky_ac073tc1a")
        spidev = sys.modules["spidev"]
        monkeypatch.setattr(module.gpiod, "EdgeEvent", EdgeEvent, raising=False)

        def make(*, lazy_spi=False, held=True, timeout_phase=None, fail_bulk=False,
                 fail_xfer_data=False, no_cs="normal"):
            trace = []
            spi = RecordingSPI(trace, fail_bulk=fail_bulk,
                               fail_xfer_data=fail_xfer_data, no_cs=no_cs)
            gpio = RecordingGPIO(trace, spi, module.Value, held=held, timeout_phase=timeout_phase)
            driver = loaded.display((20, 800, 480, "inky_ac073tc1a", 7))
            driver._gpio = gpio
            driver._spi_bus = None if lazy_spi else spi
            pixels = (np.arange(800 * 480, dtype=np.uint32) % 9).astype("uint8")
            pixels[pixels == 8] = 7
            pixels = pixels.reshape(480, 800)
            driver.set_image(Image.frombytes("P", (800, 480), pixels.tobytes()))
            state = SimpleNamespace(driver=driver, spi=spi, gpio=gpio, trace=trace,
                                    module=module, pixels=pixels, lazy_creations=[])

            def create_spi():
                state.lazy_creations.append(True)
                return spi

            def activate():
                monkeypatch.setattr(module, "time", SimpleNamespace(
                    sleep=lambda duration: trace.append(("sleep", duration))))
                monkeypatch.setattr(module, "gpiodevice", SimpleNamespace(wait_for_edge=gpio.wait_for_edge))
                monkeypatch.setattr(spidev, "SpiDev", create_spi)
            state.activate = activate
            return state

        yield make


def configure_versions(monkeypatch, *, inky="2.5.0", spidev="3.8"):
    from inky_web.inky import spi

    monkeypatch.setattr(spi, "version", lambda name: {"inky": inky, "spidev": spidev}[name])


def run_bulk(harness, *, callback=None):
    from inky_web.inky.spi import AC073BulkSPI

    harness.activate()
    return AC073BulkSPI(harness.driver).run_show(callback or harness.driver.show)


def image_message(harness):
    matches = [message for message in harness.spi.messages if message[0] == 1 and len(message[1]) == PIXEL_BYTES]
    assert len(matches) == 1
    return matches[0]


@pytest.mark.filterwarnings("ignore:Busy Wait")
@pytest.mark.parametrize("held", [False, True])
def test_full_upstream_show_bulk_preserves_every_packed_byte_gpio_command_and_wait(
    real_ac073, monkeypatch, held,
):
    configure_versions(monkeypatch)
    baseline = real_ac073(held=held)
    baseline.activate()
    baseline_observations = BusyObserver(baseline.driver, "ac073").run_show()
    adapted = real_ac073(held=held)
    original_method = adapted.driver._spi_write
    observations = run_bulk(adapted, callback=BusyObserver(adapted.driver, "ac073").run_show)

    flat = adapted.pixels.flatten()
    assert (flat[::2] == 7).any() and (flat[1::2] == 7).any()
    clean_as_white = np.where(flat == 7, 1, flat).astype("uint8")
    expected = ((clean_as_white[::2] << 4) | clean_as_white[1::2]).tobytes()
    assert len(expected) == PIXEL_BYTES
    assert image_message(baseline) == (1, expected, PIXEL_BYTES, 0)
    assert image_message(adapted) == (1, expected, 0, 1)
    assert adapted.spi.bulk_calls == [expected]
    assert observations == baseline_observations
    assert adapted.trace == baseline.trace
    assert [event[1] for event in adapted.trace if event[0] == "sleep"] == (
        [0.1, 0.1, 0.1] + ([1.0, 0.4, 45.0, 0.4] if held else [])
    )
    assert [message[1][0] for message in adapted.spi.messages if message[0] == 0][-4:] == [0x10, 0x04, 0x12, 0x02]
    assert adapted.spi.no_cs is True and adapted.spi.max_speed_hz == 5_000_000
    assert "_spi_write" not in vars(adapted.driver)
    assert adapted.driver._spi_write == original_method
    assert "_busy_wait" not in vars(adapted.driver) and adapted.driver._gpio is adapted.gpio
    np.testing.assert_array_equal(adapted.driver.buf, adapted.pixels)


@pytest.mark.filterwarnings("ignore:Busy Wait")
def test_bulk_qualification_occurs_after_real_lazy_spi_setup(real_ac073, monkeypatch):
    configure_versions(monkeypatch)
    h = real_ac073(lazy_spi=True)
    assert h.driver._spi_bus is None
    run_bulk(h)
    assert h.lazy_creations == [True] and h.driver._spi_bus is h.spi
    assert image_message(h)[2:] == (0, 1)


def test_adapter_never_initializes_lazy_spi_before_the_upstream_callback(real_ac073, monkeypatch):
    configure_versions(monkeypatch)
    h = real_ac073(lazy_spi=True)
    marker = object()

    def callback():
        assert h.driver._spi_bus is None and h.driver._gpio_setup is False
        assert not h.trace and not h.lazy_creations
        return marker

    assert run_bulk(h, callback=callback) is marker
    assert h.driver._spi_bus is None and not h.trace and not h.lazy_creations
    assert "_spi_write" not in vars(h.driver)


@pytest.mark.filterwarnings("ignore:Busy Wait")
@pytest.mark.parametrize("incompatible", [
    "inky_version", "spidev_version", "module", "source_hash", "class_method",
    "subclass", "instance_method", "writebytes2", "no_cs_false", "no_cs_missing", "no_cs_error",
    "mode", "mode_type", "bits_per_word", "cshigh", "lsbfirst", "threewire", "loop",
])
def test_any_unqualified_driver_or_spi_path_uses_unchanged_upstream_xfer(
    real_ac073, monkeypatch, tmp_path, incompatible,
):
    configure_versions(monkeypatch, inky="2.4.0" if incompatible == "inky_version" else "2.5.0",
                       spidev="3.7" if incompatible == "spidev_version" else "3.8")
    h = real_ac073(no_cs=incompatible.removeprefix("no_cs_") if incompatible.startswith("no_cs_") else "normal")
    driver_class = type(h.driver)
    original = h.driver._spi_write
    if incompatible == "module":
        monkeypatch.setattr(driver_class, "__module__", "unqualified.inky_ac073tc1a")
    elif incompatible == "source_hash":
        altered = tmp_path / "changed-upstream.py"
        altered.write_text(h.module.__loader__.get_source(h.module.__name__) + "\n# changed\n")
        monkeypatch.setattr(h.module, "__file__", str(altered))
    elif incompatible == "class_method":
        def changed(instance, dc, values):
            return original.__func__(instance, dc, values)
        monkeypatch.setattr(driver_class, "_spi_write", changed)
    elif incompatible == "subclass":
        h.driver.__class__ = type("DerivedInky", (driver_class,), {"__module__": driver_class.__module__})
    elif incompatible == "instance_method":
        h.driver._spi_write = MethodType(original.__func__, h.driver)
    elif incompatible == "writebytes2":
        h.spi.writebytes2 = None
    elif incompatible == "mode":
        h.spi.mode = 1
    elif incompatible == "mode_type":
        h.spi.mode = False
    elif incompatible == "bits_per_word":
        h.spi.bits_per_word = 16
    elif incompatible in {"cshigh", "lsbfirst", "threewire", "loop"}:
        setattr(h.spi, incompatible, True)
    before = vars(h.driver).get("_spi_write")
    run_bulk(h)
    assert image_message(h)[2:] == (PIXEL_BYTES, 0) and not h.spi.bulk_calls
    assert vars(h.driver).get("_spi_write") is before


@pytest.mark.filterwarnings("ignore:Busy Wait")
@pytest.mark.parametrize("kind", ["command", "boolean_dc", "tuple", "bytes", "short", "long", "boolean_element"])
def test_only_exact_full_data_list_can_use_bulk(real_ac073, monkeypatch, kind):
    configure_versions(monkeypatch)
    h = real_ac073()
    h.activate()
    h.driver.setup()
    dc, values = 1, [0x11] * PIXEL_BYTES
    if kind == "command":
        dc = 0
    elif kind == "boolean_dc":
        dc = True
    elif kind == "tuple":
        values = tuple(values)
    elif kind == "bytes":
        values = bytes(values)
    elif kind == "short":
        values = values[:4096]
    elif kind == "long":
        values.append(0x11)
    elif kind == "boolean_element":
        values[0] = True
    previous_bulk = len(h.spi.bulk_calls)
    previous_xfers = h.spi.xfer_calls
    marker = object()

    def callback():
        h.driver._spi_write(dc, values)
        return marker

    assert run_bulk(h, callback=callback) is marker
    assert len(h.spi.bulk_calls) == previous_bulk
    assert h.spi.xfer_calls - previous_xfers == len(values)
    assert h.spi.messages[-1][:2] == (int(bool(dc)), bytes(values))
    assert "_spi_write" not in vars(h.driver)


@pytest.mark.filterwarnings("ignore:Busy Wait")
def test_partial_bulk_exception_has_no_retry_or_later_power_commands_and_preserves_original_cs(
    real_ac073, monkeypatch,
):
    configure_versions(monkeypatch)
    baseline = real_ac073(fail_xfer_data=True)
    baseline.activate()
    with pytest.raises(OSError, match="partial xfer"):
        baseline.driver.show()
    h = real_ac073(fail_bulk=True)
    original_method = h.driver._spi_write
    with pytest.raises(OSError, match="partial bulk"):
        run_bulk(h)
    assert len(h.spi.bulk_calls) == 1
    assert h.gpio.cs == baseline.gpio.cs == 0
    assert bytes(h.spi.payload) == bytes(baseline.spi.payload) and len(h.spi.payload) == 4096
    commands = [message[1][0] for message in h.spi.messages if message[0] == 0]
    assert commands[-1] == 0x10 and all(command not in commands for command in (0x04, 0x12, 0x02))
    assert h.spi.current_xfers == 0 and h.spi.current_bulk == 1
    assert "_spi_write" not in vars(h.driver) and h.driver._spi_write == original_method


def controller(h, monkeypatch):
    h.activate()
    monkeypatch.setattr(importlib.import_module("inky.auto"), "auto", lambda **_: h.driver)
    monkeypatch.setenv("INKY_STUDIO_DISPLAY_PROFILE", AC073_TIMED_WAIT_PROFILE)
    monkeypatch.setattr("inky_web.inky.display.version", lambda name: "2.5.0" if name == "inky" else "3.8")
    display = DisplayController(mode="hardware")
    display.initialize()
    display.require_available()
    return display


@pytest.mark.filterwarnings("ignore:Busy Wait")
@pytest.mark.parametrize("failure", [None, "timeout", "partial_bulk"])
def test_real_controller_keeps_busy_verdict_and_durable_barrier_on_bulk_failures(
    real_ac073, monkeypatch, data_dir, tmp_path, failure,
):
    configure_versions(monkeypatch)
    h = real_ac073(held=failure != "timeout", timeout_phase="refresh" if failure == "timeout" else None,
                  fail_bulk=failure == "partial_bulk")
    display = controller(h, monkeypatch)
    source = tmp_path / "input.png"
    Image.new("RGB", (800, 480), "white").save(source)
    original_method = h.driver._spi_write
    if failure is None:
        display.display_image(source)
        assert display.status()["state"] == "ready"
        assert display.status()["confirmation"] == "timed_wait_unverified"
        assert [item["outcome"] for item in display.status()["observations"]] == ["held_high_unverified"] * 4
        assert ConfirmationBarrier(data_dir).load() is None
    else:
        with pytest.raises(DisplayUnavailableError) as caught:
            display.display_image(source)
        expected = "display_busy_timeout" if failure == "timeout" else "display_refresh_failed"
        assert caught.value.code == expected
        assert display.status()["state"] == "error" and display.status()["error"]["code"] == expected
        assert ConfirmationBarrier(data_dir).load() == "in_progress"
        counts = (h.spi.xfer_calls, len(h.spi.bulk_calls))
        with pytest.raises(DisplayUnavailableError):
            display.display_image(source)
        assert (h.spi.xfer_calls, len(h.spi.bulk_calls)) == counts
        if failure == "partial_bulk":
            assert [item["phase"] for item in display.status()["observations"]] == ["setup"]
            assert h.gpio.cs == 0
    assert len(h.spi.bulk_calls) == 1
    assert "_spi_write" not in vars(h.driver) and h.driver._spi_write == original_method
    assert "_busy_wait" not in vars(h.driver) and h.driver._gpio is h.gpio
