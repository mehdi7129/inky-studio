#!/usr/bin/env python3
"""Serve the exact legacy-proof PHOTO backend on private HTTP + pinned HTTPS.

Both loopback listeners share one app, lifespan, durable synthetic bootstrap
credential and TLS identity. HTTP accepts only the nonce proof during this test.
Request safety is asserted in memory; bodies, cookies and secrets are never logged.
No backend edits, system trust installation, Bluetooth, SPI or Pi access.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import http.client
import json
import logging
import os
from pathlib import Path
import re
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time

sys.dont_write_bytecode = True
EXPECTED_BACKEND = "79050e25cb749d03b65592e81f1dd89bffa44472"
FIXTURE_PASSWORD = "Abcdef0123456789"  # Public synthetic fixture only; never a real frame credential.
PROOF_PATH = "/api/auth/legacy-tls-proof"


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(value, output, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Invalid synthetic request")
        result[key] = value
    return result


class Audit:
    def __init__(self, app, output: Path, metadata: dict):
        self.app, self.output, self.metadata = app, output, metadata
        self.lock = threading.Lock()
        self.counts = Counter()
        self.nonce_hashes = set()
        self.http_requests = 0
        self.safety_failures = 0
        self.http_responses_no_store_no_cookie = 0

    def flush(self, **metadata):
        with self.lock:
            self.metadata.update(metadata)
            write_json(self.output, {**self.metadata, "http_proof_audit": {
                "requests_checked": self.http_requests,
                "unique_nonces": len(self.nonce_hashes),
                "nonce_only_no_cookie_or_credential": self.safety_failures == 0,
                "no_store_no_set_cookie_responses": self.http_responses_no_store_no_cookie,
                "safety_failures": self.safety_failures,
                "request_bodies_persisted": False,
            }, "requests": [
                {"method": method, "path": path, "status": status, "scheme": scheme, "count": count}
                for (method, path, status, scheme), count in sorted(self.counts.items())
            ]})

    def failure(self):
        with self.lock:
            self.safety_failures += 1
        self.flush()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        is_http = scope["scheme"] == "http"
        body = b""
        if is_http:
            try:
                # The proof is public but must never inherit any live session authority.
                assert scope["method"] == "POST" and scope["path"] == PROOF_PATH
                assert not scope.get("query_string")
                headers = {key.lower(): value for key, value in scope.get("headers", [])}
                assert not any(key in headers for key in (
                    b"cookie", b"authorization", b"proxy-authorization", b"x-inky-owner-id", b"x-inky-owner-token", b"x-device-token"))
                while True:
                    message = await receive()
                    assert message["type"] == "http.request"
                    body += message.get("body", b"")
                    assert len(body) <= 2048
                    if not message.get("more_body", False):
                        break
                payload = json.loads(body, object_pairs_hook=unique_object)
                assert type(payload) is dict and set(payload) == {"v", "nonce"}
                assert type(payload["v"]) is int and payload["v"] == 1
                assert type(payload["nonce"]) is str and re.fullmatch(r"[0-9a-f]{64}", payload["nonce"])
                assert FIXTURE_PASSWORD.encode("ascii") not in body
                digest = hashlib.sha256(bytes.fromhex(payload["nonce"])).digest()
                with self.lock:
                    self.http_requests += 1
                    self.nonce_hashes.add(digest)
            except (AssertionError, ValueError, TypeError, UnicodeError):
                self.failure()
                await send({"type": "http.response.start", "status": 400,
                            "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]})
                await send({"type": "http.response.body", "body": b'{"detail":"Synthetic transport safety assertion failed"}'})
                return
        delivered = False

        async def replayed_receive():
            nonlocal delivered
            if is_http and not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        async def recorded_send(message):
            if message["type"] == "http.response.start":
                if is_http:
                    headers = {key.lower(): value for key, value in message.get("headers", [])}
                    valid = b"set-cookie" not in headers and b"no-store" in headers.get(b"cache-control", b"")
                    if valid:
                        with self.lock:
                            self.http_responses_no_store_no_cookie += 1
                    else:
                        self.failure()
                # UUID path components are public. Unrecognized paths are never echoed into receipts.
                path = scope["path"]
                if not path.startswith("/api/") or "?" in path:
                    path = "<unexpected>"
                with self.lock:
                    self.counts[(scope["method"], path, message["status"], scope["scheme"])] += 1
                self.flush()
            await send(message)
        await self.app(scope, replayed_receive, recorded_send)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--maximum-seconds", type=int, default=1800)
    args = parser.parse_args()
    os.umask(0o077)
    backend = args.backend.resolve(strict=True)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (output / "fixture-public.json").exists() or (output / "backend-receipt.json").exists():
        parser.error("Choose a fresh output directory; existing fixture receipts are preserved.")
    commit = subprocess.run(["git", "-C", str(backend), "rev-parse", "HEAD"], check=True,
                            capture_output=True, text=True).stdout.strip()
    if commit != EXPECTED_BACKEND:
        parser.error("The backend checkout is not the pinned legacy-proof candidate.")
    if not 30 <= args.maximum_seconds <= 7200:
        parser.error("--maximum-seconds must be between30 and7200.")
    assert len(FIXTURE_PASSWORD) == 16 and re.fullmatch(r"[A-Za-z0-9]{16}", FIXTURE_PASSWORD)

    with tempfile.TemporaryDirectory(prefix="private-fixture-", dir=output) as temporary:
        workspace = Path(temporary)
        data = workspace / "data"
        data.mkdir(mode=0o700)
        os.environ["INKY_STUDIO_DATA_DIR"] = str(data)
        os.environ["INKY_STUDIO_DISPLAY_MODE"] = "mock"
        os.environ["INKY_STUDIO_BLUETOOTH"] = "0"
        os.environ.pop("INKY_STUDIO_DISABLE_AUTH", None)
        os.environ.pop("INKY_STUDIO_DISPLAY_PROFILE", None)
        sys.path.insert(0, str(backend / "server"))
        import uvicorn
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        from inky_web import auth, main as backend_main
        from inky_web.db import init_db
        from inky_web.models import SettingsUpdate
        from inky_web.provisioning.identity import load_or_create_identity
        from inky_web.services import settings

        logging.disable(logging.CRITICAL)
        credentials = auth._new_credentials(data, FIXTURE_PASSWORD, bootstrap=True)
        auth._write_credentials(credentials)
        assert credentials.bootstrap_password == FIXTURE_PASSWORD
        init_db()
        settings.update(SettingsUpdate(change_mode="manual"))
        identity = load_or_create_identity(workspace / "identity")
        certificate, key = workspace / "certificate.pem", workspace / "private-key.pem"
        certificate.write_bytes(identity.cert_pem)
        key.write_bytes(identity.key_pem)
        backend_main.app.state.frame_identity = identity
        listeners = []
        for _ in range(2):
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            listeners.append(listener)
        http_listener, https_listener = listeners
        http_endpoint = f"http://127.0.0.1:{http_listener.getsockname()[1]}"
        endpoint = f"https://127.0.0.1:{https_listener.getsockname()[1]}"
        os.environ["INKY_STUDIO_PHOTO_ACCESS_URL"] = endpoint
        descriptor = {"http_endpoint": http_endpoint, "endpoint": endpoint,
                      "frame_id": identity.frame_id, "spki_sha256": identity.spki_sha256,
                      "backend_commit": commit, "process_id": os.getpid(), "created_at_utc": utc()}
        audit = Audit(backend_main.app, output / "backend-receipt.json", {
            **descriptor, "transport": "real uvicorn HTTP nonce-only + pinned HTTPS loopback",
            "shared_app_and_lifespan": True, "synthetic_bootstrap_record": True,
            "display_mode": "mock", "bluetooth": False, "hardware_access": False,
            "request_bodies_recorded": False, "status": "starting",
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        })
        servers = []

        class ManagedServer(uvicorn.Server):
            # One shared signal handler and lifespan are owned below, not once per listener.
            def install_signal_handlers(self):
                pass

            def capture_signals(self):
                from contextlib import nullcontext
                return nullcontext()

        common = dict(app=audit, host="127.0.0.1", port=0, access_log=False,
                      log_config=None, proxy_headers=False, lifespan="off")
        servers.append(ManagedServer(uvicorn.Config(**common)))
        servers.append(ManagedServer(uvicorn.Config(ssl_keyfile=str(key), ssl_certfile=str(certificate), **common)))

        def ready():
            try:
                deadline = time.monotonic() + 30
                while not all(server.started for server in servers):
                    if any(server.should_exit for server in servers) or time.monotonic() >= deadline:
                        raise TimeoutError()
                    time.sleep(0.05)
                context = ssl.create_default_context(cadata=identity.cert_pem.decode("ascii"))
                with socket.create_connection(("127.0.0.1", https_listener.getsockname()[1]), timeout=5) as raw:
                    with context.wrap_socket(raw, server_hostname=identity.server_name) as secured:
                        peer = x509.load_der_x509_certificate(secured.getpeercert(binary_form=True))
                        spki = peer.public_key().public_bytes(serialization.Encoding.DER,
                                                             serialization.PublicFormat.SubjectPublicKeyInfo)
                        if hashlib.sha256(spki).hexdigest() != identity.spki_sha256:
                            raise ValueError("Synthetic SPKI mismatch")
                        tls_version = secured.version()
                        connection = http.client.HTTPConnection("127.0.0.1", timeout=5)
                        connection.sock = secured
                        connection.request("GET", "/api/health", headers={"Host": endpoint.removeprefix("https://")})
                        response = connection.getresponse()
                        health = json.loads(response.read())
                        if response.status != 200 or health.get("status") != "ok":
                            raise ValueError("Synthetic health failed")
                audit.flush(status="ready", smoke={"health_status": 200, "tls_version": tls_version,
                    "ca_and_san_verified": True, "spki_verified": True, "checked_at_utc": utc()})
                write_json(output / "fixture-public.json", descriptor)
                write_json(output / "fixture-environment.json", {
                    "INKY_PHOTO_INTEROP_HTTP_ENDPOINT": http_endpoint,
                    "INKY_PHOTO_INTEROP_ENDPOINT": endpoint,
                    "INKY_PHOTO_INTEROP_FRAME_ID": identity.frame_id,
                    "INKY_PHOTO_INTEROP_SPKI_SHA256": identity.spki_sha256,
                })
                print(json.dumps({"status": "ready", "descriptor": str(output / "fixture-public.json"),
                                  "environment": str(output / "fixture-environment.json"), "pid": os.getpid()}), flush=True)
            except Exception as exc:
                audit.flush(status="failed", error_type=type(exc).__name__)
                for server in servers:
                    server.should_exit = True

        async def serve():
            loop = asyncio.get_running_loop()
            def shutdown():
                for server in servers:
                    server.should_exit = True
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, shutdown)
            timer = loop.call_later(args.maximum_seconds, shutdown)
            try:
                # Exactly one lifespan creates auth_service/session store shared by both transports.
                async with backend_main.lifespan(backend_main.app):
                    threading.Thread(target=ready, name="fixture-readiness", daemon=True).start()
                    tasks = [asyncio.create_task(server.serve(sockets=[listener])) for server, listener in zip(servers, listeners)]
                    try:
                        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    finally:
                        shutdown()
                        await asyncio.gather(*tasks)
            finally:
                timer.cancel()
                for sig in (signal.SIGTERM, signal.SIGINT):
                    loop.remove_signal_handler(sig)
        try:
            asyncio.run(serve())
        finally:
            audit.flush(status="stopped", stopped_at_utc=utc())
            for listener in listeners:
                listener.close()
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), file=sys.stderr)
        raise SystemExit(1) from None
