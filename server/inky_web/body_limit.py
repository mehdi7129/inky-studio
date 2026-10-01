"""Bound HTTP ingress before body buffering and multipart temporary-file writes."""
from __future__ import annotations

from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Leave room for a multipart envelope around the queue's 10 MiB PNG limit.
MAX_REQUEST_BODY_BYTES = 11 * 1024 * 1024
_OVERFLOW_KEY = "inky_web.request_body_limit_exceeded"
_DETAIL = "Requête trop volumineuse (limite : 11 Mio)"


class RequestBodyTooLarge(MultiPartException):
    """Trigger Starlette's multipart cleanup, including rolled-over temp files."""

    def __init__(self) -> None:
        super().__init__(_DETAIL)


def _too_large_response(scope: Scope) -> JSONResponse:
    # The remaining body is intentionally not drained; do not reuse HTTP/1.x.
    headers = {"Connection": "close"} if scope.get("http_version", "").startswith("1.") else None
    return JSONResponse({"detail": _DETAIL}, status_code=413, headers=headers)


async def body_limit_http_exception_handler(request: Request, exc: HTTPException) -> Response:
    # Request.form() translates MultiPartException to 400; FastAPI does the
    # same for JSON body reads. Only translate our own receive failure back.
    cause = exc.__cause__ or exc.__context__
    if request.scope.get(_OVERFLOW_KEY) and isinstance(cause, RequestBodyTooLarge):
        return _too_large_response(request.scope)
    return await http_exception_handler(request, exc)


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit_digits = str(MAX_REQUEST_BODY_BYTES).encode("ascii")
        for name, value in scope.get("headers", []):
            if name.lower() != b"content-length":
                continue
            # Compare decimal strings, avoiding int() on an untrusted huge
            # header. The HTTP server handles invalid framing; we still count.
            value = value.strip()
            if value.isdigit():
                digits = value.lstrip(b"0") or b"0"
                if len(digits) > len(limit_digits) or (
                    len(digits) == len(limit_digits) and digits > limit_digits
                ):
                    await _too_large_response(scope)(scope, receive, send)
                    return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            if received > MAX_REQUEST_BODY_BYTES:
                raise RequestBodyTooLarge()
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_REQUEST_BODY_BYTES:
                    scope[_OVERFLOW_KEY] = True
                    # Do not forward this chunk or receive any remaining body.
                    raise RequestBodyTooLarge()
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except RequestBodyTooLarge:
            # Covers direct Request.body()/stream() consumers outside FastAPI's
            # body parsing. Never attempt a second response after headers went out.
            if response_started:
                raise
            await _too_large_response(scope)(scope, receive, send)
