# iPhone publication plan

Status snapshot: **2026-09-27**. The path is **private TestFlight → real-device
acceptance → public readiness → final candidate → App Review → manual release**.
Public release remains a separate decision after Mehdi's hardware feedback.
Bluetooth setup is implemented in a candidate awaiting TestFlight compliance
and physical iPhone/Wi-Fi qualification. InkyOS and remote family access remain
separate workstreams.

## 1. Verified delivery and remaining gates

| Item | Current evidence |
|---|---|
| App | Native SwiftUI iPhone companion, iOS 18+, French UI; rounded bento, system light/dark appearance, portrait only and camera import in available build 3 |
| Identity | `fr.mehdiguiard.inkystudio`; App Store Connect app **6816637620** |
| Available beta | **1.0.0 (3)**, source **9bd24bd**, assigned to **Mehdi — test iPhone** with one internal tester; Mehdi accepted the physical iPhone test step. This is not exhaustive evidence for every journey below |
| Bluetooth binary | **1.0.0 (4)**, source **70148f5**, Xcode 27; uploaded **2026-09-27 14:04:25 UTC**, Apple processing complete, **Internal Only** |
| Build 4 distribution | **Missing Compliance / Informations manquantes**, **zero assigned groups**; no Bluetooth TestFlight update is available yet |
| Validation | Backend/TLS/GATT, Simulator and Mac–Pi radio checks passed within their documented scope. Backend and iOS CI are green for deployed source **ae61df1** and documentation commit **6f4eb30**. Real iPhone QR adoption and Wi-Fi commit/rollback remain open |
| Encryption paperwork | Technical annex and a private official XFA draft with 49 populated fields prepared; static review companion visually checked. XFA rendering remains unverified; no signature, submission or Apple approval |
| Public metadata | French description, promotional text, keywords, subtitle **Vos photos, sur votre cadre**, **Photo & Video** category, 2026 Mehdi Guiard copyright and manual release saved as a draft; no public candidate submitted |
| App Privacy | **No Data Collected** saved in draft from the current self-hosted data-flow audit; not yet published |
| EU trader status | App Store Connect already identifies this developer as a trader for the app; existing account declaration was not changed, details remain to verify before release |
| Website | **https://inky-studio.netlify.app** deployed on the existing free Netlify plan; home, support and privacy verified over HTTPS, mobile layout and local links checked |
| Support | Mehdi explicitly approved **mehdi071292@gmail.com** as the public contact |
| Hardware | Pi Zero 2 W Rev 1.0; server candidate **0.5.0-rc.2**, source **ae61df1**, deployed with active network helper. HTTP/HTTPS, authentication, driver detection and local BlueZ registration checked; no real Wi-Fi transition qualified |

Evidence: [TESTFLIGHT-DELIVERY.md](TESTFLIGHT-DELIVERY.md),
[SERVER-BLUETOOTH-DELIVERY.md](SERVER-BLUETOOTH-DELIVERY.md),
[BLUETOOTH-INTEGRATION.md](BLUETOOTH-INTEGRATION.md),
[ENCRYPTION-INVENTORY.md](ENCRYPTION-INVENTORY.md),
[form preparation](export/PREPARATION-FORMULAIRE.md), and
[the native README](../../ios/README.md). Earlier test results remain in
[VALIDATION.md](VALIDATION.md) and the
[Bluetooth qualification report](reviews/2026-09-27-bluetooth/README.md);
historical delivery statements there do not supersede the current reports above.
Preserve the archive, dSYMs, source SHA, IPA checksum and upload receipt outside
temporary storage. Simulator success is not physical-device acceptance.

## 2. Finish private TestFlight delivery

**Owner:** release engineer and Mehdi.

- Resolve the actual encryption-document gate for **1.0.0 (4)**. Review the
  private prefilled form, validate its rendering in a compatible XFA reader,
  complete the reserved administrative choices and obtain the required signed
  documents and Apple approval. The inherited prechecked combined formality is
  not a confirmed selection; no exemption or authorization reference is established.
  See [the preparation and remaining limits](export/PREPARATION-FORMULAIRE.md).
- Once compliance permits distribution, assign build 4 to **Mehdi — test
  iPhone** and verify the update appears, installs and launches on Mehdi's iPhone.
  Record the exact iPhone/iOS/build. Build 3 remains the available beta meanwhile.
