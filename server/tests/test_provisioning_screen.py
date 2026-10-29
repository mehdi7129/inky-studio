"""Pixel and layout checks; synthetic QR values, no camera or physical display."""
import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
import qrcode
from PIL import Image, ImageChops, ImageDraw

from inky_web.provisioning import screen

# Unique resolutions represented by the inky 2.3.0 driver catalogue in
# test_display.py. Colour variants share this black-and-white layout.
PANEL_SIZES = [(212, 104), (250, 122), (400, 300), (600, 400),
               (600, 448), (640, 400), (800, 480), (1600, 1200)]
PAYLOAD = json.dumps({"v": 1, "id": "12345678-1234-4234-8234-123456789abc",
                      "k": "0123456789abcdef" * 4, "t": "fedcba9876543210" * 4}, separators=(",", ":"))


@pytest.fixture
def painted(monkeypatch):
    """Observe actual paste and glyph bounds, not the renderer's layout helpers."""
    qr_areas, text_areas = [], []
    original_paste = Image.Image.paste
    original_text = ImageDraw.ImageDraw.text

    def paste(image, source, box=None, mask=None):
        if isinstance(source, Image.Image) and isinstance(box, tuple) and len(box) == 2:
            x, y = box
            qr_areas.append((x, y, x + source.width, y + source.height))
        return original_paste(image, source, box, mask)

    def text(draw, xy, value, *args, **kwargs):
        text_areas.append((value, draw.textbbox(xy, value, font=kwargs.get("font"))))
        return original_text(draw, xy, value, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "paste", paste)
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", text)
    return qr_areas, text_areas


def matrix_for(payload):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=1)
    qr.add_data(payload)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


@pytest.mark.parametrize(("width", "height"), PANEL_SIZES)
def test_catalogue_preserves_every_qr_module_quiet_zone_and_visible_label(width, height, painted):
    expected = matrix_for(PAYLOAD)
    image = screen.render_qr(PAYLOAD, width, height)
    qr_areas, text_areas = painted
    assert image.size == (width, height)
    assert len(qr_areas) == 1
    left, top, right, bottom = qr_areas[0]
    assert 0 <= left < right <= width and 0 <= top < bottom <= height
    assert right - left == bottom - top
    assert (right - left) % expected.width == 0
    scale = (right - left) // expected.width
    assert scale >= 1
    code = image.crop(qr_areas[0])
    expected = expected.resize(code.size, Image.Resampling.NEAREST)
    assert ImageChops.difference(code, expected).getbbox() is None
    quiet = 4 * scale
    for area in ((0, 0, code.width, quiet), (0, code.height - quiet, code.width, code.height),
                 (0, 0, quiet, code.height), (code.width - quiet, 0, code.width, code.height)):
        assert code.crop(area).getextrema() == ((255, 255),) * 3
    assert text_areas  # Every supported panel has space for short useful labels.
    for text, (x0, y0, x1, y1) in text_areas:
        assert 0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height, text
        assert x1 <= left or x0 >= right or y1 <= top or y0 >= bottom, text
    for index, (_, first) in enumerate(text_areas):
        for _, second in text_areas[index + 1:]:
            assert first[2] <= second[0] or second[2] <= first[0] or first[3] <= second[1] or second[3] <= first[1]


def test_large_panel_keeps_original_composition(painted):
    raw = matrix_for(PAYLOAD)
    screen.render_qr(PAYLOAD, 800, 480)
    qr_areas, text_areas = painted
    side = raw.width * (400 // raw.width)
    assert qr_areas == [((400 - side) // 2, (480 - side) // 2,
                         (400 - side) // 2 + side, (480 - side) // 2 + side)]
    assert [text for text, _ in text_areas] == [
        "Inky Studio", "Connecter ce cadre", "Scanne ce QR dans l’app.",
        "Valable 10 minutes.", "Garde cet écran privé.",
    ]


def test_code_uses_full_panel_when_labels_do_not_fit(painted):
    raw = matrix_for(PAYLOAD)
    image = screen.render_qr(PAYLOAD, raw.width, raw.height)
    assert painted == ([(0, 0, raw.width, raw.height)], [])
    assert ImageChops.difference(image, raw).getbbox() is None


@pytest.mark.parametrize(("width", "height"), [(20, 20), (212, 30), (30, 122)])
def test_impossible_qr_is_refused_before_any_pixels_are_painted(width, height, painted):
    with pytest.raises(ValueError, match="^QR trop grand pour cet écran$"):
        screen.render_qr(PAYLOAD, width, height)
    assert painted == ([], [])


@pytest.mark.parametrize(("width", "height"), [(0, 122), (212, -1), (True, 122), (212, 1.5)])
def test_invalid_dimensions_are_refused(width, height):
    with pytest.raises(ValueError, match="^Dimensions d’écran invalides$"):
        screen.render_qr(PAYLOAD, width, height)


def test_oversized_payload_has_a_fixed_error_without_payload(painted):
    with pytest.raises(ValueError, match="^QR trop grand pour cet écran$"):
        screen.render_qr("synthetic-overflow" * 1000, 800, 480)
    assert painted == ([], [])


def test_unrenderable_qr_is_never_sent_to_display_or_journaled(tmp_path):
    events = []
    display = SimpleNamespace(spec=SimpleNamespace(width=20, height=20), operation=nullcontext,
                              reserve=lambda value: events.append(("reserve", value)),
                              release=lambda value: events.append(("release", value)),
                              display_image=lambda *args, **kwargs: pytest.fail("Partial QR must never be displayed"))
    with pytest.raises(ValueError, match="^QR trop grand pour cet écran$"):
        screen.show(display, tmp_path, PAYLOAD)
    assert events == [("reserve", screen.RESERVATION), ("release", screen.RESERVATION)]
    assert not (tmp_path / ".adoption-screen").exists()
