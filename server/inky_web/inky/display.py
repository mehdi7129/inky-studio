"""Display abstraction with auto-fallback to a mock when running off-Pi.

The real driver wraps the official Pimoroni inky library (`inky.auto`). When that
library or the SPI device is unavailable (e.g. when developing on macOS), we
transparently load a mock that exposes the same interface, so the rest of the
backend can be written without conditional imports.
"""
from __future__ import annotations

import logging
import platform
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DisplaySpec:
    """Static description of a connected Inky display."""

    model: str
    width: int
    height: int
    colors: int


MOCK_SPEC = DisplaySpec(
    model="Mock Inky Impression 7.3\"",
    width=800,
    height=480,
    colors=7,
)


class DisplayController:
    """Owns the active display driver (real or mock).

    The real Pimoroni driver is only imported lazily because it pulls in
    Linux-only deps (gpiod, spidev). On macOS we always run in mock mode.
    """

    def __init__(self) -> None:
        self._impl: Any | None = None
        self._is_mock: bool = True
        self._spec: DisplaySpec = MOCK_SPEC
        self._color_mode: str = "pimoroni"

    def initialize(self) -> None:
        if platform.system() != "Linux":
            logger.info("Non-Linux platform detected — running with mock display")
            self._is_mock = True
            self._spec = MOCK_SPEC
            return

        try:
            from inky.auto import auto  # type: ignore
        except ImportError:
            logger.warning("Pimoroni inky library not installed — using mock display")
            return

        try:
            self._impl = auto(ask_user=False, verbose=False)
            self._is_mock = False
            self._spec = DisplaySpec(
                model=getattr(self._impl, "name", "Inky Impression"),
                width=self._impl.width,
                height=self._impl.height,
                colors=getattr(self._impl, "colour_count", 7),
            )
            logger.info("Detected display: %s", self._spec)
        except Exception as exc:  # noqa: BLE001 — hardware errors vary
            logger.warning("Could not initialize real display (%s) — using mock", exc)
            self._impl = None
            self._is_mock = True
            self._spec = MOCK_SPEC

    def shutdown(self) -> None:
        self._impl = None

    def info(self) -> dict[str, Any]:
        return {
            "model": self._spec.model,
            "width": self._spec.width,
            "height": self._spec.height,
            "colors": self._spec.colors,
            "color_mode": self._color_mode,
            "is_mock": self._is_mock,
        }
