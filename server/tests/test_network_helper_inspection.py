"""Setup-only network observations: actual sockets, fake NM, no radio."""
import hashlib
import json
import socket
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

from tests.test_network_helper import FakeNM, begin_request, helper

BOOT = "11111111-1111-4111-8111-111111111111"
NEXT_BOOT = "22222222-2222-4222-8222-222222222222"


class ObservedNM(FakeNM):
    def __init__(self):
        super().__init__()
        self.service_instance = BOOT + ":" + ":1.42"
        self.current_boot, self.current_owner = BOOT, ":1.42"
        self.persistent_valid = True

    def commit_identity(self):
        return {"commit_boot_id": self.current_boot, "commit_nm_unique_owner": self.current_owner}

    def inspect_persistent(self, row):
        if not self.persistent_valid:
            raise RuntimeError("private NM diagnostic")
        assert self.profiles[row["profile_uuid"]]["saved"]
        return {"boot_id": self.current_boot, "nm_unique_owner": self.current_owner,
                "ipv4": self.current["addresses"], "active_profile_uuid": self.current["uuid"],
                "profile_persistent": True}


@pytest.fixture
def committed(tmp_path):
    journal = helper.Journal(tmp_path / "network")
    nm = ObservedNM()
    nm.journal = journal
    engine = helper.Provisioner(nm, journal, monotonic=lambda: 1000)
    request = begin_request()
    engine.handle(request)
    nm.finish_activation()
    engine.tick()
    engine.handle({"op": "confirm", "id": request["id"], "owner_id": request["owner_id"]})
    nm.finish_activation()
    engine.tick()
    assert journal.get(request["id"])["phase"] == "committed"
    return engine, nm, request


def query(request):
    return {"op": "inspect_committed", "id": request["id"], "owner_id": request["owner_id"]}


def test_historical_commit_and_current_observation_readonly(committed, monkeypatch):
    engine, nm, request = committed
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
              for p in engine.journal.directory.iterdir()}
    monkeypatch.setattr(engine, "tick", lambda: pytest.fail("inspection cannot advance mutations"))
    nm.current_boot, nm.current_owner = NEXT_BOOT, ":1.99"
    nm.current.update(uuid=None, addresses=[], activated=False)
    result = engine.inspect_committed(query(request))
    assert result["commit_boot_id"] == BOOT and result["commit_nm_unique_owner"] == ":1.42"
    assert result["boot_id"] == NEXT_BOOT and result["nm_unique_owner"] == ":1.99"
    assert result["ipv4"] == [] and result["active_profile_uuid"] is None
    digest = result.pop("observation_sha256")
    assert digest == hashlib.sha256((json.dumps(result, sort_keys=True, ensure_ascii=True,
                                               separators=(",", ":")) + "\n").encode("ascii")).hexdigest()
    assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
                      for p in engine.journal.directory.iterdir()}


def test_latest_no_pending_fallback(committed):
    engine, _, request = committed
    assert engine.inspect_committed({"op": "inspect_latest_committed"})["id"] == request["id"]
    pending = engine.journal.get(request["id"])
    pending.pop("commit_boot_id")
    pending.pop("commit_nm_unique_owner")
    pending.update(id=str(uuid4()), phase="waiting", state="connecting")
    engine.journal.put(pending)
    with pytest.raises(helper.HelperError, match="^busy$"):
        engine.inspect_committed({"op": "inspect_latest_committed"})
    with pytest.raises(helper.HelperError, match="^busy$"):
        engine.inspect_committed(query(request))


