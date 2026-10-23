"""Private PHOTO credentials; deliberately independent of Bluetooth ownership.

Only hashes of bearer secrets are persisted. A live legacy session
can enroll an owner after the client has independently approved the TLS identity.
This cannot recover a lost cookie or establish trust from an HTTP response.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import secrets
import sqlite3
import stat
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

MAX_DEVICES = 128  # Includes tombstones: revoked identifiers are never reusable.
MAX_INVITATIONS = 128
MAX_ISSUED_INVITATIONS = 4096
MAX_TTL = 300
HEX = re.compile(r"[0-9a-f]{64}\Z")
LAN_BOOTSTRAP_ISSUER = "inky-imager-lan-bootstrap-v1"


class AccessError(ValueError):
    def __init__(self, code: str = "unauthorized"):
        self.code = code
        super().__init__(code)


def uuid(value: str) -> str:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValueError("UUID invalide") from None
    return value


def token(value: str) -> str:
    if not isinstance(value, str) or HEX.fullmatch(value) is None:
        raise ValueError("Jeton invalide")
    return value


def digest(value: str) -> str:
    return hashlib.sha256(b"inky-photo-access-v1\0" + bytes.fromhex(token(value))).hexdigest()


@dataclass(frozen=True)
class Principal:
    device_id: str
    role: str
    epoch: str


SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
 device_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE,
 role TEXT NOT NULL CHECK(role IN ('owner','media')), epoch TEXT NOT NULL,
 request_id TEXT NOT NULL UNIQUE, created_at REAL NOT NULL,
 revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1))
);
CREATE TABLE IF NOT EXISTS invitations (
 invitation_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE,
 issuer_id TEXT NOT NULL, epoch TEXT NOT NULL, boot TEXT NOT NULL,
 request_id TEXT NOT NULL UNIQUE, created_at REAL NOT NULL, expires_at REAL NOT NULL,
 created_mono REAL NOT NULL, expires_mono REAL NOT NULL,
 claim_request_id TEXT UNIQUE, claim_device_id TEXT, claim_token_hash TEXT,
 revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1))
);
CREATE TABLE IF NOT EXISTS issued_invitations (
 invitation_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
 token_hash TEXT NOT NULL UNIQUE
);
"""


