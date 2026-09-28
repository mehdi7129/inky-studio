"""Opt-in durable identity preparation and journaled certificate publication.

Nothing imports this module from the runtime. It grants no factory authority,
sets no clock, and never migrates a legacy installation. An OS orchestrator must
authorize preparation and retain an independent consumed receipt: losing all
application files must never authorize another call to create().

The prepared identity and bounded operation journal share one atomic bundle.
All publication/repair calls reopen that bundle; a missing journal is never
silently recreated. Normal identity loading and renewal remain unchanged.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from cryptography import x509
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from . import identity as normal
from .factory import FactoryIdentity

if TYPE_CHECKING:
    from .bootstrap_tls import BootstrapTLSContext

PREPARED_IDENTITY_FILENAME = "bootstrap-identity.json"
BUNDLE_NAME = PREPARED_IDENTITY_FILENAME
MAX_BUNDLE_BYTES = 1_048_576
MAX_OPERATIONS = 64
BOOTSTRAP_ISSUANCE = datetime(2000, 1, 1, tzinfo=UTC) + normal.CLOCK_SKEW
MIN_CERTIFICATE_EPOCH = int(normal.EARLIEST_CLOCK.timestamp())
# This is a serialization bound for the certificate's 396-day interval, not a
# policy for accepting a phone's time or evidence that a system clock was set.
MAX_CERTIFICATE_EPOCH = int(datetime(9998, 1, 1, tzinfo=UTC).timestamp())


class BootstrapIdentityRecoveryRequired(OSError):
    def __init__(self) -> None:
        super().__init__("Prepared identity requires explicit local recovery")


class CertificateConflict(ValueError):
    def __init__(self) -> None:
        super().__init__("Certificate operation conflicts with durable state")


class CertificateJournalFull(ValueError):
    def __init__(self) -> None:
        super().__init__("Certificate operation journal requires explicit maintenance")


@dataclass(frozen=True)
class ClockResult:
    """Trusted local adapter assertion, neither network input nor independent UTC.

    Constructing this object does not verify a receipt or invoke a clock setter.
    The future coordinator must validate the privileged result and authorization.
    """

    operation_id: str
    epoch_seconds: int

    def __post_init__(self) -> None:
        normal.canonical_uuid(self.operation_id)
        if type(self.epoch_seconds) is not int or not MIN_CERTIFICATE_EPOCH <= self.epoch_seconds <= MAX_CERTIFICATE_EPOCH:
            raise ValueError("Invalid local clock result")


@dataclass(frozen=True)
class CertificateOperationResult:
    """Historical completed result; load_current_identity() obtains today's leaf."""

    operation_id: str
    certificate_sha256: str
    certificate_der: bytes = field(repr=False)


def certificate_sha256(identity: normal.Identity) -> str:
    return hashlib.sha256(identity.cert_der).hexdigest()


def _json_bytes(record: dict) -> bytes:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _strict_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate field")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("Invalid JSON constant")


def _read_json(path: Path, limit: int) -> dict:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            raise BootstrapIdentityRecoveryRequired()
        os.fchmod(source.fileno(), 0o600)
        data = source.read(limit + 1)
    if len(data) > limit:
        raise BootstrapIdentityRecoveryRequired()
    try:
        value = json.loads(data, object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    except RecursionError:
        raise BootstrapIdentityRecoveryRequired() from None
    if type(value) is not dict:
        raise BootstrapIdentityRecoveryRequired()
    return value


@contextmanager
def _lock(path: Path) -> Iterator[None]:
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise BootstrapIdentityRecoveryRequired()
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _exists(path: Path) -> bool:
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False


def _directory(path: Path, *, create: bool) -> Path:
    path = Path(path)
    if not create and (path.is_symlink() or not path.is_dir()):
        raise BootstrapIdentityRecoveryRequired()
    return normal.private_directory(path)


def _atomic_json(path: Path, record: dict, *, exclusive: bool) -> None:
    data = _json_bytes(record)
    if len(data) > MAX_BUNDLE_BYTES:
        raise BootstrapIdentityRecoveryRequired()
    staging = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".prepared-", delete=False) as output:
            staging = Path(output.name)
            os.fchmod(output.fileno(), 0o600)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        if exclusive:
            # Atomic no-replace publication. The complete, fsynced inode becomes
            # visible at once; a competing or corrupt existing file is preserved.
            os.link(staging, path, follow_symlinks=False)
        else:
            os.replace(staging, path)
        normal._sync_directory(path.parent)
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)


