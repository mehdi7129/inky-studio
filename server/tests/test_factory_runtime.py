"""Real temporary files/coordinator, synthetic OS authority and Unix policy.

Portable tests replace only installed UID/path policy and root metadata checks;
they do not qualify Linux service permissions, IPC or a physical first boot.
"""
from __future__ import annotations

import copy
import json
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from inky_web import auth
from inky_web.provisioning import factory_runtime as guard
from inky_web.provisioning.bootstrap_identity import PREPARED_IDENTITY_FILENAME
from inky_web.provisioning.first_boot import FirstBootRefused, FirstBootUncertain
from inky_web.provisioning.ownership import OwnershipStore, credential_epoch

READ_FILE = guard._read_file
ROOT_DIRECTORY = guard._root_directory


class FakeOS:
    def __init__(self):
        self.state = {"status": "authorized"}
        self.receipt = {"receipt_id": str(uuid4()), "digest": "a" * 64}
        self.inspect_calls = 0
        self.begin_calls = []
        self.on_begin = None

    def inspect_initialization(self):
        self.inspect_calls += 1
        return copy.deepcopy(self.state)

    def begin_initialization(self, intent):
        self.begin_calls.append(intent)
        if self.state["status"] == "authorized":
            self.state = {"status": "consumed", "intent": intent, "receipt": self.receipt.copy()}
            status = "newly_consumed"
        else:
            assert self.state["intent"] == intent
            status = "already_consumed"
        reply = {**copy.deepcopy(self.state), "status": status}
        return self.on_begin(reply) if self.on_begin else reply


def write_json(path, value, mode=0o600):
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(mode)


def snapshot(directory):
    return {str(path.relative_to(directory)): path.read_bytes()
            for path in directory.rglob("*") if path.is_file() and not path.is_symlink()}


@pytest.fixture(scope="module")
def record():
    return auth._new_credentials(Path("/synthetic"), "synthetic-factory-password",
                                 bootstrap=True).record()


@pytest.fixture
def configured(tmp_path, monkeypatch, record):
    marker = tmp_path / "etc" / "factory-v1.json"
    marker.parent.mkdir()
    data = tmp_path / "data"
    data.mkdir(mode=0o700)
    uid = os.geteuid()
    value = {"version": 1, "app_uid": uid, "data_dir": str(data)}
    write_json(marker, value, 0o644)
    write_json(data / "credentials.json", record)
    monkeypatch.setattr(guard, "MARKER_PATH", marker)
    monkeypatch.setattr(guard, "EXPECTED_DATA_DIR", data)
    monkeypatch.setattr(guard, "EXPECTED_APP_UID", uid)
    # The temporary tree belongs to the test user; only root's installed
    # ownership policy is injected. Real FD traversal/mode/link/read checks run.
    monkeypatch.setattr(guard, "_root_directory", lambda _info: None)

    def read_file(directory, name, limit, **policy):
        if name == marker.name and policy.get("uid") == 0 and policy.get("gid") == 0:
            policy = policy | {"uid": uid, "gid": os.getegid()}
        return READ_FILE(directory, name, limit, **policy)

    monkeypatch.setattr(guard, "_read_file", read_file)
    monkeypatch.setenv(guard.REQUIRED_ENV, "1")
    monkeypatch.delenv("INKY_STUDIO_DISABLE_AUTH", raising=False)
    adapter = FakeOS()
    monkeypatch.setattr(guard, "InitializationIPCClient", lambda **_hooks: adapter)
    return SimpleNamespace(data=data, marker=marker, marker_value=value,
                           adapter=adapter, uid=uid, root=tmp_path)


def invoke(configured, code="factory_runtime_pending"):
    config = guard.select_runtime(configured.data)
    with pytest.raises(guard.FactoryRuntimeError) as error:
        guard.initialize_factory(config)
    assert error.value.code == code
    assert error.value.exit_status == 78 and str(error.value) == code


def test_legacy_absent_is_read_only(tmp_path, monkeypatch):
    monkeypatch.delenv(guard.REQUIRED_ENV, raising=False)
    monkeypatch.setattr(guard, "MARKER_PATH", tmp_path / "missing-marker")
    monkeypatch.setattr(guard, "InitializationIPCClient", lambda: pytest.fail("No IPC for selection"))
    data = tmp_path / "not-created"
    before = snapshot(tmp_path)
    assert guard.select_runtime(data) is None
    guard.guard_legacy_command(data)
    assert not data.exists() and snapshot(tmp_path) == before


