"""Settings endpoints — read and update typed configuration."""
from __future__ import annotations

from fastapi import APIRouter, Request

from inky_web.models import Settings, SettingsUpdate
from inky_web.services import settings as settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=Settings)
async def get_settings() -> Settings:
    return settings_service.get()


@router.post("", response_model=Settings)
async def update_settings(request: Request, patch: SettingsUpdate) -> Settings:
    new = settings_service.update(patch)
    display = request.app.state.display
    display.set_color_mode(new.color_mode.value)
    request.app.state.bus.broadcast("settings_changed", new.model_dump(mode="json"))
    return new
