"""Inert loopback OpenSSL fixture for the Swift TLS client, never a product server.

Run with PYTHONPATH=server python -m tests.softap_interop_server DIRECTORY.
It writes fixture.json and prints only its path. SIGTERM drains both listeners.
The fixture identity and echo payload contain no real frame/owner/Wi-Fi secret.
"""
from __future__ import annotations

import asyncio
import base64
import json
import signal
import sys
from pathlib import Path

from inky_web.provisioning.bootstrap_tls import BootstrapTLSContext
from inky_web.provisioning.identity import load_or_create_identity
from inky_web.provisioning.softap_transport import SoftAPServer, SoftAPTransport
from inky_web.provisioning.transport import BOOTSTRAP_PROFILE, NORMAL_PROFILE


async def run(directory):
    directory.mkdir(parents=True, exist_ok=True)
    identity = load_or_create_identity(directory / "synthetic-identity")
    async def handler(message):
        return {"v": 1, "id": message.get("id"), "ok": True, "result": {"synthetic": True}}
    servers = []
    config = {"host": "127.0.0.1", "frame_id": identity.frame_id,
              "spki_sha256": identity.spki_sha256,
              "certificate_der": base64.b64encode(identity.cert_der).decode("ascii")}
    try:
        for profile in (BOOTSTRAP_PROFILE, NORMAL_PROFILE):
            context = BootstrapTLSContext(identity) if profile == BOOTSTRAP_PROFILE else identity.ssl_context()
            transport = SoftAPTransport(context, handler, profile=profile)
            server = SoftAPServer(transport, identity, profile=profile, host="127.0.0.1", port=0)
            await server.start()
            servers.append(server)
            config["bootstrap_port" if profile == BOOTSTRAP_PROFILE else "normal_port"] = server.server.sockets[0].getsockname()[1]
        fixture = directory / "fixture.json"
        fixture.write_text(json.dumps(config, sort_keys=True) + "\n", encoding="ascii")
        print(fixture, flush=True)
        stopped = asyncio.Event()
        loop = asyncio.get_running_loop()
        for name in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(name, stopped.set)
        await stopped.wait()
    finally:
        for server in servers:
            await server.stop()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("A private synthetic-fixture directory is required")
    asyncio.run(run(Path(sys.argv[1])))
