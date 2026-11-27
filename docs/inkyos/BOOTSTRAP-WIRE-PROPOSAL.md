# Factory association wire contract — proposal A

Status: **DOCUMENTARY PROPOSAL, not a registered protocol or implemented
dispatcher**. Prepared against Studio
`cf17a0514989023143798570a8ae47739b829301`. UUIDs, fields and error mapping below
are concrete review candidates; joint Studio/InkyOS review precedes runtime
changes. No service, image, SD, TestFlight build or normal v1 behavior is changed.

## Scope and authority

This lot is a vertical slice: physical QR → bootstrap BLE/TLS → durable factory
claim → authenticated recovery/status. Its last user-visible state is **“Cadre
associé — préparation du cadre en attente”**, not a connected photo frame.
Time, certificate publication, country, Wi-Fi, HTTPS, photos and the initial
photo-password display remain subsequent work. `next_step: system_setup` is a
description of that limitation, never authorization for a phase B command.

Reuse `FirstBootResult`, `PreparedFactoryIdentity`, the existing factory ledger
and `OwnershipStore`; introduce no second ownership/claim ledger. IPC-A is
unchanged. Server authority comes from the independently validated OS receipt,
prepared identity, ledger and current credentials callback, never from public
QR metadata or a phone-supplied epoch. Missing/inconsistent records require
recovery; adopted frames never reopen initial adoption.

