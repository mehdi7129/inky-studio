"""Entry point for the Inky Studio FastAPI app."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from inky_web import __version__, auth
from inky_web.api import router as api_router
from inky_web.db import data_dir, init_db
from inky_web.events import EventBus
from inky_web.inky.display import DisplayController
from inky_web.services.scheduler import Scheduler
from inky_web.services.settings import get as get_settings

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
    app.state.bus = EventBus()
    app.state.display = DisplayController()
    app.state.display.initialize()
    app.state.display.set_color_mode(get_settings().color_mode.value)
    app.state.scheduler = Scheduler(app.state.display, app.state.bus)
    await app.state.scheduler.start()

    credentials_existed = (data_dir() / "credentials.json").is_file()
    app.state.credentials = auth.load_or_create_credentials(data_dir())
    app.state.sessions = auth.SessionStore()
    app.state.login_limiter = auth.LoginRateLimiter()
    if not auth.auth_disabled():
        logger = logging.getLogger(__name__)
        logger.info(
            "Auth enabled. Password (also persisted in %s) : %s",
            app.state.credentials.path,
            app.state.credentials.password,
        )

    # On first boot (credentials freshly generated AND nothing ever displayed),
    # push the welcome screen so the user sees the URL + password on the Inky.
    if not credentials_existed and not auth.auth_disabled():
        try:
            from inky_web import history as _history_module  # noqa: F401
        except ImportError:
            pass
        # No history yet → show welcome. Run in a thread so lifespan stays snappy.
        import asyncio

        from inky_web.services import history as history_service
        from inky_web.welcome import show_welcome

        if history_service.count() == 0:
            logging.getLogger(__name__).info(
                "First boot detected — pushing welcome screen to the Inky"
            )
            asyncio.create_task(asyncio.to_thread(show_welcome, app.state.display))

    try:
        yield
    finally:
        await app.state.scheduler.stop()
        app.state.display.shutdown()


app = FastAPI(
    title="Inky Studio",
    version=__version__,
    description="Web UI for the Inky e-ink photo frame",
    lifespan=lifespan,
)

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

if CLIENT_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=CLIENT_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str) -> FileResponse:
        candidate = CLIENT_DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(CLIENT_DIST / "index.html")


def run() -> None:
    uvicorn.run(
        "inky_web.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    run()
