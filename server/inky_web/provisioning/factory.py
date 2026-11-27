"""Internal, opt-in factory initialization assertions; no OS or wire contract.

The future trusted OS adapter must verify and consume an independently retained
initialization receipt before constructing these values. These Python types do
neither: they are not credentials, network input parsers, or permission to reset
an existing frame. In particular, reopening a store always needs the same receipt
AND identity, never just another identity carrying the old receipt.

The expected identity can be prepared in memory before journaling pending. If a
crash then loses its private key, the future orchestrator must require recovery,
not generate a replacement pin. Identity/key persistence is outside this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from inky_web.provisioning.identity import canonical_uuid, validate_token


class FactoryState(StrEnum):
    PENDING = "pending"
    FACTORY = "factory"
    ADOPTED = "adopted"
    RECOVERY = "recovery"


class FactoryRecoveryRequired(OSError):
    """A fixed local error; evidence is preserved, not rewritten as recovery.

    RECOVERY is an observed failure, never a database state that could conceal
    corruption or grant a new initialization attempt.
    """

    state = FactoryState.RECOVERY

    def __init__(self) -> None:
        super().__init__("Factory initialization requires explicit local recovery")


@dataclass(frozen=True)
class InitializationReceipt:
    """Assertion supplied only by a future trusted local initialization adapter.

    The digest is an opaque SHA-256-shaped binding, not a specified OS receipt
    format or a cryptographic verification of that receipt.
    """

    receipt_id: str
    digest: str = field(repr=False)

    def __post_init__(self) -> None:
        canonical_uuid(self.receipt_id)
        if type(self.digest) is not str:
            raise ValueError("Invalid initialization receipt")
        validate_token(self.digest)


@dataclass(frozen=True)
class FactoryIdentity:
    """Expected durable frame UUID and public-key pin, never a private key."""

    frame_id: str
    spki_sha256: str

    def __post_init__(self) -> None:
        canonical_uuid(self.frame_id)
        if type(self.spki_sha256) is not str:
            raise ValueError("Invalid factory identity")
        validate_token(self.spki_sha256)


@dataclass(frozen=True)
class FactoryStatus:
    state: FactoryState
    identity: FactoryIdentity
    first_owner_id: str | None


# The original ownership tables remain authoritative. This single journal row
# joins their SQLite transaction; there is no second ownership store to reconcile.
FACTORY_SCHEMA = """
CREATE TABLE factory_initialization (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    receipt_id TEXT NOT NULL,
    receipt_digest TEXT NOT NULL,
    frame_id TEXT NOT NULL,
    spki_sha256 TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'factory', 'adopted')),
    first_owner_id TEXT REFERENCES owners(owner_id),
    CHECK ((state = 'adopted' AND first_owner_id IS NOT NULL)
        OR (state IN ('pending', 'factory') AND first_owner_id IS NULL))
);
PRAGMA user_version = 2;
"""
