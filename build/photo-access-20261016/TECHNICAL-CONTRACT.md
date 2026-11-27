# PHOTO access and invitation candidate — 2026-10-16

Source-only candidate, based on `73f65627baf38e82f9d102fb727834f275205642`.
Worktree: `/Users/mehdiguiard/Library/Caches/inky-studio-photo-access-20261016`.
Branch: `codex/photo-access-20261016`.
No Pi/SD/service/image/update, iOS, BLE ownership, Phase B, main, push or deployment changed.

## Authority and transport

The new PHOTO store is `<data_dir>/photo-access/access.sqlite3` (directory0700,
file0600), separate from Bluetooth `owners`. Owner is enrolled **only** using an
existing, live password-login/legacy cookie on HTTPS. A device cookie, including
an invited media cookie, cannot enroll or promote any owner.

The app must already possess independently approved frame identity before it
sends its legacy cookie or its new credentials over HTTPS. Learning a pin from
HTTP is **not** trust establishment. A live cookie alone cannot recover a lost
cookie, recover an erased QR/password, establish initial trust, or bypass iOS
local authentication. This candidate does not solve cold start of old v11 with
only a lost RAM cookie.

Production `main.run()`/`serve()` disable Uvicorn `proxy_headers` for both actual
listeners. New endpoints require ASGI HTTPS; device cookies require HTTPS for
all API calls and WSS for WebSockets. Neither Forwarded nor X-Forwarded-Proto is
used as transport evidence. TLS termination/reverse proxy startup with trusted
proxy headers is outside this deployment contract.

Public identity is read from the **already-loaded public certificate** in
`app.state.frame_identity`: frame UUID and SHA256(DER SubjectPublicKeyInfo).
PHOTO routes never load/create identities, read `identity.json`, access key_pem,
write certificates, or read a private key. When HTTPS identity is unavailable,
the endpoints return503 before mutation.

**Creation of an invitation is closed (503) unless**
`INKY_STUDIO_PHOTO_ACCESS_URL` contains an explicit canonical HTTPS origin.
Example shape only: `https://frame-host.local:8443`.
No Host, forwarded host, address detection, certificate SAN or BLE owner state
is guessed to create that URL. Transport host/IP and TLS certificate SAN can be
different; iOS must use the approved SPKI with its pinned transport policy.
No public-origin configuration was added to any real Pi in this task.

## JSON contract

All UUIDs are canonical lowercase hyphenated UUID strings. Device and invitation
tokens are exactly32 bytes represented by64 lowercase hexadecimal characters.
The iPhone generates and durably saves tokens, IDs and request IDs **before**
sending the request. Tokens occur only in JSON request bodies, never paths or
query strings. The server persists hashes only and does not echo a token.
Unknown fields and noncanonical/coerced values are rejected.

`identity` means `{ "frame_id": UUID, "spki_sha256": HEX64 }`.
Invitation creation adds `"url": "https://configured-origin:port"` to identity.
Unix timestamps are numbers in seconds. JSON examples below use type labels,
not actual credentials.

- `POST /api/auth/devices/enroll` (live LEGACY cookie only):
  request `{device_id:UUID, device_token:HEX64, request_id:UUID}`;
  response `{device_id:UUID, role:"owner", identity:Identity}`.
  Identical retries return the same result. It preserves the legacy cookie;
  the client then opens a device session. This avoids losing enrollment retries
  when its response is uncertain. Different credentials/request/device cannot
  overwrite a prior enrollment. Enrollment serializes with logout/password
  rotation, and refuses stale RAM authority after an external durable reset.
- `POST /api/auth/device-session` (no cookie required):
  request `{device_id:UUID, device_token:HEX64}`;
  response `{authenticated:true, device_id:UUID, role:"owner"|"media", identity:Identity}`
  plus `inky_session` cookie with Secure, HttpOnly, SameSite=strict.
- `POST /api/auth/invitations` (individual PHOTO owner cookie only):
  request `{invitation_id:UUID, invitation_token:HEX64, request_id:UUID, ttl_seconds:INTEGER}`;
  ttl_seconds defaults300, permitted1..300; response
  `{invitation_id:UUID, expires_at:UNIX, role:"media", identity:IdentityWithURL}`.
  The server assigns media unconditionally; clients cannot request owner.
  Identical creation retries preserve initial expiry, never extend it.
