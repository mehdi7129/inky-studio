# Private TestFlight delivery

Date: **2026-09-27**. Distribution was requested by Mehdi for a physical iPhone
test before preparing a public App Store release.

| Checkpoint | Verified result |
|---|---|
| App Store Connect record | Inky Studio, app ID `6816637620`, French primary language |
| Bundle / team | `fr.mehdiguiard.inkystudio` / `X524H8XA4L` |
| Binary | **1.0.0 (2)**, iPhone, iOS 18+, built using Xcode 27 / iOS 27 SDK |
| Source | `2cc692e71be9f3fc79a569c096520dee2230daf5` |
| Upload | Standard App Store Connect distribution; succeeded at **09:34:33 UTC** |
| Apple processing | App Store Connect displayed **Terminé**; no processing warning or missing-compliance action |
| TestFlight group | **Mehdi — test iPhone**, internal, automatic distribution disabled |
| Build assignment | Two builds assigned; one tester, Mehdi, marked **Invité** |
| Test information | French beta description, feedback address and build-specific physical-device checklist saved |
| Hardware installation | Mehdi reports the app works on his iPhone; the subsequent UI/camera changes need a new beta test |
| Public App Store | Not submitted or released; no external/public beta link created |

[Open TestFlight](https://appstoreconnect.apple.com/teams/03da9ef5-608a-40ef-9367-b987b26ea06d/apps/6816637620/testflight/ios).
The overview's **Prêt à soumettre** state concerns the next submission stage;
the build is already assigned to the internal group. Invitation receipt and
installation on the iPhone are separate from server-side delivery.

## First device test

1. Open Apple's TestFlight invitation on the iPhone and install **Inky Studio
   1.0.0 (2)**. Use iOS 18 or later.
2. Connect to the home network shared with the Raspberry and allow local-network
   access. Enter the real frame's address and existing password, not the local
   simulator fixture address or password.
3. Validate first connection, real Face ID and password fallback, then a selected
   HEIC photo through crop, upload and physical e-ink refresh.
4. Check queue/history, settings and foreground/network recovery. Report steps,
   expected/actual results and non-sensitive screenshots through TestFlight.

Bluetooth Wi-Fi provisioning and remote family access are planned features;
they are not present in this build. See [APP-STORE-PLAN.md](APP-STORE-PLAN.md).

## Evidence retained locally

- Archive: `build/ios/archives/InkyStudio-1.0.0-2.xcarchive`, including its successful Apple
  distribution receipt.
- Upload log: `build/ios/app-store-evidence/build2-upload.log` (`EXPORT SUCCEEDED`).
- Screenshot: ignored `build/ios/app-store-evidence/testflight-build-2.png`.
- Signed packages and checksums: ignored `build/ios/BUILD-INFO.md`.
- Automated validation: [VALIDATION.md](VALIDATION.md).

No Apple credentials, tokens or frame passwords are stored in the repository.

Build 1 was delivered first at 09:17:39 UTC from `cb198e6`. Build 2 fixes only
the app icon and increments the build number; the native workflows are unchanged.
Both signed archives are retained under ignored `build/ios/archives/`.

Public app documentation is live at [inky-studio.netlify.app](https://inky-studio.netlify.app),
with [support](https://inky-studio.netlify.app/support.html) and
[privacy](https://inky-studio.netlify.app/confidentialite.html).

## Update: build 3 — rounded design and camera

**1.0.0 (3)**, source `9bd24bd`, was uploaded successfully at **11:24:45 UTC**
on 2026-09-27. Apple processing is **Terminé**. The build is assigned to the
existing **Mehdi — test iPhone** internal group, with one tester; French
build-specific testing notes are saved. No public or external distribution.

This beta preserves the original rounded layout, removes photo filenames, fixes
the empty title area, follows system appearance, stays in portrait and adds the
camera/photo-library choice plus the approved icon A. Physical camera capture
and this build's iPhone acceptance remain to be tested.

Password personalization is present but hidden with the currently deployed
v0.4.2 server; the matching backend and installed CLI must be deployed separately.
BLE Wi-Fi provisioning is not in this beta.

- [Build 3 in App Store Connect](https://appstoreconnect.apple.com/teams/03da9ef5-608a-40ef-9367-b987b26ea06d/apps/6816637620/testflight/ios/ac86cdc7-736b-4061-a940-58a290d41b2d)
- [Detailed tests and screenshots](reviews/2026-09-27-refinement-validation.md)
- Archive: ignored `build/ios/archives/InkyStudio-1.0.0-3.xcarchive`.
- Upload/export logs, IPA and screenshot: ignored `build/ios/app-store-evidence/build3/`.
- Exported IPA SHA-256: `09b3b5806b371a43c4df11897f8220a6c5a5f195399c294375bb08fba4b526f4`.
