# Stabilization audit — first pass

Date: 2026-09-26. Baseline: `18f231d` (`origin/main`, version 0.3.3).

## Scope and method

Reviewed the backend, React client, image pipeline, authentication, WebSocket
delivery, SQLite services, scheduling, display lifecycle, installer, updater,
CLI, CI/release workflows and documentation. Findings below are based on code
inspection plus local reproductions; physical display behaviour is not certified.

The original local checkout was `a0f239f`, 16 commits ahead and 25 behind the
rewritten remote branch. It was left untouched. Work uses a separate worktree
and the current GitHub baseline. Early hypotheses about removed worker/dither
code were discarded before this report.

Baseline inventory: 94 tracked files, 3,132 Python lines, 2,251 client code lines
(including CSS/config), 115 script lines, 107 workflow lines, plus the 280-line
root installer. Generated dependencies and the npm lockfile are excluded from
code-line counts.

Three parallel reviewers examined separate areas. Each confirmed defect was
paired with a reproduction or regression where practical. Root integration
checks included clean Python installation, packaging, shell checks and a real
Safari session against a loopback-only server with disposable data and a mock
display. No Pi service, hardware, release or production data was modified.

## Baseline validation

| Check | Result on baseline |
| --- | --- |
| Clean Python 3.11 `pip install -e './server[dev]'` | Failed: Hatchling rejects README outside project directory |
| Ruff | Pass |
| Pytest using isolated baseline source and prepared dependencies | 75 pass |
| Frontend lint and production build | Pass |
| Frontend tests | Zero tests; `passWithNoTests` concealed the gap |
| Shell syntax | Pass |
| ShellCheck | SC2086 and SC2046 in legacy-process handling |
| npm advisory scan | 10 alerts: 6 high, 4 moderate, development toolchain |
| Masked tracked-file secret-pattern scan | No private-key/GitHub-token/AWS-key pattern match; not a historical or exhaustive secrets audit |

## Confirmed findings and corrections

P1 denotes a major reliability/security defect; P2 a functional or bounded
hardening defect; P3 a minor diagnostic/documentation issue. Priorities include
the local-network, single-process deployment context.

| ID | Priority | Baseline evidence | Correction / regression evidence |
| --- | --- | --- | --- |
| A01 | P1 | Clean install fails on `readme = '../README.md'`. | Use the existing server README; clean editable install and sdist→wheel build pass. |
| A02 | P1 | Anonymous encoded parent/absolute SPA paths return files outside `client/dist` with HTTP 200. | Resolve and confine all candidates; parent, absolute and symlink escape tests; unknown API paths return 404. |
| A03 | P2 | REST queue returns 401 while anonymous WebSocket receives `hello`; idle disconnected subscribers persist. | Authenticate handshake, recheck sessions, receive disconnects, clean up subscribers; auth/revocation/idle tests. |
| A04 | P2 | Scheduler thread writes to `asyncio.Queue`; waiting subscriber raises `RuntimeError` in debug mode. | Dispatch on each subscriber's owning loop with `call_soon_threadsafe`; thread/debug tests. |
| A05 | P1 | Daily mode with no history never becomes due (4,320 computed ticks; actual ticks at the configured hour and next day leave the queue intact). | Past first daily window is due; scheduler tests exercise real ticks. |
| A06 | P1 | Simulated display `OSError` leaves both queue and history empty. | Peek then acknowledge only after successful display/history recording; manual/automatic retry tests. |
| A07 | P1 | Two interleaved fake-driver calls show the same image twice; concurrent queue pops return the same entry. | Serialize display operations and driver calls; SQLite transactions for add/reorder/pop. Concurrent fake-driver, next, add and pop tests. |
| A08 | P2 | Previous after A→B→C produces B→C→B→C. | Additive persisted navigation cursor; Previous reaches A and stops. |
| A09 | P2 | Next-change timestamp shifts to 06:00/04:00 across DST for a 05:00 setting. The next day's tick already recalculated correctly. | Advance by calendar day; Europe/Paris DST tests. |
| A10 | P2 conditional | Concurrent settings service calls can overwrite unrelated fields; multi-field writes are autocommitted individually. Single-loop async routes do not themselves interleave these synchronous calls. | Write only submitted fields within one transaction; concurrent service regression. |
| A11 | P2 | Successful reorder leaves a permanent optimistic order; later uploaded photo is absent from the list. | Release temporary order after refresh and serialize mutations; React regression reproduced before the patch. |
| A12 | P2 | User can upload the previous PNG while a newly selected crop is encoding. | Bind prepared result to source/file/dimensions/offsets; prohibit stale upload; delayed-encode regression. |
| A13 | P2 | Reconnect `hello` ignored; open History/Settings do not refresh; older responses can overwrite newer state. | Resync on reconnect/events, request generations, session-expiry handling; React and WebSocket-hook regressions. |
| A14 | P2 | CLI `update` raises `No module named inky_web.updater`; failed CLI welcome leaves service stopped. | Correct module path; exit cleanup restarts service. Stubbed CLI tests execute both paths. |
| A15 | P2 | Archive `../extracted-sibling/proof` passes string-prefix check and escapes extraction directory; links are not rejected. | Component-aware paths, regular files/directories only, no archived privilege bits, size/member limits and release-layout validation; synthetic archives tested. Requires a malformed/compromised release, not an anonymous API exploit. |
| A16 | P2 | Merge-based rollback leaves files introduced by a failed update. | Prune newly introduced managed files before restore, preserve runtime data/venv, rollback only after complete backup; simulated pip failure test. Cross-process update lock also tested. Dependency rollback is explicitly not claimed. |
| A17 | P2 | Invalid credential JSON schema can crash startup or make login unusable; 10,000 refused logins retain 10,000 timestamps. | Validate credentials and replace atomically with mode 600; bounded deque and monotonic clock; malformed/reset/10,000-refusal tests. |
| A18 | P2 | Upload handler reads entire file without an application limit; password is logged on every startup. | Bound file read/persisted upload to 10 MiB and return 413; remove password values from logs. Multipart ingress caveat below. |
| A19 | P2 | Tests silently succeed without any client test; release workflow only builds. Development dependency advisories remain in baseline lockfile. | Require tests, add frontend regressions, test Python 3.11/3.13, ShellCheck CI and release checks; compatible dependency updates clear npm advisories. |
| A20 | P2 | Real Safari Next click displays image successfully, then errors: `The string did not match the expected pattern.` API returns empty 202, client attempts JSON decoding. | Accept empty successful mutation responses; fetch-boundary regression and repeated Safari smoke check. |
| A21 | P3 | Update-check errors are stored but not shown; Next/Previous errors have no handler; README port/conversion/reset-password descriptions are stale. | Display operation failures, restore controls, correct current docs. |