- `POST /api/auth/invitations/claim` (no cookie required):
  request `{invitation_id:UUID, invitation_token:HEX64, device_id:UUID, device_token:HEX64, request_id:UUID}`;
  response and cookie are the device-session shape with role media.
  Retry requires the exact original invitation/device/request/secrets, still
  valid invitation window and issuer authority, and nonrevoked device.
- `DELETE /api/auth/invitations/{invitation_id}` (PHOTO owner): `{revoked:true}`.
  Idempotent. Closes the invitation, including retries. A device already admitted
  has its own credential; revoke that device separately to remove its access.
- `GET /api/auth/devices` (PHOTO owner):
  `{devices:[{device_id:UUID, role:"owner"|"media", created_at:UNIX, revoked:BOOL}]}`.
- `GET /api/auth/devices/{device_id}` (PHOTO owner): one object from that list,
  404 if absent from the current epoch.
- `DELETE /api/auth/devices/{device_id}` (PHOTO owner): `{revoked:true}`.
  Revokes the device and its outstanding invitations, invalidates all of its
  sessions and actively closes already connected, idle WebSockets. No accepted
  physical refresh is canceled mid-operation.

The **iPhone** constructs the secret QR from its pre-saved invitation token:
`{v:1,p:"invite",id:FRAME_UUID,k:SPKI_HEX64,url:HTTPS_ORIGIN,i:INVITATION_UUID,t:TOKEN_HEX64}`.
No bootstrap, password, cookie, device token or BLE owner token appears in it.
The backend does not render or emit the QR and no new iOS parser is claimed here.

## Roles and compatibility

Legacy password login/logout/password rotation and v11 cookies remain supported
on their previous endpoints. Their old HTTP behavior is unchanged. New owner
cookies can use owner APIs, but cannot act as legacy enrollment cookies.

Media capabilities are a closed method/path list: state/display diagnostics,
photos, queue/upload/reorder/remove, history, manual next/previous, reading
settings, and scheduling updates (`change_mode`, `change_hour`,
`change_interval_minutes`). Media cannot change saturation or other settings,
password, Wi-Fi/provisioning, update software, create/revoke invitations, enroll
owners, list/revoke devices, or access future unknown API routes. WS media events
also use a closed list, excluding system/update events and future unknown types.
The server enforcement is independent of whether the iOS UI hides controls.

## Durability, bounds and failure behavior

SQLite uses BEGIN IMMEDIATE and synchronous=FULL. A shared authorization gate
serializes password rotation, enrolling, claiming, authenticating/issuing device
sessions and revocation. Durable password-verifier epoch is checked for every
PHOTO authorization. Missing/corrupt credentials refuse access without creating,
repairing or migrating the credential file. External durable reset is detected
by idle device WebSockets within approximately1 second; normal revocation sends
an immediate wakeup.

Invitation lifetime is capped300s by wall and monotonic clocks. Restart removes
all active invitation/claim-retry records. Finite-clock/highwater checks and
committed invalidation prevent an observed expired/rolled-back QR from becoming
valid again when time returns to an earlier value. Issuer role/revocation and
current credential epoch are rechecked atomically at claim.

Permanent anti-replay receipts prevent reusing invitation ID, request ID or token
hash after pruning, expiry, claim or restart. Bounds:128 lifetime device records
(including revocation tombstones),128 active invitation rows,4096 lifetime issued
invitation receipts,2MiB DB page limit,8 sessions per device,2048-byte new auth
request bodies including chunked bodies. Device-session/claim share a global
30 attempts/minute limit. On exhaustion, reject rather than delete security
receipts; raising limits or explicit local recovery requires a separate reviewed
change. Epoch rotation intentionally invalidates existing device credentials;
there is no implicit media-to-owner recovery.

New auth responses/errors use Cache-Control:no-store. Authenticated device API
responses also use no-store, including photos. Validation returns a generic422
without input, context or attacker-controlled field names. Secrets are not in
logs/events, response JSON, exception messages or emitted credential metadata.
403 = HTTPS/origin/role refusal;401 = unauthorized/revoked/expired;
409 = conflict/capacity/auth-disabled;413 = oversized;422 = invalid input;
503 = unavailable identity/configuration/storage. These are generic failure
messages and do not expose stored hashes or invitation/device token validity.

## Validation

See `VALIDATION.md` beside this report for final command results and remaining
qualification boundaries. No new external dependency.
