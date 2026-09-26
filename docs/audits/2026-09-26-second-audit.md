# Stabilization audit — independent second pass

Date: 2026-09-26. Reviewed first-pass commit: `4a86ee5` against baseline
`18f231d`. This pass began **after [PR #2](https://github.com/mehdi7129/inky-studio/pull/2)
was opened**, as requested. The [first report](2026-09-26-first-audit.md) remains
unchanged as the record of the initial conclusions.

## Outcome

The original baseline defects were confirmed. However, the first pass did **not**
fully solve A13/A14/A15, and its A06/A08 changes introduced two regressions. Those
overly broad completion claims are corrected below. Passing the original 133
backend / 18 frontend tests was insufficient evidence for these edge cases.

Reviewers changed areas: the initial API reviewer checked updater/packaging,
the initial frontend reviewer checked backend services, and the initial backend
reviewer checked the client. The coordinating reviewer independently checked
API/authentication, image validation and actual browser/server interaction.
Baseline and first-pass source archives were used for differential reproductions;
all hardware interactions used temporary files and fake/mock drivers.

## Verification of the first report

| Claim | Verdict | Evidence and qualification |
| --- | --- | --- |
| A01 | Confirmed | Independent baseline sdist build fails on the README path; corrected sdist→wheel succeeds. |
| A02 | Confirmed | Independent anonymous encoded absolute-path request exposes a temporary private marker on baseline (200); corrected app returns 404. Limited to files readable by the server process. |
| A03 | Confirmed | Baseline anonymous WS receives `hello`; corrected route rejects it. This exposed event metadata, not permission to execute REST mutations. First-pass browser handling of rejected reconnects was incomplete: B05 below. |
| A04 | Confirmed | Inter-thread event test runs with asyncio debug enabled and a waiting consumer. Corrected dispatch runs on the consumer's loop. This does not imply every production broadcast previously crashed. |
| A05 | Confirmed | Real scheduler tick with empty history: baseline no show / queue 1; corrected one show / queue 0. |
| A06 | Confirmed, correction regressed an edge case | Hardware failure previously consumed queue; corrected failure retains it. The original PNG was not deleted. A missing source file instead blocked later photos until B02. |
| A07 | Confirmed, bounded guarantee | Fake shared driver reproduces duplicated rendered content on baseline and distinct serial content after correction. Lock is per process; display/history/ack are not one crash-atomic transaction. |
| A08 | Confirmed, correction regressed concurrent deletion | Baseline navigation oscillates; first fix reaches earlier entries, but the new FK fails if history is deleted during refresh. B01 fixes this. |
| A09 | Confirmed | Independent Europe/Paris transition checks: advertised 06:00/04:00 becomes 05:00/05:00. The original report correctly distinguished this from the following day's scheduler tick. |
| A10 | Confirmed, conditional | Two-thread service reproduction loses one field before correction and retains both afterwards. Current synchronous service calls within a single async route loop do not interleave that way. |
| A11 | Confirmed | The same reorder/new-props regression fails on baseline and passes on the PR. |
| A12 | Confirmed, test boundary clarified | Delayed conversion test rejects a stale upload after correction. Canvas/HEIC conversion is mocked in that test; it is not decoder qualification. |
| A13 | Confirmed, initially only partially fixed | App generations and hello resync were insufficient for Settings/History races and a rejected reconnect handshake. B05–B07 reproduce and fix these gaps. |
| A14 | Confirmed, migration initially incomplete | New wrapper works, but the previously installed `/usr/local/bin/inky-studio` is a copy and stays unchanged during in-app update. B03 retains its old Python entrypoint. Welcome restart cleanup also passes independent stub checks. |
| A15 | Confirmed, validation initially incomplete | Sibling-prefix extraction escape is blocked; links/special entries are rejected. Missing assets directory still passed first-pass payload validation: B04. Member/expanded-byte limits apply after `getmembers()`; compressed downloads and initial metadata allocation remain unbounded. |
| A16 | Confirmed, code restoration only | New file survives baseline rollback, is removed after correction. Dependencies, power loss, partial successful deployment and post-restart health are not covered by this guarantee. |
| A17 | Confirmed, bounded scope | Independent 10,000-attempt run: same five accepted attempts, stored timestamps reduced from 10,000 to 5. Credentials/reset helper tests pass. The shell reset-password command still deletes then restarts; the atomic helper test is not an end-to-end CLI reset guarantee. |
| A18 | Confirmed, not an ingress cap | Handler rejects oversized files and password value is no longer logged. Parsing/spooling before the handler remains possible, as first report already disclosed. |
| A19 | Confirmed | Baseline permits zero client tests, releases only build. Independent npm scan confirms 10→0 advisory change. CI now runs actual suites and both supported test Python versions. Registry scan is not a security proof; Pi-only dependencies were not scanned. |
| A20 | Confirmed | Baseline Next/Previous 202 bodies cause JSON parse failure; response-boundary tests and Safari verify the correction. HTTP 202 is returned after the handler finishes refresh, not while a detached job runs. |
| A21 | Confirmed | Error visibility regressions reproduced and corrected. Additional stale palette/default-saturation comments found and corrected in this pass. |

## Findings added by this pass

All nine cases below were reproduced before their second-pass correction. They
are P2; B01/B02 were regressions introduced by the first-pass changes, B03–B07
were incompletely covered behaviours, and B08/B09 were additional baseline bugs.

| ID | Reproduction / impact | Final correction and regression |
| --- | --- | --- |
| B01 | Delete the Previous target while the fake driver is inside `show()`: screen changes to B, then FK `IntegrityError` leaves API state at C. | Navigation cursor is a chronological integer boundary, not a FK into a deletable log. Tests cover target deletion, clear during refresh and deletion between Previous calls. |
| B02 | Missing first queued PNG: repeated Next raises `FileNotFoundError`, blocks valid later photos. | Skip only the unusable queue entry, retain photo metadata, emit `skipped/file_missing`, continue. Actual driver errors, including `FileNotFoundError` from a missing SPI device, still preserve the queue. |
| B03 | Existing global wrapper invokes `python -m inky_web.updater`; only the repository wrapper had been fixed. | Compatibility module delegates to current updater; subprocess/runpy test uses a stub main, no network/systemd. |
| B04 | Release contains server/main, pyproject and client/index but no assets directory; validation passes although app import requires assets. | Reject before backup/application. Test asserts neither installation mutation is reached. This is not a complete asset-integrity or health check. |
| B05 | Restart local server with same data and stale browser cookie: WS handshakes return 403, browser reports 1006, UI remains logged in indefinitely. | Check HTTP auth before reconnect, with a 3-second abortable timeout and normal offline backoff. Real Safari now returns to login without manual reload after restart. |
| B06 | Old Settings GET arrives after successful saturation PATCH to 1.5; slider reverts to 1.0. | Settings reads and mutations share a request generation. Deterministic delayed-response regression. |
| B07 | Old post-delete History reload arrives after a newer WS-triggered load `[C,B]`; C disappears. | All history reload paths share a generation. Deterministic delayed-response regression. |
| B08 | PNG with correct chunk CRCs but empty decompressed IDAT is accepted; Pillow pixel decode then raises a truncation error at display time. | Fully decode after checking expected dimensions, before persistence. Synthetic malformed PNG rejected without a stored file. |
| B09 | Same PNG uploaded after switching expected panel from 800×480 to 1600×1200 is accepted via dedupe. | Validate dimensions and pixels before SHA-based reuse; regression rejects the duplicate for the wrong panel. |

`display_navigation` is a new table introduced by this unmerged PR. Removing its
FK adjusts the new schema, not an existing released schema. Temporary databases
created with the intermediate first-pass build are not migrated by this change.

## Final validation

- Python 3.11.12: Ruff passes; **142 pytest tests pass**. One upstream
  Starlette/httpx deprecation warning remains.
- Node 22.23.3: ESLint, TypeScript and production build pass; **23 Vitest tests
  in three files pass**. The lazy HEIC chunk-size warning remains.
- `npm audit`: **0 known advisories** on the final dependency tree. Python
  dependencies did not change after the first-pass clean audit of the prepared
  development environment.
- First-pass GitHub CI passed Python 3.11, Python 3.13, frontend and ShellCheck.
  The final commit is submitted to the same checks; their live results are on
  [PR #2](https://github.com/mehdi7129/inky-studio/pull/2).
- Safari smoke: the first-pass workflow (login, live queue, mock display,
  history/requeue, Settings) plus a real server restart. Before B05 the UI stayed
  stale while WS repeatedly received 403; after B05 an auth-status request and
  automatic login screen were observed. Temporary server stopped and test tab
  closed afterwards.
- Shell syntax, ShellCheck, clean sdist/wheel build and `git diff --check` pass.

The remaining work listed in the first report is still relevant: separation of
current display/library from deletable history; multipart ingress limits; atomic
deployment/dependency rollback; storage recovery and quotas; persistent update
progress; history pagination/accessibility; real HEIC and Pi/SPI/GPIO validation.
No release, merge, installation on a Pi or production update was performed.
