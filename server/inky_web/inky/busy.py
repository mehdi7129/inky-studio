"""Observe the distinct BUSY contracts in the pinned Pimoroni inky 2.5.0.

The caller qualifies module/version/dimensions and serializes each instance.
GPIO reads, waits, clocks and sleeps remain upstream's. A returned matching
edge is not proof of its freshness or of the physical image. EL133UF1 alone
refuses to send POF after an unproved, fully drained refresh wait.
"""
from __future__ import annotations

from types import FunctionType, MethodType
from typing import Any

from .errors import DisplayUnavailableError

_MISSING = object()
CONTRACTS = {
    "ac073": (("_busy_wait", "setup", 1.0), ("_busy_wait", "power_on", 0.4),
              ("_busy_wait", "refresh", 45.0), ("_busy_wait", "power_off", 0.4)),
    "uc8159": (("_busy_wait", "setup", 1.0), ("_busy_wait", "power_on", 0.2),
               ("_busy_wait", "refresh", 32.0), ("_busy_wait", "power_off", 0.2)),
    "e640": (("_busy_wait", "setup", 0.3), ("_busy_wait", "power_on", 0.3),
             ("_busy_wait", "refresh", 40.0), ("_busy_wait", "power_off", 0.3)),
    "e673": (("_busy_wait", "setup", 0.3), ("_busy_wait", "power_on", 0.3),
             ("_busy_wait", "refresh", 32.0), ("_busy_wait", "power_off", 0.3),
             ("_busy_wait", "standby", 0.3)),
    "el133uf1": (("_busy_wait", "setup", 0.3), ("_busy_wait", "power_on", 0.2),
                 ("_refresh_wait", "refresh", 65.0), ("_busy_wait", "power_off", 0.2)),
}
_TIMEOUTS = {"edge_timeout", "level_timeout", "refresh_assert_timeout", "refresh_timeout"}


def _restore_attribute(instance: Any, name: str, previous: Any) -> None:
    if previous is _MISSING:
        delattr(instance, name)
    else:
        setattr(instance, name, previous)


def _raise_busy_failure(timeout: bool) -> None:
    if timeout:
        raise DisplayUnavailableError(
            "Le cadre n’a pas répondu à temps. La photo est conservée. Vérifie le matériel, puis redémarre le service.",
            "display_busy_timeout",
        )
    raise DisplayUnavailableError(
        "La fin de l’affichage n’a pas pu être confirmée. La photo est conservée. Vérifie le cadre, puis redémarre le service.",
        "display_busy_unverified",
    )


def validate_observations(observations: list[dict[str, Any]], family: str) -> None:
    """A return from show() alone never proves these Impression refreshes."""
    if any(item.get("outcome") in _TIMEOUTS for item in observations):
        _raise_busy_failure(True)
    expected = CONTRACTS[family]
    if ([(item.get("phase"), item.get("timeout")) for item in observations]
            != [(phase, timeout) for _, phase, timeout in expected]):
        _raise_busy_failure(False)
    refresh = next(item for item in observations if item["phase"] == "refresh")
    required = ("edge_received" if family in {"ac073", "uc8159"}
                else "refresh_completed" if family == "el133uf1" else "level_released")
    if refresh["outcome"] != required:
        _raise_busy_failure(False)


class _GPIOObservation:
    """Retain existing reads only, in bounded state; never probe GPIO again."""

    def __init__(self, gpio: Any, value_enum: Any) -> None:
        self.original = gpio
        self.active = value_enum.ACTIVE
        self.inactive = value_enum.INACTIVE
        self.first: Any = _MISSING
        self.last: Any = _MISSING
        self.seen_inactive = False
        self.active_after_inactive = False
        self.invalid = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self.original, name)

    def get_value(self, *args: Any, **kwargs: Any) -> Any:
        value = self.original.get_value(*args, **kwargs)
        if self.first is _MISSING:
            self.first = value
        self.last = value
        if value == self.inactive:
            self.seen_inactive = True
        elif value == self.active:
            self.active_after_inactive |= self.seen_inactive
        else:
            self.invalid = True
        return value

    def polling_outcome(self, family: str, method: str) -> str:
        if self.invalid or self.first is _MISSING:
            return "unrecognized"
        if method == "_refresh_wait":
            if not self.seen_inactive:
                return "refresh_assert_timeout"
            if self.active_after_inactive and self.last == self.active:
                return "refresh_completed"
            return "refresh_timeout"
        if self.first == self.active:
            return "held_high_unverified"
        if family == "el133uf1":
            # LOW first, LOW next returns without establishing a transition.
            return "idle_low_unverified" if self.last == self.inactive else "level_timeout"
        return "level_released" if self.last == self.active else "level_timeout"