def _normal_record(frame_id: str, key_pem: bytes, cert_pem: bytes) -> dict:
    return {"v": 1, "id": frame_id, "key_pem": key_pem.decode("ascii"), "cert_pem": cert_pem.decode("ascii")}


def _normal_identity(record: dict, directory: Path, frame_id: str, key_pem: bytes) -> normal.Identity:
    identity = normal._parse(record, directory)
    if identity.frame_id != frame_id or identity.key_pem != key_pem:
        raise BootstrapIdentityRecoveryRequired()
    return identity


def _intent(initialization_intent: str, binding: FactoryIdentity, operation: dict) -> str:
    parameters = {key: operation[key] for key in ("operation_id", "kind", "old_certificate_sha256", "epoch_seconds")}
    parameters.update({"initialization_intent": initialization_intent, "frame_id": binding.frame_id,
                       "spki_sha256": binding.spki_sha256})
    return hashlib.sha256(_json_bytes(parameters)).hexdigest()


def _result(operation: dict) -> CertificateOperationResult:
    cert = x509.load_pem_x509_certificate(operation["candidate_cert_pem"].encode("ascii"))
    return CertificateOperationResult(operation["operation_id"], operation["candidate_sha256"],
                                      cert.public_bytes(serialization.Encoding.DER))


