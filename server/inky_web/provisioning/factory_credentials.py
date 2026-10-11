"""Serialize fresh Studio credentials to a private pipe; never publish them.

This is not initialization authority. InkyOS owns the one-time root permission,
exclusive publication and subsequent IPC-A authorization. No environment value
or existing application state is consulted by this serializer.
"""
from __future__ import annotations

import json
import os
import secrets
import stat
import sys
from pathlib import Path

MAX_OUTPUT_BYTES = 8192  # Includes the final LF; agrees with the factory guard.
PASSWORD_LENGTH = 16
_USAGE = b"factory_credentials_usage\n"
_FAILED = b"factory_credentials_failed\n"


def emit_v2() -> bytes:
    """Generate a new record in memory, using Studio's fixed credential format."""
    # Keep application dependency/import failures inside the CLI's fixed error
    # boundary, and do not load them until the output descriptor is validated.
    from inky_web import auth

    password = "".join(secrets.choice(auth.PASSWORD_ALPHABET) for _ in range(PASSWORD_LENGTH))
    # _new_credentials only generates salt/verifier; this path is metadata in
    # Credentials, never an opened file or a caller-selectable destination.
    credentials = auth._new_credentials(Path("/var/lib/inky-studio"), password, bootstrap=True)
    payload = json.dumps(credentials.record(), ensure_ascii=True, allow_nan=False,
                         separators=(",", ":")).encode("ascii") + b"\n"
    if len(payload) > MAX_OUTPUT_BYTES:
        raise ValueError
    return payload


def _diagnostic(message: bytes) -> None:
    try:
        os.write(2, message)
    except OSError:
        pass


def main() -> int:
    # Check before generating any password or salt. fstat can establish FIFO
    # type, not privacy: the root caller must supply its own private pipe.
    try:
        if sys.argv[1:] != ["--emit-v2"] or not stat.S_ISFIFO(os.fstat(1).st_mode):
            raise ValueError
    except (OSError, ValueError):
        _diagnostic(_USAGE)
        return 64
    try:
        payload = emit_v2()
        remaining = memoryview(payload)
        while remaining:
            written = os.write(1, remaining)
            if written <= 0:
                raise OSError
            remaining = remaining[written:]
    except Exception:
        # A prefix may already have reached the private pipe. The caller must
        # discard it on nonzero exit; it is never reflected in diagnostics.
        _diagnostic(_FAILED)
        return 70
    # os.write is unbuffered: there is no Python stdout buffer left to flush.
    # The root parent still requires EOF and successful child reaping.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
