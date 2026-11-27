# Validation — PHOTO access candidate

Base: `73f65627baf38e82f9d102fb727834f275205642`.
Python: existing isolated `/Users/mehdiguiard/Library/Caches/inky-display-250-validation-venv/bin/python`.
No package/dependency installation. All runtime data lived in pytest temporary
directories. Real network checks used ephemeral loopback listeners only.

Results:

- Ruff check of `inky_web` plus `tests/test_photo_access.py`: PASS.
- Extended targeted regression suite including existing production listeners:
  **129 passed**,1 warning,123.66s. Files: test_photo_access.py, test_auth.py,
  test_auth_storage.py, test_websocket.py, test_provisioning_integration.py,
  test_provisioning_listeners.py.
- After serializing legacy enrollment with logout, the final auth/API regression
  suite: **118 passed**,1 warning,24.20s. Same files except listener suite; now
  includes the additional actual HTTP/TLS PHOTO endpoint regression.
- Final small fail-closed role hardening:3 targeted tests PASS (unknown corrupt
  role rejected, exact claim retry, invited photo/upload/schedule/display path).
  No broad suite was repeated after that one-clause predicate change.
- `git diff --check`: PASS.

The warning is the environment's existing Starlette/httpx deprecation notice,
not a product failure or a dependency change.

Coverage includes competing concurrent claims (one recipient only), exact
idempotent retry, token/device/request mismatch denial, invitation lifetime,
process restart, durable anti-replay receipts after expiry/restart, issuer and
recipient revocation, finite/highwater clock changes, password epoch changes,
external durable reset and corrupt/missing credentials without implicit recovery,
capacity bounds, cookie-only enrollment, device/media denial from owner APIs,
media photo upload/navigation/scheduling, closed WS event filtering, closing idle
WS on revocation/reset/session displacement, no-store and redacted validation,
oversized body refusal and no secret in API/log output.

The real production entry point ran in isolated child processes with Uvicorn,
HTTP, TLS1.3, session cookies and certificate validation. HTTP plus forged
X-Forwarded-Proto/Forwarded was refused403. Real TLS1.3 could enroll and open an
individual owner session; response SPKI matched the tested certificate and the
cookie was Secure. Existing dual-listener shutdown/drain and BLE integration
regressions passed. Inert display/BlueZ fixtures were used: no SPI, real frame
refresh, BLE radio, Pi, SD, Wi-Fi or installed app was contacted.

Independent source-only review by `/root/qr_invitation_contract` found three P2
issues; all corrected and reread closed: invitation recreation after expiry,
durable credential epoch observation, and irreversible clock invalidation.
Final review reported no new concrete P1/P2 in its bounded scope; no independent
reviewer tests were run.

Not qualified by these tests: integration in iOS, actual iPhone QR/Face ID/code
fallback, new phone invitation/Keychain persistence, real Pi deployment or
physical display, configuration of a real canonical HTTPS sharing origin,
first boot offline/bootstrap, old-v11 cold start recovery, factory/Phase B.
No push, upload, deployment, merge or runtime mutation was performed.
