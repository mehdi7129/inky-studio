# Inky Studio 1.0.1 (20) and PHOTO service 0.5.0rc5

Public source prerelease for Xcode and backend integrators.

- One QR scan, iPhone unlock, crop and send. Password-based pairing verifies the frame first and then uses HTTPS pinned to its certificate key. The HTTP proof request contains only its format version and a fresh nonce.
- Saved device access can reopen after a restart or reconnect. The app checks the identity of a known alternate endpoint before switching.
- Interrupted photo uploads can be resumed by reopening the import screen. The frame records an upload receipt so a retry with the same key and file does not add a second queue item.
- After an owner access has been saved and successfully reopened on a later app launch, the frame can retire the obsolete bootstrap password.
- English, French, Spanish, Portuguese, German, Italian, Japanese, Korean, Arabic, Simplified Chinese and Traditional Chinese follow the iPhone’s language settings. French remains the development language.
- Includes the localized frame welcome screen and the five-minute initial QR from the InkyOS PHOTO 0.5.0rc4 checkpoint.

## Compatibility

| Use | Requirements |
| --- | --- |
| Build the app | iOS 18+, Xcode, and the pinned TLS build described in the [iOS README](../../ios/README.md). |
| Use already supported PHOTO invitations | A compatible InkyOS frame on the local network, including the published InkyOS 2026.11.20-rc2 with PHOTO 0.5.0rc3. |
| Use endpoint recovery, upload receipts and bootstrap retirement together | The companion PHOTO service 0.5.0rc5 from this release. The wheel is provided for integration and local testing. |
| Pair an older password-based QR | The frame must support the anonymous TLS proof. If it cannot prove its identity, update the frame software before pairing. |

The published InkyOS and inkyImager downloads still contain PHOTO 0.5.0rc3. Keep a recovery path before attempting a backend migration. After bootstrap retirement, switching back to an older backend requires local recovery because that backend cannot read the retired credential format. A permitted LAN PHOTO member can still invite another media member.

## Qualification

The hardening was tested on Simulator and local fixtures, with the anonymous HTTP proof and pinned HTTPS session exercised over loopback. Before deploying on a working frame, qualify the physical QR scan, iPhone authentication, LAN packet capture, reboot with a changed DHCP lease, interrupted upload, and one appearance on the real e-paper panel.

See the [App Store/source record for build 19](ios-v1.0.0-build19.md) for the earlier signed binary. Build 20 is available here as source.
