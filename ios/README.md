# Inky Studio for iPhone

Native SwiftUI companion for Inky Studio v0.4.2+. Requires iOS 18 or newer. Photo transfer requires a Raspberry reachable on the same local network; the offline demo needs no frame. There is no cloud account. The local `InkyTLS` Swift package embeds pinned Mbed TLS 4.1.1 for secure Bluetooth provisioning. Password changes and Bluetooth require a compatible updated server; normal photo workflows remain compatible with v0.4.2.

The available beta is build 3. Build 4 contains Bluetooth but awaits export compliance; source candidate build 5 also includes the demo and connection guide. Source/build success does not establish TestFlight availability. See [delivery status](../docs/ios/TESTFLIGHT-DELIVERY.md).

## Run

Open `InkyStudio.xcodeproj`, select the **InkyStudio** scheme and an iPhone simulator or physical iPhone, then Run. The checked-in project is ready to build; XcodeGen is only needed when adding source files or changing `project.yml`.

```bash
# A fresh checkout needs the local TLS binary artifact. Requires Xcode, CMake
# and Python 3.12+; downloads the hash-verified pinned upstream source.
scripts/build-mbedtls-apple.sh

# From the repository root, after structural project changes:
xcodegen generate --spec ios/project.yml

xcodebuild -project ios/InkyStudio.xcodeproj -scheme InkyStudio \
  -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
```

Enter the Raspberry hostname (for example `inkyold.local:8000`) or its IP address and the existing frame password. An omitted HTTP port defaults to 8000. Accept the iOS local network prompt. Bonjour discovery is not required or implemented.

## Features

- **Cadre:** current photo, schedule, queue summary, previous/next physical display commands.
- **File:** add photos, reorder with drag handles or accessible context actions, remove entries.
- **Historique:** dates, paginated history, requeue original PNG bytes, delete an entry or clear history.
- **Réglages:** daily/interval/manual schedule, whole-hour Pi-local schedule, saturation, optional biometrics, device information, Pi release check/update, logout and forget frame.
- Rounded Bento interface, automatic system light/dark appearance, portrait only, no technical filenames in photo cards.
- Native camera capture or Photos picker, HEIC/JPEG/PNG decoding, EXIF orientation, pan/pinch crop, zoom/reset, exact panel dimensions, SDR/sRGB PNG without private source metadata. Camera permission is requested on use; captures are not automatically saved to Photos. The Pi alone handles palette quantization.
- Authenticated password change when the server advertises support, renewed session and updated biometric credential. A lost response requires an explicit reconnect instead of repeating the mutation.
- Foreground WebSocket updates, reconnect with capped backoff, state refresh after return, independent polling to recover missed events, readable errors and offline state.
- **Explorer la démo:** the same four tabs with temporary local illustrations, crop/import, queue/history, settings, reset and exit; no connection to a Raspberry and no change to real credentials.
- **Préparer mon cadre:** an in-app first-connection guide, also available in Settings. [Demo behavior and review walkthrough](../docs/ios/DEMO-AND-ONBOARDING.md).

## Credentials and transport

First pairing uses the existing Pi password. Face ID or Touch ID is opt-in. The saved password is a Keychain item protected by `biometryCurrentSet` and `WhenPasscodeSetThisDeviceOnly`; changes to enrolled biometrics invalidate access. The app never receives biometric data. Password fallback is always available.

Only the frame address and biometric preference are stored in UserDefaults. Cookies are private, in memory and isolated per origin/client, shared by JSON, PNG and WebSocket requests. Relaunching the app requires login (Face ID when enabled). Logout keeps the optional saved credential; disabling biometrics or forgetting the frame removes it. No session is shared with Safari. The Pi invalidates sessions when it restarts.

The default Pi uses HTTP on the local network. `NSAllowsLocalNetworking` permits local origins; public HTTP hosts are not exempted from ATS, and TLS certificate checks are never bypassed. Cross-origin redirects cannot forward passwords or cookies. Do not expose the Pi's HTTP service directly on the internet.

