"""Exact pinned 2.5 BUSY/update methods, inert GPIO/SPI, actual Studio verdicts."""
from __future__ import annotations

import ast
import asyncio
import warnings
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from threading import Barrier, Event
from types import SimpleNamespace

import pytest
from PIL import Image

from inky_web.inky.busy import CONTRACTS, BusyObserver, validate_observations
from inky_web.inky.confirmation import NAME
from inky_web.inky.display import DisplayController, DisplaySpec
from inky_web.inky.errors import DisplayUnavailableError
from tests.fixtures.inky_busy_250 import BUSY_PINS, CONSTANTS, SOURCES


class Value(Enum):
    INACTIVE = 0
    ACTIVE = 1


class EdgeEvent:
    class Type(Enum):
        RISING_EDGE = 1
        FALLING_EDGE = 2

    def __init__(self, line=17, event_type=None):
        self.line_offset = line
        self.event_type = event_type or self.Type.RISING_EDGE


class Clock:
    def __init__(self, trace):
        self.now = 0.0
        self.trace = trace

    def time(self):
        return self.now

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.trace.append(("sleep", seconds))
        self.now += seconds


class FakeGPIO:
    def __init__(self, trace, family, scenarios, barrier, blocked):
        self.trace = trace
        self.family = family
        self.scenarios = scenarios
        self.barrier = barrier
        self.blocked = blocked
        self.phase = "setup"
        self.indices = {}

    def get_value(self, pin):
        index = self.indices.get(self.phase, 0)
        self.indices[self.phase] = index + 1
        self.trace.append(("get_value", pin))
        if self.phase == "refresh" and index == 0:
            if self.barrier:
                self.barrier.wait(timeout=3)
            if self.blocked:
                entered, release = self.blocked
                entered.set()
                assert release.wait(3)
        defaults = ([Value.INACTIVE] if self.family in {"ac073", "uc8159"}
                    else [Value.INACTIVE, Value.INACTIVE] if self.family == "el133uf1" and self.phase != "refresh"
                    else [Value.INACTIVE, Value.INACTIVE, Value.ACTIVE])
        values = self.scenarios.get(self.phase, {}).get("values", defaults)
        value = values[min(index, len(values) - 1)]
        if isinstance(value, BaseException):
            raise value
        return value


@pytest.fixture
def driver_factory():
    def make(family="ac073", scenarios=None, *, lazy_gpio=False, barrier=None, blocked=None):
        trace = []
        scenarios = scenarios or {}
        clock = Clock(trace)
        gpio = FakeGPIO(trace, family, scenarios, barrier, blocked)

        def wait_for_edge(request, line, timeout):
            # The helper receives the very same real request as the baseline;
            # the observation never passes its proxy into gpiodevice.
            assert type(request) is FakeGPIO
            request.trace.append(("wait_for_edge", line, timeout))
            result = request.scenarios.get(request.phase, {}).get("edge", EdgeEvent())
            if isinstance(result, BaseException):
                raise result
            return result

        helper = SimpleNamespace(wait_for_edge=wait_for_edge)
        namespace = {"Value": Value, "time": clock, "warnings": warnings,
                     "gpiod": SimpleNamespace(EdgeEvent=EdgeEvent), "gpiodevice": helper}
        namespace.update(CONSTANTS[family])
        parsed = ast.parse(SOURCES[family]).body[0]
        exec(compile(ast.Module(body=parsed.body, type_ignores=[]), f"inky-2.5.0-{family}", "exec"), namespace)
        upstream = type("PinnedWaitAndUpdate", (), {node.name: namespace[node.name] for node in parsed.body})
        dims = {"ac073": (800, 480), "uc8159": (600, 448), "e640": (600, 400),
                "e673": (800, 480), "el133uf1": (1600, 1200)}[family]

        class Driver(upstream):
            busy_pin = BUSY_PINS[family]
            width, height = dims

            def __init__(self):
                self._gpio = None if lazy_gpio else gpio
                self.show_calls = 0

            def setup(self):
                # GPIO acquisition/reset/init commands excluded from this
                # fixture; the setup wait and update/wait bodies are exact.
                if self._gpio is None:
                    self._gpio = gpio
                gpio.phase = "setup"
                gpio.indices = {}
                self._busy_wait(CONTRACTS[family][0][2])

            def show(self):
                self.show_calls += 1
                self._update([0x77], [0x77]) if family == "el133uf1" else self._update([0x77])
                trace.append(("show_returned",))

            def set_image(self, image, *, saturation):
                assert image.size == dims and image.mode == "RGB"
                trace.append(("set_image", image.size, image.mode, saturation))

            def _send_command(self, command, *data):
                trace.append(("command", command, *data))
                phase = {0x04: "power_on", 0x12: "refresh", 0x02: "power_off"}.get(command)
                if command == 0x00 and family == "e673":
                    phase = "standby"
                if phase:
                    gpio.phase = phase

        return Driver(), gpio, trace, namespace

    return make


