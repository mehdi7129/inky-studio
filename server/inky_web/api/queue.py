"""Queue endpoints: list, upload (add), delete, reorder."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from inky_web.models import QueueEntry, ReorderRequest, UploadResponse
from inky_web.services import photos, queue
from inky_web.services.photos import PhotoValidationError

router = APIRouter(prefix="/queue", tags=["queue"])


@router.get("", response_model=list[QueueEntry])
async def list_queue() -> list[QueueEntry]:
    return queue.list_all()


@router.post("", response_model=UploadResponse, status_code=201)
async def add_to_queue(
    request: Request,
    file: Annotated[UploadFile, File()],
) -> UploadResponse:
    """Upload a PNG that has already been resized + palette-applied in the browser.

    The image dimensions must match the connected display exactly — the server
    refuses unconverted uploads. This is the contract that lets the Pi store
    only ~200 KB per photo instead of multi-megabyte originals.
    """
    display = request.app.state.display
    bus = request.app.state.bus
    info = display.info()
    expected_size = (info["width"], info["height"])

    content = await file.read()
    try:
        photo, already_existed = photos.save(
            content=content,
            original_filename=file.filename or "upload.png",
            expected_size=expected_size,
        )
    except PhotoValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    entry = queue.add(photo.id)
    bus.broadcast("photo_uploaded", {"photo_id": photo.id, "already_existed": already_existed})
    bus.broadcast("queue_updated", {"action": "added", "photo_id": photo.id})
    return UploadResponse(photo=photo, queue_entry=entry, already_existed=already_existed)


@router.delete("/{photo_id}", status_code=204)
async def remove_from_queue(request: Request, photo_id: str) -> None:
    removed = queue.remove(photo_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Not in queue")
    request.app.state.bus.broadcast("queue_updated", {"action": "removed", "photo_id": photo_id})


@router.post("/reorder", response_model=list[QueueEntry])
async def reorder_queue(request: Request, payload: ReorderRequest) -> list[QueueEntry]:
    new_order = queue.reorder(payload.photo_ids)
    request.app.state.bus.broadcast("queue_updated", {"action": "reordered"})
    return new_order
