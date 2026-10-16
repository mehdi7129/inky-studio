#!/usr/bin/env python3
"""Limited NetworkManager service; stdlib + Debian's system dbus-python only.

Run as inky-network, never through the writable application virtualenv. The
root-owned installer supplies a 0700 state directory and an inky-provisioning
group runtime directory. Socket membership is an authorization boundary: the
application authenticates owners and only forwards confirm from pinned HTTPS.
No shell, subprocess, Wi-Fi secret logging or Wi-Fi secret journal is used.

Supported qualification target: wlan0, WPA2 personal/RSN, IPv4. The journal and
checkpoint cover different failure boundaries. Every incomplete operation is
rolled back on helper restart, including a profile saved immediately before a
crash. A committed activation is reactivated without dbus-client binding before
the checkpoint is removed. Hardware behavior still requires isolated Pi tests.

API references (consulted 2026-09-27):
https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.html
https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.Settings.Connection.html
https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.Device.Wireless.html
"""
from __future__ import annotations

import argparse
import fcntl
import grp
import hashlib
import hmac
import ipaddress
import json
import math
import os
import re
import secrets
import signal
import socket
import socketserver
import stat
import sys
import tempfile
import time
import types
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

REQUEST_LIMIT = 8192
RESPONSE_LIMIT = 16384
JOURNAL_LIMIT = 131072
HISTORY_LIMIT = 64
CHECKPOINT_SECONDS = 180
FINAL_PHASES = {"committed", "rolled_back", "failed"}
PHASES = FINAL_PHASES | {"prepared", "checkpoint", "activating", "waiting", "saving", "detaching", "commit_ready", "rolling_back"}
STATES = {"connecting", "awaiting_confirmation", "committed", "rolled_back", "failed"}
NM = "org.freedesktop.NetworkManager"
ROOT = "/org/freedesktop/NetworkManager"
PERMISSIONS = tuple(f"{NM}.{name}" for name in ("wifi.scan", "network-control", "settings.modify.system", "checkpoint-rollback"))
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
CHECKPOINT_PATH = re.compile(r"/org/freedesktop/NetworkManager/Checkpoint/[0-9]+\Z")
DEVICE_PATH = re.compile(r"/org/freedesktop/NetworkManager/Devices/[0-9]+\Z")
SOCKET_PATH = Path("/run/inky-network/control.sock")
STATE_DIR = Path("/var/lib/inky-network")
GRAPH_PATH = Path("/usr/lib/inkyos/writer-graph.py")
NM_OWNER = re.compile(r":[0-9]+\.[0-9]+\Z")
INSPECTIONS = {"inspect_committed", "inspect_latest_committed"}
REQUIRED_ENV = "INKY_STUDIO_FACTORY_REQUIRED"
WRITER_ENV_NAMES = (
    "INKYOS_WRITER_LEASE_FD",
    "INKYOS_WRITER_ROLE",
    "INKYOS_WRITER_CONTEXT_SHA256",
)
RUNTIME_PATH = Path("/usr/lib/inkyos/factory-runtime-contract.py")
MANIFEST_PATH = Path("/etc/inkyos/factory-runtime-v1.json")
FACTORY_SIGNAL_PATHS = (
    Path("/etc/inky-studio/factory-v1.json"),
    MANIFEST_PATH,
    Path("/run/inkyos-factory/context.json"),
    Path("/run/inkyos-factory"),
)


class FactoryWriterRefused(Exception):
    """Fixed public diagnostic for failed installed factory admission."""

    def __init__(self):
        super().__init__("factory_runtime_refused")


def _require(value):
    if not value:
        raise FactoryWriterRefused()


def factory_signals_present():
    """Read-only detection; partial/unreadable policy must never select legacy."""
    if REQUIRED_ENV in os.environ or any(name.startswith("INKYOS_WRITER_") for name in os.environ):
        return True
    for path in FACTORY_SIGNAL_PATHS:
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return True
        return True
    return False


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_protected(path, mode, limit):
    """Read fixed OS policy through protected FDs before executing its Python."""
    _require(path.is_absolute() and ".." not in path.parts)
    _require(callable(getattr(os, "listxattr", None)))
    parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in (None, *path.parts[1:-1]):
            if part is not None:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                os.close(parent)
                parent = child
            info = os.fstat(parent)
            _require(stat.S_ISDIR(info.st_mode) and (info.st_uid, info.st_gid) == (0, 0)
                     and not stat.S_IMODE(info.st_mode) & 0o7022 and not os.listxattr(parent))
        before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                 and (before.st_uid, before.st_gid) == (0, 0)
                 and stat.S_IMODE(before.st_mode) == mode and 0 < before.st_size <= limit)
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            _require(_stamp(os.fstat(descriptor)) == _stamp(before) and not os.listxattr(descriptor))
            chunks, remaining = [], limit + 1
            while remaining:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            _require(len(raw) == before.st_size and _stamp(before) == _stamp(os.fstat(descriptor))
                     == _stamp(os.stat(path.name, dir_fd=parent, follow_symlinks=False)))
            return raw
        finally:
            os.close(descriptor)
    finally:
        os.close(parent)


def installed_factory_runtime():
    # The helper runs with system Python and cannot import the application.
    # Context, role and inherited-FD checks belong only to this pinned OS API.
    manifest = json.loads(_read_protected(MANIFEST_PATH, 0o644, 16384),
                          object_pairs_hook=unique_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(FactoryWriterRefused()))
    _require(type(manifest) is dict and type(manifest.get("os_module_pins")) is dict)
    expected = manifest["os_module_pins"].get(RUNTIME_PATH.name)
    _require(type(expected) is str and HEX64.fullmatch(expected) is not None)
    raw = _read_protected(RUNTIME_PATH, 0o555, 1024 * 1024)
    _require(hashlib.sha256(raw).hexdigest() == expected)
    module = types.ModuleType("inkyos_factory_runtime_contract")
    module.__file__ = str(RUNTIME_PATH)
    exec(compile(raw, module.__file__, "exec"), module.__dict__)  # noqa: S102 — pinned root-owned bytes
    _require(callable(getattr(module, "writer_guard", None)))
    return module


