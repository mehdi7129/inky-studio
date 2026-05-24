"""Welcome screen tests — render a valid PIL image at any resolution."""
from __future__ import annotations

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
    assert (data_dir / "welcome_preview.png").is_file()
