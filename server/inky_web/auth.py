"""Single-password auth with a session-cookie + in-memory session store.

Design — kept deliberately tiny because this app serves one user on one Pi:
- A 10-char alphanumeric password is generated on first boot and persisted to
  ``<data_dir>/credentials.json`` (mode 600). It is shown on the welcome
  screen of the Inky display so the user can read it physically.
- On successful login, we mint a random session id (``secrets.token_urlsafe``)
  and store it in a process-local dict ``{session_id: expires_at}``. The id is
  sent back as an HttpOnly cookie with SameSite=Strict.
- Sessions evaporate on restart — that's intentional; it forces re-auth after
  any reboot/update without us having to manage refresh tokens or revocation.
- Rate limiting on /api/auth/login: max 5 attempts per IP per 60 s.

Set ``INKY_STUDIO_DISABLE_AUTH=1`` to skip authentication explicitly (used by
pytest; optional for local development).
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import string
import tempfile
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from fastapi import HTTPException, Request, Response

logger = logging.getLogger(__name__)

COOKIE_NAME: Final = "inky_session"
SESSION_TTL_SECONDS: Final = 30 * 24 * 3600  # 30 days
LOGIN_RATE_LIMIT_WINDOW: Final = 60  # seconds
LOGIN_RATE_LIMIT_MAX: Final = 5
PASSWORD_ALPHABET: Final = string.ascii_letters + string.digits

# Public endpoints — auth middleware lets these through unauthenticated.
PUBLIC_PATHS: Final = frozenset(
    {
        "/api/health",
        "/api/auth/login",
        "/api/auth/status",
    }
)


def auth_disabled() -> bool:
    return os.environ.get("INKY_STUDIO_DISABLE_AUTH") == "1"


@dataclass
class Credentials:
    password: str
    path: Path


def _credentials_path(data_dir: Path) -> Path:
    return data_dir / "credentials.json"


def load_or_create_credentials(data_dir: Path) -> Credentials:
    """Return existing credentials, or generate + persist new ones (mode 600)."""
    path = _credentials_path(data_dir)
    if path.is_file():
        try:
            data = json.loads(path.read_text())
            password = data.get("password") if isinstance(data, dict) else None
            if not isinstance(password, str) or not 1 <= len(password) <= 64:
                raise ValueError("Expected a non-empty password of at most 64 characters")
            return Credentials(password=password, path=path)
        except ValueError as exc:
            logger.warning("Corrupt credentials at %s — regenerating (%s)", path, exc)

    return _create_credentials(data_dir)


def _create_credentials(data_dir: Path) -> Credentials:
    """Atomically replace the credentials with a private, fully written file."""
    path = _credentials_path(data_dir)
    password = "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(10))
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=data_dir, prefix=".credentials-", delete=False) as tmp:
            temporary_path = Path(tmp.name)
            json.dump({"password": password}, tmp, indent=2)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    logger.info("Generated new credentials at %s — show on welcome screen", path)
    return Credentials(password=password, path=path)


def reset_credentials(data_dir: Path) -> Credentials:
    """Drop existing credentials and create a fresh password — used by `inky-studio reset-password`."""
    return _create_credentials(data_dir)


class SessionStore:
    """In-memory ``{session_id: expires_at}`` map.

    Cleared on process restart — that's the simplest revocation policy.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, float] = {}

    def create(self) -> str:
        now = time.time()
        self._sessions = {token: expires for token, expires in self._sessions.items() if expires > now}
        token = secrets.token_urlsafe(32)
        self._sessions[token] = now + SESSION_TTL_SECONDS
        return token

    def validate(self, token: str | None) -> bool:
        if not token:
            return False
        expires = self._sessions.get(token)
        if expires is None:
            return False
        if time.time() >= expires:
            self._sessions.pop(token, None)
            return False
        return True

    def invalidate(self, token: str | None) -> None:
        if token:
            self._sessions.pop(token, None)


class LoginRateLimiter:
    """Track login attempts per IP with a sliding window."""

    def __init__(
        self,
        window_seconds: int = LOGIN_RATE_LIMIT_WINDOW,
        max_attempts: int = LOGIN_RATE_LIMIT_MAX,
    ) -> None:
        self._window = window_seconds
        self._max = max_attempts
        self._attempts: dict[str, deque[float]] = {}

    def record_and_check(self, ip: str) -> bool:
        """Allow at most ``max_attempts`` per window, with bounded per-IP storage."""
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


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="strict",
        secure=False,  # Local-network HTTP. Flip to True if you put it behind HTTPS.
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME)


def require_auth(request: Request) -> None:
    """Raise 401 if the request is not authenticated. Used as a FastAPI dep."""
    if auth_disabled():
        return
    sessions: SessionStore = request.app.state.sessions
    if not sessions.validate(get_session_token(request)):
        raise HTTPException(status_code=401, detail="Authentification requise")
