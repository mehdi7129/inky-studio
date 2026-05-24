"""Photo file serving — used by the frontend to render thumbnails/previews."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from inky_web.services.photos import find_by_id, path_for

router = APIRouter(prefix="/photos", tags=["photos"])


@router.get("/{photo_id}")
async def get_photo_file(photo_id: str) -> FileResponse:
    photo = find_by_id(photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Unknown photo")
    path = path_for(photo_id)
    if not path.exists():
        raise HTTPException(status_code=410, detail="Photo file missing on disk")
    return FileResponse(path, media_type=photo.mime, filename=photo.original_filename)