@pytest.mark.parametrize("mode", ["old_metadata", "corrupt", "missing", "persistent", "wrong_owner", "wrong_id"])
def test_unprovable_no_fallback_no_repair(committed, mode):
    engine, nm, request = committed
    expected, request = "not_ready", query(request)
    if mode == "old_metadata":
        row = engine.journal.get(request["id"])
        row.pop("commit_boot_id")
        row.pop("commit_nm_unique_owner")
        engine.journal.put(row)
    elif mode == "corrupt":
        engine.journal.path.write_bytes(b'{"v":1,"records":[')
    elif mode == "missing":
        engine.journal.path.unlink()
    elif mode == "persistent":
        nm.persistent_valid = False
    else:
        request["owner_id" if mode == "wrong_owner" else "id"] = str(uuid4())
        expected = "not_found"
    before = {p.name: p.read_bytes() for p in engine.journal.directory.iterdir()}
    with pytest.raises(helper.HelperError, match="^" + expected + "$"):
        engine.inspect_committed(request)
    assert before == {p.name: p.read_bytes() for p in engine.journal.directory.iterdir()}


def test_app_handle_cannot_inspect(committed):
    engine, _, request = committed
    with pytest.raises(helper.HelperError, match="permission_denied"):
        engine.handle(query(request))


@pytest.mark.parametrize("bad", [{"op": "inspect_latest_committed", "owner_id": "a"},
                                 {"op": "inspect_committed", "id": "a", "owner_id": "b"},
                                 {"op": "inspect_latest_committed", "password": "never"}])
def test_closed_grammar(bad):
    with pytest.raises(helper.HelperError, match="invalid_request"):
        helper.parse_request(json.dumps(bad).encode() + b"\n")


@pytest.mark.parametrize("mode", ["allow", "reject", "boolean", "exit_failure"])
def test_socket_exact_setup_guard(committed, mode):
    engine, _, request = committed
    events = []
    @contextmanager
    def guard(connection):
        assert connection.fileno() >= 0
        assert connection.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) == socket.SOCK_STREAM
        events.append("entered")
        if mode == "reject":
            raise RuntimeError("private PID1 proof diagnostic")
        try:
            yield True if mode == "boolean" else None
        finally:
            events.append("released")
            if mode == "exit_failure":
                raise RuntimeError("private graph diagnostic")
    with tempfile.TemporaryDirectory(prefix="inky-inspect-", dir="/tmp") as folder:
        path = Path(folder) / "socket"
        with helper.Server(path, engine, setup_peer_guard=guard) as server:
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(3)
                connection.connect(str(path))
                connection.sendall(json.dumps(query(request)).encode() + b"\n")
                raw = connection.makefile("rb").readline(16385)
            thread.join(3)
            assert not thread.is_alive()
    result = json.loads(raw)
    assert result["ok"] is (mode == "allow")
    if mode == "allow":
        assert result["result"]["id"] == request["id"]
    else:
        assert result == {"ok": False, "error": "permission_denied"}
    assert events[0] == "entered"


def test_empty_not_found(tmp_path):
    journal, nm = helper.Journal(tmp_path / "network"), ObservedNM()
    nm.journal = journal
    engine = helper.Provisioner(nm, journal, monotonic=lambda: 1000)
    with pytest.raises(helper.HelperError, match="^not_found$"):
        engine.inspect_committed({"op": "inspect_latest_committed"})


