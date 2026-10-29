#!/usr/bin/env python3
"""Real Foundation HTTPS/WSS against ephemeral loopback-only TLS fixtures.

Uses only Python stdlib and the OpenSSL CLI. No app install, Keychain write,
trusted-root installation, Bluetooth, Pi connection, or persistent private key.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import shutil
import ssl
import subprocess
import tempfile
import threading


ROOT = Path(__file__).resolve().parents[2]
FRAME_ID = "9bf6c09e-0752-43b6-933b-6ce2815407ec"
SERVER_NAME = f"frame-{FRAME_ID}.inky.invalid"
OWNER_ID = "11111111-2222-4333-8444-555555555555"
OWNER_TOKEN = "42" * 32  # Synthetic; never a user credential.
TRANSACTION_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
PASSWORD = "synthetic-wire-password"
COOKIE = "wire_session=synthetic"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWWQAAAAASUVORK5CYII="
)
SWIFT_SOURCES = [
    "ios/InkyStudio/Provisioning/FrameIdentity.swift",
    "ios/InkyStudio/Provisioning/PinnedFrameTrust.swift",
    "ios/InkyStudio/Provisioning/OwnershipVault.swift",
    "ios/InkyStudio/Core/Models.swift",
    "ios/InkyStudio/Core/APIError.swift",
    "ios/InkyStudio/Core/FramePhotoClient.swift",
    "ios/InkyStudio/Core/InkyAPI.swift",
    "scripts/https-wire-bench/InkyHTTPSWire.swift",
]


def command(args: list[str]) -> str:
    completed = subprocess.run(args, check=True, text=True, capture_output=True)
    return completed.stdout.strip()


class FixtureServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, label: str, context: ssl.SSLContext | None = None):
        self.label = label
        self.context = context
        self.redirect: str | None = None
        self.counts: Counter[str] = Counter()
        self.invalid_owner = 0
        self.invalid_payload = 0
        self.tcp_connections = 0
        self.completed_tls_handshakes = 0
        self.versions: set[str] = set()
        self.lock = threading.Lock()
        super().__init__(("127.0.0.1", 0), FixtureHandler)

    @property
    def url(self) -> str:
        return f"{'https' if self.context else 'http'}://127.0.0.1:{self.server_port}"

    def get_request(self):
        connection, address = super().get_request()
        with self.lock:
            self.tcp_connections += 1
        connection.settimeout(5)
        if self.context:
            try:
                connection = self.context.wrap_socket(connection, server_side=True)
                with self.lock:
                    self.completed_tls_handshakes += 1
            except Exception:
                connection.close()
                raise
        return connection, address

    def handle_error(self, request, client_address):
        # A rejected TLS/WSS connection may close before a fixture response.
        # Request counts and Swift expectations are the authoritative result.
        pass

    def report(self) -> dict:
        with self.lock:
            return {
                "requests": dict(self.counts),
                "invalid_owner": self.invalid_owner,
                "invalid_payload": self.invalid_payload,
                "tls_versions": sorted(self.versions),
                "tcp_connections": self.tcp_connections,
                "completed_tls_handshakes": self.completed_tls_handshakes,
            }


class FixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: FixtureServer

    def log_message(self, *args):
        pass  # No body, header, password, token, or cookie logging.

    def send_bytes(self, code: int, data: bytes, content_type="application/json", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def reply(self, value, code=200, headers=None):
        self.send_bytes(code, json.dumps(value).encode(), headers=headers)

    def record(self) -> bool:
        valid = (self.headers.get("X-Inky-Owner-ID") == OWNER_ID
                 and self.headers.get("X-Inky-Owner-Token") == OWNER_TOKEN)
        with self.server.lock:
            self.server.counts[f"{self.command} {self.path}"] += 1
            self.server.invalid_owner += int(not valid)
            if isinstance(self.connection, ssl.SSLSocket):
                self.server.versions.add(self.connection.version())
        if not valid:
            self.reply({"error": "synthetic owner rejected"}, 401)
        return valid

    def reject_payload(self):
        with self.server.lock:
            self.server.invalid_payload += 1
        self.reply({"error": "synthetic payload rejected"}, 400)

    def do_POST(self):
        if not self.record():
            return
        try:
            count = int(self.headers.get("Content-Length", "0"))
            if not 0 < count < 8192:
                raise ValueError()
            body = json.loads(self.rfile.read(count))
        except (ValueError, json.JSONDecodeError):
            self.reject_payload()
            return
        if self.server.redirect:
            self.send_bytes(307, b"", headers={"Location": self.server.redirect + self.path})
        elif self.path == "/api/auth/login" and body == {"password": PASSWORD}:
            self.reply({"authenticated": True, "auth_required": True},
                       headers={"Set-Cookie": COOKIE + "; Path=/; Secure; HttpOnly; SameSite=Strict"})
        elif self.path == "/api/provisioning/wifi/confirm" and body == {"transaction_id": TRANSACTION_ID}:
            self.reply({"ok": True, "result": {"state": "committed"}})
        else:
            self.reject_payload()

    def do_GET(self):
        if not self.record():
            return
        authenticated = self.headers.get("Cookie") == COOKIE
        if self.path == "/api/auth/status":
            self.reply({"authenticated": authenticated, "auth_required": True})
        elif not authenticated:
            self.reply({"error": "synthetic session rejected"}, 401)
        elif self.path == "/api/photos/fixture":
            self.send_bytes(200, PNG, "image/png")
        elif self.path == "/api/ws" and self.headers.get("Upgrade", "").lower() == "websocket":
            key = self.headers.get("Sec-WebSocket-Key", "")
            accept = base64.b64encode(hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            message = b'{"type":"hello","payload":{}}'
            self.wfile.write(bytes([0x81, len(message)]) + message)
            self.wfile.flush()
            # Keep the connection alive until URLSession closes the test stream.
            self.close_connection = True
            try:
                self.connection.recv(1024)
            except (OSError, TimeoutError):
                pass
        else:
            self.reply({"error": "synthetic route missing"}, 404)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write non-secret JSON evidence")
    options = parser.parse_args()
    if platform.system() != "Darwin":
        raise SystemExit("This qualification requires macOS Foundation/Security and Xcode Swift.")
    openssl = os.environ.get("INKY_HTTPS_OPENSSL") or (
        "/opt/homebrew/opt/openssl@3/bin/openssl"
        if Path("/opt/homebrew/opt/openssl@3/bin/openssl").exists() else shutil.which("openssl")
    )
    if not openssl:
        raise SystemExit("OpenSSL 3 with req -not_before/-not_after is required.")
    os.umask(0o077)
    servers: dict[str, FixtureServer] = {}
    threads = []
    with tempfile.TemporaryDirectory(prefix="inky-https-wire-") as temporary:
        workspace = Path(temporary)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        key = workspace / "identity-key.pem"
        other_key = workspace / "other-key.pem"
        for target in [key, other_key]:
            command([openssl, "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", str(target)])

        def certificate(label, signing_key=key, name=SERVER_NAME, start=-1, end=395):
            pem = workspace / (label + ".pem")
            der = workspace / (label + ".der")
            command([openssl, "req", "-new", "-x509", "-sha256", "-key", str(signing_key),
                     "-subj", "/CN=" + name, "-not_before", (now + timedelta(days=start)).strftime("%Y%m%d%H%M%SZ"),
                     "-not_after", (now + timedelta(days=end)).strftime("%Y%m%d%H%M%SZ"),
                     "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
                     "-addext", "keyUsage=critical,digitalSignature,keyCertSign,cRLSign",
                     "-addext", "extendedKeyUsage=serverAuth", "-addext", "subjectAltName=DNS:" + name,
                     "-out", str(pem)])
            command([openssl, "x509", "-in", str(pem), "-outform", "DER", "-out", str(der)])
            return pem, der, signing_key

        fixtures = {
            "original": certificate("original", start=-30, end=366),
            "renewed": certificate("renewed"),
            "changed_key": certificate("changed-key", signing_key=other_key),
            "wrong_name": certificate("wrong-name", name="another-frame.inky.invalid"),
            "expired": certificate("expired", start=-397, end=-1),
            "future": certificate("future", start=1, end=397),
        }
        corrupt = bytearray(fixtures["original"][1].read_bytes())
        corrupt[-1] ^= 1  # Keep the public key and DER valid; break self-signature.
        bad_der = workspace / "bad-signature.der"
        bad_der.write_bytes(corrupt)
        bad_pem = workspace / "bad-signature.pem"
        command([openssl, "x509", "-inform", "DER", "-in", str(bad_der), "-out", str(bad_pem)])
        fixtures["bad_signature"] = bad_pem, bad_der, key
        for label in ["original", "renewed", "expired_cache", "wrong_pin", "changed_key", "wrong_name", "expired", "future", "bad_signature", "redirect_http", "redirect_https", "redirect_destination", "http"]:
            context = None
            if label != "http":
                fixture_name = {"expired_cache": "renewed", "wrong_pin": "original", "redirect_http": "original",
                                "redirect_https": "original", "redirect_destination": "original"}.get(label, label)
                pem, _, signing_key = fixtures[fixture_name]
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.minimum_version = ssl.TLSVersion.TLSv1_3
                context.maximum_version = ssl.TLSVersion.TLSv1_3
                context.set_alpn_protocols(["http/1.1"])
                context.load_cert_chain(pem, signing_key)
            servers[label] = FixtureServer(label, context)
        servers["redirect_http"].redirect = servers["http"].url
        servers["redirect_https"].redirect = servers["redirect_destination"].url

        manifest = workspace / "manifest.json"
        manifest.write_text(json.dumps({
            "frameID": FRAME_ID,
            "originalDER": str(fixtures["original"][1]),
            "expiredDER": str(fixtures["expired"][1]),
            "endpoints": {name: server.url for name, server in servers.items()},
        }))
        swift_output = workspace / "swift-results.json"
        executable = workspace / "InkyHTTPSWire"
        print("Compiling production InkyAPI + FrameTrustPolicy with strict concurrency…", flush=True)
        command(["xcrun", "swiftc", "-parse-as-library", "-swift-version", "5", "-strict-concurrency=complete", "-warnings-as-errors",
                 *[str(ROOT / source) for source in SWIFT_SOURCES], "-o", str(executable)])
        try:
            for server in servers.values():
                thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
                thread.start()
                threads.append(thread)
            execution = subprocess.run([str(executable), str(manifest), str(swift_output)],
                                       text=True, capture_output=True, timeout=90)
            if execution.stdout:
                print(execution.stdout.strip())
            if not swift_output.exists():
                raise RuntimeError(f"Swift harness produced no results (exit {execution.returncode}).")
            swift_results = json.loads(swift_output.read_text())
            reports = {name: server.report() for name, server in servers.items()}
        finally:
            for server in servers.values():
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=1)

        checks = []
        def check(name, passed):
            checks.append({"name": name, "passed": bool(passed)})

        for name in ["original", "renewed", "expired_cache"]:
            report = reports[name]
            check(name + ".server_routes_and_credentials", report["requests"] == {
                "GET /api/auth/status": 2, "POST /api/auth/login": 1,
                "GET /api/photos/fixture": 1, "GET /api/ws": 1,
                "POST /api/provisioning/wifi/confirm": 1,
            } and report["invalid_owner"] == 0 and report["invalid_payload"] == 0)
            check(name + ".tls13", report["tls_versions"] == ["TLSv1.3"])
        for name in ["wrong_pin", "changed_key", "wrong_name", "expired", "future", "bad_signature"]:
            check(name + ".connected_but_zero_http_payload", not reports[name]["requests"]
                  and reports[name]["tcp_connections"] >= 4)
        for name in ["http", "redirect_destination"]:
            check(name + ".zero_connection_or_payload", not reports[name]["requests"]
                  and reports[name]["tcp_connections"] == 0)
        for name in ["redirect_http", "redirect_https"]:
            check(name + ".redirect_not_replayed", reports[name]["requests"] == {"POST /api/auth/login": 1})
        check("renewal.distinct_der", fixtures["original"][1].read_bytes() != fixtures["renewed"][1].read_bytes())
        all_results = swift_results + checks
        evidence = {
            "passed": execution.returncode == 0 and all(row["passed"] for row in all_results),
            "timestamp_utc": now.isoformat(),
            "platform": platform.platform(),
            "scope": "Real macOS URLSession; unmodified production InkyAPI, OriginRedirectDelegate, FrameTrustPolicy. Loopback only. No iOS runtime or Pi hardware qualification.",
            "swift": command(["xcrun", "swiftc", "--version"]),
            "openssl_cli": command([openssl, "version"]),
            "python_ssl": ssl.OPENSSL_VERSION,
            "source_sha256": {source: hashlib.sha256((ROOT / source).read_bytes()).hexdigest() for source in SWIFT_SOURCES},
            "certificate_sha256": {name: hashlib.sha256(der.read_bytes()).hexdigest() for name, (_, der, _) in fixtures.items()},
            "cases": all_results,
            "servers": reports,
        }
        if options.output:
            options.output.parent.mkdir(parents=True, exist_ok=True)
            options.output.write_text(json.dumps(evidence, indent=2) + "\n")
        for row in all_results:
            print(("PASS " if row["passed"] else "FAIL ") + row["name"])
        print(f"{sum(row['passed'] for row in all_results)}/{len(all_results)} HTTPS wire checks passed.")
        return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        # Compiler/OpenSSL diagnostics contain synthetic paths only, no credentials.
        print(error.stderr)
        raise SystemExit(error.returncode)
