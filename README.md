# Inky Studio

The iPhone app and local photo service for an InkyOS e-ink frame. Import and crop photos, manage the queue and history, and choose daily, interval or manual display schedules on the same local network.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## Three projects, one frame

| Project | Responsibility |
|---|---|
| [InkyOS](https://github.com/mehdi7129/inkyOS) | Raspberry Pi system image, hardware profiles, boot and SD maintenance. |
| [inkyImager](https://github.com/mehdi7129/inkyImager) | Mac app that prepares and writes the SD card and its network configuration. |
| **Inky Studio** | Native iPhone app and the local PHOTO service running on the frame. This repository also retains the earlier browser interface. |

Start with the image and installation instructions in **InkyOS** and **inkyImager**. The [ecosystem and release checkpoints](docs/ECOSYSTEM.md) explain which sources match the current beta.

## Current iPhone flow

1. Prepare the frame with inkyImager and boot it on the same Wi-Fi network as the iPhone.
2. In Inky Studio, choose **Scanner un QR code** and scan the code displayed by the frame.
3. Authorize access with Face ID, Touch ID or the iPhone passcode, then add a photo and choose its schedule.
4. Reopen the app with its saved device access; the frame does not need to keep showing its original QR.

The current LAN image uses pinned HTTPS on port **8443**. Pairing and photo sharing use separate device credentials; the app does not send the frame's owner credential to another iPhone.

### Sharing photos with another iPhone

With the sharing-capable frame service installed, open **Réglages → Partager l’accès → Afficher un QR d’accès**. The other iPhone scans it using Inky Studio. Each invitation is valid for five minutes and can be used once.

On the explicit LAN runtime, every authorized photo member can invite another photo member. These accesses can send photos and choose their schedule; Wi-Fi, administration and device management remain restricted.

**The service update is still pending on the reference SD card.** Build 17 supports the feature, but an older frame that does not advertise `can_invite` keeps photo-member sharing disabled. See the [dated status](docs/ECOSYSTEM.md#status-on-23-october-2026) before testing it.

## Available checkpoints

| Component | Checkpoint | State on 23 October 2026 |
|---|---|---|
| iPhone beta | **1.0.0 (17)** | Available in the existing internal TestFlight group. The “Accès protégé” Settings card is removed; local authentication at app opening remains. |
| iPhone sources | [release/ios-1.0.0-build17](https://github.com/mehdi7129/inky-studio/tree/release/ios-1.0.0-build17) | Exact tested source checkpoint for build 17. |
| Sharing service sources | [release/backend-lan-photo-sharing-20261023](https://github.com/mehdi7129/inky-studio/tree/release/backend-lan-photo-sharing-20261023) | Tested offline update; installation on the reference card is pending. |
| Current reference installation | LAN image with backend `b75bf1e7` | Build 16 was reported working on this installation. |

`main` retains the earlier public implementation. The two release branches are separate component checkpoints and have not been merged into `main`. Select the matching branch when building an app or service; they are not a combined new OS image.

TestFlight availability is internal beta distribution. Installation packages, SD images and device-specific data are handled by the corresponding delivery and maintenance workflows.

## Build and development

- **iPhone:** see [ios/README.md](ios/README.md). Requires iOS 18+; use the build-17 branch for the QR-first beta source and its TLS package instructions.
- **Backend:** see [server/README.md](server/README.md). Use the sharing-service branch for the explicit LAN PHOTO runtime and its contract.
- **Browser interface:** `client/` contains the earlier React frontend. Its development and legacy installer paths remain available for their original installation model.

Local development commands for the public `main` checkout:

```sh
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
ruff check .
pytest
```

```sh
cd client
npm ci
npm run dev
```

The development browser server and standalone legacy HTTP service are separate from the InkyOS LAN image. Hardware rendering and supported panel profiles are configured and qualified in InkyOS; successful mock or Simulator tests alone do not qualify a physical display.

See [CLAUDE.md](CLAUDE.md) for source layout and contributor conventions. Dated reports under `docs/` preserve their historical scope; use [the current checkpoint page](docs/ECOSYSTEM.md) for release status.

## License

MIT — see [LICENSE](LICENSE). The earlier Samba-based project remains at [inky-photo-frame](https://github.com/mehdi7129/inky-photo-frame).
