#!/usr/bin/env python3
"""Smoke the installed candidate in a disposable Linux ARM64 venv.

Run under a network-disabled namespace, outside image assembly. Does not enter
the application lifespan, create credentials/identity, open GPIO/SPI, contact a
frame, or start a service. GPIO/panel/radio behavior requires separate hardware
qualification. Installation and wheel hashes are checked by the calling bench.
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.metadata
import io
import json
import os
import platform
import socket
import sys
import tempfile
from pathlib import Path


async def request(app, path):
    messages = []
    request_sent = False
    finished = asyncio.Event()

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await finished.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.body" and not message.get("more_body", False):
            finished.set()

    await asyncio.wait_for(app({"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
                               "http_version": "1.1", "method": "GET", "scheme": "http",
                               "path": path, "raw_path": path.encode(), "query_string": b"",
                               "root_path": "", "headers": [(b"host", b"localhost")],
                               "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 8000)}, receive, send), 10)
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return status, body


def main():
    if platform.system() != "Linux" or platform.machine() not in {"aarch64", "arm64"} or sys.version_info[:2] != (3, 13):
        raise SystemExit("This qualification requires Linux ARM64 / CPython 3.13")
    if sys.prefix == sys.base_prefix:
        raise SystemExit("A disposable isolated venv is required")
    # Proof that no non-loopback interface is available in the namespace.
    # sysfs may still describe the parent namespace after unshare --net.
    interfaces = sorted(name for _index, name in socket.if_nameindex())
    if interfaces != ["lo"]:
        raise SystemExit(f"Network isolation missing: {interfaces}")
    for key in list(os.environ):
        if key.startswith("INKY_STUDIO_"):
            del os.environ[key]
    with tempfile.TemporaryDirectory(prefix="inky-offline-smoke-data-") as data:
        os.environ["INKY_STUDIO_DATA_DIR"] = data
        imported = []
        for name in ("spidev", "gpiod", "numpy", "dbus_fast", "pydantic_core", "PIL._imaging",
                     "cryptography.hazmat.bindings._rust", "uvloop", "httptools", "watchfiles"):
            importlib.import_module(name)
            imported.append(name)
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from PIL import Image
        key = Ed25519PrivateKey.generate()
        key.public_key().verify(key.sign(b"offline qualification"), b"offline qualification")
        image = io.BytesIO()
        Image.new("RGB", (8, 8), "blue").save(image, format="PNG")
        assert Image.open(io.BytesIO(image.getvalue())).size == (8, 8)
        from inky_web import __version__, auth
        from inky_web.inky.display import DisplayController

        def hardware_forbidden(*_args, **_kwargs):
            raise AssertionError("This smoke test must not initialize hardware or enter lifespan")

        DisplayController.initialize = hardware_forbidden
        from inky_web.main import app
        app.state.sessions = auth.SessionStore()
        health_status, health_body = asyncio.run(request(app, "/api/health"))
        assert health_status == 200 and json.loads(health_body)["version"] == __version__
        protected_status, _ = asyncio.run(request(app, "/api/state"))
        assert protected_status == 401
        frontend_status, frontend_body = asyncio.run(request(app, "/"))
        assert frontend_status == 200 and b"<html" in frontend_body.lower()
        assert not list(Path(data).iterdir()), "Import/API smoke created application state"
        print(json.dumps({"scope": "offline-linux-arm64-import-and-asgi-smoke", "passed": True,
                          "python": platform.python_version(), "architecture": platform.machine(),
                          "application_version": __version__, "network_interfaces": interfaces,
                          "native_imports": imported, "health_status": health_status,
                          "protected_status": protected_status, "frontend_status": frontend_status,
                          "data_created": False, "application_lifespan_entered": False,
                          "hardware_qualified": False,
                          "rpi_gpio": {"version": importlib.metadata.version("RPi.GPIO"),
                                       "imported": False, "reason": "Raspberry-specific import/hardware guard"}}, indent=2))


if __name__ == "__main__":
    main()
