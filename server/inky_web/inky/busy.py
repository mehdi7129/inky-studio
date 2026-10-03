"""Observe the pinned AC073 busy waits without changing its refresh sequence.

The caller must qualify the driver as Pimoroni AC073 / inky 2.3.0 and serialize
access to the instance. This is not a deadline or a replacement driver: GPIO
calls, sleeps, warnings, power-off and exceptions remain those of upstream.
"""

from typing import Any

_MISSING = object()
_PHASES = (("setup", 1.0), ("power_on", 0.4), ("refresh", 45.0), ("power_off", 0.4))


def _restore_attribute(instance: Any, name: str, previous: Any) -> None:
    if previous is _MISSING:
        delattr(instance, name)
    else:
        setattr(instance, name, previous)


class _GPIOObservation:
    """Forward the original calls once, retaining only their existing results."""

    def __init__(self, gpio: Any, active_value: Any) -> None:
        self._gpio = gpio
        self._active_value = active_value
        self.initial_active: bool | None = None
        self.wait_result: Any = _MISSING
        self.read_events = False
        self.events_present = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._gpio, name)

    def get_value(self, *args: Any, **kwargs: Any) -> Any:
        value = self._gpio.get_value(*args, **kwargs)
        if self.initial_active is None:
            self.initial_active = value == self._active_value
        return value

    def wait_edge_events(self, *args: Any, **kwargs: Any) -> Any:
        result = self._gpio.wait_edge_events(*args, **kwargs)
        self.wait_result = result
        return result

    def read_edge_events(self, *args: Any, **kwargs: Any) -> Any:
        result = self._gpio.read_edge_events(*args, **kwargs)
        self.read_events = True
        # gpiod returns a list. Inspect only that concrete, already returned
        # container; never consume an iterator or call GPIO again to confirm it.
        # Presence does not establish event freshness or successful rendering.
        self.events_present = type(result) is list and len(result) > 0
        return result

    def outcome(self) -> str:
        if self.wait_result is not _MISSING:
            if not self.wait_result:
                return "edge_timeout"
            if self.read_events:
                return "edge_received" if self.events_present else "edge_unverified"
        elif self.initial_active is True:
            return "held_high_unverified"
        return "unrecognized"


class BusyObserver:
    """Per-instance, temporary observation of one complete AC073 ``show()``.

    ``observations`` remains readable if upstream raises. Timeouts themselves
    never raise here: the owner decides whether the completed call is a success
    only after the driver has also performed its power-off and final busy wait.
    """

    def __init__(self, impl: Any) -> None:
        self._impl = impl
        self.observations: list[dict[str, Any]] = []

    def run_show(self) -> list[dict[str, Any]]:
        self.observations = []
        impl = self._impl
        original_wait = impl._busy_wait
        # Use upstream's enum without importing gpiod or performing another read.
        active_value = original_wait.__func__.__globals__["Value"].ACTIVE
        previous_wait = vars(impl).get("_busy_wait", _MISSING)

        def observed_wait(*args: Any, **kwargs: Any) -> Any:
            timeout = args[0] if args else kwargs.get("timeout", 40.0)
            index = len(self.observations)
            phase = "unrecognized"
            if index < len(_PHASES) and timeout == _PHASES[index][1]:
                phase = _PHASES[index][0]
            observation = {
                "phase": phase,
                "sequence": index + 1,
                "timeout": timeout,
                "outcome": "unrecognized",
            }
            self.observations.append(observation)
            # setup() may have just created the LineRequest. Preserve that real
            # initialization; only the temporary proxy belongs to this observer.
            previous_gpio = vars(impl).get("_gpio", _MISSING)
            proxy = _GPIOObservation(impl._gpio, active_value)
            impl._gpio = proxy
            try:
                result = original_wait(*args, **kwargs)
            except BaseException as exc:
                observation["outcome"] = "error"
                observation["error_type"] = type(exc).__name__
                raise
            else:
                observation["outcome"] = proxy.outcome()
                return result
            finally:
                _restore_attribute(impl, "_gpio", previous_gpio)

        impl._busy_wait = observed_wait
        try:
            impl.show()
        finally:
            _restore_attribute(impl, "_busy_wait", previous_wait)
        return self.observations
