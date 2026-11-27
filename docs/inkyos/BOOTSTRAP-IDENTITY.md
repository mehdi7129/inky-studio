# Prepared identity and certificate publication prototype

Status: internal opt-in component, inactive in the normal application. No clock
setter, BLE registration, OS receipt validation or legacy migration is enabled.

`server/inky_web/provisioning/bootstrap_identity.py` prepares a per-frame P-256
key, UUID and historical bootstrap certificate without reading the RTC. Its
private `bootstrap-identity.json` bundle also contains the certificate-operation
journal. The normal `identity.json` does not exist until an explicitly authorized
publication call. The existing normal loader, parser and automatic renewal are
unchanged and reject the historical bootstrap certificate.

## Internal Python API

```python
prepared = PreparedFactoryIdentity.create(
    private_dir, initialization_intent=canonical_operation_uuid,
)
prepared = PreparedFactoryIdentity.reopen(
    private_dir,
    expected_intent=canonical_operation_uuid,   # optional during OS inspection
    expected_binding=expected_factory_identity, # optional until independently bound
)
binding = prepared.binding  # FactoryIdentity(frame_id, spki_sha256)
context = prepared.bootstrap_tls_context()  # dedicated BootstrapTLSContext

clock = ClockResult(operation_id=canonical_operation_uuid, epoch_seconds=epoch)
result = prepared.publish_initial(operation_id=clock.operation_id, clock_result=clock)
current = prepared.load_current_identity()

result = prepared.repair_existing(
    operation_id=next_clock.operation_id,
    clock_result=next_clock,
    expected_old_certificate_sha256=certificate_sha256(current),
)
```

`ClockResult` is a typed **local assertion** from a future trusted coordinator.
It does not verify a privileged receipt, authorize an operation or independently
prove UTC. No method calls or reapplies a clock setter. The allowed integer epoch
range is a certificate-serialization bound (2026-01-01 through 9998-01-01), not
the future clock-change policy; booleans, floats and strings are rejected.

`verify_current_or_unpublished()` returns the strictly loaded normal `Identity`
or `None` when initial publication has not completed. A missing normal identity
after completed publication or during a subsequent repair requires recovery.
This check does not publish/renew anything or establish valid current time,
network readiness or ownership.

## Persistence and replay

- Creation is exclusive and refuses an existing prepared bundle or normal
  identity. Reopen never creates a missing bundle. Legacy installations without
  one need a separately reviewed migration, not implicit enrollment here.
- The parent directory is private (0700), files and lock files are 0600. Reads
  and lock opens use `O_NOFOLLOW | O_NONBLOCK` and reject non-regular files.
  Strict JSON rejects duplicate keys, invalid constants, excessive size and
  excessive recursion. Keys and certificates are redacted from object reprs.
- A complete staged file is fsynced before atomic publication; initial creation
  uses a no-replace hard link. Directory fsync follows publication. Refusals may
  restrict permissions; they never regenerate identity or reset history.
- Lock order is `.bootstrap-identity.lock`, then `.identity.lock`. The latter
  serializes publication with existing normal renewal. The fixed historical
  issuance is 2000-01-01 00:05 UTC: validity begins at midnight and follows the
  same 396-day issuance lifetime and five-minute skew as the normal builder.
- Before normal publication, a pending operation records exact candidate PEM,
  operation UUID, intent digest, kind, previous DER certificate digest and clock
  assertion. The candidate reuses the exact original private-key bytes and UUID.
  A retry reads these bytes; it does not generate another certificate.
- After interruption, current identity must match the expected old certificate
  or the stored candidate. Unexpected identity or a conflicting renewal is
  preserved and rejected. A previously published candidate is recognized and
  only its journal result is finalized.
- Completed replays return `CertificateOperationResult`, a **historical** result.
  They never restore an older certificate over a subsequent renewal, nor
  recreate a deleted normal identity. Load the current identity separately.
- The integrated journal permits at most 64 operations and a 1 MiB bundle.
  Exhaustion requires explicit maintenance; no receipt is silently pruned.

The bundle is not independent initialization authority. The future OS receipt
must forbid calling `create` again after prior initialization, even if all app
files are deleted before normal publication. This software-only prototype does
not prevent restoring an entire older storage image. Prepared identities must
not be included in an OS image or produced during image assembly.

## Validation scope

Synthetic tests cover preparation with an unavailable RTC, exclusive concurrent
creation, strict reopen and identity binding, corrupt/P-384/mismatched bundles,
symlinks/FIFOs/oversized/deep JSON, exact publication retries, expired/future leaf
repair, journal capacity and replay after later normal renewal. Four subprocess
crash cases exit after journaling or after publication, for initial issuance and
repair. Recovery reuses the durable candidate without generating a certificate.

This validates local files and cryptographic identity invariants. It does not
qualify power-loss behavior of a particular SD card/filesystem, physical QR,
iPhone BLE, privileged time mutation, complete first boot or an InkyOS release.
