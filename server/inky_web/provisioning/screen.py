"""Private adoption QR rendered by the existing, single display owner."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw
from qrcode.exceptions import DataOverflowError

from inky_web.services import history, photos, settings
from inky_web.welcome import _find_font

RESERVATION = "bluetooth-adoption"


def render_qr(payload: str, width: int, height: int) -> Image.Image:
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise ValueError("Dimensions d’écran invalides")
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=1)
    qr.add_data(payload)
    try:
        qr.make(fit=True)
    except (DataOverflowError, ValueError):
        raise ValueError("QR trop grand pour cet écran") from None
    matrix = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    result = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(result)
    origin = width // 2 + 12
    labels = [(origin, height // 2 - 90, "Inky Studio", _find_font(max(18, width // 28), bold=True))]
    instructions = ("Connecter ce cadre", "Scanne ce QR dans l’app.", "Valable 10 minutes.", "Garde cet écran privé.")
    font = _find_font(max(13, width // 42))
    bounds = [draw.textbbox((0, 0), line, font=font) for line in instructions]
    line_height = max(34, max(bottom - top for _, top, _, bottom in bounds) + 6)
    for offset, line in enumerate(instructions):
        labels.append((origin, height // 2 - 25 + line_height * offset, line, font))
    scale = min(width // 2, height - 40) // matrix.width
    # Preserve the existing roomy composition only when the real glyph bounds
    # fit. Fixed offsets previously clipped text on 104/122-pixel-high panels.
    if scale >= 1 and _labels_fit(draw, labels, (width // 2, 0, width, height)):
        x, y = (width // 2 - matrix.width * scale) // 2, (height - matrix.height * scale) // 2
    else:
        scale, x, y, labels = _compact_layout(draw, matrix.width, width, height)
    # The matrix includes its full four-module quiet zone. Never force scale 1
    # when it cannot fit, crop modules, or use fractional resizing.
    matrix = matrix.resize((matrix.width * scale, matrix.height * scale), Image.Resampling.NEAREST)
    result.paste(matrix, (x, y))
    for x, y, text, font in labels:
        draw.text((x, y), text, fill="black", font=font)
    return result


def _labels_fit(draw, labels, area):
    bounds = [draw.textbbox((x, y), text, font=font) for x, y, text, font in labels]
    if not all(area[0] <= left <= right <= area[2] and area[1] <= top <= bottom <= area[3]
               for left, top, right, bottom in bounds):
        return False
    return all(first[2] <= second[0] or second[2] <= first[0]
               or first[3] <= second[1] or second[3] <= first[1]
               for index, first in enumerate(bounds) for second in bounds[index + 1:])


def _compact_layout(draw, modules: int, width: int, height: int):
    margin, gap = 4, 10
    lines = [("Inky Studio", _find_font(14, bold=True))]
    lines.extend((text, _find_font(12)) for text in ("Scanne ce QR", "dans l’app.", "10 minutes."))
    bounds = [draw.textbbox((0, 0), text, font=font) for text, font in lines]
    text_width = max(right - left for left, top, right, bottom in bounds)
    text_height = sum(bottom - top for left, top, right, bottom in bounds) + 6 * (len(lines) - 1)
    scale = min(height - 2 * margin, width - 2 * margin - gap - text_width) // modules
    if scale >= 1 and text_height <= height - 2 * margin:
        side = modules * scale
        x = (width - side - gap - text_width) // 2
        y = (height - side) // 2
        text_y = (height - text_height) // 2
        labels = []
        for (text, font), (left, top, _, bottom) in zip(lines, bounds, strict=True):
            labels.append((x + side + gap - left, text_y - top, text, font))
            text_y += bottom - top + 6
        return scale, x, y, labels
    # A dense QR or an unusually narrow display may leave no room for labels.
    # Preserve the complete code rather than shrinking modules to fit text.
    scale = min(width, height) // modules
    if scale < 1:
        raise ValueError("QR trop grand pour cet écran")
    side = modules * scale
    return scale, (width - side) // 2, (height - side) // 2, []


def show(display, private_dir: Path, payload: str) -> None:
    with display.operation():
        display.reserve(RESERVATION)
        try:
            image = render_qr(payload, display.spec.width, display.spec.height)
            marker = private_dir / ".adoption-screen"
            with marker.open("wb") as output:
                os.fchmod(output.fileno(), 0o600)
                output.flush()
                os.fsync(output.fileno())
            _sync(private_dir)
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
