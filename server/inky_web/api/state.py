"""Read-only endpoints exposing display + service state."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from inky_web import __version__
from inky_web.models import ColorMode, DisplayInfo, DisplayState
from inky_web.services import history, queue

router = APIRouter(tags=["state"])


class HealthResponse(BaseModel):
    status: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)


@router.get("/display", response_model=DisplayInfo)
async def display_info(request: Request) -> DisplayInfo:
    display = request.app.state.display
    info = display.info()
    return DisplayInfo(
        model=info["model"],
        width=info["width"],
        height=info["height"],
        colors=info["colors"],
        color_mode=ColorMode(info["color_mode"]),
        is_mock=info["is_mock"],
    )


@router.get("/state", response_model=DisplayState)
async def display_state(request: Request) -> DisplayState:
    display = request.app.state.display
    scheduler = request.app.state.scheduler
    info = display.info()
    return DisplayState(
        display=DisplayInfo(
            model=info["model"],
            width=info["width"],
            height=info["height"],
            colors=info["colors"],
            color_mode=ColorMode(info["color_mode"]),
            is_mock=info["is_mock"],
        ),
        current=history.current(),
        queue_count=queue.count(),
        next_change_at=scheduler.next_change_at(),
    )
