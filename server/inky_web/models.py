"""Pydantic schemas shared between API routes, services, and WebSocket payloads."""
from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class ColorMode(StrEnum):
    pimoroni = "pimoroni"
    spectra_palette = "spectra_palette"
    warmth_boost = "warmth_boost"


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
    color_mode: ColorMode = ColorMode.spectra_palette
    change_mode: ChangeMode = ChangeMode.daily
    change_hour: int = Field(default=5, ge=0, le=23)
    change_interval_minutes: int = Field(default=60, ge=1, le=1440)


class DisplayInfo(BaseModel):
    model: str
    width: int
    height: int
    colors: int
    color_mode: ColorMode
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
    color_mode: ColorMode | None = None
    change_mode: ChangeMode | None = None
    change_hour: int | None = Field(default=None, ge=0, le=23)
    change_interval_minutes: int | None = Field(default=None, ge=1, le=1440)
