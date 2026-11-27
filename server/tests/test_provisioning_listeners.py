"""Run the production dual-listener entry point on real loopback sockets.

Only hardware initialization and BlueZ are replaced. Uvicorn, TLS, auth,
lifespan, scheduler, signal handling and listener failures are real subprocesses.
"""
from __future__ import annotations

import http.client
import json
import os
import signal
import socket
import ssl
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.cookies import SimpleCookie
from pathlib import Path

import pytest
from websockets.sync.client import connect

from inky_web.provisioning.identity import load_or_create_identity

CHILD = r'''
import asyncio
import json
import os
import time
from io import BytesIO
from pathlib import Path

import uvicorn
from PIL import Image

from inky_web import auth, main
from inky_web.provisioning.bluez import BlueZServer
from inky_web.models import SettingsUpdate
from inky_web.services import history, photos, queue, scheduler, settings

directory = Path(os.environ["INKY_STUDIO_DATA_DIR"])
directory.mkdir(parents=True, exist_ok=True)
stage = os.environ.get("HOLD_STAGE")
auth._write_credentials(auth._new_credentials(directory, "listener-test-password", bootstrap=stage == "welcome"))

def event(name, **details):
    with (directory / "events.jsonl").open("a") as output:
        output.write(json.dumps({"name": name, **details}) + "\n")

def hold():
    deadline = time.monotonic() + 30
    while not (directory / "release").exists():
        if time.monotonic() >= deadline:
            raise AssertionError("Inert test driver not released")
        time.sleep(.01)

class Driver:
    def set_image(self, image, **kwargs):
        event("display.set_image")
    def show(self):
        event("display.show.begin")
        (directory / "show-started").touch()
        hold()
        event("display.show.end")

def initialize(self):
    # DisplayController.__init__ already creates its safe mock state. Never
    # import or probe the physical driver, including on Linux CI runners.
    event("display.initialize")
    if stage:
        with self.operation():
            if stage == "initialize":
                event("display.initialize.holding")
                hold()
            self._impl, self._is_mock = Driver(), False

original_shutdown = main.DisplayController.shutdown
def shutdown(self):
    original_shutdown(self)
    event("display.shutdown")

original_begin_shutdown = main.DisplayController.begin_shutdown
def begin_shutdown(self):
    original_begin_shutdown(self)
    event("display.drain")

original_record = history.record
def record(*args, **kwargs):
    result = original_record(*args, **kwargs)
    event("history.record")
    return result
history.record = record
original_remove = queue.remove_entry
def remove(*args, **kwargs):
    result = original_remove(*args, **kwargs)
    event("queue.ack")
    return result
queue.remove_entry = remove
original_manual = scheduler._manual_next
def manual(*args):
    event("request.worker")
    return original_manual(*args)
scheduler._manual_next = manual

original_init = main.init_db
def init_db():
    event("lifespan.initialize")
    original_init()
    if stage:
        settings.update(SettingsUpdate(change_mode="manual"))
    if stage == "request":
        for red in (20, 40):
            content = BytesIO()
            Image.new("RGB", (800, 480), (red, 0, 0)).save(content, format="PNG")
            photo, _ = photos.save(content=content.getvalue(), original_filename="inert.png")
            queue.add(photo.id)

async def bluez_start(self):
    event("bluez.start")

original_start = main.Scheduler.start
async def scheduler_start(self):
    event("scheduler.start")
    await original_start(self)

original_stop = main.Scheduler.stop
async def scheduler_stop(self):
    await original_stop(self)
    event("scheduler.stop")

main.DisplayController.initialize = initialize
main.DisplayController.shutdown = shutdown
main.DisplayController.begin_shutdown = begin_shutdown
main.init_db = init_db
main.Scheduler.start = scheduler_start
main.Scheduler.stop = scheduler_stop
BlueZServer.start = bluez_start

OriginalConfig = uvicorn.Config
def config(*args, **kwargs):
    event("config", workers=kwargs.get("workers"), timeout=kwargs.get("timeout_graceful_shutdown"))
    encrypted = bool(kwargs.get("ssl_certfile"))
    kwargs.update(host="127.0.0.1", port=0, log_level="warning", access_log=False)
    blocked = os.environ.get("BLOCKED_PROTOCOL")
    if blocked == ("https" if encrypted else "http"):
        kwargs["port"] = int(os.environ["BLOCKED_PORT"])
    return OriginalConfig(*args, **kwargs)

uvicorn.Config = config
original_startup = uvicorn.Server.startup
async def startup(self, sockets=None):
    await original_startup(self, sockets=sockets)
    if self.started:
        event("listen", protocol="https" if self.config.ssl else "http",
              port=self.servers[0].sockets[0].getsockname()[1])

uvicorn.Server.startup = startup
if os.environ.get("FAIL_LISTENER") == "1":
    original_main_loop = uvicorn.Server.main_loop
    async def main_loop(self):
        if self.config.ssl:
            if stage == "welcome":
                while not (directory / "show-started").exists():
                    await asyncio.sleep(.01)
            raise RuntimeError("synthetic listener failure")
        await original_main_loop(self)
    uvicorn.Server.main_loop = main_loop
elif os.environ.get("FAIL_LISTENER_AFTER_FILE") == "1":
    original_main_loop = uvicorn.Server.main_loop
    async def main_loop(self):
        if not self.config.ssl:
            while not (directory / "fail-listener").exists():
                await asyncio.sleep(.01)
            raise RuntimeError("synthetic active listener failure")
        await original_main_loop(self)
    uvicorn.Server.main_loop = main_loop

main.run()
event("entry.returned")
'''


