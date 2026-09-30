"""Display abstraction with auto-fallback to a mock when running off-Pi.

The real driver wraps the official Pimoroni inky library (`inky.auto`). When that
library or the SPI device is unavailable (e.g. when developing on macOS), we
transparently load a mock that exposes the same interface, so the rest of the
backend can be written without conditional imports.
"""
from __future__ import annotations

import logging
import platform
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageEnhance

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DisplaySpec:
    """Static description of a connected Inky display."""

    model: str
    width: int
    height: int
    colors: int


MOCK_SPEC = DisplaySpec(
    model="Mock Inky Impression 7.3\" (Spectra 6)",
    width=800,
    height=480,
    colors=6,
)

# Default when no per-call value is given (e.g. the welcome screen). 1.0 hands
# set_image() the panel's measured (most faithful) palette.
SATURATION = 1.0


class DisplayController:
    """Owns the active display driver (real or mock).

    The real Pimoroni driver is only imported lazily because it pulls in
    Linux-only deps (gpiod, spidev). On macOS we always run in mock mode.
    """

    def __init__(self) -> None:
        self._impl: Any | None = None
        self._is_mock: bool = True
        self._spec: DisplaySpec = MOCK_SPEC
        self._lock = threading.RLock()
        self._reservation: str | None = None

    @contextmanager
    def operation(self) -> Iterator[None]:
        """Serialize selection, hardware refresh, and its persisted result."""
        with self._lock:
            yield

    @property
    def reserved(self) -> bool:
        with self._lock:
            return self._reservation is not None

    def reserve(self, owner: str) -> None:
        with self._lock:
            if self._reservation not in (None, owner):
                raise RuntimeError("Écran occupé")
            self._reservation = owner

    def release(self, owner: str) -> None:
        with self._lock:
            if self._reservation == owner:
                self._reservation = None

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
                model=_detect_model_name(self._impl),
                width=self._impl.width,
                height=self._impl.height,
                colors=_detect_color_count(self._impl),
            )
            logger.info("Detected display: %s", self._spec)
        except Exception as exc:  # noqa: BLE001 — hardware errors vary
            logger.warning("Could not initialize real display (%s) — using mock", exc)
            self._impl = None
            self._is_mock = True
            self._spec = MOCK_SPEC

    def shutdown(self) -> None:
        with self.operation():
            self._impl = None

    @property
    def spec(self) -> DisplaySpec:
        return self._spec

    @property
    def is_mock(self) -> bool:
        return self._is_mock

    def info(self) -> dict[str, Any]:
        return {
            "model": self._spec.model,
            "width": self._spec.width,
            "height": self._spec.height,
            "colors": self._spec.colors,
            "is_mock": self._is_mock,
        }

    def display_image(self, path: Path, saturation: float | None = None) -> None:
        """Push the image at ``path`` to the e-ink display.

        ``saturation`` (0..2) drives two stages:
          * 0..1  → Pimoroni ``set_image(saturation=…)`` (1.0 = the panel's
            faithful measured palette);
          * 1..2  → set_image stays at 1.0 and we apply a source-image vibrance
            boost (PIL ``ImageEnhance.Color``) on top for extra punch. The panel
            gamut caps how vivid this can actually get.

        Otherwise the official library owns all colour science (single faithful
        quantisation to the auto-detected panel's exact palette).
        """
        with self.operation():
            self._display_image(path, saturation)

    def _display_image(self, path: Path, saturation: float | None) -> None:
        value = SATURATION if saturation is None else max(0.0, min(2.0, saturation))
        pimoroni_sat = min(value, 1.0)
        color_factor = max(1.0, value)  # 1.0 = no boost; up to 2.0 = strong boost
        if self._is_mock or self._impl is None:
            logger.info("[mock] Would display %s (sat=%s, boost=%s)", path, pimoroni_sat, color_factor)
            return

        with Image.open(path) as raw:
            img = raw.convert("RGB")
        if img.size != (self._spec.width, self._spec.height):
            img = img.resize((self._spec.width, self._spec.height))
        if color_factor > 1.0:
            img = ImageEnhance.Color(img).enhance(color_factor)

        try:
            self._impl.set_image(img, saturation=pimoroni_sat)
        except TypeError:
            # Older inky versions don't accept the saturation kwarg.
            self._impl.set_image(img)

        self._impl.show()
        logger.info("Displayed %s (sat=%s, boost=%s)", path, pimoroni_sat, color_factor)


def _detect_model_name(impl: Any) -> str:
    name = getattr(impl, "name", None)
    if name:
        return name
    cls = type(impl).__name__
    module = type(impl).__module__.lower()
    if "ac073tc1a" in module:
        return 'Inky Impression 7.3" (7-color)'
    if "e673" in module:
        return 'Inky Impression 7.3" (Spectra 6)'
    if "el133uf1" in module:
        return 'Inky Impression 13.3" (Spectra 6)'
    if "uc8159" in module:
        if (impl.width, impl.height) == (600, 448):
            return 'Inky Impression 5.7" (7-color)'
        if (impl.width, impl.height) == (640, 400):
            return 'Inky Impression 4" (7-color)'
    return f"Inky Impression ({cls})"


def _detect_color_count(impl: Any) -> int:
    # Newer inky lib drops ``colour_count`` — fall back to module sniffing.
    explicit = getattr(impl, "colour_count", None)
    if isinstance(explicit, int) and explicit > 0:
        return explicit
    module = type(impl).__module__.lower()
    if "e673" in module or "el133uf1" in module:
        return 6  # Spectra 6
    if "ac073tc1a" in module or "uc8159" in module:
        return 7  # Classic 7-color Inky Impression
    return 7
