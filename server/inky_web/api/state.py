"""Read-only endpoints exposing display + service state."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from inky_web import __version__

router = APIRouter(tags=["state"])


class HealthResponse(BaseModel):
    status: str
    version: str


class DisplayStateResponse(BaseModel):
    model: str
    width: int
    height: int
    colors: int
    color_mode: str
    is_mock: bool


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)


@router.get("/display", response_model=DisplayStateResponse)
async def display_state(request: Request) -> DisplayStateResponse:
    display = request.app.state.display
    info = display.info()
    return DisplayStateResponse(**info)
