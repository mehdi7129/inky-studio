"""Unit tests for the self-updater (no real network or subprocess)."""
from __future__ import annotations

import fcntl
import gzip
import io
import tarfile
from unittest.mock import AsyncMock, Mock

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


@pytest.mark.parametrize(("current", "latest", "expected"), [
    ("0.5.0-rc.1", "v0.5.0", True),
    ("0.5.0-rc.1", "v0.4.2", False),
    ("0.5.0", "v0.5.0", False),
    ("0.5.0+private-build", "v0.5.0", False),
    ("dev", "v0.5.0", True),
    ("unknown", "v0.5.0", True),
    ("dev", "dev", False),
])
def test_candidate_can_upgrade_to_final_without_downgrading(monkeypatch, current, latest, expected):
    monkeypatch.setattr(updater, "__version__", current)
    monkeypatch.setattr(updater, "_fetch_latest_release", lambda: {"tag_name": latest})
    assert updater.get_status(use_cache=False)["update_available"] is expected


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


class _Response:
    def __init__(self, body, length=None, fail_after=None):
        self.body = io.BytesIO(body)
        self.headers = {} if length is None else {"Content-Length": length}
        self.read_sizes = []
        self.fail_after = fail_after
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def read(self, size):
        self.read_sizes.append(size)
        assert 0 < size <= updater._HTTP_CHUNK_BYTES
        if self.fail_after is not None and self.body.tell() >= self.fail_after:
            raise OSError("interrupted response")
        return self.body.read(size)


@pytest.mark.parametrize("length", [None, "1", "8"])
@pytest.mark.parametrize("size", [8, 9])
def test_download_enforces_actual_byte_budget(tmp_path, monkeypatch, length, size):
    monkeypatch.setattr(updater, "_MAX_DOWNLOAD_BYTES", 8)
    monkeypatch.setattr(updater, "_HTTP_CHUNK_BYTES", 4)
    response = _Response(b"x" * size, length)
    monkeypatch.setattr(updater.urllib.request, "urlopen", Mock(return_value=response))
    target = tmp_path / "release.tar.gz"
    if size == 8:
        updater._download("https://fixture.invalid/release", target)
        assert target.read_bytes() == b"x" * size
    else:
        with pytest.raises(RuntimeError, match="too large"):
            updater._download("https://fixture.invalid/release", target)
        assert not target.exists()
    assert response.read_sizes == [4, 4, 1]
    assert response.closed


def test_download_never_writes_the_chunk_exceeding_remaining_budget(monkeypatch):
    monkeypatch.setattr(updater, "_MAX_DOWNLOAD_BYTES", 6)
    monkeypatch.setattr(updater, "_HTTP_CHUNK_BYTES", 4)
    response = _Response(b"1234567")
    monkeypatch.setattr(updater.urllib.request, "urlopen", Mock(return_value=response))
    target = Mock()
    output = io.BytesIO()
    writes = []

    class Output:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def write(self, chunk):
            writes.append(chunk)
            return output.write(chunk)

    target.open.return_value = Output()
    with pytest.raises(RuntimeError, match="too large"):
        updater._download("https://fixture.invalid/release", target)
    assert response.read_sizes == [4, 3]
    assert writes == [b"1234"]
    target.unlink.assert_called_once_with(missing_ok=True)


def test_download_removes_partial_file_on_read_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "_HTTP_CHUNK_BYTES", 4)
    response = _Response(b"12345678", fail_after=4)
    monkeypatch.setattr(updater.urllib.request, "urlopen", Mock(return_value=response))
    target = tmp_path / "release.tar.gz"
    with pytest.raises(OSError, match="interrupted"):
        updater._download("https://fixture.invalid/release", target)
    assert response.body.tell() == 4
    assert response.closed
    assert not target.exists()