def _events(directory):
    path = directory / "events.jsonl"
    result = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                result.append(json.loads(line))
            except ValueError:
                pass  # The child may be finishing the last line right now.
    return result


@contextmanager
def _frame(directory, **overrides):
    directory.mkdir()
    environment = {
        **os.environ, "INKY_STUDIO_DATA_DIR": str(directory),
        "INKY_STUDIO_DISABLE_AUTH": "0", "INKY_STUDIO_BLUETOOTH": "1",
        "PYTHONUNBUFFERED": "1", **overrides,
    }
    with (directory / "process.log").open("w+") as output:
        process = subprocess.Popen(
            [sys.executable, "-c", CHILD], env=environment,
            cwd=Path(__file__).resolve().parents[1], stdout=output, stderr=output,
        )
        try:
            yield process
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def _listeners(process, directory, expected=2):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and process.poll() is None:
        ports = {event["protocol"]: event["port"] for event in _events(directory)
                 if event["name"] == "listen"}
        if len(ports) == expected:
            return ports
        time.sleep(0.02)
    pytest.fail(f"Listeners did not start: {(directory / 'process.log').read_text()}")


def _wait_event(process, directory, name, count=1):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and process.poll() is None:
        if sum(item["name"] == name for item in _events(directory)) >= count:
            return
        time.sleep(.01)
    pytest.fail(f"Missing {name}: {(directory / 'process.log').read_text()}")