@pytest.mark.parametrize("flag", ["", "0", "true", " 1", "1 ", "01"])
def test_invalid_flag_is_not_absence(configured, monkeypatch, flag):
    monkeypatch.setenv(guard.REQUIRED_ENV, flag)
    before = snapshot(configured.root)
    with pytest.raises(guard.FactoryRuntimeError, match="^factory_runtime_refused$"):
        guard.select_runtime(configured.data)
    assert snapshot(configured.root) == before
    assert configured.adapter.inspect_calls == 0


def test_marker_without_flag_and_required_without_marker_refuse(configured, monkeypatch):
    monkeypatch.delenv(guard.REQUIRED_ENV)
    with pytest.raises(guard.FactoryRuntimeError):
        guard.select_runtime(configured.data)
    monkeypatch.setenv(guard.REQUIRED_ENV, "1")
    configured.marker.unlink()
    with pytest.raises(guard.FactoryRuntimeError):
        guard.select_runtime(configured.data)
    assert configured.adapter.inspect_calls == 0
    assert not (configured.data / "provisioning").exists()


@pytest.mark.parametrize("mutation", [
    {"version": True}, {"version": 1.0}, {"version": 2}, {"app_uid": True},
    {"app_uid": -1}, {"data_dir": "/elsewhere"}, {"data_dir": None}, {"extra": "secret"},
])
def test_closed_marker_types(configured, mutation):
    write_json(configured.marker, configured.marker_value | mutation, 0o644)
    with pytest.raises(guard.FactoryRuntimeError):
        guard.select_runtime(configured.data)
    assert configured.adapter.inspect_calls == 0


@pytest.mark.parametrize("raw", [b"", b"x" * 1025, b"[]", b"null", b"{", b"\xff",
                                 b'{"version":1,"version":1}', b'{"version":NaN}'])
def test_bad_marker_bytes(configured, raw):
    configured.marker.write_bytes(raw)
    with pytest.raises(guard.FactoryRuntimeError):
        guard.select_runtime(configured.data)


@pytest.mark.parametrize("mode", [0o600, 0o664, 0o666, 0o755])
def test_marker_requires_exact_public_mode(configured, mode):
    configured.marker.chmod(mode)
    with pytest.raises(guard.FactoryRuntimeError):
        guard.select_runtime(configured.data)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "directory"])
def test_special_marker_is_rejected_without_blocking(configured, kind):
    target = configured.marker.with_name("source")
    configured.marker.rename(target)
    if kind == "symlink":
        configured.marker.symlink_to(target)
    elif kind == "hardlink":
        os.link(target, configured.marker)
    elif kind == "fifo":
        os.mkfifo(configured.marker)
    else:
        configured.marker.mkdir()
    with pytest.raises(guard.FactoryRuntimeError):
        guard.select_runtime(configured.data)


@pytest.mark.parametrize("uid,gid,mode", [(1, 0, 0o755), (0, 1, 0o755),
                                          (0, 0, 0o775), (0, 0, 0o777)])
def test_installed_parent_policy(uid, gid, mode):
    info = SimpleNamespace(st_mode=stat.S_IFDIR | mode, st_uid=uid, st_gid=gid)
    with pytest.raises(ValueError):
        ROOT_DIRECTORY(info)
    ROOT_DIRECTORY(SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0, st_gid=0))


def test_exact_file_owner_group_are_checked(tmp_path):
    path = tmp_path / "file"
    path.write_bytes(b"x")
    path.chmod(0o644)
    with guard._directory(tmp_path) as directory:
        with pytest.raises(ValueError):
            READ_FILE(directory, path.name, 10, uid=os.geteuid() + 1)
        with pytest.raises(ValueError):
            READ_FILE(directory, path.name, 10, gid=os.getegid() + 1)