@pytest.mark.parametrize("operation", ["download", "json"])
@pytest.mark.parametrize("length", ["9", "-1", "invalid"])
def test_http_rejects_bad_or_oversized_length_before_reading(tmp_path, monkeypatch, operation, length):
    monkeypatch.setattr(updater, "_MAX_DOWNLOAD_BYTES", 8)
    monkeypatch.setattr(updater, "_MAX_JSON_BYTES", 8)
    response = _Response(b"{}", length)
    monkeypatch.setattr(updater.urllib.request, "urlopen", Mock(return_value=response))
    target = tmp_path / "release.tar.gz"
    with pytest.raises(RuntimeError):
        if operation == "download":
            updater._download("https://fixture.invalid/release", target)
        else:
            updater._http_json("https://fixture.invalid/release")
    assert response.read_sizes == []
    assert not target.exists()
    assert response.closed


@pytest.mark.parametrize("length", [None, "1", str(1024 * 1024)])
@pytest.mark.parametrize("extra", [0, 1])
def test_json_response_limit_is_one_mib(monkeypatch, length, extra):
    body = b"{}" + b" " * (1024 * 1024 - 2 + extra)
    response = _Response(body, length)
    monkeypatch.setattr(updater.urllib.request, "urlopen", Mock(return_value=response))
    if extra:
        with pytest.raises(RuntimeError, match="too large"):
            updater._http_json("https://fixture.invalid/release")
    else:
        assert updater._http_json("https://fixture.invalid/release") == {}
    assert response.body.tell() == len(body)
    assert response.read_sizes[-1] == 1
    assert response.closed


@pytest.mark.parametrize("name", ["../extracted-sibling/proof", "/tmp/proof", "server/../../proof"])
def test_extract_rejects_escaping_paths(tmp_path, name):
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz", format=tarfile.USTAR_FORMAT) as tf:
        info = tarfile.TarInfo(name)
        info.size = 5
        tf.addfile(info, io.BytesIO(b"proof"))
    with pytest.raises(RuntimeError, match="Unsafe path"):
        updater._safe_extract(archive, tmp_path / "extracted")
    assert not (tmp_path / "extracted-sibling").exists()


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE])
def test_extract_rejects_links_and_special_files(tmp_path, kind):
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz", format=tarfile.USTAR_FORMAT) as tf:
        info = tarfile.TarInfo("server/link")
        info.type = kind
        info.linkname = "../../outside"
        tf.addfile(info)
    with pytest.raises(RuntimeError, match="Unsupported archive entry"):
        updater._safe_extract(archive, tmp_path / "extracted")


def test_extract_accepts_release_layout_and_preserves_executable(tmp_path):
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz", format=tarfile.USTAR_FORMAT) as tf:
        info = tarfile.TarInfo("./scripts/inky-studio-cli")
        info.size, info.mode = 4, 0o4755
        tf.addfile(info, io.BytesIO(b"test"))
    updater._safe_extract(archive, tmp_path / "extracted")
    target = tmp_path / "extracted/scripts/inky-studio-cli"
    assert target.read_bytes() == b"test"
    assert target.stat().st_mode & 0o7777 == 0o755


@pytest.mark.parametrize("archive_format", [tarfile.USTAR_FORMAT, tarfile.GNU_FORMAT])
def test_extract_accepts_ordinary_ustar_and_gnu_archives(tmp_path, archive_format):
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz", format=archive_format) as tf:
        directory = tarfile.TarInfo("server")
        directory.type = tarfile.DIRTYPE
        tf.addfile(directory)
        info = tarfile.TarInfo("server/main.py")
        info.size = 4
        tf.addfile(info, io.BytesIO(b"code"))
    updater._safe_extract(archive, tmp_path / "extracted")
    assert (tmp_path / "extracted/server/main.py").read_bytes() == b"code"