Installer source-mode version checking now matches Vite's engine range; archive
download/extraction/copy failures return explicitly even when the shell function
is called in an `if` condition. Legacy PID handling uses Bash arrays. These are
static/local checks; no installer was executed against systemd or boot settings.

## Remaining limitations and follow-up work

- **P2, confirmed — history doubles as state/library.** Clearing history makes
  `current()` and recycle candidates empty although stored photos remain. A
  durable display state and a photo-library lifecycle need a separate design.
- **P2 — multipart ingress is not globally bounded.** The 10 MiB handler cap
  prevents unbounded `read()` and final storage, but Starlette may spool a larger
  request before the handler runs. A total request-body cap remains desirable.
- **P2 — updater is not an atomic deployment.** Code restoration is tested, but
  pip dependency changes, process/power interruption, data migrations, health
  after restart, and replacement of old files on successful update are not
  transactional. No end-to-end sudo/systemd update was performed. Progress is
  transient WebSocket state and cannot be recovered by a late-opened panel.
- **P2 — storage validation.** Corrupt typed settings can still fail validation.
  Concurrent photo service writes and filesystem/SQLite crash consistency need
  further fault-injection coverage. There is no automatic storage quota/cleanup.
- **P2 — physical driver qualification.** The lock protects one process; a
  second process, hung SPI driver, power loss, shutdown deadline and physical
  colour/refresh behaviour require Pi testing. The existing `inky==2.3.0` pin
  was preserved. Waiting for the welcome task does not bound a hung driver.
- **P3 — UI completeness.** History exposes only the most recent 200 entries;
  no pagination. Uploader keyboard support remains limited. HEIC decoding was
  not exercised with real images; its lazy-loaded bundle is about 1.35 MB.
- Python dependencies remain lower-bound ranges rather than a deployment lock.
  HTTP LAN without TLS and non-Secure session cookies remain existing deployment
  choices; this audit does not certify Internet-facing use.

## Validation record

Before opening the PR:

- Python 3.11.12: Ruff passes; **133 pytest tests pass** (one upstream
  Starlette/httpx deprecation warning).
- Node 22.23.3: ESLint, TypeScript and production build pass; **18 Vitest tests
  in three files pass**. The known lazy HEIC chunk-size warning remains.
- `npm audit`: **0 advisories** after compatible Vite/Vitest/transitive updates.
  Runtime-only scan also reports zero. This is a registry snapshot, not proof
  that the dependencies contain no vulnerabilities.
- `pip-audit` on the new dev environment: initially flagged its bundled pip
  25.1.1/setuptools 80.7.1; after upgrading this local tooling to pip 26.2.1 and
  setuptools 84.0.0, **0 known vulnerabilities**. The editable application itself
  is skipped by the registry scanner; the hardware-only `pi` extra was not
  installed/audited on macOS.
- Clean editable installation succeeds; `uv build server` builds an sdist and
  then a wheel from that sdist.
- ShellCheck, Bash syntax and `git diff --check` pass.
- Safari against `127.0.0.1:8765`: login, synthetic PNG upload via API with live
  queue update in the browser, Next with mock display, history, requeue, Settings.
  The A20 error was observed before the fix and absent after rebuilding/reloading.
  No real image or physical display was used; the browser crop path was covered
  by component tests with mocked canvas conversion, not this live smoke test.

The second pass must retain this report and explicitly mark any disproved or
overstated claims, rather than silently rewriting the initial conclusions.

External references consulted: [Python tar extraction](https://docs.python.org/3/library/tarfile.html#extraction-filters)
and [Vite runtime requirements](https://vite.dev/guide/). Python extraction
defaults vary by version; this implementation explicitly copies only regular
files/directories instead of relying on those defaults.
