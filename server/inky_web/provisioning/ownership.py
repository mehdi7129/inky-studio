"""Durable, bounded ownership independent of HTTP/Bluetooth connectivity.

One application authority owns this store. Constructing it invalidates any old
QR window, so reboot or an offline RTC rollback cannot extend an adoption window.
The phone generates and saves its owner token *before* calling claim(). Only
hashes of QR/owner tokens are stored; none are returned by status or exceptions.

The credential_epoch callback must read the application's authoritative current
password salt/digest, including a credential file committed before a crash.
prepare_password_rotation runs BEFORE that file is replaced. Authorization then
follows the observed epoch, with no fragile post-commit revocation callback.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import sqlite3
import stat
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from inky_web.provisioning.factory import (
    FACTORY_SCHEMA,
    FactoryIdentity,
    FactoryRecoveryRequired,
    FactoryState,
    FactoryStatus,
    InitializationReceipt,
)
from inky_web.provisioning.identity import (
    SecretToken,
    _sync_directory,
    canonical_uuid,
    private_directory,
    private_lock,
    validate_token,
)

MAX_WINDOW_SECONDS = 600
MAX_OWNERS = 8
MAX_OWNER_RECORDS = 256  # Includes permanent revocation tombstones; fail closed when full.
MAX_HISTORY = 128

SCHEMA = """
CREATE TABLE owners (
    owner_id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0 CHECK (revoked IN (0, 1)),
    created_at REAL NOT NULL,
    claim_request_id TEXT NOT NULL UNIQUE,
    claim_intent TEXT NOT NULL
);
CREATE TABLE allowed_epochs (
    owner_id TEXT NOT NULL REFERENCES owners(owner_id),
    epoch TEXT NOT NULL,
    PRIMARY KEY (owner_id, epoch)
);
CREATE TABLE window (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    token_hash TEXT NOT NULL,
    epoch TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE requests (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL UNIQUE,
    owner_id TEXT NOT NULL REFERENCES owners(owner_id),
    intent TEXT NOT NULL
);
PRAGMA user_version = 1;
"""


class OwnershipError(ValueError):
    """Stable protocol error code; its message never incorporates input values."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class OwnershipStorageError(OSError):
    def __init__(self) -> None:
        super().__init__("Ownership storage is unavailable; explicit local recovery may be required")


@dataclass(frozen=True)
class OwnerAuthorization:
    owner_id: str
    epoch: str


@dataclass(frozen=True)
class ClaimResult:
    owner_id: str
    request_id: str


@dataclass(frozen=True)
class OwnershipStatus:
    owner_id: str
    epoch: str
    request_id: str | None = None
    claimed: bool = True


def credential_epoch(salt: bytes, digest: bytes) -> str:
    """Versioned canonical SHA-256 identifier of the stored application verifier.

    This is not a password hash or an authentication credential. A fresh salt
    changes the epoch even if the user selects the same password again.
    """
    if not isinstance(salt, bytes) or len(salt) != 16 or not isinstance(digest, bytes) or len(digest) != 32:
        raise ValueError("Invalid credential verifier")
    canonical = json.dumps({"v": 1, "salt": salt.hex(), "digest": digest.hex()},
                           separators=(",", ":"), sort_keys=True).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _hash_token(token: str | SecretToken) -> str:
    try:
        return hashlib.sha256(bytes.fromhex(validate_token(token))).hexdigest()
    except ValueError:
        raise OwnershipError("invalid_token") from None


def _uuid(value: str) -> str:
    try:
        return canonical_uuid(value)
    except ValueError:
        raise OwnershipError("invalid_id") from None


def _epoch(value: str) -> str:
    try:
        return validate_token(value)
    except ValueError:
        raise OwnershipError("invalid_epoch") from None


class OwnershipStore:
    """Private SQLite singleton; no network, shell, radio or display side effects.

    At most eight currently authorized owners, 256 lifetime owner IDs (revoked
    IDs can never be reused) and 128 recent request rows. Hitting the lifetime
    bound requires explicit recovery rather than forgetting revocation history.
    Original claim receipts remain with their bounded owner record, so a lost
    claim reply stays recoverable after request-history pruning.
    """

    def __init__(self, private_dir: Path, credential_epoch: Callable[[], str], *,
                 clock: Callable[[], float] = time.time,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        """Unchanged legacy entry point; factory stores explicitly refuse it."""
        self._initialize(private_dir, credential_epoch, clock=clock, monotonic=monotonic,
                         receipt=None, expected_identity=None, create_factory=False)

    @classmethod
    def create_factory(cls, private_dir: Path, credential_epoch: Callable[[], str], *,
                       receipt: InitializationReceipt, expected_identity: FactoryIdentity,
                       clock: Callable[[], float] = time.time,
                       monotonic: Callable[[], float] = time.monotonic) -> OwnershipStore:
        """Journal one explicitly authorized initialization, only in an absent DB.

        This does not validate/consume an actual root-owned receipt or create a
        key, credential, QR, radio or runtime. The trusted caller supplies those
        assertions, then confirms the same persisted identity with mark_factory_ready.
        A partial/failed creation is preserved for reopen or explicit recovery.
        An existing legacy store can never be promoted by this API.
        """
        return cls._factory_store(private_dir, credential_epoch, receipt=receipt,
                                  expected_identity=expected_identity, clock=clock,
                                  monotonic=monotonic, create=True)

    @classmethod
    def reopen_factory(cls, private_dir: Path, credential_epoch: Callable[[], str], *,
                       receipt: InitializationReceipt, expected_identity: FactoryIdentity,
                       clock: Callable[[], float] = time.time,
                       monotonic: Callable[[], float] = time.monotonic) -> OwnershipStore:
        """Reopen only an existing consistent journal with the original binding.

        Missing or corrupt records require recovery; there is no regeneration or
        factory inference from absent owners, Wi-Fi, photos or application files.
        Every reopen invalidates any previous physical QR window.
        """
        return cls._factory_store(private_dir, credential_epoch, receipt=receipt,
                                  expected_identity=expected_identity, clock=clock,
                                  monotonic=monotonic, create=False)

    @classmethod
    def _factory_store(cls, private_dir: Path, credential_epoch: Callable[[], str], *,
                       receipt: InitializationReceipt, expected_identity: FactoryIdentity,
                       clock: Callable[[], float], monotonic: Callable[[], float],
                       create: bool) -> OwnershipStore:
        # No dictionary coercion: these are local typed assertions, not a parser.
        if type(receipt) is not InitializationReceipt or type(expected_identity) is not FactoryIdentity:
            raise ValueError("Explicit local factory assertions are required")
        store = cls.__new__(cls)
        store._initialize(private_dir, credential_epoch, clock=clock, monotonic=monotonic,
                          receipt=receipt, expected_identity=expected_identity, create_factory=create)
        return store

    def _initialize(self, private_dir: Path, credential_epoch: Callable[[], str], *,
                    clock: Callable[[], float], monotonic: Callable[[], float],
                    receipt: InitializationReceipt | None,
                    expected_identity: FactoryIdentity | None, create_factory: bool) -> None:
        self._credential_epoch = credential_epoch
        self._clock = clock
        self._monotonic = monotonic
        self._factory_receipt = receipt
        self._factory_identity = expected_identity
        self._lock = threading.RLock()
        self._window_deadline: float | None = None
        self._window_wall_highwater: float | None = None
        self._closed = False
        try:
            if receipt is not None and not create_factory and not Path(private_dir).is_dir():
                raise FactoryRecoveryRequired()
            self.directory = private_directory(private_dir)
            self.path = self.directory / "ownership.sqlite3"
            with private_lock(self.directory / ".ownership.lock"):
                existed = self.path.exists() or self.path.is_symlink()
                if receipt is not None and existed == create_factory:
                    raise FactoryRecoveryRequired()
                descriptor = os.open(self.path, os.O_RDWR | os.O_NOFOLLOW |
                                     (0 if existed else os.O_CREAT | os.O_EXCL), 0o600)
                try:
                    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                        raise OSError("Ownership storage is not a regular file")
                    os.fchmod(descriptor, 0o600)
                finally:
                    os.close(descriptor)
                with self._connection() as connection:
                    if not existed:
                        connection.executescript("BEGIN IMMEDIATE;" + SCHEMA +
                                                 (FACTORY_SCHEMA if receipt is not None else ""))
                        if receipt is not None:
                            connection.execute(
                                "INSERT INTO factory_initialization VALUES (1, ?, ?, ?, ?, 'pending', NULL)",
                                (receipt.receipt_id, receipt.digest, expected_identity.frame_id,
                                 expected_identity.spki_sha256),
                            )
                        connection.commit()
                    self._validate_store_mode(connection)
                    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise OwnershipStorageError()
                    # Never resume an adoption window across authority restarts.
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute("DELETE FROM window")
                    connection.commit()
                _sync_directory(self.directory)
        except (OSError, sqlite3.Error):
            if receipt is not None:
                raise FactoryRecoveryRequired() from None
            raise OwnershipStorageError() from None

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        # mode=rw prevents a deleted store being recreated by an already-open
        # authority. Creation is confined to the explicit constructor path above.
        if self._factory_receipt is not None:
            # A substituted FIFO must reach fstat without waiting for a writer.
            descriptor = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise FactoryRecoveryRequired()
            finally:
                os.close(descriptor)
        connection = sqlite3.connect(self.path.absolute().as_uri() + "?mode=rw", uri=True,
                                     isolation_level=None, timeout=5)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = DELETE")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA fullfsync = ON")
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._closed:
                raise OwnershipError("store_closed")
            try:
                with self._connection() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    try:
                        self._validate_store_mode(connection)
                        yield connection
                        self._validate_store_mode(connection)
                        connection.commit()
                    except BaseException:
                        connection.rollback()
                        raise
            except (sqlite3.Error, OSError):
                if self._factory_receipt is not None:
                    raise FactoryRecoveryRequired() from None
                raise OwnershipStorageError() from None

    def _validate_store_mode(self, connection: sqlite3.Connection) -> None:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        journal_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'factory_initialization'",
        ).fetchone() is not None
        if self._factory_receipt is None:
            if version != 1 or journal_exists:
                raise OwnershipStorageError()
        elif version != 2 or not journal_exists:
            raise FactoryRecoveryRequired()
        else:
            self._factory_status(connection)

    def _factory_status(self, connection: sqlite3.Connection) -> FactoryStatus:
        if self._factory_receipt is None:
            raise OwnershipError("factory_not_enabled")
        rows = connection.execute(
            "SELECT id, receipt_id, receipt_digest, frame_id, spki_sha256, state, first_owner_id "
            "FROM factory_initialization",
        ).fetchall()
        if len(rows) != 1 or rows[0]["id"] != 1:
            raise FactoryRecoveryRequired()
        row = rows[0]
        try:
            receipt = InitializationReceipt(row["receipt_id"], row["receipt_digest"])
            identity = FactoryIdentity(row["frame_id"], row["spki_sha256"])
            state = FactoryState(row["state"])
            first_owner = row["first_owner_id"]
            if first_owner is not None:
                canonical_uuid(first_owner)
        except (ValueError, TypeError):
            raise FactoryRecoveryRequired() from None
        if (receipt.receipt_id != self._factory_receipt.receipt_id
                or not secrets.compare_digest(receipt.digest, self._factory_receipt.digest)
                or identity != self._factory_identity or state == FactoryState.RECOVERY):
            raise FactoryRecoveryRequired()
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise FactoryRecoveryRequired()
        if state == FactoryState.ADOPTED:
            if first_owner is None or connection.execute(
                "SELECT 1 FROM owners WHERE owner_id = ?", (first_owner,),
            ).fetchone() is None:
                raise FactoryRecoveryRequired()
        else:
            if first_owner is not None or connection.execute("SELECT 1 FROM owners LIMIT 1").fetchone():
                raise FactoryRecoveryRequired()
            if state == FactoryState.PENDING and connection.execute("SELECT 1 FROM window LIMIT 1").fetchone():
                raise FactoryRecoveryRequired()
        return FactoryStatus(state, identity, first_owner)

    def factory_status(self) -> FactoryStatus:
        """Local durable state, validated afresh; never inferred from connectivity."""
        with self._transaction() as connection:
            return self._factory_status(connection)

    def mark_factory_ready(self, identity: FactoryIdentity) -> FactoryStatus:
        """Confirm the expected persisted identity; pending -> factory is one-way.

        The caller must verify the real key/identity store before this assertion.
        Repeated confirmation is harmless, including after adoption; it cannot
        replace identity or reopen adoption. No identity file is read or written.
        """
        if type(identity) is not FactoryIdentity:
            raise ValueError("An explicit local identity assertion is required")
        with self._transaction() as connection:
            status = self._factory_status(connection)
            if identity != status.identity:
                raise FactoryRecoveryRequired()
            if status.state == FactoryState.PENDING:
                connection.execute("UPDATE factory_initialization SET state = 'factory' WHERE id = 1")
            return self._factory_status(connection)

    def _current_epoch(self, expected: str | None = None) -> str:
        current = _epoch(self._credential_epoch())
        if expected is not None and not secrets.compare_digest(current, _epoch(expected)):
            raise OwnershipError("epoch_changed")
        return current

    def _window_valid(self, row: sqlite3.Row | None, epoch: str) -> bool:
        now, monotonic_now = self._clock(), self._monotonic()
        if row is None or not math.isfinite(now) or not math.isfinite(monotonic_now):
            return False
        # A backwards wall clock invalidates a window even within one process.
        highwater = self._window_wall_highwater
        self._window_wall_highwater = now if highwater is None else max(highwater, now)
        valid = (row["epoch"] == epoch and row["created_at"] <= now < row["expires_at"]
                 and (highwater is None or now >= highwater)
                 and self._window_deadline is not None and monotonic_now < self._window_deadline)
        if not valid:
            self._window_deadline = None
        return valid

    def open_window(self, ttl_seconds: float = MAX_WINDOW_SECONDS, *,
                    expected_epoch: str | None = None) -> SecretToken:
        """Privileged local/display action: create one physical QR window.

        This is not an unauthenticated remotely callable method. The application
        must authorize the physical/setup action and display the resulting QR.
        Epoch mismatch and live-window conflict do not disclose the existing QR.
        On an opted-in factory store, this administrative entry point is only
        available after adoption. Initial adoption uses open_factory_window.
        """
        return self._open_window(ttl_seconds, expected_epoch=expected_epoch, factory=False)

    def open_factory_window(self, ttl_seconds: float = MAX_WINDOW_SECONDS, *,
                            expected_epoch: str | None = None) -> SecretToken:
        """Local initial-adoption action, only for the explicitly ready factory.

        No runtime calls this method yet. A future orchestrator must reserve the
        physical display and verify identity/credential storage before invoking it.
        Losing Wi-Fi, owners or password authorization never makes it available
        after the first successful claim.
        """
        return self._open_window(ttl_seconds, expected_epoch=expected_epoch, factory=True)

    def _open_window(self, ttl_seconds: float, *, expected_epoch: str | None,
                     factory: bool) -> SecretToken:
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (float, int)) or not 0 < ttl_seconds <= MAX_WINDOW_SECONDS:
            raise OwnershipError("invalid_ttl")
        with self._transaction() as connection:
            if factory or self._factory_receipt is not None:
                state = self._factory_status(connection).state
                if state == FactoryState.PENDING:
                    raise OwnershipError("factory_not_ready")
                if factory and state != FactoryState.FACTORY:
                    raise OwnershipError("factory_unavailable")
                if not factory and state != FactoryState.ADOPTED:
                    raise OwnershipError("factory_window_required")
            epoch = self._current_epoch(expected_epoch)
            row = connection.execute("SELECT * FROM window WHERE id = 1").fetchone()
            if self._window_valid(row, epoch):
                raise OwnershipError("window_active")
            now, monotonic_now = self._clock(), self._monotonic()
            if not math.isfinite(now) or not math.isfinite(monotonic_now):
                raise OwnershipError("invalid_clock")
            token = SecretToken(secrets.token_hex(32))
            connection.execute("DELETE FROM window")
            connection.execute("INSERT INTO window VALUES (1, ?, ?, ?, ?)",
                               (_hash_token(token), epoch, now, now + ttl_seconds))
            self._window_deadline = monotonic_now + ttl_seconds
            self._window_wall_highwater = now
            return token

    def close_window(self) -> None:
        with self._transaction() as connection:
            connection.execute("DELETE FROM window")
            self._window_deadline = self._window_wall_highwater = None

    @staticmethod
    def _authorized(connection: sqlite3.Connection, owner_id: str, token_hash: str,
                    epoch: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT o.* FROM owners o JOIN allowed_epochs e ON e.owner_id = o.owner_id "
            "WHERE o.owner_id = ? AND o.revoked = 0 AND e.epoch = ?", (owner_id, epoch),
        ).fetchone()
        # Keep one generic failure for unknown, stale, revoked and wrong token.
        actual = row["token_hash"] if row else "0" * 64
        matches = secrets.compare_digest(actual, token_hash)
        if row is None or not matches:
            raise OwnershipError("unauthorized")
        return row

    def authenticate(self, owner_id: str, owner_token: str | SecretToken) -> OwnerAuthorization:
        """Check the current credential epoch on EVERY authenticated command."""
        owner_id, token_hash = _uuid(owner_id), _hash_token(owner_token)
        with self._transaction() as connection:
            epoch = self._current_epoch()
            self._authorized(connection, owner_id, token_hash, epoch)
            return OwnerAuthorization(owner_id, epoch)

    def claim(self, qr_token: str | SecretToken, owner_id: str,
              owner_token: str | SecretToken, request_id: str,
              expected_epoch: str) -> ClaimResult:
        """Atomically consume QR + install the phone's already-saved credential.

        Identical retries require the same owner credential and current epoch.
        A revoked owner cannot retrieve a success receipt or register again.
        """
        owner_id, request_id = _uuid(owner_id), _uuid(request_id)
        owner_hash, qr_hash = _hash_token(owner_token), _hash_token(qr_token)
        expected_epoch = _epoch(expected_epoch)
        intent = hashlib.sha256(json.dumps(
            [owner_id, owner_hash, qr_hash, expected_epoch], separators=(",", ":"),
        ).encode("ascii")).hexdigest()
        with self._transaction() as connection:
            factory_state = None
            if self._factory_receipt is not None:
                factory_state = self._factory_status(connection).state
                if factory_state == FactoryState.PENDING:
                    raise OwnershipError("factory_not_ready")
            epoch = self._current_epoch(expected_epoch)
            existing = connection.execute("SELECT * FROM owners WHERE owner_id = ?", (owner_id,)).fetchone()
            if existing is not None:
                self._authorized(connection, owner_id, owner_hash, epoch)
                if existing["claim_request_id"] != request_id or existing["claim_intent"] != intent:
                    raise OwnershipError("request_conflict")
                return ClaimResult(owner_id, request_id)
            window = connection.execute("SELECT * FROM window WHERE id = 1").fetchone()
            if not self._window_valid(window, epoch):
                raise OwnershipError("qr_unavailable")
            if not secrets.compare_digest(window["token_hash"], qr_hash):
                raise OwnershipError("unauthorized")
            duplicate = connection.execute("SELECT 1 FROM owners WHERE claim_request_id = ?", (request_id,)).fetchone()
            if duplicate:
                raise OwnershipError("request_conflict")
            active = connection.execute(
                "SELECT COUNT(*) FROM owners o JOIN allowed_epochs e ON e.owner_id = o.owner_id "
                "WHERE o.revoked = 0 AND e.epoch = ?", (epoch,),
            ).fetchone()[0]
            total = connection.execute("SELECT COUNT(*) FROM owners").fetchone()[0]
            if active >= MAX_OWNERS or total >= MAX_OWNER_RECORDS:
                raise OwnershipError("owner_capacity")
            connection.execute("INSERT INTO owners VALUES (?, ?, 0, ?, ?, ?)",
                               (owner_id, owner_hash, self._clock(), request_id, intent))
            connection.execute("INSERT INTO allowed_epochs VALUES (?, ?)", (owner_id, epoch))
            connection.execute("INSERT INTO requests(request_id, owner_id, intent) VALUES (?, ?, ?)",
                               (request_id, owner_id, intent))
            connection.execute("DELETE FROM requests WHERE sequence NOT IN "
                               "(SELECT sequence FROM requests ORDER BY sequence DESC LIMIT ?)", (MAX_HISTORY,))
            if factory_state == FactoryState.FACTORY:
                connection.execute(
                    "UPDATE factory_initialization SET state = 'adopted', first_owner_id = ? WHERE id = 1",
                    (owner_id,),
                )
            connection.execute("DELETE FROM window")
            self._window_deadline = self._window_wall_highwater = None
            return ClaimResult(owner_id, request_id)

    def status(self, owner_id: str, owner_token: str | SecretToken,
               request_id: str | None = None) -> OwnershipStatus:
        """Authenticated recovery after a lost reply; never returns any secret."""
        owner_id, token_hash = _uuid(owner_id), _hash_token(owner_token)
        if request_id is not None:
            request_id = _uuid(request_id)
        with self._transaction() as connection:
            epoch = self._current_epoch()
            owner = self._authorized(connection, owner_id, token_hash, epoch)
            if request_id is not None and owner["claim_request_id"] != request_id:
                raise OwnershipError("request_not_found")
            return OwnershipStatus(owner_id, epoch, request_id)

    def revoke(self, owner_id: str) -> None:
        """Trusted administrative operation; caller authorization is external.

        The application must also close active sessions for this owner. Keeping
        the tombstone makes revoke idempotent and prevents later reactivation.
        """
        owner_id = _uuid(owner_id)
        with self._transaction() as connection:
            connection.execute("UPDATE owners SET revoked = 1 WHERE owner_id = ?", (owner_id,))
            connection.execute("DELETE FROM allowed_epochs WHERE owner_id = ?", (owner_id,))
            connection.execute("DELETE FROM requests WHERE owner_id = ?", (owner_id,))

    def prepare_password_rotation(self, old_epoch: str, new_epoch: str,
                                  actor_owner_id: str | None = None) -> None:
        """Stage BEFORE password persistence; no change until callback changes.

        actor_owner_id must come from an already authenticated owner session,
        never from an unverified request field. The current authorization is
        rechecked here. None intentionally preserves nobody in the next epoch.
        On credential-write failure everybody valid in old_epoch stays valid.
        Serialize this call and the credential write with CredentialService's
        rotation lock; this method itself never changes the password.
        """
        old_epoch, new_epoch = _epoch(old_epoch), _epoch(new_epoch)
        if old_epoch == new_epoch:
            raise OwnershipError("same_epoch")
        if actor_owner_id is not None:
            actor_owner_id = _uuid(actor_owner_id)
        with self._transaction() as connection:
            self._current_epoch(old_epoch)
            if actor_owner_id is not None:
                actor = connection.execute(
                    "SELECT 1 FROM owners o JOIN allowed_epochs e ON e.owner_id = o.owner_id "
                    "WHERE o.owner_id = ? AND o.revoked = 0 AND e.epoch = ?",
                    (actor_owner_id, old_epoch),
                ).fetchone()
                if actor is None:
                    raise OwnershipError("unauthorized")
            # Drop any abandoned preparations, bounding epochs to current+next.
            connection.execute("DELETE FROM allowed_epochs WHERE epoch <> ?", (old_epoch,))
            if actor_owner_id is not None:
                connection.execute("INSERT INTO allowed_epochs VALUES (?, ?)", (actor_owner_id, new_epoch))

    def close(self) -> None:
        """End outstanding QR display authorization; retained owners are durable."""
        with self._lock:
            if not self._closed:
                self.close_window()
                self._closed = True
