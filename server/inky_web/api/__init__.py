"""Aggregated API router."""
from fastapi import APIRouter

from inky_web.api import state

router = APIRouter()
router.include_router(state.router)
