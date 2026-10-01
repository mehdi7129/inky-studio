"""Prepared keys exist before UTC without becoming normal identity or authority."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from inky_web.provisioning import bootstrap_identity as bootstrap
from inky_web.provisioning import identity as normal


def prepare(tmp_path):
    return bootstrap.PreparedFactoryIdentity.create(tmp_path / "private", initialization_intent=str(uuid4()))


def bundle(prepared):
    return prepared._directory / bootstrap.PREPARED_IDENTITY_FILENAME


def test_prepare_without_rtc_then_reopen_pinned_and_redacted(tmp_path, monkeypatch):
    def forbidden_clock(_value=None):
        raise AssertionError("Preparation read the wall clock")

    monkeypatch.setattr(normal, "_now", forbidden_clock)
    prepared = prepare(tmp_path)
    assert not (prepared._directory / "identity.json").exists()
    assert "PRIVATE KEY" not in repr(prepared)
    assert stat.S_IMODE(prepared._directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(bundle(prepared).stat().st_mode) == 0o600
    certificate = x509.load_der_x509_certificate(prepared.bootstrap_certificate_der)
    assert certificate.not_valid_before_utc == datetime(2000, 1, 1, tzinfo=UTC)
    assert certificate.not_valid_after_utc == bootstrap.BOOTSTRAP_ISSUANCE + normal.CERTIFICATE_LIFETIME
    reopened = bootstrap.PreparedFactoryIdentity.reopen(
        prepared._directory, expected_intent=prepared.initialization_intent, expected_binding=prepared.binding,
    )
    assert reopened == prepared
    assert bootstrap.PreparedFactoryIdentity.reopen(prepared._directory) == prepared
    # The normal parser/loader policy remains strict, including at RTC 1970.
    with pytest.raises(normal.IdentityFormatError):
        normal._parse(normal_record(prepared), prepared._directory)
    monkeypatch.undo()
    with pytest.raises(ValueError):
        normal.load_or_create_identity(tmp_path / "legacy", now=datetime(1970, 1, 1, tzinfo=UTC))


def normal_record(prepared):
    return {"v": 1, "id": prepared.frame_id, "key_pem": prepared.key_pem.decode(),
            "cert_pem": prepared.bootstrap_cert_pem.decode()}


def test_bootstrap_context_is_separate_and_loads_historical_certificate(tmp_path):
    from inky_web.provisioning.bootstrap_tls import BootstrapTLSContext

    prepared = prepare(tmp_path)
    context = prepared.bootstrap_tls_context()
    assert type(context) is BootstrapTLSContext
    assert not isinstance(prepared, normal.Identity)
    assert not (prepared._directory / "identity.json").exists()
    assert not list(prepared._directory.glob(".tls-*"))


def test_create_is_exclusive_and_never_enrolls_legacy_identity(tmp_path):
    prepared = prepare(tmp_path)
    before = bundle(prepared).read_bytes()
    with pytest.raises(bootstrap.CertificateConflict):
        bootstrap.PreparedFactoryIdentity.create(prepared._directory, initialization_intent=str(uuid4()))
    assert bundle(prepared).read_bytes() == before
    directory = tmp_path / "legacy"
    identity = normal.load_or_create_identity(directory, now=datetime(2026, 9, 28, tzinfo=UTC))
    old = (directory / "identity.json").read_bytes()
    with pytest.raises(bootstrap.CertificateConflict):
        bootstrap.PreparedFactoryIdentity.create(directory, initialization_intent=str(uuid4()))
    assert (directory / "identity.json").read_bytes() == old
    assert identity.key_pem and not (directory / bootstrap.BUNDLE_NAME).exists()


def test_two_creators_publish_exactly_one_identity(tmp_path):
    directory = tmp_path / "private"

    def attempt(_):
        try:
            return bootstrap.PreparedFactoryIdentity.create(directory, initialization_intent=str(uuid4()))
        except bootstrap.CertificateConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    successful = [value for value in results if value is not None]
    assert len(successful) == 1
    assert bootstrap.PreparedFactoryIdentity.reopen(directory) == successful[0]


def test_missing_bundle_or_directory_never_recreated(tmp_path):
    directory = tmp_path / "absent"
    with pytest.raises(bootstrap.BootstrapIdentityRecoveryRequired):
        bootstrap.PreparedFactoryIdentity.reopen(directory)
    assert not directory.exists()
    prepared = prepare(tmp_path)
    bundle(prepared).unlink()
    with pytest.raises(bootstrap.BootstrapIdentityRecoveryRequired):
        bootstrap.PreparedFactoryIdentity.reopen(prepared._directory)
    assert not bundle(prepared).exists()


@pytest.mark.parametrize("expected", ["intent", "uuid", "pin"])
def test_reopen_rejects_mismatched_external_binding_without_overwrite(tmp_path, expected):
    prepared = prepare(tmp_path)
    intent, binding = prepared.initialization_intent, prepared.binding
    if expected == "intent":
        intent = str(uuid4())
    elif expected == "uuid":
        binding = replace(binding, frame_id=str(uuid4()))
    else:
        binding = replace(binding, spki_sha256="f" * 64)
    before = bundle(prepared).read_bytes()
    with pytest.raises(bootstrap.BootstrapIdentityRecoveryRequired):
        bootstrap.PreparedFactoryIdentity.reopen(prepared._directory, expected_intent=intent, expected_binding=binding)
    assert bundle(prepared).read_bytes() == before


@pytest.mark.parametrize("mutation", ["schema", "intent", "uuid", "key", "certificate", "p384", "journal", "key-type"])
def test_corrupt_bundle_requires_recovery_and_preserves_evidence(tmp_path, mutation):
    prepared = prepare(tmp_path)
    record = json.loads(bundle(prepared).read_bytes())
    if mutation == "schema":
        record["v"] = True
    elif mutation == "intent":
        record["initialization_intent"] = "invalid"
    elif mutation == "uuid":
        record["frame_id"] = str(uuid4())
    elif mutation == "journal":
        del record["operations"]
    elif mutation == "key-type":
        record["key_pem"] = None
    elif mutation == "certificate":
        record["bootstrap_cert_pem"] = record["bootstrap_cert_pem"].replace("A", "B", 1)
    else:
        curve = ec.SECP384R1() if mutation == "p384" else ec.SECP256R1()
        key = ec.generate_private_key(curve)
        record["key_pem"] = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()).decode()
        if mutation == "p384":
            record["bootstrap_cert_pem"] = normal._certificate(key, prepared.frame_id, bootstrap.BOOTSTRAP_ISSUANCE).decode()
    bundle(prepared).write_text(json.dumps(record))
    before = bundle(prepared).read_bytes()
    with pytest.raises(bootstrap.BootstrapIdentityRecoveryRequired):
        bootstrap.PreparedFactoryIdentity.reopen(prepared._directory)
    assert bundle(prepared).read_bytes() == before


@pytest.mark.parametrize("contents", [b"", b"{", b'{"v":1,"v":1}', b"x" * (bootstrap.MAX_BUNDLE_BYTES + 1)])
def test_invalid_or_oversized_json_is_preserved(tmp_path, contents):
    prepared = prepare(tmp_path)
    bundle(prepared).write_bytes(contents)
    with pytest.raises(bootstrap.BootstrapIdentityRecoveryRequired):
        bootstrap.PreparedFactoryIdentity.reopen(prepared._directory)
    assert bundle(prepared).read_bytes() == contents


def test_symlink_bundle_and_directory_are_refused(tmp_path):
    prepared = prepare(tmp_path)
    target = tmp_path / "saved.json"
    bundle(prepared).rename(target)
    bundle(prepared).symlink_to(target)
    before = target.read_bytes()
    with pytest.raises(bootstrap.BootstrapIdentityRecoveryRequired):
        bootstrap.PreparedFactoryIdentity.reopen(prepared._directory)
    assert target.read_bytes() == before
    alias = tmp_path / "alias"
    alias.symlink_to(prepared._directory, target_is_directory=True)
    with pytest.raises(bootstrap.BootstrapIdentityRecoveryRequired):
        bootstrap.PreparedFactoryIdentity.reopen(alias)


@pytest.mark.parametrize("target", [bootstrap.BUNDLE_NAME, ".bootstrap-identity.lock", ".identity.lock"])
def test_fifo_is_rejected_without_blocking(tmp_path, target):
    prepared = prepare(tmp_path)
    path = prepared._directory / target
    if path.exists():
        path.unlink()
    os.mkfifo(path, 0o600)
    script = """
from pathlib import Path
import sys
from inky_web.provisioning.bootstrap_identity import PreparedFactoryIdentity, BootstrapIdentityRecoveryRequired
try:
    prepared = PreparedFactoryIdentity.reopen(Path(sys.argv[1]))
    prepared.load_current_identity()
except BootstrapIdentityRecoveryRequired:
    print('recovery')
else:
    raise AssertionError('FIFO accepted')
"""
    result = subprocess.run([sys.executable, "-c", script, str(prepared._directory)],
                            check=True, capture_output=True, text=True, timeout=5)
    assert result.stdout.strip() == "recovery"
    assert stat.S_ISFIFO(path.stat().st_mode)
