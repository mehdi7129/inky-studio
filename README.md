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
| [inkyImager 0.1.2](https://github.com/mehdi7129/inkyImager/releases/tag/v0.1.2) | Signed/notarized Mac app, macOS14+ on Apple Silicon | Prepare a new SD card and its Wi-Fi configuration. |
| [InkyOS 2026.10.29-rc1](https://github.com/mehdi7129/inkyOS/releases/tag/2026.10.29-rc1) | Clean generic image, **prerelease** | Frame system and compatible PHOTO service. |
| [Inky Studio iOS1.0.0 (19)](https://github.com/mehdi7129/inky-studio/releases/tag/ios-v1.0.0-build19) | Source checkpoint and existing **internal TestFlight** beta | iPhone photo app. Public App Store review is still being prepared. |

The GitHub release does **not** provide an installable iPhone IPA or public
TestFlight invitation. The app is not yet publicly available on the App Store.
Hardware is bought separately; this independent community project does not sell it
and is not an official Pimoroni, Raspberry Pi or Apple product.

The reference configuration is a Pi Zero2W with an Inky Impression7.3-inch
800×480 display using the explicit AC073 profile, WPA2/2.4GHz/France. The exact
panel SKU is not certified; do not assume every similarly named revision works.
The maintainer reports successful photo use and QR sharing over several days.
The **new generic image's first physical boot is not yet observed**; existing
frame acceptance and this new artifact's software checks are separate evidence.
See each project's release notes before preparing a new card. A fresh flash erases
that card; do not reflash an already-working frame just to update the iPhone app.

## Connect and share

1. Prepare and boot a compatible frame using the linked installation guide.
2. Put the frame and iPhone on the same LAN. In the app choose **Scanner un QR**
   and scan the frame QR; allow camera/local-network access.
3. Use Face ID or your iPhone passcode to unlock saved access, then import/crop a
   photo and add it to the queue. Wait for the physical e-paper refresh.
4. On an authorized, unlocked phone open **Réglages → Partager le cadre →
   Partager l’accès**. The other iPhone scans the displayed invitation in Inky Studio.

An invitation lasts five minutes and is single-use. Expiring the QR does not
remove an already-accepted device access. On this LAN service every authorized
photo member may invite another photo member. Photo access covers photos, queue,
history and scheduling; it does not grant Wi-Fi or frame administration.
Owner-authorized installations may revoke devices; guests may cancel their own
pending invitations. Already-admitted descendants are separate device accesses.

Access is retained in the protected iPhone Keychain. The QR connection verifies
the frame's HTTPS identity. There is no cloud account, Internet remote-control
service, tracking SDK or product demo. The old **Accès protégé** Settings block
is removed; local authentication at opening remains. Build19 resumes connection
automatically when the app becomes active after local authentication.

## Source provenance

The source release tag combines already-delivered component sources without changing
their runtime code. Main retains its earlier implementation; select the tag or
frozen source branch before building the delivered candidate. The iPhone and service have independent version numbers:

| Component | Exact delivered source |
|---|---|
| iPhone build19 | [`65e626e8760bc956e17a118f2a18175b184a6f3c`](https://github.com/mehdi7129/inky-studio/tree/release/ios-1.0.0-build19) |
| PHOTO service0.5.0rc2 | [`716104b130d34d1973001e78f15e25989d4c2e76`](https://github.com/mehdi7129/inky-studio/tree/release/backend-lan-photo-sharing-20261023) |

See [release provenance](docs/releases/ios-v1.0.0-build19.json), the
[ecosystem guide](docs/ECOSYSTEM.md), and the [release notes](docs/releases/ios-v1.0.0-build19.md).
The iOS tag is a GitHub prerelease and does not replace the legacy stable backend
updater's latest release. The `v*` workflow remains for matching backend versions;
`ios-*` releases describe iPhone/component source checkpoints.

## Screenshots

Real app UI captured in Simulator with synthetic photo data and a fictitious QR.
These are not physical-frame proof or live pairing credentials.

[View the five current screens](docs/ios/screenshots/README.md).

## Build and contribute

- [iPhone delivery and source instructions](docs/ios/CURRENT-RELEASE.md), iOS18 minimum.
- [Backend development](server/README.md) and [explicit LAN runtime](docs/IMAGER-LAN.md).
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
See [CLAUDE.md](CLAUDE.md) for contributor commands and conventions. Historical
reports and inactive prototypes stay dated; publishing sources does not resume
paused work or enable optional factory/Bluetooth/SoftAP/OTA paths.

## Support and privacy

[Support](https://inky-studio.netlify.app/support.html) ·
[Privacy](https://inky-studio.netlify.app/confidentialite.html) ·
[Issues](https://github.com/mehdi7129/inky-studio/issues).
The public website is being updated separately; the repository's `website/`
contains the prepared current pages. Do not post active frame QRs, Wi-Fi passwords,
private keys or personal photos in public issues. Existing installations can keep
legacy credentials; HTTPS QR photo access is the current supported LAN path.

## License

MIT — [LICENSE](LICENSE). Bundled iOS TLS notices are retained under
`ios/InkyStudio/Resources/ThirdPartyNotices.txt`; third-party component licenses
remain their own. The earlier Samba project is [inky-photo-frame](https://github.com/mehdi7129/inky-photo-frame).
