# iPhone and TestFlight distribution

The native app has an independent version (`1.0.0`, build `1`). It does not change the Raspberry release version. Bundle ID: `fr.mehdiguiard.inkystudio`. The project currently uses Mehdi's signing team `X524H8XA4L`; another developer must select their own team and bundle ID.

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

Testing notes: confirm local network permission, first password login, Face ID opt-in, logout and biometric login, password fallback, HEIC import/crop/upload, next/previous refresh and background/reconnect. The app does not include a remotely reachable demonstration server for external reviewers.

## Privacy and signing

There is no analytics, advertising, tracking or developer-controlled cloud service. Selected photos are sent only to the user-configured frame. Source photo metadata is removed from exported PNGs. The included privacy manifest declares app-local UserDefaults use (`CA92.1`). The app uses Apple's built-in encryption and declares no non-exempt encryption.

Archive/export success proves the package can be signed. It does not prove App Store Connect upload, Apple processing, TestFlight availability or physical Face ID success; record those separately in the validation log.
