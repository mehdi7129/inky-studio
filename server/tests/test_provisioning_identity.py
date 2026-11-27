"""Persistent TLS identity, secret handling and certificate renewal boundaries."""
from __future__ import annotations

import hashlib
import json
import ssl
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID

from inky_web.provisioning import identity

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def test_stable_identity_and_certificate_contract(tmp_path):
    first = identity.load_or_create_identity(tmp_path, now=NOW)
    again = identity.load_or_create_identity(tmp_path, now=NOW + timedelta(days=1))
    assert first == again
    key = serialization.load_pem_private_key(first.key_pem, password=None)
    assert isinstance(key.curve, ec.SECP256R1)
    assert first.key_pem.startswith(b"-----BEGIN PRIVATE KEY-----")
    certificate = x509.load_der_x509_certificate(first.cert_der)
    assert certificate.not_valid_before_utc == NOW - timedelta(minutes=5)
    assert certificate.not_valid_after_utc == NOW + timedelta(days=396)
    assert first.issued_at == NOW
    assert certificate.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    assert certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value == x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH])
    assert certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName) == [first.server_name]
    spki = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    assert first.spki_sha256 == hashlib.sha256(spki).hexdigest()
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "identity.json").stat().st_mode) == 0o600
    assert "PRIVATE KEY" not in repr(first)


def test_qr_has_exact_compact_non_url_contract(tmp_path):
    frame = identity.load_or_create_identity(tmp_path, now=NOW)
    token = identity.SecretToken("42" * 32)
    payload = frame.qr_payload(token)
    assert json.loads(payload) == {"v": 1, "id": frame.frame_id, "k": frame.spki_sha256, "t": token.value}
    assert payload == json.dumps(json.loads(payload), separators=(",", ":"))
    assert len(payload.encode()) <= 512 and not payload.startswith(("http:", "https:"))
    assert token.value not in str(token) and token.value not in repr(token)
    with pytest.raises(ValueError):
        frame.qr_payload("not-a-token")


@pytest.mark.parametrize("payload", [b"{", b"[]", b"null", b"{}", b"x" * 20_000])
def test_corrupt_bundle_never_recreated(tmp_path, payload):
    path = tmp_path / "identity.json"
    path.write_bytes(payload)
    with pytest.raises(identity.IdentityFormatError):
        identity.load_or_create_identity(tmp_path, now=NOW)
    assert path.read_bytes() == payload


@pytest.mark.parametrize("field,value", [("id", "00000000-0000-0000-0000-000000000000"), ("v", True), ("key_pem", "invalid")])
def test_inconsistent_bundle_fails_closed(tmp_path, field, value):
    identity.load_or_create_identity(tmp_path, now=NOW)
    path = tmp_path / "identity.json"
    record = json.loads(path.read_text())
    record[field] = value
    path.write_text(json.dumps(record))
    before = path.read_bytes()
    with pytest.raises(identity.IdentityFormatError):
        identity.load_or_create_identity(tmp_path, now=NOW)
    assert path.read_bytes() == before


def test_symlink_bundle_is_not_followed(tmp_path):
    target = tmp_path / "elsewhere"
    target.write_text("unchanged")
    (tmp_path / "identity.json").symlink_to(target)
    with pytest.raises(identity.IdentityStorageError):
        identity.load_or_create_identity(tmp_path, now=NOW)
    assert target.read_text() == "unchanged"


def test_concurrent_first_creation_uses_one_key(tmp_path):
    with ThreadPoolExecutor(max_workers=4) as pool:
        frames = list(pool.map(lambda _: identity.load_or_create_identity(tmp_path, now=NOW), range(4)))
    assert len({frame.spki_sha256 for frame in frames}) == 1
    assert len({frame.frame_id for frame in frames}) == 1


def test_renewal_keeps_private_key_frame_and_pin(tmp_path):
    first = identity.load_or_create_identity(tmp_path, now=NOW)
    before_boundary = first.refresh_certificate_if_needed(NOW + timedelta(days=306))
    assert before_boundary.cert_pem == first.cert_pem
    renewed = first.refresh_certificate_if_needed(NOW + timedelta(days=307))
    assert renewed.cert_pem != first.cert_pem
    assert (renewed.frame_id, renewed.key_pem, renewed.spki_sha256) == (first.frame_id, first.key_pem, first.spki_sha256)
    assert identity.load_or_create_identity(tmp_path, now=NOW + timedelta(days=308)) == renewed


