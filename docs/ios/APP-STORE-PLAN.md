# iPhone publication plan

Status snapshot: **2026-09-27**. The path is **private TestFlight → real-device
acceptance → public readiness → final candidate → App Review → manual release**.
Public release remains a separate decision after Mehdi's hardware feedback.
Bluetooth travel setup and remote family access are separate future phases.

## 1. Verified delivery and remaining gates

| Item | Current evidence |
|---|---|
| App | Native SwiftUI iPhone companion, iOS 18+, French UI, local Inky Studio v0.4.2+ server |
| Identity | `fr.mehdiguiard.inkystudio`; App Store Connect app **6816637620** |
| Binary | **1.0.0 (2)**, source **2cc692e**, Xcode 27; standard App Store Connect distribution |
| Upload / processing | Latest upload succeeded **2026-09-27 09:34:33 UTC**; Apple processing complete without a remaining compliance action |
| Private TestFlight | Group **Mehdi — test iPhone**, two builds and one invited tester; invitation acceptance and device installation still to verify |
| Validation | 35 unit tests, 41 fixture API checks and all 7 signed simulator UI journeys passed, including simulated Face ID; real Pi API probe passed |
| Public metadata | French description, promotional text, keywords, subtitle **Vos photos, sur votre cadre**, **Photo & Video** category, 2026 Mehdi Guiard copyright and manual release saved as a draft; no public candidate submitted |
| App Privacy | **No Data Collected** saved in draft from the current self-hosted data-flow audit; not yet published |
| EU trader status | App Store Connect already identifies this developer as a trader for the app; existing account declaration was not changed, details remain to verify before release |
| Website | **https://inky-studio.netlify.app** deployed on the existing free Netlify plan; home, support and privacy verified over HTTPS, mobile layout and local links checked |
| Support | Mehdi explicitly approved **mehdi071292@gmail.com** as the public contact |
| Hardware | Pi Zero 2 W Rev 1.0; Bluetooth service active, `bluetoothctl` and `nmcli` installed; no BLE provisioning flow implemented |

Evidence: [TESTFLIGHT-DELIVERY.md](TESTFLIGHT-DELIVERY.md),
[VALIDATION.md](VALIDATION.md), [DISTRIBUTION.md](DISTRIBUTION.md), and
[the native README](../../ios/README.md). Preserve the archive, dSYMs, source SHA,
IPA checksum and upload receipt outside temporary storage. An invitation is not
proof of installation, and simulator success is not physical-device acceptance.

## 2. Finish private TestFlight delivery

**Owner:** release engineer and Mehdi.

- Verify the invited Apple Account can install **1.0.0 (2)** in TestFlight and
  launch it. Record the iPhone/iOS and installation result.
- Keep the beta private; public links and external testing are separate steps.
  Existing beta description, feedback address and hardware checklist must match
  the assigned build. Standard distribution preserves eligibility for later
  external/public review; an Internal Only upload would not.
