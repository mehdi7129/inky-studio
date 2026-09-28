"""Opt-in local first-boot coordinator; no runtime, OS socket or wire protocol.

The injected adapter is the trusted OS boundary. Its actual begin call, never a
cached application grant, decides whether a missing ownership store may be
created. Prepared identity and uncertain failures are retained for recovery.
Credentials must already exist: this module neither creates a password nor
claims an owner, displays a QR, repairs a clock or publishes a normal identity.
"""
from __future__ import annotations

import fcntl
import os
import stat
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .bootstrap_identity import PREPARED_IDENTITY_FILENAME, PreparedFactoryIdentity
from .factory import FactoryRecoveryRequired, FactoryStatus, InitializationReceipt
from .identity import canonical_uuid, private_directory, validate_token
from .ownership import OwnershipStore


class InitializationAdapter(Protocol):
    """Trusted local adapter; implementations must perform real OS operations.

    These return only the inspect/begin subobjects of the OS receipt model.
    This protocol does not define a socket, RPC or remotely callable endpoint.
    """

    def inspect_initialization(self) -> dict: ...

    def begin_initialization(self, intent: str) -> dict: ...


class FirstBootRefused(FactoryRecoveryRequired):
    """No begin was submitted by this invocation; local preparation may exist."""

    begin_attempted = False


class FirstBootUncertain(FactoryRecoveryRequired):
    """Begin was submitted: consumption or local commits may have happened."""

    begin_attempted = True


@dataclass(frozen=True)
class FirstBootResult:
    prepared_identity: PreparedFactoryIdentity
    ownership: OwnershipStore
    status: FactoryStatus


def _ordinary(info: os.stat_result) -> None:
    if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1 or info.st_uid != os.geteuid()):
        raise FirstBootRefused()


@contextmanager
def _workflow_lock(directory: Path) -> Iterator[None]:
    """Stable, separate lock; O_NONBLOCK prevents FIFO opens from hanging."""
    path = directory / ".first-boot.lock"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(descriptor)
        _ordinary(info)
        if info.st_size != 0:
            raise FirstBootRefused()
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        current = os.stat(path, follow_symlinks=False)
        _ordinary(current)
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise FirstBootRefused()
        yield
    finally:
        os.close(descriptor)


def _preflight_existing(directory: Path, names: tuple[str, ...]) -> None:
    # Check special files nonblockingly before entering downstream storage
    # APIs; cooperating first-boot callers hold the workflow lock.
    for name in names:
        path = directory / name
        if not os.path.lexists(path):
            continue
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            _ordinary(os.fstat(descriptor))
        finally:
            os.close(descriptor)


def _receipt_response(value: object, *, inspect: bool) -> tuple[str, str | None, InitializationReceipt | None]:
    if type(value) is not dict or type(value.get("status")) is not str:
        raise ValueError("Invalid initialization response")
    status = value["status"]
    if inspect and status == "authorized" and set(value) == {"status"}:
        return status, None, None
    allowed = {"consumed"} if inspect else {"newly_consumed", "already_consumed"}
    if status not in allowed or set(value) != {"status", "intent", "receipt"}:
        raise ValueError("Invalid initialization response")
    intent, receipt = value["intent"], value["receipt"]
    if type(intent) is not str or type(receipt) is not dict or set(receipt) != {"receipt_id", "digest"}:
        raise ValueError("Invalid initialization response")
    canonical_uuid(intent)
    if type(receipt["receipt_id"]) is not str or type(receipt["digest"]) is not str:
        raise ValueError("Invalid initialization response")
    return status, intent, InitializationReceipt(receipt["receipt_id"], receipt["digest"])


class FirstBootCoordinator:
    """Serialize prepare -> consume -> ledger -> verified ready, without retry.

    ``verify_credentials`` must read and verify already-persisted credential
    material every time it is called, returning its canonical current epoch.
    It is also retained by OwnershipStore so later password rotation is observed.
    Tests using a fake callback do not qualify real credential persistence.
    """

    def __init__(self, private_dir: Path, adapter: InitializationAdapter,
                 verify_credentials: Callable[[], str], *,
                 clock: Callable[[], float] = time.time,
                 monotonic: Callable[[], float] = time.monotonic):
        self.directory = Path(private_dir)
        self.adapter = adapter
        self.verify_credentials = verify_credentials
        self.clock, self.monotonic = clock, monotonic

    def _current_epoch(self) -> str:
        value = self.verify_credentials()
        if type(value) is not str:
            raise ValueError("Invalid persisted credentials")
        return validate_token(value)

    def initialize(self) -> FirstBootResult:
        begin_attempted = False
        try:
            directory = private_directory(self.directory)
            with _workflow_lock(directory):
                state, os_intent, inspected_receipt = _receipt_response(
                    self.adapter.inspect_initialization(), inspect=True)
                _preflight_existing(directory, (
                    ".identity.lock", ".bootstrap-identity.lock", ".ownership.lock",
                    "ownership.sqlite3", PREPARED_IDENTITY_FILENAME,
                ))
                # Detect a missing/invalid local prerequisite before generating
                # an identity or consuming one-use OS authority. Do not capture
                # this epoch: credentials are read again after the begin call.
                self._current_epoch()
                prepared_path = directory / PREPARED_IDENTITY_FILENAME
                if state == "consumed":
                    prepared = PreparedFactoryIdentity.reopen(directory, expected_intent=os_intent)
                else:
                    # A DB without OS consumption is inconsistent, even when
                    # there are no owners. It is never fresh-factory evidence.
                    if os.path.lexists(directory / "ownership.sqlite3"):
                        raise FirstBootRefused()
                    if os.path.lexists(prepared_path):
                        prepared = PreparedFactoryIdentity.reopen(directory)
                    else:
                        prepared = PreparedFactoryIdentity.create(
                            directory, initialization_intent=str(uuid4()))
                intent, binding = prepared.initialization_intent, prepared.binding
                canonical_uuid(intent)
                prepared.verify_current_or_unpublished()
                begin_attempted = True  # Set BEFORE invoking the external boundary.
                grant, granted_intent, receipt = _receipt_response(
                    self.adapter.begin_initialization(intent), inspect=False)
                if granted_intent != intent or (state == "consumed" and (
                        grant != "already_consumed" or receipt != inspected_receipt)):
                    raise FirstBootUncertain()
                _preflight_existing(directory, (".ownership.lock", "ownership.sqlite3"))
                operation = (OwnershipStore.create_factory if grant == "newly_consumed"
                             else OwnershipStore.reopen_factory)
                store = operation(directory, self._current_epoch, receipt=receipt,
                                  expected_identity=binding, clock=self.clock, monotonic=self.monotonic)
                self._current_epoch()
                # Re-read durable material, rather than asserting an in-memory
                # prepared value after a credential callback or a store commit.
                verified = PreparedFactoryIdentity.reopen(
                    directory, expected_intent=intent, expected_binding=binding)
                verified.verify_current_or_unpublished()
                status = store.mark_factory_ready(verified.binding)
                return FirstBootResult(verified, store, status)
        except Exception:
            # No retry, secret/error reflection, grant cache or cleanup/reset.
            if begin_attempted:
                raise FirstBootUncertain() from None
            raise FirstBootRefused() from None
