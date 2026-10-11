"""Fail-closed factory startup selection; never enables the unfinished runtime.

Selection and CLI guards only read local files. The explicit initializer may
prepare the existing coordinator's durable state, then always exits pending.
Paths/UIDs are installed policy, not environment-overridable dependencies.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from .bootstrap_identity import PREPARED_IDENTITY_FILENAME
from .first_boot import FirstBootCoordinator, FirstBootRefused, FirstBootUncertain
from .initialization_ipc import InitializationIPCClient
from .ownership import credential_epoch

MARKER_PATH = Path("/etc/inky-studio/factory-v1.json")
EXPECTED_DATA_DIR = Path("/var/lib/inky-studio")
EXPECTED_APP_UID = 1000
REQUIRED_ENV = "INKY_STUDIO_FACTORY_REQUIRED"
MAX_MARKER_BYTES = 1024
MAX_CREDENTIAL_BYTES = 8192
MAX_LEDGER_BYTES = 8 * 1024 * 1024
_CODES = frozenset({"factory_runtime_refused", "factory_runtime_uncertain", "factory_runtime_pending"})


class FactoryRuntimeError(Exception):
    """Only fixed, public diagnostics; no underlying exception or secret text."""

    def __init__(self, code: str = "factory_runtime_refused", exit_status: int = 78):
        self.code = code if type(code) is str and code in _CODES else "factory_runtime_refused"
        self.exit_status = 78
        super().__init__(self.code)


@dataclass(frozen=True)
class FactoryRuntimeConfig:
    data_dir: Path
    app_uid: int


def _root_directory(info: os.stat_result) -> None:
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_gid != 0
            or info.st_mode & 0o022):
        raise ValueError


@contextmanager
def _directory(path: Path, *, protected: bool = False,
               leaf_uid: int | None = None) -> Iterator[int]:
    """Walk anchored directory FDs, refusing links even in intermediate paths."""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if protected:
            _root_directory(os.fstat(descriptor))
        for index, component in enumerate(path.parts[1:]):
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK,
                            dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            info = os.fstat(descriptor)
            if leaf_uid is not None and index == len(path.parts) - 2:
                if info.st_uid != leaf_uid or info.st_mode & 0o022:
                    raise ValueError
            elif protected:
                _root_directory(info)
        yield descriptor
    finally:
        os.close(descriptor)


def _exists(name: str | Path, *, directory: int | None = None) -> bool:
    try:
        os.stat(name, dir_fd=directory, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def _fingerprint(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_file(directory: int, name: str, limit: int, *, uid: int | None = None,
               gid: int | None = None, mode: int | None = None) -> bytes:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= limit
                or (uid is not None and info.st_uid != uid)
                or (gid is not None and info.st_gid != gid)
                or (mode is not None and stat.S_IMODE(info.st_mode) != mode)):
            raise ValueError
        chunks = bytearray()
        while len(chunks) <= limit:
            chunk = os.read(descriptor, min(65536, limit + 1 - len(chunks)))
            if not chunk:
                break
            chunks.extend(chunk)
        if (len(chunks) != info.st_size or len(chunks) > limit
                or _fingerprint(os.fstat(descriptor)) != _fingerprint(info)
                or _fingerprint(os.stat(name, dir_fd=directory, follow_symlinks=False)) != _fingerprint(info)):
            raise ValueError
        return bytes(chunks)
    finally:
        os.close(descriptor)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_number(_value):
    raise ValueError


def _json(raw: bytes) -> dict:
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                       parse_float=_reject_number, parse_constant=_reject_number)
    if type(value) is not dict:
        raise ValueError
    return value


def _factory_trace(data_directory: Path) -> bool:
    # Legacy paths may use an existing platform alias (e.g. /var on macOS).
    # Resolve it only for this read-only inspection, never for factory admission.
    path = data_directory.resolve(strict=False) / "provisioning"
    try:
        with _directory(path) as directory:
            if any(_exists(name, directory=directory) for name in (
                ".first-boot.lock", PREPARED_IDENTITY_FILENAME, ".bootstrap-identity.lock",
            )):
                return True
            if not _exists("ownership.sqlite3", directory=directory):
                return False
            try:
                raw = _read_file(directory, "ownership.sqlite3", MAX_LEDGER_BYTES)
            except FileNotFoundError:
                raise ValueError from None
    except FileNotFoundError:
        return False
    if len(raw) < 100 or raw[:16] != b"SQLite format 3\x00":
        raise ValueError
    if int.from_bytes(raw[60:64], "big") != 1:
        return True
    # SQLite never opens the on-disk DB: no journal replay, WAL/SHM creation or
    # disk writes. Supported legacy stores use DELETE, not WAL. A hot DELETE
    # journal is deliberately left to normal legacy startup recovery. There is
    # no supported v1 -> factory-v2 migration that could hide in that journal.
    if raw[18:20] != b"\x01\x01":
        raise ValueError
    connection = sqlite3.connect(":memory:")
    try:
        connection.deserialize(raw)
        connection.execute("PRAGMA trusted_schema = OFF")
        connection.execute("PRAGMA query_only = ON")
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'factory_initialization'",
        ).fetchone() is not None
    finally:
        connection.close()


def select_runtime(data_directory: Path) -> FactoryRuntimeConfig | None:
    """Select installed factory policy without creating files or contacting IPC."""
    try:
        flag = os.environ.get(REQUIRED_ENV)
        if flag is not None and flag != "1":
            raise ValueError
        marker_present = _exists(MARKER_PATH)
        if flag is None:
            if marker_present or _factory_trace(Path(data_directory)):
                raise ValueError
            return None
        if not marker_present or os.environ.get("INKY_STUDIO_DISABLE_AUTH") == "1":
            raise ValueError
        with _directory(MARKER_PATH.parent, protected=True) as directory:
            marker = _json(_read_file(directory, MARKER_PATH.name, MAX_MARKER_BYTES,
                                      uid=0, gid=0, mode=0o644))
        if (set(marker) != {"version", "app_uid", "data_dir"}
                or type(marker["version"]) is not int or marker["version"] != 1
                or type(marker["app_uid"]) is not int or marker["app_uid"] != EXPECTED_APP_UID
                or type(marker["data_dir"]) is not str or marker["data_dir"] != str(EXPECTED_DATA_DIR)
                or os.getuid() != EXPECTED_APP_UID or os.geteuid() != EXPECTED_APP_UID):
            raise ValueError
        path = Path(os.path.abspath(data_directory))
        if path != EXPECTED_DATA_DIR:
            raise ValueError
        with _directory(path, protected=True, leaf_uid=EXPECTED_APP_UID):
            pass
        return FactoryRuntimeConfig(path, EXPECTED_APP_UID)
    except Exception:
        raise FactoryRuntimeError() from None


def _verified_epoch(config: FactoryRuntimeConfig) -> str:
    # Import lazily: auth CLI uses this guard before its normal credential APIs.
    from inky_web import auth

    if select_runtime(config.data_dir) != config:
        raise ValueError
    with _directory(config.data_dir, protected=True, leaf_uid=config.app_uid) as directory:
        record = _json(_read_file(directory, "credentials.json", MAX_CREDENTIAL_BYTES,
                                  uid=config.app_uid, mode=0o600))
    required = {"version", "algorithm", "n", "r", "p", "salt", "hash"}
    if set(record) not in (required, required | {"bootstrap_password"}):
        raise ValueError
    for name, expected in (("version", 2), ("n", auth.SCRYPT_N),
                           ("r", auth.SCRYPT_R), ("p", auth.SCRYPT_P)):
        if type(record[name]) is not int or record[name] != expected:
            raise ValueError
    if type(record["algorithm"]) is not str or record["algorithm"] != "scrypt":
        raise ValueError
    for name, length in (("salt", 32), ("hash", 64)):
        if type(record[name]) is not str or re.fullmatch("[0-9a-f]{" + str(length) + "}", record[name]) is None:
            raise ValueError
    if "bootstrap_password" in record and not auth._valid_password(record["bootstrap_password"]):
        raise ValueError
    # The permissive legacy parser only receives this strictly validated v2
    # shape, so it can neither migrate nor choose arbitrary scrypt parameters.
    credentials = auth._parse_record(config.data_dir / "credentials.json", record)
    return credential_epoch(credentials.salt, credentials.digest)


def initialize_factory(config: FactoryRuntimeConfig) -> NoReturn:
    """Preflight persisted credentials, coordinate once, then always stop closed."""
    try:
        if type(config) is not FactoryRuntimeConfig or type(config.app_uid) is not int:
            raise ValueError
        _verified_epoch(config)
        coordinator = FirstBootCoordinator(
            config.data_dir / "provisioning", InitializationIPCClient(),
            verify_credentials=lambda: _verified_epoch(config),
        )
    except Exception:
        raise FactoryRuntimeError() from None
    try:
        coordinator.initialize()
    except FirstBootRefused:
        raise FactoryRuntimeError() from None
    except FirstBootUncertain:
        raise FactoryRuntimeError("factory_runtime_uncertain") from None
    except Exception:
        raise FactoryRuntimeError("factory_runtime_uncertain") from None
    raise FactoryRuntimeError("factory_runtime_pending")


def guard_legacy_command(data_directory: Path) -> None:
    """Refuse factory password/reset/welcome commands without calling IPC."""
    if select_runtime(data_directory) is not None:
        raise FactoryRuntimeError()


def _check_legacy_main() -> int:
    if sys.argv[1:] != ["--check-legacy"]:
        print("Usage: factory_runtime --check-legacy", file=sys.stderr)
        return 2
    try:
        from inky_web.db import resolve_data_dir

        guard_legacy_command(resolve_data_dir())
    except FactoryRuntimeError as error:
        print(error.code, file=sys.stderr)
        return error.exit_status
    except Exception:
        print("factory_runtime_refused", file=sys.stderr)
        return 78
    return 0


if __name__ == "__main__":
    raise SystemExit(_check_legacy_main())
