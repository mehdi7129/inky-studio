"""Read-only factory signals shared by startup, assets and maintenance.

A missing or malformed part of the installed contract must never select the
legacy runtime. These are presence checks, not authorization or OS admission.
"""
from __future__ import annotations

import os
from pathlib import Path

WRITER_ENV_NAMES = (
    "INKYOS_WRITER_LEASE_FD",
    "INKYOS_WRITER_ROLE",
    "INKYOS_WRITER_CONTEXT_SHA256",
)
FACTORY_SIGNAL_PATHS = (
    Path("/etc/inky-studio/factory-v1.json"),
    Path("/etc/inkyos/factory-runtime-v1.json"),
    Path("/run/inkyos-factory/context.json"),
    Path("/run/inkyos-factory"),
)


def factory_signals_present() -> bool:
    """Fail closed on partial signals, links or an unreadable public path."""
    if ("INKY_STUDIO_FACTORY_REQUIRED" in os.environ
            or any(name.startswith("INKYOS_WRITER_") for name in os.environ)):
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
