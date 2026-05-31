"""Unit tests for the self-updater (no real network or subprocess)."""
from __future__ import annotations

import inky_web
from inky_web.services import updater


def test_parse_version():
    assert updater._parse_version("v1.2.3") == (1, 2, 3)
    assert updater._parse_version("0.2.0") == (0, 2, 0)
    assert updater._parse_version("v1.2.3-rc1") == (1, 2, 3)  # pre-release suffix stripped
    assert updater._parse_version("1.2.x") == (1, 2)  # stops at first non-numeric part
    assert updater._parse_version(None) == ()
    assert updater._parse_version("") == ()


def test_status_update_available(monkeypatch):
    monkeypatch.setattr(inky_web, "__version__", "0.2.0")
    monkeypatch.setattr(updater, "__version__", "0.2.0")
    monkeypatch.setattr(updater, "_fetch_latest_release", lambda: {"tag_name": "v0.3.0"})
    status = updater.get_status(use_cache=False)
    assert status == {"current": "0.2.0", "latest": "0.3.0", "update_available": True}


def test_status_up_to_date(monkeypatch):
    monkeypatch.setattr(updater, "__version__", "0.3.0")
    monkeypatch.setattr(updater, "_fetch_latest_release", lambda: {"tag_name": "v0.3.0"})
    status = updater.get_status(use_cache=False)
    assert status["update_available"] is False
    assert status["latest"] == "0.3.0"


def test_status_network_failure(monkeypatch):
    monkeypatch.setattr(updater, "_fetch_latest_release", lambda: None)
    status = updater.get_status(use_cache=False)
    assert status["latest"] is None
    assert status["update_available"] is False


def test_status_cache(monkeypatch):
    calls = {"n": 0}

    def fake_fetch():
        calls["n"] += 1
        return {"tag_name": "v9.9.9"}

    monkeypatch.setattr(updater, "_fetch_latest_release", fake_fetch)
    monkeypatch.setitem(updater._status_cache, "value", None)
    updater.get_status(use_cache=True)
    updater.get_status(use_cache=True)
    assert calls["n"] == 1  # second call served from cache


def test_pick_tarball_asset():
    release = {
        "assets": [
            {"name": "notes.txt", "browser_download_url": "x"},
            {"name": "inky-studio-v1.0.0.tar.gz", "browser_download_url": "y"},
        ]
    }
    asset = updater._pick_tarball_asset(release)
    assert asset and asset["browser_download_url"] == "y"
    assert updater._pick_tarball_asset({"assets": []}) is None
