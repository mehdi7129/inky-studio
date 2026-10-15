"""Welcome screen tests — render a valid PIL image at any resolution."""
from __future__ import annotations

import json
import stat

import pytest
from fastapi.testclient import TestClient

from inky_web.welcome import render_welcome_image, show_welcome


def test_render_welcome_image_returns_correct_dimensions():
    img = render_welcome_image(800, 480, url="http://192.168.1.120:8000", password="abc123XYZ0")
    assert img.size == (800, 480)
    assert img.mode == "RGB"


def test_render_welcome_image_scales_to_larger_display():
    # The 13.3" display has different aspect ratio (4:3) — the text positioning
    # uses relative offsets so this should still render cleanly.
    img = render_welcome_image(1600, 1200, url="http://inky.local:8000", password="Pass123abcd")
    assert img.size == (1600, 1200)


def test_show_welcome_writes_preview_in_mock_mode(data_dir):
    show_welcome()
    preview = data_dir / "welcome_preview.png"
    assert preview.is_file()
    assert stat.S_IMODE(preview.stat().st_mode) == 0o600
    assert not list(data_dir.glob(".welcome-*"))


def test_personalized_password_cannot_be_recovered_by_welcome(data_dir, monkeypatch):
    from inky_web import auth, welcome

    credentials = auth.load_or_create_credentials(data_dir)
    service = auth.CredentialService(credentials, auth.SessionStore())
    token = service.login(credentials.bootstrap_password)
    service.change_password(token, credentials.bootstrap_password, "personalized-secret")
    original_render = welcome.render_welcome_image
    displayed = []

    def capture(width, height, *, url, password):
        displayed.append(password)
        return original_render(width, height, url=url, password=password)

    monkeypatch.setattr(welcome, "render_welcome_image", capture)
    show_welcome()
    assert displayed == [None]
    assert service.credentials.verify("personalized-secret")


@pytest.mark.parametrize("personalized", [False, True])
def test_startup_retries_existing_bootstrap_but_never_personalized_password(data_dir, monkeypatch, personalized):
    from inky_web import auth, welcome
    from inky_web.main import app

    monkeypatch.delenv("INKY_STUDIO_DISABLE_AUTH", raising=False)
    credentials = auth.load_or_create_credentials(data_dir)
    if personalized:
        service = auth.CredentialService(credentials, auth.SessionStore())
        token = service.login(credentials.bootstrap_password)
        service.change_password(token, credentials.bootstrap_password, "personalized-secret")
    displayed = []
    monkeypatch.setattr(welcome, "show_welcome", lambda display: displayed.append(display))
    # The credentials file already exists, as after an interrupted first boot.
    with TestClient(app):
        pass
    assert len(displayed) == (0 if personalized else 1)


def test_physical_welcome_file_is_private_and_removed_on_display_failure(data_dir):
    seen = []

    class FailingDisplay:
        is_mock = False

        def info(self):
            return {"width": 800, "height": 480}

        def display_image(self, path):
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            seen.append(path)
            raise RuntimeError("mock panel failure")

    with pytest.raises(RuntimeError, match="panel failure"):
        show_welcome(FailingDisplay())
    assert len(seen) == 1
    assert not seen[0].exists()


@pytest.mark.parametrize("address", ["10.1.2.3", "172.16.0.1", "172.31.255.254", "192.168.1.120"])
def test_lan_qr_has_only_initial_login_contract(address):
    from inky_web.welcome import lan_login_payload

    url = f"http://{address}:8000"
    payload = lan_login_payload(url, "DemoPass12345678")
    assert json.loads(payload) == {
        "v": 1, "p": "lan-login", "url": url, "password": "DemoPass12345678",
    }
    assert len(payload.encode("utf-8")) <= 512


@pytest.mark.parametrize("url", [
    "http://8.8.8.8:8000", "http://127.0.0.1:8000", "http://0.0.0.0:8000",
    "http://169.254.1.2:8000", "http://172.15.1.2:8000", "http://172.32.1.2:8000",
    "http://224.1.2.3:8000", "http://192.168.001.2:8000", "http://10.0.0.256:8000",
    "http://inky.local:8000", "http://localhost:8000", "https://192.168.1.120:8443",
    "http://192.168.1.120:80", "http://192.168.1.120", "http://192.168.1.120:8000/",
    "http://192.168.1.120:8000/login", "http://192.168.1.120:8000?password=bad",
    "http://192.168.1.120:8000#fragment", "http://user@192.168.1.120:8000",
    "http://user:secret@192.168.1.120:8000", "http://192.168.1.120:8000\n",
    " http://192.168.1.120:8000", "http://[fd00::1]:8000",
    "http://192.168.1.120%2f:8000",
])
def test_lan_qr_rejects_origins_outside_the_current_lan_contract(url):
    from inky_web.welcome import lan_login_payload

    assert lan_login_payload(url, "DemoPass12345678") is None