def installed_setup_peer_guard(connection):
    """Only the pinned OS graph can attest the exact root setup-service peer."""
    try:
        runtime = installed_factory_runtime()
        contract = runtime.load_contract()
        _, _, support, records = runtime.inventories(contract)
        path = str(GRAPH_PATH)[1:]
        with contract.tree() as tree:
            _require(path in support["paths"] and path in records
                     and records[path]["type"] == "file" and records[path]["mode"] == "0555")
            runtime.check_path(tree, path, records)
            raw = tree.read(path, 0o555, 1024 * 1024)
            _require(hashlib.sha256(raw).hexdigest() == records[path]["sha256"])
        graph = types.ModuleType("inkyos_writer_graph")
        graph.__file__ = str(GRAPH_PATH)
        exec(compile(raw, graph.__file__, "exec"), graph.__dict__)  # noqa: S102 — pinned OS support bytes
        return graph.setup_peer_guard(connection)
    except Exception:  # noqa: BLE001 — fixed diagnostics; peer/storage details are private
        raise HelperError("permission_denied") from None


@contextmanager
def setup_peer_scope(connection, guard):
    manager = None
    entered = False
    try:
        manager = guard(connection)
        value = manager.__enter__()
        entered = True
        if value is not None:
            raise HelperError("permission_denied")
    except Exception:  # noqa: BLE001 — proof diagnostics are private
        if entered:
            try:
                manager.__exit__(None, None, None)
            except Exception:  # noqa: BLE001, S110 — fixed diagnostics; peer/storage details are private
                pass
        raise HelperError("permission_denied") from None
    try:
        yield
    except BaseException as error:
        try:
            manager.__exit__(type(error), error, error.__traceback__)
        except Exception:
            if not isinstance(error, Exception):
                raise
            raise HelperError("permission_denied") from None
        raise
    else:
        try:
            manager.__exit__(None, None, None)
        except Exception:  # noqa: BLE001 — fixed diagnostics; peer/storage details are private
            raise HelperError("permission_denied") from None


class StopRequested:
    requested = False

    def request(self, _signum, _frame):
        # Raising here could unwind a live synchronous NM mutation and release
        # SH before its real effects finish. Repeated signals only set this flag.
        self.requested = True


@contextmanager
def factory_signals():
    stop = StopRequested()
    previous = {}
    try:
        for number in (signal.SIGTERM, signal.SIGINT):
            previous[number] = signal.signal(number, stop.request)
        yield stop
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


