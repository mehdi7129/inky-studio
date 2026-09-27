"""Welcome screen tests — render a valid PIL image at any resolution."""
from __future__ import annotations

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
