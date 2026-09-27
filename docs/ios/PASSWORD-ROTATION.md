# Password rotation: implementation and deployment gate

This change concerns the Inky Studio application password only. It does not change
the Raspberry Pi's Linux/SSH password, Wi-Fi credentials, or sudo configuration.
Bluetooth provisioning, recovery codes, device ownership and TLS provisioning are
future work. Nothing in this document has been deployed to the frame.

## HTTP contract

`GET /api/auth/status` and login/logout responses now include
`password_change_supported`. It is `true` when application authentication is
enabled, including an unauthenticated status probe, and `false` when
`INKY_STUDIO_DISABLE_AUTH=1`. Existing clients can ignore the extra field; clients
talking to older servers must treat an absent field as unsupported.

`POST /api/auth/password` requires the current session cookie and JSON:

```json
{"current_password":"current secret","new_password":"replacement secret"}
```

The current password accepts 1–64 Unicode code points to preserve legacy login
compatibility. The new password accepts 8–64; neither is trimmed or normalized.
Invalid Unicode is rejected. Successful rotation returns HTTP 200:

```json
{"authenticated":true,"auth_required":true,"password_change_supported":true}
```

The response sets a new `inky_session` cookie. All previous sessions, including the
request's old cookie and other phones, are revoked. Connected WebSockets wake and
close with code 1008 even when no frame events or client messages are occurring.
The initiating phone must persist its replacement secret after success and use
the new cookie. It must not replay the mutation automatically after a timeout:
the operation may have committed even if its HTTP response was lost.

| Status | Meaning |
| --- | --- |
| 401 | Missing, expired or revoked session; authenticate again. |
| 403 | Incorrect current password, with the session preserved; or a rejected browser Origin. |
| 409 | Authentication is disabled; changing a password is unsupported. |
| 422 | Invalid fields/length/Unicode; validation responses omit supplied secrets. |
| 429 | Five rotation attempts per client IP in 60 seconds have been used. Login has its own limit. |
| 503 | Credential storage failure; read the distinction below. |

Browser requests with an Origin header must match the request's origin exactly.
Native clients may omit Origin. Cookies are HttpOnly, SameSite=Strict and Secure
when the request scheme is HTTPS. This does **not** add HTTPS to the existing
HTTP server: password changes require a trusted LAN, a verified HTTPS endpoint,
or a suitably configured VPN. This release does not establish trust on hotel
Wi-Fi or provide protection from an active network intermediary over HTTP.

## Storage and concurrency

The v2 credential file stores a random 16-byte salt and a 32-byte scrypt hash
(`N=32768`, `r=8`, `p=1`, approximately 32 MiB per calculation). Calculations run
outside the ASGI event loop. A shared service lock serializes login verification
and rotation, so an old-password login cannot mint a surviving session after a
rotation. The application remains a single-process service, consistent with its
existing in-memory sessions, display state, scheduler and event bus.

Updates write a private 0600 temporary file, flush and fsync it, replace
`credentials.json` atomically, and fsync the parent directory before reporting
success. A failure before replacement returns 503 and retains the old file,
password and sessions. If replacement succeeded but directory fsync failed,
memory follows the visible new file and all sessions are revoked. That 503
explicitly asks the user to reconnect with the **new** password and check storage;
power-loss durability cannot be promised in this exceptional case.

Valid legacy `{"password": "..."}` files migrate on startup without changing the
password. Their plaintext field is removed. Corrupt, unsupported or unreadable
files fail closed; startup does not silently reset access. Local recovery must
be explicit through `inky-studio reset-password`.

Only a newly generated first-boot or explicit-reset password retains a
`bootstrap_password` in that private file. This permits the physical welcome
screen and CLI to show it after power loss. Personalization removes it. Migrated
and personalized passwords cannot be recovered with `inky-studio password` or
`inky-studio welcome`; the CLI explains the explicit reset command, and the
screen displays that the password is not consultable. The app never logs secrets.
The local password/reset CLI deliberately prints the initial/new secret to its
invoking terminal; do not capture that output in shared logs.

While a bootstrap credential exists and photo history is empty, startup retries
the welcome screen, including after a power interruption during first boot.
Welcome PNGs are created privately with mode 0600; physical-display temporary
images are removed after use, including display failures. Existing preview and
legacy temporary-image paths are restricted to 0600 on credential loading.

## Mandatory deployment gate: refresh the installed CLI

Version 0.4.2's installer copied its CLI into `/usr/local/bin/inky-studio`.
The current updater replaces `scripts/inky-studio-cli` in the installation tree
but **does not update that installed copy**. Its old `password` command expects
a plaintext JSON field, and its old reset command deletes the credential file.

Do not ship this backend to a device while leaving that old installed CLI in
place. A deployment operator must perform the following controlled steps, using
the device's actual installation and data paths. The service should remain
stopped while deploying the matching backend and CLI and taking the backup.

```bash
# Set INSTALL_DIR and DATA_DIR to the actual paths before running these commands.
sudo systemctl stop inky-studio.service
umask 077
BACKUP="${DATA_DIR}/credentials.pre-password-rotation.$(date -u +%Y%m%dT%H%M%SZ).json"
test ! -e "${BACKUP}"
install -m 0600 "${DATA_DIR}/credentials.json" "${BACKUP}"

# Deploy the reviewed backend/release tree and its dependencies while stopped.
sudo install -m 0755 "${INSTALL_DIR}/scripts/inky-studio-cli" /usr/local/bin/inky-studio
cmp "${INSTALL_DIR}/scripts/inky-studio-cli" /usr/local/bin/inky-studio
sudo systemctl start inky-studio.service
```

