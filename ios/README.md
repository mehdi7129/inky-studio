# Inky Studio for iPhone

Native SwiftUI app for an Inky photo frame on the same local network. Requires iOS 18 or newer. Photos stay between the iPhone and the frame; no developer-operated cloud account is required.

## Source branches and beta status

As of **23 October 2026**:

| Component | Reference | Verified status |
|---|---|---|
| Internal iPhone beta | **1.0.0 (17)** | Uploaded, validated by Apple and available in the existing internal TestFlight group |
| iPhone beta source | [release/ios-1.0.0-build17](https://github.com/mehdi7129/inky-studio/tree/release/ios-1.0.0-build17) | Frozen source `3930573`; separate from `main` |
| Current frame installation | LAN backend `b75bf1e7` | Build 16 was reported working on the physical installation |
| Photo-sharing service | [release/backend-lan-photo-sharing-20261023](https://github.com/mehdi7129/inky-studio/tree/release/backend-lan-photo-sharing-20261023) | Source `716104b1`, tested and packaged; **SD installation still pending** |

`main` retains the earlier password/HTTP implementation. Building `main` does not reproduce the delivered beta 17. Use the dedicated iOS source branch for that app, and the dedicated backend branch for the matching LAN service. Neither source publication nor TestFlight availability proves installation on the frame.

See the [ecosystem checkpoint](../docs/ECOSYSTEM.md) for the roles of InkyOS, inkyImager and Studio. TestFlight is internal; there is no public App Store release or public beta invitation link at this checkpoint.

## Current iPhone flow

1. Prepare and configure the SD with [inkyImager](https://github.com/mehdi7129/inkyImager), using the image provided by [InkyOS](https://github.com/mehdi7129/inkyOS).
2. Join the same Wi-Fi network as the frame and allow Inky Studio's local-network access.
3. Open **Scanner un QR code** and scan the frame's QR or an invitation displayed by another authorized iPhone.
4. Confirm Face ID, Touch ID or the iPhone passcode. The app retains a distinct device credential for later reopening.
5. Import, crop and send a photo, then manage its queue, history and daily, interval or manual schedule.

Build 17 removes only the **Accès protégé** card and manual **Verrouiller l’app** action from Settings. Local authentication when opening the app remains in place.

### Sharing from an iPhone

After the service has been updated to the LAN sharing backend, open **Réglages → Partager l’accès → Afficher un QR d’accès**. The other iPhone scans it from Inky Studio's home screen and receives its own photo access. Both phones must be able to reach the same frame on the local network.

An invitation expires after five minutes, is usable once, and can be cancelled before use. An authorized photo member can invite another member when the authenticated service response includes `can_invite=true`. This does not grant Wi-Fi configuration, software-update or device-administration rights. A member can cancel its own invitation; it gains no authority over another device's invitations.

**The service update is still pending on the current SD.** Beta 17 remains compatible with the existing backend, but keeps member sharing unavailable when the capability is absent. Publishing the source or updating the iPhone alone does not enable that service capability.

## Credentials and transport

The current Imager/LAN flow uses HTTPS on port **8443**, with the frame identity and certificate pin bound to the scanned invitation. Device credentials and invitation drafts are stored in protected Keychain items. Cookies stay isolated per origin/client and are not shared with Safari. A frame restart requires a new session using the retained credential, rather than a new pairing QR.

The app never receives biometric data. A cancelled or failed association preserves the previously selected access until the new one is verified. Backgrounding locks private content and cancels pending admission.

The older password login and HTTP port **8000** belong to the legacy installation represented by `main`. They are not the connection or maintenance instructions for the Imager/LAN image. Do not expose either local service directly on the internet.

## Build the app

Open `ios/InkyStudio.xcodeproj`, select **InkyStudio**, then choose a Simulator or an iPhone. Select your own signing team and bundle ID for device builds.

The frozen project retains `CURRENT_PROJECT_VERSION=7`. The delivered TestFlight archive used the command-line override `CURRENT_PROJECT_VERSION=17`; the source branch records the code checkpoint, not that archive's signing state or default local build number. A local Run is not a reproduction of the signed distribution package. A future upload needs a fresh unused Apple build number, rather than reusing 17.

For the beta source branch, first prepare the TLS binary artifact as described in its [InkyTLS package guide](https://github.com/mehdi7129/inky-studio/blob/release/ios-1.0.0-build17/ios/Packages/InkyTLS/README.md). Signed app archives, local build caches, signing profiles and credentials are not part of this source publication. The dated release checks used Xcode 27 and the iOS 27 SDK, with iOS 18 as the deployment minimum.

XcodeGen is needed only after structural project changes:

```bash
xcodegen generate --spec ios/project.yml
xcodebuild -project ios/InkyStudio.xcodeproj -scheme InkyStudio -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
```

This unsigned Simulator command checks compilation only. Keychain tests require normal Simulator signing.

## Tests and qualification

The frozen beta 17 source passed **128 distinct iOS tests**: 95 AppStore tests, 22 photo-access client tests and 11 UI tests. Its signed archive/export passed **87 package checks**. These are dated release checks, not a claim that every repository test or every hardware configuration has been qualified.

The loopback fixture uses generated photos and never contacts a real frame. UI tests reset its state, so disable parallel execution:

```bash
python3 ios/scripts/mock-server.py
# In another terminal, using a booted Simulator:
xcodebuild -project ios/InkyStudio.xcodeproj -scheme InkyStudio -destination 'platform=iOS Simulator,id=<SIMULATOR_UDID>' -parallel-testing-enabled NO -collect-test-diagnostics never CODE_SIGNING_ALLOWED=YES CODE_SIGN_IDENTITY=- test
```

The PhotosPicker test also needs a generated image seeded with `ios/scripts/seed-simulator-photo.py`. Ad-hoc Simulator signing supplies Keychain entitlements; it does not prove physical Face ID or Keychain behavior. QR rendering/decoding, wire contracts and Simulator navigation do not replace the real two-iPhone → frame photo/reconnection test, which remains pending after SD maintenance.

## Distribution and history

The app and Raspberry service have independent version numbers. The [distribution guide](../docs/ios/DISTRIBUTION.md) and [delivery log](../docs/ios/TESTFLIGHT-DELIVERY.md) retain historical checkpoints; their top notices distinguish those from the current beta.

`Core/` contains validated wire types and network clients; `Auth/` owns local credential protection; `App/AppStore.swift` coordinates sessions; `UI/` contains screens and the QR handoff; `Photos/` handles temporary import and metadata-stripped PNG output.
