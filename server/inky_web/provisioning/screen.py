"""Private adoption QR rendered by the existing, single display owner."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw

from inky_web.services import history, photos, settings
from inky_web.welcome import _find_font

RESERVATION = "bluetooth-adoption"


def render_qr(payload: str, width: int, height: int) -> Image.Image:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=1)
    qr.add_data(payload)
    qr.make(fit=True)
    matrix = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    # Integer nearest-neighbor modules keep the QR readable on the e-ink panel.
    scale = max(1, min(width // 2, height - 40) // matrix.width)
    matrix = matrix.resize((matrix.width * scale, matrix.height * scale), Image.Resampling.NEAREST)
    result = Image.new("RGB", (width, height), "white")
    x, y = (width // 2 - matrix.width) // 2, (height - matrix.height) // 2
    result.paste(matrix, (x, y))
    draw = ImageDraw.Draw(result)
    origin = width // 2 + 12
    draw.text((origin, height // 2 - 90), "Inky Studio", fill="black", font=_find_font(max(18, width // 28), bold=True))
    for offset, line in enumerate(("Connecter ce cadre", "Scanne ce QR dans l’app.", "Valable 10 minutes.", "Garde cet écran privé.")):
        draw.text((origin, height // 2 - 25 + 34 * offset), line, fill="black", font=_find_font(max(13, width // 42)))
    return result


def show(display, private_dir: Path, payload: str) -> None:
    with display.operation():
        display.reserve(RESERVATION)
        try:
            marker = private_dir / ".adoption-screen"
            with marker.open("wb") as output:
                os.fchmod(output.fileno(), 0o600)
                output.flush()
                os.fsync(output.fileno())
            _sync(private_dir)
            image = render_qr(payload, display.spec.width, display.spec.height)
            _push(display, private_dir, image)
        except BaseException:
            display.release(RESERVATION)
            raise


def restore(display, private_dir: Path) -> None:
    with display.operation():
        try:
            current = history.current()
            path = photos.path_for(current.photo.id) if current else None
            if path is not None and path.is_file():
                display.display_image(path, saturation=settings.get().saturation)
            else:
                image = Image.new("RGB", (display.spec.width, display.spec.height), "white")
                ImageDraw.Draw(image).text((30, 30), "Inky Studio", fill="black", font=_find_font(32, bold=True))
                _push(display, private_dir, image)
            (private_dir / ".adoption-screen").unlink(missing_ok=True)
            _sync(private_dir)
        finally:
            display.release(RESERVATION)


def restore_if_reserved(display, private_dir: Path) -> None:
    with display.operation():
        if display.reserved:
            restore(display, private_dir)


def _sync(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _push(display, private_dir, image):
    path = None
    try:
        with tempfile.NamedTemporaryFile(dir=private_dir, prefix=".adoption-", suffix=".png", delete=False) as file:
            path = Path(file.name)
            os.fchmod(file.fileno(), 0o600)
            image.save(file, format="PNG")
        display.display_image(path, saturation=0)
    finally:
        if path is not None:
            path.unlink(missing_ok=True)
