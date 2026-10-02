"""Exercise HTTP ingress through the real app, parser, storage and event bus."""
from __future__ import annotations

import asyncio
import json
import struct
import zlib

import pytest
import starlette.formparsers
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException
from starlette.websockets import WebSocketDisconnect

from inky_web.body_limit import (
    MAX_REQUEST_BODY_BYTES,
    BodyLimitMiddleware,
    RequestBodyTooLarge,
    body_limit_http_exception_handler,
)

MIB = 1024 * 1024
BOUNDARY = b"inky-test-boundary"
MULTIPART = (b"content-type", b"multipart/form-data; boundary=" + BOUNDARY)
PART_HEADER = (
    b"--" + BOUNDARY + b'\r\nContent-Disposition: form-data; name="file"; filename="photo.png"'
    b"\r\nContent-Type: image/png\r\n\r\n"
)
PART_END = b"\r\n--" + BOUNDARY + b"--\r\n"


def _request(client, chunks, *, headers=(), path="/api/queue", method="POST", version="1.1"):
    """Control ASGI receive boundaries, including dishonest Content-Length."""
    from inky_web.main import app

    result = {"reads": 0, "messages": []}

    async def run():
        async def receive():
            index = result["reads"]
            if index >= len(chunks):
                # A disconnect watcher can wait here until the response ends.
                await asyncio.Event().wait()
            result["reads"] += 1
            return {"type": "http.request", "body": chunks[index],
                    "more_body": index + 1 < len(chunks)}

        async def send(message):
            result["messages"].append(message)

        await asyncio.wait_for(app({
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": version, "method": method, "scheme": "http",
            "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
            "headers": list(headers), "client": ("127.0.0.1", 1), "server": ("test", 80),
        }, receive, send), timeout=5)

    client.portal.call(run)
    starts = [m for m in result["messages"] if m["type"] == "http.response.start"]
    assert len(starts) == 1
    result["status"] = starts[0]["status"]
    result["headers"] = dict(starts[0]["headers"])
    result["body"] = b"".join(m.get("body", b"") for m in result["messages"])
    return result


@pytest.fixture
def spools(monkeypatch):
    original = starlette.formparsers.SpooledTemporaryFile
    records = []

    def create(*args, **kwargs):
        file = original(*args, **kwargs)
        record = {"file": file, "written": 0}
        records.append(record)
        write = file.write

        def record_write(data):
            record["written"] += len(data)
            return write(data)

        file.write = record_write
        return file

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", create)
    return records


def _assert_413(result):
    assert result["status"] == 413
    assert json.loads(result["body"]) == {"detail": "Requête trop volumineuse (limite : 11 Mio)"}
    assert result["headers"][b"connection"] == b"close"


@pytest.mark.parametrize("length", [
    str(MAX_REQUEST_BODY_BYTES + 1).encode(),
    b"0" * 20 + str(MAX_REQUEST_BODY_BYTES + 1).encode(),
    b"9" * 5000,
])
def test_declared_overflow_rejects_without_receive_or_spool(client, spools, length):
    result = _request(client, [PART_HEADER, b"unused"], headers=[MULTIPART, (b"content-length", length)])
    _assert_413(result)
    assert result["reads"] == 0
    assert spools == []


@pytest.mark.parametrize("framing", [[], [(b"transfer-encoding", b"chunked")],
                                    [(b"content-length", b"1")], [(b"content-length", b"0")]])
def test_streaming_overflow_stops_receive_and_closes_rolled_file(client, spools, monkeypatch, framing):
    from inky_web.db import connection
    from inky_web.main import app

    events = []
    monkeypatch.setattr(app.state.bus, "broadcast", lambda *args: events.append(args))
    chunks = [PART_HEADER] + [b"x" * MIB] * 13 + [PART_END]
    result = _request(client, chunks, headers=[MULTIPART, *framing])
    _assert_413(result)
    assert result["reads"] == 12 < len(chunks)
    assert len(spools) == 1
    assert spools[0]["file"]._rolled
    assert spools[0]["file"].closed
    # The crossing chunk was withheld before the parser wrote its contents.
    assert spools[0]["written"] == 10 * MIB
    assert client.get("/api/queue").json() == []
    with connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0] == 0
    assert events == []


@pytest.mark.parametrize("declared", [False, True])
def test_exact_total_limit_accepts_json_and_one_more_byte_rejects(client, declared):
    payload = b'{"photo_ids": ["unknown"]}'
    payload += b" " * (MAX_REQUEST_BODY_BYTES - len(payload))
    headers = [(b"content-type", b"application/json")]
    if declared:
        headers.append((b"content-length", str(MAX_REQUEST_BODY_BYTES).encode()))
    accepted = _request(client, [payload], headers=headers, path="/api/queue/reorder")
    assert accepted["status"] == 200
    assert json.loads(accepted["body"]) == []
    rejected = _request(client, [payload, b" ", b"unread"], headers=headers, path="/api/queue/reorder")
    _assert_413(rejected)
    assert rejected["reads"] == 2


def _padded_png(png_factory, size):
    png = png_factory(800, 480)
    # A private ancillary PNG chunk keeps the exact-size image structurally valid.
    data = b"x" * (size - len(png) - 12)
    chunk = b"npAd" + data
    return png[:-12] + struct.pack("!I", len(data)) + chunk + struct.pack("!I", zlib.crc32(chunk)) + png[-12:]


def test_ten_mib_png_plus_envelope_is_accepted(client, png_factory, spools):
    png = _padded_png(png_factory, 10 * MIB)
    assert len(png) == 10 * MIB
    response = client.post("/api/queue", files={"file": ("large.png", png, "image/png")})
    assert response.status_code == 201
    assert len(client.get("/api/queue").json()) == 1
    assert spools and all(record["file"].closed for record in spools)


def test_file_limit_remains_ten_mib(client, png_factory, spools):
    png = _padded_png(png_factory, 10 * MIB + 1)
    response = client.post("/api/queue", files={"file": ("large.png", png, "image/png")})
    assert response.status_code == 413
    assert response.json()["detail"] == "Photo exceeds the 10 MiB upload limit"
    assert client.get("/api/queue").json() == []
    assert spools and all(record["file"].closed for record in spools)


def test_existing_parse_and_validation_errors_keep_their_status(client):
    malformed = client.post("/api/queue", content=b"bad", headers={"Content-Type": "multipart/form-data"})
    assert malformed.status_code == 400
    assert malformed.json()["detail"] == "Missing boundary in multipart."
    assert client.post("/api/queue", files={"other": ("x.png", b"bad", "image/png")}).status_code == 422
    invalid_json = client.post("/api/queue/reorder", content=b"{", headers={"Content-Type": "application/json"})
    assert invalid_json.status_code == 422
    assert client.get("/api/missing").status_code == 404


def test_auth_rejection_precedes_body_read_and_retains_cors(client, monkeypatch, spools):
    monkeypatch.setenv("INKY_STUDIO_DISABLE_AUTH", "0")
    result = _request(client, [PART_HEADER, b"unused"], headers=[
        MULTIPART, (b"content-length", str(MAX_REQUEST_BODY_BYTES + 1).encode()),
        (b"origin", b"http://localhost:5273"),
    ])
    assert result["status"] == 401
    assert result["reads"] == 0
    assert result["headers"][b"access-control-allow-origin"] == b"http://localhost:5273"
    assert spools == []


@pytest.mark.parametrize("path", [
    "/api/auth/login", "/api/auth/status", "/api/health", "/api/provisioning/wifi/confirm",
    "/api/ws", "/non-api-page",
])
def test_auth_exemptions_still_reach_ingress_limit(client, monkeypatch, path):
    monkeypatch.setenv("INKY_STUDIO_DISABLE_AUTH", "0")
    result = _request(client, [b"unread"], path=path, headers=[
        (b"content-length", str(MAX_REQUEST_BODY_BYTES + 1).encode()),
    ])
    _assert_413(result)
    assert result["reads"] == 0