def test_auth_uid_and_data_binding(configured, monkeypatch):
    before = snapshot(configured.root)
    monkeypatch.setenv("INKY_STUDIO_DISABLE_AUTH", "1")
    with pytest.raises(guard.FactoryRuntimeError):
        guard.select_runtime(configured.data)
    monkeypatch.delenv("INKY_STUDIO_DISABLE_AUTH")
    with pytest.raises(guard.FactoryRuntimeError):
        guard.select_runtime(configured.data / "other")
    monkeypatch.setattr(guard.os, "geteuid", lambda: configured.uid + 1)
    with pytest.raises(guard.FactoryRuntimeError):
        guard.select_runtime(configured.data)
    assert snapshot(configured.root) == before


def test_normalized_path_allowed_but_symlink_data_refused(configured):
    assert guard.select_runtime(configured.data / ".." / configured.data.name).data_dir == configured.data
    original = configured.data.with_name("actual-data")
    configured.data.rename(original)
    configured.data.symlink_to(original, target_is_directory=True)
    with pytest.raises(guard.FactoryRuntimeError):
        guard.select_runtime(configured.data)


def test_symlink_marker_parent_refused(configured):
    parent = configured.marker.parent
    actual = parent.with_name("actual-marker-parent")
    parent.rename(actual)
    parent.symlink_to(actual, target_is_directory=True)
    with pytest.raises(guard.FactoryRuntimeError):
        guard.select_runtime(configured.data)


@pytest.mark.parametrize("name", [".first-boot.lock", PREPARED_IDENTITY_FILENAME, ".bootstrap-identity.lock"])
def test_factory_traces_prevent_downgrade_without_reading_secrets(configured, monkeypatch, name):
    configured.marker.unlink()
    monkeypatch.delenv(guard.REQUIRED_ENV)
    directory = configured.data / "provisioning"
    directory.mkdir()
    (directory / name).symlink_to(directory / "missing")
    with pytest.raises(guard.FactoryRuntimeError):
        guard.guard_legacy_command(configured.data)
    assert configured.adapter.inspect_calls == 0


def test_legacy_ledger_and_hot_delete_journal_are_untouched(configured, monkeypatch):
    configured.marker.unlink()
    monkeypatch.delenv(guard.REQUIRED_ENV)
    directory = configured.data / "provisioning"
    store = OwnershipStore(directory, lambda: "a" * 64)
    store.close()
    # Abrupt process exit leaves a genuine hot rollback journal. Selection must
    # neither recover it nor reject all legacy stores simply because it exists.
    result = subprocess.run([sys.executable, "-c", """
import os, sqlite3, sys
c = sqlite3.connect(sys.argv[1])
c.execute('PRAGMA cache_size = 1')
c.execute('BEGIN IMMEDIATE')
c.execute('CREATE TABLE interrupted(payload BLOB)')
for _ in range(16):
    c.execute('INSERT INTO interrupted VALUES (zeroblob(65536))')
os._exit(0)
""", str(store.path)], check=False, capture_output=True)
    assert result.returncode == 0
    journal = directory / "ownership.sqlite3-journal"
    assert journal.is_file() and journal.stat().st_size > 512
    before = snapshot(directory)
    assert guard.select_runtime(configured.data) is None
    assert snapshot(directory) == before
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT 1 FROM sqlite_master WHERE name='interrupted'").fetchone() is None


@pytest.mark.parametrize("version,table", [(2, False), (1, True), (0, False), (99, False)])
def test_factory_or_ambiguous_ledger_without_identity_refuses(configured, monkeypatch, version, table):
    configured.marker.unlink()
    monkeypatch.delenv(guard.REQUIRED_ENV)
    directory = configured.data / "provisioning"
    directory.mkdir()
    with sqlite3.connect(directory / "ownership.sqlite3") as connection:
        connection.execute(f"PRAGMA user_version={version}")
        if table:
            connection.execute("CREATE TABLE factory_initialization(id INTEGER)")
    before = snapshot(directory)
    with pytest.raises(guard.FactoryRuntimeError):
        guard.select_runtime(configured.data)
    assert snapshot(directory) == before


