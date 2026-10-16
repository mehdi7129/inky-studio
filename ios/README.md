# Inky Studio for iPhone

Native SwiftUI companion for Inky Studio, iOS 18+. Photo transfer requires a Raspberry reachable on the same local network. There is no cloud account. `InkyTLS` embeds pinned Mbed TLS 4.1.1 for Bluetooth provisioning.

## Candidate and delivery

This branch implements the Bento B connection screen approved on 2026-10-16 and required local unlock with Face ID **or the iPhone passcode**. It removes the product demo and manual frame-address/password entry. This candidate has not been uploaded to Apple. The delivered internal TestFlight baseline is **1.0.0 (11)** from `e6da9c05`; a successful local build does not change that delivery state. No public App Store submission is included.

## Run

Open `InkyStudio.xcodeproj`, choose InkyStudio and an iPhone Simulator or device. A fresh checkout needs the local TLS binary artifact:

```bash
# Requires Xcode, CMake and Python 3.12+; downloads hash-verified upstream source.
scripts/build-mbedtls-apple.sh

# Regenerate after adding/removing source files.
xcodegen generate --spec ios/project.yml

xcodebuild build -project ios/InkyStudio.xcodeproj -scheme InkyStudio \
  -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO
```

Scan the frame's supported LAN login QR. Keep iPhone and frame on the same Wi-Fi and accept the iOS local-network prompt. The current LAN QR assumes that the frame already has a working network. Offline first-boot association is a separate InkyOS contract; an invitation shown by another iPhone is also a future protocol, not a supported QR type in this candidate. Unsupported QRs must be rejected without replacing an existing frame or secret.

## Features

- **Cadre:** current photo, previous/next display commands, schedule and queue summary.
- **File:** add/reorder/remove photos, including accessible reorder actions.
- **Historique:** dates, pagination, requeue original PNG bytes and remove history.
- **Réglages:** schedule, saturation, device information, Pi release check/update, associated-frame Wi-Fi configuration, help, local lock and forget.
- Native Photos picker/camera, HEIC/JPEG/PNG, EXIF orientation, crop/pan/zoom/reset and exact panel dimensions. Output is SDR/sRGB PNG without private source metadata; the Pi owns quantization. Camera captures are not automatically saved to Photos.
- Rounded Bento UI, native light/dark appearance and Dynamic Type. No demo, example-photo button, biometric preference or manual frame password form.
- Foreground WebSocket updates with bounded reconnect/backoff and polling recovery. Pending display confirmation is not a confirmed successful display; photo/queue state remains authoritative on the server.

## Local unlock and migration

Local unlock is separate from the Pi session. Face ID or the **system iPhone passcode** is required; the app never collects that passcode in a custom field. An iPhone passcode must be configured. New frame credentials use Keychain `WhenPasscodeSetThisDeviceOnly` with `.userPresence`, allowing biometrics or the device passcode. The app never receives biometric data. Legacy `biometryCurrentSet` items need authenticated migration; an invalidated item cannot retroactively be recovered using a different ACL.

After the first successful QR association, the credential is saved under that protection. A failed save leaves the new association incomplete and prevents mutations until storage succeeds; retrying storage does not replay network login. Cancelled local authentication leaves the app locked. A background lock preserves a live Pi session instead of logging out. Content and network actions require the local unlocked state; no prompt or login is added to each photo request. Inactive system-authentication transitions must not cancel their own unlock attempt. A scene-window cover also shields presented photo surfaces while inactive, in addition to the root and native camera covers.

Cookies remain private and in memory, isolated per origin/client and shared by JSON/PNG/WebSocket requests. The Pi invalidates sessions when its process restarts. **An old session with no saved credential can be locally locked/unlocked while still alive, but cannot be made durable by recovering a password from its opaque cookie.** If v11 was closed, or an app update terminated it after credential storage was skipped, its RAM cookie/password is already gone. A future authenticated backend enrollment can only help a session that is still valid; this candidate cannot promise scan-free recovery of a lost secret. Voluntary LAN recovery authenticates locally and validates a separate QR candidate before replacing the old connection; cancelling keeps the previous cookie, locator and protected credential. An adopted frame keeps its HTTPS pin: leaving that association requires fresh local authentication and an explicit, account-scoped forget confirmation, not an HTTP downgrade.

The existing LAN QR uses private-IPv4 HTTP:8000 and carries a frame password. It has no frame-ID/SPKI trust anchor and must not be treated as a pinned identity or copied as an invitation. Adopted frames retain the separate HTTPS pin/owner path with no silent fallback to HTTP. TLS checks are never bypassed and cross-origin redirects must not forward cookies/credentials. See [Bluetooth integration](../docs/ios/BLUETOOTH-INTEGRATION.md).

## Tests and visual checks

The loopback fixture is test infrastructure, independent of the removed demo. It never contacts a real Pi. Disable test parallelization; use ad-hoc Simulator signing so Keychain entitlements exist:

```bash
python3 ios/scripts/mock-server.py
# In another terminal:
python3 ios/scripts/smoke-api.py

caffeinate -i xcodebuild test -project ios/InkyStudio.xcodeproj -scheme InkyStudio \
  -destination 'platform=iOS Simulator,id=<SIMULATOR_UDID>' \
  -only-testing:InkyStudioTests -parallel-testing-enabled NO \
  -collect-test-diagnostics never CODE_SIGNING_ALLOWED=YES CODE_SIGN_IDENTITY=-
```

Tests inject local-auth/vault operations to exercise the state machine and failures. Such tests and DEBUG locked-state screenshots do not establish physical Face ID/passcode, QR optics, Wi-Fi commit/rollback or e-ink display. Connected UI tests additionally need fixture setup/seeded Photos. Report runner startup failures separately from failed product assertions.

See [distribution](../docs/ios/DISTRIBUTION.md) for a separately authorized archive/sign/upload and [validation](../docs/ios/VALIDATION.md) for the historical physical qualification boundaries.

## Architecture and references

`Core/` owns wire types and the isolated network client; `Auth/` wraps local unlock and protected Keychain access; `App/AppStore.swift` owns frame/session state; `UI/` owns tabs and connection views; `Photos/` owns import and crop. `Provisioning/` owns the distinct Bluetooth adoption/owner protocol.

Apple: [deviceOwnerAuthentication](https://developer.apple.com/documentation/localauthentication/lapolicy/deviceownerauthentication), [userPresence](https://developer.apple.com/documentation/security/secaccesscontrolcreateflags/userpresence), [Keychain local authentication](https://developer.apple.com/documentation/localauthentication/accessing-keychain-items-with-face-id-or-touch-id), [local network privacy](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy).
