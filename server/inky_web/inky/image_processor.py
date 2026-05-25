"""Server-side image processing pipeline — mirrors the quality of inky-photo-frame v2.0.

The browser only resizes/crops the image (fast, lossless). All colour-science
work (palette quantisation + dithering) happens here with Pillow's C-accelerated
implementation, which produces far better results than the JS dithering used for
the in-browser preview.

Three modes (matching v2.0):
  pimoroni        — no pre-processing; Inky library applies its own quantisation
                    at saturation=0.5 (official Pimoroni default)
  spectra_palette — boost contrast+saturation then quantise to the calibrated
                    6-colour palette using Floyd-Steinberg; Inky receives the
                    already-quantised "P" mode image and skips its own pass
  warmth_boost    — warm-tone channel adjustments first, then spectra_palette path
"""
from __future__ import annotations

import logging
from PIL import Image, ImageEnhance

logger = logging.getLogger(__name__)

# Calibrated Spectra 6-colour palette (RGB, measured on sRGB monitor vs real display).
# These are the ACTUAL colours the e-ink panel can produce.
SPECTRA_PALETTE = [
    (0x00, 0x00, 0x00),  # black
    (0xFF, 0xFF, 0xFF),  # white
    (0xA0, 0x20, 0x20),  # red   — darker than #FF0000
    (0xF0, 0xE0, 0x50),  # yellow — warmer than #FFFF00
    (0x60, 0x80, 0x50),  # green  — muted, cyan-shifted
    (0x50, 0x80, 0xB8),  # blue   — lighter/cyan
]

WARMTH_BOOST = {
    "red_boost": 1.15,
    "green_reduce": 0.92,
    "blue_reduce": 0.75,
    "brightness": 1.12,
}


def _make_spectra_palette_image() -> Image.Image:
    """Return a 1×1 'P'-mode image carrying only the Spectra 6 palette entries."""
    flat: list[int] = []
    for r, g, b in SPECTRA_PALETTE:
        flat += [r, g, b]
    flat += [0, 0, 0] * (256 - len(SPECTRA_PALETTE))  # Pillow needs 256 entries
    p_img = Image.new("P", (1, 1))
    p_img.putpalette(flat)
    return p_img


_SPECTRA_PALETTE_IMAGE: Image.Image | None = None


def _get_palette_image() -> Image.Image:
    global _SPECTRA_PALETTE_IMAGE
    if _SPECTRA_PALETTE_IMAGE is None:
        _SPECTRA_PALETTE_IMAGE = _make_spectra_palette_image()
    return _SPECTRA_PALETTE_IMAGE


def _quantise_to_spectra(img: Image.Image) -> Image.Image:
    """Apply Pillow Floyd-Steinberg quantisation to the Spectra 6-colour palette.

    Returns an RGB image (not P-mode) so it can be passed straight to
    ``inky.set_image()``.  The Inky library detects mode != "P" and runs its
    own blend pass, but since the image already contains ONLY the 6 palette
    colours, the blend is a no-op and the result is identical.
    """
    q = img.quantize(palette=_get_palette_image(), dither=Image.Dither.FLOYDSTEINBERG)
    return q.convert("RGB")


def _apply_spectra(img: Image.Image) -> Image.Image:
    """Boost contrast+saturation, then quantise to Spectra 6 palette."""
    img = ImageEnhance.Contrast(img).enhance(1.2)
    img = ImageEnhance.Color(img).enhance(1.3)
    return _quantise_to_spectra(img)


def _apply_warmth(img: Image.Image) -> Image.Image:
    """Warm-tone channel boost, then Spectra quantisation."""
    img = ImageEnhance.Brightness(img).enhance(WARMTH_BOOST["brightness"])
    r, g, b = img.split()
    r = ImageEnhance.Brightness(r).enhance(WARMTH_BOOST["red_boost"])
    g = ImageEnhance.Brightness(g).enhance(WARMTH_BOOST["green_reduce"])
    b = ImageEnhance.Brightness(b).enhance(WARMTH_BOOST["blue_reduce"])
    img = Image.merge("RGB", (r, g, b))
    return _quantise_to_spectra(img)


def process(img: Image.Image, color_mode: str) -> tuple[Image.Image, float]:
    """Apply colour-mode processing to an RGB image.

    Returns ``(processed_image, saturation_hint)`` where ``saturation_hint``
    is the value to pass to ``inky.set_image(img, saturation=...)``:
      - 0.5  for pimoroni mode (Inky handles everything)
      - 1.0  for the Spectra modes (we already quantised; pass through as-is)
    """
    if img.mode != "RGB":
        img = img.convert("RGB")

    if color_mode == "spectra_palette":
        logger.info("Applying spectra_palette (Pillow Floyd-Steinberg + calibrated palette)")
        return _apply_spectra(img), 1.0

    if color_mode == "warmth_boost":
        logger.info("Applying warmth_boost (warmth adjustments + Spectra palette)")
        return _apply_warmth(img), 1.0

    # pimoroni / unknown — let Inky library handle quantisation at saturation=0.5
    logger.info("Applying pimoroni mode (Inky default saturation=0.5)")
    return img, 0.5