def _request(port, path, *, identity=None, method="GET", payload=None, cookie=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    version = None
    if identity:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.load_verify_locations(cadata=identity.cert_pem.decode())
        connection.sock = context.wrap_socket(
            socket.create_connection(("127.0.0.1", port), timeout=3),
            server_hostname=identity.server_name,
        )
        version = connection.sock.version()
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    try:
        connection.request(method, path, body=json.dumps(payload) if payload is not None else None,
                           headers=headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), json.loads(response.read()), version
    finally:
        connection.close()


def _assert_single_lifecycle(directory):
    names = [event["name"] for event in _events(directory)]
    for name in ("lifespan.initialize", "display.initialize", "display.shutdown",
                 "scheduler.start", "scheduler.stop", "bluez.start"):
        assert names.count(name) == 1, (name, names, (directory / "process.log").read_text())


def test_dual_listeners_tls13_share_session_and_exit_on_sigterm(tmp_path):
    directory = tmp_path / "frame"
    with _frame(directory) as process:
        ports = _listeners(process, directory)
        identity = load_or_create_identity(directory / "provisioning")
        assert ports["http"] != ports["https"]
        assert not _request(ports["http"], "/api/auth/status")[2]["authenticated"]
        status, headers, result, _ = _request(
            ports["http"], "/api/auth/login", method="POST",
            payload={"password": "listener-test-password"},
        )
        assert status == 200 and result["authenticated"]
        cookies = SimpleCookie(headers["set-cookie"])
        cookie = f"inky_session={cookies['inky_session'].value}"
        for protocol in ("http", "https"):
            status, _, result, version = _request(
                ports[protocol], "/api/auth/status", cookie=cookie,
                identity=identity if protocol == "https" else None,
            )
            assert status == 200 and result["authenticated"]
            assert version == ("TLSv1.3" if protocol == "https" else None)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_2
        context.load_verify_locations(cadata=identity.cert_pem.decode())
        with socket.create_connection(("127.0.0.1", ports["https"]), timeout=3) as sock:
            with pytest.raises((ssl.SSLError, ConnectionResetError)):
                context.wrap_socket(sock, server_hostname=identity.server_name)
        assert _request(ports["https"], "/api/auth/logout", method="POST",
                        identity=identity, cookie=cookie)[0] == 200
        assert not _request(ports["http"], "/api/auth/status", cookie=cookie)[2]["authenticated"]
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=15) == 0, (directory / "process.log").read_text()
    _assert_single_lifecycle(directory)
    for port in ports.values():
        with socket.socket() as probe:
            probe.settimeout(1)
            assert probe.connect_ex(("127.0.0.1", port)) != 0


@pytest.mark.parametrize("protocol", ["http", "https"])
def test_listener_bind_failure_is_nonzero_and_closes_lifespan(tmp_path, protocol):
    directory = tmp_path / "frame"
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        with _frame(directory, BLOCKED_PROTOCOL=protocol,
                    BLOCKED_PORT=str(occupied.getsockname()[1])) as process:
            assert process.wait(timeout=15) != 0, (directory / "process.log").read_text()
    _assert_single_lifecycle(directory)
    assert "entry.returned" not in [event["name"] for event in _events(directory)]


def test_listener_runtime_failure_is_not_swallowed(tmp_path):
    directory = tmp_path / "frame"
    with _frame(directory, FAIL_LISTENER="1") as process:
        assert process.wait(timeout=15) != 0, (directory / "process.log").read_text()
    _assert_single_lifecycle(directory)
    assert "entry.returned" not in [event["name"] for event in _events(directory)]


@pytest.mark.parametrize("bluetooth", ["0", "1"])
def test_sigterm_drains_admitted_refresh_with_ack_rejects_waiter_and_closes_ws(tmp_path, bluetooth):
    directory = tmp_path / "drain"
    with _frame(directory, HOLD_STAGE="request", INKY_STUDIO_BLUETOOTH=bluetooth,
                WEB_CONCURRENCY="3") as process:
        ports = _listeners(process, directory, expected=1 if bluetooth == "0" else 2)
        _, headers, _, _ = _request(ports["http"], "/api/auth/login", method="POST",
                                   payload={"password": "listener-test-password"})
        cookie = headers["set-cookie"].split(";", 1)[0]

        def next_photo():
            connection = http.client.HTTPConnection("127.0.0.1", ports["http"], timeout=25)
            try:
                connection.request("POST", "/api/display/next", headers={"Cookie": cookie})
                response = connection.getresponse()
                return response.status, response.read()
            finally:
                connection.close()

        with connect(f"ws://127.0.0.1:{ports['http']}/api/ws", additional_headers={"Cookie": cookie}):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(next_photo)
                _wait_event(process, directory, "display.show.begin")
                second = pool.submit(next_photo)
                _wait_event(process, directory, "request.worker", count=2)
                process.send_signal(signal.SIGTERM)
                _wait_event(process, directory, "display.drain")
                process.send_signal(signal.SIGINT)
                process.send_signal(signal.SIGTERM)
                # Cross the old Uvicorn 10 s cancellation threshold on HTTP.
                time.sleep(10.3 if bluetooth == "0" else .2)
                assert process.poll() is None
                assert not first.done()
                assert "display.shutdown" not in [item["name"] for item in _events(directory)]
                (directory / "release").touch()
                assert first.result(timeout=10)[0] == 202
                assert second.result(timeout=10)[0] == 503
            # The server must close the idle WebSocket itself; do not let the
            # client context exit make an otherwise stuck shutdown succeed.
            assert process.wait(timeout=10) == 0, (directory / "process.log").read_text()
    events = _events(directory)
    names = [item["name"] for item in events]
    assert names.count("display.set_image") == names.count("display.show.end") == 1
    assert names.index("display.show.end") < names.index("history.record") < names.index("queue.ack") < names.index("display.shutdown")
    configs = [item for item in events if item["name"] == "config"]
    assert all(item["workers"] == 1 and item["timeout"] is None for item in configs)


