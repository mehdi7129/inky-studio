# Offline application payload for InkyOS

This producer creates a **candidate**, not a public release or a qualified SD
image. It keeps the existing flat application layout and adds separate Python
assets. Neither the existing online installer/updater nor the HTTP/BLE protocols
change. Do not run `install.sh` or `install-bluetooth.sh` during image assembly:
they configure and start host services.

## Inputs and trust

- A full, locally available Git commit. Source bytes are read from Git objects,
  with replacement refs, lazy fetching and Git environment overrides disabled.
  The working tree, user data, caches and native iPhone builds are excluded.
- The web frontend built in a clean checkout at that exact commit using the
  committed `client/package-lock.json`, Node 22, `npm ci` and `npm run build`.
  `--frontend-source-commit` records the producer's declaration; it is not an
  independent build attestation. Archive bytes are hashed after assembly.
- A directory of already acquired wheels and a provenance inventory. The
  current experimental selection is
  [provenance.json](../packaging/arm64-cp313/provenance.json): 38 registry wheels
  and two locally built native wheels. Every input is matched by filename,
  size and SHA-256; versions, requirements, extras, Python constraints and wheel
  tags are checked without importing wheel code or executing build hooks.
- CPython **3.13.5**, Linux **aarch64**, Debian **Trixie**, glibc **2.41**.
  The two native wheels are target-specific `linux_aarch64` distributions;
  the tag alone is not an ABI/runtime qualification.

The native `RPi.GPIO 0.7.1` and `spidev 3.8` wheels were produced in a disposable
ARM64 Debian VM with network access disabled, from hashed PyPI sources. The
[build report](../packaging/arm64-cp313/native-build-results.json) is referenced
by its byte hash in the inventory. The [InkyOS recipe and evidence](https://github.com/mehdi7129/inkyOS/blob/f27bf47/docs/NATIVE-WHEELS.md)
describe four builds with identical resulting bytes. This demonstrates that
experiment's repeatability, not operation on a physical Raspberry/panel.

Hatchling's editable build additionally needs `editables`. It is now explicit in
`build-system.requires`, so the dependency graph can be closed before invoking
an editable build. The selected wheel versions are frozen in the inventory;
the source project's broader dependency constraints remain intact.

## Producing a candidate

Use Python 3.11+ and Git supporting `--no-lazy-fetch`. Prepare a tooling venv
outside the source payload and install `packaging/requirements-tools.txt`.
The following step has no network, extraction, installation, backend import or
service side effect. The output directory must not already exist.

```sh
python scripts/package_offline.py \
  --source-commit FULL_40_CHARACTER_COMMIT \
  --client-dist client/dist \
  --frontend-source-commit FULL_40_CHARACTER_COMMIT \
  --wheel-dir /path/to/verified-wheels \
  --provenance packaging/arm64-cp313/provenance.json \
  --output build/offline-candidate
```

Outputs:

| File | Contents |
| --- | --- |
| `inky-studio-vVERSION.tar.gz` | Committed source, prebuilt `client/dist`, scripts, shared assets and existing release metadata |
| `inky-studio-python-arm64-cp313.zip` | Exact wheels, `provenance.json`, `licenses/index.json` and collected notices |
| `requirements-arm64-cp313.lock` | Exact runtime + Pi + build requirements, with hashes of delivered wheels |
| `inky-studio-manifest-v1.json` | Version, source SHA, asset hashes/sizes and source references for all three contracts |

The tar contains `server/SOURCE_COMMIT`, **not a new top-level entry**: older
installed updaters reject unknown release-root paths before upgrading their own
code. There is only one `.tar.gz`, so existing asset selection remains valid.
The producer uses fixed archive metadata and stable ordering. Inputs with links,
unsafe archive paths, unsupported wheel tags, conflicting versions, missing
dependencies, unexpected wheels or mismatched hashes are rejected. A failed
assembly leaves no final bundle.

Notices are collected from each wheel, with missing declarations explicitly
reported. This is evidence collection, not a legal license-compatibility ruling.
The manifest's qualification evidence starts empty: no static packaging result
automatically grants software or hardware qualification.

## Separate target installation test

Have the InkyOS input validator and inert archive inspector check the manifest,
its reviewed hash and all assets **before extraction**. The target experiment
runs in a new temporary tree and venv in the ARM64 VM, not an image rootfs and
not the personal Raspberry. Disable external networking for the whole install.

```sh
python3 -m venv APPLICATION/server/.venv
APPLICATION/server/.venv/bin/python -m pip --isolated install \
  --no-index --no-cache-dir --require-hashes --only-binary=:all: \
  --find-links WHEELHOUSE -r requirements-arm64-cp313.lock
APPLICATION/server/.venv/bin/python -m pip --isolated install \
  --no-index --no-cache-dir --no-deps --no-build-isolation \
  -e 'APPLICATION/server[pi]'
APPLICATION/server/.venv/bin/python -m pip check
APPLICATION/server/.venv/bin/python scripts/qualify_offline_runtime.py
```

The smoke script refuses other architectures/Python minors and a network
namespace containing an interface other than loopback. It checks native library
imports, in-memory PNG and crypto operations, the real ASGI health route, the
401 response of a protected route and the bundled frontend. Display
initialization is replaced with an assertion failure; the application lifespan
is never entered. No credentials, database or identity may be created. The
Raspberry-specific `RPi.GPIO` import is intentionally deferred to hardware.
Record install logs, versions, input hashes and the smoke JSON separately.

This VM has build tooling installed: its successful imports would not prove
that every required system library exists on the minimal Pi rootfs. A minimal
target check, real GPIO/SPI/display/Bluetooth tests, and initial adoption remain
separate gates. The existing updater still resolves packages online, and its
rollback restores application files, not a coherent application/venv/helper
snapshot; this producer does not claim an offline updater.

## First boot still needs an application contract

Packaging must not initialize a frame while building an image. InkyOS creates
the host identity; only Inky Studio owns app credentials, TLS identity, QR and
the display. Before promising setup without an existing LAN, implement and test:

1. A durable factory/adopted/recovery state and a local, bounded QR trigger.
   Empty history, unavailable Wi-Fi or missing files must not reopen adoption.
2. Initial clock trust and recovery after long storage. The current TLS identity
   rejects an invalid date before the application's lifespan; bypassing TLS
   validation is not a solution.
3. An explicit Wi-Fi country flow before scan/connection. BLE v1/helper requests
   have strict schemas; new time/country fields need a coordinated protocol.
4. Physical access to the initial app password after QR claim. The present QR
   does not contain this password, and photo authentication remains separate.
5. Repeated Wi-Fi attempts when no previous profile exists, retaining the frame
   identity and adopted owner after errors/cuts.

References: [pip repeatable installs](https://pip.pypa.io/en/stable/topics/repeatable-installs/),
[pip secure installs](https://pip.pypa.io/en/stable/topics/secure-installs/),
[Git object/fetch options](https://git-scm.com/docs/git).
