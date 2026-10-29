"""Private AC073 admission barrier; contains no photo, credential or job data."""
from __future__ import annotations

import json
import logging
import os
import stat
import uuid
from pathlib import Path

from inky_web.inky.errors import DisplayUnavailableError

NAME = ".display-confirmation.json"
logger = logging.getLogger(__name__)


class ConfirmationBarrier:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _open(self) -> int:
        return os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def load(self) -> str | None:
        try:
            directory = self._open()
            try:
                try:
                    fd = os.open(NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
                except FileNotFoundError:
                    return None
                try:
                    info = os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.geteuid() or info.st_nlink != 1:
                        raise ValueError("unsafe barrier")
                    raw = os.read(fd, 257)
                finally:
                    os.close(fd)
                for state in ("in_progress", "pending"):
                    if raw == self._encode(state):
                        return state
                raise ValueError("invalid barrier")
            finally:
                os.close(directory)
        except (OSError, ValueError) as exc:
            raise self._unavailable() from exc

    @staticmethod
    def _encode(state: str) -> bytes:
        return (json.dumps({"schema_version": 1, "state": state}, sort_keys=True) + "\n").encode()

    @staticmethod
    def _unavailable() -> DisplayUnavailableError:
        return DisplayUnavailableError(
            "L’état de confirmation de l’écran ne peut pas être vérifié. Aucune nouvelle commande n’a été envoyée.",
            "display_confirmation_storage_failed",
        )

    def write(self, state: str) -> None:
        assert state in {"in_progress", "pending"}
        directory = None
        temporary = ".display-confirmation-" + uuid.uuid4().hex
        try:
            # Refuse unsafe/malformed existing state instead of replacing it.
            self.load()
            directory = self._open()
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            with os.fdopen(fd, "wb") as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(self._encode(state))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, NAME, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        except OSError as exc:
            raise self._unavailable() from exc
        finally:
            if directory is not None:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass
                finally:
                    os.close(directory)

    def clear(self) -> None:
        removed = False
        try:
            if self.load() != "in_progress":
                raise ValueError("missing active barrier")
            directory = self._open()
            try:
                os.unlink(NAME, dir_fd=directory)
                removed = True
                os.fsync(directory)
            finally:
                os.close(directory)
        except (OSError, ValueError) as exc:
            if removed:
                # An unsuccessful directory sync is not a committed clear.
                # Restore the conservative barrier before returning the fault.
                try:
                    self.write("in_progress")
                except DisplayUnavailableError:
                    logger.critical("Display confirmation barrier restoration failed; storage requires operator review")
            raise self._unavailable() from exc


def main() -> None:
    """Explicit offline migration of a known old, unconfirmed result; never show."""
    import sys

    from inky_web.db import data_dir

    if sys.argv[1:] != ["--seed-pending"]:
        raise SystemExit("Usage: python -m inky_web.inky.confirmation --seed-pending")
    barrier = ConfirmationBarrier(data_dir())
    state = barrier.load()
    if state not in (None, "pending"):
        raise SystemExit("Existing interrupted display requires review; barrier unchanged.")
    if state is None:
        barrier.write("pending")
    print('{"confirmation":"pending","display_commands_sent":0}')


if __name__ == "__main__":
    main()
