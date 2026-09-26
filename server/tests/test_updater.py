"""Unit tests for the self-updater (no real network or subprocess)."""
from __future__ import annotations

import fcntl
import io
import tarfile
from unittest.mock import AsyncMock

import pytest

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


@pytest.mark.parametrize("name", ["../extracted-sibling/proof", "/tmp/proof", "server/../../proof"])
def test_extract_rejects_escaping_paths(tmp_path, name):
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        info = tarfile.TarInfo(name)
        info.size = 5
        tf.addfile(info, io.BytesIO(b"proof"))
    with pytest.raises(RuntimeError, match="Unsafe path"):
        updater._safe_extract(archive, tmp_path / "extracted")
    assert not (tmp_path / "extracted-sibling").exists()


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE])
def test_extract_rejects_links_and_special_files(tmp_path, kind):
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        info = tarfile.TarInfo("server/link")
        info.type = kind
        info.linkname = "../../outside"
        tf.addfile(info)
    with pytest.raises(RuntimeError, match="Unsupported archive entry"):
        updater._safe_extract(archive, tmp_path / "extracted")


def test_extract_accepts_release_layout_and_preserves_executable(tmp_path):
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        info = tarfile.TarInfo("./scripts/inky-studio-cli")
        info.size, info.mode = 4, 0o4755
        tf.addfile(info, io.BytesIO(b"test"))
    updater._safe_extract(archive, tmp_path / "extracted")
    target = tmp_path / "extracted/scripts/inky-studio-cli"
    assert target.read_bytes() == b"test"
    assert target.stat().st_mode & 0o7777 == 0o755


def test_restore_removes_added_files_but_preserves_runtime(tmp_path):
    install = tmp_path / "install"
    server = install / "server"
    server.mkdir(parents=True)
    (server / "old.py").write_text("old")
    (server / "data").mkdir()
    (server / "data/photo.png").write_bytes(b"photo")
    (server / ".venv").mkdir()
    (server / ".venv/python").write_text("python")
    backup = tmp_path / "backup"
    updater._backup_current(install, backup)
    assert not (backup / "server/data").exists()
    assert not (backup / "server/.venv").exists()
    (server / "old.py").write_text("new")
    (server / "new.py").write_text("new")
    (install / "VERSION").write_text("v9")
    updater._restore(backup, install)
    assert (server / "old.py").read_text() == "old"
    assert not (server / "new.py").exists()
    assert not (install / "VERSION").exists()
    assert (server / "data/photo.png").read_bytes() == b"photo"
    assert (server / ".venv/python").read_text() == "python"


def test_payload_must_be_complete_and_exclude_runtime(tmp_path):
    tmp_path = tmp_path / "payload"
    tmp_path.mkdir()
    with pytest.raises(RuntimeError, match="Incomplete"):
        updater._validate_payload(tmp_path)
    for name in ["server/pyproject.toml", "server/inky_web/main.py", "client/dist/index.html"]:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("test")
    updater._validate_payload(tmp_path)
    (tmp_path / "server/data").mkdir()
    with pytest.raises(RuntimeError, match="protected"):
        updater._validate_payload(tmp_path)


@pytest.mark.asyncio
async def test_failed_pip_restores_code_and_reports_dependency_limit(tmp_path, monkeypatch):
    install = tmp_path / "install"
    (install / "server").mkdir(parents=True)
    (install / "server/old.py").write_text("original")
    payload = tmp_path / "payload"
    for name in ["server/pyproject.toml", "server/inky_web/main.py", "client/dist/index.html"]:
        target = payload / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("new")
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        for child in payload.iterdir():
            tf.add(child, arcname=child.name)
    monkeypatch.setattr(updater, "_fetch_latest_release", lambda: {
        "tag_name": "v9", "assets": [{"name": "release.tar.gz", "browser_download_url": "fixture"}],
    })
    monkeypatch.setattr(updater, "_download", lambda _url, dest: dest.write_bytes(archive.read_bytes()))
    run = AsyncMock(return_value=1)
    monkeypatch.setattr(updater, "_run_streaming", run)
    restart = AsyncMock()
    monkeypatch.setattr(updater.asyncio, "create_subprocess_exec", restart)
    events = []
    assert not await updater.perform_update(lambda *args, **kwargs: events.append(args), install_dir=install)
    assert (install / "server/old.py").read_text() == "original"
    assert not (install / "server/inky_web").exists()
    assert not (install / "client").exists()
    restart.assert_not_called()
    assert "dépendances Python" in events[-1][1]


@pytest.mark.asyncio
async def test_concurrent_update_is_rejected_before_network(tmp_path, monkeypatch):
    with (tmp_path / ".inky-update.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        def unexpected_fetch():
            pytest.fail("Concurrent update must not contact the network")
        monkeypatch.setattr(updater, "_fetch_latest_release", unexpected_fetch)
        events = []
        assert not await updater.perform_update(lambda *args, **kwargs: events.append(args), install_dir=tmp_path)
    assert events == [("error", "Une mise à jour est déjà en cours.")]
