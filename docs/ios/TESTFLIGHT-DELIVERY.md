# Private TestFlight delivery

Date: **2026-09-27**. Distribution was requested by Mehdi for a physical iPhone
test before preparing a public App Store release.

## Current delivery status

- Available internal beta: **1.0.0 (3)**, without Bluetooth.
- Bluetooth build **1.0.0 (4)**: uploaded and processed, **Missing Compliance**,
  **zero assigned groups**. No new TestFlight update is available yet.
- Raspberry: candidate **0.5.0-rc.2**, source `ae61df1`, now deployed and checked.
  See [the server delivery](SERVER-BLUETOOTH-DELIVERY.md). Physical iPhone QR
  adoption and Wi-Fi commit/rollback remain unqualified; PR #11 stays draft.
- The private official-form draft has 49 populated fields; its XFA rendering
  is unverified. A separate five-page review companion passed visual QA.
  Neither document is signed or submitted, and neither is Apple approval.

## Historical delivery: build 2

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

## Historical build 2 device-test checklist

1. Open Apple's TestFlight invitation on the iPhone and install **Inky Studio
   1.0.0 (2)**. Use iOS 18 or later.
2. Connect to the home network shared with the Raspberry and allow local-network
   access. Enter the real frame's address and existing password, not the local
   simulator fixture address or password.
3. Validate first connection, real Face ID and password fallback, then a selected
   HEIC photo through crop, upload and physical e-ink refresh.
4. Check queue/history, settings and foreground/network recovery. Report steps,
   expected/actual results and non-sensitive screenshots through TestFlight.

Bluetooth Wi-Fi provisioning and remote family access were outside this build.
See [APP-STORE-PLAN.md](APP-STORE-PLAN.md) and the current build 4 status below.

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
camera/photo-library choice plus the approved icon A. Mehdi accepted the physical
iPhone test step on 2026-09-27 ("je valide le 1") and authorized continuation.
This is user acceptance, not an instrumented log of every physical camera/Face ID
scenario. PR #8 was merged as `b31046d` after this acceptance.

Password personalization was introduced on the frame by server `0.5.0-rc.1`,
deployed after the CLI migration. Mehdi then personalized the password and confirmed both
successful reconnection and rejection of an incorrect password. See [server delivery](SERVER-CANDIDATE-DELIVERY.md).
BLE Wi-Fi provisioning is not in this beta.

- [Build 3 in App Store Connect](https://appstoreconnect.apple.com/teams/03da9ef5-608a-40ef-9367-b987b26ea06d/apps/6816637620/testflight/ios/ac86cdc7-736b-4061-a940-58a290d41b2d)
- [Detailed tests and screenshots](reviews/2026-09-27-refinement-validation.md)
- Archive: ignored `build/ios/archives/InkyStudio-1.0.0-3.xcarchive`.
- Upload/export logs, IPA and screenshot: ignored `build/ios/app-store-evidence/build3/`.
- Exported IPA SHA-256: `09b3b5806b371a43c4df11897f8220a6c5a5f195399c294375bb08fba4b526f4`.


## Bluetooth candidate build 4 — uploaded, not distributed

**1.0.0 (4)**, source `70148f5`, was uploaded successfully on 2026-09-27 at
**14:04:25 UTC**, with `testFlightInternalTestingOnly=true`. Apple processing
completed. This build has **Missing Compliance / Informations manquantes** and
no assigned group; build 3 remains the available beta. French testing notes are
saved for the candidate and updated in App Store Connect after the rc.2
deployment. The UI confirmed **Enregistré**; the notes now identify the installed
backend and the remaining iPhone/Wi-Fi tests. Screenshot retained privately:
`build/ios/app-store-evidence/build4/testflight-build4-backend-rc2.png`. This
metadata update does not resolve compliance or assign a tester group.

The actual build questionnaire was inspected: standard encryption embedded
outside Apple's OS, France **Yes**, requires approved export documents in the
app information section. There was no save action available at that point, only
the documentation link. The dialog was cancelled. No document, exemption,
reference number or declaration was submitted. See [the factual inventory](ENCRYPTION-INVENTORY.md).

A signed development export of the same archive also succeeded. It can be
installed from Xcode once the iPhone is connected, unlocked and has Developer
Mode enabled. Mehdi explicitly prefers TestFlight and Simulator checks; this
direct-install alternative is therefore not being pursued. The phone was still
unavailable at the last device check.
No physical iPhone Bluetooth adoption or actual Wi-Fi transition is claimed.

- [Build 4 in App Store Connect](https://appstoreconnect.apple.com/teams/03da9ef5-608a-40ef-9367-b987b26ea06d/apps/6816637620/testflight/ios/ffcfb92e-e664-4ffb-b7f2-b447c7f4e453)
- Signed archive: ignored `build/ios/archives/InkyStudio-1.0.0-4.xcarchive`.
- Archive/upload/development export logs, signed development IPA and screenshot:
  ignored `build/ios/app-store-evidence/build4/`.
- Bundle ID, build number 4, bundled third-party notices and code signature
  verified. The former automatic encryption exemption flag is absent.
- Before deployment, the network helper passed health and scan checks. The
  earlier candidate backend was tested privately with BlueZ and a forced mock
  display: [evidence](reviews/2026-09-27-bluetooth/pi-backend.json).
- The production service now runs **0.5.0-rc.2** from `ae61df1`. Both backend and
  iOS CI passed on that commit. Deployment checks cover HTTP, local HTTPS TLS
  1.3, required authentication, the detected display driver and correlated local
  BlueZ registration. They do not replace physical iPhone/radio/QR tests or a
  real Wi-Fi change. [Deployment report](SERVER-BLUETOOTH-DELIVERY.md).
