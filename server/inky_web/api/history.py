"""History endpoint — chronological log of displayed photos."""
from __future__ import annotations

from fastapi import APIRouter, Query

from inky_web.models import HistoryEntry
from inky_web.services import history

router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=list[HistoryEntry])
async def list_history(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[HistoryEntry]:
    return history.list_recent(limit=limit, offset=offset)
