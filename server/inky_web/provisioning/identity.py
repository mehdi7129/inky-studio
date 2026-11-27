"""One durable frame identity and a strictly local, versioned adoption QR.

The self-signed certificate is an *explicit per-frame trust anchor*, only after
its SPKI has been matched to the physical QR. A certificate obtained over BLE
is untrusted input. This module never enables an accept-all client trust policy.
Apple's SSL policy bounds leaf validity, including explicitly anchored leaves.
Certificates last 396 days; renewal keeps the same private key and QR pin.
An implausible backwards RTC never causes a key or certificate replacement.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import ssl
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

HEX_TOKEN = re.compile(r"[0-9a-f]{64}\Z")
EARLIEST_CLOCK = datetime(2026, 1, 1, tzinfo=UTC)
CERTIFICATE_LIFETIME = timedelta(days=396)
CLOCK_SKEW = timedelta(minutes=5)
RENEW_BEFORE = timedelta(days=90)
MAX_QR_BYTES = 512
MAX_IDENTITY_BYTES = 16_384


class IdentityFormatError(ValueError):
    def __init__(self) -> None:
        super().__init__("Invalid frame identity; explicit local recovery is required")


class IdentityStorageError(OSError):
    def __init__(self, *, committed: bool = False) -> None:
        super().__init__("Cannot persist the private frame identity")
        self.committed = committed


@dataclass(frozen=True)
class SecretToken:
    """A secret requires explicit .value access; logs/repr remain redacted."""

    value: str = field(repr=False)

    def __post_init__(self) -> None:
        validate_token(self.value)

    def __repr__(self) -> str:
        return "SecretToken(<redacted>)"

    __str__ = __repr__


def validate_token(value: str | SecretToken) -> str:
    value = value.value if isinstance(value, SecretToken) else value
    if not isinstance(value, str) or HEX_TOKEN.fullmatch(value) is None:
        raise ValueError("Expected a canonical 32-byte hexadecimal token")
    return value


def canonical_uuid(value: str) -> str:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError, TypeError):
        raise ValueError("Expected a canonical UUID") from None
    return value


def private_directory(path: Path) -> Path:
    """Create/restrict the dedicated directory, never follow its final symlink."""
    path = Path(path)
    if path.is_symlink():
        raise OSError("Private directory must not be a symlink")
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not path.is_dir():
        raise OSError("Private directory is not a directory")
    path.chmod(0o700)
    return path


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def private_lock(path: Path) -> Iterator[None]:
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("Private lock is not a regular file")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _spki(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


@dataclass(frozen=True)
class Identity:
    frame_id: str
    cert_pem: bytes = field(repr=False)
    key_pem: bytes = field(repr=False)
    _directory: Path = field(repr=False)

    @property
    def server_name(self) -> str:
        return f"frame-{self.frame_id}.inky.invalid"

    @property
    def cert_der(self) -> bytes:
        return x509.load_pem_x509_certificate(self.cert_pem).public_bytes(serialization.Encoding.DER)

    @property
    def spki_sha256(self) -> str:
        return hashlib.sha256(_spki(x509.load_pem_x509_certificate(self.cert_pem).public_key())).hexdigest()

    @property
    def issued_at(self) -> datetime:
        return x509.load_pem_x509_certificate(self.cert_pem).not_valid_before_utc + CLOCK_SKEW

    def refresh_certificate_if_needed(self, now: datetime | None = None) -> Identity:
        """Return current/renewed identity; never rotate its key or physical pin.

        The caller must reload TLS contexts when this returns a changed leaf.
        A clock older than issuance reuses the persisted leaf unchanged. Once a
        leaf expires, correcting the frame's clock is required for renewal.
        """
        with private_lock(self._directory / ".identity.lock"):
            current = _parse(_read(self._directory / "identity.json"), self._directory)
            if current.frame_id != self.frame_id or current.spki_sha256 != self.spki_sha256:
                raise IdentityFormatError()
            return _renew_if_needed(current, _now(now))

    def qr_payload(self, token: str | SecretToken) -> str:
        """Secret, non-URL JSON. Never put the returned text in logs/events."""
        payload = json.dumps({"v": 1, "id": self.frame_id, "k": self.spki_sha256,
                              "t": validate_token(token)}, separators=(",", ":"))
        if len(payload.encode("utf-8")) > MAX_QR_BYTES:
            raise ValueError("QR exceeds its bounded representation")
        return payload

    def ssl_context(self) -> ssl.SSLContext:
        """Server context for MemoryBIO/HTTPS; no resumption tickets or 0-RTT.

        OpenSSL's Python API requires filenames to load a chain. Private scratch
        files exist only during that call and are removed before returning.
        This is a server context, not a policy for trusting a remote server.
        """
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.num_tickets = 0
        context.options |= ssl.OP_NO_TICKET
        with tempfile.TemporaryDirectory(prefix=".tls-", dir=self._directory) as scratch:
            cert_path, key_path = Path(scratch) / "certificate.pem", Path(scratch) / "key.pem"
            for path, data in ((cert_path, self.cert_pem), (key_path, self.key_pem)):
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as output:
                    output.write(data)
            context.load_cert_chain(cert_path, key_path)
        return context

    def materialize_tls_files(self) -> tuple[Path, Path]:
        """Private derived PEM files for Uvicorn's startup-only TLS options.

        identity.json remains authoritative. These copies are recreated from the
        already validated bundle under its lock, never read back as identity.
        No key rotation can happen implicitly between the two writes.
        """
        certificate = self._directory / "tls-certificate.pem"
        key = self._directory / "tls-key.pem"
        with private_lock(self._directory / ".identity.lock"):
            for destination, data in ((certificate, self.cert_pem), (key, self.key_pem)):
                staging = None
                try:
                    with tempfile.NamedTemporaryFile(dir=self._directory, prefix=".tls-", delete=False) as output:
                        staging = Path(output.name)
                        os.fchmod(output.fileno(), 0o600)
                        output.write(data)
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(staging, destination)
                finally:
                    if staging is not None:
                        staging.unlink(missing_ok=True)
            _sync_directory(self._directory)
        return certificate, key


def _now(value: datetime | None) -> datetime:
    value = datetime.now(UTC) if value is None else value
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("An aware UTC clock is required")
    return value.astimezone(UTC).replace(microsecond=0)


def _certificate(key: ec.EllipticCurvePrivateKey, frame_id: str, now: datetime) -> bytes:
    server_name = f"frame-{frame_id}.inky.invalid"
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, server_name)])
    certificate = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - CLOCK_SKEW).not_valid_after(now + CERTIFICATE_LIFETIME)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                                    key_encipherment=False, data_encipherment=False,
                                    key_agreement=False, key_cert_sign=True, crl_sign=True,
                                    encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(server_name)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM)


def _generate(directory: Path, now: datetime) -> Identity:
    if now < EARLIEST_CLOCK:
        raise ValueError("A plausible clock is required to initialize the frame certificate")
    frame_id = str(uuid4())
    key = ec.generate_private_key(ec.SECP256R1())
    return Identity(frame_id, _certificate(key, frame_id, now),
                    key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()), directory)


def _renew_if_needed(identity: Identity, now: datetime) -> Identity:
    certificate = x509.load_pem_x509_certificate(identity.cert_pem)
    if now < EARLIEST_CLOCK or now < identity.issued_at or certificate.not_valid_after_utc - now >= RENEW_BEFORE:
        return identity
    key = serialization.load_pem_private_key(identity.key_pem, password=None)
    renewed = Identity(identity.frame_id, _certificate(key, identity.frame_id, now),
                       identity.key_pem, identity._directory)
    _persist(renewed, identity._directory / "identity.json")
    return renewed


def _parse(record: object, directory: Path) -> Identity:
    try:
        if not isinstance(record, dict) or set(record) != {"v", "id", "cert_pem", "key_pem"}:
            raise ValueError
        if type(record["v"]) is not int or record["v"] != 1:
            raise ValueError
        frame_id = canonical_uuid(record["id"])
        key_pem, cert_pem = record["key_pem"].encode("ascii"), record["cert_pem"].encode("ascii")
        key = serialization.load_pem_private_key(key_pem, password=None)
        cert = x509.load_pem_x509_certificate(cert_pem)
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ValueError
        expected_name = f"frame-{frame_id}.inky.invalid"
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, expected_name)])
        if cert.subject != subject or cert.issuer != subject or _spki(key.public_key()) != _spki(cert.public_key()):
            raise ValueError
        key.public_key().verify(cert.signature, cert.tbs_certificate_bytes,
                                ec.ECDSA(cert.signature_hash_algorithm))
        issued_at = cert.not_valid_before_utc + CLOCK_SKEW
        if issued_at < EARLIEST_CLOCK or cert.not_valid_after_utc - issued_at != CERTIFICATE_LIFETIME:
            raise ValueError
        constraints = cert.extensions.get_extension_for_class(x509.BasicConstraints)
        if not constraints.critical or constraints.value != x509.BasicConstraints(ca=True, path_length=0):
            raise ValueError
        if list(cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value) != [x509.DNSName(expected_name)]:
            raise ValueError
        if list(cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value) != [ExtendedKeyUsageOID.SERVER_AUTH]:
            raise ValueError
        return Identity(frame_id, cert_pem, key_pem, directory)
    except (ValueError, TypeError, AttributeError, KeyError, InvalidSignature, x509.ExtensionNotFound):
        raise IdentityFormatError() from None


def _read(path: Path) -> object:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as source:
        file_stat = os.fstat(source.fileno())
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > MAX_IDENTITY_BYTES:
            raise IdentityFormatError()
        os.fchmod(source.fileno(), 0o600)
        try:
            return json.loads(source.read(MAX_IDENTITY_BYTES + 1))
        except (ValueError, UnicodeError):
            raise IdentityFormatError() from None


def _persist(identity: Identity, path: Path) -> None:
    temporary_path = None
    committed = False
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="ascii", dir=path.parent,
                                         prefix=".identity-", delete=False) as output:
            temporary_path = Path(output.name)
            os.fchmod(output.fileno(), 0o600)
            json.dump({"v": 1, "id": identity.frame_id,
                       "cert_pem": identity.cert_pem.decode("ascii"),
                       "key_pem": identity.key_pem.decode("ascii")}, output, separators=(",", ":"))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
        committed = True
        _sync_directory(path.parent)
    except OSError:
        raise IdentityStorageError(committed=committed) from None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def load_or_create_identity(private_dir: Path, *, now: datetime | None = None) -> Identity:
    """Load one stable bundle, or initialize once when the bundle is absent.

    Corrupt/inconsistent/unreadable bundles are never replaced. A process lock
    serializes first creation across concurrent application starts.
    """
    try:
        directory = private_directory(private_dir)
        path = directory / "identity.json"
        with private_lock(directory / ".identity.lock"):
            try:
                return _renew_if_needed(_parse(_read(path), directory), _now(now))
            except FileNotFoundError:
                identity = _generate(directory, _now(now))
                _persist(identity, path)
                return identity
    except (IdentityStorageError, IdentityFormatError):
        raise
    except OSError:
        raise IdentityStorageError() from None
