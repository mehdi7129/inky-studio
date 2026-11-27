"""Factory frontend selection never falls back to a source checkout."""
from __future__ import annotations

import pytest

from inky_web import frontend


def test_legacy_source_layout_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(frontend, "factory_signals_present", lambda: False)
    module_file = tmp_path / "checkout" / "server" / "inky_web" / "main.py"
    assert frontend.resolve_client_dist(module_file) == tmp_path / "checkout" / "client" / "dist"


@pytest.mark.parametrize("signal", [
    "INKY_STUDIO_FACTORY_REQUIRED",
    "INKYOS_WRITER_ROLE",
    "INKYOS_WRITER_CONTEXT_SHA256",
    "INKYOS_WRITER_LEASE_FD",
])
def test_factory_signals_select_external_bundle_even_when_empty(signal, tmp_path, monkeypatch):
    monkeypatch.setenv(signal, "")
    module_file = tmp_path / "server" / ".venv" / "lib" / "python3.13" / "site-packages" / "inky_web" / "main.py"
    assert frontend.resolve_client_dist(module_file) == frontend.FACTORY_CLIENT_DIST
    assert frontend.FACTORY_CLIENT_DIST.as_posix() == "/usr/lib/inky-studio/client/dist"


def test_missing_factory_bundle_does_not_reuse_existing_source_frontend(tmp_path, monkeypatch):
    monkeypatch.setenv("INKY_STUDIO_FACTORY_REQUIRED", "1")
    source = tmp_path / "checkout" / "client" / "dist"
    source.mkdir(parents=True)
    (source / "index.html").write_text("LEGACY FRONTEND")
    missing_bundle = tmp_path / "usr" / "lib" / "inky-studio" / "client" / "dist"
    monkeypatch.setattr(frontend, "FACTORY_CLIENT_DIST", missing_bundle)
    resolved = frontend.resolve_client_dist(tmp_path / "checkout" / "server" / "inky_web" / "main.py")
    assert resolved == missing_bundle
    assert not resolved.exists()
