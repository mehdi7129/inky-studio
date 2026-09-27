"""Local application credentials, durable password rotation and cookie sessions.

Personalized and migrated passwords are stored only as salted scrypt hashes.
First boot and an explicit local reset retain a private bootstrap password so
the physical welcome screen remains useful after a power interruption. Rotation
removes that cleartext bootstrap value. This is unrelated to the Linux password.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import secrets
import string
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from fastapi import HTTPException, Request, Response

logger = logging.getLogger(__name__)
COOKIE_NAME: Final = "inky_session"
SESSION_TTL_SECONDS: Final = 30 * 24 * 3600
LOGIN_RATE_LIMIT_WINDOW: Final = 60
LOGIN_RATE_LIMIT_MAX: Final = 5
PASSWORD_ALPHABET: Final = string.ascii_letters + string.digits
# About 32 MiB per calculation, serialized per service, outside the event loop.
SCRYPT_N: Final = 32768
SCRYPT_R: Final = 8
SCRYPT_P: Final = 1
PUBLIC_PATHS: Final = frozenset({"/api/health", "/api/auth/login", "/api/auth/status"})


def auth_disabled() -> bool:
    return os.environ.get("INKY_STUDIO_DISABLE_AUTH") == "1"


class CredentialFormatError(ValueError):
    """Never replace unreadable credentials implicitly, or include their content."""

    def __init__(self) -> None:
        super().__init__("Identifiants invalides. Utilise explicitement inky-studio reset-password pour récupérer l’accès.")


class CredentialStorageError(OSError):
    def __init__(self, *, committed: bool = False) -> None:
        super().__init__("Impossible d’enregistrer les identifiants sur le stockage du cadre.")
        # If the rename succeeded but directory fsync failed, the visible file
        # has changed. Memory and sessions must follow it even when returning 503.
        self.committed = committed


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
        maxmem=64 * 1024 * 1024, dklen=32,
    )


@dataclass(frozen=True)
class Credentials:
    path: Path
    salt: bytes = field(repr=False)
    digest: bytes = field(repr=False)
    bootstrap_password: str | None = field(default=None, repr=False)

    def verify(self, password: str) -> bool:
        try:
            return secrets.compare_digest(self.digest, _derive(password, self.salt))
        except UnicodeEncodeError:
            return False

    def record(self) -> dict:
        record = {
            "version": 2, "algorithm": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R,
            "p": SCRYPT_P, "salt": self.salt.hex(), "hash": self.digest.hex(),
        }
        if self.bootstrap_password is not None:
            record["bootstrap_password"] = self.bootstrap_password
        return record


def _new_credentials(data_dir: Path, password: str, *, bootstrap: bool = False) -> Credentials:
    salt = secrets.token_bytes(16)
    return Credentials(data_dir / "credentials.json", salt, _derive(password, salt),
                       password if bootstrap else None)


def _read_record(path: Path) -> dict:
    try:
        if path.stat().st_size > 8192:
            raise CredentialFormatError()
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            raise CredentialFormatError()
        return record
    except (ValueError, UnicodeError) as exc:
        raise CredentialFormatError() from exc


def _valid_password(value: object) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _parse_record(path: Path, record: dict) -> Credentials:
    if set(record) == {"password"} and _valid_password(record["password"]):
        # Migrate without changing the password or preserving old cleartext.
        return _new_credentials(path.parent, record["password"])
    required = {"version", "algorithm", "n", "r", "p", "salt", "hash"}
    try:
        if not required <= record.keys() or record.keys() - required - {"bootstrap_password"}:
            raise ValueError
        if (record["version"], record["algorithm"], record["n"], record["r"], record["p"]) != (
            2, "scrypt", SCRYPT_N, SCRYPT_R, SCRYPT_P,
        ):
            raise ValueError
        salt, digest = bytes.fromhex(record["salt"]), bytes.fromhex(record["hash"])
        if len(salt) != 16 or len(digest) != 32:
            raise ValueError
        bootstrap = record.get("bootstrap_password")
        credentials = Credentials(path, salt, digest, bootstrap)
        if "bootstrap_password" in record and (
            not _valid_password(bootstrap) or not credentials.verify(bootstrap)
        ):
            raise ValueError
        return credentials
    except (ValueError, TypeError, KeyError) as exc:
        raise CredentialFormatError() from exc


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_credentials(credentials: Credentials) -> None:
    temporary_path = None
    committed = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=credentials.path.parent,
            prefix=".credentials-", delete=False,
        ) as tmp:
            temporary_path = Path(tmp.name)
            os.fchmod(tmp.fileno(), 0o600)
            json.dump(credentials.record(), tmp)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(temporary_path, credentials.path)
        committed = True
        _sync_directory(credentials.path.parent)
    except OSError as exc:
        raise CredentialStorageError(committed=committed) from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove a private credential staging file")


def load_or_create_credentials(data_dir: Path) -> Credentials:
    # Older welcome renderers used the process umask for PNGs containing the
    # initial secret. Restrict existing artifacts too, including after migration.
    for name in ("welcome_preview.png", "_welcome_tmp.png"):
        artifact = data_dir / name
        if artifact.is_file():
            artifact.chmod(0o600)
    path = data_dir / "credentials.json"
    try:
        record = _read_record(path)
    except FileNotFoundError:
        if path.is_symlink():
            raise CredentialFormatError() from None
        return reset_credentials(data_dir)
    credentials = _parse_record(path, record)
    if "password" in record:
        _write_credentials(credentials)
        logger.info("Migrated legacy application credentials to scrypt")
    return credentials


def reset_credentials(data_dir: Path) -> Credentials:
    """Explicit local recovery. The CLI stops the service before replacing this file."""
    data_dir.mkdir(parents=True, exist_ok=True)
    password = "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(16))
    credentials = _new_credentials(data_dir, password, bootstrap=True)
    _write_credentials(credentials)
    return credentials


def display_password(data_dir: Path) -> str | None:
    """Read only: this command never creates, migrates or resets credentials."""
    path = data_dir / "credentials.json"
    record = _read_record(path)
    credentials = _parse_record(path, record)
    return record["password"] if "password" in record else credentials.bootstrap_password


class SessionStore:
    """Process-local sessions with immediate notification of revocation to WebSockets."""

    def __init__(self) -> None:
        self._sessions: dict[str, float] = {}
        self._lock = threading.RLock()
        self._watchers: dict[asyncio.Event, asyncio.AbstractEventLoop] = {}

    def create(self) -> str:
        with self._lock:
            now = time.time()
            self._sessions = {token: expiry for token, expiry in self._sessions.items() if expiry > now}
            token = secrets.token_urlsafe(32)
            self._sessions[token] = now + SESSION_TTL_SECONDS
            return token

    def validate(self, token: str | None) -> bool:
        if not token:
            return False
        with self._lock:
            expires = self._sessions.get(token)
            if expires is None:
                return False
            if time.time() >= expires:
                self._sessions.pop(token, None)
                return False
            return True

    def _notify(self) -> None:
        for event, loop in list(self._watchers.items()):
            try:
                loop.call_soon_threadsafe(event.set)
            except RuntimeError:
                self._watchers.pop(event, None)

    def invalidate(self, token: str | None) -> None:
        with self._lock:
            if token and self._sessions.pop(token, None) is not None:
                self._notify()

    def invalidate_all(self) -> None:
        with self._lock:
            self._sessions.clear()
            self._notify()

    def watch_revocation(self) -> asyncio.Event:
        event = asyncio.Event()
        with self._lock:
            self._watchers[event] = asyncio.get_running_loop()
        return event

    def unwatch_revocation(self, event: asyncio.Event) -> None:
        with self._lock:
            self._watchers.pop(event, None)


class CredentialService:
    """Serialize login verification and rotation across worker threads.

    A login verified against the old hash cannot issue a session after rotation.
    The ASGI app runs one process, as required by its other in-memory services.
    """

    def __init__(self, credentials: Credentials, sessions: SessionStore) -> None:
        self.credentials = credentials
        self.sessions = sessions
        self._lock = threading.Lock()

    def login(self, password: str) -> str:
        with self._lock:
            if not self.credentials.verify(password):
                raise HTTPException(status_code=401, detail="Mot de passe incorrect")
            return self.sessions.create()

    def change_password(self, token: str | None, current_password: str, new_password: str) -> str:
        with self._lock:
            if not self.sessions.validate(token):
                raise HTTPException(status_code=401, detail="Authentification requise")
            if not self.credentials.verify(current_password):
                raise HTTPException(status_code=403, detail="Le mot de passe actuel est incorrect")
            replacement = _new_credentials(self.credentials.path.parent, new_password)
            try:
                _write_credentials(replacement)
            except CredentialStorageError as exc:
                if exc.committed:
                    self.credentials = replacement
                    self.sessions.invalidate_all()
                    raise HTTPException(
                        status_code=503,
                        detail="Enregistrement incertain. Reconnecte-toi avec le nouveau mot de passe et vérifie le stockage du cadre.",
                    ) from exc
                raise HTTPException(
                    status_code=503,
                    detail="Stockage indisponible. Le mot de passe actuel reste valable.",
                ) from exc
            self.credentials = replacement
            self.sessions.invalidate_all()
            return self.sessions.create()


class LoginRateLimiter:
    """Track login attempts per IP with bounded per-IP sliding windows."""

    def __init__(self, window_seconds: int = LOGIN_RATE_LIMIT_WINDOW, max_attempts: int = LOGIN_RATE_LIMIT_MAX) -> None:
        self._window = window_seconds
        self._max = max_attempts
        self._attempts: dict[str, deque[float]] = {}

    def record_and_check(self, ip: str) -> bool:
        now = time.monotonic()
        recent = self._attempts.setdefault(ip, deque())
        while recent and now - recent[0] >= self._window:
            recent.popleft()
        if len(recent) >= self._max:
            return False
        recent.append(now)
        return True


def get_session_token(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME)


def set_session_cookie(response: Response, token: str, *, secure: bool = False) -> None:
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_TTL_SECONDS,
                        httponly=True, samesite="strict", secure=secure)


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME)


def require_auth(request: Request) -> None:
    if not auth_disabled() and not request.app.state.sessions.validate(get_session_token(request)):
        raise HTTPException(status_code=401, detail="Authentification requise")


def main() -> int:
    parser = argparse.ArgumentParser(description="Local application password management")
    parser.add_argument("command", choices=["password", "reset-password"])
    args = parser.parse_args()
    # Unlike db.data_dir(), resolve the path without creating any directories.
    raw = os.environ.get("INKY_STUDIO_DATA_DIR")
    directory = Path(raw).expanduser() if raw else Path(__file__).resolve().parent.parent / "data"
    try:
        password = (reset_credentials(directory).bootstrap_password
                    if args.command == "reset-password" else display_password(directory))
    except (OSError, CredentialFormatError):
        print("Identifiants indisponibles. Vérifie le stockage et les permissions ; inky-studio reset-password permet une récupération explicite.")
        return 1
    print(password or "Mot de passe personnalisé non consultable. Utilise inky-studio reset-password pour le remplacer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
