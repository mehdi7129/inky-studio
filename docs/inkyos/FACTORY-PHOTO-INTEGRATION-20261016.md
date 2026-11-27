# Factory / PHOTO backend integration candidate — 16 October 2026

Local source merge only. No push, release, wheel, native dependency closure,
image, Pi, SD, VM, installed service or physical display operation belongs to
this lot. The app/iOS work is separate; no iOS file changes are included here.

## Exact sources

- Factory base: `eb117903cb647a14e9722d7387a41058ea8807b3`, clean source worktree
  `/Users/mehdiguiard/Library/Caches/inky-studio-public-metadata`.
- PHOTO/display/invitations: `9ec89d72696339cd305255ae5619606fb94aa0c6`, clean
  source worktree `/Users/mehdiguiard/Library/Caches/inky-studio-photo-access-20261016`.
  Its immediate display base is `73f65627baf38e82f9d102fb727834f275205642`.
- Three-way common ancestor: `c31b13afdc957425571810c46230eaaf52fa5d14`.
- Destination worktree:
  `/Users/mehdiguiard/Library/Caches/inky-studio-factory-photo-integration-20261016`.
  Branch: `codex/factory-photo-integration-20261016`.

The PHOTO objects were fetched from their local source path, without remote
network access. Existing reports under `build/photo-access-20261016` describe
the historical PHOTO source candidate; their counts are not new integration
results and are not added to the results below.

## Resolution and preserved boundaries

Three content conflicts were resolved in `main.py`, `inky/display.py` and
`tests/test_display_busy.py`.

`main.py` retains factory selection under the main writer guard before legacy
database initialization, credential creation, PHOTO store construction,
identity materialization, hardware, scheduler and listeners. Unexpected factory
coordinator returns still refuse. Entry-point tests now also explicitly forbid
constructing `PhotoAccessStore` during factory selection.

The factory phase A, identity, ownership, writer/admission and maintenance
modules are retained from the factory base. The packaging/dependency metadata,
scripts, shared metadata and iOS files remain unchanged from that base.
In particular `server/pyproject.toml` still pins **inky==2.5.0**. No dependency
upgrade, downgrade, regenerated package or changed source provenance is implied.

The display merge ports the recoverable pending-confirmation correction to the
strict AC073 2.5.0 observation contract. Real timeout, malformed/unrecognized
observations and interrupted refresh remain failures; no automatic retry is
introduced. EL133UF1 still refuses an unproved refresh before POF. Other driver
families retain their 2.5.0 validation and do not gain the AC073 barrier/retry
protocol. Test fixtures were adapted to the pinned driver API; the production
guards were not relaxed to accommodate old 2.3.0 fixtures.

PHOTO owner/media credentials remain separate from Bluetooth ownership.
Owner enrollment requires a live password-login cookie over HTTPS and an
already approved frame identity. Invited access is always media. Device
cookies cannot enroll/promote owners; HTTP and WS media capabilities remain
closed lists. The store remains independently persisted under `photo-access`.

Both production Uvicorn listeners retain `proxy_headers=False`. PHOTO requires
actual HTTPS/WSS rather than forwarded headers. Invitation creation still
requires explicit `INKY_STUDIO_PHOTO_ACCESS_URL`; no address, Host, SAN or BLE
owner is used to invent a canonical sharing origin.

## Validation

Existing environment only:
`/Users/mehdiguiard/Library/Caches/inky-display-250-validation-venv` (Python
3.13.15, Ruff 0.17.0). No installation or dependency changes. Each pytest batch
runs from this worktree's `server` using `python -m pytest -q -p no:cacheprovider`.
Runtime data is confined to pytest temporary directories. Real listener tests
use ephemeral loopback sockets and inert hardware/BlueZ boundaries.

Results are recorded per batch below; reruns are not added together.

- Factory state/credentials/bootstrap: **289 passed**, one existing
  Starlette/httpx deprecation warning, 8.74 s. Files: `test_factory_runtime.py`,
  `test_factory_credentials.py`, `test_provisioning_factory.py`,
  `test_provisioning_ownership.py`, `test_first_boot.py`,
  `test_bootstrap_identity.py`, `test_bootstrap_tls.py`.
- Factory entry points/admission/lifetime: **174 passed**, one existing
  Starlette/httpx warning, 41.83 s. Files: `test_factory_runtime_entrypoints.py`,
  `test_factory_phase_a.py`, `test_factory_admission.py`, `test_factory_writer.py`,
  `test_factory_session.py`, `test_factory_maintenance.py`.
- PHOTO/auth/WS/production listeners: **133 passed**, one existing
  Starlette/httpx warning, 38.38 s. Files: `test_photo_access.py`, `test_auth.py`,
  `test_auth_storage.py`, `test_websocket.py`, `test_provisioning_integration.py`,
  `test_provisioning_listeners.py`. This includes actual loopback HTTP refusal
  with forged forwarded headers and actual TLS device enrollment/session.
- Welcome/scheduler/queue: **87 passed**, two deprecation warnings, 2.74 s.
  Files: `test_welcome.py`, `test_scheduler.py`, `test_api_queue.py`. The second
  warning concerns Pillow's existing `Image.getdata` test helper.
- Final impacted display batch after restricting the barrier to AC073:
  **123 passed**, one existing Starlette/httpx warning, 4.34 s. Files/selections:
  `test_display_busy.py`, `test_display_confirmation.py`, and
  `test_display_hardware.py::test_authenticated_reads_survive_sticky_display_fault_without_admitting_writes`.
  Coverage includes all family BUSY contracts, AC073 durable pending/manual
  retry, unknown sequences, queued requests and non-AC073 barrier absence.
- A preceding display batch (`test_display_busy.py`,
  `test_display_confirmation.py`, `test_display_hardware.py`, `test_display.py`,
  `test_api_display.py`) passed **181 tests** before the final restriction.
  It overlaps the final impacted batch and is not added to it. An earlier
  missing `family` field in a test stub was corrected rather than weakening
  production diagnostics.
- `ruff check .` from `server`: **PASS** across backend/tests.
- `git diff --check`: **PASS**. Dependency/package metadata, scripts,
  provisioning modules, shared metadata and iOS are unchanged from the factory
  source. No full backend suite was run.

A separate read-only source review found no concrete integration regression
in the factory selection, PHOTO authority split, media capabilities or
TLS/origin boundaries. It ran no independent tests and does not qualify the
installed OS graph or physical hardware.

## Explicitly incomplete

- The installed factory initializer still prepares durable state then stops
  closed with `factory_runtime_pending`. The separate, injected phase A
  lifecycle is not a new installed grant or a legacy-startup bypass.
- There is **no first factory PHOTO handoff**. Claiming factory/BLE ownership
  neither enrolls a PHOTO owner nor opens the normal PHOTO service. A reviewed
  transition with explicit authority, durable credentials and trusted HTTPS
  identity is still needed. This merge does not fake it with an owner grant,
  password migration or factory-to-legacy fallback.
- Time/timezone synchronization, country configuration and the app's
  `SystemSetup` feature are not implemented by this lot.
- The existing physical TEST PHOTO result at `73f65627` with Inky 2.3.0 remains
  evidence for that installed payload only. It does not qualify the present
  Inky 2.5.0 source, a new native closure, a new image or any panel refresh.
- No iPhone QR/Face ID/Keychain/invitation flow, Pi reboot, offline first boot,
  native dependency closure or installed service transition was qualified here.
- Phase B storage/migration stays outside this merge and remains inactive.
