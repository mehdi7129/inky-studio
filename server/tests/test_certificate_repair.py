"""Write-ahead certificate publication and same-key repair, without a setter."""
from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from inky_web.provisioning import bootstrap_identity as bootstrap
from inky_web.provisioning import identity as normal

NOW = int(datetime(2026, 9, 28, 12, tzinfo=UTC).timestamp())


@pytest.fixture
def prepared(tmp_path):
    return bootstrap.PreparedFactoryIdentity.create(tmp_path / "private", initialization_intent=str(uuid4()))


def initial(prepared, epoch=NOW):
    operation_id = str(uuid4())
    clock = bootstrap.ClockResult(operation_id, epoch)
    return operation_id, clock, prepared.publish_initial(operation_id=operation_id, clock_result=clock)


def read_bundle(prepared):
    return json.loads((prepared._directory / bootstrap.BUNDLE_NAME).read_bytes())


def test_initial_publication_has_same_key_uuid_and_replay_exact_bytes(prepared, monkeypatch):
    operation_id, clock, result = initial(prepared)
    current = prepared.load_current_identity()
    assert current.frame_id == prepared.frame_id
    assert current.spki_sha256 == prepared.binding.spki_sha256
    assert current.key_pem == prepared.key_pem
    assert current.cert_der == result.certificate_der
    assert current.issued_at == datetime.fromtimestamp(NOW, UTC)
    normal_bytes = (prepared._directory / "identity.json").read_bytes()
    journal_bytes = (prepared._directory / bootstrap.BUNDLE_NAME).read_bytes()

    def forbidden_generation(*_args):
        raise AssertionError("Replay regenerated a certificate")

    monkeypatch.setattr(normal, "_certificate", forbidden_generation)
    reopened = bootstrap.PreparedFactoryIdentity.reopen(prepared._directory, expected_binding=prepared.binding)
    assert reopened.publish_initial(operation_id=operation_id, clock_result=clock) == result
    assert (prepared._directory / "identity.json").read_bytes() == normal_bytes
    assert (prepared._directory / bootstrap.BUNDLE_NAME).read_bytes() == journal_bytes


@pytest.mark.parametrize("original_epoch", [int(datetime(2026, 1, 1, tzinfo=UTC).timestamp()),
                                             int(datetime(2098, 1, 1, tzinfo=UTC).timestamp())])
def test_expired_or_bad_future_leaf_can_be_repaired_only_explicitly(prepared, original_epoch):
    _, _, first = initial(prepared, original_epoch)
    old = prepared.load_current_identity()
    if original_epoch > NOW:
        # Existing automatic renewal still preserves a leaf issued in the future.
        assert old.refresh_certificate_if_needed(datetime.fromtimestamp(NOW, UTC)).cert_der == old.cert_der
        repair_epoch = NOW
    else:
        repair_epoch = int((old.issued_at + timedelta(days=500)).timestamp())
    operation_id = str(uuid4())
    result = prepared.repair_existing(operation_id=operation_id,
                                     clock_result=bootstrap.ClockResult(operation_id, repair_epoch),
                                     expected_old_certificate_sha256=first.certificate_sha256)
    current = prepared.load_current_identity()
    assert current.key_pem == old.key_pem == prepared.key_pem
    assert current.frame_id == old.frame_id
    assert current.spki_sha256 == old.spki_sha256
    assert current.cert_der == result.certificate_der != old.cert_der
    assert current.issued_at == datetime.fromtimestamp(repair_epoch, UTC)


def test_completed_replay_never_restores_old_leaf_after_later_normal_renewal(prepared):
    operation_id, clock, first = initial(prepared)
    original = prepared.load_current_identity()
    renewed = original.refresh_certificate_if_needed(original.issued_at + timedelta(days=400))
    newer_bytes = (prepared._directory / "identity.json").read_bytes()
    assert renewed.cert_der != first.certificate_der
    assert prepared.publish_initial(operation_id=operation_id, clock_result=clock) == first
    assert (prepared._directory / "identity.json").read_bytes() == newer_bytes
    assert prepared.load_current_identity().cert_der == renewed.cert_der


