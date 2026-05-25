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
from pathlib import Path
from typing import Any

from PIL import Image

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


class DisplayController:
    """Owns the active display driver (real or mock).

    The real Pimoroni driver is only imported lazily because it pulls in
    Linux-only deps (gpiod, spidev). On macOS we always run in mock mode.
    """

    def __init__(self) -> None:
        self._impl: Any | None = None
        self._is_mock: bool = True
        self._spec: DisplaySpec = MOCK_SPEC
        self._color_mode: str = "spectra_palette"

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
        self._impl = None

    @property
    def color_mode(self) -> str:
        return self._color_mode

    def set_color_mode(self, mode: str) -> None:
        self._color_mode = mode

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
            "color_mode": self._color_mode,
            "is_mock": self._is_mock,
        }

    def display_image(self, path: Path, color_mode: str | None = None) -> None:
        """Push the image at ``path`` to the e-ink with server-side colour processing.

        ``color_mode`` overrides the controller's current setting for this call,
        which lets the scheduler pass the live settings value.
        """
        effective_mode = color_mode if color_mode is not None else self._color_mode
        if self._is_mock or self._impl is None:
            logger.info("[mock] Would display %s (mode=%s)", path, effective_mode)
            return

        from inky_web.inky.image_processor import process  # lazy import avoids Pillow at startup

        with Image.open(path) as raw:
            img = raw.convert("RGB")

        processed_img, saturation = process(img, effective_mode)

        try:
            self._impl.set_image(processed_img, saturation=saturation)
        except TypeError:
            # Older inky versions don't accept saturation kwarg
            self._impl.set_image(processed_img)

        self._impl.show()
        logger.info("Displayed %s (mode=%s)", path, effective_mode)


def _detect_model_name(impl: Any) -> str:
    name = getattr(impl, "name", None)
    if name:
        return name
    cls = type(impl).__name__
    module = type(impl).__module__.lower()
    if "ac073tc1a" in module:
        # Pimoroni's 6-color Spectra chip — used by both 7.3" 2025 and 13.3" 2025
        if impl.width == 1600:
            return 'Inky Impression 13.3" (Spectra 6)'
        return 'Inky Impression 7.3" (Spectra 6)'
    if "uc8159" in module:
        return 'Inky Impression 7.3" (7-color)'
    return f"Inky Impression ({cls})"


def _detect_color_count(impl: Any) -> int:
    # Newer inky lib drops ``colour_count`` — fall back to module sniffing.
    explicit = getattr(impl, "colour_count", None)
    if isinstance(explicit, int) and explicit > 0:
        return explicit
    module = type(impl).__module__.lower()
    if "ac073tc1a" in module:
        return 6  # Spectra 6
    if "uc8159" in module:
        return 7  # Classic 7-color Inky Impression
    return 7
