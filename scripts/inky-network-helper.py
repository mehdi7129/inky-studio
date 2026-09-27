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
import socketserver
import stat
import tempfile
import time
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
    if not isinstance(raw, bytes) or not raw.endswith(b"\n") or len(raw) > REQUEST_LIMIT + 1:
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
              "cancel_owner": {"op", "owner_id"}}
    if value["op"] not in fields or set(value) != fields[value["op"]]:
        raise HelperError("invalid_request")
    if "owner_id" in value:
        canonical_uuid(value["owner_id"])
    if value["op"] in {"begin", "status", "confirm", "cancel"}:
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
        if not isinstance(row, dict) or set(row) != expected:
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
        import dbus

        self.dbus = dbus
        self.bus = dbus.SystemBus(private=True)
        self.manager = self.interface(ROOT, NM)
        self.device = str(self.manager.GetDeviceByIpIface("wlan0", timeout=3))
        properties = self.properties(self.device, NM + ".Device")
        if int(properties["DeviceType"]) != 2 or not bool(properties["Managed"]):
            raise HelperError("not_ready")

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
            self.manager.ActivateConnection(self.dbus.ObjectPath(profile[0]), self.dbus.ObjectPath(self.device), self.dbus.ObjectPath("/"), timeout=3)


class Provisioner:
    """Serialized state machine; the socket server and watchdog call one thread."""

    def __init__(self, adapter, journal, *, monotonic=time.monotonic):
        self.adapter, self.journal, self.monotonic = adapter, journal, monotonic
        self.deadline = None
        self._password = None
        self._detached_activation = None
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
        row = self._put(row, phase="rolling_back", state=state, addresses=[])
        try:
            # Never apply a previous-boot checkpoint path to a new NM instance.
            if self._same_checkpoint(row):
                self.adapter.checkpoint_rollback(row["checkpoint"])
            self.adapter.delete_profile(row)
            current = self.adapter.snapshot()["uuid"]
            if row["previous_uuid"] is not None and current in (None, row["profile_uuid"]):
                self.adapter.restore_previous(row["previous_uuid"])
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
                self.adapter.checkpoint_destroy(row["checkpoint"])
                self._put(row, phase="committed", state="committed", checkpoint=None)
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

    def handle(self, request):
        validate_request(request)
        if not self.ready:
            raise HelperError("not_ready")
        operation = request["op"]
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


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(2)
        try:
            request = parse_request(self.rfile.readline(REQUEST_LIMIT + 2))
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

    def __init__(self, path, provisioner):
        self.provisioner = provisioner
        super().__init__(str(path), Handler)

    def service_actions(self):
        try:
            self.provisioner.tick()
        except Exception:  # noqa: BLE001, S110 — raw exceptions may contain secrets
            # Never print D-Bus errors: they may include request data. Durable
            # pending cleanup remains blocked and will be retried next tick.
            pass

    def handle_error(self, request, client_address):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", default="/run/inky-network/control.sock")
    parser.add_argument("--state-dir", default="/var/lib/inky-network")
    args = parser.parse_args()
    socket_path, state_dir = Path(args.socket), Path(args.state_dir)
    os.umask(0o077)
    lock = None
    try:
        # The root-owned unit provides this directory with the socket's group.
        if not socket_path.parent.is_dir() or socket_path.parent.is_symlink():
            raise HelperError("not_ready")
        lock = os.open(socket_path.parent / ".helper.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        journal = Journal(state_dir)
        provisioner = Provisioner(NetworkManagerAdapter(), journal)
        if socket_path.exists() or socket_path.is_symlink():
            if not stat.S_ISSOCK(socket_path.lstat().st_mode):
                raise HelperError("not_ready")
            socket_path.unlink()
        with Server(socket_path, provisioner) as server:
            os.chown(socket_path, -1, grp.getgrnam("inky-provisioning").gr_gid)
            socket_path.chmod(0o660)
            server.serve_forever(poll_interval=1)
    except KeyboardInterrupt:
        return 0
    except Exception:  # noqa: BLE001 — fixed startup diagnostic without secrets
        # Fixed diagnostic only; systemd restarts and journal recovery owns cleanup.
        print("Inky network helper unavailable; check permissions and private state.", flush=True)
        return 1
    finally:
        if lock is not None:
            os.close(lock)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
