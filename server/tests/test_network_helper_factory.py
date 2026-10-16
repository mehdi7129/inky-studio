"""Factory helper entrypoint checks; no real NM, root service or radio."""
from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

HELPER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "inky-network-helper.py"
SPEC = importlib.util.spec_from_file_location("inky_network_helper_factory", HELPER_PATH)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


@pytest.fixture(autouse=True)
def inky_env(monkeypatch, tmp_path):
    # Override conftest's application fixture: this system-Python helper must
    # neither import inky_web nor create its DB as part of qualification.
    for name in tuple(os.environ):
        if name == helper.REQUIRED_ENV or name.startswith("INKYOS_WRITER_"):
            monkeypatch.delenv(name)
    paths = tuple(tmp_path / f"signal-{index}" for index in range(4))
    monkeypatch.setattr(helper, "FACTORY_SIGNAL_PATHS", paths)
    monkeypatch.setattr(helper, "SOCKET_PATH", tmp_path / "socket-dir" / "control.sock")
    monkeypatch.setattr(helper, "STATE_DIR", tmp_path / "state")
    helper.SOCKET_PATH.parent.mkdir()
    monkeypatch.setattr(sys, "argv", [str(HELPER_PATH)])


def assert_no_effects():
    assert not (helper.SOCKET_PATH.parent / ".helper.lock").exists()
    assert not helper.SOCKET_PATH.exists()
    assert not helper.STATE_DIR.exists()


