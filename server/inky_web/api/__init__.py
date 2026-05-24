"""Aggregated API router."""
from fastapi import APIRouter

from inky_web.api import display, history, photos, queue, settings, state, ws

router = APIRouter()
router.include_router(state.router)
router.include_router(queue.router)
router.include_router(display.router)
router.include_router(history.router)
router.include_router(settings.router)
router.include_router(photos.router)
router.include_router(ws.router)
