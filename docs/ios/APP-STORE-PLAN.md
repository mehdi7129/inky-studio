# iPhone publication plan

Status snapshot: **2026-10-09**. The path is **private TestFlight → real-device
acceptance → public readiness → final candidate → App Review → manual release**.
Public release remains a separate decision after Mehdi's hardware feedback.
Build **1.0.0 (9)** is delivered to the internal TestFlight group. Apple approved
export compliance on **2026-10-08**; real iPhone/frame qualification remains open.
InkyOS and remote family access remain separate workstreams.

Mehdi reports on **2026-10-09** that the app works well and that no screen is
currently connected. This is positive user feedback, without an exact installed
build number or a pass for each hardware journey. Work can continue using the
[tests without a frame](TEST-WITHOUT-FRAME.md). App Store Connect was inspected
**read-only on 2026-10-09 around 09:10 UTC**, after the session became accessible
again. The saved choices below were observed without modifying any Apple field.
They describe the current draft, not a public-release decision or legal opinion.

## 1. Verified delivery and remaining gates

| Item | Current evidence |
|---|---|
| App | Native SwiftUI iPhone companion, iOS 18+, French UI; rounded bento, system light/dark appearance, portrait only, camera import and a visible offline demo in delivered build 9 |
| Identity | `fr.mehdiguiard.inkystudio`; App Store Connect app **6816637620** |
| Available beta | **1.0.0 (9)**, clean source **181edb2**, uploaded and assigned to **Mehdi — test iPhone** with one internal tester on **2026-10-09**; French test notes saved. Exact currently installed build remains to record |
| Bluetooth delivery | Included in the delivered beta; real QR adoption and Wi-Fi commit/rollback still require the frame. Historical build 4 compliance is no longer the current delivery gate |
| Validation | Build 9: **76/76 archive/IPA checks**, **109 unit tests + 17 UI tests**, one expected simulated Face ID skip, no failures; iPhone Release and general CI pass. TLS 15/15, Bluetooth transport 13/13, HTTPS 52/52 and fixture 45 checks pass. These do not establish physical iPhone QR adoption, Wi-Fi transition or screen refresh |
| Encryption | Apple export approval recorded **2026-10-08**; the live app-information page shows **two approved documents**. Build 9 includes the approved code and non-exempt encryption declaration; Apple processed it without a missing-compliance gate. This is not public App Review approval |
| Public metadata | Version 1.0.0 is **À finaliser avant soumission**, with **manual release** selected. French description, promotional text, keywords, support/marketing URLs, demo review notes and review contacts are filled. No public candidate has been submitted |
| Public candidate | The draft still selects **build 7**, labelled **Informations manquantes**. Replace it with the qualified final candidate before submission; this older selection does not block delivered TestFlight build 9 |
| Listing screenshots | Eight existing assets are visible; the inspected medium-size slot reuses existing resources and has zero slot-specific uploads. Completeness and agreement with the final candidate still need review |
| App Privacy | **Données non collectées**, **Publié il y a 9 jours**, with the privacy URL present and validated in the live review |
| EU trader status | Current DSA declaration explicitly says **non-trader / non-commerçant**. This corrects the older note claiming trader status; no declaration was changed |
| Price / availability | **0 EUR** in France; **France only (1/175)**; future distribution **Public**. Mac and Apple Vision Pro availability are unchecked |
| Category / rights / age | **Photo et vidéo**, third-party content-rights answer **Yes** saved, age rating **4+** |
| Website | **https://inky-studio.netlify.app** deployed on the existing free Netlify plan; home, support and privacy verified over HTTPS, mobile layout and local links checked |
| Support | Mehdi explicitly approved **mehdi071292@gmail.com** as the public contact |
| Hardware (last recorded deployment; not rechecked today) | Pi Zero 2 W Rev 1.0; server candidate **0.5.0-rc.2**, source **ae61df1**, deployed with active network helper. HTTP/HTTPS, authentication, driver detection and local BlueZ registration checked; no real Wi-Fi transition qualified |

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

## 2. Continue private TestFlight acceptance

**Owner:** release engineer and Mehdi.