def test_authenticated_upload_still_reaches_ingress_limit(client, monkeypatch):
    from inky_web import auth
    from inky_web.main import app

    monkeypatch.setenv("INKY_STUDIO_DISABLE_AUTH", "0")
    token = app.state.sessions.create()
    result = _request(client, [PART_HEADER] + [b"x" * MIB] * 13 + [PART_END], headers=[
        MULTIPART, (b"cookie", f"{auth.COOKIE_NAME}={token}".encode()),
    ])
    _assert_413(result)
    assert result["reads"] == 12


@pytest.mark.parametrize("declared", [False, True])
def test_limit_responses_retain_cors(client, declared):
    headers = [(b"content-type", b"application/json"), (b"origin", b"http://localhost:5273")]
    if declared:
        headers.append((b"content-length", str(MAX_REQUEST_BODY_BYTES + 1).encode()))
    result = _request(client, [b"x" * (MAX_REQUEST_BODY_BYTES + 1)],
                      headers=headers, path="/api/queue/reorder")
    _assert_413(result)
    assert result["headers"][b"access-control-allow-origin"] == b"http://localhost:5273"


def test_preflight_still_precedes_auth_and_body_limit(client, monkeypatch):
    monkeypatch.setenv("INKY_STUDIO_DISABLE_AUTH", "0")
    result = _request(client, [b"unused"], method="OPTIONS", headers=[
        (b"origin", b"http://localhost:5273"), (b"access-control-request-method", b"POST"),
        (b"content-length", str(MAX_REQUEST_BODY_BYTES + 1).encode()),
    ])
    assert result["status"] == 200
    assert result["reads"] == 0


def test_http2_omits_connection_header(client):
    result = _request(client, [], version="2", headers=[
        (b"content-length", str(MAX_REQUEST_BODY_BYTES + 1).encode()),
    ])
    assert result["status"] == 413
    assert b"connection" not in result["headers"]


def test_websocket_ignores_http_body_limit_and_preserves_auth(client, monkeypatch):
    with client.websocket_connect("/api/ws", headers={"Content-Length": str(MAX_REQUEST_BODY_BYTES + 1)}) as socket:
        assert socket.receive_json()["type"] == "hello"
    monkeypatch.setenv("INKY_STUDIO_DISABLE_AUTH", "0")
    with pytest.raises(WebSocketDisconnect) as rejected, client.websocket_connect("/api/ws"):
        pass
    assert rejected.value.code == 1008


def test_direct_body_reader_gets_413():
    app = FastAPI()
    app.add_middleware(BodyLimitMiddleware)

    @app.post("/")
    async def read(request: Request):
        await request.body()
        return {}

    with TestClient(app) as client:
        # A lying length forces receive(), rather than the early header path.
        response = client.post("/", content=b"x" * (MAX_REQUEST_BODY_BYTES + 1), headers={"Content-Length": "1"})
    assert response.status_code == 413


def test_unrelated_http_exception_is_not_remapped():
    app = FastAPI()
    app.add_exception_handler(HTTPException, body_limit_http_exception_handler)

    @app.get("/")
    async def unrelated(request: Request):
        # A swallowed overflow must not rewrite a later, unrelated HTTP error.
        request.scope["inky_web.request_body_limit_exceeded"] = True
        raise HTTPException(409, detail="conflict", headers={"X-Error": "kept"})

    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 409
    assert response.headers["X-Error"] == "kept"


async def test_overflow_after_response_start_does_not_send_twice():
    messages = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await receive()

    async def receive():
        return {"type": "http.request", "body": b"x" * (MAX_REQUEST_BODY_BYTES + 1)}

    async def send(message):
        messages.append(message)

    with pytest.raises(RequestBodyTooLarge):
        await BodyLimitMiddleware(app)({"type": "http", "headers": []}, receive, send)
    assert [message["type"] for message in messages] == ["http.response.start"]
