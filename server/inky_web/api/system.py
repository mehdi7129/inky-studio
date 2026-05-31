"""System endpoints — check for and apply app updates.

Both routes are protected by the global ``AuthMiddleware`` (they're not in
``auth.PUBLIC_PATHS``). The actual work lives in :mod:`inky_web.services.updater`;
progress is streamed to clients as ``system_update`` WebSocket events.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from inky_web.models import UpdateStatus
from inky_web.services import updater

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/update", response_model=UpdateStatus)
async def update_status(refresh: bool = False) -> UpdateStatus:
    # ?refresh=1 bypasses the ~10 min cache (used by the explicit "check" button)
    # so a freshly published release shows up immediately.
    data = await asyncio.to_thread(updater.get_status, use_cache=not refresh)
    return UpdateStatus(**data)


@router.post("/update", status_code=202)
async def start_update(request: Request) -> dict[str, bool]:
    app = request.app
    if getattr(app.state, "updating", False):
        raise HTTPException(status_code=409, detail="Une mise à jour est déjà en cours")
    app.state.updating = True
    emit = updater.bus_emitter(app.state.bus)

    async def _run() -> None:
        try:
            await updater.perform_update(emit)
        finally:
            # If the update succeeded the service is restarted and this never
            # runs; on failure we clear the flag so the user can retry.
            app.state.updating = False

    asyncio.create_task(_run())
    return {"started": True}