def test_offline_backwards_clock_keeps_persisted_certificate(tmp_path):
    first = identity.load_or_create_identity(tmp_path, now=NOW)
    before = (tmp_path / "identity.json").read_bytes()
    assert first.refresh_certificate_if_needed(datetime(1970, 1, 1, tzinfo=UTC)) == first
    assert identity.load_or_create_identity(tmp_path, now=NOW - timedelta(days=1)) == first
    assert (tmp_path / "identity.json").read_bytes() == before


def test_first_initialization_requires_plausible_clock(tmp_path):
    with pytest.raises(ValueError):
        identity.load_or_create_identity(tmp_path, now=datetime(1970, 1, 1, tzinfo=UTC))
    assert not (tmp_path / "identity.json").exists()


def test_precommit_failure_preserves_existing_identity(tmp_path, monkeypatch):
    first = identity.load_or_create_identity(tmp_path, now=NOW)
    before = (tmp_path / "identity.json").read_bytes()

    def fail(*args):
        raise OSError("disk failure")

    monkeypatch.setattr(identity.os, "replace", fail)
    with pytest.raises(identity.IdentityStorageError) as error:
        first.refresh_certificate_if_needed(NOW + timedelta(days=350))
    assert not error.value.committed
    assert (tmp_path / "identity.json").read_bytes() == before
    assert not list(tmp_path.glob(".identity-*"))


def test_postcommit_sync_failure_keeps_same_identity(tmp_path, monkeypatch):
    first = identity.load_or_create_identity(tmp_path, now=NOW)

    def fail(*args):
        raise OSError("directory sync failure")

    monkeypatch.setattr(identity, "_sync_directory", fail)
    with pytest.raises(identity.IdentityStorageError) as error:
        first.refresh_certificate_if_needed(NOW + timedelta(days=350))
    assert error.value.committed
    current = identity.load_or_create_identity(tmp_path, now=NOW + timedelta(days=351))
    assert current.spki_sha256 == first.spki_sha256
    assert current.cert_pem != first.cert_pem


def test_tls_files_are_private_and_scratch_is_removed(tmp_path):
    frame = identity.load_or_create_identity(tmp_path, now=NOW)
    context = frame.ssl_context()
    assert context.minimum_version == context.maximum_version == ssl.TLSVersion.TLSv1_3
    assert context.num_tickets == 0 and context.options & ssl.OP_NO_TICKET
    assert not list(tmp_path.glob(".tls-*"))
    cert_path, key_path = frame.materialize_tls_files()
    assert cert_path.read_bytes() == frame.cert_pem
    assert key_path.read_bytes() == frame.key_pem
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in (cert_path, key_path))


def test_memory_bio_handshake_with_explicit_anchor_and_hostname(tmp_path):
    # This client represents a certificate explicitly accepted after QR pinning;
    # it still runs standard chain/date/name checks, never CERT_NONE.
    frame = identity.load_or_create_identity(tmp_path)
    client_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client_context.minimum_version = ssl.TLSVersion.TLSv1_3
    client_context.load_verify_locations(cadata=frame.cert_pem.decode())
    client_in, client_out, server_in, server_out = (ssl.MemoryBIO() for _ in range(4))
    client = client_context.wrap_bio(client_in, client_out, server_hostname=frame.server_name)
    server = frame.ssl_context().wrap_bio(server_in, server_out, server_side=True)
    complete = set()
    for _ in range(20):
        for name, session in (("client", client), ("server", server)):
            try:
                session.do_handshake()
                complete.add(name)
            except ssl.SSLWantReadError:
                pass
        server_in.write(client_out.read())
        client_in.write(server_out.read())
        if len(complete) == 2:
            break
    assert complete == {"client", "server"}
    assert client.version() == "TLSv1.3"
    assert client.getpeercert(binary_form=True) == frame.cert_der