@pytest.mark.parametrize(("count", "size", "accepted"), [(2, 4, True), (3, 0, False), (2, 5, False)])
def test_extract_checks_member_and_total_size_budgets_before_extracting(
    tmp_path, monkeypatch, count, size, accepted,
):
    monkeypatch.setattr(updater, "_MAX_ARCHIVE_MEMBERS", 2)
    monkeypatch.setattr(updater, "_MAX_ARCHIVE_BYTES", 8)
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz", format=tarfile.USTAR_FORMAT) as tf:
        for index in range(count):
            info = tarfile.TarInfo(f"file{index}")
            info.size = size
            tf.addfile(info, io.BytesIO(b"x" * size))
    dest = tmp_path / "extracted"
    if accepted:
        updater._safe_extract(archive, dest)
        assert [p.read_bytes() for p in sorted(dest.iterdir())] == [b"xxxx", b"xxxx"]
    else:
        with pytest.raises(RuntimeError, match="too large"):
            updater._safe_extract(archive, dest)
        assert not list(dest.iterdir())


@pytest.mark.parametrize("kind", [
    tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.SOLARIS_XHDTYPE,
    tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK, tarfile.GNUTYPE_SPARSE,
    tarfile.REGTYPE,
])
@pytest.mark.parametrize("parser_dispatch", ["runtime", "bypass_public_frombuf"])
def test_extract_rejects_oversized_header_before_reading_its_body(
    tmp_path, monkeypatch, kind, parser_dispatch,
):
    if parser_dispatch == "bypass_public_frombuf":
        # Recent CPython uses _frombuf internally instead of the public
        # frombuf override. Exercise that bypass on older interpreters too,
        # retaining the standard post-header member-processing dispatch.
        base_frombuf = tarfile.TarInfo.frombuf.__func__

        @classmethod
        def from_base_header(cls, archive):
            buf = archive.fileobj.read(tarfile.BLOCKSIZE)
            member = base_frombuf(cls, buf, archive.encoding, archive.errors)
            member.offset = archive.fileobj.tell() - tarfile.BLOCKSIZE
            return member._proc_member(archive)

        monkeypatch.setattr(tarfile.TarInfo, "fromtarfile", from_base_header)

    # Give tarfile only the raw header: the stream spy fails if parsing attempts
    # to allocate/read an extension body or skip a too-large regular file.
    info = tarfile.TarInfo("huge-metadata")
    info.type = kind
    info.size = updater._MAX_ARCHIVE_BYTES + 1
    header = info.tobuf(format=tarfile.GNU_FORMAT)
    read_sizes = []

    class HeaderStream(io.BytesIO):
        def read(self, size=-1):
            read_sizes.append(size)
            assert self.tell() == 0 and size == 512, "read beyond rejected header"
            return super().read(size)

    stream = HeaderStream(header)
    real_open = tarfile.open
    monkeypatch.setattr(updater.tarfile, "open", lambda *args, **kwargs: real_open(
        fileobj=stream, mode="r:", tarinfo=kwargs["tarinfo"],
    ))
    reason = "too large" if kind == tarfile.REGTYPE else "Unsupported archive entry"
    with pytest.raises(RuntimeError, match=reason):
        updater._safe_extract(tmp_path / "unused.tar.gz", tmp_path / "extracted")
    assert read_sizes == [512]
    assert stream.tell() == 512
    assert not list((tmp_path / "extracted").iterdir())


@pytest.mark.parametrize("budget", ["members", "total_size"])
def test_extract_checks_accumulated_budget_at_header_before_skipping_body(tmp_path, monkeypatch, budget):
    first = tarfile.TarInfo("first")
    first.size = 4
    last = tarfile.TarInfo("last")
    last.size = 5
    raw = first.tobuf() + b"data" + b"\0" * 508 + last.tobuf()
    monkeypatch.setattr(updater, "_MAX_ARCHIVE_MEMBERS", 1 if budget == "members" else 2)
    monkeypatch.setattr(updater, "_MAX_ARCHIVE_BYTES", 8)
    read_positions = []

    class BudgetStream(io.BytesIO):
        def read(self, size=-1):
            read_positions.append(self.tell())
            assert 0 < size <= 512 and self.tell() < len(raw), "read past over-budget header"
            return super().read(size)

        def seek(self, offset, whence=0):
            assert whence == 0 and offset < len(raw), "skipped body of over-budget member"
            return super().seek(offset, whence)

    stream = BudgetStream(raw)
    real_open = tarfile.open
    monkeypatch.setattr(updater.tarfile, "open", lambda *args, **kwargs: real_open(
        fileobj=stream, mode="r:", tarinfo=kwargs["tarinfo"],
    ))
    with pytest.raises(RuntimeError, match="too large"):
        updater._safe_extract(tmp_path / "unused.tar.gz", tmp_path / "extracted")
    assert read_positions == [0, 1023, 1024]
    assert not list((tmp_path / "extracted").iterdir())


