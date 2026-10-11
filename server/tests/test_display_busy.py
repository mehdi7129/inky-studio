"""Run the actual pinned busy wait/update against inert GPIO and SPI commands."""

import ast
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from enum import Enum
from threading import Barrier
from types import SimpleNamespace

import pytest

from inky_web.inky.busy import BusyObserver
from tests.fixtures.inky_ac073_busy_230 import SOURCE


class Value(Enum):
    INACTIVE = 0
    ACTIVE = 1


class FakeGPIO:
    def __init__(self, trace, phases=None, barrier=None):
        self.trace = trace
        self.phases = phases or [(Value.INACTIVE, True)] * 4
        self.index = -1
        self.barrier = barrier

    def get_value(self, pin):
        self.trace.append(("get_value", pin))
        self.index += 1
        value = self.phases[self.index][0]
        if isinstance(value, BaseException):
            raise value
        return value

    def wait_edge_events(self, timeout):
        self.trace.append(("wait_edge_events", timeout))
        if self.barrier:
            self.barrier.wait(timeout=3)
        result = self.phases[self.index][1]
        if isinstance(result, BaseException):
            raise result
        return result

    def read_edge_events(self):
        self.trace.append(("read_edge_events",))
        return ["rising-edge"]


@pytest.fixture
def driver_factory():
    def make(phases=None, *, lazy_gpio=False, barrier=None):
        trace = []
        namespace = {
            "Value": Value,
            "time": SimpleNamespace(sleep=lambda seconds: trace.append(("sleep", seconds))),
            "warnings": warnings,
            "timedelta": timedelta,
            "AC073TC1_DTM": 0x10,
            "AC073TC1_PON": 0x04,
            "AC073TC1_DRF": 0x12,
            "AC073TC1_POF": 0x02,
        }
        parsed_class = ast.parse(SOURCE).body[0]
        # Compile the upstream method AST, without its imports or GPIO setup.
        exec(compile(ast.Module(body=parsed_class.body, type_ignores=[]), "pimoroni-2.3.0-busy", "exec"), namespace)
        upstream = type("PinnedWaitAndUpdate", (), {
            "_busy_wait": namespace["_busy_wait"],
            "_update": namespace["_update"],
        })
        gpio = FakeGPIO(trace, phases, barrier)

        class Driver(upstream):
            busy_pin = 17

            def __init__(self):
                self._gpio = None if lazy_gpio else gpio
                self.show_calls = 0

            def setup(self):
                # Only GPIO acquisition is simulated. The wait and complete
                # PON/DRF/POF ordering are executed from the upstream source.
                if self._gpio is None:
                    self._gpio = gpio
                self._busy_wait(1.0)

            def show(self):
                self.show_calls += 1
                self._update([0x77])
                trace.append(("show_returned",))

            def _send_command(self, command, data=None):
                trace.append(("command", command, data))

        return Driver(), gpio, trace

    return make


def test_healthy_trace_is_identical_to_unobserved_upstream(driver_factory):
    baseline, _, baseline_trace = driver_factory()
    baseline.show()
    driver, gpio, trace = driver_factory()
    observer = BusyObserver(driver)

    assert observer.run_show() == [
        {"phase": phase, "sequence": index, "timeout": timeout, "outcome": "edge_received"}
        for index, (phase, timeout) in enumerate([
            ("setup", 1.0), ("power_on", 0.4), ("refresh", 45.0), ("power_off", 0.4),
        ], start=1)
    ]
    assert driver.show_calls == 1
    assert trace == baseline_trace
    assert driver._gpio is gpio
    assert "_busy_wait" not in vars(driver)


def test_ready_wait_followed_by_empty_events_is_unverified(driver_factory):
    baseline, baseline_gpio, baseline_trace = driver_factory()
    driver, gpio, trace = driver_factory()

    def empty_read(target_trace):
        def read():
            target_trace.append(("read_edge_events",))
            return []
        return read

    baseline_gpio.read_edge_events = empty_read(baseline_trace)
    gpio.read_edge_events = empty_read(trace)
    baseline.show()

    observations = BusyObserver(driver).run_show()

    assert [item["outcome"] for item in observations] == ["edge_unverified"] * 4
    assert trace == baseline_trace
    assert trace.count(("read_edge_events",)) == 4
    assert ("command", 0x02, [0x00]) in trace
    assert trace[-1] == ("show_returned",)
    assert driver._gpio is gpio


def test_non_list_events_are_not_consumed_to_verify_presence(driver_factory):
    driver, gpio, _ = driver_factory()
    results = []

    class Events:
        def __init__(self):
            self.iterations = 0

        def __iter__(self):
            self.iterations += 1
            assert self.iterations == 1
            yield "one-edge"

        def __len__(self):
            raise AssertionError("Observer must not probe an arbitrary iterable")

    def read():
        result = Events()
        results.append(result)
        return result

    gpio.read_edge_events = read

    observations = BusyObserver(driver).run_show()

    assert [item["outcome"] for item in observations] == ["edge_unverified"] * 4
    assert len(results) == 4
    assert all(result.iterations == 1 for result in results)
    assert driver._gpio is gpio


