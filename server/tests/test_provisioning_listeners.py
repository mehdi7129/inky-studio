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
from contextlib import contextmanager
from http.cookies import SimpleCookie
from pathlib import Path

import pytest

from inky_web.provisioning.identity import load_or_create_identity

CHILD = r'''
import asyncio
import json
import os
from pathlib import Path

import uvicorn

from inky_web import auth, main
from inky_web.provisioning.bluez import BlueZServer

directory = Path(os.environ["INKY_STUDIO_DATA_DIR"])
directory.mkdir(parents=True, exist_ok=True)
auth._write_credentials(auth._new_credentials(directory, "listener-test-password"))

def event(name, **details):
    with (directory / "events.jsonl").open("a") as output:
        output.write(json.dumps({"name": name, **details}) + "\n")

def initialize(self):
    # DisplayController.__init__ already creates its safe mock state. Never
    # import or probe the physical driver, including on Linux CI runners.
    event("display.initialize")

original_shutdown = main.DisplayController.shutdown
def shutdown(self):
    event("display.shutdown")
    original_shutdown(self)

original_init = main.init_db
def init_db():
    event("lifespan.initialize")
    original_init()

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
main.init_db = init_db
main.Scheduler.start = scheduler_start
main.Scheduler.stop = scheduler_stop
BlueZServer.start = bluez_start

OriginalConfig = uvicorn.Config
def config(*args, **kwargs):
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
            raise RuntimeError("synthetic listener failure")
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


def _listeners(process, directory):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and process.poll() is None:
        ports = {event["protocol"]: event["port"] for event in _events(directory)
                 if event["name"] == "listen"}
        if len(ports) == 2:
            return ports
        time.sleep(0.02)
    pytest.fail(f"Listeners did not start: {(directory / 'process.log').read_text()}")


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
