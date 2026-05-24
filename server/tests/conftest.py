"""Shared fixtures.

Each test gets a fresh data directory under tmp_path so SQLite state and
saved photos can't leak between tests. The INKY_STUDIO_DATA_DIR env var is the
single source of truth for db.py — overriding it is enough.
"""
from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("INKY_STUDIO_DATA_DIR", str(tmp_path))
    from inky_web.db import init_db
    init_db()
    yield tmp_path


@pytest.fixture
def client(data_dir) -> TestClient:
    from inky_web.main import app
    with TestClient(app) as test_client:
        yield test_client


def make_png(width: int = 800, height: int = 480, color=(255, 0, 0)) -> bytes:
    """Build a valid PNG of the given size — used to feed upload endpoints."""
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
