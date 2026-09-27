# InkyTLS — transport-independent TLS 1.3 client

Local Swift package for iOS 18+ / macOS 13+, Swift 6. A Swift actor owns a C
memory-BIO bridge to **Mbed TLS 4.1.1**. It does not discover Bluetooth devices,
adopt frames, store owner credentials or change Wi-Fi.

## Build the dependency

From the repository root:

```sh
bash scripts/build-mbedtls-apple.sh
```

Requires Xcode, CMake and Python ≥3.12 (override `INKY_TLS_PYTHON` if necessary).
The script verifies the official archive against the fixed SHA-256 before
extraction, compiles only static libraries, and generates
`Artifacts/MbedTLS.xcframework` with these slices:

- iOS: arm64, deployment target 18.0.
- iOS Simulator: arm64 + x86_64, deployment target 18.0.
- macOS: arm64 + x86_64, deployment target 13.0, for package tests and Mac bench.

No global install. Archive, sources, build folders, XCFramework and toolchain
metadata are ignored by Git. This is a pinned, repeatable build process, not a
claim of identical bytes across compiler/SDK versions. The default upstream
crypto configuration is retained; TLS version, tickets and early data are
restricted per connection. `INKY_TLS_BUILD_JOBS` defaults to 4.

The application project must explicitly depend on this package after artifacts
are generated; this package does not change the app project. CI must perform the
dependency build before resolving/building the package. Third-party notices are
in [Licenses](Licenses/NOTICE.md); retain them when distributing the linked app.

## Trust and API

```swift
let configuration = try TLSConfiguration(
    serverName: identity.expectedServerName,
    trustedCertificatesDER: [freshCertificateDER],
    pinnedSPKISHA256: identity.spkiSHA256
)
let client = try TLSClient(configuration: configuration)
```

**Before this call**, the caller must compare the freshly received certificate's
SPKI hash to its independently trusted physical QR / persisted identity. This
package requires DER trust anchors and a 32-byte SPKI pin. It never trusts an
advertisement, an IP address or a certificate received without that comparison.
There is no trust-all mode, optional certificate verification or HTTP fallback.

The connection enforces TLS 1.3, X.509 REQUIRED (chain, name, dates and usage),
plus SHA256(DER SubjectPublicKeyInfo) in the verification callback. The callback
never removes library verification errors. Session tickets and 0-RTT are off.
The agreed self-signed P-256 frame certificate (CA:TRUE, serverAuth, DNS SAN,
396-day validity) works as an explicit anchor. A renewed certificate may use the
same pinned key; instantiate a new client with the freshly validated DER.

1. `receiveCiphertext` atomically enqueues transport bytes; on `.backpressure`,
   **none were consumed**. Retain and retry after the TLS engine makes room.
2. `advanceHandshake` returns `.complete`, `.needsRead`, or `.needsWrite`.
   Always drain available output with `drainCiphertext(maxBytes:)`; WANT_READ
   does not imply that the output queue is empty.
3. Only after authenticated handshake, `queuePlaintext` accepts one message of
   1...16384 bytes. `flushPlaintext` resumes it without changing the owned buffer
   while Mbed TLS requires WANT_WRITE retries. Drain output between retries.
4. `readPlaintext` returns bytes, progress needs or clean closure. Empty transport
   EOF without TLS close_notify is a terminal error. `close` emits close_notify
   once pending plaintext has drained; then drain ciphertext and close transport.

Input/output rings are each bounded (default 64 KiB, accepted 1–256 KiB); a
single owned plaintext buffer is 16 KiB. These do not include Mbed TLS's own
record/handshake allocations. A process-wide mutex also serializes PSA state
across different actors. No blocking I/O occurs inside the engine. Deadlines,
cancellation, framing, peer isolation and Bluetooth flow control belong to the
caller. Discard a failed/disconnected client and create a new one; never mix
fragments from different sessions. No secret or certificate logging.

## Validation

Generate fresh **synthetic** fixtures before testing (no private key is bundled
in the test runner or committed). The generator uses Python and
`cryptography>=44,<51` for explicit validity dates; no OpenSSL CLI is required.
Set `INKY_TLS_TEST_PYTHON` to the Python interpreter with this dependency installed.

```sh
cd ios/Packages/InkyTLS
bash Tests/InkyTLSTests/Support/generate-fixtures.sh
COPYFILE_DISABLE=1 swift test --scratch-path /tmp/inky-tls-spm-tests
xcodebuild -scheme InkyTLS -destination 'generic/platform=iOS' \
  -derivedDataPath /tmp/inky-tls-device-build CODE_SIGNING_ALLOWED=NO build
xcodebuild -scheme InkyTLS -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath /tmp/inky-tls-simulator-build CODE_SIGNING_ALLOWED=NO build
```

Mac interop requires Python with OpenSSL/TLS 1.3. Set `INKY_TLS_TEST_PYTHON`
explicitly (recommended in CI); otherwise the peer resolves `python3` from PATH. The Python peer communicates only through pipes.
Use `/tmp` build output on a File Provider/Desktop workspace to avoid generated
bundle Finder metadata breaking ad-hoc signing.

Verified on 27 September 2026, Xcode 27:

- **10 Mac tests PASS**: valid self-signed identity, wrong pin/name/expired/future/
  trust anchor rejected, no plaintext before authentication, 16 KiB send with
  TX queue 1024 and 20-byte fragments, receive backpressure without consumption,
  clean peer closure, corrupt record rejection, abrupt EOF, configuration errors and
  a delayed pipe response spanning more than one poll interval.
- **3 tests PASS on iOS 18.5 Simulator**, including a real Mbed TLS ClientHello
  generated with that runtime's entropy source (no radio/network).
- Package build PASS for generic iOS device and Simulator; libraries also contain
  the x86_64 Simulator slice. This does not constitute a physical iPhone BLE test.

The upstream library's full test suite was not executed here. This package is
qualified for these limited cases, not an independently audited adoption system.
