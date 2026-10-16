"""Pixel/layout and single-owner checks; no physical panel/camera proof."""
from pathlib import Path

import pytest
import qrcode
from PIL import Image, ImageChops, ImageDraw, ImageFont

from inky_web.provisioning import bootstrap_screen, bootstrap_wire, screen

from .test_bootstrap_runtime import FakeDisplay

PANEL_SIZES = [(212, 104), (250, 122), (400, 300), (600, 400),
               (600, 448), (640, 400), (800, 480), (1600, 960), (1600, 1200)]
PAYLOAD = bootstrap_wire.encode_qr("00000000-0000-4000-8000-000000000001", "1" * 64, "a" * 64)


@pytest.fixture
def painted(monkeypatch):
    qr_areas, text_areas = [], []
    original_paste, original_text = Image.Image.paste, ImageDraw.ImageDraw.text

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


@pytest.mark.parametrize(("width", "height"), PANEL_SIZES)
def test_bootstrap_dense_qr_keeps_integer_modules_and_quiet_zone(width, height, painted):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=1)
    qr.add_data(PAYLOAD)
    qr.make(fit=True)
    expected = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    image = bootstrap_screen.render_qr(PAYLOAD, width, height)
    qr_areas, text_areas = painted
    assert len(qr_areas) == 1
    area = qr_areas[0]
    assert 0 <= area[0] < area[2] <= width and 0 <= area[1] < area[3] <= height
    side = area[2] - area[0]
    assert side == area[3] - area[1] and side % expected.width == 0
    resized = expected.resize((side, side), Image.Resampling.NEAREST)
    assert ImageChops.difference(image.crop(area), resized).getbbox() is None
    for text, bounds in text_areas:
        assert 0 <= bounds[0] < bounds[2] <= width and 0 <= bounds[1] < bounds[3] <= height, text
        assert bounds[2] <= area[0] or area[2] <= bounds[0] or bounds[3] <= area[1] or area[3] <= bounds[1]


@pytest.mark.parametrize(("width", "height"), [(800, 480), (1600, 960), (1600, 1200)])
@pytest.mark.parametrize("bundled_font", [False, True])
def test_large_factory_bento_keeps_readable_copy_inside_separate_cards(
    width, height, bundled_font, painted, monkeypatch,
):
    cards = []
    original = ImageDraw.ImageDraw.rounded_rectangle

    def rectangle(draw, bounds, *args, **kwargs):
        cards.append(bounds)
        return original(draw, bounds, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "rounded_rectangle", rectangle)
    if bundled_font:
        monkeypatch.setattr(bootstrap_screen, "_find_font",
                            lambda size, **_: ImageFont.load_default(size=size))
    image = bootstrap_screen.render_qr(PAYLOAD, width, height)
    assert image.size == (width, height)
    assert len(cards) == 3
    assert image.getpixel((0, 0)) == (255, 255, 255)
    qr_areas, text_areas = painted
    qr_area = qr_areas[0]
    assert qr_area[2] - qr_area[0] >= width * 0.35
    flattened = " ".join(text for text, _ in text_areas)
    for expected in ("Inky Studio", "Connecter mon cadre.", "Scannez ce QR avec l’app.",
                     "Le Wi-Fi ensuite.",
                     "Choisissez votre réseau dans l’app, après le scan."):
        assert expected in flattened
    assert not any(character.isdecimal() for character in flattened)
    assert not any(value in flattened.lower() for value in
                   ("http", "adresse", "mot de passe", "password", "demo", "démo"))
    scale = min(width / 800, height / 480)
    for index, (text, bounds) in enumerate(text_areas):
        assert bounds[3] - bounds[1] >= 18 * scale, text
        if index:
            assert any(card[0] < bounds[0] < bounds[2] < card[2]
                       and card[1] < bounds[1] < bounds[3] < card[3] for card in cards), text
        for _, other in text_areas[index + 1:]:
            assert (bounds[2] <= other[0] or other[2] <= bounds[0]
                    or bounds[3] <= other[1] or other[3] <= bounds[1]), text


@pytest.mark.parametrize(("width", "height"), [(212, 104), (250, 122), (600, 448)])
def test_small_factory_panels_keep_the_existing_compact_render(width, height):
    actual = bootstrap_screen.render_qr(PAYLOAD, width, height)
    expected = screen.render_qr(PAYLOAD, width, height)
    assert ImageChops.difference(actual, expected).getbbox() is None


@pytest.mark.parametrize(("width", "height"), PANEL_SIZES)
@pytest.mark.parametrize("adopted", [False, True])
def test_status_text_fits_every_catalogue_panel(width, height, adopted, painted):
    image = bootstrap_screen.render_status(width, height, adopted=adopted)
    assert image.size == (width, height)
    assert not painted[0]
    assert [text for text, _ in painted[1]][0] == "Inky Studio"
    for text, bounds in painted[1]:
        assert 0 <= bounds[0] < bounds[2] <= width and 0 <= bounds[1] < bounds[3] <= height, text


def test_factory_screen_never_restores_normal_photo_or_creates_another_ledger(tmp_path, monkeypatch):
    from inky_web.services import history, photos, settings

    for module, method in ((history, "current"), (photos, "path_for"), (settings, "get")):
        monkeypatch.setattr(module, method, lambda *_: pytest.fail("Factory uses no normal loader"))
    display = FakeDisplay()
    existing = {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    target = bootstrap_screen.BootstrapScreen(display, tmp_path)
    target.show_qr(PAYLOAD)
    target.show_status(adopted=True)
    assert len(display.images) == 2 and display.reservation == bootstrap_screen.RESERVATION
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()} == existing
    target.release()
    assert display.reservation is None


def test_factory_screen_passes_the_exact_synthetic_wire_payload_to_its_renderer(tmp_path, monkeypatch):
    observed = []
    original = bootstrap_screen.render_qr

    def render(payload, width, height):
        observed.append(payload)
        return original(payload, width, height)

    monkeypatch.setattr(bootstrap_screen, "render_qr", render)
    display = FakeDisplay()
    target = bootstrap_screen.BootstrapScreen(display, tmp_path)
    target.show_qr(PAYLOAD)
    assert observed == [PAYLOAD]
    decoded = bootstrap_wire.decode_qr(observed[0].encode("ascii"))
    assert decoded["v"] == 2 and decoded["p"] == "bootstrap"
    assert len(display.images) == 1


def test_refused_qr_performs_no_partial_refresh_and_release_starts_no_refresh(tmp_path):
    display = FakeDisplay()
    display.spec.width = display.spec.height = 20
    target = bootstrap_screen.BootstrapScreen(display, Path(tmp_path))
    with pytest.raises(ValueError):
        target.show_qr(PAYLOAD)
    assert not display.images
    target.release()
    assert display.reservation is None
