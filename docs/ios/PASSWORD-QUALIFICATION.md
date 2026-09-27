# Isolated HTTP/WebSocket password-upgrade qualification

`scripts/qualify-password-upgrade.py` qualifies the staged backend on a Mac or Pi
without using the production service, credentials, database or display. It uses
the runtime dependencies already needed by the application: FastAPI, Uvicorn and
websockets. The HTTP client is Python's standard library; pytest, TestClient and
httpx are not required.

## Run against an explicit staging tree

Use the existing application virtual environment and set `PYTHONPATH` to the
candidate's `server` directory. This selects candidate code without installing
it over production or changing the existing environment's packages.

```bash
PYTHONPATH="${STAGING_DIR}/server" \
  /home/pi/inky-studio/server/.venv/bin/python \
  "${STAGING_DIR}/scripts/qualify-password-upgrade.py" --timeout 60
```

On the Mac, substitute the local virtual environment's Python executable. The
script accepts a 5–180 second test deadline, with up to six additional seconds
per active child for graceful shutdown and forced termination. Its result is
one JSON object and exit code 0 for success or 1 for a failed check. Invalid CLI
arguments use argparse's normal exit code 2. The reported backend version helps
verify which candidate was loaded; always use the explicit staging `PYTHONPATH`.

The JSON contains fixed check labels, backend/Python versions and timings. It
does not contain passwords, salts, hashes, cookies, credential contents or raw
exception messages. Child stdout/stderr and application logging are suppressed
to avoid accidental request-state disclosure. On failure, the check label or
exception class is reported without a traceback.

## Isolation and cleanup

- A new mode-0700 temporary directory holds synthetic credentials and a marker.
  A new legacy-format file is created with mode 0600; no production file is read.
- The parent binds `127.0.0.1:0` and transfers that exact descriptor to a child.
  There is no public-network bind or free-port discovery/startup race.
- The child creates a new FastAPI app with the **real** auth/WebSocket routers,
  authentication middleware and validation-error handler. It uses fresh
  CredentialService, SessionStore, rate limiters and EventBus instances.
- The main application lifespan is never started. No DisplayController,
  scheduler, database, updater or management CLI is invoked. Importing the
  middleware definitions does not initialize the production application.
- The child explicitly enables authentication and points any incidental data-dir
  lookup to its private QA directory. An inherited development auth bypass
  therefore cannot produce a false pass.
- HTTP uses direct loopback sockets with no proxy, redirect or mutation replay.
  The WebSocket client receives an already connected loopback socket, so proxy
  configuration cannot redirect its handshake.
- Every network operation has a timeout bounded by the remaining test deadline.
  A POSIX alarm also bounds library waits or fragmented HTTP response reads.
  The parent terminates and reaps the server child on success, failure or an
  ordinary interruption; if graceful termination takes four seconds, it kills
  the child and waits up to two more seconds. WebSocket close has a two-second
  timeout. Temporary credentials are removed by the parent's context manager.
  As with other tools, SIGKILL or power loss cannot execute cleanup; any leftover
  uniquely named QA directory still contains synthetic data only and is private.

Never qualify the management CLI's `reset-password` command using only a
temporary data-dir override: that command still addresses the real systemd
service. This script does not invoke it, sudo, or systemctl.

## What is checked

1. Public capability reporting and 401 protection without a session.
2. Legacy credential migration to a scrypt-only file without changing the
   synthetic initial password, followed by two independent HTTP logins.
3. Incorrect current password gives 403 without replacing the cookie or revoking
   its session; invalid new-password length gives 422 without echoing secrets.
4. A real WebSocket receives `hello`; rotation returns 200 and a new HttpOnly,
   SameSite=Strict cookie; the idle old WebSocket closes with code 1008.
5. Both old sessions are rejected, the new session works, the old password fails
   and the new password logs in successfully.
6. Five rotation attempts consume the real rate limit; the next returns 429
   while preserving the authenticated session.
7. The persisted file remains 0600 and contains neither supplied password nor a
   cleartext bootstrap field.
8. The first server process is stopped. A second process reloads that same file:
   previous sessions fail, the old password fails and the new password works.
9. Both server processes exit and the temporary directory is removed.

Reported timings are HTTP round trips including actual scrypt and filesystem
work for this isolated instance. They do not qualify the physical display,
production CLI migration, production settings/data, TLS or an app session on a
phone. Failure-injection/storage-concurrency coverage remains in the backend
unit suite; this script does not fill or alter the production filesystem.

## Local validation

The initial Mac run using Python 3.13.3 and websockets 17.1 completed all 29 checks
in 2.232 seconds against backend `0.5.0-rc.1`. Initial login took 77.317 ms,
rotation 131.207 ms and login after restart 66.512 ms. These are Mac measurements,
not Pi measurements. Root performs the separate candidate run on the Pi.

The final Python 3.11.12 run also passed all 29 checks in 2.134 seconds. Negative
tests using isolated synthetic package fixtures verified failed child startup
(0.519 s), the five-second deadline (5.103 s), and SIGTERM interruption (0.746 s).
Each returned failure JSON without stderr/tracebacks and removed all temporary
QA data. Ruff with the backend configuration and `git diff --check` passed.

The deployment gate remains unchanged: refresh the installed CLI/launcher with
the required administrative action before migrating production credentials.
See [PASSWORD-ROTATION.md](PASSWORD-ROTATION.md) for deployment and rollback.