@pytest.mark.parametrize(("kind", "size"), [(tarfile.REGTYPE, -1), (tarfile.DIRTYPE, 1)])
def test_extract_rejects_invalid_sizes_from_header(tmp_path, kind, size):
    info = tarfile.TarInfo("invalid")
    info.type, info.size = kind, size
    archive = tmp_path / "release.tar.gz"
    archive.write_bytes(gzip.compress(info.tobuf(format=tarfile.GNU_FORMAT)))
    with pytest.raises(RuntimeError, match="Invalid archive entry size"):
        updater._safe_extract(archive, tmp_path / "extracted")
    assert not list((tmp_path / "extracted").iterdir())


@pytest.mark.parametrize("invalid", ["path", "link"])
def test_extract_validates_whole_archive_before_writing_any_file(tmp_path, invalid):
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz", format=tarfile.USTAR_FORMAT) as tf:
        first = tarfile.TarInfo("valid-file")
        first.size = 4
        tf.addfile(first, io.BytesIO(b"code"))
        last = tarfile.TarInfo("../invalid" if invalid == "path" else "invalid-link")
        if invalid == "link":
            last.type, last.linkname = tarfile.SYMTYPE, "valid-file"
        tf.addfile(last)
    with pytest.raises(RuntimeError):
        updater._safe_extract(archive, tmp_path / "extracted")
    assert not list((tmp_path / "extracted").iterdir())


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
    with pytest.raises(RuntimeError, match="Incomplete"):
        updater._validate_payload(tmp_path)
    (tmp_path / "client/dist/assets").mkdir()
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
    (payload / "client/dist/assets").mkdir()
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz", format=tarfile.USTAR_FORMAT) as tf:
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


@pytest.mark.parametrize(("current", "latest"), [
    ("0.5.0-rc.1", "v0.4.2"),
    ("0.5.0", "v0.5.0"),
    ("0.5.0+private-build", "v0.5.0"),
])
async def test_direct_update_refuses_older_or_same_stable_release_before_changing_installation(
    tmp_path, monkeypatch, current, latest,
):
    # This is the route's actual entry point, without a preceding status check.
    # An installed RC already uses credentials that v0.4.2 cannot understand.
    credential = tmp_path / "server/data/credentials.json"
    credential.parent.mkdir(parents=True)
    credential.write_text('{"version":2,"synthetic":"unchanged"}')
    installed_code = tmp_path / "server/current.py"
    installed_code.write_text("existing code")
    monkeypatch.setattr(updater, "__version__", current)
    monkeypatch.setattr(updater, "_fetch_latest_release", lambda: {
        "tag_name": latest, "assets": [{"name": "release.tar.gz", "browser_download_url": "fixture"}],
    })
    download, backup, apply = Mock(), Mock(), Mock()
    pip, restart = AsyncMock(), AsyncMock()
    monkeypatch.setattr(updater, "_download", download)
    monkeypatch.setattr(updater, "_backup_current", backup)
    monkeypatch.setattr(updater, "_apply", apply)
    monkeypatch.setattr(updater, "_run_streaming", pip)
    monkeypatch.setattr(updater.asyncio, "create_subprocess_exec", restart)
    events = []
    assert not await updater.perform_update(lambda *args, **kwargs: events.append(args), install_dir=tmp_path)
    for operation in (download, backup, apply, pip, restart):
        operation.assert_not_called()
    assert installed_code.read_text() == "existing code"
    assert credential.read_text() == '{"version":2,"synthetic":"unchanged"}'
    assert events[-1][0] == "error"
    assert "inchangé" in events[-1][1]


