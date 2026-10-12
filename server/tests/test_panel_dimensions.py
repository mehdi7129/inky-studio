"""Exercise panel dimensions through upload, persistence and display acknowledgement.

The API, PNG and SQLite are real; the controller is explicitly mock. This is
not a driver or physical refresh qualification.
"""
from io import BytesIO

import pytest
from PIL import Image

from inky_web.inky.display import DisplaySpec


@pytest.mark.parametrize(
    ("width", "height", "colors"),
    [(600, 400, 6), (800, 480, 6), (1600, 1200, 6),
     (800, 480, 7), (600, 448, 7), (640, 400, 7)],
)
def test_panel_photo_upload_and_display_keep_exact_dimensions(client, png_factory, width, height, colors):
    from inky_web.main import app

    app.state.display._spec = DisplaySpec("Dimension test panel", width, height, colors)
    state = client.get("/api/state")
    assert state.status_code == 200
    assert state.json()["display"]["width"] == width
    assert state.json()["display"]["height"] == height
    assert state.json()["display"]["colors"] == colors

    # A common 800x480 assumption must not accept a transposed or near-sized PNG.
    wrong = client.post("/api/queue", files={
        "file": ("wrong.png", png_factory(width, height + 1), "image/png"),
    })
    assert wrong.status_code == 400
    assert client.get("/api/queue").json() == []

    content = png_factory(width, height, color=(5, 111, 233))
    upload = client.post("/api/queue", files={"file": ("photo.png", content, "image/png")})
    assert upload.status_code == 201
    photo = upload.json()["photo"]
    assert (photo["width"], photo["height"]) == (width, height)
    stored = client.get(f"/api/photos/{photo['id']}")
    assert stored.status_code == 200
    with Image.open(BytesIO(stored.content)) as image:
        assert image.size == (width, height)
        assert image.convert("RGB").getpixel((width // 2, height // 2)) == (5, 111, 233)

    assert client.post("/api/display/next").status_code == 202
    displayed = client.get("/api/state").json()
    current_photo = displayed["current"]["photo"]
    assert current_photo["id"] == photo["id"]
    assert (current_photo["width"], current_photo["height"]) == (width, height)
    assert client.get("/api/queue").json() == []
