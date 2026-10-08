#!/usr/bin/env python3
"""Loopback-only Inky Studio v0.4.2 fixture, using Python's standard library.

Run: python3 ios/scripts/mock-server.py --port 8765
Test password: test-password. Never connects to or changes a physical frame.
Fault controls: POST /__test/availability {"available": false/true},
POST /__test/settings-delay {"seconds": 0..5}; /__test/reset clears both.
"""
from __future__ import annotations

import argparse
import base64
import copy
from email import policy
from email.parser import BytesParser
import hashlib
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import socket
import struct
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlsplit
import zlib

PASSWORD = "test-password"
WIDTH, HEIGHT = 800, 480
MAX_UPLOAD = 10 * 1024 * 1024


def png_bytes(seed: int) -> bytes:
    """Generate a landscape illustration without external assets or packages."""
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack("!I", len(payload)) + kind + payload + struct.pack("!I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    rows = bytearray()
    for y in range(HEIGHT):
        rows.append(0)
        for x in range(WIDTH):
            if y < HEIGHT * 0.48:
                rgb = (160 + seed * 8, 196 + y // 16, 215 + seed * 4)
            elif y < HEIGHT * 0.62 + 35 * ((x // 110) % 3):
                rgb = (87 + seed * 14, 112 + seed * 8, 98 + seed * 9)
            else:
                rgb = (44 + seed * 14, 111 + y // 12, 150 + seed * 13)
            rows.extend(min(255, v) for v in rgb)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b"")


FIXTURE_FILES = [png_bytes(i) for i in range(3)]


class Fixture:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.sockets: dict[socket.socket, tuple[str, threading.Lock]] = {}
        self.reset()

    def reset(self) -> None:
        with self.lock:
            self.close_sockets()
            if hasattr(self, "delay_cancelled"):
                self.delay_cancelled.set()
            self.delay_cancelled = threading.Event()
            self.available = True
            self.settings_delay = 0.0
            self.sessions: set[str] = set()
            self.password = PASSWORD
            self.login_attempts: list[float] = []
            self.settings = {"change_mode": "daily", "change_hour": 8, "change_interval_minutes": 60, "saturation": 1.0}
            self.photos: dict[str, dict] = {}
            self.files: dict[str, bytes] = {}
            now = time.time()
            for i, (photo_id, filename) in enumerate([
                ("c0a570000001", "Un matin à Cassis.png"),
                ("a11050000002", "Lac d'Allos.png"),
                ("5ad000000003", "Ombres d'été.png"),
            ]):
                data = FIXTURE_FILES[i]
                self.files[photo_id] = data
                self.photos[photo_id] = {"id": photo_id, "sha256": hashlib.sha256(data).hexdigest(), "original_filename": filename, "mime": "image/png", "width": WIDTH, "height": HEIGHT, "size_bytes": len(data), "created_at": now - 86400 * (3 - i)}
            self.queue = [
                {"id": 1, "position": 0, "added_at": now - 60, "photo": self.photos["a11050000002"]},
                {"id": 2, "position": 1, "added_at": now - 30, "photo": self.photos["5ad000000003"]},
            ]
            self.history = [
                {"id": 2, "displayed_at": now - 120, "source": "auto", "photo": self.photos["c0a570000001"]},
                {"id": 1, "displayed_at": now - 86400, "source": "auto", "photo": self.photos["5ad000000003"]},
            ]
            self.next_queue_id = 3
            self.next_history_id = 3
            self.navigation_history_id = 2
            self.display = {"model": 'Mock Inky Impression 7.3" (Spectra 6)', "width": WIDTH, "height": HEIGHT, "colors": 6, "is_mock": True}

    def close_sockets(self) -> None:
        """Drop transports without invalidating authenticated fixture sessions."""
        with self.lock:
            for connection in self.sockets:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            self.sockets.clear()

    def state(self) -> dict:
        with self.lock:
            next_change = None
            if self.settings["change_mode"] != "manual":
                next_change = time.time() + (self.settings["change_interval_minutes"] * 60 if self.settings["change_mode"] == "interval" else 86400)
            return {"display": copy.deepcopy(self.display), "current": copy.deepcopy(self.history[0]) if self.history else None, "queue_count": len(self.queue), "next_change_at": next_change}

    def emit(self, event: str, payload: dict) -> None:
        frame = json.dumps({"type": event, "payload": payload}).encode()
        with self.lock:
            clients = list(self.sockets.items())
        for connection, (token, write_lock) in clients:
            try:
                with write_lock:
                    send_frame(connection, frame if token in self.sessions else struct.pack("!H", 1008), 1 if token in self.sessions else 8)
            except OSError:
                with self.lock:
                    self.sockets.pop(connection, None)


FIXTURE = Fixture()


def send_frame(connection: socket.socket, data: bytes, opcode: int = 1) -> None:
    length = len(data)
    size = bytes([length]) if length < 126 else b"\x7e" + struct.pack("!H", length) if length <= 65535 else b"\x7f" + struct.pack("!Q", length)
    connection.sendall(bytes([0x80 | opcode]) + size + data)


def exact(connection: socket.socket, count: int) -> bytes:
    result = bytearray()
    while len(result) < count:
        data = connection.recv(count - len(result))
        if not data:
            raise ConnectionError("Socket closed")
        result.extend(data)
    return bytes(result)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "InkyFixture/0.4.2"

    def log_message(self, fmt: str, *args: object) -> None:
        # Never log request bodies, cookies or passwords.
        print(f"{self.address_string()} {fmt % args}", flush=True)

    @property
    def token(self) -> str:
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            return cookies["inky_session"].value if "inky_session" in cookies else ""
        except Exception:
            return ""

    def reply(self, code: int, value: object = None, *, data: bytes | None = None, content_type: str = "application/json", cookie: str | None = None) -> None:
        payload = data if data is not None else json.dumps(value, ensure_ascii=False).encode() if value is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def failure(self, code: int, message: str) -> None:
        self.reply(code, {"detail": message})

    def read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > MAX_UPLOAD + 65536:
            raise OverflowError()
        return self.rfile.read(length)

    def do_GET(self) -> None:
        self.route()

    def do_POST(self) -> None:
        self.route()

    def do_DELETE(self) -> None:
        self.route()

    def route(self) -> None:
        try:
            self.dispatch()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except OverflowError:
            self.close_connection = True
            self.failure(413, "Photo exceeds the 10 MiB upload limit")
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            self.failure(400, f"Invalid fixture request: {error}")

    def dispatch(self) -> None:
        parsed = urlsplit(self.path)
        path, method = parsed.path, self.command
        raw = self.read_body() if method == "POST" else b""
        body = json.loads(raw) if raw and "application/json" in self.headers.get("Content-Type", "") else {}
        if path == "/__test/biometrics" and method in {"GET", "POST"}:
            device = getattr(self.server, "biometric_device", None)
            if method == "GET":
                self.reply(200, {"enabled": device is not None})
                return
            if device is None:
                self.failure(409, "Start the fixture with --biometric-device <simulator-UDID>")
                return
            event = body.get("event")
            if event not in {"success", "failure"}:
                self.failure(400, "Expected success or failure")
                return
            # The target is verified as a simulator at startup. No shell, arbitrary
            # device IDs, production frame data, or physical phone can be supplied.
            try:
                subprocess.run(["xcrun", "devicectl", "device", "simulate", "biometrics", "--device", device, "--" + event, "--timeout", "10"], check=True, capture_output=True, timeout=12)
            except (subprocess.SubprocessError, OSError) as error:
                self.failure(503, f"Simulator biometric event failed: {type(error).__name__}")
            else:
                self.reply(200, {"simulated": event})
            return
        if path == "/__test/reset" and method == "POST":
            FIXTURE.reset()
            self.reply(200, {"reset": True})
            return
        if path == "/__test/availability" and method == "POST":
            available = body.get("available")
            if not isinstance(available, bool):
                self.failure(400, "Expected an available boolean")
                return
            with FIXTURE.lock:
                FIXTURE.available = available
                if not available:
                    FIXTURE.close_sockets()
            self.reply(200, {"available": available})
            return
        if path == "/__test/settings-delay" and method == "POST":
            seconds = body.get("seconds")
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 0 <= seconds <= 5:
                self.failure(400, "Expected seconds between 0 and 5")
                return
            with FIXTURE.lock:
                FIXTURE.settings_delay = float(seconds)
            self.reply(200, {"seconds": seconds})
            return
        with FIXTURE.lock:
            if path.startswith("/api/") and not FIXTURE.available:
                self.failure(503, "Fixture API temporarily unavailable")
                return
        if path == "/api/health" and method == "GET":
            self.reply(200, {"status": "ok", "version": "0.4.2"})
            return
        authenticated = self.token in FIXTURE.sessions
        if path == "/api/auth/status" and method == "GET":
            self.reply(200, {"authenticated": authenticated, "auth_required": True, "password_change_supported": True})
            return
        if path == "/api/auth/login" and method == "POST":
            with FIXTURE.lock:
                now = time.monotonic()
                FIXTURE.login_attempts = [attempt for attempt in FIXTURE.login_attempts if now - attempt < 60]
                if len(FIXTURE.login_attempts) >= 5:
                    self.failure(429, "Trop de tentatives — réessaye dans une minute")
                    return
                FIXTURE.login_attempts.append(now)
            if body.get("password") != FIXTURE.password:
                self.failure(401, "Mot de passe incorrect")
                return
            token = secrets.token_urlsafe(32)
            with FIXTURE.lock:
                FIXTURE.sessions.add(token)
            self.reply(200, {"authenticated": True, "auth_required": True}, cookie=f"inky_session={token}; HttpOnly; Max-Age=2592000; Path=/; SameSite=Strict")
            return
        if not authenticated:
            self.failure(401, "Authentification requise")
            return
        if path == "/api/auth/password" and method == "POST":
            with FIXTURE.lock:
                if body.get("current_password") != FIXTURE.password:
                    self.failure(403, "Mot de passe actuel incorrect")
                    return
                new = body.get("new_password")
                if not isinstance(new, str) or not 8 <= len(new) <= 64:
                    self.failure(422, "Le mot de passe doit contenir entre 8 et 64 caractères.")
                    return
                FIXTURE.password = new
                FIXTURE.sessions.clear()
                token = secrets.token_urlsafe(32)
                FIXTURE.sessions.add(token)
            self.reply(200, {"authenticated": True, "auth_required": True, "password_change_supported": True}, cookie=f"inky_session={token}; HttpOnly; Max-Age=2592000; Path=/; SameSite=Strict")
            FIXTURE.emit("auth_changed", {})
            return
        if path == "/api/ws" and method == "GET":
            self.websocket()
            return
        if path == "/api/auth/logout" and method == "POST":
            with FIXTURE.lock:
                FIXTURE.sessions.discard(self.token)
            self.reply(200, {"authenticated": False, "auth_required": True}, cookie='inky_session=""; Max-Age=0; Path=/; SameSite=Strict')
            FIXTURE.emit("hello", {})
            return
        if path == "/api/state" and method == "GET":
            self.reply(200, FIXTURE.state())
            return
        if path == "/api/display" and method == "GET":
            self.reply(200, FIXTURE.display)
            return
        if path == "/api/queue" and method == "GET":
            with FIXTURE.lock:
                self.reply(200, FIXTURE.queue)
            return
        if path == "/api/queue" and method == "POST":
            self.upload(raw)
            return
        if path == "/api/queue/reorder" and method == "POST":
            ids = body.get("photo_ids", [])
            if not ids:
                self.reply(422, {"detail": [{"loc": ["body", "photo_ids"], "msg": "List should have at least 1 item", "type": "too_short"}]})
                return
            with FIXTURE.lock:
                ordered = {entry["photo"]["id"]: entry for entry in FIXTURE.queue}
                final = list(dict.fromkeys(photo_id for photo_id in ids if photo_id in ordered))
                final.extend(photo_id for photo_id in ordered if photo_id not in final)
                FIXTURE.queue = [ordered[photo_id] for photo_id in final]
                for i, entry in enumerate(FIXTURE.queue):
                    entry["position"] = i
                self.reply(200, FIXTURE.queue)
            FIXTURE.emit("queue_updated", {"action": "reordered"})
            return
        if path.startswith("/api/queue/") and method == "DELETE":
            photo_id = path.rsplit("/", 1)[1]
            with FIXTURE.lock:
                previous = len(FIXTURE.queue)
                FIXTURE.queue = [entry for entry in FIXTURE.queue if entry["photo"]["id"] != photo_id]
                if previous == len(FIXTURE.queue):
                    self.failure(404, "Not in queue")
                    return
            self.reply(204)
            FIXTURE.emit("queue_updated", {"action": "removed", "photo_id": photo_id})
            return
        if path == "/api/history" and method == "GET":
            query = parse_qs(parsed.query)
            limit, offset = int(query.get("limit", ["100"])[0]), int(query.get("offset", ["0"])[0])
            if not 1 <= limit <= 500 or offset < 0:
                self.reply(422, {"detail": [{"loc": ["query"], "msg": "Invalid pagination", "type": "value_error"}]})
                return
            with FIXTURE.lock:
                self.reply(200, FIXTURE.history[offset:offset + limit])
            return
        if path == "/api/history" and method == "DELETE":
            with FIXTURE.lock:
                count = len(FIXTURE.history)
                FIXTURE.history = []
            self.reply(204)
            FIXTURE.emit("history_changed", {"cleared": count})
            return
        if path.startswith("/api/history/") and method == "DELETE":
            entry_id = int(path.rsplit("/", 1)[1])
            with FIXTURE.lock:
                FIXTURE.history = [entry for entry in FIXTURE.history if entry["id"] != entry_id]
            self.reply(204)
            FIXTURE.emit("history_changed", {"deleted": entry_id})
            return
        if path.startswith("/api/photos/") and method == "GET":
            data = FIXTURE.files.get(path.rsplit("/", 1)[1])
            if data is None:
                self.failure(404, "Unknown photo")
            else:
                self.reply(200, data=data, content_type="image/png")
            return
        if path == "/api/settings" and method in {"GET", "POST"}:
            if method == "POST":
                with FIXTURE.lock:
                    delay, cancelled = FIXTURE.settings_delay, FIXTURE.delay_cancelled
                if cancelled.wait(delay):
                    self.failure(503, "Fixture reset during settings save")
                    return
                rules = {
                    "change_mode": lambda value: value in {"daily", "interval", "manual"},
                    "change_hour": lambda value: isinstance(value, int) and 0 <= value <= 23,
                    "change_interval_minutes": lambda value: isinstance(value, int) and 1 <= value <= 1440,
                    "saturation": lambda value: isinstance(value, (float, int)) and 0 <= value <= 2,
                }
                for key, value in body.items():
                    if key in rules and value is not None and not rules[key](value):
                        self.reply(422, {"detail": [{"loc": ["body", key], "msg": f"Invalid {key}", "type": "value_error"}]})
                        return
                with FIXTURE.lock:
                    if cancelled.is_set() or not FIXTURE.available:
                        self.failure(503, "Fixture API temporarily unavailable")
                        return
                    FIXTURE.settings.update({key: value for key, value in body.items() if key in rules and value is not None})
            self.reply(200, FIXTURE.settings)
            if method == "POST":
                FIXTURE.emit("settings_changed", copy.deepcopy(FIXTURE.settings))
            return
        if path in {"/api/display/next", "/api/display/previous"} and method == "POST":
            self.display_action(path.endswith("/previous"))
            return
        if path == "/api/system/update" and method == "GET":
            self.reply(200, {"current": "0.4.2", "latest": "0.4.2", "update_available": False})
            return
        if path == "/api/system/update" and method == "POST":
            self.reply(202, {"started": True})
            FIXTURE.emit("system_update", {"stage": "checking", "message": "Recherche de la dernière version…"})
            FIXTURE.emit("system_update", {"stage": "error", "message": "Serveur de test : aucune mise à jour réelle n’est effectuée."})
            return
        self.failure(404, HTTPStatus.NOT_FOUND.phrase)

    def upload(self, raw: bytes) -> None:
        content_type = self.headers.get("Content-Type", "")
        mime = BytesParser(policy=policy.default).parsebytes(f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + raw)
        part = next((part for part in mime.walk() if part.get_param("name", header="content-disposition") == "file"), None)
        if part is None:
            self.reply(422, {"detail": [{"loc": ["body", "file"], "msg": "Field required", "type": "missing"}]})
            return
        data = part.get_payload(decode=True)
        if not isinstance(data, bytes) or len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n":
            self.failure(400, "Only PNG uploads are accepted — the client must convert before upload")
            return
        if len(data) > MAX_UPLOAD:
            self.failure(413, "Photo exceeds the 10 MiB upload limit")
            return
        width, height = struct.unpack("!II", data[16:24])
        if (width, height) != (WIDTH, HEIGHT):
            self.failure(400, f"Image size {width}x{height} does not match display {WIDTH}x{HEIGHT}")
            return
        sha = hashlib.sha256(data).hexdigest()
        with FIXTURE.lock:
            photo = next((photo for photo in FIXTURE.photos.values() if photo["sha256"] == sha), None)
            existed = photo is not None
            if photo is None:
                photo_id = secrets.token_hex(6)
                photo = {"id": photo_id, "sha256": sha, "original_filename": part.get_filename() or "upload.png", "mime": "image/png", "width": width, "height": height, "size_bytes": len(data), "created_at": time.time()}
                FIXTURE.photos[photo_id] = photo
                FIXTURE.files[photo_id] = data
            entry = next((entry for entry in FIXTURE.queue if entry["photo"]["id"] == photo["id"]), None)
            if entry is None:
                entry = {"id": FIXTURE.next_queue_id, "position": max((entry["position"] for entry in FIXTURE.queue), default=-1) + 1, "added_at": time.time(), "photo": photo}
                FIXTURE.next_queue_id += 1
                FIXTURE.queue.append(entry)
            self.reply(201, {"photo": photo, "queue_entry": entry, "already_existed": existed})
        FIXTURE.emit("photo_uploaded", {"photo_id": photo["id"], "already_existed": existed})
        FIXTURE.emit("queue_updated", {"action": "added", "photo_id": photo["id"]})

    def display_action(self, previous: bool) -> None:
        with FIXTURE.lock:
            photo = None
            popped = None
            navigation_id = None
            if previous:
                prev = next((entry for entry in FIXTURE.history if entry["id"] < FIXTURE.navigation_history_id), None)
                if prev:
                    photo, navigation_id = prev["photo"], prev["id"]
            elif FIXTURE.queue:
                popped = FIXTURE.queue.pop(0)
                photo = popped["photo"]
            else:
                current_id = FIXTURE.history[0]["photo"]["id"] if FIXTURE.history else None
                candidates = [entry["photo"] for entry in reversed(FIXTURE.history) if entry["photo"]["id"] != current_id]
                photo = candidates[0] if candidates else None
            if photo:
                entry = {"id": FIXTURE.next_history_id, "displayed_at": time.time(), "source": "manual_previous" if previous else "manual_next", "photo": photo}
                FIXTURE.next_history_id += 1
                FIXTURE.navigation_history_id = navigation_id or entry["id"]
                FIXTURE.history.insert(0, entry)
                FIXTURE.emit("display_changed", {"history_id": entry["id"], "photo_id": photo["id"], "source": entry["source"]})
            if popped:
                FIXTURE.emit("queue_updated", {"action": "popped", "photo_id": photo["id"]})
        self.reply(202)

    def websocket(self) -> None:
        key = self.headers.get("Sec-WebSocket-Key")
        if not key or self.headers.get("Upgrade", "").lower() != "websocket":
            self.failure(400, "WebSocket upgrade required")
            return
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        write_lock = threading.Lock()
        with FIXTURE.lock:
            if not FIXTURE.available:
                self.failure(503, "Fixture API temporarily unavailable")
                return
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            self.wfile.flush()
            FIXTURE.sockets[self.connection] = (self.token, write_lock)
        self.close_connection = True
        try:
            with write_lock:
                send_frame(self.connection, b'{"type":"hello","payload":{}}')
            while self.token in FIXTURE.sessions:
                header = exact(self.connection, 2)
                opcode, masked, length = header[0] & 15, bool(header[1] & 128), header[1] & 127
                if length == 126:
                    length = struct.unpack("!H", exact(self.connection, 2))[0]
                elif length == 127:
                    length = struct.unpack("!Q", exact(self.connection, 8))[0]
                if length > 65536:
                    break
                mask = exact(self.connection, 4) if masked else b""
                payload = exact(self.connection, length)
                if masked:
                    payload = bytes(value ^ mask[i % 4] for i, value in enumerate(payload))
                if opcode == 8:
                    with write_lock:
                        send_frame(self.connection, payload[:125], 8)
                    break
                if opcode == 9:
                    with write_lock:
                        send_frame(self.connection, payload, 10)
        except (OSError, ConnectionError):
            pass
        finally:
            with FIXTURE.lock:
                FIXTURE.sockets.pop(self.connection, None)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--biometric-device", help="Optional booted simulator UDID for Xcode 27 Face ID UI tests")
    options = parser.parse_args()
    if options.biometric_device:
        devices = json.loads(subprocess.check_output(["xcrun", "simctl", "list", "devices", "booted", "--json"]))
        if not any(device["udid"] == options.biometric_device and device["state"] == "Booted" for runtime in devices["devices"].values() for device in runtime):
            parser.error("--biometric-device must be a booted iOS Simulator UDID")
        subprocess.run(["xcrun", "devicectl", "device", "settings", "biometrics", "--device", options.biometric_device, "--enable", "--timeout", "10"], check=True, timeout=12)
    server = ThreadingHTTPServer(("127.0.0.1", options.port), Handler)
    server.daemon_threads = True
    server.biometric_device = options.biometric_device
    print(f"Inky fixture ready: http://127.0.0.1:{options.port} (test-password)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