@pytest.mark.parametrize("family", CONTRACTS)
def test_healthy_trace_identical_to_unobserved_upstream_and_globals_unchanged(driver_factory, family):
    baseline, _, baseline_trace, _ = driver_factory(family)
    baseline.show()
    driver, gpio, trace, namespace = driver_factory(family)
    before = dict(namespace)
    observer = BusyObserver(driver, family)
    observed = observer.run_show()
    validate_observations(observed, family)
    assert trace == baseline_trace and driver.show_calls == 1
    assert [item["phase"] for item in observed] == [phase for _, phase, _ in CONTRACTS[family]]
    assert [item["timeout"] for item in observed] == [timeout for _, _, timeout in CONTRACTS[family]]
    assert namespace == before and driver._gpio is gpio
    assert all(name not in vars(driver) for name in ("_busy_wait", "_refresh_wait"))


@pytest.mark.parametrize("family", ["ac073", "uc8159"])
@pytest.mark.parametrize("edge", [False, [], object(), EdgeEvent(18), EdgeEvent(17, EdgeEvent.Type.FALLING_EDGE)])
def test_edge_metadata_is_exact_and_unknown_results_never_grant_refresh(driver_factory, family, edge):
    driver, gpio, trace, _ = driver_factory(family, {"refresh": {"edge": edge}})
    observed = BusyObserver(driver, family).run_show()
    assert observed[2]["outcome"] == "edge_unverified"
    with pytest.raises(DisplayUnavailableError) as caught:
        validate_observations(observed, family)
    assert caught.value.code == "display_busy_unverified"
    assert trace[-1] == ("show_returned",) and driver._gpio is gpio
    assert len([item for item in trace if item[0] == "wait_for_edge"]) == 4


@pytest.mark.parametrize("family", ["ac073", "uc8159"])
def test_unknown_gpio_level_is_not_proved_by_matching_edge(driver_factory, family):
    driver, _, _, _ = driver_factory(family, {"refresh": {"values": [None]}})
    observed = BusyObserver(driver, family).run_show()
    assert observed[2]["outcome"] == "edge_unverified"
    with pytest.raises(DisplayUnavailableError) as caught:
        validate_observations(observed, family)
    assert caught.value.code == "display_busy_unverified"


@pytest.mark.parametrize(("family", "phase"), [(f, p) for f, contract in CONTRACTS.items() for _, p, _ in contract])
@pytest.mark.filterwarnings("ignore:.*Wait")
def test_every_timeout_refuses_success_and_only_el_refresh_blocks_pof(driver_factory, family, phase):
    fault = {"edge": None} if family in {"ac073", "uc8159"} else {"values": [Value.INACTIVE]}
    if family == "el133uf1" and phase != "refresh":
        # Its power waits only time out after initialLOW then HIGH held.
        fault = {"values": [Value.INACTIVE, Value.ACTIVE]}
    driver, gpio, trace, _ = driver_factory(family, {phase: fault})
    observer = BusyObserver(driver, family)
    with pytest.raises(DisplayUnavailableError) as caught:
        observations = observer.run_show()
        validate_observations(observations, family)
    assert caught.value.code == "display_busy_timeout"
    assert driver._gpio is gpio
    assert all(name not in vars(driver) for name in ("_busy_wait", "_refresh_wait"))
    if family == "el133uf1" and phase == "refresh":
        assert not any(item[0] == "command" and item[1] == 0x02 for item in trace)
        assert trace[-1][0] == "get_value"  # Final upstream check preceded its timeout return.
    else:
        assert trace[-1] == ("show_returned",)
        assert any(item[0] == "command" and item[1] == 0x02 for item in trace)


