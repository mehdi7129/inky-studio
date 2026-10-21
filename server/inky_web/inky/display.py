"""Single hardware owner; hardware failures never become simulated displays."""
from __future__ import annotations

import logging
import os
import platform
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from PIL import Image, ImageEnhance

from inky_web.db import data_dir
from inky_web.inky.confirmation import ConfirmationBarrier
from inky_web.inky.errors import DisplayConfirmationPending, DisplayUnavailableError

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

# This opt-in accepts only the known driver's full timed fallback, without
# claiming that a BUSY edge or the physical image has been confirmed.
AC073_TIMED_WAIT_PROFILE = "ac073-800x480-timed-wait"
_AC073_PROFILES = {"ac073-800x480", AC073_TIMED_WAIT_PROFILE}


class DisplayController:
    """Owns the active display driver (real or mock).

    The real Pimoroni driver is only imported lazily because it pulls in
    Linux-only deps (gpiod, spidev). Auto mode simulates only off Linux.
    """

    def __init__(self, mode: str | None = None) -> None:
        requested = mode if mode is not None else os.environ.get("INKY_STUDIO_DISPLAY_MODE", "auto")
        if requested not in {"auto", "hardware", "mock"}:
            raise ValueError("INKY_STUDIO_DISPLAY_MODE must be auto, hardware or mock")
        self._mode = ("hardware" if platform.system() == "Linux" else "mock") if requested == "auto" else requested
        self._profile = os.environ.get("INKY_STUDIO_DISPLAY_PROFILE", "")
        if self._profile not in {"", *_AC073_PROFILES}:
            raise ValueError("Unknown INKY_STUDIO_DISPLAY_PROFILE")
        if self._profile and self._mode != "hardware":
            raise ValueError("A display hardware profile requires hardware mode")
        self._impl: Any | None = None
        self._is_mock = self._mode == "mock"
        self._spec: DisplaySpec | None = MOCK_SPEC if self._is_mock else None
        self._error: DisplayUnavailableError | None = None
        self._pending_confirmation: DisplayConfirmationPending | None = None
        self._confirmation = "not_observed"
        self._confirmation_barrier: ConfirmationBarrier | None = None
        self._initialized = False
        self._refreshing = False
        self._busy_observer: Any | None = None
        self._driver_info: dict[str, Any] = {}
        self._observations: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        self._closing = threading.Event()
        self._operation_local = threading.local()
        self._reservation: str | None = None

    @contextmanager
    def operation(self) -> Iterator[None]:
        """Serialize selection, hardware refresh, and its persisted result."""
        with self._lock:
            depth = getattr(self._operation_local, "depth", 0)
            if depth == 0 and self._closing.is_set():
                raise DisplayUnavailableError("Le service d’affichage est en cours d’arrêt.", "display_stopping")
            self._operation_local.depth = depth + 1
            try:
                yield
            finally:
                self._operation_local.depth = depth

    def begin_shutdown(self) -> None:
        """Close admission immediately, without waiting for the active SPI owner."""
        self._closing.set()

    @property
    def closing(self) -> bool:
        return self._closing.is_set()

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
        with self.operation():
            if self._initialized:
                return
            self._initialized = True
            if self._is_mock:
                logger.info("Display simulation selected; no hardware access")
                return
            try:
                from inky.auto import auto  # type: ignore

                self._impl = auto(ask_user=False, verbose=False)
                self._spec = DisplaySpec(
                    model=_detect_model_name(self._impl),
                    width=self._impl.width,
                    height=self._impl.height,
                    colors=_detect_color_count(self._impl),
                )
                self._configure_hardware()
                logger.info("Detected display: %s", self._spec)
            except DisplayUnavailableError as exc:
                self._error = exc
            except (Exception, SystemExit):
                # gpiodevice can use SystemExit for unavailable pins. Keep the
                # diagnostic API alive, but do not invent a working display.
                logger.exception("Hardware display initialization failed")
                self._error = DisplayUnavailableError(
                    "Écran indisponible. Vérifie le matériel et le pilote, puis redémarre le service."
                )

    def _configure_hardware(self) -> None:
        impl = self._impl
        module = type(impl).__module__
        eeprom = getattr(impl, "eeprom", None)
        variant = getattr(eeprom, "display_variant", None)
        color = getattr(eeprom, "color", None)
        self._driver_info = {
            "module": module,
            "display_variant": variant if type(variant) is int else None,
            "color_raw": color if type(color) is int else None,
            "color_interpretation": "unmapped" if color == 4 else "not_interpreted",
        }
        families = {
            "inky.inky_ac073tc1a": ("ac073", {(800, 480)}),
            "inky.inky_uc8159": ("uc8159", {(600, 448), (640, 400)}),
            "inky.inky_e640": ("e640", {(600, 400)}),
            "inky.inky_e673": ("e673", {(800, 480)}),
            "inky.inky_el133uf1": ("el133uf1", {(1600, 1200)}),
        }
        selected = families.get(module)
        is_ac073 = module == "inky.inky_ac073tc1a" and (impl.width, impl.height) == (800, 480)
        eeprom_size = (getattr(eeprom, "width", None), getattr(eeprom, "height", None))
        if self._profile and not is_ac073:
            raise ValueError("Detected driver does not match the selected bench profile")
        if is_ac073:
            fields = (*eeprom_size, variant, color, impl.width, impl.height)
            if not all(type(value) is int for value in fields) or eeprom_size != (800, 480) or variant != 20 or color not in {4, 5}:
                raise ValueError("Unexpected raw EEPROM tuple for the AC073 observer")
            if color == 4 and self._profile not in _AC073_PROFILES:
                raise ValueError("Unmapped EEPROM color 4 requires the explicit bench profile")
        if selected is not None:
            family, dimensions = selected
            if type(impl.width) is not int or type(impl.height) is not int or (impl.width, impl.height) not in dimensions:
                raise ValueError("Detected dimensions do not match the qualified BUSY contract")
            installed = version("inky")
            self._driver_info["inky_version"] = installed
            if installed != "2.5.0":
                raise ValueError("Impression BUSY observer requires inky 2.5.0")
            from inky_web.inky.busy import BusyObserver
            self._busy_observer = BusyObserver(impl, family)
            if family == "ac073":
                self._confirmation_barrier = ConfirmationBarrier(data_dir())
                barrier = self._confirmation_barrier.load()
                if barrier == "pending":
                    self._pending_confirmation = DisplayConfirmationPending()
                elif barrier == "in_progress":
                    raise DisplayUnavailableError(
                        "Un affichage précédent a été interrompu ou n’a pas de résultat enregistré. Aucune reprise automatique n’a été lancée.",
                        "display_confirmation_interrupted",
                    )
            for dependency in ("gpiod", "gpiodevice", "spidev"):
                try:
                    self._driver_info[f"{dependency}_version"] = version(dependency)
                except PackageNotFoundError:
                    self._driver_info[f"{dependency}_version"] = None

    def require_available(self) -> None:
        if self._error is not None:
            raise self._error
        if self._spec is None or (not self._is_mock and self._impl is None):
            raise DisplayUnavailableError("Écran indisponible. Redémarre le service après vérification du matériel.")

    @property
    def pending_confirmation(self) -> DisplayConfirmationPending | None:
        """Capture before queuing a manual operation; only this result may be retried."""
        return self._pending_confirmation

    @property
    def automatic_rotation_paused(self) -> bool:
        return self._pending_confirmation is not None

    def status(self) -> dict[str, Any]:
        # Do not acquire the SPI lock: operator diagnostics must remain readable
        # while the owner is blocked inside a long hardware refresh.
        state = "stopping" if self.closing else "error" if self._error else "busy" if self._refreshing else "mock" if self._is_mock else "ready" if self._impl else "uninitialized"
        return {
            "mode": self._mode,
            "profile": self._profile or None,
            "state": state,
            "is_mock": self._is_mock,
            "error": self._error.payload() if self._error else None,
            # Availability is separate from observation of the last refresh.
            # Older clients understand ready/error=null and can retry manually.
            "confirmation": "pending" if self._pending_confirmation else "mock" if self._is_mock else self._confirmation,
            "warning": self._pending_confirmation.payload() if self._pending_confirmation else None,
            "automatic_rotation_paused": self.automatic_rotation_paused,
            "driver": dict(self._driver_info),
            "busy_monitor": f"{self._busy_observer.family}_2.5.0" if self._busy_observer is not None else "not_monitored",
            "observations": [dict(item) for item in self._observations],
        }

    def shutdown(self) -> None:
        self.begin_shutdown()
        # Bypass the admission gate; wait through selection, show and persistence.
        with self._lock:
            self._busy_observer = None
            self._impl = None
            self._pending_confirmation = None
            self._error = DisplayUnavailableError("Le service d’affichage est arrêté.")

    @property
    def spec(self) -> DisplaySpec:
        self.require_available()
        assert self._spec is not None
        return self._spec

    @property
    def is_mock(self) -> bool:
        return self._is_mock

    def info(self) -> dict[str, Any]:
        # Detected dimensions remain useful when a refresh fails. Reading them
        # does not assert that the driver is available; spec and display_image
        # keep the sticky hardware-error gate for operations that need it.
        spec = self._spec
        if spec is None:
            self.require_available()
            assert self._spec is not None
            spec = self._spec
        return {
            "model": spec.model,
            "width": spec.width,
            "height": spec.height,
            "colors": spec.colors,
            "is_mock": self._is_mock,
        }

    def display_image(
        self, path: Path, saturation: float | None = None,
        *, retry_confirmation: DisplayConfirmationPending | None = None,
    ) -> None:
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
            self.require_available()
            if self._pending_confirmation is not None and retry_confirmation is not self._pending_confirmation:
                # An automatic caller, or a request queued before this outcome,
                # must not turn a missing confirmation into a second refresh.
                raise self._pending_confirmation
            self._refreshing = True
            self._observations = []
            try:
                self._display_image(path, saturation)
            except DisplayConfirmationPending as exc:
                self._pending_confirmation = exc
                raise
            except DisplayUnavailableError as exc:
                self._pending_confirmation = None
                self._error = exc
                raise
            except (Exception, SystemExit) as exc:
                self._pending_confirmation = None
                logger.exception("Display operation failed; automatic retries disabled")
                self._error = DisplayUnavailableError(
                    "L’affichage a échoué. La photo est conservée. Vérifie le cadre, puis redémarre le service.",
                    "display_refresh_failed",
                )
                raise self._error from exc
            else:
                self._pending_confirmation = None
            finally:
                self._refreshing = False

    def _display_image(self, path: Path, saturation: float | None) -> None:
        value = SATURATION if saturation is None else max(0.0, min(2.0, saturation))
        pimoroni_sat = min(value, 1.0)
        color_factor = max(1.0, value)  # 1.0 = no boost; up to 2.0 = strong boost
        if self._is_mock:
            logger.info("[mock] Would display %s (sat=%s, boost=%s)", path, pimoroni_sat, color_factor)
            return

        with Image.open(path) as raw:
            img = raw.convert("RGB")
        spec = self.spec
        if img.size != (spec.width, spec.height):
            img = img.resize((spec.width, spec.height))
        if color_factor > 1.0:
            img = ImageEnhance.Color(img).enhance(color_factor)

        try:
            self._impl.set_image(img, saturation=pimoroni_sat)
        except TypeError:
            # Older inky versions don't accept the saturation kwarg.
            self._impl.set_image(img)

        if self._busy_observer is None:
            self._impl.show()
            self._confirmation = "driver_returned"
        else:
            family = self._busy_observer.family
            if family == "ac073":
                # Durable before the first upstream show command. An interruption
                # keeps in_progress and cannot silently resume on the next process.
                if self._confirmation_barrier is None:
                    self._confirmation_barrier = ConfirmationBarrier(data_dir())
                self._confirmation_barrier.write("in_progress")
            try:
                if family == "ac073":
                    from inky_web.inky.spi import AC073BulkSPI
                    observations = AC073BulkSPI(self._impl).run_show(self._busy_observer.run_show)
                else:
                    observations = self._busy_observer.run_show()
            finally:
                self._observations = [dict(item) for item in self._busy_observer.observations]
            # Each driver owns its clocks/waits. EL133 refuses an unproved
            # refresh before POF; all other verdicts follow the full show().
            from inky_web.inky.busy import completed_ac073_waits, validate_observations
            timed_wait = self._profile == AC073_TIMED_WAIT_PROFILE
            try:
                validate_observations(observations, family, allow_ac073_timed_wait=timed_wait)
            except DisplayUnavailableError as exc:
                recoverable = (
                    family == "ac073" and exc.code == "display_busy_unverified"
                    and completed_ac073_waits(observations)
                    and observations[2]["outcome"] == "held_high_unverified"
                )
                if not recoverable:
                    raise
                # AC073 completed its timed fallback and power-off normally.
                # Preserve uncertainty and require an explicit manual retry.
                assert self._confirmation_barrier is not None
                self._confirmation_barrier.write("pending")
                raise DisplayConfirmationPending() from exc
            if family == "ac073":
                assert self._confirmation_barrier is not None
                self._confirmation_barrier.clear()
            if timed_wait and any(item["outcome"] == "held_high_unverified" for item in observations):
                self._confirmation = "timed_wait_unverified"
            else:
                self._confirmation = next(item["outcome"] for item in observations
                                          if item["phase"] == "refresh")
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
    if "e640" in module:
        return 'Inky Impression 4" (Spectra 6)'
    if "el133uf1" in module:
        return 'Inky Impression 13.3" (Spectra 6)'
    if "uc8159" in module:
        if (impl.width, impl.height) == (600, 448):
            return 'Inky Impression 5.7" (7-color)'
        if (impl.width, impl.height) == (640, 400):
            return 'Inky Impression 4" (7-color)'
    if "jd79661" in module:
        return 'Inky pHAT 2.13" (4-color)'
    if "jd79668" in module:
        return 'Inky wHAT 4.2" (4-color)'
    if module == "inky.phat":
        return f'Inky pHAT 2.13" ({_detect_color_count(impl)}-color)'
    if module in {"inky.what", "inky.inky_ssd1683"}:
        return f'Inky wHAT 4.2" ({_detect_color_count(impl)}-color)'
    return f"Inky Impression ({cls})"


def _detect_color_count(impl: Any) -> int:
    # Newer inky lib drops ``colour_count`` — fall back to module sniffing.
    explicit = getattr(impl, "colour_count", None)
    if isinstance(explicit, int) and explicit > 0:
        return explicit
    module = type(impl).__module__.lower()
    if "e673" in module or "e640" in module or "el133uf1" in module:
        return 6  # Spectra 6
    if "ac073tc1a" in module or "uc8159" in module:
        return 7  # Classic 7-color Inky Impression
    if "jd79661" in module or "jd79668" in module:
        return 4  # Black, white, red and yellow
    if module in {"inky.phat", "inky.what", "inky.inky_ssd1683"}:
        # EEPROM colour is independent of the nominal display variant.
        colour = getattr(impl, "colour", None)
        if colour == "black":
            return 2
        if colour in {"red", "yellow"}:
            return 3
    return 7
