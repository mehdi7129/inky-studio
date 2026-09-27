#!/usr/bin/env python3
"""Qualify a candidate backend in private scratch data, without SPI or Wi-Fi writes.

Use the candidate venv's Python and --server-dir /path/to/candidate/server.
By default BlueZ is replaced and only helper health is requested. --bluez-real
registers the candidate's real GATT service temporarily. --scan-real requires
the operator to establish that no helper transaction is pending: the installed
helper runs its transaction watchdog before handling scan. No other operation
can reach the helper, including cancellation during runtime shutdown.

The TLS/GATT stream check is in process; it does not qualify radio transport.
Temporary credentials, owner tokens and QR payloads are never printed. All
scratch artifacts are deleted unless --keep-data is explicitly requested.
"""
from __future__ import annotations

import argparse
import asyncio
import http.client
import json
import os
import secrets
import shutil
import socket
import ssl
import struct
import sys
import tempfile
from collections import Counter
from http.cookies import SimpleCookie
from pathlib import Path
from uuid import uuid4


class QualificationFailure(Exception):
    pass


def require(condition, check):
    if not condition:
        raise QualificationFailure(check)


def request(port, path, *, identity=None, method="GET", payload=None, cookie=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    version = None
    if identity is not None:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.load_verify_locations(cadata=identity.cert_pem.decode())
        connection.sock = context.wrap_socket(
            socket.create_connection(("127.0.0.1", port), timeout=10),
            server_hostname=identity.server_name,
        )
        version = connection.sock.version()
    headers = {"Content-Type": "application/json"}
    if cookie is not None:
        headers["Cookie"] = cookie
    try:
        connection.request(method, path, body=None if payload is None else json.dumps(payload), headers=headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), json.loads(response.read()), version
    finally:
        connection.close()


class TLSClient:
    """OpenSSL client over the production acknowledged GATT stream implementation."""

    def __init__(self, transport, identity, qr):
        require(qr["id"] == identity.frame_id and qr["k"] == identity.spki_sha256, "qr_identity_pin")
        self.transport = transport
        self.device = "/org/inky/qualification/" + uuid4().hex
        self.sequence = 0
        self.header = struct.Struct("!BHH")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.load_verify_locations(cadata=identity.cert_pem.decode())
        self.incoming, self.outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
        self.tls = context.wrap_bio(self.incoming, self.outgoing, server_hostname=identity.server_name)
        reset = b"\0" + secrets.token_bytes(16)
        transport.write(self.device, reset, 247)
        require(transport.read(self.device) == reset, "gatt_reset")

    def exchange(self):
        self.sequence += 1
        packet = self.header.pack(1, self.sequence, self.sequence - 1) + self.outgoing.read(239)
        self.transport.write(self.device, packet, 247)
        self.transport.write(self.device, packet, 247)
        response = self.transport.read(self.device)
        require(response == self.transport.read(self.device), "gatt_retry")
        require(self.header.unpack_from(response) == (1, self.sequence, self.sequence), "gatt_sequence")
        self.incoming.write(response[self.header.size:])

    async def handshake(self):
        async with asyncio.timeout(20):
            while True:
                try:
                    self.tls.do_handshake()
                    while self.outgoing.pending:
                        self.exchange()
                    require(self.tls.version() == "TLSv1.3", "gatt_tls13")
                    return
                except ssl.SSLWantReadError:
                    self.exchange()
                    await asyncio.sleep(0.002)

    async def command(self, payload):
        encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
        self.tls.write(struct.pack("!I", len(encoded)) + encoded)
        received = bytearray()
        async with asyncio.timeout(25):
            while True:
                self.exchange()
                await asyncio.sleep(0.005)
                try:
                    received.extend(self.tls.read(20000))
                except ssl.SSLWantReadError:
                    continue
                if len(received) >= 4 and len(received) == struct.unpack("!I", received[:4])[0] + 4:
                    result = json.loads(received[4:])
                    require(result.get("id") == payload["id"] and result.get("ok") is True,
                            "tls_command_" + payload["op"])
                    return result["result"]

    def close(self):
        self.transport.disconnect(self.device)


async def qualify(args, directory):
    # All imports and constructors that resolve application data happen only
    # after isolation. Never load credentials from an existing frame directory.
    os.environ["INKY_STUDIO_DATA_DIR"] = str(directory)
    os.environ["INKY_STUDIO_DISABLE_AUTH"] = "0"
    os.environ["INKY_STUDIO_BLUETOOTH"] = "1"
    sys.path.insert(0, str(args.server_dir.resolve()))
    import uvicorn
    from inky_web import auth, main
    from inky_web.provisioning import runtime, screen
    from inky_web.provisioning.bluez import BlueZServer
    from inky_web.provisioning.network import NetworkClient, NetworkUnavailable

    events = Counter()
    helper_operations = []
    qr_values = []
    listeners, servers = {}, []
    ready = asyncio.Event()
    password = secrets.token_urlsafe(24)
    auth._write_credentials(auth._new_credentials(directory, password))

    class MockOnlyDisplay(main.DisplayController):
        def initialize(self):
            self._impl, self._is_mock = None, True
            events["display_initialize"] += 1

        def _display_image(self, path, saturation=None):
            require(self._impl is None and self._is_mock, "mock_display_only")
            require(Path(path).resolve().is_relative_to(directory), "mock_image_isolated")
            events["mock_images"] += 1
            target = directory / f"mock-screen-{events['mock_images']}.png"
            shutil.copyfile(path, target)
            target.chmod(0o600)

        def shutdown(self):
            events["display_shutdown"] += 1
            super().shutdown()

    class ReadOnlyNetwork:
        def __init__(self):
            self.client = NetworkClient(args.network_socket)

        async def call(self, operation, **arguments):
            if operation != "health" and not (operation == "scan" and args.scan_real):
                raise NetworkUnavailable("qualification_operation_forbidden")
            helper_operations.append(operation)
            return await self.client.call(operation, **arguments)

        def cancel_pending_sync(self):
            # Both runtime shutdown and any credential hook must remain local.
            # Never cancel a transaction belonging to the production application.
            events["local_cancel_noop"] += 1

    main.DisplayController = MockOnlyDisplay
    runtime.NetworkClient = ReadOnlyNetwork
    original_show = screen.show

    def show(display, private_dir, payload):
        qr_values.append(json.loads(payload))
        original_show(display, private_dir, payload)

    screen.show = show
    if not args.bluez_real:
        async def fake_bluez_start(self):
            events["mock_bluez_start"] += 1
        BlueZServer.start = fake_bluez_start

    original_config = uvicorn.Config

    def config(*arguments, **options):
        options.update(host="127.0.0.1", port=0, log_level="warning", access_log=False)
        return original_config(*arguments, **options)

    uvicorn.Config = config
    original_startup = uvicorn.Server.startup

    async def startup(self, sockets=None):
        servers.append(self)
        await original_startup(self, sockets=sockets)
        if self.started:
            name = "https" if self.config.ssl else "http"
            listeners[name] = self.servers[0].sockets[0].getsockname()[1]
            if len(listeners) == 2:
                ready.set()

    uvicorn.Server.startup = startup
    serve_task = asyncio.create_task(main.serve_with_https())
    ready_task = asyncio.create_task(ready.wait())
    checks = []
    stream = None
    try:
        done, _ = await asyncio.wait((serve_task, ready_task), timeout=30, return_when=asyncio.FIRST_COMPLETED)
        if serve_task in done:
            await serve_task
        require(ready.is_set(), "dual_listener_startup")
        frame = main.app.state.provisioning
        require(frame is not None and frame.available, "bluez_registration")
        require(main.app.state.display.is_mock, "mock_display")
        identity = frame.identity
        checks.append("dual_loopback_listeners")

        async def http(path, *, secure=False, **options):
            return await asyncio.to_thread(request, listeners["https" if secure else "http"], path,
                                           identity=identity if secure else None, **options)

        status, _, body, _ = await http("/api/queue")
        require(status == 401, "normal_auth_required")
        status, headers, body, _ = await http("/api/auth/login", method="POST", payload={"password": password})
        require(status == 200 and body.get("authenticated"), "normal_auth_login")
        cookie = "inky_session=" + SimpleCookie(headers["set-cookie"])["inky_session"].value
        for secure in (False, True):
            status, _, body, version = await http("/api/auth/status", secure=secure, cookie=cookie)
            require(status == 200 and body.get("authenticated"), "shared_cookie")
            require(version == ("TLSv1.3" if secure else None), "https_tls13")
        checks.extend(("normal_auth", "shared_http_https_session", "https_tls13"))
        status, _, body, _ = await http("/api/provisioning/capabilities", cookie=cookie)
        require(status == 200 and body.get("bluetooth") is True, "helper_health_ready")
        checks.append("real_helper_health")
        status, _, body, _ = await http("/api/provisioning/adoption/window", method="POST", cookie=cookie)
        require(status == 200 and set(body) == {"frame_id", "expires_in"}, "physical_qr_not_http")
        require(len(qr_values) == 1 and events["mock_images"] == 1, "mock_qr_render")
        require((directory / "mock-screen-1.png").is_file(), "mock_qr_png")
        checks.append("private_mock_qr")
        stream = TLSClient(frame.transport, identity, qr_values[0])
        await stream.handshake()
        owner_id, owner_token = str(uuid4()), secrets.token_hex(32)

        async def command(operation, **extra):
            return await stream.command({"v": 1, "id": str(uuid4()), "op": operation,
                                         "owner_id": owner_id, "owner_token": owner_token, **extra})

        claimed = await command("claim", claim_token=qr_values[0]["t"])
        require(claimed["frame_id"] == identity.frame_id, "ownership_claim")
        require((await command("status"))["frame_id"] == identity.frame_id, "owner_status")
        require(not frame.display.reserved, "qr_restored_after_claim")
        checks.extend(("in_process_gatt_tls13_claim", "owner_status", "mock_qr_restored"))
        if args.scan_real:
            result = await command("wifi.scan")
            require(isinstance(result.get("networks"), list), "real_wifi_scan")
            checks.append("real_helper_scan")
        for forbidden in ("begin", "confirm", "cancel", "cancel_owner", "cancel_pending"):
            try:
                await frame.network.call(forbidden)
            except NetworkUnavailable:
                pass
            else:
                raise QualificationFailure("helper_mutation_not_blocked")
        checks.append("helper_mutations_blocked")
    finally:
        ready_task.cancel()
        await asyncio.gather(ready_task, return_exceptions=True)
        if stream is not None:
            stream.close()
        for server in servers:
            server.should_exit = True
        try:
            await asyncio.wait_for(serve_task, timeout=25)
        except TimeoutError:
            raise QualificationFailure("candidate_cleanup_timeout") from None
    require(events["display_initialize"] == events["display_shutdown"] == 1, "single_display_lifecycle")
    require(events["local_cancel_noop"] == 1, "isolated_shutdown_cancellation")
    require(set(helper_operations) <= {"health", "scan"}, "helper_read_only_proxy")
    checks.append("single_lifecycle_cleanup")
    return {"ok": True, "checks": checks, "bluez": "real" if args.bluez_real else "mock",
            "gatt_stream": "in_process", "spi_calls": 0, "ports": listeners,
            "helper_operations": helper_operations, "display": dict(events),
            "wifi_scan": "explicit_opt_in" if args.scan_real else "skipped"}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server-dir", type=Path, default=Path(__file__).resolve().parents[1] / "server")
    parser.add_argument("--network-socket", default="/run/inky-network/control.sock")
    parser.add_argument("--bluez-real", action="store_true", help="Temporarily register real BlueZ GATT and advertisement")
    parser.add_argument("--scan-real", action="store_true",
                        help="Operator confirms no pending helper transaction; allow its real scan/watchdog")
    parser.add_argument("--keep-data", action="store_true", help="Keep private test credentials and mock PNG artifacts")
    args = parser.parse_args()
    os.umask(0o077)
    directory = Path(tempfile.mkdtemp(prefix="inky-qualify-")).resolve()
    try:
        result = asyncio.run(qualify(args, directory))
        if args.keep_data:
            result["private_test_data"] = str(directory)
        print(json.dumps(result, separators=(",", ":")))
        return 0
    except Exception as error:  # noqa: BLE001 — emit only the sanitized qualification report, never raw secrets
        print(json.dumps({"ok": False, "error": type(error).__name__,
                          "check": str(error) if isinstance(error, QualificationFailure) else "candidate_failed",
                          **({"private_test_data": str(directory)} if args.keep_data else {})}), file=sys.stderr)
        return 1
    finally:
        if not args.keep_data:
            shutil.rmtree(directory)


if __name__ == "__main__":
    raise SystemExit(main())
