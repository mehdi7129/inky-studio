"""Pipe-only native interop fixture: production bootstrap, synthetic adapters.

Every secret is generated inside a private temporary directory. This process is
never an installed service and does not import the normal HTTP application.
"""
from __future__ import annotations

import asyncio
import base64
import copy
import json
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

ROOT, DIRECTORY = map(Path, sys.argv[1:3])
MTU, PROFILE = int(sys.argv[3]), sys.argv[4]
sys.path.insert(0, str(ROOT / "server"))

from inky_web.provisioning.bootstrap_runtime import BootstrapRuntime
from inky_web.provisioning.factory import FactoryState
from inky_web.provisioning.first_boot import FirstBootCoordinator
from inky_web.provisioning.transport import GATTTransport, TransportError

EPOCH = "e" * 64


class SyntheticOS:
    def __init__(self):
        self.state = {"status": "authorized"}
        self.receipt = {"receipt_id": str(uuid4()), "digest": "d" * 64}

    def inspect_initialization(self):
        return copy.deepcopy(self.state)

    def begin_initialization(self, intent):
        status = "newly_consumed" if self.state["status"] == "authorized" else "already_consumed"
        self.state = {"status": "consumed", "intent": intent, "receipt": self.receipt.copy()}
        return {**copy.deepcopy(self.state), "status": status}


class SyntheticDisplay:
    """Exercise real QR/status rendering while replacing only physical output."""

    def __init__(self):
        self.spec = SimpleNamespace(width=800, height=480)
        self.closing = False
        self.reservation = None
        self.lock = threading.RLock()

    @contextmanager
    def operation(self):
        with self.lock:
            yield

    def reserve(self, value):
        assert self.reservation in (None, value)
        self.reservation = value

    def release(self, value):
        if self.reservation == value:
            self.reservation = None

    def display_image(self, path, **_):
        # The production screen already saved and fsynced its synthetic image.
        assert Path(path).is_file()


class SyntheticBlueZ:
    def __init__(self, transport, identity, **_):
        self.transport, self.identity = transport, identity

    async def start(self):
        pass

    async def stop(self):
        self.transport.close()


def emit(value):
    print(json.dumps(value, separators=(",", ":")), flush=True)


async def main():
    os_adapter = SyntheticOS()
    coordinator = FirstBootCoordinator(DIRECTORY, os_adapter, lambda: EPOCH)
    runtime = None
    qr_codes = []
    handler_calls = 0

    async def start():
        nonlocal runtime
        result = coordinator.initialize()
        runtime = BootstrapRuntime(result, lambda: EPOCH, SyntheticDisplay(), DIRECTORY,
                                   server_factory=SyntheticBlueZ)
        original_show_qr = runtime.screen.show_qr

        def observe(payload):
            qr_codes.append(json.loads(payload))
            original_show_qr(payload)

        runtime.screen.show_qr = observe
        await runtime.start()
        original_command = runtime.command

        async def counted_command(message):
            nonlocal handler_calls
            handler_calls += 1
            return await original_command(message)

        runtime.transport.handler = counted_command
        if PROFILE == "normal-alpn":
            # Deliberately incompatible production v1 peer, still advertising
            # a syntactically correct bootstrap identity. TLS must stop it.
            context = result.prepared_identity.bootstrap_tls_context()._context
            context.set_alpn_protocols(["inky-normal/1"])
            runtime.transport.close()
            runtime.transport = GATTTransport(context, counted_command)
        identity = runtime.bluez.identity
        return {"identity": {"v": 2, "p": "bootstrap", "id": identity.frame_id,
                             "cert": base64.b64encode(identity.cert_der).decode()},
                "qr": qr_codes[0], "qr_count": len(qr_codes),
                "adopted": result.ownership.factory_status().state == FactoryState.ADOPTED}

    try:
        emit(await start())
        for line in sys.stdin:
            incoming = json.loads(line)
            if incoming.get("control") == "restart":
                await runtime.stop()
                emit(await start())
                continue
            if incoming.get("control") == "stop":
                break
            try:
                runtime.transport.write("synthetic-native-phone", base64.b64decode(incoming["frame"], validate=True), mtu=MTU)
                await asyncio.sleep(0)
                response = runtime.transport.read("synthetic-native-phone")
                session = runtime.transport.sessions.get("synthetic-native-phone")
                authenticated = bool(session and session.peer.authenticated)
                alpn = session.peer.tls.selected_alpn_protocol() if session else None
                emit({"frame": base64.b64encode(response).decode(), "authenticated": authenticated,
                      "alpn": alpn, "handler_calls": handler_calls,
                      "adopted": runtime.owners.factory_status().state == FactoryState.ADOPTED})
            except (TransportError, ValueError):
                # Do not reflect internal details or synthetic credentials.
                emit({"error": "closed", "handler_calls": handler_calls})
    finally:
        if runtime:
            await runtime.stop()


asyncio.run(main())
