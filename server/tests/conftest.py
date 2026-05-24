"""Shared fixtures.

Auto-applied isolation: every test gets a fresh tmp data dir AND auth is
disabled by default. Opt out by overriding the ``inky_env`` fixture in a
specific test if you want to exercise the auth path directly.
"""
from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture(autouse=True)
def inky_env(tmp_path, monkeypatch):
    """Isolate every test: fresh data dir, auth off, DB initialized."""
    monkeypatch.setenv("INKY_STUDIO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INKY_STUDIO_DISABLE_AUTH", "1")
    from inky_web.db import init_db
    init_db()
    yield tmp_path


@pytest.fixture
def data_dir(inky_env):
    """Backwards-compatible alias — most tests reference ``data_dir``."""
    return inky_env


@pytest.fixture
def client(inky_env) -> TestClient:
    from inky_web.main import app
    with TestClient(app) as test_client:
        yield test_client


def make_png(width: int = 800, height: int = 480, color=(255, 0, 0)) -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_jpeg(width: int = 800, height: int = 480) -> bytes:
    img = Image.new("RGB", (width, height), (0, 200, 0))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def png_factory():
    return make_png


@pytest.fixture
def jpeg_factory():
    return make_jpeg