The source includes secure Bluetooth Wi-Fi provisioning, initially associated
through the frame's physical QR. After association, the app verifies the frame's
identity for HTTPS and does not silently fall back to HTTP. The candidate still
needs physical iPhone QR adoption and Wi-Fi commit/rollback qualification;
Simulator and Mac/Pi bench results do not establish those outcomes. See
[Bluetooth integration](../docs/ios/BLUETOOTH-INTEGRATION.md).

The earlier [Mac/Pi diagnostic bench](../docs/ios/BLUETOOTH-BENCH.md) validates
transport only and must never carry Wi-Fi or frame credentials. It is distinct
from the authenticated provisioning implementation.

## Tests

The fixture only listens on loopback and does not touch a real Raspberry. It uses Python's standard library and generated sample PNGs. UI tests reset fixture data before each case, so disable test parallelization.

```bash
python3 ios/scripts/mock-server.py
# In another terminal:
python3 ios/scripts/smoke-api.py
# Boot the test simulator and seed a generated photo before the PhotosPicker UI test:
# xcrun simctl boot <SIMULATOR_UDID>
# python3 ios/scripts/seed-simulator-photo.py <SIMULATOR_UDID>
xcodebuild -project ios/InkyStudio.xcodeproj -scheme InkyStudio \
  -destination 'platform=iOS Simulator,name=iPhone 16,OS=18.5' \
  -parallel-testing-enabled NO CODE_SIGNING_ALLOWED=YES CODE_SIGN_IDENTITY=- test
```

Simulator tests use ad-hoc signing so Keychain entitlements are present; unsigned simulator apps cannot validate biometric storage. Debug-only UI-test arguments reset app preferences and supply a fixture address. There is no authentication bypass in the app. Unit tests cover the API wire contract, cookie isolation, URL validation, errors, crop geometry, HEIC/orientation, output dimensions and metadata removal. GitHub Actions also builds the iPhone Release configuration.

### Optional simulated Face ID journey (Xcode 27)

Start the fixture with `python3 ios/scripts/mock-server.py --biometric-device <BOOTED_SIMULATOR_UDID>` instead of the plain fixture. It verifies that the target is a simulator, enables simulated enrollment, and provides a loopback-only test endpoint to emit a biometric match using Apple's public `devicectl` commands. Run the UI tests on that same simulator, with ad-hoc signing enabled. The biometric case skips when this mode is absent; the normal CI suite uses Xcode 16.4.

This exercises the actual app Keychain path and password fallback. It does not replace physical-device verification.

On 2026-09-27, the build 5 source passed this journey on an isolated iPhone 18 Pro Max / iOS 27 Simulator: opt-in, protected storage, biometric match, reconnect, password fallback and disable. The test dismisses the iOS 27 password-save sheet with a bounded retry and checks that it actually closes. Evidence is retained locally under ignored `build/ios/demo-onboarding/FaceIDBuild5Retry.xcresult`.

## Device and TestFlight delivery

See [DISTRIBUTION.md](../docs/ios/DISTRIBUTION.md) for signing, archive/export, device installation and TestFlight steps. See [VALIDATION.md](../docs/ios/VALIDATION.md) for evidence and remaining physical-device checks.

## Architecture

`Core/` contains Codable wire types and the isolated network client. `Auth/` wraps biometric Keychain access. `App/AppStore.swift` owns the authenticated session and visible state. `UI/` contains the four tabs and pairing flow. `Photos/` owns temporary file import, ImageIO conversion and crop geometry.

Apple references: [LocalAuthentication](https://developer.apple.com/documentation/localauthentication), [Keychain biometric access](https://developer.apple.com/documentation/localauthentication/accessing-keychain-items-with-face-id-or-touch-id), [local network privacy](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy), [NSAllowsLocalNetworking](https://developer.apple.com/documentation/bundleresources/information-property-list/nsapptransportsecurity/nsallowslocalnetworking), [PhotosPicker](https://developer.apple.com/documentation/photosui/photospicker).
