"""Factory-only display content; no normal photo/history/settings restoration."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from inky_web.welcome import _find_font

from .screen import _push, render_qr

RESERVATION = "factory-bootstrap"


def render_status(width: int, height: int, *, adopted: bool) -> Image.Image:
    if type(width) is not int or type(height) is not int or min(width, height) < 32:
        raise ValueError("Dimensions d’écran invalides")
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
    def __init__(self, display, directory: Path):
        self.display, self.directory = display, Path(directory)

    def reserve(self) -> None:
        with self.display.operation():
            self.display.reserve(RESERVATION)

    def show_qr(self, payload: str) -> None:
        with self.display.operation():
            self.display.reserve(RESERVATION)
            image = render_qr(payload, self.display.spec.width, self.display.spec.height)
            _push(self.display, self.directory, image)

    def show_status(self, *, adopted: bool) -> None:
        with self.display.operation():
            self.display.reserve(RESERVATION)
            image = render_status(self.display.spec.width, self.display.spec.height, adopted=adopted)
            _push(self.display, self.directory, image)

    def release(self) -> None:
        # The runtime drains all admitted work before releasing ownership; this
        # method starts no refresh and remains valid after begin_shutdown().
        self.display.release(RESERVATION)