class PhotoAccessStore:
    def __init__(self, directory: Path, epoch: Callable[[], str], *, gate=None,
                 clock: Callable[[], float] = time.time,
                 monotonic: Callable[[], float] = time.monotonic,
                 lan_bootstrap: bool = False):
        if type(lan_bootstrap) is not bool:
            raise ValueError("Invalid LAN bootstrap policy")
        self.directory = Path(directory)
        if self.directory.is_symlink():
            raise OSError("Invalid private access directory")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.directory.chmod(0o700)
        self.path = self.directory / "access.sqlite3"
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > 2 * 1024 * 1024:
                raise OSError("Invalid access database")
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        self._epoch = epoch
        self._gate = gate or threading.RLock()
        self._clock, self._monotonic = clock, monotonic
        self._last_wall = self._last_mono = None
        self._boot = secrets.token_hex(16)
        self._lan_bootstrap_enabled = lan_bootstrap
        self._lan_bootstrap_started = False
        self._lan_bootstrap_id = None
        with self._connection() as conn:
            if conn.execute("PRAGMA user_version").fetchone()[0] not in (0, 1):
                raise OSError("Unsupported access database")
            conn.executescript(SCHEMA)
            conn.execute("PRAGMA user_version=1")
        # Opening a new process/store invalidates every previous invitation,
        # including completed-claim retry receipts. Device credentials survive.
        with self._transaction() as conn:
            conn.execute("DELETE FROM invitations")
        fd = os.open(self.directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA max_page_count=512")
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _transaction(self):
        with self._gate, self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def _authorized(self, conn, principal: Principal):
        row = conn.execute("SELECT * FROM devices WHERE device_id=?", (principal.device_id,)).fetchone()
        if (row is None or row["revoked"] or principal.role not in {"owner", "media"}
                or row["role"] != principal.role
                or row["epoch"] != principal.epoch or principal.epoch != self._epoch()):
            raise AccessError()
        return row

    def _owner(self, conn, principal):
        row = self._authorized(conn, principal)
        if principal.role != "owner":
            raise AccessError("forbidden")
        return row

    def valid(self, principal: Principal) -> bool:
        try:
            with self._gate, self._connection() as conn:
                self._authorized(conn, principal)
            return True
        except (AccessError, OSError, sqlite3.Error):
            return False

    def authenticate(self, device_id: str, device_token: str) -> Principal:
        device_id, hashed = uuid(device_id), digest(device_token)
        with self._gate, self._connection() as conn:
            row = conn.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
            if row is None or not secrets.compare_digest(row["token_hash"], hashed):
                raise AccessError()
            principal = Principal(device_id, row["role"], row["epoch"])
            self._authorized(conn, principal)
            return principal

    def _insert_device(self, conn, device_id, hashed, role, request_id, epoch):
        if conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0] >= MAX_DEVICES:
            raise AccessError("capacity")
        try:
            now, _ = self._observe_clock(conn)
            conn.execute("INSERT INTO devices VALUES (?,?,?,?,?,?,0)",
                         (device_id, hashed, role, epoch, request_id, now))
        except sqlite3.IntegrityError:
            raise AccessError("conflict") from None

    def _observe_clock(self, conn):
        now, mono = self._clock(), self._monotonic()
        if (not math.isfinite(now) or not math.isfinite(mono)
                or (self._last_wall is not None and now < self._last_wall)
                or (self._last_mono is not None and mono < self._last_mono)):
            conn.execute("UPDATE invitations SET revoked=1")
            # This denial must survive the surrounding transaction's rollback.
            conn.commit()
            if math.isfinite(now) and math.isfinite(mono):
                self._last_wall, self._last_mono = now, mono
            raise AccessError()
        self._last_wall, self._last_mono = now, mono
        return now, mono

    def enroll(self, device_id: str, device_token: str, request_id: str) -> Principal:
        device_id, request_id, hashed = uuid(device_id), uuid(request_id), digest(device_token)
        with self._transaction() as conn:
            epoch = self._epoch()
            row = conn.execute("SELECT * FROM devices WHERE device_id=? OR request_id=?",
                               (device_id, request_id)).fetchone()
            if row is not None:
                if (row["device_id"] != device_id or row["request_id"] != request_id
                        or row["role"] != "owner" or row["revoked"] or row["epoch"] != epoch
                        or not secrets.compare_digest(row["token_hash"], hashed)):
                    raise AccessError("conflict")
            else:
                self._insert_device(conn, device_id, hashed, "owner", request_id, epoch)
            return Principal(device_id, "owner", epoch)

    def lan_bootstrap_available(self) -> bool:
        """Local startup policy only; tombstones also close initial pairing."""
        if not self._lan_bootstrap_enabled or self._lan_bootstrap_started:
            return False
        with self._gate, self._connection() as conn:
            return conn.execute("SELECT 1 FROM devices WHERE epoch=? LIMIT 1",
                                (self._epoch(),)).fetchone() is None

    def lan_bootstrap_completed(self) -> bool:
        """Read the durable pairing result, including revoked-device tombstones."""
        with self._gate, self._connection() as conn:
            return conn.execute("SELECT 1 FROM devices WHERE epoch=? LIMIT 1",
                                (self._epoch(),)).fetchone() is not None

    def _insert_invitation(self, conn, issuer_id, epoch, invitation_id, hashed,
                           request_id, now, mono, ttl_seconds):
        if conn.execute("SELECT COUNT(*) FROM invitations").fetchone()[0] >= MAX_INVITATIONS:
            raise AccessError("capacity")
        if conn.execute("SELECT COUNT(*) FROM issued_invitations").fetchone()[0] >= MAX_ISSUED_INVITATIONS:
            raise AccessError("capacity")
        try:
            conn.execute("INSERT INTO issued_invitations VALUES (?,?,?)",
                         (invitation_id, request_id, hashed))
            conn.execute("INSERT INTO invitations VALUES (?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,0)",
                         (invitation_id, hashed, issuer_id, epoch, self._boot,
                          request_id, now, now + ttl_seconds, mono, mono + ttl_seconds))
        except sqlite3.IntegrityError:
            raise AccessError("conflict") from None

    def begin_lan_bootstrap(self, invitation_id: str, invitation_token: str,
                            request_id: str) -> dict:
        """One local, media-only pairing lease; never create a synthetic owner.

        The explicit LAN entrypoint enables this policy only after rejecting
        factory traces. No HTTP route exposes this method. Its same printed QR
        may be renewed while live and unclaimed; expiry cannot mint a new one.
        """
        invitation_id, request_id = uuid(invitation_id), uuid(request_id)
        hashed = digest(invitation_token)
        with self._transaction() as conn:
            if not self._lan_bootstrap_enabled or self._lan_bootstrap_started:
                raise AccessError("forbidden")
            epoch = self._epoch()
            if conn.execute("SELECT 1 FROM devices WHERE epoch=? LIMIT 1", (epoch,)).fetchone():
                raise AccessError("forbidden")
            now, mono = self._observe_clock(conn)
            # Consume this process's mint permission before the durable write;
            # an uncertain write never authorizes an automatic replacement QR.
            self._lan_bootstrap_started = True
            self._insert_invitation(conn, LAN_BOOTSTRAP_ISSUER, epoch,
                                    invitation_id, hashed, request_id, now, mono, MAX_TTL)
            self._lan_bootstrap_id = invitation_id
            return {"invitation_id": invitation_id, "expires_at": now + MAX_TTL}

    def renew_lan_bootstrap(self, invitation_id: str, invitation_token: str) -> bool:
        """Renew the already-visible initial QR only before either clock expiry."""
        invitation_id, hashed = uuid(invitation_id), digest(invitation_token)
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM invitations WHERE invitation_id=?",
                               (invitation_id,)).fetchone()
            now, mono = self._observe_clock(conn)
            if (not self._lan_bootstrap_enabled or invitation_id != self._lan_bootstrap_id
                    or row is None or row["issuer_id"] != LAN_BOOTSTRAP_ISSUER
                    or row["boot"] != self._boot or row["revoked"]
                    or row["epoch"] != self._epoch()
                    or not row["created_at"] <= now < row["expires_at"]
                    or not row["created_mono"] <= mono < row["expires_mono"]
                    or not secrets.compare_digest(row["token_hash"], hashed)):
                raise AccessError()
            if row["claim_request_id"] is not None:
                return False
            if conn.execute("SELECT 1 FROM devices WHERE epoch=? LIMIT 1",
                            (row["epoch"],)).fetchone():
                conn.execute("UPDATE invitations SET revoked=1 WHERE invitation_id=?", (invitation_id,))
                return False
            conn.execute("UPDATE invitations SET expires_at=?,expires_mono=? WHERE invitation_id=?",
                         (now + MAX_TTL, mono + MAX_TTL, invitation_id))
            return True

    def end_lan_bootstrap(self, invitation_id: str, invitation_token: str) -> None:
        """Close this local lease before the HTTPS listener finishes draining."""
        invitation_id, hashed = uuid(invitation_id), digest(invitation_token)
        with self._transaction() as conn:
            if not self._lan_bootstrap_enabled or invitation_id != self._lan_bootstrap_id:
                raise AccessError()
            row = conn.execute("SELECT * FROM invitations WHERE invitation_id=?",
                               (invitation_id,)).fetchone()
            if (row is None or row["issuer_id"] != LAN_BOOTSTRAP_ISSUER
                    or not secrets.compare_digest(row["token_hash"], hashed)):
                raise AccessError()
            conn.execute("UPDATE invitations SET revoked=1 WHERE invitation_id=?", (invitation_id,))

    def invite(self, actor: Principal, invitation_id: str, invitation_token: str,
               request_id: str, ttl_seconds: int) -> dict:
        invitation_id, request_id = uuid(invitation_id), uuid(request_id)
        hashed = digest(invitation_token)
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= MAX_TTL:
            raise ValueError("Durée invalide")
        with self._transaction() as conn:
            self._owner(conn, actor)
            now, mono = self._observe_clock(conn)
            conn.execute("DELETE FROM invitations WHERE expires_at<=? OR expires_mono<=? OR boot<>?",
                         (now, mono, self._boot))
            row = conn.execute("SELECT * FROM invitations WHERE invitation_id=? OR request_id=?",
                               (invitation_id, request_id)).fetchone()
            if row is not None:
                if (row["invitation_id"] != invitation_id or row["request_id"] != request_id
                        or row["issuer_id"] != actor.device_id or row["epoch"] != actor.epoch
                        or row["revoked"] or row["claim_request_id"] is not None
                        or row["expires_at"] - row["created_at"] != ttl_seconds
                        or not secrets.compare_digest(row["token_hash"], hashed)):
                    raise AccessError("conflict")
                return {"invitation_id": invitation_id, "expires_at": row["expires_at"]}
            # Expiry/restart may prune an active record, never its durable
            # anti-replay receipt. An old QR must not become valid again.
            self._insert_invitation(conn, actor.device_id, actor.epoch, invitation_id,
                                    hashed, request_id, now, mono, ttl_seconds)
            return {"invitation_id": invitation_id, "expires_at": now + ttl_seconds}

    def claim(self, invitation_id: str, invitation_token: str, device_id: str,
              device_token: str, request_id: str) -> Principal:
        invitation_id, device_id, request_id = uuid(invitation_id), uuid(device_id), uuid(request_id)
        invitation_hash, device_hash = digest(invitation_token), digest(device_token)
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM invitations WHERE invitation_id=?", (invitation_id,)).fetchone()
            now, mono = self._observe_clock(conn)
            if row is not None and (not row["created_at"] <= now < row["expires_at"]
                                    or not row["created_mono"] <= mono < row["expires_mono"]):
                conn.execute("UPDATE invitations SET revoked=1 WHERE invitation_id=?", (invitation_id,))
                conn.commit()
                raise AccessError()
            if (row is None or row["boot"] != self._boot or row["revoked"]
                    or not row["created_at"] <= now < row["expires_at"]
                    or not row["created_mono"] <= mono < row["expires_mono"]
                    or row["epoch"] != self._epoch()
                    or not secrets.compare_digest(row["token_hash"], invitation_hash)):
                raise AccessError()
            if row["issuer_id"] == LAN_BOOTSTRAP_ISSUER:
                if (not self._lan_bootstrap_enabled
                        or row["invitation_id"] != self._lan_bootstrap_id):
                    raise AccessError()
                if (row["claim_request_id"] is None and conn.execute(
                        "SELECT 1 FROM devices WHERE epoch=? LIMIT 1", (row["epoch"],)).fetchone()):
                    raise AccessError("forbidden")
            else:
                self._owner(conn, Principal(row["issuer_id"], "owner", row["epoch"]))
            principal = Principal(device_id, "media", row["epoch"])
            if row["claim_request_id"] is not None:
                if (row["claim_request_id"] != request_id or row["claim_device_id"] != device_id
                        or not secrets.compare_digest(row["claim_token_hash"], device_hash)):
                    raise AccessError("conflict")
                device = self._authorized(conn, principal)
                if not secrets.compare_digest(device["token_hash"], device_hash):
                    raise AccessError()
            else:
                self._insert_device(conn, device_id, device_hash, "media", request_id, row["epoch"])
                try:
                    conn.execute("UPDATE invitations SET claim_request_id=?,claim_device_id=?,claim_token_hash=? WHERE invitation_id=?",
                                 (request_id, device_id, device_hash, invitation_id))
                except sqlite3.IntegrityError:
                    raise AccessError("conflict") from None
            return principal

    def revoke_invitation(self, actor: Principal, invitation_id: str):
        invitation_id = uuid(invitation_id)
        with self._transaction() as conn:
            self._owner(conn, actor)
            conn.execute("UPDATE invitations SET revoked=1 WHERE invitation_id=?", (invitation_id,))

    def devices(self, actor: Principal, device_id: str | None = None) -> list[dict]:
        if device_id is not None:
            device_id = uuid(device_id)
        with self._gate, self._connection() as conn:
            self._owner(conn, actor)
            rows = conn.execute("SELECT device_id,role,created_at,revoked FROM devices WHERE epoch=? ORDER BY created_at,device_id",
                                (actor.epoch,)).fetchall()
            return [{**dict(row), "revoked": bool(row["revoked"])} for row in rows
                    if device_id is None or row["device_id"] == device_id]

    def revoke_device(self, actor: Principal, device_id: str):
        device_id = uuid(device_id)
        with self._transaction() as conn:
            self._owner(conn, actor)
            conn.execute("UPDATE devices SET revoked=1 WHERE device_id=?", (device_id,))
            conn.execute("UPDATE invitations SET revoked=1 WHERE issuer_id=?", (device_id,))