The backup command assumes an existing installation; a fresh installation has
no credential file to back up. Run the commands as the service/data owner, with
the administrative authorization needed to install the CLI. Do not broaden the
application's scoped sudoers rule. The installer already installs the new CLI on
fresh/re-run installations. No updater privilege changes are included here.

A thin installed wrapper pointing to the repository script could remove this
staleness problem for future installations, but would need separate migration
and ownership/path validation. It is intentionally not part of this change.

After startup, check health and the capability field, log in with the existing
secret, and qualify rotation, other-device logout, idle WebSocket disconnection,
CLI read-only behavior and a controlled local reset. Do not print the credential
file while collecting diagnostics. The synthetic Pi benchmark below qualifies
the scrypt primitive on the actual hardware. End-to-end login/rotation latency,
storage durability and behavior during a display refresh still require a
controlled deployment qualification; the benchmark does not exercise those paths.

## Rollback and local recovery

Keep a protected pre-migration credential backup and the previous release until
qualification completes. The old server cannot read v2 credentials and may
silently generate a replacement: never start it against the v2 file.

Before any password change, a rollback can stop the service, restore the previous
backend and matching CLI, and atomically restore the protected legacy credential
backup (stage it on the same filesystem with mode 0600, then rename it over
`credentials.json`) before restart. Verify the expected login locally.

After personalization, restoring the pre-migration backup would reactivate the
old password and undo its revocation. Do not do that silently. Prefer fixing
forward with the v2 backend, or perform an explicitly agreed local credential
reset as part of rollback. Preserve the current credential file privately before
any recovery operation. Once recovery/qualification is confirmed, remove obsolete
plaintext backups under the operator's chosen retention policy.

The updated `inky-studio reset-password` stops the service, atomically persists a
fresh bootstrap credential, and restarts it even when persistence fails. A
pre-replacement failure keeps the old credential; restart clears all sessions.
There is no BLE recovery, account-based recovery, or recovery-code mechanism yet.

## Verification

Local Python 3.13 checks: 180 backend tests passed; an additional assertion that
login/rotation logs do not contain the secrets passed in its targeted test.
Python 3.11: 178 tests passed before the final welcome-image permission changes,
then all 31 affected credential-storage/welcome tests passed. Ruff, ShellCheck
for the installer/CLI/uninstaller, and `git diff --check` passed. Both environments
are isolated temporary virtual environments. A non-blocking Starlette warning
announces future deprecation of its httpx-based TestClient.

Coverage includes legacy migration and corrupt-file rejection, salted hashes,
permissions, file-fsync/rename/directory-fsync failures, concurrent old-password
login and a competing rotation, full session revocation, WebSocket notification
from a worker thread, password boundaries/Unicode and secret-free validation,
rate limiting, cookie replacement, disabled-auth capabilities, read-only CLI
behavior, successful/failed CLI reset, and personalized welcome-screen behavior.

These tests use isolated temporary data, harmless service-command stubs and
mock displays. They do not change the live Pi or exercise production credentials.

### Pi Zero 2 W: synthetic scrypt benchmark

Measured via the existing SSH key on **2026-09-27 at 11:19:47 UTC**. The command
ran `python3` with an inline script, read only the hardware model and
`/proc/meminfo`, and executed three sequential `hashlib.scrypt` calls. It did not
read or modify credentials, change any service, write files on the Pi, or use
sudo. Inputs were public synthetic bytes: `b'inky-synthetic-benchmark-only'` and
`bytes(range(16))` as the salt; the derived values were not printed.

| Property | Observed value |
| --- | --- |
| Hardware | Raspberry Pi Zero 2 W Rev 1.0 |
| Python | 3.13.5 |
| Architecture / kernel | aarch64 / 6.12.75+rpt-rpi-v8 |
| Parameters | N=32768, r=8, p=1, maxmem=67,108,864 bytes, dklen=32 |
| Trial 1 | 491.838 ms |
| Trial 2 | 494.303 ms |
| Trial 3 | 492.160 ms |
| Median / mean | 492.160 / 492.767 ms |
| Process peak RSS before / after | 16,280 / 49,240 KiB |
| Increase in process peak RSS | 32,960 KiB, about 32.19 MiB |
| MemTotal | 426,076 KiB |
| MemAvailable before / after | 195,060 / 200,056 KiB |
| SwapTotal | 1,474,552 KiB |
| SwapFree before / after | 1,345,680 / 1,345,680 KiB |

Each duration used `time.perf_counter()` around one call. Peak RSS came from
`resource.getrusage(resource.RUSAGE_SELF).ru_maxrss`, in KiB on Linux. Available
memory is a system-wide snapshot and can vary independently of this process;
its increase must not be interpreted as the benchmark freeing that amount.

All three calls completed successfully. The measured cost is approximately
0.49 seconds for one password verification and about 32 MiB additional working
memory. A successful rotation verifies the old password and derives the new hash,
so its cryptographic work alone is **estimated** at roughly 0.98 seconds from
these measurements. That estimate excludes lock contention, HTTP, filesystem
writes/fsync and simultaneous device workloads. The parameters remain unchanged.
