# Inky Studio for iPhone

Native SwiftUI companion for Inky Studio v0.4.2+. Requires iOS 18 or newer and a Raspberry reachable on the same Wi-Fi network. No third-party Swift dependencies or cloud account. The optional password-change feature requires a compatible updated server; normal photo workflows remain compatible with v0.4.2.

## Run

Open `InkyStudio.xcodeproj`, select the **InkyStudio** scheme and an iPhone simulator or physical iPhone, then Run. The checked-in project is ready to build; XcodeGen is only needed when adding source files or changing `project.yml`.

```bash
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

## Credentials and transport

First pairing uses the existing Pi password. Face ID or Touch ID is opt-in. The saved password is a Keychain item protected by `biometryCurrentSet` and `WhenPasscodeSetThisDeviceOnly`; changes to enrolled biometrics invalidate access. The app never receives biometric data. Password fallback is always available.

Only the frame address and biometric preference are stored in UserDefaults. Cookies are private, in memory and isolated per origin/client, shared by JSON, PNG and WebSocket requests. Relaunching the app requires login (Face ID when enabled). Logout keeps the optional saved credential; disabling biometrics or forgetting the frame removes it. No session is shared with Safari. The Pi invalidates sessions when it restarts.

The default Pi uses HTTP on the local network. `NSAllowsLocalNetworking` permits local origins; public HTTP hosts are not exempted from ATS, and TLS certificate checks are never bypassed. Cross-origin redirects cannot forward passwords or cookies. Do not expose the Pi's HTTP service directly on the internet.

Bluetooth Wi-Fi provisioning is not yet integrated into the app. The independent
[Mac/Pi diagnostic bench](../docs/ios/BLUETOOTH-BENCH.md) validates transport only;
it must never carry Wi-Fi or frame credentials.

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

## Device and TestFlight delivery

See [DISTRIBUTION.md](../docs/ios/DISTRIBUTION.md) for signing, archive/export, device installation and TestFlight steps. See [VALIDATION.md](../docs/ios/VALIDATION.md) for evidence and remaining physical-device checks.

## Architecture

`Core/` contains Codable wire types and the isolated network client. `Auth/` wraps biometric Keychain access. `App/AppStore.swift` owns the authenticated session and visible state. `UI/` contains the four tabs and pairing flow. `Photos/` owns temporary file import, ImageIO conversion and crop geometry.

Apple references: [LocalAuthentication](https://developer.apple.com/documentation/localauthentication), [Keychain biometric access](https://developer.apple.com/documentation/localauthentication/accessing-keychain-items-with-face-id-or-touch-id), [local network privacy](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy), [NSAllowsLocalNetworking](https://developer.apple.com/documentation/bundleresources/information-property-list/nsapptransportsecurity/nsallowslocalnetworking), [PhotosPicker](https://developer.apple.com/documentation/photosui/photospicker).