@pytest.mark.parametrize("failed_phase", range(4))
@pytest.mark.filterwarnings("ignore:Busy Wait")
def test_false_edge_wait_is_recorded_without_skipping_power_off(driver_factory, failed_phase):
    phases = [(Value.INACTIVE, True)] * 4
    phases[failed_phase] = (Value.INACTIVE, False)
    baseline, _, baseline_trace = driver_factory(phases)
    baseline.show()
    driver, gpio, trace = driver_factory(phases)
    observations = BusyObserver(driver).run_show()

    assert [item["outcome"] for item in observations] == [
        "edge_timeout" if index == failed_phase else "edge_received" for index in range(4)
    ]
    assert trace == baseline_trace
    assert ("command", 0x02, [0x00]) in trace
    assert trace[-1] == ("show_returned",)
    assert observations[-1]["phase"] == "power_off"
    assert driver.show_calls == 1
    assert driver._gpio is gpio


@pytest.mark.filterwarnings("ignore:Busy Wait")
def test_held_high_is_unverified_even_with_warnings_disabled(driver_factory):
    phases = [(Value.ACTIVE, None)] * 4
    baseline, _, baseline_trace = driver_factory(phases)
    baseline.show()
    driver, _, trace = driver_factory(phases)
    observations = BusyObserver(driver).run_show()

    assert [item["outcome"] for item in observations] == ["held_high_unverified"] * 4
    assert trace == baseline_trace
    assert [item for item in trace if item[0] == "sleep"] == [
        ("sleep", 1.0), ("sleep", 0.4), ("sleep", 45.0), ("sleep", 0.4),
    ]
    assert not any(item[0] in {"wait_edge_events", "read_edge_events"} for item in trace)
    assert ("command", 0x02, [0x00]) in trace


@pytest.mark.parametrize("operation", ["get", "wait", "read", "drain"])
def test_gpio_exceptions_propagate_and_restore_attributes(driver_factory, operation):
    fault = OSError("inert GPIO fault")
    phases = [(fault if operation == "get" else Value.INACTIVE,
               fault if operation == "wait" else True)]
    driver, gpio, _ = driver_factory(phases)

    def raising_read():
        raise fault

    def raising_iterator():
        yield "one-edge"
        raise fault

    if operation == "read":
        gpio.read_edge_events = raising_read
    elif operation == "drain":
        gpio.read_edge_events = raising_iterator
    observer = BusyObserver(driver)
    with pytest.raises(OSError) as caught:
        observer.run_show()

    assert caught.value is fault
    assert observer.observations == [{
        "phase": "setup", "sequence": 1, "timeout": 1.0,
        "outcome": "error", "error_type": "OSError",
    }]
    assert driver._gpio is gpio
    assert "_busy_wait" not in vars(driver)


@pytest.mark.parametrize("fault", [RuntimeError("show failed"), SystemExit(3)])
def test_show_exceptions_keep_completed_diagnostics_and_instance_method(driver_factory, fault):
    driver, gpio, _ = driver_factory()
    previous_wait = driver._busy_wait
    driver._busy_wait = previous_wait

    def failed_show():
        driver._busy_wait(1.0)
        raise fault

    driver.show = failed_show
    observer = BusyObserver(driver)
    with pytest.raises(type(fault)) as caught:
        observer.run_show()

    assert caught.value is fault
    assert observer.observations[0]["outcome"] == "edge_received"
    assert driver._busy_wait is previous_wait
    assert driver._gpio is gpio


def test_class_gpio_is_not_shadowed_after_observation(driver_factory):
    driver, gpio, _ = driver_factory()
    type(driver)._gpio = gpio
    del driver._gpio

    BusyObserver(driver).run_show()

    assert driver._gpio is gpio
    assert "_gpio" not in vars(driver)
    assert "_busy_wait" not in vars(driver)


def test_first_show_preserves_gpio_created_by_setup(driver_factory):
    driver, gpio, _ = driver_factory(lazy_gpio=True)
    assert driver._gpio is None

    BusyObserver(driver).run_show()

    assert driver._gpio is gpio
    assert driver.show_calls == 1


@pytest.mark.filterwarnings("ignore:Busy Wait")
def test_two_instances_observe_independently_during_overlapping_shows(driver_factory):
    barrier = Barrier(2)
    healthy, healthy_gpio, _ = driver_factory(barrier=barrier)
    failed, failed_gpio, _ = driver_factory([(Value.INACTIVE, False)] * 4, barrier=barrier)
    observers = [BusyObserver(healthy), BusyObserver(failed)]

    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(observer.run_show) for observer in observers]
        results = [task.result(timeout=5) for task in tasks]

    assert [item["outcome"] for item in results[0]] == ["edge_received"] * 4
    assert [item["outcome"] for item in results[1]] == ["edge_timeout"] * 4
    assert healthy._gpio is healthy_gpio
    assert failed._gpio is failed_gpio
    assert "_busy_wait" not in vars(healthy)
    assert "_busy_wait" not in vars(failed)


