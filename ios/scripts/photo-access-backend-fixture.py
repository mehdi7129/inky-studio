#!/usr/bin/env python3
"""Serve the real PHOTO backend over private, pinned loopback HTTPS for XCTest.

No backend source changes, system trust installation, Bluetooth, SPI or Pi access.
Only public endpoint/UUID/SPKI descriptors and method/path/status receipts are logged.
Use the existing backend validation venv; stop with SIGINT after the targeted test.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import http.client
import json
import logging
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time

sys.dont_write_bytecode = True
EXPECTED_BACKEND = "9ec89d72696339cd305255ae5619606fb94aa0c6"
FIXTURE_PASSWORD = "photo-access-interop-password-v1"  # Synthetic, never a real frame credential.


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


class Audit:
    def __init__(self, app, output: Path, metadata: dict):
        self.app, self.output, self.metadata = app, output, metadata
        self.lock = threading.Lock()
        self.counts = Counter()

    def flush(self, **metadata):
        with self.lock:
            self.metadata.update(metadata)
            write_json(self.output, {**self.metadata, "requests": [
                {"method": method, "path": path, "status": status, "scheme": scheme, "count": count}
                for (method, path, status, scheme), count in sorted(self.counts.items())
            ]})

    async def __call__(self, scope, receive, send):
        async def recorded_send(message):
            if scope["type"] == "http" and message["type"] == "http.response.start":
                key = (scope["method"], scope["path"], message["status"], scope["scheme"])
                with self.lock:
                    self.counts[key] += 1
                self.flush()
            await send(message)
        await self.app(scope, receive, recorded_send)


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
    if (output / "fixture-public.json").exists():
        parser.error("Choose a fresh output directory; existing fixture receipts are preserved.")
    commit = subprocess.run(["git", "-C", str(backend), "rev-parse", "HEAD"], check=True,
                            capture_output=True, text=True).stdout.strip()
    if commit != EXPECTED_BACKEND:
        parser.error("The backend checkout is not the pinned PHOTO candidate.")
    if not 30 <= args.maximum_seconds <= 7200:
        parser.error("--maximum-seconds must be between30 and7200.")

    with tempfile.TemporaryDirectory(prefix="private-fixture-", dir=output) as temporary:
        workspace = Path(temporary)
        data = workspace / "data"
        data.mkdir(mode=0o700)
        # Override every hardware/auth selector before importing backend modules.
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
        auth._write_credentials(auth._new_credentials(data, FIXTURE_PASSWORD, bootstrap=False))
        init_db()
        settings.update(SettingsUpdate(change_mode="manual"))
        identity = load_or_create_identity(workspace / "identity")
        certificate = workspace / "certificate.pem"
        key = workspace / "private-key.pem"
        certificate.write_bytes(identity.cert_pem)
        key.write_bytes(identity.key_pem)
        backend_main.app.state.frame_identity = identity
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        endpoint = f"https://127.0.0.1:{listener.getsockname()[1]}"
        os.environ["INKY_STUDIO_PHOTO_ACCESS_URL"] = endpoint
        descriptor = {"endpoint": endpoint, "frame_id": identity.frame_id,
                      "spki_sha256": identity.spki_sha256, "backend_commit": commit,
                      "process_id": os.getpid(), "created_at_utc": utc()}
        audit = Audit(backend_main.app, output / "backend-receipt.json", {
            **descriptor, "transport": "real uvicorn HTTPS loopback only", "display_mode": "mock",
            "bluetooth": False, "hardware_access": False, "request_bodies_recorded": False,
            "status": "starting", "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        })
        server = uvicorn.Server(uvicorn.Config(audit, host="127.0.0.1", port=0,
            ssl_keyfile=str(key), ssl_certfile=str(certificate),
            access_log=False, log_config=None, proxy_headers=False, lifespan="on"))

        def ready():
            try:
                deadline = time.monotonic() + 30
                while not server.started:
                    if server.should_exit or time.monotonic() >= deadline:
                        raise TimeoutError()
                    time.sleep(0.05)
                # Verify CA, certificate SAN and independent SPKI; never use CERT_NONE.
                context = ssl.create_default_context(cadata=identity.cert_pem.decode("ascii"))
                with socket.create_connection(("127.0.0.1", listener.getsockname()[1]), timeout=5) as raw:
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
                    "INKY_PHOTO_INTEROP_ENDPOINT": endpoint,
                    "INKY_PHOTO_INTEROP_FRAME_ID": identity.frame_id,
                    "INKY_PHOTO_INTEROP_SPKI_SHA256": identity.spki_sha256,
                })
                print(json.dumps({"status": "ready", "descriptor": str(output / "fixture-public.json"),
                                  "environment": str(output / "fixture-environment.json"), "pid": os.getpid()}), flush=True)
            except Exception as exc:
                audit.flush(status="failed", error_type=type(exc).__name__)
                server.should_exit = True

        threading.Thread(target=ready, name="fixture-readiness", daemon=True).start()
        def expiry():
            time.sleep(args.maximum_seconds)
            server.should_exit = True
        threading.Thread(target=expiry, name="fixture-deadline", daemon=True).start()
        try:
            server.run(sockets=[listener])
        finally:
            audit.flush(status="stopped", stopped_at_utc=utc())
            listener.close()
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), file=sys.stderr)
        raise SystemExit(1) from None