- Keep the beta private; build 4 was deliberately uploaded **Internal Only**
  and cannot become the external/public candidate. A later public candidate needs
  an eligible upload and its own validation/compliance. The French build 4 notes
  already identify the deployed rc.2 backend and the outstanding physical tests.
- Internal testers must be eligible App Store Connect users. External testing
  requires its own beta information and applicable Beta App Review. Refresh the
  build before its 90-day expiry if testing continues. See Apple's
  [TestFlight workflow](https://developer.apple.com/help/app-store-connect/test-a-beta-version/testflight-overview/).

**Acceptance:** build 4 compliance is resolved, the internal group is assigned,
and Mehdi installs and opens it through TestFlight. Delivery enables the hardware
qualification below; it does not require those tests to have already passed.
Mehdi prefers TestFlight and Simulator checks, so the signed Xcode development
export is not the current delivery path. No external/public beta or App Store
availability is implied.

## 3. Real iPhone and frame acceptance

**Owner:** Mehdi performs device interactions; engineering records results and
fixes issues. Use identified test photos, preserve unrelated data, and restore
original schedule settings afterwards. Record app/iOS/server versions, panel
model/resolution, network and PASS/FAIL/NOT TESTED for each row.

| Journey | Checks and acceptance |
|---|---|
| Connection | Clean install; hostname and IP; denied/accepted local-network permission and Settings recovery; wrong/correct password. Clear errors, correct frame and bounded waits |
| Face ID | Opt in, logout/relaunch, real biometric success/cancel/failure, password fallback, disable, forget frame. Optional access works; credential removal and fallback remain reliable |
| Restricted biometrics | No enrollment/unavailable authentication and enrollment change on a designated device where practical. No lockout; preserve current Keychain protections |
| Native photos | Actual HEIC, including the previously failing image if Mehdi selects it; JPEG/PNG, EXIF orientation, large image, iCloud-backed selection. Correct output and useful errors without hangs |
| Camera and presentation | Capture/cancel and camera permission denial/recovery; portrait restriction, system light/dark changes and rounded layouts across tabs. Camera/Face ID hardware behavior is not established by Simulator fixtures |
| Crop → upload → display | Pan/pinch/reset/cancel; exact detected panel dimensions; stripped metadata; real next/previous refresh. Framing correct, Pi alone quantizes colors, no duplicate commands |
| Queue/history | Reorder/remove identified entries, requeue history, verify dates and agreement with the web UI. Persisted state matches across clients |
| Settings | Daily/interval/manual, whole-hour Pi-local schedule, saturation, save/reopen. Values persist and frame behavior matches |
| Lifecycle | Lock/unlock, background/foreground, terminate/relaunch. State resynchronizes and authentication is understandable |
| Fault recovery | Leave LAN/cellular-only, interrupt/recover Wi-Fi, expired session or safe Pi restart, invalid address, cancelled login. No endless spinner, stale success or replayed mutation |
| Concurrent changes | Change queue/settings in the web app while iPhone is open. State converges; late results cannot restore a signed-out session |
| Bluetooth Wi-Fi | Build 4 with rc.2: physical QR adoption, wrong Wi-Fi password, rollback, selected 2.4 GHz hotspot, pinned HTTPS confirmation and photo transfer. See section 10 for recovery cases |
| Pi update | Check version/release information. Actual update only in an agreed maintenance window with recovery, not as an incidental acceptance action |

Do not reset Mehdi's Face ID or restart/upgrade production hardware merely to
finish the checklist. Mark deferred cases and arrange a suitable test device or
maintenance slot. Report reproducible steps and non-sensitive screenshots through
TestFlight; never include frame passwords.

Mehdi has confirmed app-password personalization, successful reconnection and
rejection of an incorrect password. Preserve that evidence without marking the
remaining connection, camera, biometric or Bluetooth cases automatically passed.

**Acceptance:** connection, real Face ID/fallback, HEIC-to-frame, settings and
network/background recovery pass; no open crash, data-loss, authentication or
core-workflow blocker. Fixes receive a new build number, affected automated tests
and physical regression. Mehdi then decides to proceed with public readiness.

## 4. Public app readiness

### Reviewer access

The current Release app needs a private LAN frame. The Python loopback fixture and
Debug launch arguments do not provide App Review access.

**Recommended product work:** a visible **Explore demo** entry point using local,
licensed/generated sample content and the real native screens. Exercise crop,
queue/history and settings; label simulated refresh/update behavior. Keep demo
state separate, support reset/exit, retain normal real-frame authentication, and
keep any personal demo imports local/removable. Ship no real credentials or
household photos and do not expose the user's Pi to the internet.

A built-in demo is a recommendation, not a blanket Apple requirement. For hardware
environments that are difficult to reproduce, Apple describes preparing a demo
video or hardware in its [review preparation guidance](https://developer.apple.com/app-store/review/).
Agree the review arrangement where needed, explain limitations in Review Notes,
and provide requested resources. See also [review access and completeness](https://developer.apple.com/app-store/review/guidelines/).

**Deliverables:** Release-build walkthrough, a real iPhone/Pi refresh video, and
an agreed review path. If the demo approach is chosen, a fresh installation
outside the household must complete it without hidden flags, secrets or a Pi;
no demo action may mutate a connected real frame. Approval is not guaranteed.

### Onboarding and accessibility

- Explain separate Raspberry/Inky hardware, installed server/version, same LAN,
  finding the address/password, permission recovery and e-ink refresh latency.
  Distinguish first adoption, which currently requires an authenticated LAN
  session, from later Bluetooth Wi-Fi recovery by an already-adopted phone.
  Publish a verified hardware matrix; one 800×480 panel does not validate all
  Inky displays. Do not imply cellular remote access.
- **Support** and **Privacy** links are now implemented in source before login
  and in settings, using the existing rounded card and system colors. Their
  HTTPS destinations both returned 200. This source addition is newer than the
  uploaded build 4; it needs a future numbered beta/public candidate and must
  not be claimed as already delivered through TestFlight. The privacy manifest
  does not replace a public policy. Apple's
  [sections 1.5 and 5.1.1(i)](https://developer.apple.com/app-store/review/guidelines/)
  cover contact information and accessible privacy links.
- Validate VoiceOver, Dynamic Type through accessibility sizes, contrast, reduced
  motion, non-color status cues and touch targets. Provide usable alternatives to
  precise crop/reorder gestures. Test a small and large iPhone, portrait-only
  behavior and both system appearances. Confirm actual platform availability; do not claim untested iPad
  or Mac support. Advertise only verified accessibility features.

**Acceptance:** a new user understands prerequisites, can recover permissions,
find support/privacy and complete core tasks with VoiceOver and large text.

## 5. HTTPS bento microsite

Implementation/deployment is authorized on the existing **Netlify Free Legacy
plan ($0/month)**, using **https://inky-studio.netlify.app**. The three published routes were verified over HTTPS. No paid domain, hosting upgrade or application cloud
backend is included. Match the app's white/black bento style with subtle accents.

| Page | Deliverable and acceptance |
|---|---|
| Home `/` | Real screens, benefits, separate hardware/server requirements, local-network limitations and installation guidance. Responsive; no unsupported claim or broken download button |
| Support `/support.html` | Setup, address/password, permissions, Face ID fallback, HEIC/iCloud, e-ink delays, offline recovery and compatibility; working contact **mehdi071292@gmail.com** |
| Privacy `/confidentialite.html` | Developer/contact, device→Pi photo flow, local processing/metadata removal, Keychain, storage/deletion, support/diagnostic handling, hosting logs and effective date. Public HTTPS without login |

The current app has no advertising, tracking, analytics SDK or developer photo
cloud. Verify the final candidate still matches. Explain that forgetting the
frame removes iPhone connection/credential state, not Pi data. In v0.4.2, deleting
queue/history entries or clearing history **does not delete the PNG files**;
there is no photo-file deletion API exposed to the app. Do not promise complete
photo erasure from those actions. The Pi separately checks/downloads GitHub
releases. Describe actual Netlify logs and support-email retention accurately.

**Acceptance:** home/support/privacy load on mobile and desktop, links work from
the app and store draft, contact is reachable, and the policy matches the binary.
Do not request passwords or private images in public issue reports. Activate the
App Store download link only after public availability.

## 6. Listing and authentic screenshots

Use French as primary localization. Review the existing draft description,
promotional text, keywords, subtitle **Vos photos, sur votre cadre**, **Photo &
Video** category and copyright. Confirm rights to icon/sample photos and hardware references.
No implied manufacturer partnership. English metadata is optional; English app
UI is a separate choice and must not be claimed while the interface is French.

State iOS 18+, separate Raspberry/Inky equipment, installed Inky Studio server,
same-network operation and optional Face ID. Capture the final public UI on a
**6.9-inch iPhone**, preferably **1320×2868 portrait**: frame, crop, queue, history,
settings and biometric connection. Lead with useful functionality and use
non-personal content. Existing 1206×2622 screenshots are QA evidence, not the
principal 6.9-inch set. Apple accepts 1–10 JPEG/PNG assets without alpha; recheck
[current screenshot specifications](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/)
at upload. Localize artwork only for published localizations; video is optional.

**Acceptance:** all assets match the submitted build, pass size validation, contain
no personal data, and communicate hardware requirements before installation.

## 7. App Store declarations and owner decisions

| Area | Required verification / acceptance |
|---|---|
| App Privacy | Current draft says **No Data Collected**: selected photos go to the user's Pi, with no developer/SDK access or analytics. Re-audit final data flows, demo and diagnostics before publishing; policy, answers and manifest must agree |
| Privacy manifest | Recheck required-reason APIs. Current manifest declares local UserDefaults use, no tracking and no collected types; resolve any archive warnings |
| Age rating | Answer the current questionnaire based on actual features/content. Do not guess a final age or claim Kids Category |
| Encryption | Build 4 embeds Mbed TLS outside the OS; the former automatic `ITSAppUsesNonExemptEncryption=false` declaration is removed. Its actual France `Yes` questionnaire requires documents and Apple approval. Drafts are unsigned/unsubmitted; no exemption is established. Reconcile the final public candidate with [the inventory](ENCRYPTION-INVENTORY.md) |
| Countries / price | Mehdi confirms initial territories and free/paid model. No IAP/subscription exists. Paid distribution requires applicable agreements/tax/banking setup and revised scope |
| EU trader status | Existing account declaration identifies a trader. Confirm its accuracy and verify required public contact/identity details before EU publication; free does not imply non-trader. TestFlight-only testing is separate |
| Account / rights | Confirm seller identity, agreements, team, category, content licenses and available platforms |
| Review information | Reachable contact, hardware/dependency explanation, reproducible demo/video/hardware instructions. Private review credentials, if needed, stay in App Store Connect, never Git |

Use Apple's [privacy definitions](https://developer.apple.com/app-store/app-privacy-details/),
[age-rating definitions](https://developer.apple.com/help/app-store-connect/reference/app-information/age-ratings-values-and-definitions/),
[encryption documentation](https://developer.apple.com/help/app-store-connect/reference/app-information/export-compliance-documentation-for-encryption/),
and [EU trader requirements](https://developer.apple.com/help/app-store-connect/manage-compliance-information/manage-european-union-digital-services-act-trader-requirements/).
Unknown personal/commercial facts stay **TO CONFIRM**; engineering cannot choose
them on Mehdi's behalf. A future hosted demo/relay changes the privacy assessment.

## 8. Final candidate, review and manual release

1. Close readiness tasks and hardware blockers. Increment each binary's build
   number; keep 1.0.0 as the first public marketing version if appropriate.
2. Run automated regression, Release archive validation, link/privacy checks and
   physical smoke: login → Face ID → HEIC/crop → display → background/reconnect.
   Verify the selected review path. Preserve the exact source/archive/symbols.
3. Test that candidate privately before submission; do not silently substitute
   an untested binary. Attach it to the version with final assets/forms/notes.
4. Keep **manual release** selected. Submit only after Mehdi's public-release
   go-ahead. Explain that the Pi updater updates companion hardware software,
   not the iOS binary. Keep review resources live; respond with concrete evidence.
5. Rebuild/retest if review requires changes. After approval, verify the approved
   build, countries, price and URLs before the deliberate release action.
6. Verify the public listing and install the store build on an iPhone. Record the
   date, store URL, version/build and smoke result; enable the site's download CTA.

**Acceptance:** the physically tested, approved candidate is available in the
intended regions with accurate metadata and functioning support. Apple's review
and processing times are not committed ETAs.

## 9. Maintenance

Retain each release's archive, matching dSYMs/UUIDs, source SHA, IPA checksum,
toolchain and notes in durable private storage; temporary results and expiring CI
artifacts are insufficient. Verify symbolication. Start with TestFlight feedback
and available Apple crash reports; revisit privacy before adding diagnostics SDKs.

Check crashes/support daily in the first week, then regularly. Maintain links,
account access, iOS/Pi/panel compatibility and Apple requirements. Record app/server
versions without collecting unnecessary private content. For severe regressions,
stop further availability where appropriate and ship a tested correction; do not
assume installed apps can automatically roll back. Preserve Pi API/data
compatibility or document a migration before release.

## 10. Bluetooth candidate: finish physical Wi-Fi qualification

**Implemented in iOS 1.0.0 (4) and server 0.5.0-rc.2; not yet qualified end to
end on iPhone.** Build 3 has no Bluetooth flow. The backend is deployed, while
build 4 awaits the compliance gate described in section 2. Photos continue to
use Wi-Fi. [PR #11](https://github.com/mehdi7129/inky-studio/pull/11) remains draft;
merge and public release await the hardware criteria, not just green CI.

The Pi Zero 2 W supports
[Bluetooth 4.2/BLE and 2.4 GHz Wi-Fi](https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/).
The current supported target is **WPA2 Personal, 2.4 GHz, IPv4 on `wlan0`**.
Captive portals, WPA Enterprise, open networks and 5 GHz are outside this
implementation. It does not read saved iPhone Wi-Fi passwords or automatically
control Personal Hotspot.

| Implemented work | Current contract and remaining physical evidence |
|---|---|
| First adoption | An authenticated LAN session opens a ten-minute physical QR window. The phone verifies the frame identity before sending a secret. Real QR display/scanning and ownership adoption remain to test; first ownership entirely offline is not implemented |
| Later travel setup | An already-adopted phone can enter Bluetooth setup from the login screen without a common LAN. Ownership is separate from app/SSH passwords and persists in Keychain and the frame's verifier store |
| Encrypted channel | CoreBluetooth → BlueZ GATT with TLS 1.3, Mbed TLS on iPhone, P-256 frame identity and QR-derived SPKI pin. TLS/GATT tests and the Mac–Pi radio bench pass; the bench used trust supplied by known SSH, not a physical QR scan |
| Network service | Installed dedicated helper uses bounded socket operations and constrained NetworkManager permissions. Health/scan and local service checks pass; no real network transition has been qualified |
| Secret handling | No retained Wi-Fi password on iPhone or in the transaction journal. A confirmed NetworkManager profile retains the secret needed to reconnect. App-password rotation revokes other owners and cancels a pending trial before committing the new password |
| Checkpoint and confirmation | A 180-second trial remains temporary until the phone joins the same network and confirms over pinned HTTPS. Missing confirmation or interruption triggers rollback. Transaction and recovery tests are simulated; real commit/rollback and power interruption remain open |
| Photo transport | An adopted iPhone uses HTTPS `8443` with identity verification and no HTTP fallback. Legacy HTTP `8000` remains available for existing clients. This is not a claim that every client uses encrypted transport |

The real-hardware sequence selected by Mehdi is: adopt on the home network,
try an incorrect Wi-Fi password and observe rollback, then switch to a
**2.4 GHz hotspot**, join the iPhone to that network, confirm HTTPS and transfer
a test photo. Record version, phase and result without passwords or private SSIDs.

| Travel scenario | Expected behavior to verify |
|---|---|
| Private 2.4 GHz network | Configure, upload/display and reconnect after power cycle |
| Local Wi-Fi without internet | Photo management works; update-check failure does not block it |
| Captive portal | Unsupported; association is not internet access. Document limits without promising hotel portal sign-in |
| Client isolation | Same SSID may prevent iPhone→Pi access. Distinguish unreachable local API from incorrect credentials and document tested alternatives |
| Unsupported radio/security | Explain incompatibility, avoid endless retries |
| Travel router / hotspot | Verify specific routing configurations first; do not assume automatic iPhone Personal Hotspot control |
| Wrong password/interruption | Observe actual rollback after a wrong password, app closure or BLE loss; test reboot/power interruption with a recovery path and record any deferred cases |

**Remaining deliverables:** physical iPhone QR/ownership and Wi-Fi evidence,
recovery results, final user guidance and review/privacy declarations matching
the tested binary. Check permission denial/recovery, revocation after password
change from another client, and absence of sensitive data in shared evidence.
**Acceptance:** intended WPA2 setup, pinned HTTPS photo transfer and recovery
pass on actual hardware; deferred/unsupported cases remain explicit. The current
successful deployment and Mac radio bench do not establish those outcomes.
See [the integration contract and evidence limits](BLUETOOTH-INTEGRATION.md).

Apple's optional [Wi-Fi Infrastructure framework](https://developer.apple.com/documentation/wifiinfrastructure)
may later simplify sharing saved credentials, but requires iOS 26.2+ and currently
has EU account/location eligibility restrictions. Recheck framework/entitlement
conditions; retain manual BLE provisioning as the iOS 18/international baseline.

## 11. Separate phase: remote family access

BLE provisioning does not connect relatives on another network. First confirm
invitations, supported devices, upload-only versus control rights, owner approval
and offline expectations. Compare a private tunnel with an authenticated relay
as a distinct phase, covering revocation, per-person permissions, encryption,
photo retention/deletion, queuing, cost and abuse limits. Never directly expose
the current HTTP Pi service or reuse the Wi-Fi pairing secret for family accounts.
A hosted photo service changes privacy/store declarations and operations. No
remote-access implementation or cloud purchase is included in this build.

## 12. Separate workstream: InkyOS

Keep two installation paths: advanced users install Raspberry Pi OS and Inky
Studio, while a future InkyOS image includes the same application and its
dependencies. The dedicated InkyOS conversation owns image-builder selection,
base/architecture, first-boot system setup and SD qualification; the app workstream
retains iOS/backend/protocol, TestFlight and Bluetooth acceptance.

The [InkyOS handoff](../inkyos/README.md) records the integration boundary and
[official hardware sources](../inkyos/HARDWARE-SOURCES.md). No finished image or
fully offline first adoption is claimed. That onboarding needs a coordinated
application/protocol extension; it is not already supplied by rc.2. Do not treat
the personal frame or an existing SD as disposable image-test hardware.

## Remaining decisions

- Build 4 compliance resolution and private TestFlight delivery, then Mehdi's
  physical iPhone/Bluetooth/Wi-Fi results and public-readiness go-ahead.
- Review arrangement, compatibility scope and optional English UI/metadata.
- Initial territories, price/commercial model and verification of existing EU trader details.
- Final age/privacy/encryption answers based on the eligible public candidate;
  unresolved administrative choices and accepted compliance documents cannot be
  inferred from a prepared draft.
- Public travel claims based on the qualified WPA2 scope and documented limits;
  first adoption without an existing LAN belongs to the coordinated InkyOS work.
- Remote-family requirements and whether a hosted service is wanted.
- Public review submission and the subsequent manual release decision.

Public listing, InkyOS and remote-family choices do not prevent preparing the
private beta. Build 4 delivery does depend on resolving its actual compliance gate.

## Historical delivery — build 2 and initial public documentation

Build 2 corrects a black app-icon export caused by an unsupported 24-bit AppKit
bitmap. The replacement 1024px sRGB icon is opaque and visually verified; app
functionality is unchanged. Apple processed and assigned it to the same private
group. Installation and physical-device acceptance were pending at this stage;
the current available beta and subsequent user feedback are recorded in section 1.

The website is live with authentic beta screenshots, the approved public email,
setup/troubleshooting and an accurate privacy policy. Its publication does not
publish the iPhone app. Include the subsequent native support/privacy link
addition in the future tested public candidate before App Review.
Operationally, honor the published support-message
retention period (up to one year after resolution), without deleting account
messages as part of this delivery.


### Support/privacy follow-up — 27 September 2026

The native links compile with Xcode 27.0 for iPhone Simulator. Two existing UI
regressions pass on iOS 27.0: invalid-password/login/tab navigation, and settings
save/logout (2 tests, 0 failures or skips). These tests do not open the external
links; their HTTPS destinations were checked separately. Local evidence is kept
under ignored `build/ios/support-links-validation/`. No new archive was uploaded.

The website source now distinguishes the initial password from a personalized
password and explains Bluetooth key storage, Wi-Fi recovery data, HTTPS after
adoption, and local forgetting versus server revocation. It explicitly separates
the available build 3 from build 4 awaiting qualification/distribution. HTML,
31 local links/resources and desktop rendering were checked. The reviewed ZIP
is in ignored `build/website/2026-09-27-support-privacy/`, with a source manifest
and Netlify `_headers` generated from `netlify.toml`.

This website revision is **not deployed**: Chrome's upload tool requires the
extension's file-URL access permission, which was unavailable. No upload or
production switch completed. The existing public site remains on its previous
camera-privacy revision. Verify the production content and headers after the
pending upload before marking the website follow-up delivered.
