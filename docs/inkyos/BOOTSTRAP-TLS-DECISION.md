# Bootstrap trust and clock repair — selected design direction

Status, 2026-09-28: **isolated TLS primitives implemented; no integrated bootstrap
flow, wire compatibility, or deployment qualification**. This follows the first-boot
requirements and factory ledger at `2c03466464f1b45f4baf1763e0416da52a8bef24`.
Normal BLE/HTTPS retain full date validation. Shared Swift trust now also checks
the leaf's digital-signature KeyUsage explicitly, after a negative fixture exposed
Security's permissive handling of a self-signed CA anchor. The deployed candidate
remains unchanged.
See [prototype scope and validation](BOOTSTRAP-TLS-PROTOTYPE.md).

## Decision and explicit change to the earlier requirement

Use the existing TLS 1.3 primitives in a **separate bootstrap profile**. The frame
key is known from the physical QR or an existing Keychain ownership record. The
TLS handshake must prove possession of that key before any QR/owner secret is
sent. This profile may disregard only the pinned certificate's expiration and
not-yet-valid flags; normal BLE and HTTPS retain full date validation.

This explicitly revises the earlier blanket requirement against any disabled
date check. Bootstrap is not full temporal X.509 validation, and must not be
presented as such. It is an application-defined pinned-key trust policy for a
limited initialization/repair purpose. No generic `ignoreDates` fallback will be
added to the ordinary transport or URLSession delegate.

The pin is public. It authenticates the frame to the phone, **not the phone to
the frame**. Every mutation also requires either the active physical QR claim
proof or a currently authorized owner token, checked against the current password
epoch. No unauthenticated time setter is exposed.

| Approach | Assessment |
| --- | --- |
| Current strict TLS only | Cannot repair a certificate that is already expired according to the iPhone |
| Separate TLS bootstrap profile | Reuses implemented cryptographic primitives; requires explicit trust-policy isolation and new bounded application commands |
| TLS Raw Public Key | Standardized but not a supported configuration of both current wrappers; replacing/extending the stacks is a larger project |
| Custom challenge/HMAC before TLS | Avoid: introduces a new security protocol and conflicts with existing hash-only owner-token storage |

