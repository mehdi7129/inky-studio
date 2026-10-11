"""Actual Unix connections with injected proof doubles; no native peer qualification."""
from __future__ import annotations

import asyncio
import json
import socket
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from inky_web.provisioning import network

GOOD = b'{"ok":true,"result":{"cancelled":true}}\n'


@pytest.fixture
def helper_socket():
    servers = []

    def create(handler):
        directory = tempfile.TemporaryDirectory(prefix="inky-peer-", dir="/tmp")
        path = str(Path(directory.name) / "control.sock")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(path)
        listener.listen()
        listener.settimeout(0.05)
        stop = threading.Event()
        accepted = threading.Event()
        raw_requests, errors = [], []

        def run():
            while not stop.is_set():
                try:
                    connection, _ = listener.accept()
                except TimeoutError:
                    continue
                except OSError:
                    return
                try:
                    with connection:
                        connection.settimeout(4)
                        accepted.set()
                        raw = bytearray()
                        while not raw.endswith(b"\n"):
                            chunk = connection.recv(8193)
                            if not chunk:
                                break
                            raw.extend(chunk)
                        raw_requests.append(bytes(raw))
                        if raw:
                            handler(connection, json.loads(raw))
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except BaseException as error:
                    errors.append(error)

        thread = threading.Thread(target=run)
        thread.start()
        server = SimpleNamespace(path=path, listener=listener, stop=stop, thread=thread,
                                 directory=directory, raw_requests=raw_requests,
                                 errors=errors, accepted=accepted)
        servers.append(server)
        return server

    yield create
    for server in servers:
        server.stop.set()
        server.listener.close()
        server.thread.join(5)
        server.directory.cleanup()
        assert not server.thread.is_alive()
        assert not server.errors


async def request(client, mode):
    if mode == "sync":
        await asyncio.to_thread(client.cancel_pending_sync)
        return None
    return await client.call("cancel_pending")


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_guard_uses_actual_connected_socket_through_parse_and_close(helper_socket, monkeypatch, mode):
    active, events = [], []
    loads = json.loads

    @contextmanager
    def guard(connection):
        assert connection.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) == socket.SOCK_STREAM
        assert connection.fileno() >= 0
        assert connection.getpeername() == server.path
        active.append(connection)
        events.append("enter")
        try:
            yield
        finally:
            assert connection.fileno() == -1
            events.append("closed")
            active.pop()

    def parse(raw, *args, **kwargs):
        if raw == GOOD:
            assert len(active) == 1 and active[0].fileno() >= 0
            events.append("parsed")
        return loads(raw, *args, **kwargs)

    monkeypatch.setattr(network.json, "loads", parse)
    server = helper_socket(lambda connection, _: connection.sendall(GOOD))
    result = await request(network.NetworkClient(server.path, peer_guard=guard), mode)
    assert result == (None if mode == "sync" else {"cancelled": True})
    assert events == ["enter", "parsed", "closed"] and not active
    assert server.raw_requests == [b'{"op":"cancel_pending"}\n']


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("phase", ["factory", "enter"])
async def test_guard_refusal_before_send_is_fixed_and_zero_bytes(helper_socket, mode, phase):
    class Refused:
        def __enter__(self):
            raise RuntimeError("private-proof-diagnostic")

        def __exit__(self, *_):
            pytest.fail("The proof was never entered")

    def guard(connection):
        assert connection.fileno() >= 0
        if phase == "factory":
            raise RuntimeError("private-proof-diagnostic")
        return Refused()

    server = helper_socket(lambda *_: pytest.fail("No bytes may reach the helper"))
    with pytest.raises(network.NetworkUnavailable, match="^network_unavailable$") as caught:
        await request(network.NetworkClient(server.path, peer_guard=guard), mode)
    assert caught.value.__cause__ is None
    assert await asyncio.to_thread(server.accepted.wait, 1)
    assert not any(server.raw_requests)


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_guard_boolean_entry_is_not_a_readiness_grant(helper_socket, mode):
    events = []

    class BooleanProof:
        def __enter__(self):
            events.append("entered")
            return True

        def __exit__(self, *_):
            events.append("released")
            return True

    server = helper_socket(lambda *_: pytest.fail("No request may use a boolean guard"))
    with pytest.raises(network.NetworkUnavailable, match="^network_unavailable$"):
        await request(network.NetworkClient(server.path, peer_guard=lambda _: BooleanProof()), mode)
    assert events == ["entered", "released"] and not any(server.raw_requests)


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_guard_exit_failure_cannot_publish_valid_result(helper_socket, mode):
    @contextmanager
    def guard(connection):
        try:
            yield
        finally:
            assert connection.fileno() == -1
            raise RuntimeError("private-proof-diagnostic")

    server = helper_socket(lambda connection, _: connection.sendall(GOOD))
    with pytest.raises(network.NetworkUnavailable, match="^network_unavailable$") as caught:
        await request(network.NetworkClient(server.path, peer_guard=guard), mode)
    assert caught.value.__cause__ is None and len(server.raw_requests) == 1


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("malformed", ["no_newline", "double_lines", "trailing", "late_trailing", "oversized"])
async def test_attested_helper_requires_exact_response_and_eof(helper_socket, mode, malformed):
    def respond(connection, _request):
        raw = {"no_newline": GOOD[:-1], "double_lines": GOOD + GOOD,
               "trailing": GOOD + b"private", "oversized": b" " * 16385}.get(malformed, GOOD)
        connection.sendall(raw)
        if malformed == "late_trailing":
            time.sleep(0.03)
            connection.sendall(b"private")

    @contextmanager
    def guard(connection):
        try:
            yield
        finally:
            assert connection.fileno() == -1

    server = helper_socket(respond)
    expected = "network_unavailable" if mode == "sync" else "network_response_invalid"
    with pytest.raises(network.NetworkUnavailable, match=f"^{expected}$"):
        await request(network.NetworkClient(server.path, peer_guard=guard), mode)
    assert len(server.raw_requests) == 1


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_guard_remains_live_while_complete_line_waits_for_eof(helper_socket, mode):
    sent, release = threading.Event(), threading.Event()
    active = []

    def respond(connection, _request):
        connection.sendall(GOOD)
        sent.set()
        assert release.wait(3)

    @contextmanager
    def guard(connection):
        active.append(connection)
        try:
            yield
        finally:
            assert connection.fileno() == -1
            active.pop()

    server = helper_socket(respond)
    task = asyncio.create_task(request(network.NetworkClient(server.path, peer_guard=guard), mode))
    try:
        assert await asyncio.to_thread(sent.wait, 2)
        assert not task.done() and len(active) == 1
    finally:
        release.set()
        result = await task
    assert result == (None if mode == "sync" else {"cancelled": True}) and not active


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_attested_complete_line_without_eof_expires_under_existing_deadline(helper_socket, monkeypatch, mode):
    assert network._SYNC_DEADLINE_SECONDS == 15 and network._ASYNC_DEADLINE_SECONDS == 20
    name = "_SYNC_DEADLINE_SECONDS" if mode == "sync" else "_ASYNC_DEADLINE_SECONDS"
    monkeypatch.setattr(network, name, 0.08)
    active = []

    def respond(connection, _request):
        connection.sendall(GOOD)
        assert connection.recv(1) == b""  # A complete line alone never grants success.

    @contextmanager
    def guard(connection):
        active.append(connection)
        try:
            yield
        finally:
            assert connection.fileno() == -1
            active.pop()

    server = helper_socket(respond)
    with pytest.raises(network.NetworkUnavailable, match="^network_unavailable$"):
        await request(network.NetworkClient(server.path, peer_guard=guard), mode)
    assert not active and len(server.raw_requests) == 1