@pytest.mark.parametrize("mutation", [
    {"version": True}, {"version": 2.0}, {"version": 1}, {"n": 1 << 30},
    {"r": True}, {"p": 0}, {"algorithm": "other"}, {"salt": "AB" * 16},
    {"salt": "a " * 16}, {"hash": "a" * 63}, {"hash": None},
    {"bootstrap_password": None}, {"bootstrap_password": ""},
    {"bootstrap_password": "\ud800"}, {"extra": "secret"},
])
def test_strict_credentials_reject_before_parser_ipc_or_preparation(configured, record, monkeypatch, mutation):
    write_json(configured.data / "credentials.json", record | mutation)
    monkeypatch.setattr(auth, "_parse_record", lambda *_: pytest.fail("Do not parse invalid v2"))
    before = snapshot(configured.root)
    invoke(configured, "factory_runtime_refused")
    assert configured.adapter.inspect_calls == 0
    assert snapshot(configured.root) == before
    assert not (configured.data / "provisioning").exists()


@pytest.mark.parametrize("raw", [b'{"password":"never-migrate"}', b'{"version":2,"version":2}',
                                 b'{"version":NaN}', b"x" * 8193, b"[]", b"\xff"])
def test_invalid_credential_bytes_never_create_migrate_or_consume(configured, raw, monkeypatch):
    (configured.data / "credentials.json").write_bytes(raw)
    monkeypatch.setattr(auth, "_new_credentials", lambda *_a, **_k: pytest.fail("No generation"))
    invoke(configured, "factory_runtime_refused")
    assert configured.adapter.inspect_calls == 0
    assert (configured.data / "credentials.json").read_bytes() == raw
    assert not (configured.data / "provisioning").exists()


@pytest.mark.parametrize("kind", ["missing", "symlink", "hardlink", "fifo", "public"])
def test_private_credentials_metadata_before_coordinator(configured, kind):
    path = configured.data / "credentials.json"
    target = path.with_name("source")
    if kind == "public":
        path.chmod(0o644)
    else:
        path.rename(target)
        if kind == "symlink":
            path.symlink_to(target)
        elif kind == "hardlink":
            os.link(target, path)
        elif kind == "fifo":
            os.mkfifo(path)
    invoke(configured, "factory_runtime_refused")
    assert configured.adapter.inspect_calls == 0
    assert not (configured.data / "provisioning").exists()


def test_success_is_pending_and_relaunch_reuses_intent_identity_and_credentials(configured):
    credentials_before = (configured.data / "credentials.json").read_bytes()
    invoke(configured)
    directory = configured.data / "provisioning"
    prepared_before = (directory / PREPARED_IDENTITY_FILENAME).read_bytes()
    invoke(configured)
    assert len(set(configured.adapter.begin_calls)) == 1 and len(configured.adapter.begin_calls) == 2
    assert (directory / PREPARED_IDENTITY_FILENAME).read_bytes() == prepared_before
    assert (configured.data / "credentials.json").read_bytes() == credentials_before
    assert not (directory / "identity.json").exists()
    assert not (directory / ".adoption-screen").exists()
    with sqlite3.connect(directory / "ownership.sqlite3") as connection:
        assert connection.execute("SELECT state FROM factory_initialization").fetchone() == ("factory",)
        assert connection.execute("SELECT COUNT(*) FROM owners").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM window").fetchone() == (0,)


def test_prepare_returns_durable_result_without_activating_factory_or_legacy(configured):
    from inky_web.provisioning.first_boot import FirstBootResult

    config = guard.select_runtime(configured.data)
    assert config is not None
    prepared = guard.prepare_factory(config)
    assert isinstance(prepared, FirstBootResult)
    directory = configured.data / "provisioning"
    identity_before = (directory / PREPARED_IDENTITY_FILENAME).read_bytes()
    prepared.ownership.close()
    relaunched = guard.prepare_factory(config)
    assert relaunched.prepared_identity == prepared.prepared_identity
    assert (directory / PREPARED_IDENTITY_FILENAME).read_bytes() == identity_before
    assert not (directory / "identity.json").exists()
    assert not (directory / ".adoption-screen").exists()
    assert not (configured.data / "inky_studio.db").exists()
    assert not (configured.data / "photos").exists()
    with sqlite3.connect(directory / "ownership.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM owners").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM window").fetchone() == (0,)
    relaunched.ownership.close()


