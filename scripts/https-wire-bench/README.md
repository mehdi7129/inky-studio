# HTTPS wire qualification

Run from macOS with Xcode and OpenSSL 3. The driver uses Python's standard
library only (Python 3.10 or newer):

```sh
scripts/test-https-wire.sh --output /tmp/inky-https-wire-results.json
```

`INKY_HTTPS_PYTHON` and `INKY_HTTPS_OPENSSL` override the executables. The defaults
prefer Homebrew Python 3.13 / OpenSSL 3 on Apple Silicon, then `PATH`. OpenSSL must
support `req -not_before` and `-not_after`.

The Swift CLI compiles the **actual application sources** `InkyAPI.swift`
(including `OriginRedirectDelegate`), `PinnedFrameTrust.swift`,
`FrameIdentity.swift`, `OwnershipVault.swift`, `Models.swift`, and `APIError.swift`.
No delegate or trust implementation is copied into the harness. Strict Swift
concurrency checking and warnings-as-errors are enabled.

Each run generates fresh P-256 keys and ECDSA-SHA256 self-signed certificates,
with CA:true, serverAuth, a stable frame DNS SAN, and 396-day validity windows.
All test servers bind `127.0.0.1` on ephemeral ports and require TLS 1.3. The
URLSession endpoint uses the IP; its certificate has only the expected frame
DNS SAN, proving that the adopted identity drives the SSL name policy.

The cases exercise real HTTP requests and WebSocket upgrades:

- Original certificate, renewed certificate with the same key, and a renewed
  peer while the owner's cached certificate is expired: auth status, password
  login, private session cookie, PNG photo, WSS `hello`, and Wi-Fi confirmation.
  A separate assertion proves that the expired cached certificate would fail
  fresh BLE trust validation.
- Wrong QR pin, a changed key, wrong SAN, expired or not-yet-valid leaf, and
  modified self-signature: login, photo, WSS and Wi-Fi confirmation all fail.
  Server TCP counters prove that clients connected; HTTP counters prove that
  no application request (owner headers or password) reached those peers.
- Direct HTTP with an adopted owner, and HTTPS 307 redirects to plaintext or
  another HTTPS port: requests are rejected. Neither destination receives even
  a TCP connection. The allowed redirecting origin receives exactly one login.

The optional JSON evidence contains results, TLS versions, request/connection
counts, source hashes, certificate hashes and tool versions. It contains no
password, token, cookie, private key, request body or header dump. Synthetic
credentials are fixed in the test source; no personal credential is read.
Private keys and the compiled CLI live in a restricted temporary directory
which is removed at process exit. The harness never calls Keychain or Bluetooth
and never installs a trust anchor or changes system trust settings.

This proves the **macOS Foundation URLSession wire path using production app
code**. It does not replace iOS runtime/ATS, local-network permission, Wi-Fi
migration, Raspberry Pi hardware, or real-radio BLE qualification. Renewal is
tested on fresh URLSessions with distinct leaf DER, not an already-open socket.