@pytest.mark.parametrize("stage", ["initialize", "welcome"])
@pytest.mark.parametrize("bluetooth", ["0", "1"])
def test_signal_during_startup_or_welcome_drains_once(tmp_path, stage, bluetooth):
    directory = tmp_path / "startup"
    with _frame(directory, HOLD_STAGE=stage, INKY_STUDIO_BLUETOOTH=bluetooth) as process:
        _wait_event(process, directory, "display.initialize.holding" if stage == "initialize" else "display.show.begin")
        process.send_signal(signal.SIGTERM)
        _wait_event(process, directory, "display.drain")
        process.send_signal(signal.SIGINT)
        time.sleep(.1)
        assert process.poll() is None
        (directory / "release").touch()
        assert process.wait(timeout=10) == 0, (directory / "process.log").read_text()
    names = [item["name"] for item in _events(directory)]
    assert names.count("display.initialize") == names.count("display.shutdown") == 1
    if stage == "welcome":
        assert names.index("display.show.end") < names.index("display.shutdown")
    else:
        assert "listen" not in names and "display.show.begin" not in names


def test_listener_failure_drains_welcome_before_releasing_hardware(tmp_path):
    directory = tmp_path / "failure-drain"
    with _frame(directory, HOLD_STAGE="welcome", FAIL_LISTENER="1") as process:
        _wait_event(process, directory, "display.show.begin")
        _wait_event(process, directory, "display.drain")
        assert process.poll() is None
        (directory / "release").touch()
        assert process.wait(timeout=10) != 0
    names = [item["name"] for item in _events(directory)]
    assert names.index("display.show.end") < names.index("display.shutdown")


def test_listener_failure_closes_other_listener_admission_before_active_refresh_ends(tmp_path):
    directory = tmp_path / "failure-request"
    with _frame(directory, HOLD_STAGE="request", FAIL_LISTENER_AFTER_FILE="1") as process:
        ports = _listeners(process, directory)
        _, headers, _, _ = _request(ports["http"], "/api/auth/login", method="POST",
                                   payload={"password": "listener-test-password"})
        cookie = headers["set-cookie"].split(";", 1)[0]
        identity = load_or_create_identity(directory / "provisioning")

        def next_photo(protocol):
            connection = http.client.HTTPConnection("127.0.0.1", ports[protocol], timeout=15)
            if protocol == "https":
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                context.load_verify_locations(cadata=identity.cert_pem.decode())
                connection.sock = context.wrap_socket(
                    socket.create_connection(("127.0.0.1", ports[protocol]), timeout=15),
                    server_hostname=identity.server_name,
                )
            try:
                connection.request("POST", "/api/display/next", headers={"Cookie": cookie})
                response = connection.getresponse()
                response.read()
                return response.status
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(next_photo, "http")
            _wait_event(process, directory, "display.show.begin")
            second = pool.submit(next_photo, "https")
            _wait_event(process, directory, "request.worker", count=2)
            (directory / "fail-listener").touch()
            _wait_event(process, directory, "display.drain")
            assert process.poll() is None
            (directory / "release").touch()
            assert first.result(timeout=10) == 202
            assert second.result(timeout=10) == 503
        assert process.wait(timeout=10) != 0
    names = [item["name"] for item in _events(directory)]
    assert names.count("display.show.begin") == 1
    assert names.index("display.drain") < names.index("display.show.end") < names.index("queue.ack") < names.index("display.shutdown")