@dataclass(frozen=True)
class PreparedFactoryIdentity:
    initialization_intent: str
    frame_id: str
    key_pem: bytes = field(repr=False)
    bootstrap_cert_pem: bytes = field(repr=False)
    _directory: Path = field(repr=False)

    @property
    def binding(self) -> FactoryIdentity:
        key = serialization.load_pem_private_key(self.key_pem, password=None)
        return FactoryIdentity(self.frame_id, hashlib.sha256(normal._spki(key.public_key())).hexdigest())

    @property
    def bootstrap_certificate_der(self) -> bytes:
        return x509.load_pem_x509_certificate(self.bootstrap_cert_pem).public_bytes(serialization.Encoding.DER)

    def bootstrap_tls_context(self) -> BootstrapTLSContext:
        """Dedicated server context, already constrained to bootstrap ALPN.

        Reusing the strict TLS settings/file cleanup of Identity does not turn
        this historical leaf into a normal Identity or change its normal parser.
        """
        from .bootstrap_tls import BootstrapTLSContext

        try:
            with _lock(self._directory / ".bootstrap-identity.lock"):
                self._reload()
                return BootstrapTLSContext(normal.Identity(self.frame_id, self.bootstrap_cert_pem,
                                                            self.key_pem, self._directory))
        except OSError:
            raise BootstrapIdentityRecoveryRequired() from None

    @classmethod
    def create(cls, private_dir: Path, *, initialization_intent: str) -> PreparedFactoryIdentity:
        """Explicit preparation only. No RTC read, normal identity or authority."""
        normal.canonical_uuid(initialization_intent)
        try:
            directory = _directory(private_dir, create=True)
            with _lock(directory / ".bootstrap-identity.lock"), _lock(directory / ".identity.lock"):
                if _exists(directory / BUNDLE_NAME) or _exists(directory / "identity.json"):
                    raise CertificateConflict()
                key = ec.generate_private_key(ec.SECP256R1())
                frame_id = str(uuid4())
                key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                            serialization.NoEncryption())
                # Existing pure certificate builder, deliberately not its normal
                # load/generate path: issuance is fixed and independent of RTC.
                cert_pem = normal._certificate(key, frame_id, BOOTSTRAP_ISSUANCE)
                record = {"v": 1, "kind": "prepared-factory-identity", "initialization_intent": initialization_intent,
                          "frame_id": frame_id, "key_pem": key_pem.decode("ascii"),
                          "bootstrap_cert_pem": cert_pem.decode("ascii"), "operations": []}
                _atomic_json(directory / BUNDLE_NAME, record, exclusive=True)
                prepared, _ = _load(directory)
                return prepared
        except (OSError, ValueError, TypeError, InvalidSignature, UnsupportedAlgorithm) as error:
            if isinstance(error, CertificateConflict):
                raise
            raise BootstrapIdentityRecoveryRequired() from None

    @classmethod
    def reopen(cls, private_dir: Path, *, expected_intent: str | None = None,
               expected_binding: FactoryIdentity | None = None) -> PreparedFactoryIdentity:
        """Read-only authority semantics; no create, migration or reset on absence.

        Omitting expected_intent allows an OS coordinator to inspect the validated
        local intent before beginning its independent receipt transaction. The
        caller still has to authorize that transaction; this is not a receipt.
        """
        if expected_intent is not None:
            normal.canonical_uuid(expected_intent)
        if expected_binding is not None and type(expected_binding) is not FactoryIdentity:
            raise ValueError("Invalid expected identity assertion")
        try:
            directory = _directory(private_dir, create=False)
            with _lock(directory / ".bootstrap-identity.lock"):
                prepared, _ = _load(directory)
                if ((expected_intent is not None and prepared.initialization_intent != expected_intent)
                        or (expected_binding is not None and prepared.binding != expected_binding)):
                    raise BootstrapIdentityRecoveryRequired()
                return prepared
        except (OSError, ValueError, TypeError, InvalidSignature, UnsupportedAlgorithm):
            raise BootstrapIdentityRecoveryRequired() from None

    def _reload(self) -> dict:
        prepared, record = _load(_directory(self._directory, create=False))
        if prepared != self:
            raise BootstrapIdentityRecoveryRequired()
        return record

    def load_current_identity(self) -> normal.Identity:
        """Strictly load current normal bytes; never issue, renew or restore them."""
        try:
            with _lock(self._directory / ".bootstrap-identity.lock"), _lock(self._directory / ".identity.lock"):
                self._reload()
                return _normal_identity(_read_json(self._directory / "identity.json", normal.MAX_IDENTITY_BYTES),
                                        self._directory, self.frame_id, self.key_pem)
        except (OSError, ValueError, TypeError, InvalidSignature, UnsupportedAlgorithm):
            raise BootstrapIdentityRecoveryRequired() from None

    def verify_current_or_unpublished(self) -> normal.Identity | None:
        """Check actual normal binding, or prove publication is still pending.

        A missing normal file is allowed only before the initial publication
        completes. This is a structural recovery check, not proof of valid UTC,
        network readiness or ownership. No certificate is published or renewed.
        """
        try:
            with _lock(self._directory / ".bootstrap-identity.lock"), _lock(self._directory / ".identity.lock"):
                record = self._reload()
                current = self._current_or_absent()
                if current is not None:
                    return current
                operations = record["operations"]
                if not operations or (len(operations) == 1 and operations[0]["state"] == "pending"):
                    return None
                raise BootstrapIdentityRecoveryRequired()
        except (OSError, ValueError, TypeError, InvalidSignature, UnsupportedAlgorithm):
            raise BootstrapIdentityRecoveryRequired() from None

    def publish_initial(self, *, operation_id: str, clock_result: ClockResult) -> CertificateOperationResult:
        return self._publish("initial", operation_id, clock_result, None)

    def repair_existing(self, *, operation_id: str, clock_result: ClockResult,
                        expected_old_certificate_sha256: str) -> CertificateOperationResult:
        if type(expected_old_certificate_sha256) is not str:
            raise ValueError("Invalid expected certificate digest")
        normal.validate_token(expected_old_certificate_sha256)
        return self._publish("repair", operation_id, clock_result, expected_old_certificate_sha256)

    def _publish(self, kind: str, operation_id: str, clock_result: ClockResult,
                 old_digest: str | None) -> CertificateOperationResult:
        normal.canonical_uuid(operation_id)
        if type(clock_result) is not ClockResult or clock_result.operation_id != operation_id:
            raise ValueError("A matching local clock result is required")
        try:
            with _lock(self._directory / ".bootstrap-identity.lock"), _lock(self._directory / ".identity.lock"):
                record = self._reload()
                operations = record["operations"]
                request = {"operation_id": operation_id, "kind": kind, "old_certificate_sha256": old_digest,
                           "epoch_seconds": clock_result.epoch_seconds}
                request_intent = _intent(self.initialization_intent, self.binding, request)
                operation = next((item for item in operations if item["operation_id"] == operation_id), None)
                if operation is not None:
                    if operation["intent"] != request_intent:
                        raise CertificateConflict()
                    if operation["state"] == "completed":
                        return _result(operation)
                else:
                    if any(item["state"] == "pending" for item in operations):
                        raise CertificateConflict()
                    if len(operations) >= MAX_OPERATIONS:
                        raise CertificateJournalFull()
                    current = self._current_or_absent()
                    if kind == "initial":
                        if operations or current is not None:
                            raise CertificateConflict()
                    elif not operations or current is None or certificate_sha256(current) != old_digest:
                        raise CertificateConflict()
                    now = datetime.fromtimestamp(clock_result.epoch_seconds, UTC)
                    key = serialization.load_pem_private_key(self.key_pem, password=None)
                    candidate = normal._certificate(key, self.frame_id, now)
                    checked = _normal_identity(_normal_record(self.frame_id, self.key_pem, candidate),
                                               self._directory, self.frame_id, self.key_pem)
                    operation = request | {"intent": request_intent, "state": "pending",
                                           "candidate_cert_pem": candidate.decode("ascii"),
                                           "candidate_sha256": certificate_sha256(checked)}
                    operations.append(operation)
                    _atomic_json(self._directory / BUNDLE_NAME, record, exclusive=False)
                    record = self._reload()  # Candidate bytes are now durable, not regenerated.
                    operation = record["operations"][-1]
                self._publish_candidate(operation)
                current = self._current_or_absent()
                if current is None or certificate_sha256(current) != operation["candidate_sha256"]:
                    raise BootstrapIdentityRecoveryRequired()
                operation["state"] = "completed"
                _atomic_json(self._directory / BUNDLE_NAME, record, exclusive=False)
                completed = self._reload()
                return _result(next(item for item in completed["operations"] if item["operation_id"] == operation_id))
        except (CertificateConflict, CertificateJournalFull):
            raise
        except (OSError, ValueError, TypeError, InvalidSignature, UnsupportedAlgorithm):
            raise BootstrapIdentityRecoveryRequired() from None

    def _current_or_absent(self) -> normal.Identity | None:
        path = self._directory / "identity.json"
        try:
            record = _read_json(path, normal.MAX_IDENTITY_BYTES)
        except FileNotFoundError:
            return None
        return _normal_identity(record, self._directory, self.frame_id, self.key_pem)

    def _publish_candidate(self, operation: dict) -> None:
        current = self._current_or_absent()
        if current is not None and certificate_sha256(current) == operation["candidate_sha256"]:
            return  # Publication succeeded before a crash; only finalize the journal.
        if operation["kind"] == "initial":
            if current is not None:
                raise CertificateConflict()
        elif current is None or certificate_sha256(current) != operation["old_certificate_sha256"]:
            raise CertificateConflict()
        candidate = _normal_record(self.frame_id, self.key_pem, operation["candidate_cert_pem"].encode("ascii"))
        _atomic_json(self._directory / "identity.json", candidate, exclusive=operation["kind"] == "initial")


