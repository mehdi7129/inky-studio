# Native iPhone implementation

Approved: 2026-09-27. Mehdi approved all six bento mockups and asked for end-to-end implementation. Distribution: personal use, then TestFlight. Network: same Wi-Fi as the Raspberry.

## Acceptance criteria

- Native SwiftUI app (iOS 18+), four tabs matching the approved light bento design.
- Existing v0.4.2 server compatibility without a Raspberry migration.
- Manual address/password pairing, optional biometric Keychain credential, explicit password fallback and sign out/forget frame.
- Shared authenticated networking for JSON, image bytes and foreground WebSocket events.
- Native photo picker and orientation-aware crop to exact panel size; upload PNG without local quantization.
- Queue reorder/delete, history requeue/delete, display next/previous, settings and Pi update flow.
- Helpful empty/offline/auth/error/loading states; refresh after foreground return and connection recovery.
- Simulator build, behavior tests, visual inspection, release archive and documented device/TestFlight delivery.

## Work boundaries

Implementation is isolated in the `codex/native-ios` worktree. Existing web/server behavior remains the compatibility contract. Design references are under `design/ios/2026-09-27`.

## Validation log

Implementation complete. Final evidence and physical-device delivery boundaries are recorded in `VALIDATION.md`.