@pytest.mark.filterwarnings("ignore:Busy Wait")
def test_second_show_starts_fresh_and_keeps_previous_result_stable(driver_factory):
    driver, gpio, _ = driver_factory([(Value.INACTIVE, False)] * 4)
    observer = BusyObserver(driver)
    previous = observer.run_show()
    gpio.phases = [(Value.INACTIVE, True)] * 4
    gpio.index = -1

    current = observer.run_show()

    assert len(previous) == len(current) == 4
    assert previous is not current
    assert [item["outcome"] for item in previous] == ["edge_timeout"] * 4
    assert [item["outcome"] for item in current] == ["edge_received"] * 4
    assert current[0]["sequence"] == 1
    assert driver.show_calls == 2


def test_unexpected_timeout_or_extra_wait_has_unrecognized_phase(driver_factory):
    driver, _, _ = driver_factory([(Value.INACTIVE, True)] * 5)

    def unusual_show():
        for timeout in [2.0, 0.4, 45.0, 0.4, 0.4]:
            driver._busy_wait(timeout=timeout)

    driver.show = unusual_show
    observations = BusyObserver(driver).run_show()

    assert [item["phase"] for item in observations] == [
        "unrecognized", "power_on", "refresh", "power_off", "unrecognized",
    ]
    assert [item["outcome"] for item in observations] == ["edge_received"] * 5


@pytest.mark.parametrize(("condition", "outcome", "code"), [
    ("healthy", "edge_received", None),
    ("timeout", "edge_timeout", "display_busy_timeout"),
    ("held_high", "held_high_unverified", "display_busy_unverified"),
    ("empty_events", "edge_unverified", "display_busy_unverified"),
])
@pytest.mark.filterwarnings("ignore:Busy Wait")
def test_upstream_busy_sequence_through_controller_and_display_api(
    client, png_factory, driver_factory, condition, outcome, code,
):
    """Exercise upload -> queue -> real controller/observer -> response/ack."""
    phases = [(Value.INACTIVE, True)] * 4
    if condition == "timeout":
        phases[2] = (Value.INACTIVE, False)
    elif condition == "held_high":
        phases[2] = (Value.ACTIVE, None)
    driver, gpio, trace = driver_factory(phases)
    if condition == "empty_events":
        original_read = gpio.read_edge_events

        def read():
            events = original_read()
            return [] if gpio.index == 2 else events

        gpio.read_edge_events = read

    def set_image(image, *, saturation):
        trace.append(("set_image", image.size, image.mode, saturation))

    driver.set_image = set_image
    display = client.app.state.display
    display._impl, display._is_mock = driver, False
    display._busy_observer = BusyObserver(driver)

    upload = client.post(
        "/api/queue",
        files={"file": ("test.png", png_factory(), "image/png")},
    )
    assert upload.status_code == 201
    photo_id = upload.json()["photo"]["id"]
    original_queue = client.get("/api/queue").json()
    original_history = client.get("/api/history").json()
    assert len(original_queue) == 1
    assert original_history == []

    response = client.post("/api/display/next")

    assert driver.show_calls == 1
    assert trace[0][:3] == ("set_image", (800, 480), "RGB")
    # The actual upstream _update has completed POF and its final busy wait
    # before the controller emits a success or a deferred failure response.
    assert trace[-5:] == [
        ("command", 0x02, [0x00]),
        ("get_value", 17),
        ("wait_edge_events", timedelta(seconds=0.4)),
        ("read_edge_events",),
        ("show_returned",),
    ]
    diagnostics = client.get("/api/display/status").json()
    assert diagnostics["observations"][2]["outcome"] == outcome
    assert driver._gpio is gpio
    assert "_busy_wait" not in vars(driver)

    if code is None:
        assert response.status_code == 202
        assert client.get("/api/queue").json() == []
        history = client.get("/api/history").json()
        assert len(history) == 1
        assert history[0]["photo"]["id"] == photo_id
        assert history[0]["source"] == "manual_next"
    else:
        assert response.status_code == 503
        assert response.json()["code"] == code
        assert diagnostics["error"]["code"] == code
        assert client.get("/api/queue").json() == original_queue
        assert client.get("/api/history").json() == original_history
        completed_trace = list(trace)
        second = client.post("/api/display/next")
        assert second.status_code == 503
        assert second.json()["code"] == code
        assert driver.show_calls == 1
        assert trace == completed_trace
        assert client.get("/api/queue").json() == original_queue
        assert client.get("/api/history").json() == original_history
