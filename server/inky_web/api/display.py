"""Display action endpoints: manual next/previous."""
from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import Response
from pydantic import BaseModel

from inky_web.services import scheduler

router = APIRouter(prefix="/display", tags=["display"])


class DisplayFailure(BaseModel):
    code: str
    detail: str


class BusyObservation(BaseModel):
    phase: str
    timeout: float
    outcome: str
    sequence: int
    error_type: str | None = None


class DisplayDiagnostics(BaseModel):
    mode: str
    profile: str | None
    state: str
    is_mock: bool
    error: DisplayFailure | None
    driver: dict[str, str | int | None]
    busy_monitor: str
    observations: list[BusyObservation]


@router.get("/status", response_model=DisplayDiagnostics)
async def display_status(request: Request) -> DisplayDiagnostics:
    return DisplayDiagnostics(**request.app.state.display.status())


@router.post("/next", status_code=status.HTTP_202_ACCEPTED)
async def next_photo(request: Request) -> Response:
    display = request.app.state.display
    bus = request.app.state.bus
    await scheduler.trigger_next(display, bus)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post("/previous", status_code=status.HTTP_202_ACCEPTED)
async def previous_photo(request: Request) -> Response:
    display = request.app.state.display
    bus = request.app.state.bus
    await scheduler.trigger_previous(display, bus)
    return Response(status_code=status.HTTP_202_ACCEPTED)
