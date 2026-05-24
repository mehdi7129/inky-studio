"""Welcome screen — first-run and on-demand display of the URL + password.

Renders a large, readable PIL image on the connected Inky display showing:

    Inky Studio
    http://<ip>:8000
    Password: abcDEFG123
    (instructions)

Triggered automatically by the installer (``inky-studio welcome``) and on
first boot if the credentials file was just created. Reuses the same
``DisplayController`` abstraction as the rest of the app — if no real
display is connected (mac dev), it logs the image bytes instead.
"""
from __future__ import annotations

import logging
import socket
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from inky_web.auth import load_or_create_credentials
from inky_web.db import data_dir as default_data_dir
from inky_web.inky.display import DisplayController

logger = logging.getLogger(__name__)

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",  # macOS dev fallback
]


def _find_font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.ImageFont:
    candidates = []
    if mono and bold:
        candidates.append("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf")
    elif mono:
        candidates.append("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")
    elif bold:
        candidates.append("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    else:
        candidates.append("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    candidates.extend(FONT_CANDIDATES)

    for path in candidates:
        if Path(path).is_file():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _detect_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return socket.gethostname()


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    font: ImageFont.ImageFont,
    width: int,
    fill: str | tuple[int, int, int],
) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    draw.text(((width - text_width) // 2, y), text, font=font, fill=fill)
    return y + text_height


def render_welcome_image(
    width: int,
    height: int,
    *,
    url: str,
    password: str,
) -> Image.Image:
    """Render the welcome PIL image at the given dimensions. Pure function."""
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)

    title_font = _find_font(int(height * 0.11), bold=True)
    url_font = _find_font(int(height * 0.095), bold=True, mono=True)
    label_font = _find_font(int(height * 0.06))
    password_font = _find_font(int(height * 0.085), bold=True, mono=True)
    hint_font = _find_font(int(height * 0.05))

    # Title
    y = int(height * 0.04)
    y = _draw_centered(draw, "Inky Studio", y, title_font, width, "black")

    # Separator
    y += int(height * 0.02)
    draw.line([(int(width * 0.1), y), (int(width * 0.9), y)], fill="black", width=2)

    # URL
    y += int(height * 0.04)
    y = _draw_centered(draw, url, y, url_font, width, (32, 64, 184))  # Spectra-friendly blue

    # Password block
    y += int(height * 0.06)
    y = _draw_centered(draw, "Mot de passe", y, label_font, width, "black")
    y += int(height * 0.01)
    y = _draw_centered(draw, password, y, password_font, width, (160, 32, 32))  # Spectra-friendly red

    # Separator + hint
    y += int(height * 0.05)
    draw.line(
        [(int(width * 0.15), y), (int(width * 0.85), y)],
        fill="gray",
        width=1,
    )
    y += int(height * 0.025)
    _draw_centered(draw, "Ouvre l'URL dans ton navigateur", y, hint_font, width, "black")
    return img


def show_welcome(display: DisplayController | None = None) -> None:
    """Push the welcome screen to the Inky. Creates a fresh display if none provided."""
    owns_display = display is None
    if display is None:
        display = DisplayController()
        display.initialize()

    info = display.info()
    creds = load_or_create_credentials(default_data_dir())
    url = f"http://{_detect_ip()}:8000"

    img = render_welcome_image(
        info["width"],
        info["height"],
        url=url,
        password=creds.password,
    )

    if display.is_mock:
        debug_path = default_data_dir() / "welcome_preview.png"
        img.save(debug_path)
        logger.info("[mock] Saved welcome preview to %s — would push to display", debug_path)
    else:
        tmp_path = default_data_dir() / "_welcome_tmp.png"
        img.save(tmp_path)
        try:
            display.display_image(tmp_path)
            logger.info("Welcome screen pushed to display")
        finally:
            tmp_path.unlink(missing_ok=True)

    if owns_display:
        display.shutdown()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    show_welcome()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