Build **1.0.0 (9)** was uploaded, processed and assigned to **Mehdi — test iPhone**
on **2026-10-09**. The signed archive/IPA, source SHA, checksums and delivery
observations are recorded in [TESTFLIGHT-DELIVERY.md](TESTFLIGHT-DELIVERY.md).
No extra upload or old build 4 compliance action is needed merely to continue
these tests.

- Record the version/build shown in TestFlight, iPhone model and iOS version
  before attaching a result to build 9. Mehdi's positive feedback today does not
  supply that exact version or a detailed acceptance log.
- Complete the [short no-frame checklist](TEST-WITHOUT-FRAME.md): demo, navigation,
  appearance, large text, import/crop, reset and real iPhone camera/VoiceOver where
  available. Engineering can continue regression, documentation and listing
  preparation while the hardware is absent.
- Keep QR adoption, Bluetooth Wi-Fi, authentication with the real frame and actual
  e-ink output explicitly untested until the hardware returns.
- Continue internal TestFlight distribution. External testing, App Review and
  public release remain separate steps; no public submission is authorized by
  this readiness work. Recheck the current beta availability/expiry in TestFlight
  when scheduling further testing.

**Acceptance:** the installed build is identified and no-frame results are
recorded separately from physical-frame results. Build 9 delivery is complete;
full hardware acceptance is not. Mehdi prefers TestFlight and Simulator checks,
so direct signed Xcode installation is not the current delivery path.

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
| Bluetooth Wi-Fi | Delivered build 9 with the identified compatible server: physical QR adoption, wrong Wi-Fi password, rollback, selected 2.4 GHz hotspot, pinned HTTPS confirmation and photo transfer. See section 10 for recovery cases |
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

Delivered build 9 includes a visible offline demo and first-connection guide;
see [behavior, isolation and walkthrough](DEMO-AND-ONBOARDING.md). It can be
explored without a frame. The Python loopback fixture and Debug launch arguments
remain test infrastructure, not the public reviewer entry point.

**Delivered behavior:** **Explorer la démo** uses original locally drawn examples
and the real native screens. Crop, queue/history and settings are interactive;
physical refresh, scheduling and update limits are explicit. Demo state is
temporary and separate, with reset/exit and no real-frame authentication or
commands. No real credentials or household photos are shipped, and the user's Pi
remains private. An automated walkthrough is not an Apple acceptance decision.

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
- **Support** and **Privacy** links are delivered before login and in settings,
  using the existing rounded cards and system colors. Recheck their destinations
  and agreement with the final listing. The privacy manifest does not replace a
  public policy; the support/privacy source addition is included in build 9.
- Validate VoiceOver, Dynamic Type through accessibility sizes, contrast, reduced
  motion, non-color status cues and touch targets. Provide usable alternatives to
  precise crop/reorder gestures. Use only the existing local **iPhone 15 Pro Max
  Simulator**; do not create another local Simulator. Test portrait-only behavior
  and both system appearances there, and keep untested device sizes explicit.
  Confirm actual platform availability; do not claim untested iPad or Mac support.
  Automated accessibility checks do not replace listening with real VoiceOver.
  Advertise only verified accessibility features.

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
same-network operation and optional Face ID. Capture the final public UI using
only the existing local **iPhone 15 Pro Max Simulator**: frame, crop, queue,
history and settings, with non-personal content and clear demo context. Preserve
the rounded Bento design. Existing QA captures are evidence, not automatically a
complete App Store screenshot set.

The read-only check on **2026-10-09 around 09:10 UTC** showed eight existing
assets: `01-cadre`, `02-cadrage`, `03-file`, `04-historique`, `05-reglages`,
`06-face-id`, `08-cadre-demo` and `07-accueil-demo`. The inspected medium-size
slot uses existing resources and has **zero uploads specific to that slot**;
this is not evidence that the screenshot section is empty. The set still needs
a visual review against the final candidate and the required device slots.

