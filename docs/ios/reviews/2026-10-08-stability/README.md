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
| Progress spinners replaced some accessible button names | Keep stable labels for saving settings, loading older photos and enabling biometrics; expose progress separately |
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

Final-source validation and screenshot review: **in progress**.

Local evidence is retained outside Git under
`build/ios/stability-2026-10-07/` (the session began October 7).

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
