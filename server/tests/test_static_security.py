"""The SPA fallback must never expose files outside the frontend build."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from inky_web import auth, frontend, main


@pytest.fixture(params=("legacy", "factory"))
def static_client(tmp_path, monkeypatch, request):
    factory = request.param == "factory"
    monkeypatch.setattr(frontend, "factory_signals_present", lambda: factory)
    monkeypatch.setattr(frontend, "FACTORY_CLIENT_DIST", tmp_path / "installed" / "client" / "dist")
    dist = frontend.resolve_client_dist(tmp_path / "server" / "inky_web" / "main.py")
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("SPA INDEX")
    (dist / "favicon.svg").write_text("PUBLIC ASSET")
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("COMPILED FRONTEND")
    if factory:
        source = tmp_path / "client" / "dist"
        source.mkdir(parents=True)
        (source / "index.html").write_text("WRONG SOURCE FRONTEND")
    private = tmp_path / "private.txt"
    private.write_text("PRIVATE FIXTURE")
    (dist / "symlink.txt").symlink_to(private)
    monkeypatch.setattr(main, "CLIENT_DIST", dist)
    monkeypatch.delenv("INKY_STUDIO_DISABLE_AUTH", raising=False)
    app = FastAPI()
    app.state.sessions = auth.SessionStore()
    app.add_middleware(main.AuthMiddleware)
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    app.add_api_route("/{full_path:path}", main.spa_fallback, methods=["GET"])
    with TestClient(app) as client:
        yield client, private


def test_parent_traversal_is_rejected_without_authentication(static_client):
    client, _ = static_client
    response = client.get("/%2e%2e/%2e%2e/private.txt")
    assert response.status_code == 404
    assert "PRIVATE FIXTURE" not in response.text


def test_absolute_path_is_rejected_without_authentication(static_client):
    client, private = static_client
    response = client.get("/%2f" + str(private).lstrip("/"))
    assert response.status_code == 404


def test_symlink_outside_build_is_rejected(static_client):
    client, _ = static_client
    assert client.get("/symlink.txt").status_code == 404


def test_static_files_and_spa_navigation_still_work(static_client):
    client, _ = static_client
    assert client.get("/favicon.svg").text == "PUBLIC ASSET"
    assert client.get("/queue").text == "SPA INDEX"
    assert client.get("/assets/app.js").text == "COMPILED FRONTEND"


def test_unknown_api_route_does_not_return_spa_html(static_client):
    client, _ = static_client
    client.cookies.set(auth.COOKIE_NAME, client.app.state.sessions.create())
    assert client.get("/api/unknown").status_code == 404