@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_legacy_helper_still_accepts_first_line_without_eof(helper_socket, mode):
    release, sent = threading.Event(), threading.Event()

    def respond(connection, _request):
        connection.sendall(GOOD + b"extra")
        sent.set()
        assert release.wait(3)

    server = helper_socket(respond)
    task = asyncio.create_task(request(network.NetworkClient(server.path), mode))
    try:
        assert await asyncio.to_thread(sent.wait, 2)
        result = await asyncio.wait_for(asyncio.shield(task), 1)
        assert result == (None if mode == "sync" else {"cancelled": True})
    finally:
        release.set()
        await task


async def test_guard_cannot_suppress_explicit_helper_refusal(helper_socket):
    errors = []

    class Suppressing:
        def __enter__(self):
            return None

        def __exit__(self, exception_type, exception, traceback):
            errors.append(exception)
            return True

    server = helper_socket(lambda connection, _: connection.sendall(b'{"ok":false,"error":"busy"}\n'))
    with pytest.raises(network.NetworkUnavailable, match="^busy$"):
        await network.NetworkClient(server.path, peer_guard=lambda _: Suppressing()).call("scan")
    assert len(errors) == 1 and str(errors[0]) == "busy"


@pytest.mark.parametrize("exit_fails", [False, True])
async def test_repeated_cancellation_drains_writer_under_guard_without_orphan(helper_socket, monkeypatch, exit_fails):
    """Real transport; a barrier holds wait_closed after its real closure."""
    active, events = [], []
    close_started, release_close = asyncio.Event(), asyncio.Event()
    server_received = threading.Event()
    original_open = asyncio.open_unix_connection

    @contextmanager
    def guard(connection):
        active.append(connection)
        events.append("entered")
        try:
            yield
        finally:
            assert close_started.is_set() and release_close.is_set()
            assert connection.fileno() == -1
            events.append("proof_released")
            active.pop()
            if exit_fails:
                raise RuntimeError("private-proof-diagnostic")

    class HeldWriter:
        def __init__(self, inner):
            self.inner = inner

        def get_extra_info(self, key):
            return self.inner.get_extra_info(key)

        def write(self, value):
            assert active == [self.inner.get_extra_info("socket")]
            events.append("sent")
            self.inner.write(value)

        async def drain(self):
            await self.inner.drain()

        def close(self):
            assert active
            events.append("close")
            self.inner.close()

        async def wait_closed(self):
            await self.inner.wait_closed()
            close_started.set()
            await release_close.wait()
            assert active
            events.append("drained")

    async def open_connection(*args, **kwargs):
        reader, writer = await original_open(*args, **kwargs)
        return reader, HeldWriter(writer)

    def respond(connection, _request):
        server_received.set()
        assert connection.recv(1) == b""  # The caller closes after cancellation.

    monkeypatch.setattr(network.asyncio, "open_unix_connection", open_connection)
    server = helper_socket(respond)
    task = asyncio.create_task(network.NetworkClient(server.path, peer_guard=guard).call("scan"))
    try:
        assert await asyncio.to_thread(server_received.wait, 2)
        task.cancel()
        await asyncio.wait_for(close_started.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and len(active) == 1
    finally:
        release_close.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert events == ["entered", "sent", "close", "drained", "proof_released"]
    assert not active and len(server.raw_requests) == 1
