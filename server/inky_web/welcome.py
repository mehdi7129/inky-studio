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

import ipaddress
import json
import logging
import os
import re
import socket
import tempfile
from pathlib import Path

import qrcode
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
    # Pillow bundles a scalable font: minimal OS images need no system TTF.
    return ImageFont.load_default(size=size)


def _detect_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return socket.gethostname()


def lan_login_payload(url: str, password: str | None) -> str | None:
    """Physical initial-login QR, distinct from Bluetooth adoption credentials.

    This version describes only the existing HTTP/RFC1918/8000 LAN service.
    The caller supplies the recoverable bootstrap password, never a user password.
    Invalid addresses keep the manual welcome screen; no network lookup is made.
    """
    if not isinstance(password, str) or not 1 <= len(password) <= 128:
        return None
    if any(not 0x21 <= ord(char) <= 0x7E for char in password):
        return None
    match = re.fullmatch(r"http://([0-9.]+):8000", url)
    if match is None:
        return None
    try:
        address = ipaddress.IPv4Address(match[1])
    except ipaddress.AddressValueError:
        return None
    private_ranges = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    if not any(address in ipaddress.IPv4Network(network) for network in private_ranges):
        return None
    payload = json.dumps(
        {"v": 1, "p": "lan-login", "url": url, "password": password},
        separators=(",", ":"), ensure_ascii=True,
    )
    return payload if len(payload.encode("utf-8")) <= 512 else None


def _fit_font(draw, text, size, width, *, bold=False, mono=False):
    size = max(1, int(size))
    while True:
        font = _find_font(size, bold=bold, mono=mono)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        if text_width <= width or size == 1:
            return font
        size = max(1, min(size - 1, int(size * width / text_width)))


def _draw_centered(draw, text, y, font, width, fill, *, x=0):
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width, text_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    # Position the actual glyph bounds, including fonts with a nonzero bearing.
    draw.text((x + (width - text_width) // 2 - bbox[0], y - bbox[1]),
              text, font=font, fill=fill)
    return y + text_height


def _login_qr(payload: str, max_size: int) -> Image.Image | None:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                       border=4, box_size=1)
    qr.add_data(payload)
    qr.make(fit=True)
    matrix = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    scale = max_size // matrix.width
    # Small panels retain manual login rather than render an unreadable QR.
    if scale < 3:
        return None
    return matrix.resize((matrix.width * scale, matrix.height * scale),
                         Image.Resampling.NEAREST)


def render_welcome_image(
    width: int,
    height: int,
    *,
    url: str,
    password: str | None,
) -> Image.Image:
    """Bento welcome: a large QR and two readable cards, even without system fonts."""
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)
    margin = max(4, int(min(width, height) * 0.05))
    gap = max(4, int(height * 0.035))
    inner = max(3, int(height * 0.035))
    usable_width = max(1, width - 2 * margin)
    title_font = _fit_font(draw, "Inky Studio", height * 0.115, usable_width, bold=True)
    title_bottom = _draw_centered(draw, "Inky Studio", margin, title_font, width, "black")
    hint_size = max(1, int(height * 0.05))
    footer_y = height - margin - hint_size
    content_top = title_bottom + margin
    content_bottom = footer_y - gap
    content_height = max(1, content_bottom - content_top)
    qr_card_width = int(usable_width * 0.41)
    payload = lan_login_payload(url, password)
    qr = (_login_qr(payload, min(qr_card_width - 2 * inner,
                               max(0, content_height - hint_size - 3 * inner)))
          if payload is not None else None)
    radius = max(4, int(height * 0.045))
    stroke = max(1, int(height * 0.006))
    text_x, text_width = margin, usable_width
    if qr is not None:
        draw.rounded_rectangle((margin, content_top, margin + qr_card_width, content_bottom),
                               radius=radius, outline="black", width=stroke)
        qr_x = margin + (qr_card_width - qr.width) // 2
        qr_y = content_top + inner
        img.paste(qr, (qr_x, qr_y))
        caption = "Scanner dans l'app"
        font = _fit_font(draw, caption, hint_size, qr_card_width - 2 * inner)
        caption_bbox = draw.textbbox((0, 0), caption, font=font)
        caption_height = caption_bbox[3] - caption_bbox[1]
        caption_y = qr_y + qr.height + max(0, (content_bottom - inner - qr_y
                                              - qr.height - caption_height) // 2)
        _draw_centered(draw, caption, caption_y, font, qr_card_width, "black", x=margin)
        text_x = margin + qr_card_width + gap
        text_width = width - margin - text_x

    card_height = (content_height - gap) // 2
    cards = [
        (content_top, "Adresse du cadre", url, height * 0.085),
        (content_top + card_height + gap,
         "Mot de passe initial" if password else "Mot de passe actuel",
         password or "Non consultable", height * 0.095),
    ]
    for top, label, value, value_size in cards:
        bottom = top + card_height
        draw.rounded_rectangle((text_x, top, text_x + text_width, bottom), radius=radius,
                               outline="black", width=stroke)
        label_font = _fit_font(draw, label, height * 0.055, text_width - 2 * inner)
        value_font = _fit_font(draw, value, value_size, text_width - 2 * inner,
                               bold=True, mono=True)
        label_bbox = draw.textbbox((0, 0), label, font=label_font)
        value_bbox = draw.textbbox((0, 0), value, font=value_font)
        label_height = label_bbox[3] - label_bbox[1]
        value_height = value_bbox[3] - value_bbox[1]
        text_gap = max(2, int(height * 0.035))
        y = top + max(inner, (card_height - label_height - value_height - text_gap) // 2)
        y = _draw_centered(draw, label, y, label_font, text_width, "black", x=text_x)
        _draw_centered(draw, value, y + text_gap, value_font, text_width, "black", x=text_x)

    hint = ("Un Wi-Fi commun pour l'iPhone et le cadre" if qr is not None
            else "Ouvre l'adresse dans ton navigateur")
    font = _fit_font(draw, hint, hint_size, usable_width)
    _draw_centered(draw, hint, footer_y, font, width, "black")
    return img


def show_welcome(display: DisplayController | None = None) -> None:
    """Push the welcome screen to the Inky. Creates a fresh display if none provided."""
    owns_display = display is None
    if display is None:
        display = DisplayController()
        display.initialize()
    try:
        _show_welcome(display)
    finally:
        if owns_display:
            display.shutdown()


def _show_welcome(display: DisplayController) -> None:
    display.require_available()
    info = display.info()
    creds = load_or_create_credentials(default_data_dir())
    url = f"http://{_detect_ip()}:8000"

    img = render_welcome_image(
        info["width"],
        info["height"],
        url=url,
        password=creds.bootstrap_password,
    )

    tmp_path = None
    try:
        # The image may contain the initial secret. Create it privately before
        # writing pixels; chmod after save would leave a readable time window.
        with tempfile.NamedTemporaryFile(dir=default_data_dir(), prefix=".welcome-", suffix=".png", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            os.fchmod(tmp.fileno(), 0o600)
            img.save(tmp, format="PNG")
        if display.is_mock:
            debug_path = default_data_dir() / "welcome_preview.png"
            os.replace(tmp_path, debug_path)
            logger.info("[mock] Saved private welcome preview to %s", debug_path)
        else:
            display.display_image(tmp_path)
            logger.info("Welcome screen pushed to display")
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    show_welcome()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
