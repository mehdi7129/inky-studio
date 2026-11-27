"""The language picker can change welcome copy without altering the QR."""
from __future__ import annotations

import hashlib
import json

import pytest
from fontTools.ttLib import TTFont
from PIL import Image, ImageChops, ImageDraw, features

from inky_web.inky.display import _PIMORONI_DISPLAYS
from inky_web.lan_runtime import invitation_payload, render_lan_expired, render_lan_welcome
from inky_web.provisioning.identity import load_or_create_identity
from inky_web.welcome_locale import (
    EXPIRED_COPY,
    FONT_DIR,
    WELCOME_COPY,
    resolve_welcome_language,
    welcome_font,
)
from tests.test_lan_photo import bootstrap_invitation

LANGUAGES = ("ar", "de", "en", "es", "fr", "it", "ja", "ko", "pt", "zh-Hans", "zh-Hant")
PANEL_SIZES = sorted({size for _, size in _PIMORONI_DISPLAYS})


@pytest.fixture(scope="module")
def payload(tmp_path_factory):
    identity = load_or_create_identity(tmp_path_factory.mktemp("welcome-identity"))
    invitation = bootstrap_invitation()
    return invitation_payload(identity, "https://inky-localization-test.local:8443",
                              invitation["invitation_id"], invitation["invitation_token"])


@pytest.mark.parametrize("invalid", [None, "", "EN", "pt-BR", "zh-hans", "zh-TW", "und", " en", "../ja"])
def test_only_exact_ios_language_tags_are_accepted(monkeypatch, invalid):
    assert tuple(sorted(WELCOME_COPY)) == LANGUAGES
    monkeypatch.setattr(features, "check_feature", lambda _: True)
    assert [resolve_welcome_language(language) for language in LANGUAGES] == list(LANGUAGES)
    assert resolve_welcome_language(invalid) == "fr"


@pytest.mark.parametrize("failed_feature", ["raqm", "fribidi"])
def test_unavailable_arabic_shaping_keeps_original_qr_and_french_copy(monkeypatch, failed_feature, payload):
    monkeypatch.setattr(features, "check_feature", lambda feature: feature != failed_feature)
    assert render_lan_welcome(212, 104, payload, language="ar") == render_lan_welcome(212, 104, payload)


def test_missing_bundled_font_keeps_original_qr_and_french_copy(monkeypatch, tmp_path, payload):
    monkeypatch.setattr("inky_web.welcome_locale.FONT_DIR", tmp_path)
    assert render_lan_welcome(212, 104, payload, language="ja") == render_lan_welcome(212, 104, payload)


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize(("width", "height"), PANEL_SIZES)
def test_all_panel_sizes_preserve_the_invitation_qr_and_localize_copy(monkeypatch, payload, language, width, height):
    if language == "ar" and not all(features.check_feature(name) for name in ("raqm", "fribidi")):
        pytest.skip("Arabic screen shaping requires Pillow RAQM and FriBidi")
    qr_renders = []
    text_renders = []
    paste = Image.Image.paste
    draw_text = ImageDraw.ImageDraw.text

    def record_qr(image, region, position=None, mask=None):
        qr_renders.append((position, region.copy()))
        return paste(image, region, position, mask)

    def record_text(draw, position, text, **kwargs):
        bounds = draw.textbbox(position, text, font=kwargs["font"], direction=kwargs["direction"])
        text_renders.append((text, bounds, kwargs["direction"]))
        return draw_text(draw, position, text, **kwargs)

    monkeypatch.setattr(Image.Image, "paste", record_qr)
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", record_text)
    base = render_lan_welcome(width, height, payload)
    text_renders.clear()
    rendered = render_lan_welcome(width, height, payload, language=language)
    assert rendered.size == (width, height)
    (old_pos, old_qr), (new_pos, new_qr) = qr_renders
    assert new_pos == old_pos
    assert new_qr == old_qr
    qr_box = (*new_pos, new_pos[0] + new_qr.width, new_pos[1] + new_qr.height)
    assert rendered.crop(qr_box) == new_qr
    difference = ImageChops.difference(base, rendered).getbbox()
    brand, *lines = text_renders
    copy = WELCOME_COPY[language]
    assert brand[0] == "Inky Studio"
    assert tuple(line[0] for line in lines) == (
        copy.compact if width <= 400 else copy.headline + copy.instructions
    )
    assert all(direction == copy.direction for _, _, direction in lines)
    for _, (left, top, right, bottom), _ in lines:
        assert qr_box[2] < left < right < width
        assert 0 < top < bottom < height
    if language == "fr":
        assert difference is None
    else:
        assert difference is not None
        assert all(first[1][3] < second[1][1] for first, second in zip(text_renders[:-1], lines, strict=True))


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("bold", [False, True])
def test_packaged_fonts_have_all_welcome_glyphs(language, bold):
    localized = WELCOME_COPY[language]
    lines = localized.headline + (EXPIRED_COPY[language],) if bold else localized.instructions + localized.compact
    font = welcome_font(language, bold=bold)
    if font is None:
        font = FONT_DIR / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    with TTFont(font) as data:
        missing = set(map(ord, "".join(lines))) - data.getBestCmap().keys()
        assert missing == set()


def test_subset_font_sources_and_licenses_are_attested():
    manifest = json.loads((FONT_DIR / "WELCOME-FONT-PROVENANCE.json").read_text())
    assert manifest["licenses"] == "OFL-1.1"
    assert manifest["sources"].keys() == {tag for tag, copy in WELCOME_COPY.items() if copy.subset}
    for language, source in manifest["sources"].items():
        license_text = (FONT_DIR / source["license_file"]).read_bytes()
        assert b"SIL Open Font License, Version 1.1" in license_text
        assert hashlib.sha256(license_text).hexdigest() == source["license_sha256"]
        assert {subset["file"] for subset in source["subsets"]} == {
            welcome_font(language, bold=False).name, welcome_font(language, bold=True).name,
        }
        for subset in source["subsets"]:
            font = FONT_DIR / subset["file"]
            font_data = font.read_bytes()
            assert hashlib.sha256(font_data).hexdigest() == subset["sha256"]
            assert len(font_data) == subset["bytes"]
            with TTFont(font) as data:
                assert data["name"].getBestFamilyName() == f"Inky Welcome {language}"
                assert data["name"].getDebugName(0)


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize(("width", "height"), PANEL_SIZES)
def test_expired_screen_has_localized_text_inside_the_panel(monkeypatch, language, width, height):
    if language == "ar" and not all(features.check_feature(name) for name in ("raqm", "fribidi")):
        pytest.skip("Arabic screen shaping requires Pillow RAQM and FriBidi")
    lines = []
    draw_text = ImageDraw.ImageDraw.text

    def record_text(draw, position, text, **kwargs):
        bounds = draw.textbbox(position, text, font=kwargs["font"], direction=kwargs["direction"])
        lines.append((text, bounds, kwargs["direction"]))
        return draw_text(draw, position, text, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", record_text)
    image = render_lan_expired(width, height, language=language)
    assert image.size == (width, height)
    brand, localized = lines
    assert brand[0] == "Inky Studio"
    assert localized[0] == EXPIRED_COPY[language]
    left, top, right, bottom = localized[1]
    assert 0 < left < right < width and brand[1][3] < top < bottom < height
    assert localized[2] == WELCOME_COPY[language].direction
