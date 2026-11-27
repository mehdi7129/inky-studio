"""Factory-only display content; no normal photo/history/settings restoration."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw
from qrcode.exceptions import DataOverflowError

from inky_web.welcome import _find_font

from .factory import FactoryRecoveryRequired
from .identity import validate_token
from .screen import _push
from .screen import render_qr as render_compact_qr

RESERVATION = "factory-bootstrap"


def _large_panel(width: int, height: int) -> bool:
    return width >= 800 and height >= 480


def _text_bounds(draw, text, font):
    return draw.textbbox((0, 0), text, font=font)


def _paint_text(draw, text, x, y, font):
    left, top, _, bottom = _text_bounds(draw, text, font)
    draw.text((x - left, y - top), text, font=font, fill="black")
    return y + bottom - top


def _wrap(draw, text, font, width):
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}" if line else word
            left, _, right, _ = _text_bounds(draw, candidate, font)
            if right - left > width and line:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            left, _, right, _ = _text_bounds(draw, line, font)
            if right - left > width:
                raise ValueError("Texte trop grand pour cet écran")
            lines.append(line)
    return lines


def _card_text(draw, bounds, title, body, scale, *, prominent=False):
    left, top, right, bottom = bounds
    inset = round(20 * scale)
    width = right - left - 2 * inset
    # Keep full copy and real glyph bearings even with the bundled Pillow font.
    for adjustment in (1.0, 0.95, 0.9):
        title_font = _find_font(round((40 if prominent else 32) * scale * adjustment), bold=True)
        body_font = _find_font(round(26 * scale * adjustment))
        title_lines = _wrap(draw, title, title_font, width)
        body_lines = _wrap(draw, body, body_font, width)
        gap, line_gap = round(14 * scale), round(5 * scale)
        labels = [(line, title_font) for line in title_lines]
        labels.extend((line, body_font) for line in body_lines)
        heights = [box[3] - box[1] for text, font in labels
                   for box in [_text_bounds(draw, text, font)]]
        total = sum(heights) + line_gap * (len(labels) - 2) + gap
        if total <= bottom - top - 2 * inset:
            y = top + (bottom - top - total) // 2
            for index, (text, font) in enumerate(labels):
                y = _paint_text(draw, text, left + inset, y, font)
                y += gap if index == len(title_lines) - 1 else line_gap
            return
    raise ValueError("Texte trop grand pour cet écran")


def _canvas(width, height):
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    scale = min(width / 800, height / 480)
    margin, gap = round(24 * scale), round(16 * scale)
    title_bottom = _paint_text(draw, "Inky Studio", margin, margin,
                               _find_font(round(44 * scale), bold=True))
    content_top = title_bottom + round(24 * scale)
    return image, draw, scale, margin, gap, content_top


def render_qr(payload: str, width: int, height: int) -> Image.Image:
    """Factory Bento for large panels; preserve the existing compact renderer."""
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise ValueError("Dimensions d’écran invalides")
    if not _large_panel(width, height):
        return render_compact_qr(payload, width, height)
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=1)
    qr.add_data(payload)
    try:
        qr.make(fit=True)
    except (DataOverflowError, ValueError):
        raise ValueError("QR trop grand pour cet écran") from None
    matrix = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    image, draw, scale, margin, gap, top = _canvas(width, height)
    bottom = height - margin
    qr_right = margin + round(340 * scale)
    qr_card = (margin, top, qr_right, bottom)
    text_left = qr_right + gap
    middle = top + (bottom - top - gap) // 2
    cards = [qr_card, (text_left, top, width - margin, middle),
             (text_left, middle + gap, width - margin, bottom)]
    for bounds in cards:
        draw.rounded_rectangle(bounds, radius=round(24 * scale), outline="black",
                               width=max(1, round(2 * scale)))
    inset = round(16 * scale)
    pixels = min(qr_right - margin - 2 * inset, bottom - top - 2 * inset) // matrix.width
    if pixels < 1:
        raise ValueError("QR trop grand pour cet écran")
    side = matrix.width * pixels
    matrix = matrix.resize((side, side), Image.Resampling.NEAREST)
    image.paste(matrix, (margin + (qr_right - margin - side) // 2,
                         top + (bottom - top - side) // 2))
    _card_text(draw, cards[1], "Connecter\nmon cadre.", "Scannez ce QR avec l’app.",
               scale, prominent=True)
    _card_text(draw, cards[2], "Le Wi-Fi ensuite.",
               "Choisissez votre réseau dans l’app, après le scan.", scale)
    return image


def _render_bento_status(width: int, height: int, *, adopted: bool) -> Image.Image:
    image, draw, scale, margin, _, top = _canvas(width, height)
    bounds = (margin, top, width - margin, height - margin)
    draw.rounded_rectangle(bounds, radius=round(24 * scale), outline="black",
                           width=max(1, round(2 * scale)))
    title, body = (("Cadre associé.", "La suite se passe dans l’app.") if adopted else
                   ("QR code expiré.", "Redémarrez le cadre pour réessayer."))
    _card_text(draw, bounds, title, body, scale, prominent=True)
    return image


def render_status(width: int, height: int, *, adopted: bool) -> Image.Image:
    if type(width) is not int or type(height) is not int or min(width, height) < 32:
        raise ValueError("Dimensions d’écran invalides")
    if _large_panel(width, height):
        return _render_bento_status(width, height, adopted=adopted)
    lines = (["Inky Studio", "Cadre associé", "Préparation du cadre", "en attente."] if adopted
             else ["Inky Studio", "Association en attente", "QR expiré.", "Redémarre le cadre."])
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    for size in range(min(32, height // 5), 7, -1):
        font = _find_font(size)
        boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
        total = sum(bottom - top for left, top, right, bottom in boxes) + 6 * (len(lines) - 1)
        if total <= height - 8 and max(right - left for left, top, right, bottom in boxes) <= width - 8:
            y = (height - total) // 2
            for line, (left, top, right, bottom) in zip(lines, boxes, strict=True):
                draw.text(((width - (right - left)) // 2 - left, y - top), line, font=font, fill="black")
                y += bottom - top + 6
            return image
    raise ValueError("Texte trop grand pour cet écran")


class BootstrapScreen:
    def __init__(self, display, directory: Path, *, verify_epoch: Callable[[], str] | None = None):
        self.display, self.directory = display, Path(directory)
        self.verify_epoch = verify_epoch

    def _check_admission(self) -> None:
        # Standalone legacy renderers keep their existing default. The phase A
        # runtime explicitly supplies the checked canonical epoch callback.
        if self.verify_epoch is not None:
            try:
                epoch = self.verify_epoch()
                if type(epoch) is not str:
                    raise ValueError()
                validate_token(epoch)
            except Exception:
                raise FactoryRecoveryRequired() from None

    def reserve(self) -> None:
        with self.display.operation():
            self._check_admission()
            self.display.reserve(RESERVATION)

    def show_qr(self, payload: str) -> None:
        with self.display.operation():
            self._check_admission()
            self.display.reserve(RESERVATION)
            image = render_qr(payload, self.display.spec.width, self.display.spec.height)
            self._check_admission()
            _push(self.display, self.directory, image)

    def show_status(self, *, adopted: bool) -> None:
        with self.display.operation():
            self._check_admission()
            self.display.reserve(RESERVATION)
            image = render_status(self.display.spec.width, self.display.spec.height, adopted=adopted)
            self._check_admission()
            _push(self.display, self.directory, image)

    def release(self) -> None:
        # The runtime drains all admitted work before releasing ownership; this
        # method starts no refresh and remains valid after begin_shutdown().
        self.display.release(RESERVATION)