class HelperError(Exception):
    """Only fixed public codes, never values from a request or D-Bus exception."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def canonical_uuid(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError, TypeError):
        raise HelperError("invalid_request") from None
    return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def parse_request(raw):
    if not isinstance(raw, bytes) or not raw.endswith(b"\n") or raw.count(b"\n") != 1 or len(raw) > REQUEST_LIMIT:
        raise HelperError("invalid_request")
    try:
        value = json.loads(raw, object_pairs_hook=unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError):
        raise HelperError("invalid_request") from None
    validate_request(value)
    return value


def validate_request(value):
    if not isinstance(value, dict) or not isinstance(value.get("op"), str):
        raise HelperError("invalid_request")
    fields = {"scan": {"op", "owner_id"},
              "begin": {"op", "id", "owner_id", "ssid", "security", "password"},
              "status": {"op", "id", "owner_id"},
              "confirm": {"op", "id", "owner_id"},
              "cancel": {"op", "id", "owner_id"},
              # Trusted application-only hooks. Never forward these operations
              # from the BLE command namespace or an unverified HTTP request.
              "health": {"op"},
              "cancel_pending": {"op"},
              "cancel_owner": {"op", "owner_id"},
              "inspect_committed": {"op", "id", "owner_id"},
              "inspect_latest_committed": {"op"}}
    if value["op"] not in fields or set(value) != fields[value["op"]]:
        raise HelperError("invalid_request")
    if "owner_id" in value:
        canonical_uuid(value["owner_id"])
    if value["op"] in {"begin", "status", "confirm", "cancel", "inspect_committed"}:
        canonical_uuid(value["id"])
    if value["op"] == "begin":
        try:
            ssid, password = value["ssid"], value["password"]
            if not isinstance(ssid, str) or not 1 <= len(ssid.encode("utf-8")) <= 32 or "\x00" in ssid:
                raise ValueError
            if value["security"] != "wpa2" or not isinstance(password, str) or "\x00" in password:
                raise ValueError
            encoded = password.encode("utf-8")
            if not 8 <= len(encoded) <= 63 and re.fullmatch(r"[0-9a-fA-F]{64}", password) is None:
                raise ValueError
        except (ValueError, UnicodeError):
            raise HelperError("invalid_request") from None


def fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(path, data):
    staging = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".staging-", delete=False) as output:
            staging = Path(output.name)
            os.fchmod(output.fileno(), 0o600)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(staging, path)
        fsync_directory(path.parent)
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)


def private_read(path, maximum):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as source:
        file_stat = os.fstat(source.fileno())
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > maximum:
            raise HelperError("not_ready")
        os.fchmod(source.fileno(), 0o600)
        return source.read(maximum + 1)


class Journal:
    """Atomic private journal with a local HMAC key and 64 retained results.

    Idempotence is retained for these 64 transaction IDs. Clients must use a new
    random ID for each new intent and never retry an evicted historical command.
    Missing/corrupt existing storage fails closed; it is never silently reset.
    """

    def __init__(self, directory):
        self.directory = Path(directory)
        if self.directory.is_symlink():
            raise HelperError("not_ready")
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.directory.chmod(0o700)
        self.path = self.directory / "journal.json"
        key_path = self.directory / "intent.key"
        try:
            any_existing = any(path.exists() or path.is_symlink() for path in (self.path, key_path))
            if not any_existing:
                self._key = secrets.token_bytes(32)
                atomic_write(key_path, self._key)
                atomic_write(self.path, b'{"v":1,"records":[]}')
            self._key = private_read(key_path, 32)
            if len(self._key) != 32:
                raise HelperError("not_ready")
            data = json.loads(private_read(self.path, JOURNAL_LIMIT), object_pairs_hook=unique_object)
            if not isinstance(data, dict) or set(data) != {"v", "records"} or type(data["v"]) is not int or data["v"] != 1:
                raise ValueError
            if not isinstance(data["records"], list) or len(data["records"]) > HISTORY_LIMIT:
                raise ValueError
            for row in data["records"]:
                self._validate(row)
            if len({row["id"] for row in data["records"]}) != len(data["records"]):
                raise ValueError
            if sum(row["phase"] not in FINAL_PHASES for row in data["records"]) > 1:
                raise ValueError
            self.records = data["records"]
        except (OSError, ValueError, TypeError, KeyError):
            raise HelperError("not_ready") from None

    @staticmethod
    def _validate(row):
        expected = {"id", "owner_id", "intent", "profile_uuid", "previous_uuid", "device", "instance", "checkpoint", "phase", "state", "addresses"}
        metadata = {"commit_boot_id", "commit_nm_unique_owner"}
        if not isinstance(row, dict) or set(row) not in (expected, expected | metadata):
            raise ValueError
        if metadata <= set(row):
            canonical_uuid(row["commit_boot_id"])
            if (row["phase"] != "committed" or row["state"] != "committed"
                    or type(row["commit_nm_unique_owner"]) is not str
                    or NM_OWNER.fullmatch(row["commit_nm_unique_owner"]) is None):
                raise ValueError
        for name in ("id", "owner_id", "profile_uuid"):
            canonical_uuid(row[name])
        if row["previous_uuid"] is not None:
            canonical_uuid(row["previous_uuid"])
        if row["phase"] not in PHASES or row["state"] not in STATES:
            raise ValueError
        if not isinstance(row["intent"], str) or HEX64.fullmatch(row["intent"]) is None:
            raise ValueError
        if not isinstance(row["device"], str) or DEVICE_PATH.fullmatch(row["device"]) is None:
            raise ValueError
        if row["checkpoint"] is not None and (not isinstance(row["checkpoint"], str) or CHECKPOINT_PATH.fullmatch(row["checkpoint"]) is None):
            raise ValueError
        if not isinstance(row["instance"], str) or not 1 <= len(row["instance"]) <= 128:
            raise ValueError
        if not isinstance(row["addresses"], list) or len(row["addresses"]) > 8:
            raise ValueError
        for address in row["addresses"]:
            ipaddress.IPv4Address(address)

    def inspect_records(self):
        """Validate current durable bytes without creating/chmod/writing state."""
        try:
            descriptor = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                before = os.fstat(descriptor)
                if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                        or not 0 < before.st_size <= JOURNAL_LIMIT):
                    raise ValueError
                raw = os.read(descriptor, JOURNAL_LIMIT + 1)
                if (_stamp(os.fstat(descriptor)) != _stamp(before)
                        or _stamp(os.stat(self.path, follow_symlinks=False)) != _stamp(before)
                        or len(raw) != before.st_size):
                    raise ValueError
            finally:
                os.close(descriptor)
            data = json.loads(raw, object_pairs_hook=unique_object,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if (type(data) is not dict or set(data) != {"v", "records"}
                    or type(data["v"]) is not int or data["v"] != 1
                    or type(data["records"]) is not list or len(data["records"]) > HISTORY_LIMIT):
                raise ValueError
            rows = data["records"]
            for row in rows:
                self._validate(row)
            if len({row["id"] for row in rows}) != len(rows):
                raise ValueError
            if sum(row["phase"] not in FINAL_PHASES for row in rows) > 1:
                raise ValueError
            return rows
        except Exception:  # noqa: BLE001 — fixed diagnostics; peer/storage details are private
            raise HelperError("not_ready") from None

    def intention(self, request):
        raw = json.dumps(request, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hmac.new(self._key, raw, hashlib.sha256).hexdigest()

    def get(self, transaction_id):
        return next((row.copy() for row in self.records if row["id"] == transaction_id), None)

    def active(self):
        return next((row.copy() for row in self.records if row["phase"] not in FINAL_PHASES), None)

    def put(self, row):
        self._validate(row)
        rows = [item for item in self.records if item["id"] != row["id"]] + [row.copy()]
        rows = rows[-HISTORY_LIMIT:]
        data = json.dumps({"v": 1, "records": rows}, separators=(",", ":"), allow_nan=False).encode()
        if len(data) > JOURNAL_LIMIT:
            raise HelperError("not_ready")
        try:
            atomic_write(self.path, data)
        except OSError:
            raise HelperError("not_ready") from None
        self.records = rows


class NetworkManagerAdapter:
    """Only this adapter imports dbus. Tests inject a side-effect-free fake."""

    def __init__(self):
        self.factory_mode = False
        self._factory_scan = None
        import dbus

        self.dbus = dbus
        self.bus = dbus.SystemBus(private=True)
        self.manager = self.interface(ROOT, NM)
        self.device = str(self.manager.GetDeviceByIpIface("wlan0", timeout=3))
        properties = self.properties(self.device, NM + ".Device")
        if int(properties["DeviceType"]) != 2 or not bool(properties["Managed"]):
            raise HelperError("not_ready")

    def close(self):
        bus = getattr(self, "bus", None)
        if bus is not None:
            bus.close()

    def interface(self, path, name):
        return self.dbus.Interface(self.bus.get_object(NM, path), name)

    def properties(self, path, name):
        return self.interface(path, "org.freedesktop.DBus.Properties").GetAll(name, timeout=3)

    def permissions(self):
        return {str(key): str(value) for key, value in self.manager.GetPermissions(timeout=3).items()}

    def instance(self):
        # Object paths can be reused after NM/system restart; never trust an old
        # checkpoint path without both service owner and kernel boot identity.
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        return boot + ":" + str(self.bus.get_name_owner(NM))

    def commit_identity(self):
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
        canonical_uuid(boot_id)
        owner = str(self.bus.get_name_owner(NM))
        if NM_OWNER.fullmatch(owner) is None:
            raise HelperError("not_ready")
        return {"commit_boot_id": boot_id, "commit_nm_unique_owner": owner}

    def inspect_persistent(self, row):
        """Read settings and live state only; never activate, scan or repair."""
        first = self.commit_identity()
        # NM object paths may change across boots; the observed interface and
        # persistent profile binding identify wlan0, never a historical path.
        device = self.properties(self.device, NM + ".Device")
        if str(device.get("Interface")) != "wlan0" or int(device.get("DeviceType", 0)) != 2:
            raise HelperError("not_ready")
        matches = []
        settings = self.interface(ROOT + "/Settings", NM + ".Settings")
        for path in settings.ListConnections(timeout=3):
            values = self.interface(path, NM + ".Settings.Connection").GetSettings(timeout=3)
            meta = values.get("connection", {})
            if str(meta.get("uuid")) == row["profile_uuid"]:
                matches.append((str(path), meta))
        if len(matches) != 1:
            raise HelperError("not_ready")
        path, meta = matches[0]
        props = self.properties(path, NM + ".Settings.Connection")
        if (str(meta.get("id")) != "inky-provisioning-" + row["id"]
                or str(meta.get("interface-name")) != "wlan0"
                or str(meta.get("type")) != "802-11-wireless"
                or bool(props.get("Unsaved", True)) or int(props.get("Flags", 5)) & 5
                or not str(props.get("Filename", "")).startswith("/")):
            raise HelperError("not_ready")
        current = self.snapshot()
        active_uuid = current["uuid"]
        if active_uuid is not None:
            canonical_uuid(active_uuid)
        addresses = list(dict.fromkeys(current["addresses"])) if current["activated"] else []
        if len(addresses) > 16:
            raise HelperError("not_ready")
        for address in addresses:
            if str(ipaddress.IPv4Address(address)) != address:
                raise HelperError("not_ready")
        if self.commit_identity() != first:
            raise HelperError("not_ready")
        return {"boot_id": first["commit_boot_id"], "nm_unique_owner": first["commit_nm_unique_owner"],
                "active_profile_uuid": active_uuid, "ipv4": addresses, "profile_persistent": True}

    def snapshot(self):
        device = self.properties(self.device, NM + ".Device")
        active_path = str(device["ActiveConnection"])
        active = self.properties(active_path, NM + ".Connection.Active") if active_path != "/" else {}
        addresses = []
        ip_path = str(device["Ip4Config"])
        if int(device["State"]) == 100 and ip_path != "/":
            for item in self.properties(ip_path, NM + ".IP4Config").get("AddressData", []):
                try:
                    address = ipaddress.IPv4Address(str(item["address"]))
                    if not address.is_unspecified and not address.is_loopback and not address.is_multicast:
                        addresses.append(str(address))
                except (ValueError, KeyError):
                    continue
        return {"uuid": str(active["Uuid"]) if active else None,
                "active_path": active_path,
                "activated": int(device["State"]) == 100 and int(active.get("State", 0)) == 2,
                "failed": int(device["State"]) == 120,
                "addresses": addresses[:8]}

    def scan(self):
        wireless = self.interface(self.device, NM + ".Device.Wireless")
        if getattr(self, "factory_mode", False):
            # RequestScan returns before the scan completes. LastScan is the
            # documented completion observation; retain even an uncertain call.
            baseline = int(self.properties(self.device, NM + ".Device.Wireless")["LastScan"])
            self._factory_scan = (self.instance(), baseline)
        try:
            wireless.RequestScan(self.dbus.Dictionary({}, signature="sv"), timeout=3)
        except self.dbus.DBusException:
            # Cached APs remain useful when NM throttles a repeated scan.
            pass
        found = {}
        for path in wireless.GetAllAccessPoints(timeout=3)[:128]:
            ap = self.properties(path, NM + ".AccessPoint")
            try:
                ssid = bytes(ap["Ssid"]).decode("utf-8")
                if not 1 <= len(ssid.encode("utf-8")) <= 32 or "\x00" in ssid:
                    continue
            except UnicodeError:
                continue
            rsn, wpa, flags = int(ap["RsnFlags"]), int(ap["WpaFlags"]), int(ap["Flags"])
            security = "wpa2" if rsn & 0x100 else "open" if not (rsn or wpa or flags & 1) else "unsupported"
            if not 2400 <= int(ap["Frequency"]) <= 2500:
                security = "unsupported"
            key = (ssid, security)
            strength = min(100, max(0, int(ap["Strength"])))
            if key not in found or strength > found[key]["strength"]:
                found[key] = {"ssid": ssid, "security": security, "strength": strength}
        networks = sorted(found.values(), key=lambda row: -row["strength"])[:64]
        result = {"networks": networks}
        active_ap = str(self.properties(self.device, NM + ".Device.Wireless")["ActiveAccessPoint"])
        if active_ap != "/":
            try:
                result["current_ssid"] = bytes(self.properties(active_ap, NM + ".AccessPoint")["Ssid"]).decode("utf-8")
            except UnicodeError:
                pass
        return result

    def checkpoint_create(self):
        return str(self.manager.CheckpointCreate(self.dbus.Array([self.dbus.ObjectPath(self.device)], signature="o"),
                                                self.dbus.UInt32(CHECKPOINT_SECONDS), self.dbus.UInt32(0), timeout=3))

    def checkpoint_exists(self, path):
        paths = self.properties(ROOT, NM)["Checkpoints"]
        if path not in [str(item) for item in paths]:
            return False
        return [str(item) for item in self.properties(path, NM + ".Checkpoint")["Devices"]] == [self.device]

    def checkpoint_rollback(self, path):
        results = self.manager.CheckpointRollback(self.dbus.ObjectPath(path), timeout=3)
        if set(map(str, results)) != {self.device} or int(results[self.device]) != 0:
            raise HelperError("network_failed")

    def checkpoint_destroy(self, path):
        self.manager.CheckpointDestroy(self.dbus.ObjectPath(path), timeout=3)

    def activate_new(self, row, ssid, password):
        dbus = self.dbus
        connection = {
            "connection": {"id": "inky-provisioning-" + row["id"], "uuid": row["profile_uuid"],
                           "type": "802-11-wireless", "interface-name": "wlan0", "autoconnect": dbus.Boolean(False)},
            "802-11-wireless": {"ssid": dbus.ByteArray(ssid.encode("utf-8")), "mode": "infrastructure", "band": "bg"},
            "802-11-wireless-security": {"key-mgmt": "wpa-psk", "proto": dbus.Array(["rsn"], signature="s"),
                                        "psk": password, "psk-flags": dbus.UInt32(0)},
            "ipv4": {"method": "auto"}, "ipv6": {"method": "auto"},
        }
        typed = dbus.Dictionary({section: dbus.Dictionary(values, signature="sv")
                                 for section, values in connection.items()}, signature="sa{sv}")
        self.manager.AddAndActivateConnection2(typed, dbus.ObjectPath(self.device), dbus.ObjectPath("/"),
                                              dbus.Dictionary({"persist": "memory", "bind-activation": "dbus-client"}, signature="sv"), timeout=3)

    def _profile(self, profile_uuid, transaction_id=None):
        settings = self.interface(ROOT + "/Settings", NM + ".Settings")
        for path in settings.ListConnections(timeout=3):
            connection = self.interface(path, NM + ".Settings.Connection")
            values = connection.GetSettings(timeout=3)
            meta = values.get("connection", {})
            if str(meta.get("uuid")) != profile_uuid:
                continue
            if transaction_id is not None and (str(meta.get("id")) != "inky-provisioning-" + transaction_id or str(meta.get("interface-name")) != "wlan0"):
                raise HelperError("conflict")
            return str(path), connection, values
        return None

    def persist_profile(self, row, password):
        profile = self._profile(row["profile_uuid"], row["id"])
        if profile is None:
            raise HelperError("network_failed")
        _, connection, values = profile
        values["connection"]["autoconnect"] = self.dbus.Boolean(True)
        # GetSettings omits secrets. Supply only the in-memory token for our own
        # freshly created profile, never request secrets from another profile.
        values["802-11-wireless-security"]["psk"] = password
        values["802-11-wireless-security"]["psk-flags"] = self.dbus.UInt32(0)
        connection.UpdateUnsaved(values, timeout=3)
        connection.Save(timeout=3)

    def activate_persistent(self, row):
        profile = self._profile(row["profile_uuid"], row["id"])
        if profile is None:
            raise HelperError("network_failed")
        # Ordinary ActivateConnection has no dbus-client lifetime binding.
        return str(self.manager.ActivateConnection(self.dbus.ObjectPath(profile[0]), self.dbus.ObjectPath(self.device), self.dbus.ObjectPath("/"), timeout=3))

    def delete_profile(self, row):
        profile = self._profile(row["profile_uuid"], row["id"])
        if profile is not None:
            profile[1].Delete(timeout=3)

    def restore_previous(self, previous_uuid):
        profile = self._profile(previous_uuid)
        if profile is not None:
            return str(self.manager.ActivateConnection(self.dbus.ObjectPath(profile[0]), self.dbus.ObjectPath(self.device), self.dbus.ObjectPath("/"), timeout=3))
        return None

    def factory_settled(self, cleanup, committed):
        """Observe NM completion only; this is no physical radio qualification."""
        if self._factory_scan is not None:
            instance, baseline = self._factory_scan
            if (self.instance() != instance
                    or int(self.properties(self.device, NM + ".Device.Wireless")["LastScan"]) <= baseline):
                return False
        if cleanup is not None and self._profile(cleanup["profile_uuid"], cleanup["id"]) is not None:
            return False
        for row in (cleanup, committed[0] if committed is not None else None):
            if row is not None and row["instance"] == self.instance() and row["checkpoint"] is not None:
                checkpoints = self.properties(ROOT, NM)["Checkpoints"]
                if row["checkpoint"] in map(str, checkpoints):
                    return False
        device = self.properties(self.device, NM + ".Device")
        if not bool(device["Managed"]):
            return False
        state, active_path = int(device["State"]), str(device["ActiveConnection"])
        if state == 30 and active_path == "/":
            return committed is None and (cleanup is None or cleanup["previous_uuid"] is None)
        if state != 100 or active_path == "/":
            return False
        active = self.properties(active_path, NM + ".Connection.Active")
        if int(active["State"]) != 2:
            return False
        current = canonical_uuid(str(active["Uuid"]))
        if committed is not None:
            row, expected_path = committed
            return current == row["profile_uuid"] and (expected_path is None or active_path == expected_path)
        if cleanup is None:
            return True
        if current != cleanup["previous_uuid"]:
            return False
        return (not cleanup.get("_restore_required", False)
                or cleanup.get("_restore_path") == active_path)


class Provisioner:
    """Serialized state machine; the socket server and watchdog call one thread."""

    def __init__(self, adapter, journal, *, monotonic=time.monotonic):
        self.adapter, self.journal, self.monotonic = adapter, journal, monotonic
        self.deadline = None
        self._password = None
        self._detached_activation = None
        self._factory_cleanup = None
        self._factory_committed = None
        permissions = adapter.permissions()
        if any(permissions.get(action) != "yes" for action in PERMISSIONS):
            raise HelperError("permission_denied")
        self.instance = adapter.instance()
        self.ready = True
        active = journal.active()
        if active is not None:
            self._rollback(active, "rolled_back")

    def _put(self, row, **updates):
        updated = row | updates
        try:
            self.journal.put(updated)
        except (OSError, HelperError):
            # On an uncertain journal commit, stop all new mutations. NM's own
            # bounded checkpoint still rolls back; restart re-reads the journal.
            self.ready = False
            raise HelperError("not_ready") from None
        return updated

    def _owner_row(self, request):
        row = self.journal.get(request["id"])
        if row is None or row["owner_id"] != request["owner_id"]:
            raise HelperError("not_found")
        return row

    def _result(self, row):
        remaining = 0
        if row["phase"] not in FINAL_PHASES and self.deadline is not None:
            remaining = max(0, math.ceil(self.deadline - self.monotonic()))
        return {"id": row["id"], "state": row["state"], "addresses": row["addresses"], "remaining_seconds": remaining}

    def _same_checkpoint(self, row):
        return (row["instance"] == self.adapter.instance() and row["device"] == self.adapter.device
                and row["checkpoint"] is not None and self.adapter.checkpoint_exists(row["checkpoint"]))

    def _rollback(self, row, state):
        # Retain the original checkpoint before journal finalization. NM profile
        # deletion/reactivation can still be asynchronous after the final write.
        previous_cleanup = self._factory_cleanup
        self._factory_cleanup = row.copy()
        if previous_cleanup is not None and previous_cleanup["id"] == row["id"]:
            for name in ("_restore_required", "_restore_path"):
                if name in previous_cleanup:
                    self._factory_cleanup[name] = previous_cleanup[name]
        self._factory_committed = None
        row = self._put(row, phase="rolling_back", state=state, addresses=[])
        try:
            # Never apply a previous-boot checkpoint path to a new NM instance.
            if self._same_checkpoint(row):
                self.adapter.checkpoint_rollback(row["checkpoint"])
            self.adapter.delete_profile(row)
            current = self.adapter.snapshot()["uuid"]
            if row["previous_uuid"] is not None and current in (None, row["profile_uuid"]):
                self._factory_cleanup["_restore_required"] = True
                self._factory_cleanup["_restore_path"] = None
                restored = self.adapter.restore_previous(row["previous_uuid"])
                if isinstance(restored, str) and restored != "/":
                    self._factory_cleanup["_restore_path"] = restored
            if self._same_checkpoint(row):
                self.adapter.checkpoint_destroy(row["checkpoint"])
        except Exception:  # noqa: BLE001 — adapter errors may contain secrets
            # Keep rolling_back durable and block any second switch. The timer
            # retries targeted cleanup, even if NM vanished during rollback.
            self._password = None
            raise HelperError("network_failed") from None
        self._password = None
        self._detached_activation = None
        self.deadline = None
        return self._put(row, phase=state, state=state, checkpoint=None)

    def tick(self):
        if not self.ready:
            return
        row = self.journal.active()
        if row is None:
            return
        if row["phase"] == "rolling_back":
            self._rollback(row, row["state"])
            return
        if self.deadline is None or self.monotonic() >= self.deadline or not self._same_checkpoint(row):
            self._rollback(row, "rolled_back")
            return
        status = self.adapter.snapshot()
        if status["failed"]:
            self._rollback(row, "failed")
            return
        active = status["uuid"] == row["profile_uuid"] and status["activated"] and bool(status["addresses"])
        if (row["phase"] in {"detaching", "commit_ready"} and active
                and self._detached_activation is not None and status["active_path"] == self._detached_activation):
            row = self._put(row, phase="commit_ready", addresses=status["addresses"])
            try:
                if self.monotonic() >= self.deadline or not self._same_checkpoint(row):
                    self._rollback(row, "rolled_back")
                    return
                self._factory_committed = (row.copy(), self._detached_activation)
                self.adapter.checkpoint_destroy(row["checkpoint"])
                metadata = self.adapter.commit_identity() if hasattr(self.adapter, "commit_identity") else {}
                if metadata and (metadata["commit_boot_id"] + ":" + metadata["commit_nm_unique_owner"] != row["instance"]):
                    raise HelperError("not_ready")
                self._put(row, phase="committed", state="committed", checkpoint=None, **metadata)
                self._password = None
                self.deadline = None
            except Exception:  # noqa: BLE001 — rollback every adapter failure
                if self.ready:
                    self._rollback(self.journal.get(row["id"]), "failed")
                raise HelperError("network_failed") from None
        elif active and row["phase"] == "waiting" and row["state"] != "awaiting_confirmation":
            self._put(row, state="awaiting_confirmation", addresses=status["addresses"])
        elif not active and row["phase"] == "waiting" and row["state"] == "awaiting_confirmation":
            self._put(row, state="connecting", addresses=[])

    def inspect_committed(self, request):
        """No tick, cleanup, journal rewrite, or NetworkManager mutation."""
        validate_request(request)
        if request["op"] not in INSPECTIONS or not self.ready:
            raise HelperError("not_ready")
        try:
            rows = self.journal.inspect_records()
            if any(row["phase"] in FINAL_PHASES and row["state"] != row["phase"] for row in rows):
                raise HelperError("not_ready")
            if any(row["phase"] not in FINAL_PHASES for row in rows):
                raise HelperError("busy")
            if request["op"] == "inspect_committed":
                row = next((item.copy() for item in rows if item["id"] == request["id"]
                            and item["owner_id"] == request["owner_id"]), None)
                if row is None:
                    raise HelperError("not_found")
            else:
                row = next((item.copy() for item in reversed(rows)
                            if item["phase"] == "committed" and item["state"] == "committed"), None)
                if row is None:
                    raise HelperError("not_found")
            if (row["phase"] != "committed" or row["state"] != "committed"
                    or "commit_boot_id" not in row or "commit_nm_unique_owner" not in row):
                raise HelperError("not_ready")
            observed = self.adapter.inspect_persistent(row)
            if (type(observed) is not dict or set(observed) != {"boot_id", "nm_unique_owner", "ipv4",
                    "active_profile_uuid", "profile_persistent"}
                    or observed["profile_persistent"] is not True
                    or type(observed["nm_unique_owner"]) is not str
                    or NM_OWNER.fullmatch(observed["nm_unique_owner"]) is None
                    or type(observed["ipv4"]) is not list or len(observed["ipv4"]) > 16
                    or len(set(observed["ipv4"])) != len(observed["ipv4"])):
                raise HelperError("not_ready")
            canonical_uuid(observed["boot_id"])
            if observed["active_profile_uuid"] is not None:
                canonical_uuid(observed["active_profile_uuid"])
            for address in observed["ipv4"]:
                if type(address) is not str or str(ipaddress.IPv4Address(address)) != address:
                    raise HelperError("not_ready")
            result = {"id": row["id"], "owner_id": row["owner_id"], "state": "committed",
                      "profile_uuid": row["profile_uuid"], "device": "wlan0", **observed,
                      "commit_boot_id": row["commit_boot_id"],
                      "commit_nm_unique_owner": row["commit_nm_unique_owner"]}
            result["observation_sha256"] = hashlib.sha256((json.dumps(
                result, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")).hexdigest()
            return result
        except HelperError:
            raise
        except Exception:  # noqa: BLE001 — fixed diagnostics; peer/storage details are private
            raise HelperError("not_ready") from None

    def handle(self, request):
        validate_request(request)
        if not self.ready:
            raise HelperError("not_ready")
        operation = request["op"]
        if operation in INSPECTIONS:
            # Only Handler can attest the setup-service connection.
            raise HelperError("permission_denied")
        if operation == "health":
            # A capability probe must never scan, advance a pending commit, or
            # trigger rollback. Readiness was established during startup.
            return {"ready": True, "protocol": 1}
        if operation in {"cancel_pending", "cancel_owner"}:
            # Credential rotation/revocation calls this BEFORE changing durable
            # authority. Do not tick first: a detaching/commit_ready transaction
            # must not cross its final commit boundary while being cancelled.
            # Looking up the singleton also covers a lost begin response.
            row = self.journal.active()
            if row is None or (operation == "cancel_owner" and row["owner_id"] != request["owner_id"]):
                return {"cancelled": False}
            self._rollback(row, "rolled_back")
            return {"cancelled": True}
        self.tick()
        if operation == "scan":
            return self.adapter.scan()
        if operation == "begin":
            previous = self.journal.get(request["id"])
            if previous is not None:
                if previous["owner_id"] != request["owner_id"]:
                    raise HelperError("not_found")
                if not hmac.compare_digest(previous["intent"], self.journal.intention(request)):
                    raise HelperError("conflict")
                return self._result(previous)
            if self.journal.active() is not None:
                raise HelperError("busy")
            before = self.adapter.snapshot()
            row = {"id": request["id"], "owner_id": request["owner_id"],
                   "intent": self.journal.intention(request), "profile_uuid": str(uuid4()),
                   "previous_uuid": before["uuid"], "device": self.adapter.device,
                   "instance": self.adapter.instance(), "checkpoint": None,
                   "phase": "prepared", "state": "connecting", "addresses": []}
            row = self._put(row)
            try:
                # Write-ahead above precedes the first NetworkManager mutation.
                self.deadline = self.monotonic() + CHECKPOINT_SECONDS
                checkpoint = self.adapter.checkpoint_create()
                row = self._put(row, checkpoint=checkpoint, phase="checkpoint")
                row = self._put(row, phase="activating")
                self._password = request["password"]
                self.adapter.activate_new(row, request["ssid"], self._password)
                row = self._put(row, phase="waiting")
            except Exception:  # noqa: BLE001 — rollback every adapter failure
                if self.ready:
                    self._rollback(self.journal.get(row["id"]), "failed")
                raise HelperError("network_failed") from None
            return self._result(row)
        row = self._owner_row(request)
        if operation == "status":
            return self._result(row)
        if row["phase"] in FINAL_PHASES:
            return self._result(row)
        if operation == "cancel":
            return self._result(self._rollback(row, "rolled_back"))
        if operation == "confirm":
            if row["phase"] in {"detaching", "commit_ready"}:
                return self._result(row)
            status = self.adapter.snapshot()
            if (row["state"] != "awaiting_confirmation" or not self._same_checkpoint(row)
                    or status["uuid"] != row["profile_uuid"] or not status["activated"]
                    or not status["addresses"] or self._password is None):
                raise HelperError("not_ready")
            if self.deadline is None or self.deadline - self.monotonic() < 10:
                self._rollback(row, "rolled_back")
                raise HelperError("expired")
            row = self._put(row, phase="saving")
            try:
                self.adapter.persist_profile(row, self._password)
                row = self._put(row, phase="detaching")
                self._detached_activation = self.adapter.activate_persistent(row)
                if self._detached_activation == status["active_path"]:
                    # Do not assume an existing activation lost its binding.
                    raise HelperError("network_failed")
                self.tick()
            except Exception:  # noqa: BLE001 — rollback every adapter failure
                if self.ready:
                    self._rollback(self.journal.get(row["id"]), "failed")
                raise HelperError("network_failed") from None
            return self._result(self.journal.get(row["id"]))
        raise HelperError("invalid_request")

    def drain_factory(self):
        """Cancel unfinished work and retain SH while NM remains uncertain.

        A timeout or D-Bus return cannot prove that NM stopped its asynchronous
        effects. No new requests are admitted during this retry loop, and there
        is deliberately no deadline that releases the writer lease on failure.
        """
        while True:
            try:
                # Re-read durable state after an uncertain atomic write. A
                # durable committed profile must never be cancelled on shutdown.
                self.journal = Journal(self.journal.directory)
                row = self.journal.active()
                if row is not None:
                    self._rollback(row, "rolled_back")
                self.journal = Journal(self.journal.directory)
                if self.journal.active() is None:
                    cleanup, committed = self._factory_cleanup, self._factory_committed
                    if cleanup is not None:
                        durable = self.journal.get(cleanup["id"])
                        if durable is None:
                            raise HelperError("not_ready")
                        if durable["phase"] == "committed":
                            committed = (durable | {"checkpoint": cleanup["checkpoint"]}, None)
                            cleanup = None
                    if committed is not None:
                        durable = self.journal.get(committed[0]["id"])
                        if durable is None or durable["phase"] != "committed":
                            raise HelperError("not_ready")
                    if (cleanup is not None and cleanup.get("_restore_required", False)
                            and cleanup.get("_restore_path") is None):
                        restored = self.adapter.restore_previous(cleanup["previous_uuid"])
                        if isinstance(restored, str) and restored != "/":
                            cleanup["_restore_path"] = restored
                    if self.adapter.factory_settled(cleanup, committed):
                        return
            except Exception:  # noqa: BLE001, S110 — uncertainty retains SH
                pass
            time.sleep(0.25)


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(2)
        try:
            request = parse_request(self.rfile.readline(REQUEST_LIMIT + 2))
            if self.server.factory_stop is not None and self.server.factory_stop.requested:
                return
            if request["op"] in INSPECTIONS:
                with setup_peer_scope(self.request, self.server.setup_peer_guard):
                    observation = self.server.provisioner.inspect_committed(request)
                result = {"ok": True, "result": observation}
            else:
                result = {"ok": True, "result": self.server.provisioner.handle(request)}
        except HelperError as error:
            result = {"ok": False, "error": error.code}
        except Exception:  # noqa: BLE001 — never serialize raw D-Bus exceptions
            result = {"ok": False, "error": "network_failed"}
        output = json.dumps(result, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        if len(output) > RESPONSE_LIMIT:
            output = b'{"ok":false,"error":"network_failed"}\n'
        try:
            self.wfile.write(output)
        except OSError:
            pass


class Server(socketserver.UnixStreamServer):
    request_queue_size = 8

    def __init__(self, path, provisioner, *, setup_peer_guard=installed_setup_peer_guard):
        self.setup_peer_guard = setup_peer_guard
        self.provisioner = provisioner
        self.factory_stop = None
        super().__init__(str(path), Handler)

    def verify_request(self, request, client_address):
        return self.factory_stop is None or not self.factory_stop.requested

    def serve_factory(self, stop, poll_interval=1):
        """Stop admitting calls; drain the current synchronous call under SH."""
        self.factory_stop = stop
        self.timeout = poll_interval
        while not stop.requested:
            self.handle_request()
            if not stop.requested:
                self.service_actions()

    def service_actions(self):
        try:
            self.provisioner.tick()
        except Exception:  # noqa: BLE001, S110 — raw exceptions may contain secrets
            # Never print D-Bus errors: they may include request data. Durable
            # pending cleanup remains blocked and will be retried next tick.
            pass

    def handle_error(self, request, client_address):
        pass


def notify_ready(*, required=False):
    """Publish readiness only after the admitted helper socket is listening."""
    address = os.environ.get("NOTIFY_SOCKET")
    if address is None and not required:
        return
    try:
        if (type(address) is not str or not 2 <= len(address.encode("utf-8")) <= 107
                or address[0] not in {"/", "@"} or "\x00" in address):
            raise ValueError
        target = "\x00" + address[1:] if address.startswith("@") else address
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notification:
            notification.settimeout(2)
            notification.sendto(b"READY=1", target)
    except (OSError, TypeError, ValueError, UnicodeError):
        raise HelperError("not_ready") from None


def run_helper(socket_path, state_dir, stop=None):
    def stopping():
        return stop is not None and stop.requested

    if stopping():
        return 0
    os.umask(0o077)
    lock = None
    lock_owned = False
    adapter = None
    provisioner = None
    try:
        # The root-owned unit provides this directory with the socket's group.
        if not socket_path.parent.is_dir() or socket_path.parent.is_symlink():
            raise HelperError("not_ready")
        lock = os.open(socket_path.parent / ".helper.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_owned = True
        if stopping():
            return 0
        journal = Journal(state_dir)
        if stopping():
            return 0
        if stop is None:
            adapter = NetworkManagerAdapter()
        else:
            # Preserve a private bus even if its read-only startup probes fail.
            adapter = NetworkManagerAdapter.__new__(NetworkManagerAdapter)
            adapter.__init__()
        if stopping():
            return 0
        if stop is None:
            provisioner = Provisioner(adapter, journal)
        else:
            adapter.factory_mode = True
            # Startup recovery can start a rollback and then raise. Retain the
            # partial object so its admitted NM effects are still drained.
            provisioner = Provisioner.__new__(Provisioner)
            provisioner.__init__(adapter, journal)
        if stopping():
            return 0
        if socket_path.exists() or socket_path.is_symlink():
            if not stat.S_ISSOCK(socket_path.lstat().st_mode):
                raise HelperError("not_ready")
            socket_path.unlink()
        with Server(socket_path, provisioner) as server:
            os.chown(socket_path, -1, grp.getgrnam("inky-provisioning").gr_gid)
            socket_path.chmod(0o660)
            notify_ready(required=stop is not None)
            if stop is None:
                server.serve_forever(poll_interval=1)
            else:
                server.serve_factory(stop)
    except KeyboardInterrupt:
        return 0
    except Exception:  # noqa: BLE001 — fixed startup diagnostic without secrets
        # Fixed diagnostic only; systemd restarts and journal recovery owns cleanup.
        print("Inky network helper unavailable; check permissions and private state.", flush=True)
        return 1
    finally:
        try:
            if stop is not None and lock_owned:
                drain_factory_shutdown(state_dir, adapter, provisioner)
        finally:
            if lock is not None:
                os.close(lock)
    return 0


def drain_factory_shutdown(state_dir, adapter, provisioner):
    """Retry uncertain startup recovery without releasing either writer lock."""
    while True:
        try:
            if provisioner is not None and hasattr(provisioner, "instance"):
                provisioner.drain_factory()
                adapter.close()
                return
            # A failed constructor did not issue NM mutations, but durable work
            # from an earlier helper may still need rollback. Corrupt/unreadable
            # state cannot establish absence and therefore retains SH as well.
            journal = Journal(state_dir)
            if journal.active() is None:
                if adapter is not None:
                    adapter.close()
                return
            if adapter is not None:
                adapter.close()
            adapter = NetworkManagerAdapter.__new__(NetworkManagerAdapter)
            adapter.__init__()
            adapter.factory_mode = True
            provisioner = Provisioner.__new__(Provisioner)
            provisioner.__init__(adapter, journal)
        except Exception:  # noqa: BLE001, S110 — uncertainty retains SH
            pass
        time.sleep(0.25)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", default=str(SOCKET_PATH))
    parser.add_argument("--state-dir", default=str(STATE_DIR))
    args = parser.parse_args()
    socket_path, state_dir = Path(args.socket), Path(args.state_dir)
    if not factory_signals_present():
        return run_helper(socket_path, state_dir)
    try:
        _require(os.environ.get(REQUIRED_ENV) == "1")
        _require(not any(name.startswith("INKYOS_WRITER_") and name not in WRITER_ENV_NAMES
                         for name in os.environ))
        _require(socket_path == SOCKET_PATH and state_dir == STATE_DIR)
        with factory_signals() as stop:
            runtime = installed_factory_runtime()
            # The OS API acquires its own SH before context/role validation and
            # strictly validates any inherited triplet. It owns lease cleanup.
            with runtime.writer_guard("helper") as lease:
                lease.check()
                # Socket admission, NM completion observations, private bus and
                # .helper.lock all finish before the OS lease leaves this scope.
                return run_helper(socket_path, state_dir, stop)
    except Exception:  # noqa: BLE001 — OS/bootstrap diagnostics are fixed
        print("Inky network helper factory runtime refused.", file=sys.stderr, flush=True)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