@pytest.mark.parametrize("mode", ["valid", "duplicate", "wrong_id", "wrong_interface", "unsaved", "volatile", "no_filename", "nm_restarted"])
def test_actual_adapter_readonly_persistent_profile_checks(committed, mode):
    engine, _, request = committed
    row = engine.journal.get(request["id"])
    adapter = helper.NetworkManagerAdapter.__new__(helper.NetworkManagerAdapter)
    adapter.device = "/org/freedesktop/NetworkManager/Devices/7"
    meta = {"uuid": row["profile_uuid"], "id": "inky-provisioning-" + row["id"],
            "type": "802-11-wireless", "interface-name": "wlan0"}
    props = {"Unsaved": False, "Filename": "/etc/NetworkManager/system-connections/inky.nmconnection", "Flags": 0}
    if mode == "wrong_id":
        meta["id"] = "arbitrary"
    elif mode == "wrong_interface":
        meta["interface-name"] = "eth0"
    elif mode == "unsaved":
        props["Unsaved"] = True
    elif mode == "volatile":
        props["Flags"] = 4
    elif mode == "no_filename":
        props["Filename"] = ""
    class Readonly:
        def ListConnections(self, **_):
            return ["/settings/one", "/settings/two"] if mode == "duplicate" else ["/settings/one"]
        def GetSettings(self, **_):
            return {"connection": meta}
    calls = []
    def interface(path, name):
        calls.append((path, name))
        assert name in {helper.NM + ".Settings", helper.NM + ".Settings.Connection"}
        return Readonly()
    adapter.interface = interface
    adapter.properties = lambda path, _: ({"Interface": "wlan0", "DeviceType": 2}
                                          if path == adapter.device else props)
    identities = iter([{"commit_boot_id": NEXT_BOOT, "commit_nm_unique_owner": ":1.99"},
                       {"commit_boot_id": NEXT_BOOT, "commit_nm_unique_owner": ":1.100" if mode == "nm_restarted" else ":1.99"}])
    adapter.commit_identity = lambda: next(identities)
    adapter.snapshot = lambda: {"uuid": None, "addresses": [], "activated": False}
    if mode == "valid":
        observation = adapter.inspect_persistent(row)
        assert observation["profile_persistent"] is True and observation["ipv4"] == []
        assert observation["active_profile_uuid"] is None and calls
    else:
        with pytest.raises(helper.HelperError, match="not_ready"):
            adapter.inspect_persistent(row)


def test_setup_graph_loaded_through_pinned_support_inventory(monkeypatch):
    from types import SimpleNamespace
    raw = b'def setup_peer_guard(connection):\n    return connection\n'
    path = str(helper.GRAPH_PATH)[1:]
    record = {"type": "file", "mode": "0555", "sha256": hashlib.sha256(raw).hexdigest()}
    events = []
    class Tree:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            events.append("tree_closed")
        def read(self, observed_path, mode, limit):
            assert (observed_path, mode, limit) == (path, 0o555, 1024 * 1024)
            events.append("read")
            return raw
    contract = SimpleNamespace(tree=Tree)
    runtime = SimpleNamespace(load_contract=lambda: contract,
                              inventories=lambda _: (None, None, {"paths": [path]}, {path: record}),
                              check_path=lambda tree, observed_path, records: events.append("checked"))
    monkeypatch.setattr(helper, "installed_factory_runtime", lambda: runtime)
    sentinel = object()
    assert helper.installed_setup_peer_guard(sentinel) is sentinel
    assert events == ["checked", "read", "tree_closed"]
    record["sha256"] = "0" * 64
    with pytest.raises(helper.HelperError, match="permission_denied"):
        helper.installed_setup_peer_guard(sentinel)


def test_readiness_actual_datagram_after_listen(monkeypatch, committed):
    engine, _, _ = committed
    with tempfile.TemporaryDirectory(prefix="inky-ready-", dir="/tmp") as folder:
        address = str(Path(folder) / "notify")
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver:
            receiver.bind(address)
            receiver.settimeout(2)
            monkeypatch.setenv("NOTIFY_SOCKET", address)
            with helper.Server(Path(folder) / "helper", engine):
                helper.notify_ready(required=True)
                assert receiver.recv(128) == b"READY=1"


@pytest.mark.parametrize("address", [None, "", "relative", "@", "/a\x00b", "/" + "a" * 108])
def test_factory_readiness_missing_or_bad_address_refused(monkeypatch, address):
    if address is None:
        monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
        helper.notify_ready(required=False)
    else:
        if "\x00" in address:
            # Environment variables cannot contain NUL even before validation.
            monkeypatch.setattr(helper.os, "environ", {"NOTIFY_SOCKET": address})
        else:
            monkeypatch.setenv("NOTIFY_SOCKET", address)
    with pytest.raises(helper.HelperError, match="not_ready"):
        helper.notify_ready(required=True)


def test_factory_readiness_delivery_failure_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("NOTIFY_SOCKET", str(tmp_path / "missing"))
    with pytest.raises(helper.HelperError, match="not_ready"):
        helper.notify_ready(required=True)