@pytest.mark.parametrize("family", ["ac073", "uc8159", "e640", "e673"])
@pytest.mark.filterwarnings("ignore:Busy Wait")
def test_held_high_blind_sleep_is_unverified(driver_factory, family):
    driver, _, trace, _ = driver_factory(family, {"refresh": {"values": [Value.ACTIVE]}})
    observed = BusyObserver(driver, family).run_show()
    assert observed[2]["outcome"] == "held_high_unverified"
    with pytest.raises(DisplayUnavailableError) as caught:
        validate_observations(observed, family)
    assert caught.value.code == "display_busy_unverified"
    assert ("sleep", CONTRACTS[family][2][2]) in trace
    assert trace[-1] == ("show_returned",)


@pytest.mark.parametrize("phase", [phase for _, phase, _ in CONTRACTS["ac073"]])
@pytest.mark.parametrize("outcome", ["edge_unverified", "unrecognized", "error"])
def test_explicit_ac073_timed_wait_requires_recognized_outcome_in_every_phase(driver_factory, phase, outcome):
    driver, _, _, _ = driver_factory("ac073")
    observed = BusyObserver(driver, "ac073").run_show()
    next(item for item in observed if item["phase"] == phase)["outcome"] = outcome
    with pytest.raises(DisplayUnavailableError) as caught:
        validate_observations(observed, "ac073", allow_ac073_timed_wait=True)
    assert caught.value.code == "display_busy_unverified"


@pytest.mark.parametrize("phase", [phase for _, phase, _ in CONTRACTS["ac073"]])
@pytest.mark.filterwarnings("ignore:Busy Wait")
def test_explicit_ac073_timed_wait_still_refuses_each_real_edge_timeout(driver_factory, phase):
    driver, _, trace, _ = driver_factory("ac073", {phase: {"edge": None}})
    observed = BusyObserver(driver, "ac073").run_show()
    with pytest.raises(DisplayUnavailableError) as caught:
        validate_observations(observed, "ac073", allow_ac073_timed_wait=True)
    assert caught.value.code == "display_busy_timeout" and trace[-1] == ("show_returned",)


@pytest.mark.parametrize("family", [family for family in CONTRACTS if family != "ac073"])
def test_ac073_timed_wait_opt_in_does_not_authorize_another_driver_family(driver_factory, family):
    driver, _, _, _ = driver_factory(family)
    observed = BusyObserver(driver, family).run_show()
    with pytest.raises(DisplayUnavailableError) as caught:
        validate_observations(observed, family, allow_ac073_timed_wait=True)
    assert caught.value.code == "display_busy_unverified"


@pytest.mark.parametrize("values", [[Value.ACTIVE, Value.ACTIVE, Value.INACTIVE, Value.INACTIVE, Value.ACTIVE],
                                    [Value.INACTIVE, Value.ACTIVE]])
def test_el_refresh_accepts_only_observed_low_then_high(driver_factory, values):
    driver, gpio, trace, _ = driver_factory("el133uf1", {"refresh": {"values": values}})
    observer = BusyObserver(driver, "el133uf1")
    observed = observer.run_show()
    validate_observations(observed, "el133uf1")
    assert observed[2]["outcome"] == "refresh_completed" and driver._gpio is gpio
    assert trace[-1] == ("show_returned",)


@pytest.mark.parametrize(("values", "outcome", "code"), [
    ([Value.ACTIVE], "refresh_assert_timeout", "display_busy_timeout"),
    ([Value.INACTIVE], "refresh_timeout", "display_busy_timeout"),
    ([object()], "unrecognized", "display_busy_unverified"),
])
@pytest.mark.filterwarnings("ignore:Refresh Wait")
def test_el_refusal_after_whole_wait_before_pof(driver_factory, values, outcome, code):
    baseline, _, baseline_trace, _ = driver_factory("el133uf1", {"refresh": {"values": values}})
    baseline.show()  # Upstream warning+return would proceed to POF.
    driver, gpio, trace, _ = driver_factory("el133uf1", {"refresh": {"values": values}})
    observer = BusyObserver(driver, "el133uf1")
    with pytest.raises(DisplayUnavailableError) as caught:
        observer.run_show()
    assert caught.value.code == code and observer.observations[2]["outcome"] == outcome
    pof = next(i for i, item in enumerate(baseline_trace) if item[:2] == ("command", 0x02))
    assert trace == baseline_trace[:pof]
    assert driver._gpio is gpio and "_busy_wait" not in vars(driver) and "_refresh_wait" not in vars(driver)


