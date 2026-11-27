"""Queue endpoints: list, upload (add), delete, reorder."""
from __future__ import annotations

import hashlib
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Header, HTTPException, Request, UploadFile

from inky_web.db import connection
from inky_web.models import QueueEntry, ReorderRequest, UploadResponse
from inky_web.services import photos, queue
from inky_web.services.photos import PhotoValidationError

router = APIRouter(prefix="/queue", tags=["queue"])
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # Fits a full-colour 1600×1200 PNG.


@router.get("", response_model=list[QueueEntry])
async def list_queue() -> list[QueueEntry]:
    return queue.list_all()


@router.post("", response_model=UploadResponse, status_code=201)
async def add_to_queue(
    request: Request,
    file: Annotated[UploadFile, File()],
    idempotency_key: Annotated[str | None, Header(max_length=36)] = None,
) -> UploadResponse:
    """Upload a full-colour PNG already resized and cropped in the browser.

    The image dimensions must match the connected display exactly — the server
    refuses unconverted uploads. The official display driver applies the panel
    palette when displaying it; uploaded PNGs are limited to 10 MiB.
    """
    display = request.app.state.display
    bus = request.app.state.bus
    if idempotency_key is not None:
        try:
            if str(UUID(idempotency_key)) != idempotency_key:
                raise ValueError
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid upload identifier") from exc

    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Photo exceeds the 10 MiB upload limit")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Photo exceeds the 10 MiB upload limit")
    sha = hashlib.sha256(content).hexdigest()
    try:
        with photos.storage_transaction() as (conn, created):
            if idempotency_key is not None:
                receipt = conn.execute(
                    "SELECT sha256, response FROM upload_receipts WHERE idempotency_key = ?", (idempotency_key,)
                ).fetchone()
                if receipt is not None:
                    if receipt["sha256"] != sha:
                        raise HTTPException(status_code=409, detail="Upload identifier already used")
                    return UploadResponse.model_validate_json(receipt["response"])
            display.require_available()
            info = display.info()
            dimensions = photos.prepare(content, (info["width"], info["height"]))
            photo, already_existed = photos.save_prepared(
                conn, created, content=content, sha=sha,
                original_filename=file.filename or "upload.png", dimensions=dimensions,
            )
            entry = queue.add_in_transaction(photo.id, conn)
            result = UploadResponse(photo=photo, queue_entry=entry, already_existed=already_existed)
            if idempotency_key is not None:
                conn.execute("INSERT INTO upload_receipts VALUES (?, ?, ?)",
                             (idempotency_key, sha, result.model_dump_json()))
    except PhotoValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    bus.broadcast("photo_uploaded", {"photo_id": photo.id, "already_existed": already_existed})
    bus.broadcast("queue_updated", {"action": "added", "photo_id": photo.id})
    return result


@router.get("/uploads/{upload_id}")
async def upload_receipt(upload_id: UUID) -> dict:
    with connection() as conn:
        row = conn.execute("SELECT response FROM upload_receipts WHERE idempotency_key = ?",
                           (str(upload_id),)).fetchone()
    return {"receipt": UploadResponse.model_validate_json(row["response"]) if row else None}


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