def forbid_effects(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("factory refusal reached journal, D-Bus or socket effects")

    for name in ("Journal", "NetworkManagerAdapter", "Server"):
        monkeypatch.setattr(helper, name, forbidden)


def test_legacy_without_any_signal_does_not_import_os(monkeypatch):
    calls = []
    monkeypatch.setattr(helper, "installed_factory_runtime", lambda: pytest.fail("legacy imported OS"))
    monkeypatch.setattr(helper, "run_helper", lambda socket_path, state_dir: calls.append((socket_path, state_dir)) or 9)
    assert helper.main() == 9
    assert calls == [(helper.SOCKET_PATH, helper.STATE_DIR)]


@pytest.mark.parametrize("source", ["required-empty", "required-zero", *helper.WRITER_ENV_NAMES,
                                   "INKYOS_WRITER_UNKNOWN", *range(4)])
def test_partial_signals_refuse_before_all_effects(monkeypatch, capsys, source):
    forbid_effects(monkeypatch)
    monkeypatch.setattr(helper, "installed_factory_runtime", lambda: pytest.fail("partial policy loaded OS"))
    if isinstance(source, int):
        # Presence includes malformed files and links; authorization stays in OS.
        helper.FACTORY_SIGNAL_PATHS[source].symlink_to("missing-target")
    elif source.startswith("required-"):
        monkeypatch.setenv(helper.REQUIRED_ENV, "" if source.endswith("empty") else "0")
    else:
        monkeypatch.setenv(source, "private-value-must-never-appear")
    assert helper.main() == 78
    assert_no_effects()
    captured = capsys.readouterr()
    assert captured.err == "Inky network helper factory runtime refused.\n"
    assert not captured.out


def test_unknown_writer_variable_refuses_even_with_required_flag(monkeypatch, capsys):
    forbid_effects(monkeypatch)
    monkeypatch.setenv(helper.REQUIRED_ENV, "1")
    monkeypatch.setenv("INKYOS_WRITER_EXTRA", "untrusted")
    monkeypatch.setattr(helper, "installed_factory_runtime", lambda: pytest.fail("unknown variable loaded OS"))
    assert helper.main() == 78
    assert_no_effects()
    assert capsys.readouterr().err == "Inky network helper factory runtime refused.\n"


@pytest.mark.parametrize("argument", ["--socket", "--state-dir"])
def test_factory_rejects_override_of_installed_targets(monkeypatch, tmp_path, argument):
    forbid_effects(monkeypatch)
    monkeypatch.setenv(helper.REQUIRED_ENV, "1")
    monkeypatch.setattr(sys, "argv", [str(HELPER_PATH), argument, str(tmp_path / "override")])
    monkeypatch.setattr(helper, "installed_factory_runtime", lambda: pytest.fail("override loaded OS"))
    assert helper.main() == 78
    assert_no_effects()


@pytest.mark.parametrize("failure_stage", ["loader", "guard", "check"])
def test_os_rejection_is_fixed_and_precedes_all_effects(monkeypatch, capsys, failure_stage):
    forbid_effects(monkeypatch)
    monkeypatch.setenv(helper.REQUIRED_ENV, "1")
    monkeypatch.setenv("INKYOS_WRITER_LEASE_FD", "not-a-descriptor")
    calls = []

    def fail():
        raise RuntimeError("private-contract-or-path-details")

    @contextmanager
    def guard(role):
        calls.append(role)
        assert os.environ["INKYOS_WRITER_LEASE_FD"] == "not-a-descriptor"
        if failure_stage == "guard":
            fail()
        yield SimpleNamespace(check=fail)

    def installed():
        if failure_stage == "loader":
            fail()
        return SimpleNamespace(writer_guard=guard)

    monkeypatch.setattr(helper, "installed_factory_runtime", installed)
    assert helper.main() == 78
    assert_no_effects()
    assert calls == ([] if failure_stage == "loader" else ["helper"])
    assert capsys.readouterr().err == "Inky network helper factory runtime refused.\n"


def runtime_source():
    return b"def writer_guard(role):\n    return ('trusted', role)\n"


@pytest.mark.parametrize("failure", ["duplicate", "duplicate-pin", "missing-pin", "wrong-hash", "nan", "missing-api"])
def test_loader_refuses_untrusted_payload_before_execution(monkeypatch, failure):
    raw = runtime_source()
    digest = hashlib.sha256(raw).hexdigest()
    manifest = json.dumps({"os_module_pins": {helper.RUNTIME_PATH.name: digest}}).encode()
    if failure == "duplicate":
        manifest = b'{"os_module_pins":{},"os_module_pins":{}}'
    elif failure == "duplicate-pin":
        manifest = ('{"os_module_pins":{"' + helper.RUNTIME_PATH.name + '":"' + digest
                    + '","' + helper.RUNTIME_PATH.name + '":"' + digest + '"}}').encode()
    elif failure == "missing-pin":
        manifest = b'{"os_module_pins":{}}'
    elif failure == "wrong-hash":
        raw = b"raise RuntimeError('untrusted module executed')\n"
    elif failure == "nan":
        manifest = b'{"os_module_pins":{},"unused":NaN}'
    else:
        raw = b"other_api = True\n"
        manifest = json.dumps({"os_module_pins": {helper.RUNTIME_PATH.name: hashlib.sha256(raw).hexdigest()}}).encode()
    reads = []

    def read(path, mode, limit):
        reads.append((path, mode, limit))
        return manifest if path == helper.MANIFEST_PATH else raw

    monkeypatch.setattr(helper, "_read_protected", read)
    with pytest.raises((helper.FactoryWriterRefused, ValueError)):
        helper.installed_factory_runtime()
    assert reads[0] == (helper.MANIFEST_PATH, 0o644, 16384)


def test_loader_executes_only_manifest_pinned_bytes(monkeypatch):
    raw = runtime_source()
    manifest = json.dumps({"os_module_pins": {helper.RUNTIME_PATH.name: hashlib.sha256(raw).hexdigest()}}).encode()
    reads = []

    def read(path, mode, limit):
        reads.append((path, mode, limit))
        return manifest if path == helper.MANIFEST_PATH else raw

    monkeypatch.setattr(helper, "_read_protected", read)
    runtime = helper.installed_factory_runtime()
    assert runtime.__file__ == str(helper.RUNTIME_PATH)
    assert runtime.writer_guard("helper") == ("trusted", "helper")
    assert reads == [(helper.MANIFEST_PATH, 0o644, 16384), (helper.RUNTIME_PATH, 0o555, 1024 * 1024)]


class Metadata:
    """Synthetic installed ownership while keeping actual kernel FD/link IO."""

    def __init__(self, original, changes):
        self.original, self.changes = original, changes

    def __getattr__(self, name):
        return self.changes.get(name, getattr(self.original, name))


@pytest.mark.parametrize("tamper", [None, "owner", "parent-owner", "mode", "parent-mode", "hardlink",
                                    "symlink", "parent-link", "xattr", "parent-xattr", "replacement"])
def test_protected_read_uses_fds_and_rejects_metadata_or_replacement(tmp_path, monkeypatch, tamper):
    parent = tmp_path.resolve() / "protected"
    parent.mkdir()
    target = parent / "module.py"
    target.write_bytes(runtime_source())
    target.chmod(0o555)
    original_stat, original_fstat = os.stat, os.fstat
    file_inode, parent_inode = original_stat(target).st_ino, original_stat(parent).st_ino
    if tamper == "hardlink":
        os.link(target, parent / "another-name")
    elif tamper == "symlink":
        target.unlink()
        target.symlink_to(parent / "missing")
    elif tamper == "parent-link":
        alias = tmp_path.resolve() / "alias"
        alias.symlink_to(parent, target_is_directory=True)
        target = alias / target.name

    def metadata(info):
        changes = {"st_uid": 0, "st_gid": 0}
        if stat.S_ISDIR(info.st_mode):
            changes["st_mode"] = stat.S_IFDIR | 0o755
        if info.st_ino == file_inode:
            if tamper == "owner":
                changes["st_uid"] = 1000
            elif tamper == "mode":
                changes["st_mode"] = stat.S_IFREG | 0o755
        if info.st_ino == parent_inode:
            if tamper == "parent-owner":
                changes["st_uid"] = 1000
            elif tamper == "parent-mode":
                changes["st_mode"] = stat.S_IFDIR | 0o777
        return Metadata(info, changes)

    def stat_path(path, *args, **kwargs):
        info = original_stat(path, *args, **kwargs)
        return metadata(info) if kwargs.get("dir_fd") is not None else info

    def attributes(descriptor):
        inode = original_fstat(descriptor).st_ino
        bad = (tamper == "xattr" and inode == file_inode
               or tamper == "parent-xattr" and inode == parent_inode)
        return ["user.untrusted"] if bad else []

    original_read = os.read
    replaced = False

    def read(descriptor, amount):
        nonlocal replaced
        raw = original_read(descriptor, amount)
        if tamper == "replacement" and not replaced and raw:
            replaced = True
            target.unlink()
            target.write_bytes(b"replacement")
        return raw

    with monkeypatch.context() as patch:
        patch.setattr(helper.os, "fstat", lambda descriptor: metadata(original_fstat(descriptor)))
        patch.setattr(helper.os, "stat", stat_path)
        patch.setattr(helper.os, "listxattr", attributes, raising=False)
        patch.setattr(helper.os, "read", read)
        if tamper is None:
            assert helper._read_protected(target, 0o555, 1024) == runtime_source()
        else:
            with pytest.raises((helper.FactoryWriterRefused, OSError)):
                helper._read_protected(target, 0o555, 1024)


def settled_adapter():
    adapter = helper.NetworkManagerAdapter.__new__(helper.NetworkManagerAdapter)
    adapter.device = "/org/freedesktop/NetworkManager/Devices/2"
    adapter._factory_scan = None
    adapter.instance = lambda: "synthetic-boot:synthetic-owner"
    row = {"id": str(uuid4()), "profile_uuid": str(uuid4()), "previous_uuid": str(uuid4()),
           "instance": adapter.instance(), "checkpoint": "/org/freedesktop/NetworkManager/Checkpoint/1"}
    values = {
        helper.NM + ".Device": {"Managed": True, "State": 100, "ActiveConnection": "/active/previous"},
        helper.NM + ".Connection.Active": {"State": 2, "Uuid": row["previous_uuid"]},
        helper.NM: {"Checkpoints": []},
        helper.NM + ".Device.Wireless": {"LastScan": 101},
    }
    adapter.properties = lambda _path, interface: values[interface]
    adapter._profile = lambda *_: None
    return adapter, row, values


def test_failed_bus_creation_can_close_partial_adapter_before_factory_recovery_retry(monkeypatch):
    def unavailable_bus(**_kwargs):
        raise RuntimeError("private D-Bus startup error")

    monkeypatch.setitem(sys.modules, "dbus", SimpleNamespace(SystemBus=unavailable_bus))
    adapter = helper.NetworkManagerAdapter.__new__(helper.NetworkManagerAdapter)
    with pytest.raises(RuntimeError):
        adapter.__init__()
    # An unavailable SystemBus must not strand recovery forever on close() of
    # the same partial object before the next constructor can be attempted.
    adapter.close()


@pytest.mark.parametrize("condition, expected", [
    ("activated-previous", True), ("disconnected", False), ("disconnected-no-previous", True), ("activating", False),
    ("deactivating", False), ("failed", False), ("unmanaged", False),
    ("active-not-activated", False), ("wrong-uuid", False), ("profile-remains", False),
    ("checkpoint-remains", False), ("scan-unfinished", False), ("scan-finished", True),
    ("scan-instance-changed", False), ("restore-accepted-disconnected", False),
    ("restore-old-path", False), ("restore-new-path", True), ("restore-uncertain", False),
])
def test_factory_settled_requires_observed_nm_completion(condition, expected):
    adapter, row, values = settled_adapter()
    device = values[helper.NM + ".Device"]
    active = values[helper.NM + ".Connection.Active"]
    if condition in {"disconnected", "disconnected-no-previous", "restore-accepted-disconnected"}:
        device.update(State=30, ActiveConnection="/")
        if condition == "disconnected-no-previous":
            row["previous_uuid"] = None
    elif condition in {"activating", "deactivating", "failed"}:
        device["State"] = {"activating": 40, "deactivating": 110, "failed": 120}[condition]
    elif condition == "unmanaged":
        device["Managed"] = False
    elif condition == "active-not-activated":
        active["State"] = 1
    elif condition == "wrong-uuid":
        active["Uuid"] = row["profile_uuid"]
    elif condition == "profile-remains":
        adapter._profile = lambda *_: object()
    elif condition == "checkpoint-remains":
        values[helper.NM]["Checkpoints"] = [row["checkpoint"]]
    elif condition.startswith("scan-"):
        adapter._factory_scan = (adapter.instance(), 100)
        if condition == "scan-unfinished":
            values[helper.NM + ".Device.Wireless"]["LastScan"] = 100
        elif condition == "scan-instance-changed":
            adapter.instance = lambda: "different-owner"
    if condition.startswith("restore-"):
        row.update(_restore_required=True, _restore_path="/active/restored")
        if condition == "restore-new-path":
            device["ActiveConnection"] = "/active/restored"
        elif condition == "restore-uncertain":
            row["_restore_path"] = None
    assert adapter.factory_settled(row, None) is expected


@pytest.mark.parametrize("condition, expected", [("committed", True), ("bound-path", False),
                                                 ("activating", False), ("disconnected", False),
                                                 ("checkpoint-remains", False)])
def test_factory_settled_preserves_only_stable_committed_activation(condition, expected):
    adapter, row, values = settled_adapter()
    values[helper.NM + ".Device"]["ActiveConnection"] = "/active/unbound"
    values[helper.NM + ".Connection.Active"]["Uuid"] = row["profile_uuid"]
    adapter._profile = lambda *_: object()  # committed profiles remain on disk
    if condition == "bound-path":
        values[helper.NM + ".Device"]["ActiveConnection"] = "/active/bound"
    elif condition == "activating":
        values[helper.NM + ".Connection.Active"]["State"] = 1
    elif condition == "disconnected":
        values[helper.NM + ".Device"].update(State=30, ActiveConnection="/")
    elif condition == "checkpoint-remains":
        values[helper.NM]["Checkpoints"] = [row["checkpoint"]]
    assert adapter.factory_settled(None, (row, "/active/unbound")) is expected


@pytest.mark.parametrize("uncertain", [False, True])
def test_factory_scan_marks_completion_baseline_before_even_uncertain_request(uncertain):
    adapter, _row, values = settled_adapter()
    adapter.factory_mode = True
    adapter.dbus = SimpleNamespace(Dictionary=lambda value, **_: value, DBusException=RuntimeError)
    values[helper.NM + ".Device.Wireless"]["ActiveAccessPoint"] = "/"
    calls = []

    def request_scan(*_args, **_kwargs):
        calls.append(adapter._factory_scan)
        if uncertain:
            raise RuntimeError("private error")

    adapter.interface = lambda *_: SimpleNamespace(RequestScan=request_scan, GetAllAccessPoints=lambda **_: [])
    assert adapter.scan() == {"networks": []}
    assert calls == [(adapter.instance(), 101)]
    assert not adapter.factory_settled(None, None)
    values[helper.NM + ".Device.Wireless"]["LastScan"] = 102
    assert adapter.factory_settled(None, None)


SUBPROCESS_HARNESS = r'''
import fcntl, importlib.util, os, socket, sys, time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('standalone_helper', sys.argv[1])
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
directory, stage = Path(sys.argv[2]), sys.argv[3]
# Actual systemd notification transport; factory readiness is mandatory.
notification = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
notification.bind(str(directory / 'notify'))
os.environ['NOTIFY_SOCKET'] = str(directory / 'notify')
events = directory / 'events'
def record(name):
    with events.open('a') as output: output.write(name + '\n')
def block(result='NM_returned'):
    record('blocked')
    (directory / 'blocked').touch()
    while not (directory / 'release').exists(): time.sleep(0.01)
    record(result)

class Lease:
    def __init__(self, descriptor): self.descriptor = descriptor
    def check(self): record('lease_checked')
    def fileno(self): return self.descriptor

@contextmanager
def guard(role):
    assert role == 'helper'
    descriptor = os.open(directory / 'admission.lock', os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_SH)
    record('guard_entered')
    try:
        if stage == 'admission': block('validation_returned')
        yield Lease(descriptor)
    finally:
        if stage == 'admission':
            assert not (directory / '.helper.lock').exists()
            assert not (directory / 'state').exists()
            assert not (directory / 'socket').exists()
        else:
            check = os.open(directory / '.helper.lock', os.O_RDWR)
            try: fcntl.flock(check, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally: os.close(check)
        record('guard_leaving')
        os.close(descriptor)

class NM:
    device = '/org/freedesktop/NetworkManager/Devices/2'
    def __init__(self):
        record('NM_constructed')
        self.previous = '00000000-0000-0000-0000-000000000001'
        self.current = {'uuid': self.previous, 'active_path': '/active/old', 'activated': True,
                        'failed': False, 'addresses': ['192.168.1.2']}
        self.profiles, self.checkpoints = {}, set()
        self.failure = None
        if stage == 'startup': block()
        if stage in {'constructor', 'recovery'}:
            row = helper.Journal(directory / 'state').active()
            if row is not None:
                self.profiles[row['profile_uuid']] = {'saved': False, 'bound': True}
                self.checkpoints.add(row['checkpoint'])
                self.current.update(uuid=row['profile_uuid'], active_path='/active/bound', activated=False)
        if stage == 'constructor' and not (directory / 'release').exists():
            (directory / 'blocked').touch()
            raise RuntimeError('uncertain constructor')
        if stage == 'recovery' and not (directory / 'failed-once').exists():
            self.failure = 'delete_profile'
    def called(self, name):
        record(name)
        if self.failure == name:
            self.failure = None
            (directory / 'failed-once').touch()
            raise RuntimeError('uncertain rollback')
    def permissions(self):
        record('permissions')
        return {action: 'yes' for action in helper.PERMISSIONS}
    def instance(self): return 'synthetic-boot:synthetic-owner'
    def snapshot(self):
        if (self.current['active_path'] == '/active/bound' and (directory / 'bound-ready').exists()
                or self.current['active_path'] == '/active/unbound' and (directory / 'persistent-ready').exists()):
            self.current.update(activated=True, addresses=['192.168.1.2'])
        return self.current.copy()
    def scan(self):
        record('scan')
        if stage == 'request': block()
        return {'networks': []}
    def checkpoint_create(self):
        self.called('checkpoint_create')
        path = '/org/freedesktop/NetworkManager/Checkpoint/1'
        self.checkpoints.add(path)
        return path
    def checkpoint_exists(self, path): return path in self.checkpoints
    def checkpoint_rollback(self, path):
        self.called('checkpoint_rollback')
        self.checkpoints.discard(path)
        self.current.update(uuid=None, active_path='/', activated=False, addresses=[])
    def checkpoint_destroy(self, path):
        self.called('checkpoint_destroy')
        self.checkpoints.discard(path)
    def activate_new(self, row, ssid, password):
        self.called('activate_new')
        self.profiles[row['profile_uuid']] = {'saved': False, 'bound': True}
        self.current.update(uuid=row['profile_uuid'], active_path='/active/bound', activated=False, addresses=[])
    def persist_profile(self, row, password):
        self.called('persist_profile')
        self.profiles[row['profile_uuid']]['saved'] = True
    def activate_persistent(self, row):
        self.called('activate_persistent')
        self.profiles[row['profile_uuid']]['bound'] = False
        self.current.update(active_path='/active/unbound', activated=False, addresses=[])
        return '/active/unbound'
    def delete_profile(self, row):
        self.called('delete_profile')
        self.profiles.pop(row['profile_uuid'], None)
    def restore_previous(self, previous):
        self.called('restore_previous')
        self.current.update(uuid=previous, active_path='/active/old', activated=False)
        return '/active/restored'
    def factory_settled(self, cleanup, committed):
        if stage not in {'admission', 'startup', 'request'} and not (directory / 'release').exists():
            record('drain_waiting')
            (directory / 'blocked').touch()
            return False
        if stage == 'committed':
            assert cleanup is None and committed is not None and self.profiles
        elif stage in {'waiting', 'detaching', 'constructor', 'recovery'}:
            assert cleanup is not None and committed is None and not self.profiles and not self.checkpoints
        record('NM_settled')
        return True
    def close(self): record('adapter_closed')

ActualServer = helper.Server
class Server(ActualServer):
    def server_close(self):
        super().server_close()
        record('socket_closed')

helper.SOCKET_PATH, helper.STATE_DIR = directory / 'socket', directory / 'state'
helper.installed_factory_runtime = lambda: SimpleNamespace(writer_guard=guard)
helper.NetworkManagerAdapter = NM
helper.Server = Server
helper.os.chown = lambda *_: None
helper.grp.getgrnam = lambda _: SimpleNamespace(gr_gid=os.getgid())
if stage in {'constructor', 'recovery'}:
    helper.Journal(helper.STATE_DIR).put({
        'id': '00000000-0000-0000-0000-000000000002',
        'owner_id': '00000000-0000-0000-0000-000000000003',
        'profile_uuid': '00000000-0000-0000-0000-000000000004',
        'previous_uuid': '00000000-0000-0000-0000-000000000001',
        'intent': 'f' * 64, 'device': NM.device, 'instance': 'synthetic-boot:synthetic-owner',
        'checkpoint': '/org/freedesktop/NetworkManager/Checkpoint/1',
        'phase': 'waiting', 'state': 'connecting', 'addresses': [],
    })
sys.argv = [str(helper.__file__)]
assert 'inky_web' not in sys.modules
raise SystemExit(helper.main())
'''


def wait_for(path, process, timeout=8):
    deadline = time.monotonic() + timeout
    while not path.exists():
        assert process.poll() is None, process.communicate(timeout=1)
        if time.monotonic() >= deadline:
            pytest.fail("synthetic helper did not reach its blocking call")
        time.sleep(0.01)


def exclusive_available(path):
    descriptor = os.open(path, os.O_RDWR)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("stage", ["admission", "startup", "request"])
def test_factory_retains_shared_lease_until_blocked_nm_finishes_after_repeated_term(stage):
    # Kernel flock + process signals, but only a synthetic NM adapter and no
    # root-owned services. /tmp keeps the Unix socket beneath macOS's limit.
    with tempfile.TemporaryDirectory(prefix="inky-guard-", dir="/tmp") as temporary:
        directory = Path(temporary)
        env = {name: value for name, value in os.environ.items()
               if not name.startswith("INKYOS_WRITER_") and name != helper.REQUIRED_ENV}
        env[helper.REQUIRED_ENV] = "1"
        process = subprocess.Popen([sys.executable, "-I", "-B", "-c", SUBPROCESS_HARNESS,
                                    str(HELPER_PATH), str(directory), stage],
                                   env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        clients = []
        try:
            if stage == "request":
                wait_for(directory / "socket", process)
                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                clients.append(client)
                client.settimeout(2)
                client.connect(str(directory / "socket"))
                client.sendall(json.dumps({"op": "scan", "owner_id": str(uuid4())}).encode() + b"\n")
            wait_for(directory / "blocked", process)
            assert not exclusive_available(directory / "admission.lock")
            for number in (signal.SIGTERM, signal.SIGTERM, signal.SIGINT):
                process.send_signal(number)
                time.sleep(0.05)
                assert process.poll() is None
                assert not exclusive_available(directory / "admission.lock")
                if stage == "admission":
                    assert not (directory / ".helper.lock").exists()
                    assert not (directory / "state").exists()
                else:
                    assert not exclusive_available(directory / ".helper.lock")
            if stage == "request":
                # A request queued after TERM must never reach NM when the
                # current call unblocks, even if its socket connection succeeds.
                pending = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                clients.append(pending)
                pending.settimeout(2)
                pending.connect(str(directory / "socket"))
                pending.sendall(json.dumps({"op": "scan", "owner_id": str(uuid4())}).encode() + b"\n")
            (directory / "release").touch()
            output, errors = process.communicate(timeout=5)
            assert process.returncode == 0, (output, errors)
            assert not output and not errors
            assert exclusive_available(directory / "admission.lock")
            events = (directory / "events").read_text().splitlines()
            if stage == "admission":
                assert events.index("guard_entered") < events.index("validation_returned") < events.index("guard_leaving")
                assert "NM_constructed" not in events and "socket_closed" not in events
                assert not (directory / "socket").exists() and not (directory / "state").exists()
            else:
                assert events.index("guard_entered") < events.index("NM_constructed")
                assert events.index("NM_returned") < events.index("adapter_closed") < events.index("guard_leaving")
            if stage == "startup":
                assert "permissions" not in events and "socket_closed" not in events
                assert not (directory / "socket").exists()
            elif stage == "request":
                assert events.count("scan") == 1
                assert events.index("NM_returned") < events.index("socket_closed") < events.index("adapter_closed")
        finally:
            (directory / "release").touch()
            for client in clients:
                client.close()
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)


def exchange(path, request):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2)
        client.connect(str(path))
        client.sendall(json.dumps(request).encode() + b"\n")
        return json.loads(client.recv(helper.RESPONSE_LIMIT))


