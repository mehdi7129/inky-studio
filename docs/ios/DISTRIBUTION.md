# iPhone and TestFlight distribution

The native app has an independent version (`1.0.0`, source candidate build `6`; delivered beta `3`). As checked in App Store Connect on 1 October 2026, builds 4 and 5 are uploaded, internal-only and awaiting export compliance. Build 5 adds the offline demo and first-connection guide; its delivery checkpoints are tracked in [PR #12](https://github.com/mehdi7129/inky-studio/pull/12). Build 6 prepares a candidate eligible for both TestFlight and the public App Store, with a corrected demo UI regression test. A source version is not proof of distribution. It does not change the Raspberry release version. Bundle ID: `fr.mehdiguiard.inkystudio`. The project currently uses Mehdi's signing team `X524H8XA4L`; another developer must select their own team and bundle ID.

## Personal iPhone

Connect and unlock the iPhone, trust the Mac, and enable Developer Mode if iOS requests it. Open `ios/InkyStudio.xcodeproj`, select the connected phone and run the **InkyStudio** scheme. Automatic signing handles the development profile.

For a signed archive and development export, from the repository root:

```bash
xcodebuild -project ios/InkyStudio.xcodeproj -scheme InkyStudio \
  -destination 'generic/platform=iOS' -archivePath build/InkyStudio.xcarchive \
  -allowProvisioningUpdates archive
xcodebuild -exportArchive -archivePath build/InkyStudio.xcarchive \
  -exportOptionsPlist ios/ExportOptions-Development.plist \
  -exportPath build/development -allowProvisioningUpdates
```

`xcrun devicectl list devices` shows reachable devices. A development `.app` can be installed with `xcrun devicectl device install app --device <UDID> <APP_PATH>`. The device must be registered in the provisioning profile; Xcode can register the connected device when automatically signing.

## TestFlight

Export a distribution-signed IPA with:

```bash
xcodebuild -exportArchive -archivePath build/InkyStudio.xcarchive \
  -exportOptionsPlist ios/ExportOptions-AppStore.plist \
  -exportPath build/appstore -allowProvisioningUpdates
```

Create the **Inky Studio** app record in App Store Connect with the bundle ID above and French as the primary language, if it does not already exist. Upload the final archive via Xcode Organizer → Distribute App → App Store Connect, or the exported IPA through Transporter. Wait for Apple's processing before adding the build to an internal TestFlight group. External testing may require Beta App Review. No Apple API keys, passwords or provisioning secrets belong in the repository.

The app requires a local Inky Studio frame. Beta description: **« Gérez les photos de votre cadre Inky depuis votre iPhone : import, cadrage, file d’attente, historique et programmation. Connectez votre iPhone au même Wi-Fi que le Raspberry. »**

Testing notes: confirm local network permission, first password login, Face ID opt-in, logout and biometric login, password fallback, HEIC import/crop/upload, next/previous refresh and background/reconnect. The app offers **Explorer la démo** without hardware or credentials, followed by **Préparer mon cadre** for real setup. This local demo does not simulate physical Bluetooth, Face ID, camera hardware or e-ink refresh; there is no remotely reachable demonstration server. See [the review walkthrough](DEMO-AND-ONBOARDING.md).

The checked-in App Store export now sets `testFlightInternalTestingOnly=false`; a normal distribution upload can be used for TestFlight and later App Store submission. Keep manual group assignment and manual public release. Normal export eligibility does not resolve export compliance, distribute the build to testers or submit the app for review. Complete the required encryption documentation before assigning testers, and qualify the real iPhone/frame setup before public submission.

## Privacy and signing

There is no analytics, advertising, tracking or developer-controlled cloud service. Selected photos are sent only to the user-configured frame. Source photo metadata is removed from exported PNGs. The included privacy manifest declares app-local UserDefaults use (`CA92.1`). Delivered build 3 uses Apple's built-in encryption. The Bluetooth candidate additionally embeds Mbed TLS. Until Apple approves the documents and supplies a compliance code, both automatic export-compliance keys are absent and the build uses App Store Connect's manual questionnaire. This declares no exemption: answer standard bundled encryption outside the Apple OS and France availability accurately. Apple documents this [manual questionnaire path](https://developer.apple.com/documentation/bundleresources/information-property-list/itsappusesnonexemptencryption); supplying `true` without an approved code caused an actual build 6 upload rejection. The questionnaire and required documentation must be completed before distribution; see [encryption inventory](ENCRYPTION-INVENTORY.md).

Archive/export success proves the package can be signed. It does not prove App Store Connect upload, Apple processing, TestFlight availability or physical Face ID success; record those separately in the validation log.

## Delivered beta and publication roadmap

The private TestFlight build **1.0.0 (3)** is processed and assigned to Mehdi's
internal group. See [delivery evidence](TESTFLIGHT-DELIVERY.md) and the
[public-release, BLE travel and remote-access plan](APP-STORE-PLAN.md).
The public app has not been submitted for review. Support and privacy pages are
served at [inky-studio.netlify.app](https://inky-studio.netlify.app).
