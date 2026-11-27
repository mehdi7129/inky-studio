# Inky Studio for iPhone

Native SwiftUI companion for Inky Studio, iOS 18+. Photo transfer requires a Raspberry reachable on the same local network. There is no cloud account. `InkyTLS` embeds pinned Mbed TLS 4.1.1 for Bluetooth provisioning.

## Source releases

Build **1.0.1 (20)** is the current GitHub source prerelease. See the [release notes](../docs/releases/ios-v1.0.1-build20.md) and the [build 19 distribution record](../docs/releases/ios-v1.0.0-build19.md).
In a fresh checkout, use the release tag to reproduce that source.

## Run

Open `ios/InkyStudio.xcodeproj` and choose the InkyStudio scheme. Run these commands from the repository root to prepare the pinned TLS dependency and build for Simulator:

```bash
# Requires Xcode, CMake and Python 3.12+; downloads hash-verified upstream source.
scripts/build-mbedtls-apple.sh

xcodebuild build -project ios/InkyStudio.xcodeproj -scheme InkyStudio \
  -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO
```

Keep the phone and frame on the same LAN. Allow camera and local network access,
then scan the frame QR or a PHOTO invitation. Build 20 uses the iPhone language
automatically among its 11 localizations.

For a physical device or a fork, set your own signing team and unique bundle ID
in the InkyStudio target. Keep `ios/project.yml` in sync if you regenerate the
project with XcodeGen. Use your own app record, version and unused build number
when distributing through your Apple developer account. Keep the [MIT license](../LICENSE) and
the [third-party notices](InkyStudio/Resources/ThirdPartyNotices.txt). For a new
client, see the [PHOTO API](../docs/PHOTO-API.md).

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

Cookies remain in memory and are isolated by connection. A saved device credential
opens a new session after a frame restart. If the saved locator is unavailable,
a known alternate address or local hostname must confirm the same frame UUID
and TLS key before receiving that credential. An expired or revoked device
cannot fall back to a legacy password.

For a password-based frame QR, an anonymous nonce challenge binds the frame UUID
and TLS key to the scanned secret. The password is sent only to the verified
HTTPS endpoint. A frame with an unsupported proof prompts for a software update.
Existing PHOTO invitation QRs already carry the frame identity and TLS pin.

After an interrupted upload, reopen the import sheet to resume or discard its
protected draft. Resume is an explicit action and stays bound to the selected
frame and device. Full receipt lookup needs PHOTO service 0.5.0rc5.

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