@pytest.mark.parametrize("stage", ["scan-async", "waiting", "detaching", "committed", "constructor", "recovery"])
def test_factory_keeps_shared_lease_after_dbus_return_until_observed_async_completion(stage):
    with tempfile.TemporaryDirectory(prefix="inky-drain-", dir="/tmp") as temporary:
        directory = Path(temporary)
        env = {name: value for name, value in os.environ.items()
               if not name.startswith("INKYOS_WRITER_") and name != helper.REQUIRED_ENV}
        env[helper.REQUIRED_ENV] = "1"
        process = subprocess.Popen([sys.executable, "-I", "-B", "-c", SUBPROCESS_HARNESS,
                                    str(HELPER_PATH), str(directory), stage],
                                   env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            if stage not in {"constructor", "recovery"}:
                wait_for(directory / "socket", process)
                owner_id, transaction_id = str(uuid4()), str(uuid4())
                if stage == "scan-async":
                    assert exchange(directory / "socket", {"op": "scan", "owner_id": owner_id}) == {
                        "ok": True, "result": {"networks": []}}
                else:
                    request = {"op": "begin", "id": transaction_id, "owner_id": owner_id,
                               "ssid": "Synthetic", "security": "wpa2", "password": "Synthetic-password"}
                    assert exchange(directory / "socket", request)["result"]["state"] == "connecting"
                    operation = {"id": transaction_id, "owner_id": owner_id}
                    if stage in {"detaching", "committed"}:
                        (directory / "bound-ready").touch()
                        assert exchange(directory / "socket", operation | {"op": "status"})["result"]["state"] == "awaiting_confirmation"
                        assert exchange(directory / "socket", operation | {"op": "confirm"})["result"]["state"] == "awaiting_confirmation"
                    if stage == "committed":
                        (directory / "persistent-ready").touch()
                        assert exchange(directory / "socket", operation | {"op": "status"})["result"]["state"] == "committed"
                # A successful D-Bus/request return already occurred; shutdown
                # must retain SH across the separately observed async drain.
                process.send_signal(signal.SIGTERM)
            wait_for(directory / "blocked", process)
            for number in (signal.SIGTERM, signal.SIGTERM, signal.SIGINT):
                process.send_signal(number)
                time.sleep(0.05)
                assert process.poll() is None
                assert not exclusive_available(directory / "admission.lock")
                assert not exclusive_available(directory / ".helper.lock")
            (directory / "release").touch()
            output, errors = process.communicate(timeout=5)
            failed_startup = stage in {"constructor", "recovery"}
            assert process.returncode == (1 if failed_startup else 0), (output, errors)
            assert not errors
            assert output == (b"Inky network helper unavailable; check permissions and private state.\n" if failed_startup else b"")
            assert exclusive_available(directory / "admission.lock")
            events = (directory / "events").read_text().splitlines()
            assert events.index("NM_settled") < max(index for index, event in enumerate(events) if event == "adapter_closed") < events.index("guard_leaving")
            if stage not in {"constructor", "recovery"}:
                assert events.index("socket_closed") < events.index("NM_settled")
            journal = helper.Journal(directory / "state")
            assert journal.active() is None
            if stage == "committed":
                assert journal.records[-1]["phase"] == "committed"
                assert "delete_profile" not in events and "restore_previous" not in events
            elif stage != "scan-async":
                assert journal.records[-1]["phase"] == "rolled_back"
                assert "delete_profile" in events and "restore_previous" in events
        finally:
            (directory / "release").touch()
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
