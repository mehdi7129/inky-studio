# Inky ecosystem

| Project | What to use |
|---|---|
| [Inky Studio](https://github.com/mehdi7129/inky-studio) | SwiftUI iPhone app and local PHOTO service. [iOS build and fork guide](ios/CURRENT-RELEASE.md) |
| [InkyOS](https://github.com/mehdi7129/inkyOS) | Raspberry Pi image builder, first boot, Wi-Fi and e-paper integration. [Generic image 2026.11.20-rc2](https://github.com/mehdi7129/inkyOS/releases/tag/2026.11.20-rc2) |
| [inkyImager](https://github.com/mehdi7129/inkyImager) | macOS 14+ SD writer. [Universal DMG 0.1.4](https://github.com/mehdi7129/inkyImager/releases/download/v0.1.4/inkyImager-0.1.4-Universal.dmg) |

inkyImager 0.1.4 contains InkyOS 2026.11.20-rc2 with PHOTO service 0.5.0rc3.
Prepare a new card with inkyImager, boot the frame and scan its QR on an iPhone
on the same network. Review the [display compatibility matrix](https://github.com/mehdi7129/inkyOS/blob/main/docs/DISPLAY-COMPATIBILITY.md)
before installing on a new screen. The generic image is a prerelease.

## Source versions

| Component | Released source | License for project code |
|---|---|---|
| SwiftUI app 1.0.0 (19) | [iOS source snapshot](https://github.com/mehdi7129/inky-studio/tree/ios-v1.0.0-build19/ios) with [build provenance](releases/ios-v1.0.0-build19.json) | [MIT](../LICENSE) |
| PHOTO service 0.5.0rc3 | [Backend source snapshot](https://github.com/mehdi7129/inky-studio/tree/imager-backend-0.5.0rc3/server) | [MIT](../LICENSE) |
| InkyOS 2026.11.20-rc2 | [Image assembly sources](https://github.com/mehdi7129/inkyOS/tree/2026.11.20-rc2) | [MIT](https://github.com/mehdi7129/inkyOS/blob/main/LICENSE) |
| inkyImager 0.1.4 | [Mac app sources](https://github.com/mehdi7129/inkyImager/tree/v0.1.4) | [MIT](https://github.com/mehdi7129/inkyImager/blob/main/LICENSE) |

The projects use separate repositories and release tags. The iPhone app and
the frame communicate over the PHOTO API. The Mac app embeds a pinned InkyOS
image. You can replace the iPhone app or build your own client against a
compatible frame without changing the Mac installer or rebuilding the OS.

Third-party components keep their own licenses. Follow the iOS guide for the
pinned Mbed TLS build, and keep the upstream notices when distributing a fork.