@pytest.mark.parametrize("password", [None, "", " ", "a b", "a\nb", "a\x00b", "a\x7fb", "café", "a" * 129])
def test_lan_qr_rejects_missing_or_non_bootstrap_password_text(password):
    from inky_web.welcome import lan_login_payload

    assert lan_login_payload("http://192.168.1.120:8000", password) is None


def test_missing_system_fonts_preserves_requested_font_size(monkeypatch):
    from inky_web import welcome

    monkeypatch.setattr(welcome.Path, "is_file", lambda path: False)
    small, large = welcome._find_font(12), welcome._find_font(48)
    assert large.getbbox("Inky Studio")[3] - large.getbbox("Inky Studio")[1] > 30
    assert large.getlength("1234567890") > 3 * small.getlength("1234567890")


@pytest.mark.parametrize("size", [(800, 480), (600, 448), (250, 122), (1600, 1200)])
@pytest.mark.parametrize("password", ["DemoPass12345678", None])
def test_bento_text_fits_panel_without_system_fonts(monkeypatch, size, password):
    from inky_web import welcome

    monkeypatch.setattr(welcome.Path, "is_file", lambda path: False)
    original = welcome._draw_centered
    bounds = []

    def capture(draw, text, y, font, width, fill, *, x=0):
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width, text_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
        bounds.append((x + (width - text_width) // 2, y, text_width, text_height))
        return original(draw, text, y, font, width, fill, x=x)

    monkeypatch.setattr(welcome, "_draw_centered", capture)
    image = welcome.render_welcome_image(*size, url="http://192.168.255.254:8000", password=password)
    assert image.size == size
    assert len(bounds) >= 6
    for x, y, width, height in bounds:
        assert 0 <= x < x + width <= size[0]
        assert 0 <= y < y + height <= size[1]
    # No label or value should overlap another text block on the panel.
    for index, (x, y, width, height) in enumerate(bounds):
        for other_x, other_y, other_width, other_height in bounds[index + 1:]:
            assert (x + width <= other_x or other_x + other_width <= x
                    or y + height <= other_y or other_y + other_height <= y)


def test_qr_is_black_white_integer_modules_with_four_module_quiet_zone():
    import qrcode
    from PIL import Image

    from inky_web.welcome import _login_qr, lan_login_payload

    payload = lan_login_payload("http://192.168.1.120:8000", "DemoPass12345678")
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=1)
    qr.add_data(payload)
    qr.make(fit=True)
    matrix = qr.make_image().convert("RGB")
    image = _login_qr(payload, 250)
    scale = image.width // matrix.width
    assert scale >= 3
    assert image.width == matrix.width * scale
    assert image.tobytes() == matrix.resize(image.size, Image.Resampling.NEAREST).tobytes()
    assert image.crop((0, 0, image.width, 4 * scale)).getextrema() == ((255, 255),) * 3
    assert set(image.getdata()) <= {(0, 0, 0), (255, 255, 255)}
    assert _login_qr(payload, 80) is None


@pytest.mark.parametrize("password,url", [
    (None, "http://192.168.1.120:8000"),
    ("DemoPass12345678", "http://8.8.8.8:8000"),
])
def test_manual_welcome_does_not_encode_unavailable_or_non_lan_credentials(monkeypatch, password, url):
    from inky_web import welcome

    def unexpected(*args):
        pytest.fail("Manual welcome must not encode a QR")

    monkeypatch.setattr(welcome, "_login_qr", unexpected)
    assert welcome.render_welcome_image(800, 480, url=url, password=password).size == (800, 480)


def test_welcome_logs_neither_bootstrap_password_nor_qr_payload(data_dir, caplog, monkeypatch):
    import logging

    from inky_web import auth, welcome

    credentials = auth.load_or_create_credentials(data_dir)
    monkeypatch.setattr(welcome, "_detect_ip", lambda: "192.168.1.120")
    with caplog.at_level(logging.INFO):
        show_welcome()
    assert credentials.bootstrap_password not in caplog.text
    assert "192.168.1.120" not in caplog.text
    assert "lan-login" not in caplog.text