class _EdgeObservation:
    """Forward wait_for_edge exactly once, using the actual LineRequest."""

    def __init__(self, module: Any, gpio: _GPIOObservation, pin: int, edge_type: Any) -> None:
        self._module = module
        self._gpio = gpio
        self._pin = pin
        self._edge_type = edge_type
        self.result: Any = _MISSING

    def __getattr__(self, name: str) -> Any:
        return getattr(self._module, name)

    def wait_for_edge(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        actual = self._gpio.original if request is self._gpio else request
        result = self._module.wait_for_edge(actual, *args, **kwargs)
        self.result = result
        return result

    def outcome(self) -> str:
        if self.result is _MISSING:
            return "held_high_unverified" if self._gpio.first == self._gpio.active else "unrecognized"
        if self.result is None:
            return "edge_timeout"
        if (not self._gpio.invalid and self._gpio.first == self._gpio.inactive
                and type(self.result) is self._edge_type and self.result.line_offset == self._pin
                and self.result.event_type == self._edge_type.Type.RISING_EDGE):
            return "edge_received"
        return "edge_unverified"


class BusyObserver:
    """Temporary, per-instance observation of one complete pinned show().

    No upstream class/module global is patched. AC073/UC8159/E640/E673 verdicts
    are deferred until show() returns, including POF and E673 standby. EL133UF1
    waits fully, then blocks POF if LOW→HIGH refresh completion is unproved.
    """

    def __init__(self, impl: Any, family: str = "ac073") -> None:
        if family not in CONTRACTS:
            raise ValueError("Unknown qualified BUSY contract")
        self._impl = impl
        self.family = family
        self.observations: list[dict[str, Any]] = []

    def run_show(self) -> list[dict[str, Any]]:
        self.observations = []
        impl = self._impl
        originals = {name: getattr(impl, name) for name, _, _ in CONTRACTS[self.family]}
        previous = {name: vars(impl).get(name, _MISSING) for name in originals}
        applied = []

        def wrap(name: str, original: Any) -> Any:
            function = original.__func__
            value_enum = function.__globals__["Value"]

            def observed(*args: Any, **kwargs: Any) -> Any:
                default = 65.0 if name == "_refresh_wait" else 40.0
                timeout = args[0] if args else kwargs.get("timeout", default)
                index = len(self.observations)
                phase = "unrecognized"
                contract = CONTRACTS[self.family]
                if index < len(contract) and (name, timeout) == (contract[index][0], contract[index][2]):
                    phase = contract[index][1]
                observation = {"phase": phase, "sequence": index + 1, "timeout": timeout, "outcome": "unrecognized"}
                self.observations.append(observation)
                previous_gpio = vars(impl).get("_gpio", _MISSING)
                proxy = _GPIOObservation(impl._gpio, value_enum)
                impl._gpio = proxy
                edge = None
                call = original
                try:
                    if self.family in {"ac073", "uc8159"}:
                        globals_copy = dict(function.__globals__)
                        edge = _EdgeObservation(globals_copy["gpiodevice"], proxy, impl.busy_pin,
                                                globals_copy["gpiod"].EdgeEvent)
                        globals_copy["gpiodevice"] = edge
                        clone = FunctionType(function.__code__, globals_copy, function.__name__,
                                             function.__defaults__, function.__closure__)
                        clone.__kwdefaults__ = function.__kwdefaults__
                        call = MethodType(clone, impl)
                    result = call(*args, **kwargs)
                except BaseException as exc:
                    observation["outcome"] = "error"
                    observation["error_type"] = type(exc).__name__
                    raise
                else:
                    observation["outcome"] = edge.outcome() if edge else proxy.polling_outcome(self.family, name)
                finally:
                    _restore_attribute(impl, "_gpio", previous_gpio)
                if name == "_refresh_wait" and (phase != "refresh" or observation["outcome"] != "refresh_completed"):
                    _raise_busy_failure(observation["outcome"] in _TIMEOUTS)
                return result

            return observed

        try:
            for name, original in originals.items():
                setattr(impl, name, wrap(name, original))
                applied.append(name)
            impl.show()
        finally:
            for name in reversed(applied):
                _restore_attribute(impl, name, previous[name])
        return self.observations
