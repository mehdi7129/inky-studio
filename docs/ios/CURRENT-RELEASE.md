# Inky Studio for iPhone

Native SwiftUI companion for Inky Studio, iOS 18+. Photo transfer requires a Raspberry reachable on the same local network. There is no cloud account. `InkyTLS` embeds pinned Mbed TLS 4.1.1 for Bluetooth provisioning.

## Candidate and delivery

Current: **1.0.0 (19)**, source `65e626e8760bc956e17a118f2a18175b184a6f3c`,
available in the existing internal TestFlight group. The maintainer confirms
working photo use and QR sharing with the compatible LAN service716104.
This source release is not an AppStore publication or public TestFlight invitation.
See [current release notes](../releases/ios-v1.0.0-build19.md).

There is no product demo or manual frame-address/password form. Saved access
is protected by FaceID or the iPhone passcode. Open **Réglages → Partager le
cadre → Partager l’accès** to invite another iPhone; all authorized photo members
may delegate PHOTO access on the compatible LAN service. Build19 reconnects
on foreground activation after local authentication without a second retry tap.

## Run the delivered source candidate

Start from the candidate tag, not the older executable implementation retained on main:

```sh
git clone --branch ios-v1.0.0-build19 https://github.com/mehdi7129/inky-studio.git
cd inky-studio
```

The frozen iPhone-only branch is also available at release/ios-1.0.0-build19.
Use the current notes here rather than its historical delivery paragraph.


Open `InkyStudio.xcodeproj`, choose InkyStudio and an iPhone Simulator or device. A fresh checkout needs the local TLS binary artifact:

```bash
# Requires Xcode, CMake and Python 3.12+; downloads hash-verified upstream source.
scripts/build-mbedtls-apple.sh

# Regenerate after adding/removing source files.
xcodegen generate --spec ios/project.yml

xcodebuild build -project ios/InkyStudio.xcodeproj -scheme InkyStudio \
  -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO
```

Scan the frame's supported LAN login QR or an owner's PHOTO invitation from another iPhone. Keep iPhone and frame on the same Wi-Fi and accept the iOS local-network prompt. The current LAN QR assumes that the frame already has a working network. Invitation endpoints require the matching backend implementation and a previously trusted HTTPS identity on the owner's iPhone; they do not upgrade an unpinned HTTP cookie. Offline first-boot association remains a separate InkyOS contract being integrated. Unsupported QRs must be rejected without replacing an existing frame or secret.

## Features

- **Cadre:** current photo, previous/next display commands, schedule and queue summary.
- **File:** add/reorder/remove photos, including accessible reorder actions.
- **Historique:** dates, pagination, requeue original PNG bytes and remove history.
- **Réglages:** schedule, saturation, device information, Pi release check/update, associated-frame Wi-Fi configuration, help, local lock and forget.
- Native Photos picker/camera, HEIC/JPEG/PNG, EXIF orientation, crop/pan/zoom/reset and exact panel dimensions. Output is SDR/sRGB PNG without private source metadata; the Pi owns quantization. Camera captures are not automatically saved to Photos.
- Rounded Bento UI, native light/dark appearance and Dynamic Type. No demo, example-photo button, biometric preference or manual frame password form.
- PHOTO owners and permitted LAN photo members can create an invitation QR valid for at most five minutes. Only owner-authorized sessions can manage/revoke other devices. Media iPhones can manage photos and their schedule, but cannot change saturation, update the frame, configure Wi-Fi or administer access. A PHOTO credential is separate from Bluetooth ownership.
- Foreground WebSocket updates with bounded reconnect/backoff and polling recovery. Pending display confirmation is not a confirmed successful display; photo/queue state remains authoritative on the server.

## Local unlock and migration

Local unlock is separate from the Pi session. Face ID or the **system iPhone passcode** is required; the app never collects that passcode in a custom field. An iPhone passcode must be configured. New frame credentials use Keychain `WhenPasscodeSetThisDeviceOnly` with `.userPresence`, allowing biometrics or the device passcode. The app never receives biometric data. Legacy `biometryCurrentSet` items need authenticated migration; an invalidated item cannot retroactively be recovered using a different ACL.

After the first successful QR association, the credential is saved under that protection. A failed save leaves the new association incomplete and prevents mutations until storage succeeds; retrying storage does not replay network login. Cancelled local authentication leaves the app locked. A background lock preserves a live Pi session instead of logging out. Content and network actions require the local unlocked state; no prompt or login is added to each photo request. Inactive system-authentication transitions must not cancel their own unlock attempt. A scene-window cover also shields presented photo surfaces while inactive, in addition to the root and native camera covers.

Cookies remain private and in memory, isolated per origin/client and shared by JSON/PNG/WebSocket requests. The Pi invalidates sessions when its process restarts. **An old session with no saved credential can be locally locked/unlocked while still alive, but cannot be made durable by recovering a password from its opaque cookie.** If v11 was closed, or an app update terminated it after credential storage was skipped, its RAM cookie/password is already gone. Individual owner enrollment can only use a live legacy cookie over independently pinned HTTPS; this candidate cannot reconstruct a lost secret or copy an HTTP cookie into a different HTTPS client. Voluntary LAN recovery authenticates locally and validates a separate QR candidate before replacing the old connection; cancelling keeps the previous cookie, locator and protected credential. An adopted frame keeps its HTTPS pin: leaving that association requires fresh local authentication and an explicit, account-scoped forget confirmation, not an HTTP downgrade.

Individual device credentials are generated and saved under protected Keychain access before enrollment or invitation claim. Requests retain their exact identifiers for an idempotent retry; the recipient keeps the invitation token in RAM, while an issuer's pending invitation operation may retain its token briefly in protected Keychain storage. Invitation payloads must never enter logs, UserDefaults or navigation URLs. A canonical invitation address may differ from the owner's current address only after the pinned frame's response confirms the exact same UUID and SPKI. It is encoded in the QR; owner credentials and cookies are never forwarded to that address. Expiration and single-use enforcement are authoritative on the backend. An expired or revoked device session must not fall back to a legacy password or Bluetooth owner credential.

The existing LAN QR uses private-IPv4 HTTP:8000 and carries a frame password. It has no frame-ID/SPKI trust anchor and must not be treated as a pinned identity or copied as an invitation. Adopted frames retain the separate HTTPS pin/owner path with no silent fallback to HTTP. TLS checks are never bypassed and cross-origin redirects must not forward cookies/credentials. See [Bluetooth integration](https://github.com/mehdi7129/inky-studio/blob/release/ios-1.0.0-build19/docs/ios/BLUETOOTH-INTEGRATION.md).

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

See [distribution](DISTRIBUTION.md) for a separately authorized archive/sign/upload and [validation](VALIDATION.md) for the historical physical qualification boundaries.

## Architecture and references

`Core/` owns wire types and the isolated network client; `Auth/` wraps local unlock and protected Keychain access; `App/AppStore.swift` owns frame/session state; `UI/` owns tabs and connection views; `Photos/` owns import and crop. `Provisioning/` owns the distinct Bluetooth adoption/owner protocol.

Apple: [deviceOwnerAuthentication](https://developer.apple.com/documentation/localauthentication/lapolicy/deviceownerauthentication), [userPresence](https://developer.apple.com/documentation/security/secaccesscontrolcreateflags/userpresence), [Keychain local authentication](https://developer.apple.com/documentation/localauthentication/accessing-keychain-items-with-face-id-or-touch-id), [local network privacy](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy).
