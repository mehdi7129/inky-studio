"""Narrow, temporary bulk DATA transport for the exact AC073 inky 2.5.0.

The caller owns and serializes the complete show, including while spidev 3.8
releases the GIL. Packing, commands, GPIO acquisition and BUSY remain upstream.
An unknown source, method or SPI configuration always uses the original writer.
"""
from __future__ import annotations

import hashlib
import sys
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path
from types import CodeType, FunctionType, ModuleType
from typing import Any, TypeVar

_MODULE = "inky.inky_ac073tc1a"
_SOURCE_SHA256 = "07ef76f3854d279e19cc082b5bc96b8bc20b6aed967747357e5dff4cb9c65324"
_FRAME_BYTES = 800 * 480 // 2
_MISSING = object()
_DEFAULTS = {
    "__init__": (None, "multi", 8, 22, 27, 17, False, False, None, None, None),
    "_palette_blend": ("uint8",),
    "setup": None,
    "_busy_wait": (40.0,),
    "_update": None,
    "set_pixel": None,
    "show": (True,),
    "set_border": None,
    "set_image": (0.5,),
    "_spi_write": None,
    "_send_command": (None,),
    "_send_data": None,
}
_Result = TypeVar("_Result")


def _pinned_driver(impl: Any) -> bool:
    """Check the file and live methods without importing hardware or running it."""
    try:
        cls = type(impl)
        module = sys.modules.get(_MODULE)
        if (cls.__module__ != _MODULE or not isinstance(module, ModuleType)
                or vars(module).get("Inky") is not cls or cls.__bases__ != (object,)
                or version("inky") != "2.5.0"
                or type(impl.width) is not int or type(impl.height) is not int
                or (impl.width, impl.height) != (800, 480)):
            return False
        filename = module.__file__
        if type(filename) is not str:
            return False
        try:
            source = Path(filename).read_bytes()
        except OSError:
            # zipimport exposes the same pinned source inside the wheel rather
            # than as an ordinary filesystem path. It still needs the exact SHA.
            source = module.__loader__.get_data(filename)
        if hashlib.sha256(source).hexdigest() != _SOURCE_SHA256:
            return False
        # Compilation inspects immutable code objects only; no source import,
        # GPIO setup or driver code is executed by qualification.
        compiled = compile(source, filename, "exec", dont_inherit=True)
        class_code = next(value for value in compiled.co_consts
                          if type(value) is CodeType and value.co_name == "Inky")
        methods = {value.co_name: value for value in class_code.co_consts if type(value) is CodeType}
        if methods.keys() != _DEFAULTS.keys():
            return False
        for name, code in methods.items():
            method = vars(cls).get(name)
            if (name in vars(impl) or type(method) is not FunctionType
                    or method.__globals__ is not vars(module) or method.__code__ != code
                    or method.__defaults__ != _DEFAULTS[name] or method.__kwdefaults__ is not None
                    or method.__closure__ is not None):
                return False
        return True
    except Exception:
        return False


def _bulk_bus(impl: Any):
    """Observe lazy setup's completed configuration; never change SPI settings."""
    try:
        bus = impl._spi_bus
        if (impl._gpio_setup is not True or bus is None or version("spidev") != "3.8"
                or bus.no_cs is not True
                or type(bus.mode) is not int or bus.mode != 0
                or type(bus.bits_per_word) is not int or bus.bits_per_word != 8
                or type(bus.max_speed_hz) is not int or bus.max_speed_hz != 5000000
                or any(getattr(bus, flag) is not False for flag in ("cshigh", "lsbfirst", "threewire", "loop"))):
            return None
        bulk = bus.writebytes2
        return bulk if callable(bulk) else None
    except Exception:
        return None


class AC073BulkSPI:
    """Temporarily replace one instance writer around the serialized show."""

    def __init__(self, impl: Any) -> None:
        self._impl = impl

    def run_show(self, callback: Callable[[], _Result]) -> _Result:
        impl = self._impl
        if not _pinned_driver(impl):
            return callback()
        original = impl._spi_write
        previous = vars(impl).get("_spi_write", _MISSING)
        value_enum = original.__func__.__globals__["Value"]

        def write(dc, values):
            if type(dc) is not int or dc != 1 or type(values) is not list or len(values) != _FRAME_BYTES:
                return original(dc, values)
            bulk = _bulk_bus(impl)
            if bulk is None:
                return original(dc, values)
            snapshot = tuple(values)
            if (len(snapshot) != _FRAME_BYTES
                    or any(type(value) is not int or not 0 <= value <= 255 for value in snapshot)):
                return original(dc, values)
            payload = bytes(snapshot)
            gpio, cs_pin, dc_pin = impl._gpio, impl.cs_pin, impl.dc_pin
            # All conversion/qualification precedes the first GPIO effect.
            # Preserve upstream's error behavior: a failed write leaves CS low.
            gpio.set_value(cs_pin, value_enum.INACTIVE)
            gpio.set_value(dc_pin, value_enum.ACTIVE)
            bulk(payload)
            gpio.set_value(cs_pin, value_enum.ACTIVE)

        try:
            impl._spi_write = write
            return callback()
        finally:
            if previous is _MISSING:
                delattr(impl, "_spi_write")
            else:
                impl._spi_write = previous
