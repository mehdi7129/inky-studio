# iOS stability and accessibility — 2026-10-08

Scope: the existing rounded Bento interface, foreground/offline recovery,
accessible action labels, system Reduce Motion, and export metadata. This work
is stacked on `codex/ios-bento-polish` / PR #19, base
`15b5e536e791b4e23215e9c1b60103d14e0c8e13`. It does not merge the dependent iOS
or Bluetooth branches, deploy the Raspberry, or change the TLS implementation.

## Confirmed findings and changes

| Finding | Change / regression coverage |
|---|---|
| Cancelling a refresh marked a reachable frame offline | Ignore cancellation as connectivity evidence; preserve the session and loaded data |
| A refresh requested during an in-flight failure was lost | Consume the pending refresh after a failure; hand it to a fresh task after cancellation only in the same active session |
| A recovered refresh could retain its transient error or erase a newer operation error | Track whether the displayed error belongs to connection recovery; preserve a newer business error |
| Offline and error banners overlapped each other and the navigation title in the captured queue screen | Give each banner space above the tab navigation; check their actual screen frames |
| Progress spinners replaced some accessible button names | Keep stable labels for saving settings, loading older photos and enabling biometrics; expose progress separately |
| Decorative dashboard and photo-selection images exposed SF Symbol names to VoiceOver | Hide those redundant images from the accessibility tree; keep the descriptive text and values |
| Success notices were only visual | Post a native accessibility announcement for each new, nonempty notice |
| Queue editing always animated | Respect the system Reduce Motion setting |
| Export declaration still needed a manual questionnaire | Include the exact approval code supplied by Apple on 2026-10-08 and declare non-exempt encryption |

The local fixture can now simulate temporary unavailability and bounded settings
latency. These controls are loopback-only, preserve sessions during an outage,
and reset between cases. They are not included in the Raspberry server.

Six added unit tests cover cancellation, queued retries, newer operation errors,
backgrounding and session changes. New UI checks cover background → offline →
recovery without login, settings labels while saving, and native accessibility
audits for descriptions/traits on the welcome screen, four tabs and photo flow.
The accessibility audit does not suppress reported issues.

## Validation

Device: the existing **iPhone 15 Pro Max / iOS 27.0 Simulator**, Xcode 27.0.
No additional simulator was created. All data is synthetic. DerivedData lives
under `~/Library/Caches/inky-studio-ios-stability-derived-data` to avoid macOS
File Provider metadata causing code-signing failures under Desktop.

Before the fix, two new unit tests failed with three assertions: cancellation
incorrectly cleared connectivity, and a requested retry never ran. The initial
broad baseline passed 103 unit and 13 UI tests; two Bluetooth UI cases failed
amid simulator accessibility/event-loop stalls. Both Bluetooth cases later
passed unchanged in a targeted run with 105 unit tests passing. These are
separate runs, not a claim of one successful consolidated run.

The complete local run on `18849de` reached **109 unit + 11 UI passes** before
infrastructure failures: a loopback reset timed out, its late callback was
reported against the following test, and XCTest lost its accessibility server
(`kAXErrorServerNotFound`). The UI-test runner then aborted in
`_swift_task_dealloc_specific → XCTSwiftErrorObservation → addAsyncTeardownBlock`.
The application process was still alive. This does not establish the root cause
of the preceding accessibility loss. The run was interrupted and is **not a
successful complete suite**.

The harness now explicitly selects synchronous, MainActor-isolated teardown and
confines request assertions to the current test. Late fixture callbacks are
ignored after closing/cancelling the request. The reported abort occurred in
**InkyStudioUITests-Runner**, not the shipping app; this is evidence of a test
runner failure, without proving the framework's underlying root cause.

On iOS 27 the tab query can resolve an SF Symbol child with an invalid hit point.
The helper taps the observed tab rectangle and checks the destination. A further
capture established that a correctly displayed static navigation title may not
be `hittable`; a title is not itself an interactive control.

