# Inky Studio

Native iPhone photo app and local PHOTO service for an InkyOS e-paper frame.
Connect by QR, crop photos, manage the queue/history and choose manual, daily or
interval display schedules. Photo transfer and access sharing use your local network.

[![CI](https://github.com/mehdi7129/inky-studio/actions/workflows/ci.yml/badge.svg)](https://github.com/mehdi7129/inky-studio/actions/workflows/ci.yml)
[![iOS](https://github.com/mehdi7129/inky-studio/actions/workflows/ios.yml/badge.svg)](https://github.com/mehdi7129/inky-studio/actions/workflows/ios.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## Get started

| Component | Current delivery | Purpose |
|---|---|---|
| [inkyImager 0.1.5 (.dmg)](https://github.com/mehdi7129/inkyImager/releases/download/v0.1.5/inkyImager-0.1.5-Universal.dmg) | Notarized Universal DMG, macOS 14+ on Intel and Apple Silicon | Prepare a new SD card and its Wi-Fi configuration. |
| [InkyOS 2026.11.27-rc3](https://github.com/mehdi7129/inkyOS/releases/tag/2026.11.27-rc3) | Clean generic image, **prerelease** | Frame system with automatic Pimoroni panel detection and the compatible PHOTO service. |
| [Inky Studio iOS 1.0.0 (19)](https://github.com/mehdi7129/inky-studio/releases/tag/ios-v1.0.0-build19) | iPhone build 19 source checkpoint | Native iPhone photo app and Xcode build instructions. |

The iPhone source is available under MIT and can be built in Xcode. The
GitHub iOS release documents the source of build 19.

InkyOS detects compatible Pimoroni Impression, Spectra 6, pHAT and wHAT
panels by EEPROM. The latest image has been tested with simulated displays.
First boot and optical QR scanning for this image still require hardware
testing. See the [display compatibility matrix](https://github.com/mehdi7129/inkyOS/blob/main/docs/DISPLAY-COMPATIBILITY.md).
A fresh flash erases the card. Keep your current card when you only need to
update the iPhone app.

## Connect and share

1. Prepare and boot a compatible frame using the linked installation guide.
2. Put the frame and iPhone on the same LAN. In the app choose **Scanner un QR**
   and scan the frame QR; allow camera/local-network access.
3. Use Face ID or your iPhone passcode to unlock saved access, then import/crop a
   photo and add it to the queue. Wait for the physical e-paper refresh.
4. On an authorized, unlocked phone open **Réglages → Partager le cadre →
   Partager l’accès**. The other iPhone scans the displayed invitation in Inky Studio.

The initial frame QR expires after five minutes. Power-cycle the frame for a
new invitation if initial pairing has not been completed. Each invitation is
single-use. Expiring the QR does not
remove an already-accepted device access. On this LAN service every authorized
photo member may invite another photo member. Photo access covers photos, queue,
history and scheduling; it does not grant Wi-Fi or frame administration.
Owner-authorized installations may revoke devices; guests may cancel their own
pending invitations. Already-admitted descendants are separate device accesses.

Access is retained in the protected iPhone Keychain. The QR connection verifies
the frame’s HTTPS identity. Build 19 resumes the connection automatically
when the app becomes active after local authentication.

## Source provenance

Use the component tags to build the delivered versions.

| Component | Exact source |
|---|---|
| iPhone build 19 | [ios-v1.0.0-build19](https://github.com/mehdi7129/inky-studio/tree/ios-v1.0.0-build19/ios) |
| PHOTO service 0.5.0rc4 for InkyOS | [imager-backend-0.5.0rc4](https://github.com/mehdi7129/inky-studio/tree/imager-backend-0.5.0rc4/server) |

See the [ecosystem guide](docs/ECOSYSTEM.md) and the
[iPhone build provenance](docs/releases/ios-v1.0.0-build19.json). The PHOTO
service release provides the wheel built for InkyOS. Its updater is disabled
in that profile.

## Screenshots

Real app UI captured in Simulator with synthetic photo data and a fictitious QR.
These are not physical-frame proof or live pairing credentials.

[View the five current screens](docs/ios/screenshots/README.md).

## Build and contribute

- [Build the iPhone app or create your own client](docs/ios/CURRENT-RELEASE.md), iOS 18 minimum.
- [PHOTO API and runtime used by the latest image](https://github.com/mehdi7129/inky-studio/blob/imager-backend-0.5.0rc4/docs/IMAGER-LAN.md) and [local backend development](server/README.md).
- `client/` retains the earlier React interface; its legacy installer is distinct
  from the InkyOS/inkyImager image. New frame users should follow the links above.

```sh
cd server
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
INKY_STUDIO_DISPLAY_MODE=mock inky-studio-server
```

Backend CI uses mocked display I/O; driver tests inspect a pinned official wheel.
Software/Simulator tests do not independently qualify physical display hardware.
See [CLAUDE.md](CLAUDE.md) for contributor commands and conventions.

## Support and privacy

[Support](https://inky-studio.netlify.app/support.html) ·
[Privacy](https://inky-studio.netlify.app/confidentialite.html) ·
[Issues](https://github.com/mehdi7129/inky-studio/issues).
The public website sources are in `website/`. Do not post active frame QRs, Wi-Fi passwords,
private keys or personal photos in public issues. Existing installations can keep
legacy credentials; HTTPS QR photo access is the current supported LAN path.

## License

MIT — [LICENSE](LICENSE). Bundled iOS TLS notices are retained under
`ios/InkyStudio/Resources/ThirdPartyNotices.txt`; third-party component licenses
remain their own. The earlier Samba project is [inky-photo-frame](https://github.com/mehdi7129/inky-photo-frame).
