"""Pydantic schemas shared between API routes, services, and WebSocket payloads."""
from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class ChangeMode(StrEnum):
    daily = "daily"
    interval = "interval"
    manual = "manual"


class Photo(BaseModel):
    id: str
    sha256: str
    original_filename: str
    mime: str
    width: int
    height: int
    size_bytes: int
    created_at: float


class QueueEntry(BaseModel):
    id: int
    position: int
    added_at: float
    photo: Photo


class HistoryEntry(BaseModel):
    id: int
    displayed_at: float
    source: Literal["auto", "manual_next", "manual_previous", "recycle", "upload"]
    photo: Photo


class Settings(BaseModel):
    change_mode: ChangeMode = ChangeMode.daily
    change_hour: int = Field(default=5, ge=0, le=23)
    change_interval_minutes: int = Field(default=60, ge=1, le=1440)
    # 0..1 → Pimoroni inky.set_image() saturation (1.0 = faithful, the panel's
    # measured palette). 1..2 → keep set_image at 1.0 and apply a source-image
    # vibrance boost on top for extra punch (gamut-limited by the panel).
    saturation: float = Field(default=1.0, ge=0.0, le=2.0)


class DisplayInfo(BaseModel):
    model: str
    width: int
    height: int
    colors: int
    is_mock: bool


class DisplayState(BaseModel):
    display: DisplayInfo
    current: HistoryEntry | None
    queue_count: int
    next_change_at: float | None


class UploadResponse(BaseModel):
    photo: Photo
    queue_entry: QueueEntry
    already_existed: bool


class ReorderRequest(BaseModel):
    photo_ids: list[str] = Field(min_length=1)


class SettingsUpdate(BaseModel):
    change_mode: ChangeMode | None = None
    change_hour: int | None = Field(default=None, ge=0, le=23)
    change_interval_minutes: int | None = Field(default=None, ge=1, le=1440)
    saturation: float | None = Field(default=None, ge=0.0, le=2.0)


class UpdateStatus(BaseModel):
    """Current installed version vs the latest published GitHub release."""

    current: str
    latest: str | None
    update_available: bool