def _load(directory: Path) -> tuple[PreparedFactoryIdentity, dict]:
    try:
        return _load_checked(directory)
    except (OSError, ValueError, TypeError, AttributeError, KeyError, InvalidSignature,
            UnsupportedAlgorithm, x509.ExtensionNotFound):
        raise BootstrapIdentityRecoveryRequired() from None


def _load_checked(directory: Path) -> tuple[PreparedFactoryIdentity, dict]:
    record = _read_json(directory / BUNDLE_NAME, MAX_BUNDLE_BYTES)
    if set(record) != {"v", "kind", "initialization_intent", "frame_id", "key_pem", "bootstrap_cert_pem", "operations"}:
        raise BootstrapIdentityRecoveryRequired()
    if type(record["v"]) is not int or record["v"] != 1 or record["kind"] != "prepared-factory-identity":
        raise BootstrapIdentityRecoveryRequired()
    intent, frame_id = normal.canonical_uuid(record["initialization_intent"]), normal.canonical_uuid(record["frame_id"])
    key_pem, cert_pem = record["key_pem"].encode("ascii"), record["bootstrap_cert_pem"].encode("ascii")
    if len(key_pem) > normal.MAX_IDENTITY_BYTES or len(cert_pem) > normal.MAX_IDENTITY_BYTES:
        raise BootstrapIdentityRecoveryRequired()
    key = serialization.load_pem_private_key(key_pem, password=None)
    cert = x509.load_pem_x509_certificate(cert_pem)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise BootstrapIdentityRecoveryRequired()
    if key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                         serialization.NoEncryption()) != key_pem:
        raise BootstrapIdentityRecoveryRequired()
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"frame-{frame_id}.inky.invalid")])
    if (cert.subject != subject or cert.issuer != subject or not isinstance(cert.signature_hash_algorithm, hashes.SHA256)
            or normal._spki(cert.public_key()) != normal._spki(key.public_key())
            or cert.not_valid_before_utc != BOOTSTRAP_ISSUANCE - normal.CLOCK_SKEW
            or cert.not_valid_after_utc != BOOTSTRAP_ISSUANCE + normal.CERTIFICATE_LIFETIME
            or cert.public_bytes(serialization.Encoding.PEM) != cert_pem):
        raise BootstrapIdentityRecoveryRequired()
    key.public_key().verify(cert.signature, cert.tbs_certificate_bytes, ec.ECDSA(hashes.SHA256()))
    constraints = cert.extensions.get_extension_for_class(x509.BasicConstraints)
    usage = cert.extensions.get_extension_for_class(x509.KeyUsage)
    if (not constraints.critical or constraints.value != x509.BasicConstraints(ca=True, path_length=0)
            or not usage.critical or not usage.value.digital_signature or not usage.value.key_cert_sign
            or list(cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value) != [ExtendedKeyUsageOID.SERVER_AUTH]
            or list(cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value) != [x509.DNSName(f"frame-{frame_id}.inky.invalid")]):
        raise BootstrapIdentityRecoveryRequired()
    prepared = PreparedFactoryIdentity(intent, frame_id, key_pem, cert_pem, directory)
    operations = record["operations"]
    if type(operations) is not list or len(operations) > MAX_OPERATIONS:
        raise BootstrapIdentityRecoveryRequired()
    if not operations and _exists(directory / "identity.json"):
        # A normal identity cannot precede this component's initial write-ahead
        # intent. Losing/clearing its journal is not a new initialization.
        raise BootstrapIdentityRecoveryRequired()
    seen = set()
    for index, operation in enumerate(operations):
        if type(operation) is not dict or set(operation) != {
            "operation_id", "kind", "old_certificate_sha256", "epoch_seconds", "intent", "state",
            "candidate_cert_pem", "candidate_sha256",
        }:
            raise BootstrapIdentityRecoveryRequired()
        operation_id = normal.canonical_uuid(operation["operation_id"])
        ClockResult(operation_id, operation["epoch_seconds"])
        if (operation_id in seen or operation["kind"] != ("initial" if index == 0 else "repair")
                or operation["state"] not in {"pending", "completed"}
                or (operation["state"] == "pending" and index != len(operations) - 1)):
            raise BootstrapIdentityRecoveryRequired()
        seen.add(operation_id)
        if index == 0:
            if operation["old_certificate_sha256"] is not None:
                raise BootstrapIdentityRecoveryRequired()
        else:
            normal.validate_token(operation["old_certificate_sha256"])
        candidate = _normal_identity(_normal_record(frame_id, key_pem, operation["candidate_cert_pem"].encode("ascii")),
                                     directory, frame_id, key_pem)
        if (operation["intent"] != _intent(intent, prepared.binding, operation)
                or operation["candidate_sha256"] != certificate_sha256(candidate)
                or candidate.issued_at != datetime.fromtimestamp(operation["epoch_seconds"], UTC)):
            raise BootstrapIdentityRecoveryRequired()
    return prepared, record