def test_completed_repair_replay_is_historical_after_another_repair(prepared):
    _, _, first = initial(prepared)
    repair_id = str(uuid4())
    clock = bootstrap.ClockResult(repair_id, NOW + 100)
    result = prepared.repair_existing(operation_id=repair_id, clock_result=clock,
                                       expected_old_certificate_sha256=first.certificate_sha256)
    next_id = str(uuid4())
    next_result = prepared.repair_existing(operation_id=next_id, clock_result=bootstrap.ClockResult(next_id, NOW + 200),
                                            expected_old_certificate_sha256=result.certificate_sha256)
    before = (prepared._directory / "identity.json").read_bytes()
    assert prepared.repair_existing(operation_id=repair_id, clock_result=clock,
                                    expected_old_certificate_sha256=first.certificate_sha256) == result
    assert (prepared._directory / "identity.json").read_bytes() == before
    assert bootstrap.certificate_sha256(prepared.load_current_identity()) == next_result.certificate_sha256


def test_same_operation_id_with_different_parameters_conflicts(prepared):
    operation_id, _, first = initial(prepared)
    before = (prepared._directory / "identity.json").read_bytes()
    with pytest.raises(bootstrap.CertificateConflict):
        prepared.publish_initial(operation_id=operation_id, clock_result=bootstrap.ClockResult(operation_id, NOW + 1))
    with pytest.raises(bootstrap.CertificateConflict):
        prepared.repair_existing(operation_id=operation_id, clock_result=bootstrap.ClockResult(operation_id, NOW),
                                 expected_old_certificate_sha256=first.certificate_sha256)
    assert (prepared._directory / "identity.json").read_bytes() == before


@pytest.mark.parametrize("epoch", [True, 1.5, "1800000000", -1, 0, bootstrap.MIN_CERTIFICATE_EPOCH - 1,
                                   bootstrap.MAX_CERTIFICATE_EPOCH + 1, 10**100])
def test_invalid_clock_assertions_never_publish(prepared, epoch):
    with pytest.raises(ValueError):
        bootstrap.ClockResult(str(uuid4()), epoch)
    assert not (prepared._directory / "identity.json").exists()
    assert read_bundle(prepared)["operations"] == []


def test_clock_assertion_cannot_be_mapping_or_rebound_to_operation(prepared):
    operation_id = str(uuid4())
    with pytest.raises(ValueError):
        prepared.publish_initial(operation_id=operation_id, clock_result={"operation_id": operation_id, "epoch_seconds": NOW})
    with pytest.raises(ValueError):
        prepared.publish_initial(operation_id=operation_id, clock_result=bootstrap.ClockResult(str(uuid4()), NOW))
    assert read_bundle(prepared)["operations"] == []


def test_two_simultaneous_initial_operations_cannot_publish_different_leaves(prepared):
    def attempt(_):
        operation_id = str(uuid4())
        try:
            return prepared.publish_initial(operation_id=operation_id, clock_result=bootstrap.ClockResult(operation_id, NOW))
        except bootstrap.CertificateConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert bootstrap.certificate_sha256(prepared.load_current_identity()) == winners[0].certificate_sha256
    assert len(read_bundle(prepared)["operations"]) == 1


