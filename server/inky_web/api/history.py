"""History endpoint — chronological log of displayed photos."""
from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response

from inky_web.models import HistoryEntry
from inky_web.services import history

router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=list[HistoryEntry])
async def list_history(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[HistoryEntry]:
    return history.list_recent(limit=limit, offset=offset)


@router.delete("", status_code=204)
async def clear_history(request: Request) -> Response:
    """Delete every history log entry (does not touch photo files or the queue)."""
    n = history.clear()
    request.app.state.bus.broadcast("history_changed", {"cleared": n})
    return Response(status_code=204)


@router.delete("/{history_id}", status_code=204)
async def delete_history_entry(history_id: int, request: Request) -> Response:
    """Delete a single history log entry."""
    history.delete(history_id)
    request.app.state.bus.broadcast("history_changed", {"deleted": history_id})
    return Response(status_code=204)
