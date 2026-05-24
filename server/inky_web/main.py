"""Entry point for the Inky Studio FastAPI app."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from inky_web import __version__
from inky_web.api import router as api_router
from inky_web.db import init_db
from inky_web.events import EventBus
from inky_web.inky.display import DisplayController
from inky_web.services.scheduler import Scheduler
from inky_web.services.settings import get as get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

CLIENT_DIST = Path(__file__).resolve().parents[2] / "client" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    app.state.bus = EventBus()
    app.state.display = DisplayController()
    app.state.display.initialize()
    app.state.display.set_color_mode(get_settings().color_mode.value)
    app.state.scheduler = Scheduler(app.state.display, app.state.bus)
    await app.state.scheduler.start()
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
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