[RFC 7250](https://www.rfc-editor.org/rfc/rfc7250.html#section-3) describes raw
SPKI keys with externally established identity bindings; [TLS 1.3](https://www.rfc-editor.org/rfc/rfc8446.html#section-4.4.2)
also accommodates that certificate type. Although [OpenSSL exposes RPK APIs](https://docs.openssl.org/3.6/man3/SSL_set1_server_cert_type/),
the inspected [Python 3.13 wrapper](https://github.com/python/cpython/blob/3.13/Modules/_ssl.c)
does not expose them. [Mbed TLS 4.1.1's TLS 1.3 parser](https://github.com/Mbed-TLS/mbedtls/blob/mbedtls-4.1.1/library/ssl_tls13_generic.c#L543)
parses X.509 DER; its RPK references do not supply a usable RPK API for this app.

## Required separation and certificate checks

The prototype must use distinct typed client construction, trust evidence,
server TLS context, GATT entry and command dispatcher. Require a dedicated ALPN
value authenticated by the handshake and reject absent/unexpected negotiation.
The isolated prototype fixes ALPN to `inky-bootstrap/1`; this is not an advertised
GATT capability or a complete versioned wire contract. GATT UUIDs remain open.
Existing v1 clients remain on their current
service; do not retrofit a mandatory new ALPN onto that legacy endpoint.

For bootstrap only, after checking the exact expected P-256 SPKI pin:

- Keep TLS 1.3, `VERIFY_REQUIRED`, expected canonical frame name, key/algorithm
  restrictions, certificate structure and signature/usage checks.
- Accept one expected directly pinned leaf, rejecting unexpected chains. At
  depth zero, only `MBEDTLS_X509_BADCERT_EXPIRED` and
  `MBEDTLS_X509_BADCERT_FUTURE` may be removed from verification flags.
- Preserve every other error, including name mismatch, untrusted or revoked
  certificate, unsupported key/hash and malformed data. Never clear all flags.
- Require successful `CertificateVerify`, `Finished`, matching pin and expected
  ALPN before exposing plaintext. Disable early data, resumption and shared tickets.
- Preserve the explicit self-signature check currently performed by the Swift
  normal trust code. Simply skipping `PinnedFrameTrust` would lose more than dates.

The iOS prototype's `BootstrapFrameTrust` is only certificate prevalidation.
It reuses Security's complete SSL policy at a strictly interior certificate date;
this is not an API that removes individual Security errors. The C TLS profile
independently enforces its stricter certificate shape and preserves all Mbed
verification flags except the two permitted leaf-date flags. Neither a constructed
Swift trust value nor a parsed anchor proves a completed handshake or ownership.

Mbed's [verification callback contract](https://github.com/Mbed-TLS/mbedtls/blob/mbedtls-4.1.1/include/mbedtls/x509_crt.h#L599),
[error flags](https://github.com/Mbed-TLS/mbedtls/blob/mbedtls-4.1.1/include/mbedtls/x509.h#L87)
and [TLS certificate checks](https://github.com/Mbed-TLS/mbedtls/blob/mbedtls-4.1.1/library/ssl_tls.c#L8797)
support a narrowly scoped policy. They do not validate this application's proposed
authorization or protocol separation. TLS proof-of-key and transcript integrity
remain necessary under [RFC 8446 §§4.4.3–4.4.4](https://www.rfc-editor.org/rfc/rfc8446.html#section-4.4.3).

The existing HTTPS implementation already accepts a renewed self-signed leaf
under the same pin after normal checks (`FrameTrustPolicy`). Certificate expiry
is therefore not itself offline revocation of a compromised pinned key. Neither
normal same-key renewal nor bootstrap can repair key compromise: that requires
explicit local identity replacement and physical trust establishment.

## Allowed sequence and authority

| Frame state | Bootstrap operations | Following steps |
| --- | --- | --- |
| Authorized fresh factory | Initial QR claim, authenticated claim recovery/status, then owner-authorized clock repair | Issue normal certificate; end bootstrap; reconnect with normal TLS |
| Already adopted, including an interrupted first setup | Current owner authentication/status and clock repair; no automatic new claim | Renew certificate with same UUID/key; end bootstrap; reconnect with normal TLS |
| Missing/inconsistent authority or no valid physical/owner proof | No mutation | Explicit local recovery |

The first claim must commit **before changing wall time**. Existing QR windows
check wall time as well as a monotonic deadline; changing time first could
invalidate the legitimate claim. Thus factory bootstrap is deliberately more
than "time only", but its allowlist stays limited to initial claim/recovery/time.
The iPhone must save its token before claim. Loss of the response or a crash
before clock repair resumes using that same owner; it never recreates factory.

After an accepted clock value, issue/renew the normal certificate under the
**same private key and frame UUID**, including recovery from a previously wrong
future issuance date. The present renewal rule that preserves a leaf when
`now < issued_at` needs a distinct authorized repair path; do not globally relax it.

A repaired clock alone cannot un-expire a leaf according to the iPhone. Retrieve
the renewed DER, match the original SPKI, validate it normally, and perform a new
strict handshake. The [Mbed direct-anchor check](https://github.com/Mbed-TLS/mbedtls/blob/mbedtls-4.1.1/library/x509_crt.c#L2413)
uses the actual certificate; do not treat an old DER anchor as an automatic trust
decision for a new leaf or suppress `NOT_TRUSTED` to accommodate renewal.

Only after normal TLS succeeds: confirm the operating country, verify its
effective application, scan/connect Wi-Fi, confirm the frame through pinned
HTTPS, and perform separate photo-password login. Country settings, Wi-Fi/photo
passwords, network mutation and photo APIs are rejected on bootstrap.

## Clock mutation and OS boundary

Use a serialized, bounded operation with boot/session freshness and a durable
result receipt. A lost response must not repeatedly apply an old clock value.
The current owner/epoch must be checked under the mutation lock immediately
before delegation. Define failure/retry after each time/certificate write.

An authenticated phone's timestamp is an owner assertion, not independent proof
of correct UTC. Reject non-integers, booleans, overflows and values outside the
supported range. The exact numeric limits and correction-confirmation policy
remain to be specified; a fixed short lifetime from the release date must not
make an image unusable after storage. A bad future value must have an explicit
authorized recovery path rather than becoming an irreversible high-water mark.

Session expiry must use monotonic elapsed time. Explicitly invalidate active
network sessions during repair where required, suspend/reconcile the photo
scheduler and close unused QR windows before the jump. The network helper already
uses monotonic deadlines; this does not establish correct behavior for every
other consumer of wall time.

The InkyOS session may prototype a socket-activated, bounded privileged operation
component, separately from the persistent unprivileged network helper. It must
verify the numeric local peer UID, use fixed operations/arguments, reject caller
paths, serialize mutations, and keep executable files/parents outside app writes.
Do not add broad capabilities to the current helper as a shortcut. Exact units,
capabilities, writable paths and effective permissions need review before activation.

Prefer investigating persisted regulatory state plus a pre-NetworkManager gate
over runtime writes to all of bootfs. Whether this works reliably with the target
driver remains a target test, not an assumption. Keep experimental units inactive
and do not mutate real wall clocks in a shared VM during parser/model tests.

## Prototype acceptance and remaining implementation

1. Normal/bootstrap matrix: valid, expired and future leaves. Only the dedicated
   bootstrap date cases may pass; pin/name/self-signature/usage/key/chain failures
   must fail in both profiles before secrets are sent.
2. Alter CertificateVerify/Finished; offer TLS 1.2, absent/wrong ALPN, or replay
   sessions/early data. No successful bootstrap authority or normal plaintext.
3. Normal operations on bootstrap and bootstrap operations on the normal service
   fail closed. Network errors and pin mismatches never select bootstrap silently.
4. Unknown/revoked owner, old password epoch, stale QR or concurrent revocation
   cannot change time. Two phones cannot create two initial owners or race setters.
5. Kill after claim, time write, certificate persistence and before response.
   Resume the same owner/request without reopening factory or replaying old time.
6. Repair an expired leaf and a leaf issued under a bad future time, then prove
   strict normal BLE and HTTPS success with the original UUID/SPKI.
7. Check wall-clock jumps against sessions, scheduler, windows and helper deadlines.
8. Complete Python/Mbed interoperability, Swift trust/Keychain and Simulator tests
   before physical iPhone/QR/clock/Wi-Fi qualification on dedicated hardware.

Next implementation ownership: Inky Studio owns the typed bootstrap trust/channel,
identity repair, authorization/coordinator and helper client policy. InkyOS owns
the privileged operation prototype, initialization receipt and image/boot gates.
The root-owned receipt adapter, identity lifecycle, wire schemas, time numeric
policy and complete iOS flow are still open; this decision does not enable them.