@pytest.mark.parametrize("current", ["0.5.0-rc.1", "dev", "unknown"])
async def test_direct_update_installs_matching_final_or_replaces_unversioned_development_build(
    tmp_path, monkeypatch, current,
):
    install = tmp_path / "install"
    install.mkdir()
    payload = tmp_path / "payload"
    for name in ["server/pyproject.toml", "server/inky_web/main.py", "client/dist/index.html"]:
        target = payload / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("final release fixture")
    (payload / "client/dist/assets").mkdir()
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz", format=tarfile.USTAR_FORMAT) as tf:
        for child in payload.iterdir():
            tf.add(child, arcname=child.name)
    monkeypatch.setattr(updater, "__version__", current)
    monkeypatch.setattr(updater, "_fetch_latest_release", lambda: {
        "tag_name": "v0.5.0", "assets": [{"name": "release.tar.gz", "browser_download_url": "fixture"}],
    })
    monkeypatch.setattr(updater, "_download", lambda _url, dest: dest.write_bytes(archive.read_bytes()))
    pip = AsyncMock(return_value=0)
    monkeypatch.setattr(updater, "_run_streaming", pip)
    process = Mock(returncode=0, communicate=AsyncMock(return_value=(b"", b"")))
    restart = AsyncMock(return_value=process)
    monkeypatch.setattr(updater.asyncio, "create_subprocess_exec", restart)
    events = []
    assert await updater.perform_update(lambda *args, **kwargs: events.append(args), install_dir=install)
    assert (install / "server/inky_web/main.py").read_text() == "final release fixture"
    assert (install / "client/dist/index.html").read_text() == "final release fixture"
    pip.assert_awaited_once()
    restart.assert_awaited_once_with(
        "sudo", "systemctl", "--no-block", "restart", updater.SERVICE_NAME,
        stdout=updater.asyncio.subprocess.PIPE, stderr=updater.asyncio.subprocess.STDOUT,
    )
    assert events[-1] == ("restarting", "Redémarrage sur v0.5.0…")


async def test_missing_frontend_assets_is_rejected_before_backup_or_apply(tmp_path, monkeypatch):
    def extract_incomplete_payload(_archive, dest):
        for name in ["server/pyproject.toml", "server/inky_web/main.py", "client/dist/index.html"]:
            target = dest / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("fixture")

    monkeypatch.setattr(updater, "_fetch_latest_release", lambda: {
        "tag_name": "v9", "assets": [{"name": "release.tar.gz", "browser_download_url": "fixture"}],
    })
    monkeypatch.setattr(updater, "_download", lambda *_: None)
    monkeypatch.setattr(updater, "_safe_extract", extract_incomplete_payload)
    backup, apply = Mock(), Mock()
    monkeypatch.setattr(updater, "_backup_current", backup)
    monkeypatch.setattr(updater, "_apply", apply)
    events = []
    assert not await updater.perform_update(lambda *args, **kwargs: events.append(args), install_dir=tmp_path)
    backup.assert_not_called()
    apply.assert_not_called()
    assert "Incomplete release payload" in events[-1][1]