@pytest.mark.parametrize("family", CONTRACTS)
@pytest.mark.parametrize("fault", [OSError("inert GPIO fault"), SystemExit(3)])
def test_gpio_errors_restore_preexisting_instance_methods(driver_factory, family, fault):
    driver, gpio, _, _ = driver_factory(family, {"refresh": {"values": [fault]}})
    previous = {name: getattr(driver, name) for name, _, _ in CONTRACTS[family]}
    for name, method in previous.items():
        setattr(driver, name, method)
    observer = BusyObserver(driver, family)
    with pytest.raises(type(fault)) as caught:
        observer.run_show()
    assert caught.value is fault and observer.observations[-1]["outcome"] == "error"
    assert driver._gpio is gpio
    assert all(getattr(driver, name) is method for name, method in previous.items())


@pytest.mark.parametrize("family", ["ac073", "uc8159"])
def test_helper_wait_exception_restores_gpio_method_and_module_globals(driver_factory, family):
    fault = OSError("inert edge helper fault")
    driver, gpio, _, namespace = driver_factory(family, {"refresh": {"edge": fault}})
    before = dict(namespace)
    observer = BusyObserver(driver, family)
    with pytest.raises(OSError) as caught:
        observer.run_show()
    assert caught.value is fault and observer.observations[-1]["outcome"] == "error"
    assert namespace == before and driver._gpio is gpio and "_busy_wait" not in vars(driver)


@pytest.mark.parametrize("family", CONTRACTS)
def test_lazy_and_class_gpio_ownership_is_preserved(driver_factory, family):
    driver, gpio, _, _ = driver_factory(family, lazy_gpio=True)
    BusyObserver(driver, family).run_show()
    assert driver._gpio is gpio
    type(driver)._gpio = gpio
    del driver._gpio
    BusyObserver(driver, family).run_show()
    assert driver._gpio is gpio and "_gpio" not in vars(driver)


@pytest.mark.parametrize("family", CONTRACTS)
def test_overlapping_instances_have_no_global_hook_interference(driver_factory, family):
    barrier = Barrier(2)
    left, left_gpio, _, left_globals = driver_factory(family, barrier=barrier)
    right, right_gpio, _, right_globals = driver_factory(family, barrier=barrier)
    # Real driver instances share their module globals and gpiodevice helper.
    # Rebind the right fixture's exact methods to that same namespace as well.
    for name in ("_busy_wait", "_refresh_wait", "_update"):
        if hasattr(left, name):
            setattr(type(right), name, getattr(left, name).__func__)
    assert left._busy_wait.__func__.__globals__ is right._busy_wait.__func__.__globals__
    before = [dict(left_globals), dict(right_globals)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(BusyObserver(driver, family).run_show) for driver in (left, right)]
        for task in tasks:
            validate_observations(task.result(timeout=5), family)
    assert [left_globals, right_globals] == before
    assert left._gpio is left_gpio and right._gpio is right_gpio


@pytest.mark.parametrize("family", CONTRACTS)
def test_unrecognized_sequence_never_grants_completed_show(driver_factory, family):
    driver, gpio, _, _ = driver_factory(family)
    original = driver.show

    def extra_wait():
        original()
        driver._busy_wait(0.3)

    driver.show = extra_wait
    observations = BusyObserver(driver, family).run_show()
    with pytest.raises(DisplayUnavailableError) as caught:
        validate_observations(observations, family)
    assert caught.value.code == "display_busy_unverified" and observations[-1]["phase"] == "unrecognized"
    assert driver._gpio is gpio


@pytest.mark.parametrize(("family", "condition"),
                         [(family, condition) for family in CONTRACTS
                          for condition in ("healthy", "timeout", "unverified")]
                         + [(family, "held_high") for family in ("ac073", "uc8159", "e640", "e673")])
