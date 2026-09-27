# Offline demo and first connection

Source addition after TestFlight build 4. It is not available in the distributed
build 3 and does not resolve the encryption-document gate for build 4.

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

## Validation

Validation results and screenshots are recorded with the implementation PR.
Local generated evidence lives under ignored `build/ios/demo-onboarding/`.
No public App Store submission, TestFlight upload or Pi deployment is performed
as part of this UI work.
