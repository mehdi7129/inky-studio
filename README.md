# Inky Studio

Send photos from an iPhone to an Inky e-paper frame on your local network. Scan the frame’s QR, unlock with Face ID or your iPhone passcode, then choose, crop and send a photo. You can also manage the queue, history and display schedule, and share access with another iPhone.

[Build and fork the iPhone app](ios/README.md) · [PHOTO API](docs/PHOTO-API.md) · [Screenshots](docs/ios/screenshots/README.md) · [MIT license](LICENSE)

## Get started

| Component | Download or source |
| --- | --- |
| iPhone app | [Inky Studio 1.0.1 (20) for Xcode](https://github.com/mehdi7129/inky-studio/releases/tag/ios-v1.0.1-build20), iOS 18 or later. Public source prerelease. |
| Frame system | [InkyOS 2026.11.27-rc3](https://github.com/mehdi7129/inkyOS/releases/tag/2026.11.27-rc3), a Raspberry Pi image with PHOTO service 0.5.0rc4. |
| Mac SD writer | [inkyImager 0.1.5 Universal (.dmg)](https://github.com/mehdi7129/inkyImager/releases/download/v0.1.5/inkyImager-0.1.5-Universal.dmg), macOS 14 or later, Intel and Apple Silicon. |

1. For a new frame, check the [display compatibility matrix](https://github.com/mehdi7129/inkyOS/blob/main/docs/DISPLAY-COMPATIBILITY.md) and prepare an SD card with inkyImager. The writer erases the selected card.
2. Put the frame and iPhone on the same local network. Open **Scan a QR code** and allow camera and local network access.
3. Scan the frame’s QR within five minutes and confirm the iPhone unlock. If the initial QR has expired, restart the frame to display a new invitation. Choose a photo, crop it to the panel and add it to the display queue.
4. To share the frame, open **Settings → Share frame** on an authorized iPhone. The invitation is single-use and expires after five minutes.

This is a free, independent project for compatible hardware. You buy the screen and Raspberry Pi separately. Photos travel directly between the iPhone and frame on the LAN, with no cloud account.

## GitHub and App Store versions

Build 20 is the open-source release for people building with Xcode. The GitHub download contains source and a Python wheel for developers. For the separate iOS 1.0.0 distribution checkpoint, see [build 19 and its provenance](docs/releases/ios-v1.0.0-build19.md).

Build 20 follows the system language in 11 localizations. It moves password-based QR pairing to pinned HTTPS after an anonymous identity check, restores saved frame access and lets you explicitly resume an interrupted upload. The complete recovery workflow uses the companion PHOTO service **0.5.0rc5**. The links above still deliver the existing inkyImager and InkyOS packages with service **0.5.0rc4**. A frame that cannot prove its HTTPS identity prompts for a frame software update.

See the [build 20 release notes](docs/releases/ios-v1.0.1-build20.md) for compatibility, test results and physical checks still to run.

## Build and contribute

- [iPhone app and pinned TLS dependency](ios/README.md). Fork the SwiftUI app with your own bundle ID and Apple signing team.
- [PHOTO API](docs/PHOTO-API.md) for writing a new client. The [LAN runtime documentation](docs/IMAGER-LAN.md) explains the InkyOS QR, service configuration and invitation roles.
- [Python backend](server/README.md) for a local mock display and backend tests. The earlier React web interface and its installer remain available in this repository.
- [Ecosystem guide](docs/ECOSYSTEM.md) for source tags and licenses across all three projects.

Community contributions are welcome via GitHub issues and pull requests. Please test with synthetic QR and photo data.

## Support and license

[Support](https://inky-studio.netlify.app/support.html) · [Privacy](https://inky-studio.netlify.app/confidentialite.html) · [Security reports](SECURITY.md)

The project is [MIT licensed](LICENSE). Bundled dependencies retain their licenses and [third-party notices](ios/InkyStudio/Resources/ThirdPartyNotices.txt).