@pytest.mark.parametrize("phase", ["journaled", "published"])
@pytest.mark.parametrize("kind", ["initial", "repair"])
def test_process_exit_retries_durable_candidate_without_regeneration(prepared, phase, kind, monkeypatch):
    old_digest = None
    if kind == "repair":
        _, _, previous = initial(prepared)
        old_digest = previous.certificate_sha256
    operation_id = str(uuid4())
    script = """
from pathlib import Path
import os, sys
from inky_web.provisioning.bootstrap_identity import PreparedFactoryIdentity, ClockResult
directory, phase, kind, operation, epoch, old = sys.argv[1:]
prepared = PreparedFactoryIdentity.reopen(Path(directory))
original = PreparedFactoryIdentity._publish_candidate
def crash(self, record):
    if phase == 'published':
        original(self, record)
    os._exit(73)
PreparedFactoryIdentity._publish_candidate = crash
clock = ClockResult(operation, int(epoch))
if kind == 'initial':
    prepared.publish_initial(operation_id=operation, clock_result=clock)
else:
    prepared.repair_existing(operation_id=operation, clock_result=clock, expected_old_certificate_sha256=old)
"""
    process = subprocess.run([sys.executable, "-c", script, str(prepared._directory), phase, kind,
                              operation_id, str(NOW + 100), old_digest or ""], capture_output=True, text=True, timeout=10)
    assert process.returncode == 73, process.stderr
    journal = read_bundle(prepared)
    pending = journal["operations"][-1]
    assert pending["state"] == "pending"
    candidate = pending["candidate_cert_pem"]

    def forbidden_generation(*_args):
        raise AssertionError("Crash retry generated a different certificate")

    monkeypatch.setattr(normal, "_certificate", forbidden_generation)
    reopened = bootstrap.PreparedFactoryIdentity.reopen(prepared._directory)
    arguments = {"operation_id": operation_id, "clock_result": bootstrap.ClockResult(operation_id, NOW + 100)}
    if kind == "initial":
        result = reopened.publish_initial(**arguments)
    else:
        result = reopened.repair_existing(**arguments, expected_old_certificate_sha256=old_digest)
    assert reopened.load_current_identity().cert_pem.decode() == candidate
    assert result.certificate_sha256 == pending["candidate_sha256"]
    assert read_bundle(reopened)["operations"][-1]["state"] == "completed"


def test_pending_repair_does_not_overwrite_conflicting_normal_renewal(prepared, monkeypatch):
    _, _, first = initial(prepared)
    old = prepared.load_current_identity()
    operation_id = str(uuid4())
    clock = bootstrap.ClockResult(operation_id, NOW + 10)
    original = bootstrap.PreparedFactoryIdentity._publish_candidate

    def stop_before_publish(_self, _operation):
        raise OSError("injected power interruption")

    monkeypatch.setattr(bootstrap.PreparedFactoryIdentity, "_publish_candidate", stop_before_publish)
    with pytest.raises(bootstrap.BootstrapIdentityRecoveryRequired):
        prepared.repair_existing(operation_id=operation_id, clock_result=clock,
                                 expected_old_certificate_sha256=first.certificate_sha256)
    monkeypatch.setattr(bootstrap.PreparedFactoryIdentity, "_publish_candidate", original)
    renewed = old.refresh_certificate_if_needed(old.issued_at + timedelta(days=400))
    before = (prepared._directory / "identity.json").read_bytes()
    with pytest.raises(bootstrap.CertificateConflict):
        prepared.repair_existing(operation_id=operation_id, clock_result=clock,
                                 expected_old_certificate_sha256=first.certificate_sha256)
    assert (prepared._directory / "identity.json").read_bytes() == before
    assert prepared.load_current_identity().cert_der == renewed.cert_der
    assert read_bundle(prepared)["operations"][-1]["state"] == "pending"


