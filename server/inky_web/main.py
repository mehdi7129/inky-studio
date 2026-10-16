"""Entry point for the Inky Studio FastAPI app."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import signal
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware

from inky_web import __version__, auth
from inky_web.api import router as api_router
from inky_web.api.legacy_tls_proof import PROOF_PATH
from inky_web.api.photo_access import require_https
from inky_web.db import data_dir, init_db, resolve_data_dir
from inky_web.events import EventBus
from inky_web.frontend import resolve_client_dist
from inky_web.inky.display import DisplayController
from inky_web.inky.errors import DisplayUnavailableError
from inky_web.photo_access import PhotoAccessStore
from inky_web.provisioning.api import CONFIRM_PATH
from inky_web.provisioning.api import router as provisioning_router
from inky_web.provisioning.factory_writer import FactoryWriterRefused, main_writer_guard
from inky_web.services.scheduler import Scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

CLIENT_DIST = resolve_client_dist(__file__)


class ProofCORSMiddleware(CORSMiddleware):
    """Keep the public proof path uncacheable even on early CORS responses."""

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != PROOF_PATH:
            return await super().__call__(scope, receive, send)

        async def send_no_store(message):
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = "no-store"
            await send(message)

        return await super().__call__(scope, receive, send_no_store)


class AuthMiddleware(BaseHTTPMiddleware):
    """Block unauthenticated requests to /api/* (with a few public exceptions)."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path == PROOF_PATH:
            # The nonce-only probe bypasses application cookie/session authority.
            # FastAPI may still parse cookies internally; they are never used.
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response
        individual = (path == "/api/auth/device-session" or path == "/api/auth/devices"
                      or path.startswith("/api/auth/devices/")
                      or path == "/api/auth/invitations" or path.startswith("/api/auth/invitations/"))
        if individual:
            try:
                require_https(request)
            except HTTPException as exc:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code,
                                    headers={"Cache-Control": "no-store"})
            # Bound chunked bodies too, before FastAPI parses sensitive input.
            chunks, length = [], 0
            async for chunk in request.stream():
                length += len(chunk)
                if length > 2048:
                    return JSONResponse({"detail": "Requête trop volumineuse"}, status_code=413,
                                        headers={"Cache-Control": "no-store"})
                chunks.append(chunk)
            request._body = b"".join(chunks)

        async def finish():
            response = await call_next(request)
            if individual or getattr(request.state, "photo_principal", None) is not None:
                response.headers["Cache-Control"] = "no-store"
            return response

        if auth.auth_disabled():
            return await finish()

        if not path.startswith("/api"):
            return await finish()
        sessions = request.app.state.sessions
        token = auth.get_session_token(request)
        principal = sessions.principal(token)
        if principal is not None:
            if request.scope.get("scheme") != "https":
                return JSONResponse({"detail": "Une connexion HTTPS au cadre est requise"}, status_code=403,
                                    headers={"Cache-Control": "no-store"})
            if not sessions.validate(token):
                return JSONResponse({"detail": "Authentification requise"}, status_code=401,
                                    headers={"Cache-Control": "no-store"})
            request.state.photo_principal = principal
            if principal.role == "media" and not _media_route(request.method, path):
                return JSONResponse({"detail": "Autorisation du propriétaire requise"}, status_code=403,
                                    headers={"Cache-Control": "no-store"})
            if principal.role == "media" and request.method == "POST" and path == "/api/settings":
                try:
                    body = await request.body()
                    patch = json.loads(body) if len(body) <= 2048 else None
                    if not isinstance(patch, dict) or patch.keys() - {
                        "change_mode", "change_hour", "change_interval_minutes",
                    }:
                        raise ValueError
                except (ValueError, UnicodeError):
                    return JSONResponse({"detail": "Réglage non autorisé"}, status_code=403,
                                        headers={"Cache-Control": "no-store"})
        if path in auth.PUBLIC_PATHS:
            return await finish()
        if path == CONFIRM_PATH:
            # Strict HTTPS + owner authentication is performed inside the route.
            return await finish()
        # WebSocket auth is checked separately inside the route — Starlette doesn't
        # pass WS through HTTP middleware uniformly across versions, so we no-op here.
        if path == "/api/ws":
            return await finish()

        if not sessions.validate(token):
            return JSONResponse(
                {"detail": "Authentification requise"},
                status_code=401,
                headers={"Cache-Control": "no-store"} if individual else None,
            )
        return await finish()


def _media_route(method: str, path: str) -> bool:
    """Closed capability list: future/admin endpoints are denied by default."""
    if (method, path) in {
        ("GET", "/api/health"), ("GET", "/api/auth/status"), ("POST", "/api/auth/logout"),
        ("GET", "/api/state"), ("GET", "/api/display"), ("GET", "/api/display/status"),
        ("POST", "/api/display/next"), ("POST", "/api/display/previous"),
        ("GET", "/api/queue"), ("POST", "/api/queue"), ("POST", "/api/queue/reorder"),
        ("GET", "/api/history"), ("DELETE", "/api/history"),
        ("GET", "/api/settings"), ("POST", "/api/settings"),
        ("POST", "/api/auth/device-session"), ("POST", "/api/auth/invitations/claim"),
    }:
        return True
    parts = path.split("/")
    return len(parts) == 4 and bool(parts[3]) and (method, parts[2]) in {
        ("GET", "photos"), ("DELETE", "queue"), ("DELETE", "history"),
    }


async def _select_startup_runtime() -> None:
    """Obtain OS admission before the selector or its admitted factory worker."""
    with main_writer_guard():
        await _select_startup_runtime_admitted()


async def _select_startup_runtime_admitted() -> None:
    """Return only for legacy startup; factory preparation never enables it."""
    from inky_web.provisioning.factory_runtime import (
        FactoryRuntimeError,
        initialize_factory,
        select_runtime,
    )

    config = select_runtime(resolve_data_dir())
    if config is None:
        return
    # IPC begin or a local durable write may outlive a cancelled ASGI startup.
    # Keep the admitted worker owned and drain it before propagating cancellation.
    worker = asyncio.create_task(asyncio.to_thread(initialize_factory, config))
    cancelled = False
    while not worker.done():
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    if cancelled:
        try:
            worker.result()
        except BaseException:
            pass
        raise asyncio.CancelledError()
    try:
        worker.result()
    except FactoryRuntimeError:
        raise
    except Exception:
        raise FactoryRuntimeError("factory_runtime_uncertain") from None
    # initialize_factory is deliberately NoReturn. An accidental return must
    # never turn a prepared factory ledger into a running legacy application.
    raise FactoryRuntimeError("factory_runtime_uncertain")


@asynccontextmanager
async def lifespan(app: FastAPI, stop_requested: asyncio.Event | None = None, *,
                   _legacy_selected: bool = False):
    with main_writer_guard():
        # Retain the old keyword for callers, but never treat a boolean as
        # authority to skip selection, including when only durable traces remain.
        await _select_startup_runtime()
        async with _legacy_lifespan(app, stop_requested):
            yield


@asynccontextmanager
async def _legacy_lifespan(app: FastAPI, stop_requested: asyncio.Event | None = None):
    init_db()
    app.state.sessions = auth.SessionStore()
    app.state.auth_service = auth.CredentialService(
        auth.load_or_create_credentials(data_dir()), app.state.sessions,
    )
    app.state.login_limiter = auth.LoginRateLimiter()
    app.state.password_change_limiter = auth.LoginRateLimiter()
    app.state.photo_access = None
    app.state.photo_access_limiter = auth.LoginRateLimiter(max_attempts=30)
    if not auth.auth_disabled():
        validated_record = app.state.auth_service.credentials.record()
        validated_credentials = app.state.auth_service.credentials
        def photo_epoch():
            nonlocal validated_record, validated_credentials
            current = app.state.auth_service.credentials
            try:
                # Read only; never create, migrate, reset or chmod credentials.
                record = auth._read_record(current.path)
                if record != validated_record:
                    if record.get("version") != 2:
                        raise ValueError
                    validated_credentials = auth._parse_record(current.path, record)
                    validated_record = record
                verified = validated_credentials
                return hashlib.sha256(b"inky-photo-epoch-v1\0" + verified.salt + verified.digest).hexdigest()
            except (ValueError, OSError):
                raise OSError("Identifiants du cadre indisponibles") from None
        app.state.photo_access = PhotoAccessStore(
            data_dir() / "photo-access", photo_epoch, gate=app.state.auth_service._lock,
        )
        app.state.sessions.principal_validator = app.state.photo_access.valid
    app.state.bus = EventBus()
    app.state.display = DisplayController()
    if stop_requested is not None and stop_requested.is_set():
        app.state.display.begin_shutdown()
    else:
        # Signals and the event loop must remain responsive during driver setup.
        try:
            await asyncio.to_thread(app.state.display.initialize)
        except DisplayUnavailableError:
            if not app.state.display.closing:
                raise
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
    if not app.state.display.closing and app.state.auth_service.credentials.bootstrap_password and not auth.auth_disabled():
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
        if not app.state.display.closing and os.environ.get("INKY_STUDIO_BLUETOOTH") == "1" and not auth.auth_disabled():
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
        if not app.state.display.closing:
            await app.state.scheduler.start()
        yield
    finally:
        app.state.display.begin_shutdown()
        try:
            try:
                if app.state.provisioning is not None:
                    await app.state.provisioning.stop()
            finally:
                await app.state.scheduler.stop()
                if welcome_task is not None:
                    await welcome_task
        finally:
            await asyncio.to_thread(app.state.display.shutdown)


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
    if request.url.path.startswith(("/api/auth/devices", "/api/auth/invitations", "/api/auth/device-session")):
        # Even an extra-field *name* is attacker controlled and can be a secret.
        return JSONResponse(status_code=422, content={"detail": "Requête invalide"},
                            headers={"Cache-Control": "no-store"})
    if request.url.path.startswith(("/api/auth/", "/api/provisioning/")):
        # FastAPI otherwise echoes the supplied secret in the validation input.
        errors = [{key: error[key] for key in ("type", "loc", "msg")} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})
    return await request_validation_exception_handler(request, exc)


app.add_middleware(AuthMiddleware)
app.add_middleware(
    ProofCORSMiddleware,
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
    from inky_web.provisioning.factory_runtime import FactoryRuntimeError

    try:
        asyncio.run(serve(with_https=os.environ.get("INKY_STUDIO_BLUETOOTH") == "1" and not auth.auth_disabled()))
    except (FactoryRuntimeError, FactoryWriterRefused) as exc:
        logging.getLogger(__name__).error("Frame startup stopped: %s", exc.code)
        raise SystemExit(exc.exit_status) from None


async def serve_with_https() -> None:
    """Compatibility entry point for the dual-listener qualification bench."""
    await serve(with_https=True)


async def serve(*, with_https: bool = False) -> None:
    """Own factory admission until all startup workers and listeners drain."""
    with main_writer_guard():
        await _serve_admitted(with_https=with_https)


async def _serve_admitted(*, with_https: bool = False) -> None:
    """One hardware owner and drain policy for both HTTP and HTTP+HTTPS."""
    from contextlib import contextmanager

    from inky_web.provisioning.identity import load_or_create_identity

    class ManagedServer(uvicorn.Server):
        @contextmanager
        def capture_signals(self):
            yield

        async def shutdown(self, sockets=None):
            await super().shutdown(sockets=sockets)
            self._drained = True

        async def serve(self, sockets=None):
            try:
                await super().serve(sockets=sockets)
            except BaseException as exc:
                # Uvicorn uses SystemExit for bind failures. Letting it escape
                # an asyncio task cancels the shared lifespan before its workers
                # can drain. Treat this listener failure as an ordinary error.
                shutdown()
                if isinstance(exc, SystemExit):
                    raise RuntimeError("Frame listener failed to start") from exc
                raise
            finally:
                # Older supported Uvicorn versions return immediately when a
                # signal arrives during startup; drain their opened sockets too.
                if self.started and not getattr(self, "_drained", False):
                    await self.shutdown(sockets=sockets)

    servers = []
    stop_requested = asyncio.Event()
    loop = asyncio.get_running_loop()
    app.state.display = None

    def shutdown():
        # Repeated TERM/INT never escalates to task cancellation or force_exit.
        stop_requested.set()
        if app.state.display is not None:
            app.state.display.begin_shutdown()
        scheduler = getattr(app.state, "scheduler", None)
        if scheduler is not None:
            scheduler.request_stop()
        for server in servers:
            server.should_exit = True

    # Install before identity creation and hardware lifespan initialization.
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown)
    try:
        await _select_startup_runtime()
        if stop_requested.is_set():
            return
        if with_https:
            app.state.frame_identity = await asyncio.to_thread(load_or_create_identity, data_dir() / "provisioning")
            cert, key = await asyncio.to_thread(app.state.frame_identity.materialize_tls_files)
        # This core is reached only after the selector above and under serve's
        # writer guard. Direct ASGI lifespan calls always perform their own check.
        async with _legacy_lifespan(app, stop_requested):
            if stop_requested.is_set():
                return
            # Never cancel an admitted physical operation on a wall-clock timeout.
            # Explicit workers=1 also ignores inherited WEB_CONCURRENCY.
            common = dict(app=app, host="0.0.0.0", lifespan="off", workers=1,
                          timeout_graceful_shutdown=None, proxy_headers=False)
            servers.append(ManagedServer(uvicorn.Config(port=8000, **common)))
            if with_https:
                https = uvicorn.Config(port=8443, ssl_certfile=str(cert), ssl_keyfile=str(key), **common)
                https.load()
                https.ssl = app.state.provisioning.tls_context
                servers.append(ManagedServer(https))
            tasks = [asyncio.create_task(server.serve()) for server in servers]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                shutdown()
                results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    raise result
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)


if __name__ == "__main__":
    run()
