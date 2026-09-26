#!/usr/bin/env python3
"""Exercise the local fixture's REST/auth/WebSocket contract, never a real Pi.

Start mock-server.py first; then run python3 ios/scripts/smoke-api.py.
"""
from __future__ import annotations

import argparse
import base64
from http.cookiejar import CookieJar
import json
import secrets
import socket
import struct
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPCookieProcessor, Request


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    parsed = urlsplit(base)
    if parsed.hostname != "127.0.0.1" or parsed.scheme != "http" or parsed.path or parsed.username or parsed.password:
        parser.error("This destructive fixture test only accepts http://127.0.0.1:<port>")
    jar = CookieJar()
    client = build_opener(HTTPCookieProcessor(jar))
    checks = 0

    def request(path: str, method: str = "GET", value: object = None, *, data: bytes | None = None, content_type: str = "application/json", expected: int = 200):
        nonlocal checks
        payload = json.dumps(value).encode() if value is not None else data
        req = Request(base + path, data=payload, method=method, headers={"Content-Type": content_type})
        try:
            response = client.open(req, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            body = response.read()
            assert response.status == expected, (path, response.status, body)
            checks += 1
            return json.loads(body) if "application/json" in response.headers.get("Content-Type", "") and body else body

    def receive(connection: socket.socket, count: int) -> bytes:
        result = b""
        while len(result) < count:
            chunk = connection.recv(count - len(result))
            assert chunk, "WebSocket closed unexpectedly"
            result += chunk
        return result

    def event(connection: socket.socket) -> dict:
        head = receive(connection, 2)
        length = head[1] & 127
        if length == 126:
            length = struct.unpack("!H", receive(connection, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", receive(connection, 8))[0]
        assert head[0] & 15 == 1, "Expected a text WebSocket frame"
        return json.loads(receive(connection, length))

    # This fixture-specific preflight prevents accidentally testing another local service.
    assert request("/api/health") == {"status": "ok", "version": "0.4.2"}
    assert request("/__test/reset", "POST", {}) == {"reset": True}
    connection = None
    try:
        assert request("/api/auth/status") == {"authenticated": False, "auth_required": True}
        assert request("/api/state", expected=401)["detail"] == "Authentification requise"
        assert request("/api/auth/login", "POST", {"password": "wrong"}, expected=401)["detail"] == "Mot de passe incorrect"
        assert request("/api/auth/login", "POST", {"password": "test-password"})["authenticated"]
        cookie = next(cookie for cookie in jar if cookie.name == "inky_session")
        assert cookie.value and cookie.path == "/" and not cookie.secure
        assert request("/api/auth/status")["authenticated"]
        state = request("/api/state")
        assert (state["display"]["width"], state["display"]["height"]) == (800, 480)
        assert state["current"]["photo"]["id"] == "c0a570000001" and state["queue_count"] == 2
        assert request("/api/display") == state["display"]
        queue = request("/api/queue")
        assert [entry["photo"]["id"] for entry in queue] == ["a11050000002", "5ad000000003"]
        assert len(request("/api/history?limit=1&offset=1")) == 1
        assert len(request("/api/history")) == 2
        png = request("/api/photos/c0a570000001")
        assert png.startswith(b"\x89PNG") and struct.unpack("!II", png[16:24]) == (800, 480)
        request("/api/photos/missing", expected=404)
        connection = socket.create_connection(("127.0.0.1", parsed.port or 80), timeout=5)
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        connection.sendall((f"GET /api/ws HTTP/1.1\r\nHost: {parsed.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\nCookie: inky_session={cookie.value}\r\n\r\n").encode())
        headers = b""
        while not headers.endswith(b"\r\n\r\n"):
            headers += receive(connection, 1)
        assert b"101 Switching Protocols" in headers
        assert event(connection) == {"type": "hello", "payload": {}}
        checks += 2
        settings = request("/api/settings", "POST", {"change_mode": "manual", "saturation": 1.2})
        assert settings["change_mode"] == "manual" and settings["saturation"] == 1.2
        assert event(connection) == {"type": "settings_changed", "payload": settings}
        checks += 1
        assert request("/api/state")["next_change_at"] is None
        request("/api/settings", "POST", {"saturation": 3}, expected=422)
        ids = [entry["photo"]["id"] for entry in reversed(queue)]
        assert [entry["photo"]["id"] for entry in request("/api/queue/reorder", "POST", {"photo_ids": ids})] == ids
        request("/api/queue/reorder", "POST", {"photo_ids": []}, expected=422)
        boundary = "InkyFixtureBoundary"
        multipart = f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="Cassis.png"\r\nContent-Type: image/png\r\n\r\n'.encode() + png + f"\r\n--{boundary}--\r\n".encode()
        upload = request("/api/queue", "POST", data=multipart, content_type=f"multipart/form-data; boundary={boundary}", expected=201)
        assert upload["already_existed"] and upload["photo"]["id"] == "c0a570000001"
        assert request("/api/state")["queue_count"] == 3
        request("/api/queue", "POST", data=multipart, content_type=f"multipart/form-data; boundary={boundary}", expected=201)
        assert len(request("/api/queue")) == 3, "Re-upload must not duplicate a queued photo"
        request("/api/queue/c0a570000001", "DELETE", expected=204)
        request("/api/queue/missing", "DELETE", expected=404)
        assert request("/api/display/next", "POST", expected=202) == b""
        assert request("/api/state")["current"]["photo"]["id"] == "5ad000000003"
        assert request("/api/display/previous", "POST", expected=202) == b""
        request("/api/history/1", "DELETE", expected=204)
        assert request("/api/system/update?refresh=1") == {"current": "0.4.2", "latest": "0.4.2", "update_available": False}
        assert request("/api/system/update", "POST", expected=202) == {"started": True}
        request("/api/history", "DELETE", expected=204)
        assert request("/api/history") == []
        assert request("/api/state")["current"] is None
        assert not request("/api/auth/logout", "POST")["authenticated"]
        request("/api/queue", expected=401)
        assert not request("/api/auth/status")["authenticated"]
    finally:
        if connection:
            connection.close()
        request("/__test/reset", "POST", {})
    print(f"PASS: {checks} REST, cookie, PNG and WebSocket fixture checks")


if __name__ == "__main__":
    main()
