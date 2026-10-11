# Offline demo and first connection

Current delivery: **TestFlight 1.0.0 (9)**, assigned to the internal group on
**2026-10-09**. The demo, first-connection guide and native support/privacy links
are included. Apple export compliance was approved on **2026-10-08**; the former
build 4 gate is historical. See [delivery evidence](TESTFLIGHT-DELIVERY.md).

Mehdi reported that the app works well without a connected screen. On
**2026-10-10**, InkyOS relayed the operator's confirmation that **build 9 is
installed**, not directly observed by Studio. These reports do not qualify all
demo/hardware journeys. See [delivery provenance](TESTFLIGHT-DELIVERY.md).
The [French no-frame checklist](TEST-WITHOUT-FRAME.md) separates tests
that can continue now from those that require a Raspberry and screen.

## Product behavior

- **Explorer la démo** is visible on the normal connection screen in Debug and
  Release, including when a real frame is remembered. No password, network,
  special launch argument or Raspberry is needed.
- The same four native tabs display an in-memory simulated frame. A persistent
  banner identifies the demo and provides an exit. Next/previous, queue/history,
  reorder, import/crop and settings use the normal UI and photo pipeline.
- Three original geometric landscapes are drawn on-device with UIKit. An
  example can be cropped without Photos/camera permission. Personal selections
  remain temporary within the demo; exiting or resetting the demo, or terminating
  the app, discards that session. Backgrounding alone keeps it. Normal Photos imports may use their existing temporary
  decoding file, removed after preparation; demo frame storage is memory-only.
- Demo scheduling is editable but never runs automatically. Refresh is simulated;
  no physical e-ink color rendering or refresh delay is represented. Bluetooth,
  biometrics, password changes and real software updates are unavailable in demo.
- **Préparer mon cadre** opens a scrollable guide, also accessible from Settings.
  It explains hardware/server prerequisites, LAN/address/password, permissions,
  optional Face ID, e-ink latency and Bluetooth adoption/recovery limits.
- The existing rounded cards, icon, system appearance and portrait policy remain.
  Scheduling uses a menu at accessibility text sizes so options remain readable.

## Isolation boundary

`FramePhotoClient` exposes photo workflows only. `InkyAPI` retains all real
authentication, provisioning and update operations. `DemoFrameClient` has no
network, defaults, Keychain or file-store dependency. `AppStore` can enter demo
only while signed out and not connecting; sensitive methods have explicit demo
guards. Real address, ownership and biometric preferences remain untouched.

Reset/exit retire the client, invalidate pending store operations, clear the
image cache and rebuild the tab subtree. Crop upload also checks session identity
before handing data to the store. Imports are bounded by 30 queue entries,
10 MiB per encoded image and 32 MiB total stored image bytes. History retains the
latest 100 entries, dropping older rows automatically. Unreferenced demo images
are removed; clearing history keeps the current displayed image.

## Review walkthrough

1. Launch without a frame and choose **Explorer la démo**.
2. Open Cadre and use Suivante/Précédente, then inspect File and Historique.
3. Ajouter une photo → Utiliser une image d’exemple → crop/zoom → Ajouter à la démo.
4. Change and save demo settings; reset the demo from Réglages.
5. Quitter returns to real connection. Préparer mon cadre explains actual setup.

The demo provides a reproducible overview; it does not qualify physical Bluetooth,
Face ID, camera capture, Wi-Fi recovery or an actual e-ink refresh. App Review may
still request a hardware video or other resources.

A read-only App Store Connect check on **2026-10-09 around 09:10 UTC** confirmed
that the demo review notes and review contacts are filled. The public version is
still **À finaliser avant soumission**, with manual release selected and the old
build 7 attached. The final qualified candidate and matching screenshot set must
be selected before submission; none of those Apple fields was changed in this
check. See [the current listing snapshot](APP-STORE-PLAN.md).

## Validation

Build 9 source `181edb2` passed **109 unit tests and 17 UI tests**, with one
expected simulated Face ID skip and zero failures; the iPhone Release build and
**76/76 signed archive/IPA checks** passed. The UI suite includes the public demo
walkthrough, large-text navigation and semantic accessibility checks. See the
[stability review and screenshots](reviews/2026-10-08-stability/README.md) for
individual run provenance and limits; these results do not establish real
VoiceOver speech, camera capture or frame behavior.

Historical generated evidence remains under ignored `build/ios/demo-onboarding/`.
The signed beta was subsequently uploaded and assigned as documented in
[TESTFLIGHT-DELIVERY.md](TESTFLIGHT-DELIVERY.md). No public App Review submission or
new Pi deployment is part of this documentation update.
