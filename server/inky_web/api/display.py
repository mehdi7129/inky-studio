"""Display action endpoints: manual next/previous."""
from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import Response

from inky_web.services import scheduler

router = APIRouter(prefix="/display", tags=["display"])


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