@pytest.mark.parametrize("damage", ["missing-bundle", "missing-operations", "cleared-operations", "bad-candidate", "bad-intent"])
def test_lost_or_corrupt_operation_history_is_not_recreated(prepared, damage):
    operation_id, clock, _ = initial(prepared)
    path = prepared._directory / bootstrap.BUNDLE_NAME
    record = read_bundle(prepared)
    normal_bytes = (prepared._directory / "identity.json").read_bytes()
    if damage == "missing-bundle":
        path.unlink()
    else:
        if damage == "missing-operations":
            del record["operations"]
        elif damage == "cleared-operations":
            record["operations"] = []
        elif damage == "bad-candidate":
            record["operations"][0]["candidate_sha256"] = "0" * 64
        else:
            record["operations"][0]["intent"] = "0" * 64
        path.write_text(json.dumps(record))
    before = path.read_bytes() if path.exists() else None
    with pytest.raises(bootstrap.BootstrapIdentityRecoveryRequired):
        prepared.publish_initial(operation_id=operation_id, clock_result=clock)
    assert (path.read_bytes() if path.exists() else None) == before
    assert (prepared._directory / "identity.json").read_bytes() == normal_bytes
    if damage == "missing-bundle":
        with pytest.raises(bootstrap.CertificateConflict):
            bootstrap.PreparedFactoryIdentity.create(prepared._directory, initialization_intent=str(uuid4()))


def test_journal_capacity_refuses_without_pruning_receipts(prepared, monkeypatch):
    operation_id, clock, first = initial(prepared)
    monkeypatch.setattr(bootstrap, "MAX_OPERATIONS", 1)
    other = str(uuid4())
    before = (prepared._directory / bootstrap.BUNDLE_NAME).read_bytes()
    with pytest.raises(bootstrap.CertificateJournalFull):
        prepared.repair_existing(operation_id=other, clock_result=bootstrap.ClockResult(other, NOW + 1),
                                 expected_old_certificate_sha256=first.certificate_sha256)
    assert (prepared._directory / bootstrap.BUNDLE_NAME).read_bytes() == before
    assert prepared.publish_initial(operation_id=operation_id, clock_result=clock) == first


def test_changed_normal_identity_key_cannot_be_repaired(prepared):
    _, _, first = initial(prepared)
    different = normal._generate(prepared._directory, datetime.fromtimestamp(NOW, UTC))
    normal._persist(different, prepared._directory / "identity.json")
    before = (prepared._directory / "identity.json").read_bytes()
    operation_id = str(uuid4())
    with pytest.raises(bootstrap.BootstrapIdentityRecoveryRequired):
        prepared.repair_existing(operation_id=operation_id, clock_result=bootstrap.ClockResult(operation_id, NOW + 1),
                                 expected_old_certificate_sha256=first.certificate_sha256)
    assert (prepared._directory / "identity.json").read_bytes() == before


def test_missing_current_identity_is_not_restored_by_completed_replay(prepared):
    operation_id, clock, first = initial(prepared)
    path = prepared._directory / "identity.json"
    path.unlink()
    assert prepared.publish_initial(operation_id=operation_id, clock_result=clock) == first
    assert not path.exists()
    with pytest.raises(bootstrap.BootstrapIdentityRecoveryRequired):
        prepared.load_current_identity()


@pytest.mark.parametrize("target", [bootstrap.BUNDLE_NAME, "identity.json"])
def test_deep_json_is_normalized_to_recovery_without_repair(prepared, target):
    initial(prepared)
    path = prepared._directory / target
    deep = b'{"a":' * 1800 + b"0" + b"}" * 1800
    assert len(deep) < normal.MAX_IDENTITY_BYTES
    path.write_bytes(deep)
    with pytest.raises(bootstrap.BootstrapIdentityRecoveryRequired):
        prepared.verify_current_or_unpublished()
    with pytest.raises(bootstrap.BootstrapIdentityRecoveryRequired):
        prepared.load_current_identity()
    assert path.read_bytes() == deep


def test_verify_current_distinguishes_unpublished_from_lost_completed_identity(prepared):
    assert prepared.verify_current_or_unpublished() is None
    _, _, first = initial(prepared)
    current = prepared.verify_current_or_unpublished()
    assert current is not None and current.cert_der == first.certificate_der
    (prepared._directory / "identity.json").unlink()
    with pytest.raises(bootstrap.BootstrapIdentityRecoveryRequired):
        prepared.verify_current_or_unpublished()