@pytest.mark.parametrize("failure", ["json", "download", "archive_bytes", "archive_members", "extension"])
async def test_resource_limit_failure_stops_update_before_mutations_and_cleans_up(
    tmp_path, monkeypatch, failure,
):
    install = tmp_path / "install"
    install.mkdir()
    current = install / "VERSION"
    current.write_text("existing version")
    temporary = tmp_path / "update-temp"
    temporary.mkdir()
    monkeypatch.setattr(updater.tempfile, "mkdtemp", lambda **kwargs: str(temporary))
    monkeypatch.setattr(updater, "__version__", "0.5.0")
    if failure == "json":
        monkeypatch.setattr(updater, "_MAX_JSON_BYTES", 8)
        response = _Response(b" " * 9)
    else:
        monkeypatch.setattr(updater, "_fetch_latest_release", lambda: {
            "tag_name": "v9", "assets": [{
                "name": "release.tar.gz", "browser_download_url": "https://fixture.invalid/release",
            }],
        })
        if failure == "download":
            monkeypatch.setattr(updater, "_MAX_DOWNLOAD_BYTES", 8)
            response = _Response(b"x" * 9)
        else:
            info = tarfile.TarInfo("entry")
            if failure == "archive_bytes":
                info.size = updater._MAX_ARCHIVE_BYTES + 1
            elif failure == "extension":
                info.type = tarfile.XHDTYPE
                info.size = updater._MAX_ARCHIVE_BYTES + 1
            raw = info.tobuf(format=tarfile.GNU_FORMAT)
            if failure == "archive_members":
                monkeypatch.setattr(updater, "_MAX_ARCHIVE_MEMBERS", 1)
                raw += tarfile.TarInfo("second").tobuf()
            response = _Response(gzip.compress(raw))
    monkeypatch.setattr(updater.urllib.request, "urlopen", Mock(return_value=response))
    backup, apply, restore = Mock(), Mock(), Mock()
    pip, restart = AsyncMock(), AsyncMock()
    monkeypatch.setattr(updater, "_backup_current", backup)
    monkeypatch.setattr(updater, "_apply", apply)
    monkeypatch.setattr(updater, "_restore", restore)
    monkeypatch.setattr(updater, "_run_streaming", pip)
    monkeypatch.setattr(updater.asyncio, "create_subprocess_exec", restart)
    events = []
    assert not await updater.perform_update(lambda *args, **kwargs: events.append(args), install_dir=install)
    for operation in (backup, apply, restore, pip, restart):
        operation.assert_not_called()
    assert current.read_text() == "existing version"
    assert not temporary.exists()
    assert events[-1][0] == "error"
    assert response.closed


async def test_valid_release_at_exact_resource_limits_is_installed(tmp_path, monkeypatch):
    install = tmp_path / "install"
    install.mkdir()
    archive = io.BytesIO()
    names = ("server/pyproject.toml", "server/inky_web/main.py", "client/dist/index.html")
    with tarfile.open(fileobj=archive, mode="w:gz", format=tarfile.USTAR_FORMAT) as tf:
        for name in names:
            info = tarfile.TarInfo(name)
            info.size = 4
            tf.addfile(info, io.BytesIO(b"code"))
        directory = tarfile.TarInfo("client/dist/assets")
        directory.type = tarfile.DIRTYPE
        tf.addfile(directory)
    packed = archive.getvalue()
    monkeypatch.setattr(updater, "_MAX_DOWNLOAD_BYTES", len(packed))
    monkeypatch.setattr(updater, "_MAX_ARCHIVE_BYTES", 12)
    monkeypatch.setattr(updater, "_MAX_ARCHIVE_MEMBERS", 4)
    monkeypatch.setattr(updater, "_fetch_latest_release", lambda: {
        "tag_name": "v9", "assets": [{
            "name": "release.tar.gz", "browser_download_url": "https://fixture.invalid/release",
        }],
    })
    response = _Response(packed, str(len(packed)))
    monkeypatch.setattr(updater.urllib.request, "urlopen", Mock(return_value=response))
    pip = AsyncMock(return_value=0)
    monkeypatch.setattr(updater, "_run_streaming", pip)
    process = Mock(returncode=0, communicate=AsyncMock(return_value=(b"", b"")))
    restart = AsyncMock(return_value=process)
    monkeypatch.setattr(updater.asyncio, "create_subprocess_exec", restart)
    events = []
    assert await updater.perform_update(lambda *args, **kwargs: events.append(args), install_dir=install)
    assert all((install / name).read_bytes() == b"code" for name in names)
    assert (install / "client/dist/assets").is_dir()
    pip.assert_awaited_once()
    restart.assert_awaited_once()
    assert events[-1][0] == "restarting"