See [first-boot requirements](FIRST-BOOT-CONTRACT.md),
[coordinator](FIRST-BOOT-COORDINATOR.md), [TLS primitive](BOOTSTRAP-TLS-PROTOTYPE.md)
and [prepared identity](BOOTSTRAP-IDENTITY.md). The separate phase B proposal is
[PR #25](https://github.com/mehdi7129/inky-studio/pull/25); it is not included or
implemented by this document.

## 1. Physical QR and explicit profile selection

Proposed bootstrap QR, compact UTF-8, **209 bytes** in this synthetic example:

```json
{"v":2,"p":"bootstrap","id":"00000000-0000-4000-8000-000000000001","k":"1111111111111111111111111111111111111111111111111111111111111111","t":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
```

| Field | Required value/type |
| --- | --- |
| `v` | Exact JSON integer lexeme `2`; no boolean, decimal or exponent |
| `p` | Exact ASCII string `bootstrap` |
| `id` | Canonical lowercase UUID with hyphens, 36 ASCII characters; no UUID-version restriction |
| `k` | SHA-256 of the frame's SubjectPublicKeyInfo: exactly 64 lowercase ASCII hex characters |
| `t` | Window claim secret: exactly 64 lowercase ASCII hex characters |

Exactly these five fields, flat object, maximum **512 UTF-8 bytes**. JSON member
order and surrounding JSON whitespace may vary within the bound. Reject duplicate
names after escape decoding, unknown/missing fields, invalid UTF-8, trailing
non-whitespace bytes, nesting and noncanonical values. Numeric value equality
alone does not validate the version lexeme; `2.0` and `2e0` are invalid.

The QR contains no certificate, endpoint, Wi-Fi/password, clock, country, OS
receipt, epoch or BLE peripheral identifier. `t` is temporary; never log it or
save it in iOS ownership storage. Exact in-memory claim retries retain it. After
app relaunch, recover by authenticated status with the saved owner and claim ID
first; a new scan is an explicit physical action, not proof that no commit occurred.
The physical window lasts at most **600 seconds**, with a monotonic deadline
that a wall-clock correction cannot extend. Preserve the store's conservative
invalidation on clock rollback; reboot invalidates the previous window. Only
an authorized, still-unclaimed factory state may open a replacement window.

The new client routes normal QR `{v:1,id,k,t}` through the unchanged normal
parser/profile. The bootstrap type selects only the new service and TLS profile.
Unknown versions/profiles fail explicitly. A normal certificate/date/pin error
never selects bootstrap. Advertisements and readable metadata are discovery
hints, not physical pin authority. After adoption, recovery uses the securely
stored bootstrap provenance and owner for the same frame/key; no new QR authority.

## 2. Separate GATT service, public identity and TLS

Proposed UUIDs are absent from the reference candidate. Review their allocation
before implementation; do not replace or reuse the normal `713b0001…0005` set.

| Role | Proposed UUID | Property |
| --- | --- | --- |
| Primary service | `713b0011-8890-4cc9-a2bf-26f32c43db22` | Primary |
| Identity | `713b0012-8890-4cc9-a2bf-26f32c43db22` | Read |
| Stream | `713b0013-8890-4cc9-a2bf-26f32c43db22` | Read / write-with-response |
| Certificate 0 | `713b0014-8890-4cc9-a2bf-26f32c43db22` | Read |
| Certificate 1 | `713b0015-8890-4cc9-a2bf-26f32c43db22` | Read |

Closed public identity metadata, maximum **128 UTF-8 bytes**:

```json
{"v":2,"p":"bootstrap","id":"00000000-0000-4000-8000-000000000001","cert_length":960}
```

The same version/profile/UUID rules apply; `cert_length` is a strict JSON integer
in **1…960**. Certificate 0 is exactly `min(480, cert_length)` bytes and
Certificate 1 exactly `max(0, cert_length - 480)` bytes, including an empty second
part. ReadBlob is allowed for these public values. Reject length mismatch,
additional bytes or inconsistent frame identity. Authenticate the reassembled
single DER leaf; chunk lengths or ordering alone cannot establish trust.

Use `BootstrapFrameTrust`, `BootstrapTLSConfiguration` and
`BootstrapTLSPeer`, not normal types with a date-ignore flag. TLS **1.3** and
authenticated ALPN **`inky-bootstrap/1`** are mandatory. QR/metadata version `2`
does not change ALPN version `1`. Preserve exact-leaf anchoring, physical SPKI
pin, canonical name, P-256, self-signature and usage checks; only the isolated
bootstrap leaf date exceptions already reviewed apply. No owner token, QR proof
or other application plaintext is exposed until Finished and ALPN validation.
No tickets/0-RTT, fallback, profile-crossing session or shared notifications.

## 3. Bounded transport

Reuse the current per-device read/write ACK design; every reconnect starts a new
RESET and TLS handshake. Public characteristics cannot disclose private stream
responses to another BlueZ device.

| Item | Proposed bootstrap contract |
| --- | --- |
| RESET | Byte `0` + 16 random nonce bytes; exact 17-byte echo |
| DATA | Byte `1`, sequence `uint16BE`, acknowledgement `uint16BE`, TLS bytes |
| CLOSE | Single byte `2` |
| DATA sequence | 1…65534, no wrap; changed retry/missing sequence closes session |
| ATT capacity | `min(244, negotiated MTU - 3)`; refuse a capacity below 20 |
| DATA header | 5 bytes; at most 239 TLS bytes per write at capacity 244 |
| Application record | `uint32BE` byte length followed by JSON UTF-8; no newline requirement |
| JSON payload | 1…16384 bytes, depth ≤32, no duplicate names/NaN/Infinity/UTF-16 |
| Concurrency | At most two device sessions; one application command in flight per session |
| TLS buffer | 65536 bytes maximum |
| Timeout | Absolute 45 s handshake deadline; 180 s since the last new DATA exchange, using monotonic time |

For DATA number `n`, the request is `seq=n, ack=n-1` and its cached response is
`seq=n, ack=n`. A retry must be byte-identical and returns that same response;
a changed duplicate, missing number or divergent ACK closes the session. No
sequence wraps. The handshake deadline starts at accepted RESET and is never
extended by reads, retries or DATA. Check it before further traffic and sweep
expired bootstrap sessions periodically so silent peers release their slots.
The idle deadline starts at RESET or the last successfully accepted new DATA
sequence, including empty polling DATA. Reads and byte-identical retries do
not extend it. This measures transport activity, not TLS progress; it preserves
asynchronous response polling. Normal v1 behavior remains unchanged.

Framing/encoding failures close the transport; an application error reply is not
required. Application pipelining and trailing record bytes are rejected. The
normal server currently admits ATT writes up to `min(512, MTU - 3)` while the
client caps them at 244. Applying **244 explicitly to the new bootstrap path**
is a proposed tightening, not an assertion about the unchanged normal server.

## 4. Closed request schemas and existing-store mapping

Only `bootstrap.claim` and `bootstrap.status` are admitted. The `bootstrap.`
prefix prevents accidental acceptance by the normal dispatcher. Symmetrically
reject normal `claim`, `status`, `wifi.*`, `owner.revoke`, all phase B operations
and unknown commands, even for an authenticated owner.

### Claim

```json
{"v":1,"id":"00000000-0000-4000-8000-000000000003","op":"bootstrap.claim","owner_id":"00000000-0000-4000-8000-000000000002","owner_token":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","claim_token":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
```

Exactly six fields. `v` is the exact integer lexeme `1`; `id` and `owner_id`
are canonical lowercase UUIDs; both tokens are exactly 64 lowercase hex
characters. Before the first mutation, iOS durably stores owner ID/token and
claim `id` in Keychain, with bootstrap provenance, frame UUID and SPKI pin.
Storage failure emits **zero claim**. The QR secret stays in memory only.

Map to `store.claim(claim_token, owner_id, owner_token, id, expected_epoch)`.
`expected_epoch` comes from the server's verified credentials callback and is
revalidated inside the mutation. No epoch, intent, root receipt or initialization
authority is accepted as a client claim field.

Initial claim requires the active physical QR proof and authorized factory
state. Claim/adoption/owner receipt/QR consumption remain one existing durable
transaction. Identical retries use the same owner, tokens and ID; a different
intention using the same ID is refused. Do not generate a replacement owner or
reset factory state after a timeout, unauthorized result or loss of a reply.
After relaunch, `unauthorized` does not distinguish an uncommitted claim from
revocation or an epoch change. Preserve owner/token/claim ID. If the user rescans
an authorized current QR, only its temporary QR secret changes; this is a new
physical proof, not an identical retry. Let the existing store accept or refuse
that proof and surface conflicts/recovery. Never mint another owner or claim ID
to evade a refusal; an adopted frame offers no new initial QR.

### Status/recovery

```json
{"v":1,"id":"00000000-0000-4000-8000-000000000004","op":"bootstrap.status","owner_id":"00000000-0000-4000-8000-000000000002","owner_token":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","claim_request_id":"00000000-0000-4000-8000-000000000003"}
```

Exactly six fields, with the same integer/UUID/token rules. `id` correlates this
RPC and is independent of the saved `claim_request_id`; never overwrite the
saved claim ID with a status ID. Map to
`store.status(owner_id, owner_token, request_id=claim_request_id)`.
Authenticate the current owner, token, revocation and epoch before reporting
whether its requested claim matches. This is not public frame discovery.
No matching receipt yields `request_not_found` only after owner authentication.

### State-specific admission

| Validated state | Claim | Status and physical window |
| --- | --- | --- |
| No authority / initialization pending | No wire admission; complete or refuse the existing initialization coordinator first | No QR/GATT bootstrap admission |
| Authorized `FACTORY`, ready | Initial claim requires the current physical proof; transaction selects one winner | Unknown owner is unauthorized; only this state can open a bounded initial QR |
| `ADOPTED`, current owner/receipt valid | Exact winning replay only; no second adoption/new owner | Authenticated receipt recovery; never reopen initial QR |
| Integrity/binding/epoch recovery | Refuse; preserve evidence and identity | Fixed recovery outcome; no new authority/window |

This is a lot A admission matrix, not a phase B state machine. `ADOPTED` alone
cannot select a later bootstrap-open or bootstrap-closed mode. A future integrated
runtime must consult its reviewed phase B gate rather than reopening this
initial-association service solely because the factory ledger says adopted.

## 5. Success, errors and uncertain outcomes

Success for either operation is a closed envelope and a closed result:

```json
{"v":1,"id":"00000000-0000-4000-8000-000000000004","ok":true,"result":{"frame_id":"00000000-0000-4000-8000-000000000001","owner_id":"00000000-0000-4000-8000-000000000002","claim_request_id":"00000000-0000-4000-8000-000000000003","factory_state":"adopted","next_step":"system_setup"}}
```

`id` equals the current RPC, `frame_id` equals the authenticated pinned frame,
and owner/claim IDs equal the verified durable result. `factory_state` comes
from validated ledger state after commit. Do not return `asdict(ClaimResult)` as
the whole result: that model does not contain the frame/state. Status with a
different requested claim does not return this successful envelope.

`adopted` is terminal ownership, **not** a bootstrap-open latch, clock acceptance,
normal-certificate availability or completion proof. `next_step` does not
advertise an implemented phase B capability. No hostname, HTTPS port, token,
QR, root receipt or photo password is returned. New bootstrap records must not
call `AppStore.finishBluetoothSetup` or `scanNetworks` at this endpoint.

Closed failure envelope:

```json
{"v":1,"id":"00000000-0000-4000-8000-000000000004","ok":false,"error":"request_not_found"}
```

Use `id: null` only when no canonical request ID can be extracted from a valid
parsed envelope. Never echo an invalid ID or interpolate exception text.
An uncorrelated error is grammatically readable but cannot acknowledge a
pending claim or prove its absence. Keep its outcome uncertain and use status.

| Public code | Meaning / mapping |
| --- | --- |
| `invalid_request` | Invalid application shape/type/version/op; normalize internal invalid ID/token/epoch validation |
| `unauthorized` | Invalid QR/owner proof, unknown/revoked/current-epoch-invalid owner |
| `qr_unavailable` | Window absent, expired, invalidated on restart or no longer admitted; normalize store `factory_not_ready` here without opening/resetting factory |
| `request_conflict` | Existing ID has another intention |
| `request_not_found` | Authenticated owner, different requested claim |
| `epoch_changed` | Credentials changed across claim admission/transaction |
| `owner_capacity` | Existing store capacity reached |
| `rate_limited` | Claim limiter |
| `service_stopping` | Runtime admission closed |
| `recovery_required` | Invalid durable integrity/binding or FactoryRecoveryRequired |
| `unavailable` | Fixed internal failure; outcome may be uncertain |

Before implementing, check actual store exceptions in the wrapper: this table
is a proposed normalization, not today's emitted wire enum. No response,
`unavailable`, or failed screen cleanup does **not** prove that claim did not
commit. Retain saved credentials and query authenticated status. Only the same
verified owner can recover the winning result; a losing phone gains no authority.

## 6. Runtime and phase B barriers

Console factory startup must use the validated `FirstBootResult` before any
normal identity/DB/HTTPS/network client/scheduler initialization. It must never
fall through to legacy lifespan; direct ASGI factory entry stays refused.
Use a distinct runtime/dispatcher and explicit BootstrapTLSPeer construction.
BlueZ and the iOS transport currently hardcode the normal UUIDs; constructor
parameterization alone without profile-bound trust is insufficient.

Keep admitted mutations registered until their real transaction completes, even
after session removal. Cancelling an async wrapper around `to_thread(claim)`
does not stop the SQLite work. Shutdown closes admission then drains mutations
and the single SPI owner. Never release its lock early or start another refresh
while shutdown is draining. Display failure closes/reconciles the QR window.
Reboot unclaimed invalidates the old QR and replaces the physical screen;
reboot adopted resumes the same owner/key/receipt with no initial QR reopening.
Factory screen restoration must not call normal photo-history/settings loaders.

Subsequent phase B needs separately reviewed owner/epoch-bound admission,
helper→OS proof, certificate candidate journal, strict normal-TLS reconnect and
durable closure before country/Wi-Fi/photo APIs. Neither `adopted`, a helper UID,
a boolean nor this `next_step` field supplies that proof. The OS owns installed
layout, global writer exclusion and readiness; this proposal changes no units.

## 7. Shared synthetic vectors and acceptance

[Vectors](bootstrap-wire-proposal/vectors.json) preserve bytes in
`input_utf8_hex` rather than parsed objects, including duplicate/escaped keys,
invalid UTF-8 and numeric lexemes. They are inert: repeated hex strings and UUIDs
are test-only, not credentials for any frame. Each case names a decoder stage
and expected classification; binary framing/certificate recipes are separate.
The fixture `reason` is a decoder-test classification, not an extra public
error enum. Binary recipes describe individual bounds, not complete TLS sessions.

Python consumers use `bytes.fromhex(case["input_utf8_hex"])`; Swift consumers
decode pairs of ASCII hex into `Data`. Both feed the **same raw bytes** into their
future strict bootstrap decoder. Ordinary `JSONDecoder(Int)` or `json.loads`
alone does not enforce every rule above. This proposal does not claim either
new decoder already passes these vectors.

Acceptance for the integrated lot requires:

1. All shared raw grammar/boundary/profile vectors pass Python and Swift;
   normal v1 stays unchanged and rejects/bootstrap never downgrades crossings.
2. Real Python/OpenSSL ↔ Swift/Mbed TLS + GATT framing: pin/name/signature/usage,
   wrong/absent ALPN and TLS 1.2 failures yield zero dispatch/application secrets.
3. Keychain failure emits zero mutation; saved IDs/token match exactly; response
   loss, crash before local acknowledgement, suspension and reboot recover the
   same winning claim. Two phones yield one durable winner.
4. Epoch/pin mismatch, conflicting ID, expired QR and corrupted records stay
   closed. No normal/time/country/Wi-Fi/photo operation escapes the allowlist.
5. TERM/disconnect during SQLite/SPI drains the admitted work without orphan
   mutation or competing refresh; screen/restart reconciles correctly.
6. Bento light/dark captures of the pending/recovery states preserve rounded
   cards; then physical iPhone QR/BLE/e-ink trials without LAN and with bad RTC.

Document/vector checks establish only proposal consistency. No hardware,
decoder interoperation, complete first boot or phase B readiness is evidenced by
committing this document.