def test_lost_begin_response_never_grants_recreation(configured):
    def lose(_reply):
        raise OSError("synthetic private response")

    configured.adapter.on_begin = lose
    invoke(configured, "factory_runtime_uncertain")
    directory = configured.data / "provisioning"
    prepared = (directory / PREPARED_IDENTITY_FILENAME).read_bytes()
    configured.adapter.on_begin = None
    invoke(configured, "factory_runtime_uncertain")
    assert len(configured.adapter.begin_calls) == 2
    assert len(set(configured.adapter.begin_calls)) == 1
    assert (directory / PREPARED_IDENTITY_FILENAME).read_bytes() == prepared
    assert not (directory / "ownership.sqlite3").exists()


def test_callback_rereads_credentials_epoch_without_writing(configured, record, monkeypatch):
    records = [record, record | {"salt": "b" * 32}]
    records = [{k: v for k, v in value.items() if k != "bootstrap_password"} for value in records]
    write_json(configured.data / "credentials.json", records[0])
    seen = []

    class ObserveCoordinator:
        def __init__(self, _path, _adapter, verify_credentials):
            self.verify = verify_credentials

        def initialize(self):
            seen.append(self.verify())
            write_json(configured.data / "credentials.json", records[1])
            current = (configured.data / "credentials.json").read_bytes()
            seen.append(self.verify())
            assert (configured.data / "credentials.json").read_bytes() == current

    monkeypatch.setattr(guard, "FirstBootCoordinator", ObserveCoordinator)
    invoke(configured)
    assert seen == [credential_epoch(bytes.fromhex(r["salt"]), bytes.fromhex(r["hash"])) for r in records]
    assert seen[0] != seen[1]
    assert not (configured.data / "provisioning").exists()


def test_credentials_becoming_invalid_after_begin_remain_uncertain(configured):
    def corrupt(reply):
        (configured.data / "credentials.json").write_text("private invalid contents")
        return reply

    configured.adapter.on_begin = corrupt
    invoke(configured, "factory_runtime_uncertain")
    assert len(configured.adapter.begin_calls) == 1
    # The existing coordinator can persist pending before its next credential
    # callback. It must report uncertainty, retain that state and never adopt.
    with sqlite3.connect(configured.data / "provisioning" / "ownership.sqlite3") as connection:
        assert connection.execute("SELECT state FROM factory_initialization").fetchone() == ("pending",)
        assert connection.execute("SELECT COUNT(*) FROM owners").fetchone() == (0,)
    assert not (configured.data / "provisioning" / "identity.json").exists()


@pytest.mark.parametrize("failure,code", [(FirstBootRefused(), "factory_runtime_refused"),
                                          (FirstBootUncertain(), "factory_runtime_uncertain"),
                                          (OSError("private secret"), "factory_runtime_uncertain")])
def test_coordinator_error_mapping_never_reflects_details(configured, monkeypatch, failure, code):
    class Failure:
        def __init__(self, *_args, **_kwargs):
            pass

        def initialize(self):
            raise failure

    monkeypatch.setattr(guard, "FirstBootCoordinator", Failure)
    invoke(configured, code)


def test_guard_and_cli_never_contact_ipc(configured, monkeypatch, capsys):
    from inky_web import db

    monkeypatch.setattr(guard, "InitializationIPCClient", lambda: pytest.fail("No CLI IPC"))
    monkeypatch.setattr(db, "resolve_data_dir", lambda: configured.data)
    monkeypatch.setattr(sys, "argv", ["factory_runtime", "--check-legacy"])
    before = snapshot(configured.root)
    with pytest.raises(guard.FactoryRuntimeError):
        guard.guard_legacy_command(configured.data)
    assert guard._check_legacy_main() == 78
    assert capsys.readouterr().err == "factory_runtime_refused\n"
    assert snapshot(configured.root) == before
    monkeypatch.setattr(sys, "argv", ["factory_runtime", "secret-unknown-argument"])
    assert guard._check_legacy_main() == 2
    assert "secret" not in capsys.readouterr().err


def test_untrusted_constructed_config_does_not_bypass_selection(configured):
    with pytest.raises(guard.FactoryRuntimeError, match="^factory_runtime_refused$"):
        guard.initialize_factory(guard.FactoryRuntimeConfig(configured.data, configured.uid + 1))
    assert configured.adapter.inspect_calls == 0