Before uploading, inspect the slots and size validation in App Store Connect's
official screenshot manager and recheck Apple's
[current screenshot specifications](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications/).
Do not require or install a local 6.9-inch Simulator based on the obsolete plan.
Record which existing assets are accepted and what, if anything, remains missing.
Localize artwork only for published localizations; video remains optional.

**Acceptance:** all assets match the submitted build, pass size validation, contain
no personal data, and communicate hardware requirements before installation.

## 7. App Store declarations and owner decisions

| Area | Required verification / acceptance |
|---|---|
| App Privacy | Live check: **Données non collectées**, **Publié il y a 9 jours**, privacy URL validated. Keep final data flows, demo and diagnostics consistent with policy, answers and manifest; no declaration was changed |
| Privacy manifest | Recheck required-reason APIs. Current manifest declares local UserDefaults use, no tracking and no collected types; resolve any archive warnings |
| Age rating | Live check: **4+** classification saved. Confirm continued consistency if candidate features/content change; no Kids Category claim is made |
| Encryption | Apple approved export compliance on **2026-10-08**; two approved documents are visible live. Build 9 declares non-exempt encryption and includes the approved code. Reconcile later cryptographic changes with [the inventory](ENCRYPTION-INVENTORY.md). Export approval does not approve the app for public release |
| Countries / price | Live saved choices: **0 EUR**, **France only (1/175)** and future **Public** distribution. Preserve these choices; no IAP/subscription exists |
| EU trader status | Live saved declaration: **non-commerçant**. The earlier trader note was inaccurate/outdated. This read-only check does not change or legally assess the declaration |
| Account / rights | Live saved choices: third-party content-rights answer **Yes**, **Photo et vidéo**, Mac/Apple Vision Pro unchecked. Check any remaining account agreements at submission without changing existing personal declarations |
| Review information | Demo notes and review contacts are filled live. Validate instructions against the final candidate and record remaining hardware/video evidence; private contact details stay in App Store Connect, not this document |

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

**Included in delivered iOS 1.0.0 (9); not yet qualified end to end on iPhone.**
The last recorded server deployment was **0.5.0-rc.2**; identify its actual
version when the frame is available again. Apple export compliance no longer
blocks this internal beta. Photos continue to use Wi-Fi. The Bluetooth and iOS
PR chain remains unmerged; green CI and beta delivery do not replace the physical
criteria below or authorize a merge/public release.

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

- Identify the currently installed build, collect the remaining no-frame results,
  then physical iPhone/Bluetooth/Wi-Fi results when hardware returns.
- Review arrangement, compatibility scope and optional English UI/metadata.
- Preserve the observed free France-only distribution and non-trader declaration;
  ask only about future changes or choices that are actually unresolved.
- Replace the draft's old build 7 with the qualified final candidate and review
  the eight existing screenshots against it. Preserve the observed age/privacy
  declarations and export approval; recheck consistency if the candidate changes.
  Do not reopen the former build 4 blocker without new evidence.
- Public travel claims based on the qualified WPA2 scope and documented limits;
  first adoption without an existing LAN belongs to the coordinated InkyOS work.
- Remote-family requirements and whether a hosted service is wanted.
- Public review submission and the subsequent manual release decision.

Public listing, InkyOS and remote-family choices do not prevent testing the
already-delivered private beta or continuing the work that needs no frame.
Historical entries below describe their date only and do not override build 9
delivery or Apple export approval recorded above.

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

This website revision is **published** on the existing Netlify site after the
maintainer enabled the browser extension's upload permission. Production deploy
`6ab945ef3d8845400107aadc` contains the reviewed source. All three HTML pages and
five assets return HTTPS 200; the HTML is equivalent after Netlify's pretty-URL
rewriting, the five asset hashes match, and all configured security/cache headers
pass. Evidence: ignored `build/website/2026-09-27-support-privacy/live-validation.json`
and `published-support.png`. Previous deploy `6ab8fe8839e44c58d6f12688` remains
available for rollback. This publication does not distribute an iPhone build.

Both GitHub workflows passed on the latest code commit `f9c842e`: general CI
and iOS (including Simulator tests, TLS/GATT/HTTPS checks and iPhone Release).
Subsequent delivery-state documentation changes do not alter the tested app.