- Internal testers must be eligible App Store Connect users. External testing
  requires its own beta information and applicable Beta App Review. Refresh the
  build before its 90-day expiry if testing continues. See Apple's
  [TestFlight workflow](https://developer.apple.com/help/app-store-connect/test-a-beta-version/testflight-overview/).

**Acceptance:** Mehdi installs and opens the correct build through TestFlight;
record delivery separately from the hardware test below. No external/public beta
or App Store availability is implied.

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
| Crop → upload → display | Pan/pinch/reset/cancel; exact detected panel dimensions; stripped metadata; real next/previous refresh. Framing correct, Pi alone quantizes colors, no duplicate commands |
| Queue/history | Reorder/remove identified entries, requeue history, verify dates and agreement with the web UI. Persisted state matches across clients |
| Settings | Daily/interval/manual, whole-hour Pi-local schedule, saturation, save/reopen. Values persist and frame behavior matches |
| Lifecycle | Lock/unlock, background/foreground, terminate/relaunch. State resynchronizes and authentication is understandable |
| Fault recovery | Leave LAN/cellular-only, interrupt/recover Wi-Fi, expired session or safe Pi restart, invalid address, cancelled login. No endless spinner, stale success or replayed mutation |
| Concurrent changes | Change queue/settings in the web app while iPhone is open. State converges; late results cannot restore a signed-out session |
| Pi update | Check version/release information. Actual update only in an agreed maintenance window with recovery, not as an incidental acceptance action |

Do not reset Mehdi's Face ID or restart/upgrade production hardware merely to
finish the checklist. Mark deferred cases and arrange a suitable test device or
maintenance slot. Report reproducible steps and non-sensitive screenshots through
TestFlight; never include frame passwords.

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
  Publish a verified hardware matrix; one 800×480 panel does not validate all
  Inky displays. Do not imply cellular remote access.
- Add **Support** and **Privacy** links before login and in settings. The privacy
  manifest does not replace a public policy. Apple's
  [sections 1.5 and 5.1.1(i)](https://developer.apple.com/app-store/review/guidelines/)
  cover contact information and accessible privacy links.
- Validate VoiceOver, Dynamic Type through accessibility sizes, contrast, reduced
  motion, non-color status cues and touch targets. Provide usable alternatives to
  precise crop/reorder gestures. Test a small and large iPhone and every declared
  orientation. Confirm actual platform availability; do not claim untested iPad
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
| Encryption | Current `ITSAppUsesNonExemptEncryption=false` reflects the present system-framework implementation; reassess final crypto/dependencies, especially future BLE/TLS work. Supply documentation if requested |
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

## 10. P2: travel Wi-Fi setup over Bluetooth

**Planned, absent from 1.0.0 (2).** Configure SSID/password from the iPhone over BLE;
photos still use Wi-Fi. Decide whether this ships before the first public release
or later. Do not advertise it until implemented and tested.

The verified Pi Zero 2 W supports
[Bluetooth 4.2/BLE and 2.4 GHz Wi-Fi](https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/),
not 5 GHz-only networks. Prototype iPhone CoreBluetooth central → BlueZ GATT Pi
peripheral, including concurrent Wi-Fi/BLE on the actual OS image. Installed
services are not proof of a working provisioning flow. Custom BLE GATT itself
is outside the relevant licensed-accessory requirement in Apple's [MFi scope](https://mfi.apple.com/faqs).

| Work package | Security / acceptance contract |
|---|---|
| Possession and pairing | Bounded pairing window triggered physically or through an already-authorized local action; physical QR/independent pairing secret; verify device identity. Decide activation and secret generation/reset; no existing button assumed |
| Encrypted channel | Reviewed protocol, authenticated encryption/MITM protection tied to possession, anti-replay and failed-attempt limits. No proximity-only trust, fixed shared PIN or invented crypto |
| Network selection | Pi scans SSIDs, user selects/enters password; hidden-network option. Explicit open/WPA2/WPA3/enterprise support matrix. iOS 18 flow does not assume access to saved iOS passwords |
| Pi configuration | Narrow service using NetworkManager, preferably D-Bus, with constrained privileges/input validation and no shell interpolation. Keep provisioning secret separate from frame login |
| Secret handling | No Wi-Fi passwords in app preferences, logs, diagnostics or exported backups; clear transient phone state. Pi persistence needed for reconnection uses protected NetworkManager profiles with documented permissions, deletion/reset and backup policy |
| Recovery | Status over BLE; distinguish authentication, radio/security, DHCP, local API and internet. Checkpoints/timed rollback; retain known-good configuration and a BLE recovery path when the old network is absent |
| Wi-Fi handoff | Return verified LAN connection info and use normal frame authentication; no BLE photo uploads. Explain Bluetooth/camera permissions if QR scanning is added and handle denial |
| Shared-network transport | BLE security does not encrypt current HTTP password/cookie/photo traffic. Before hotel/shared-network support, add HTTPS with Pi identity verified during pairing or a suitable private VPN; define trust rotation/recovery and never disable TLS verification |

| Travel scenario | Expected behavior to verify |
|---|---|
| Private 2.4 GHz network | Configure, upload/display and reconnect after power cycle |
| Local Wi-Fi without internet | Photo management works; update-check failure does not block it |
| Captive portal | Association is not internet access. Report limits; evaluate hotel device registration or a tested travel-router setup. No promise of automatic portal sign-in |
| Client isolation | Same SSID may prevent iPhone→Pi access. Distinguish unreachable local API from incorrect credentials and document tested alternatives |
| Unsupported radio/security | Explain incompatibility, avoid endless retries |
| Travel router / hotspot | Verify specific routing configurations first; do not assume automatic iPhone Personal Hotspot control |
| Wrong password/interruption | Recover by rollback or explicit BLE retry without credential exposure or loss of management |

**Deliverables:** threat model/protocol review, Pi service, native setup UI,
authenticated Wi-Fi transport, rollback/migration guide, permission/privacy
updates and real-hardware tests. **Acceptance:** successful setup on a fresh LAN,
no unauthorized nearby reconfiguration, recovery after interruption, usable local
photos without internet, honest hotel limitations, and packet-level evidence that
shared-network traffic exposes no passwords/cookies/photos. Reassess review,
privacy and export compliance for this new binary.

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

## Remaining decisions

- Mehdi's physical-device results and public-readiness go-ahead.
- Review arrangement, compatibility scope and optional English UI/metadata.
- Initial territories, price/commercial model and verification of existing EU trader details.
- Final age/privacy/encryption answers based on the public candidate.
- Whether travel/BLE is required before public release; pairing method and network scope.
- Remote-family requirements and whether a hosted service is wanted.
- Public review submission and the subsequent manual release decision.

The first private TestFlight installation does not depend on these later choices.

## Delivery update — build 2 and public documentation

Build 2 corrects a black app-icon export caused by an unsupported 24-bit AppKit
bitmap. The replacement 1024px sRGB icon is opaque and visually verified; app
functionality is unchanged. Apple processed and assigned it to the same private
group. Installation and physical-device acceptance remain pending.

The website is live with authentic beta screenshots, the approved public email,
setup/troubleshooting and an accurate privacy policy. Its publication does not
publish the iPhone app. Add its support/privacy links inside the next public
candidate before App Review. Operationally, honor the published support-message
retention period (up to one year after resolution), without deleting account
messages as part of this delivery.