| Evidence | Result |
|---|---|
| CI `ea07425`, [run 37812748085, attempt 2](https://github.com/mehdi7129/inky-studio/actions/runs/37812748085/attempts/2) | 109 unit tests pass; 11 fixture UI tests pass; one simulated Face ID case skipped. Three demo cases fail: two large-text scrolling helpers and an unlabelled decorative `photo.badge.plus` image. Overall run **failed**. |
| Local `resume-light.xcresult`, `ea07425` | 2/2 targeted tests pass: offline/background recovery with separate banners; four rounded tabs, hidden filenames and portrait. |
| Local `verified-dark.xcresult`, `fca004a` | Full public demo journey passes: guide, four tabs, crop, add photo, history, settings, reset and relaunch. Separate accessibility audit fails its navigation `hittable` oracle while the failure screenshot shows the correct unobscured Cadre screen. Overall run **failed**. |

The first CI run also exposed slow test drags activating buttons/links instead
of scrolling. Recordings, rather than increased timeouts or suppressed
assertions, are used to qualify the helper corrections. The accessibility audit
keeps every description/trait check; redundant decorative images are hidden
individually in the app.

Final targeted validation is in progress. No incomplete or interrupted run is
reported as a full-suite pass.

The unsigned generic iPhone **Release build on `11dd76a` passed** with Xcode 27.
Its compiled Info.plist contains non-exempt encryption = true and the exact Apple
approval code. The build emits existing incomplete-umbrella warnings from
MbedTLS and an AppIntents metadata warning; a successful build is not proof of
installation or hardware behaviour.

Local evidence is retained outside Git under
`build/ios/stability-2026-10-07/` (the session began October 7).

## Visual review

Raw Simulator PNGs are committed below. Each capture's test, source commit,
result bundle and hash are recorded in [captures.json](captures.json). Light
screens use the isolated API fixture; dark screens use the public demo. The
older large-text captures come from individually passing cases in a run that
was interrupted later, and are labelled accordingly in the manifest.

| Screen | Light | Dark |
|---|---|---|
| Cadre | [Capture](screenshots/cadre-light.png) | [Capture](screenshots/cadre-dark.png) |
| File | [Capture](screenshots/file-light.png) | [Capture](screenshots/file-dark.png) |
| Historique | [Capture](screenshots/historique-light.png) | [Capture](screenshots/historique-dark.png) |
| Réglages | [Capture](screenshots/reglages-light.png) | [Capture](screenshots/reglages-dark.png) |
| Photo crop | — | [Capture](screenshots/cadrage-dark.png) |

The rounded cards, black/white hierarchy, restrained coloured accents and
photo-first content remain consistent with the approved Bento. The inspected
normal-size screenshots show no filename, clipped label or spelling error.
The floating system tab bar overlays scrolling content temporarily; content
must remain reachable by scrolling, which the UI journeys check.

Offline banners: [before](before/offline-overlap-light.png) →
[after](screenshots/offline-light.png). The after image separates the offline
notice, API error and navigation title; the test asserts their actual frames.
The English “Fixture API temporarily unavailable” message in this diagnostic
capture is deliberately injected by the test API, not production interface copy.

Accessibility text: [Cadre](screenshots/grand-texte-cadre-light.png),
[photo submission](screenshots/grand-texte-envoi-light.png). Semantic audit and
visual inspection are separate from a spoken VoiceOver listening check.

## Reproduce

Start the loopback fixture with simulated Face ID and seed only generated photos:

```bash
python3 ios/scripts/mock-server.py --biometric-device '<EXISTING_SIMULATOR_UDID>'
# In another terminal:
python3 ios/scripts/seed-simulator-photo.py '<EXISTING_SIMULATOR_UDID>'
xcodebuild -project ios/InkyStudio.xcodeproj -scheme InkyStudio \
  -destination 'platform=iOS Simulator,id=<EXISTING_SIMULATOR_UDID>' \
  -derivedDataPath "$HOME/Library/Caches/inky-studio-ios-stability-derived-data" \
  -parallel-testing-enabled NO -collect-test-diagnostics never \
  -resultBundlePath /tmp/InkyStability.xcresult \
  CODE_SIGNING_ALLOWED=YES CODE_SIGN_IDENTITY=- test
```

The final run disables optional verbose diagnostics collection after Xcode's
`simctl diagnose` spent ten minutes timing out after the successful targeted
run. Test assertions, coverage collection and result attachments remain enabled.
Xcode also reported Security main-thread warnings in the existing trust unit
tests; this review does not qualify runtime performance on a physical phone.

## Delivery boundaries

**Build 1.0.0 (8)** was assigned to the internal TestFlight group on October 8
following Apple's export approval. App Store Connect reports installation on
the tester's iPhone 15 Pro Max. That binary predates these changes; a later
build is needed to test this PR on the phone. See [delivery status](../../TESTFLIGHT-DELIVERY.md).

Simulator and fixture results do not establish physical BLE/QR enrollment,
Wi-Fi commit/rollback, real camera capture, or actual e-ink refresh. Spoken
VoiceOver announcements still need a listening check; automated semantic audits
are not comprehensive accessibility certification. No public App Review
submission or public release is performed by this PR.
