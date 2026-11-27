"""Load the pinned, root-owned InkyOS writer guard before factory effects.

Lease acquisition and inherited-FD validation belong to the shared OS contract.
This module only bootstraps that trust and retains a main lease across nested
startup entries. It never imports OS modules in an ordinary legacy process.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import types
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from .factory_environment import WRITER_ENV_NAMES, factory_signals_present

RUNTIME_PATH = Path("/usr/lib/inkyos/factory-runtime-contract.py")
MANIFEST_PATH = Path("/etc/inkyos/factory-runtime-v1.json")
_main_lease: ContextVar[Any | None] = ContextVar("inky_factory_main_lease", default=None)
_main_environment: ContextVar[tuple | None] = ContextVar("inky_factory_main_environment", default=None)


class FactoryWriterRefused(Exception):
    """Fixed public startup diagnostic, never an underlying path or exception."""

    code = "factory_runtime_refused"
    exit_status = 78

    def __init__(self):
        super().__init__(self.code)


def _require(value: bool) -> None:
    if not value:
        raise FactoryWriterRefused()


def _stamp(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_protected(path: Path, mode: int, limit: int) -> bytes:
    """Anchor every path component before executing any installed OS Python."""
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


def _unique(pairs):
    result = {}
    for name, value in pairs:
        _require(name not in result)
        result[name] = value
    return result


def _installed_runtime() -> types.ModuleType:
    raw_manifest = _read_protected(MANIFEST_PATH, 0o644, 16384)
    value = json.loads(raw_manifest, object_pairs_hook=_unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(FactoryWriterRefused()))
    _require(type(value) is dict and type(value.get("os_module_pins")) is dict)
    expected = value["os_module_pins"].get(RUNTIME_PATH.name)
    _require(type(expected) is str and re.fullmatch(r"[0-9a-f]{64}", expected) is not None)
    raw_module = _read_protected(RUNTIME_PATH, 0o555, 1024 * 1024)
    _require(hashlib.sha256(raw_module).hexdigest() == expected)
    module = types.ModuleType("inkyos_factory_runtime_contract")
    module.__file__ = str(RUNTIME_PATH)
    exec(compile(raw_module, module.__file__, "exec"), module.__dict__)
    _require(callable(getattr(module, "writer_guard", None)))
    return module


def _environment_snapshot() -> tuple:
    _require(os.environ.get("INKY_STUDIO_FACTORY_REQUIRED") == "1")
    _require(not any(name.startswith("INKYOS_WRITER_") and name not in WRITER_ENV_NAMES
                     for name in os.environ))
    return tuple((name, os.environ.get(name)) for name in WRITER_ENV_NAMES)


def validate_inherited_main_lease() -> Any | None:
    """Check an existing lease only; never acquire or import OS authority."""
    current = _main_lease.get()
    if current is not None:
        try:
            _require(_environment_snapshot() == _main_environment.get())
            current.check()
        except Exception:
            raise FactoryWriterRefused() from None
    return current


@contextmanager
def main_writer_guard() -> Iterator[Any | None]:
    """Keep one main lease through startup, admitted workers and final drain."""
    current = validate_inherited_main_lease()
    if current is not None:
        yield current
        return
    if not factory_signals_present():
        yield None
        return
    with ExitStack() as stack:
        try:
            _environment_snapshot()
            runtime = _installed_runtime()
            lease = stack.enter_context(runtime.writer_guard("main"))
            _require(callable(getattr(lease, "check", None))
                     and callable(getattr(lease, "fileno", None)))
            lease.check()
            snapshot = _environment_snapshot()
        except Exception:
            raise FactoryWriterRefused() from None
        token = _main_lease.set(lease)
        environment_token = _main_environment.set(snapshot)
        try:
            yield lease
        finally:
            _main_environment.reset(environment_token)
            _main_lease.reset(token)
