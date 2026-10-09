# iPhone and TestFlight distribution

Updated: **9 October 2026, 07:04 UTC**. The current internal TestFlight beta is
**1.0.0 (9)**, assigned to **Mehdi — test iPhone**, the existing internal group
with one tester. French testing notes are saved. Installation of build 9 is not
yet established; build 8 is the last version reported installed on the tester's
iPhone 15 Pro Max. See [delivery evidence](TESTFLIGHT-DELIVERY.md).

Build 9 includes the stability/accessibility corrections in
[PR #21](https://github.com/mehdi7129/inky-studio/pull/21), from clean source
`181edb2f89034bb0c411b145c95fe303f112b460`. Its signed Release archive and
distribution export succeeded, and all **76 package checks passed**. Upload
succeeded on 9 October at **06:46:08 UTC**. Apple processing completed without
missing-compliance information. Native CI is green on the same source:
**109 unit tests and 17 UI tests pass**, with one expected simulated Face ID
skip; iPhone Release also builds successfully. Group assignment was verified at
**07:04 UTC**. No branch has been merged and no public App Review submission
has been made.

The native app has an independent version and does not change the Raspberry
release version. Bundle ID: `fr.mehdiguiard.inkystudio`. The project currently
uses Mehdi's signing team `X524H8XA4L`; another developer must select their own
team and bundle ID. A source version is not proof of distribution.

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

The checked-in App Store export sets `testFlightInternalTestingOnly=false`; a normal distribution upload can be used for TestFlight and later App Store submission. Keep manual group assignment and manual public release. Normal export eligibility does not resolve export compliance, distribute the build to testers or submit the app for review. Build 9 has completed Apple processing with its approved compliance code recognized, passed native CI and been assigned to the intended internal group. Qualify the real iPhone/frame setup before public submission.

## Privacy and signing

There is no analytics, advertising, tracking or developer-controlled cloud service. Selected photos are sent only to the user-configured frame. Source photo metadata is removed from exported PNGs. The included privacy manifest declares app-local UserDefaults use (`CA92.1`). The Bluetooth implementation embeds Mbed TLS in addition to Apple's built-in encryption.

Apple approved the encryption documents on **8 October 2026**, and the approved
declaration is associated with build 8. The source [Info.plist](../../ios/InkyStudio/Resources/Info.plist)
now contains Apple's supplied `ITSEncryptionExportComplianceCode` and
`ITSAppUsesNonExemptEncryption=true` for future builds retaining the same
cryptographic characteristics. Reassess the declaration if those characteristics
change. This export approval is separate from public App Review and physical
Bluetooth qualification; see the [encryption inventory](ENCRYPTION-INVENTORY.md).

Archive/export success proves the package can be signed. It does not prove App Store Connect upload, Apple processing, TestFlight availability or physical Face ID success; record those separately in the validation log.

## Delivered beta and publication roadmap

The private TestFlight build **1.0.0 (9)** is assigned to Mehdi's internal group.
Its installation and physical acceptance remain to be checked on the iPhone.
Physical QR adoption and Wi-Fi commit/rollback still need device qualification. See
[delivery evidence](TESTFLIGHT-DELIVERY.md) and the
[public-release, BLE travel and remote-access plan](APP-STORE-PLAN.md).
The public app has not been submitted for review. Support and privacy pages are
served at [inky-studio.netlify.app](https://inky-studio.netlify.app).

## Historical delivery — build 8, 8 October 2026

Build **1.0.0 (8)**, from `15b5e536e791b4e23215e9c1b60103d14e0c8e13`
(Bento polish), was assigned after Apple approved export compliance. App Store
Connect reports **Installed, 1.0.0 (8)** on an **iPhone 15 Pro Max / iOS 27.0.1**,
dated 8 October. That telemetry does not establish functional hardware
qualification, and this earlier binary does not contain the build 9 corrections.

## Historical checkpoints — 27 September to 1 October 2026

- Build **1.0.0 (3)**, without Bluetooth, was delivered to the internal group on
  27 September. It used Apple's built-in encryption.
- On 1 October, builds **4** and **5** were uploaded, internal-only and awaiting
  export compliance. Build 5 added the offline demo and first-connection guide;
  its checkpoints are recorded in [PR #12](https://github.com/mehdi7129/inky-studio/pull/12).
- Build **6** prepared normal export eligibility for TestFlight and a later
  public App Store submission, with a corrected demo UI regression test.
  An upload with `ITSAppUsesNonExemptEncryption=true` but no approved code was
  rejected as **Invalid Export Compliance Code** on 1 October. The candidate
  then used App Store Connect's manual questionnaire with both automatic
  export-compliance keys absent, pending document approval. That absence did
  not declare an exemption. See the [dated encryption history](ENCRYPTION-INVENTORY.md).

These checkpoints describe the earlier delivery and compliance state. The
current build 9 delivery and approved source metadata are recorded above.
