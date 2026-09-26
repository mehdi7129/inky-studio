# Native iPhone validation — 2026-09-27

The approved six-screen bento design is implemented in SwiftUI. Minimum iOS version: 18.0. Server compatibility tested against the existing v0.4.2 release. No production Pi files, photos, queue entries or settings were changed by these checks.

## Verified locally

| Check | Result |
|---|---|
| Simulator Debug build | Passed, Xcode 27.0 |
| Native unit tests, iPhone 16e / iOS 18.5 | **34 passed**, 0 failures |
| API unit tests | 15 passed: wire types, cookies/port isolation, redirects, empty 202/204, validation errors, multipart, deadlines/cancellation |
| Session/state unit tests | 8 passed: logout/forget races, cancellation, late 401/result isolation, refresh/pagination, history beyond 500 entries |
| Photo pipeline unit tests | 11 passed: native HEIC, EXIF orientation, crop coordinates, exact dimensions, sRGB/SDR, metadata removal, bounded PNG output |
| End-to-end UI tests, iPhone 16 Pro / iOS 18.5 | **6 passed**, 0 failures, 106.5 seconds |
| Local fixture contract smoke | **41 checks passed**, including authenticated REST and WebSocket events |
| Real Raspberry native API probe | Passed: login, v0.4.2 health, state (800×480), queue/history/settings, authenticated PNG, WebSocket hello, logout |
| iPhone Release archive | Passed, automatic Apple Development signing |
| App Store Connect IPA export | Passed with Apple distribution signing |

UI coverage: incorrect/correct password and four tabs; PhotosPicker → crop → zoom/reset → PNG upload → queue; queue edit/removal and history requeue; next-photo command; settings save/logout; offline error/retry. All fixture photos are generated, non-personal images. Visual inspection confirmed readable controls, no overlapping content, a 5:3 crop aperture and visible primary actions. See [`screenshots/`](screenshots/).

Independent review found and fixed late-session response races, a monitor-task race, refresh locking, pagination beyond 500 entries, unbounded connectivity waiting, missing image retries after reconnect and draft settings being reset on tab return. Swift sources and tests have no compiler warnings; Xcode emits its standard notice that AppIntents metadata extraction is skipped because the app has no AppIntents dependency.

## Delivery boundaries

Mehdi requested simulator validation instead of connecting a physical iPhone. Physical Face ID, device local-network permission and actual display refresh through the iPhone remain device checks; simulator success cannot prove those hardware behaviors. The production Raspberry probe was read-only apart from creating and closing its own login session.

The exported IPA is ready for App Store Connect, but export is not TestFlight publication. No build has been submitted to Apple or released to testers as part of this implementation. The app record, upload/processing and tester assignment are described in [DISTRIBUTION.md](DISTRIBUTION.md).

## Reproduce

Use the checked-in Xcode project, start `ios/scripts/mock-server.py`, boot a simulator and run `ios/scripts/seed-simulator-photo.py <UDID>`, then `xcodebuild test` with test parallelization disabled. The dedicated `.github/workflows/ios.yml` performs the same setup on Xcode 16.4 / iOS 18.5 and also builds an unsigned device Release binary.

Local evidence bundles (outside Git): `/tmp/inky-ios-unit-verified.xcresult`, `/tmp/inky-ios-ui-complete.xcresult`. Signed exports are under the ignored `build/ios/` directory. GitHub Actions retains its test result bundle for 14 days.