@pytest.mark.filterwarnings("ignore:.*Wait")
def test_controller_and_display_api_preserve_queue_until_driver_verdict(client, png_factory, driver_factory, data_dir, family, condition):
    scenarios = {}
    if condition == "timeout":
        scenarios["refresh"] = ({"edge": None} if family in {"ac073", "uc8159"} else {"values": [Value.INACTIVE]})
    elif condition == "held_high":
        scenarios["refresh"] = {"values": [Value.ACTIVE]}
    elif condition == "unverified":
        scenarios["refresh"] = ({"edge": False} if family in {"ac073", "uc8159"}
                                else {"values": [object()]} if family == "el133uf1" else {"values": [Value.ACTIVE]})
    driver, gpio, trace, _ = driver_factory(family, scenarios)
    display = client.app.state.display
    display._impl, display._is_mock = driver, False
    display._spec = DisplaySpec(family, driver.width, driver.height, 7 if family in {"ac073", "uc8159"} else 6)
    display._busy_observer = BusyObserver(driver, family)
    upload = client.post("/api/queue", files={"file": ("test.png", png_factory(driver.width, driver.height), "image/png")})
    assert upload.status_code == 201
    original_queue = client.get("/api/queue").json()
    response = client.post("/api/display/next")
    assert driver.show_calls == 1 and driver._gpio is gpio
    if family != "ac073":
        assert display._confirmation_barrier is None
        assert not (data_dir / NAME).exists()
    if condition == "healthy":
        assert response.status_code == 202 and client.get("/api/queue").json() == []
        assert len(client.get("/api/history").json()) == 1 and trace[-1] == ("show_returned",)
        status = client.get("/api/display/status").json()
        expected = ("edge_received" if family in {"ac073", "uc8159"}
                    else "refresh_completed" if family == "el133uf1" else "level_released")
        assert status["confirmation"] == expected and not status["automatic_rotation_paused"]
    elif family == "ac073" and condition == "held_high":
        assert response.status_code == 503 and response.json()["code"] == "display_confirmation_pending"
        assert client.get("/api/queue").json() == original_queue and client.get("/api/history").json() == []
        status = client.get("/api/display/status").json()
        assert status["state"] == "ready" and status["error"] is None
        assert status["confirmation"] == "pending" and status["automatic_rotation_paused"]
    else:
        code = "display_busy_timeout" if condition == "timeout" else "display_busy_unverified"
        assert response.status_code == 503 and response.json()["code"] == code
        assert client.get("/api/queue").json() == original_queue and client.get("/api/history").json() == []
        assert client.get("/api/display/status").json()["error"]["code"] == code
        completed = list(trace)
        assert client.post("/api/display/next").status_code == 503
        assert trace == completed and driver.show_calls == 1


@pytest.mark.parametrize("family", ["ac073", "e640", "el133uf1"])
def test_shutdown_waits_for_admitted_busy_owner_without_stopping_wait(tmp_path, driver_factory, family):
    entered, release = Event(), Event()
    driver, gpio, trace, _ = driver_factory(family, blocked=(entered, release))
    path = tmp_path / "photo.png"
    Image.new("RGB", (driver.width, driver.height)).save(path)
    display = DisplayController(mode="mock")
    display._impl, display._is_mock = driver, False
    display._spec = DisplaySpec(family, driver.width, driver.height, 6)
    display._busy_observer = BusyObserver(driver, family)
    with ThreadPoolExecutor(max_workers=2) as pool:
        show = pool.submit(display.display_image, path)
        try:
            assert entered.wait(2)
            display.begin_shutdown()
            stop = pool.submit(display.shutdown)
            assert display.closing and not show.done() and not stop.done()
            assert driver._gpio is not gpio  # Observer retained during blocked read.
        finally:
            release.set()
        show.result(timeout=3)
        stop.result(timeout=3)
    assert trace[-1] == ("show_returned",) and driver.show_calls == 1
    assert driver._gpio is gpio and display.status()["state"] == "stopping"


@pytest.mark.parametrize("family", ["ac073", "e640", "el133uf1"])
async def test_caller_cancellation_does_not_stop_busy_thread_and_shutdown_drains_it(tmp_path, driver_factory, family):
    entered, release, finished, stop_started = Event(), Event(), Event(), Event()
    driver, gpio, trace, _ = driver_factory(family, blocked=(entered, release))
    path = tmp_path / "photo.png"
    Image.new("RGB", (driver.width, driver.height)).save(path)
    display = DisplayController(mode="mock")
    display._impl, display._is_mock = driver, False
    display._spec = DisplaySpec(family, driver.width, driver.height, 6)
    display._busy_observer = BusyObserver(driver, family)

    def show():
        try:
            display.display_image(path)
        finally:
            finished.set()

    def shutdown():
        stop_started.set()
        display.shutdown()

    caller = asyncio.create_task(asyncio.to_thread(show))
    stop = None
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert not finished.is_set() and display.status()["state"] == "busy"
        assert driver._gpio is not gpio
        display.begin_shutdown()
        stop = asyncio.create_task(asyncio.to_thread(shutdown))
        assert await asyncio.to_thread(stop_started.wait, 2)
        assert not stop.done() and not finished.is_set()
    finally:
        release.set()
        if stop is not None:
            await stop
        if not caller.done():
            await caller
    assert finished.is_set() and trace[-1] == ("show_returned",)
    assert driver.show_calls == 1 and driver._gpio is gpio
