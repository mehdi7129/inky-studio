"""Real helper/client AF_UNIX exchange; injected proof and no NetworkManager."""
from __future__ import annotations

import importlib.util
import socket
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from inky_web.provisioning.network import NetworkClient

HELPER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "inky-network-helper.py"
SPEC = importlib.util.spec_from_file_location("inky_helper_peer_budget", HELPER_PATH)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


def test_factory_helper_waits_for_valid_client_proof_before_request():
    calls, events = [], []

    class Engine:
        def handle(self, request):
            calls.append(request)
            return {"cancelled": True}

        def tick(self):
            pass

    @contextmanager
    def guard(connection):
        assert connection.fileno() >= 0
        time.sleep(4)  # Legal proof duration exceeds the old helper's 2 s read.
        events.append("verified")
        try:
            yield
        finally:
            assert connection.fileno() == -1
            events.append("released")

    with tempfile.TemporaryDirectory(prefix="inky-helper-proof-", dir="/tmp") as directory:
        path = Path(directory) / "control.sock"
        with helper.Server(path, Engine()) as server:
            server.factory_stop = SimpleNamespace(requested=False)
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            try:
                assert NetworkClient(str(path), peer_guard=guard).cancel_pending_sync() is None
            finally:
                thread.join(3)
                assert not thread.is_alive()
    assert calls == [{"op": "cancel_pending"}]
    assert events == ["verified", "released"]


@pytest.mark.parametrize("factory", [False, True])
def test_helper_empty_connection_remains_bounded(factory, monkeypatch):
    monkeypatch.setattr(helper, "FACTORY_REQUEST_READ_SECONDS", 0.15)
    monkeypatch.setattr(helper, "LEGACY_REQUEST_READ_SECONDS", 0.05)

    class Engine:
        def handle(self, _):
            pytest.fail("An empty connection must not invoke an operation")

    with tempfile.TemporaryDirectory(prefix="inky-helper-empty-", dir="/tmp") as directory:
        path = Path(directory) / "control.sock"
        with helper.Server(path, Engine()) as server:
            server.factory_stop = SimpleNamespace(requested=False) if factory else None
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(1)
                    client.connect(str(path))
                    started = time.monotonic()
                    response = client.recv(16385)
                    elapsed = time.monotonic() - started
                    assert response == b'{"ok":false,"error":"network_failed"}\n'
                    assert elapsed >= (0.12 if factory else 0.04)
                    assert elapsed < 0.8
            finally:
                thread.join(2)
                assert not thread.is_alive()
