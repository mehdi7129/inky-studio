"""Preview endpoint — applies the full server-side image processing pipeline
and returns the result as a PNG. Used by the browser to show an accurate
preview of what will actually appear on the e-ink display, instead of the
approximate JS dithering.

POST /api/preview?color_mode=spectra_palette
  Body : multipart/form-data  file=<PNG>
  Returns : image/png  (800×480, palette already applied)
"""
from __future__ import annotations

import io
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from PIL import Image

from inky_web.inky.image_processor import process
from inky_web.models import ColorMode

router = APIRouter(prefix="/preview", tags=["preview"])


@router.post("")
async def generate_preview(
    file: Annotated[UploadFile, File()],
    color_mode: ColorMode = Query(default=ColorMode.spectra_palette),
) -> Response:
    """Process an uploaded PNG through the Pillow pipeline and return the result.

    The client sends the resized-but-undithered PNG (same file that would be
    uploaded to /api/queue) and receives back the Pillow-processed version —
    exactly what will be pushed to the e-ink display.
    """
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty payload")
    try:
        with Image.open(io.BytesIO(content)) as raw:
            img = raw.convert("RGB")
    except Exception as exc:
        raise HTTPException(400, f"Cannot decode image: {exc}") from exc

    processed, _ = process(img, color_mode.value)

    buf = io.BytesIO()
    processed.save(buf, format="PNG", optimize=False)
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )
