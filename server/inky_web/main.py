"""Entry point for the Inky Studio FastAPI app."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from inky_web import __version__, auth
from inky_web.api import router as api_router
from inky_web.db import data_dir, init_db
from inky_web.events import EventBus
from inky_web.inky.display import DisplayController
from inky_web.inky.errors import DisplayUnavailableError
from inky_web.provisioning.api import CONFIRM_PATH
from inky_web.provisioning.api import router as provisioning_router
from inky_web.services.scheduler import Scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

CLIENT_DIST = Path(__file__).resolve().parents[2] / "client" / "dist"


class AuthMiddleware(BaseHTTPMiddleware):
    """Block unauthenticated requests to /api/* (with a few public exceptions)."""

    async def dispatch(self, request: Request, call_next):
        if auth.auth_disabled():
            return await call_next(request)

        path = request.url.path
        if not path.startswith("/api"):
            return await call_next(request)
        if path in auth.PUBLIC_PATHS:
            return await call_next(request)
        if path == CONFIRM_PATH:
            # Strict HTTPS + owner authentication is performed inside the route.
            return await call_next(request)
        # WebSocket auth is checked separately inside the route — Starlette doesn't
        # pass WS through HTTP middleware uniformly across versions, so we no-op here.
        if path == "/api/ws":
            return await call_next(request)

        sessions = request.app.state.sessions
        token = auth.get_session_token(request)
        if not sessions.validate(token):
            return JSONResponse(
                {"detail": "Authentification requise"},
                status_code=401,
            )
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    app.state.sessions = auth.SessionStore()
    app.state.auth_service = auth.CredentialService(
        auth.load_or_create_credentials(data_dir()), app.state.sessions,
    )
    app.state.login_limiter = auth.LoginRateLimiter()
    app.state.password_change_limiter = auth.LoginRateLimiter()
    app.state.bus = EventBus()
    app.state.display = DisplayController()
    app.state.display.initialize()
    app.state.scheduler = Scheduler(app.state.display, app.state.bus)
    app.state.provisioning = None
    welcome_task = None
    if not auth.auth_disabled():
        logger = logging.getLogger(__name__)
        logger.info(
            "Auth enabled. Credentials persisted in %s",
            app.state.auth_service.credentials.path,
        )

    # Retry bootstrap display after a power interruption between credential
    # persistence and the first successful screen refresh. Never reveal a
    # personalized password, or overwrite a frame that already has history.
    if app.state.auth_service.credentials.bootstrap_password and not auth.auth_disabled():
        # No history yet → show welcome. Run in a thread so lifespan stays snappy.
        from inky_web.services import history as history_service
        from inky_web.welcome import show_welcome

        if history_service.count() == 0:
            logging.getLogger(__name__).info(
                "First boot detected — pushing welcome screen to the Inky"
            )
            async def welcome():
                try:
                    await asyncio.to_thread(show_welcome, app.state.display)
                except DisplayUnavailableError as exc:
                    logging.getLogger(__name__).error("Welcome display unavailable: %s", exc.code)
                    app.state.bus.broadcast("display_error", exc.payload())

            welcome_task = asyncio.create_task(welcome())

    try:
        if os.environ.get("INKY_STUDIO_BLUETOOTH") == "1" and not auth.auth_disabled():
            from inky_web.provisioning.runtime import ProvisioningRuntime
            app.state.provisioning = ProvisioningRuntime(
                data_dir() / "provisioning", app.state.auth_service, app.state.display,
                getattr(app.state, "frame_identity", None),
            )
            app.state.auth_service.prepare_owner_rotation = app.state.provisioning.prepare_rotation
            try:
                await app.state.provisioning.start()
            except Exception:
                logging.getLogger(__name__).error("Bluetooth unavailable; existing frame API remains active")
        await app.state.scheduler.start()
        yield
    finally:
        try:
            try:
                if app.state.provisioning is not None:
                    await app.state.provisioning.stop()
            finally:
                await app.state.scheduler.stop()
                if welcome_task is not None:
                    await welcome_task
        finally:
            app.state.display.shutdown()


app = FastAPI(
    title="Inky Studio",
    version=__version__,
    description="Web UI for the Inky e-ink photo frame",
    lifespan=lifespan,
)


@app.exception_handler(DisplayUnavailableError)
async def display_error(request: Request, exc: DisplayUnavailableError):
    return JSONResponse(status_code=503, content=exc.payload())


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    if request.url.path in {"/api/auth/login", "/api/auth/password"} or request.url.path.startswith("/api/provisioning/"):
        # FastAPI otherwise echoes the supplied secret in the validation input.
        errors = [{key: error[key] for key in ("type", "loc", "msg")} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})
    return await request_validation_exception_handler(request, exc)


app.add_middleware(AuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5273",
        "http://127.0.0.1:5273",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")
app.include_router(provisioning_router, prefix="/api")

async def spa_fallback(full_path: str) -> FileResponse:
    root = CLIENT_DIST.resolve()
    candidate = (root / full_path).resolve()
    if not candidate.is_relative_to(root) or full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    if candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(root / "index.html")


if CLIENT_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=CLIENT_DIST / "assets"), name="assets")
    app.add_api_route("/{full_path:path}", spa_fallback, methods=["GET"], include_in_schema=False)


def run() -> None:
    if os.environ.get("INKY_STUDIO_BLUETOOTH") == "1" and not auth.auth_disabled():
        asyncio.run(serve_with_https())
        return
    uvicorn.run(
        "inky_web.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        # Bound shutdown so an open WebSocket can't make `systemctl restart`
        # (used by the in-app update) hang until systemd's SIGKILL timeout.
        timeout_graceful_shutdown=10,
    )


async def serve_with_https() -> None:
    """Two listeners, one lifespan, one scheduler and one hardware owner."""
    from contextlib import contextmanager

    from inky_web.provisioning.identity import load_or_create_identity

    class ManagedServer(uvicorn.Server):
        @contextmanager
        def capture_signals(self):
            yield

        async def serve(self, sockets=None):
            try:
                await super().serve(sockets=sockets)
            except BaseException as exc:
                # Uvicorn uses SystemExit for bind failures. Letting it escape
                # an asyncio task cancels the shared lifespan before its workers
                # can drain. Treat this listener failure as an ordinary error.
                if self.started:
                    await self.shutdown(sockets=sockets)
                if isinstance(exc, SystemExit):
                    raise RuntimeError("Frame listener failed to start") from exc
                raise

    app.state.frame_identity = load_or_create_identity(data_dir() / "provisioning")
    cert, key = app.state.frame_identity.materialize_tls_files()
    async with lifespan(app):
        common = dict(app=app, host="0.0.0.0", lifespan="off", timeout_graceful_shutdown=10)
        http = uvicorn.Config(port=8000, **common)
        https = uvicorn.Config(port=8443, ssl_certfile=str(cert), ssl_keyfile=str(key), **common)
        https.load()
        # Share the exact context with BLE, including subsequent certificate
        # renewals. An already established TLS session keeps its own handshake.
        https.ssl = app.state.provisioning.tls_context
        servers = [ManagedServer(http), ManagedServer(https)]
        loop = asyncio.get_running_loop()
        def shutdown():
            for server in servers:
                server.should_exit = True
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, shutdown)
        tasks = [asyncio.create_task(server.serve()) for server in servers]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            shutdown()
            try:
                results = await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                for sig in (signal.SIGTERM, signal.SIGINT):
                    loop.remove_signal_handler(sig)
        for result in results:
            if isinstance(result, BaseException):
                raise result


if __name__ == "__main__":
    run()
