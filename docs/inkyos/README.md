# InkyOS integration

Inky Studio is the iPhone app and local photo service in a three-repository system:

| Project | Responsibility |
|---|---|
| [InkyOS](https://github.com/mehdi7129/inkyOS) | Raspberry Pi image, hardware profile, startup and SD maintenance |
| [inkyImager](https://github.com/mehdi7129/inkyImager) | Mac app for preparing, configuring and writing the SD image |
| [Inky Studio](https://github.com/mehdi7129/inky-studio) | iPhone photo workflows, QR access and the frame's PHOTO service |

See the [ecosystem checkpoint](../ECOSYSTEM.md) for published source references and deployment status.

## Checkpoint — 23 October 2026

- The physical frame uses the Imager-configured LAN service based on `b75bf1e7`. The maintainer reported beta **1.0.0 (16)** working on that installation.
- iPhone **1.0.0 (17)** is validated by Apple and available in internal TestFlight. It removes the Settings **Accès protégé** card while retaining local authentication at app opening.
- The LAN sharing service `716104b1` is tested and packaged, but **maintenance of the current SD is still pending**. Transitive sharing is not yet enabled on that live installation.
- Source snapshots are published separately from `main`: [iOS beta 17](https://github.com/mehdi7129/inky-studio/tree/release/ios-1.0.0-build17) and [LAN sharing backend](https://github.com/mehdi7129/inky-studio/tree/release/backend-lan-photo-sharing-20261023). A source branch, built package and deployed frame are distinct checkpoints.

## Current LAN flow

inkyImager supplies image/network preparation; InkyOS owns system and hardware startup. Studio scans the frame's QR and connects to its pinned HTTPS identity on port **8443**, from the same local network. Face ID, Touch ID or iPhone passcode protects the app, and each paired iPhone keeps its own protected credential.

The LAN runtime gives photo members access to photos and scheduling without Wi-Fi or system administration. With the sharing backend installed, authenticated `can_invite=true` permits a member to show a single-use QR for another iPhone. This does not promote either device to owner. The QR format and photo-access database schema (version 1) remain unchanged.

Legacy password/HTTP port 8000 instructions describe a different installation path. They are not SSH, OTA or maintenance instructions for the Imager-configured card.

## Preserve the existing installation

An existing card requires InkyOS maintenance, not a fresh flash or reset. The planned sequence is a complete verified backup, a change to a copy of the root filesystem, preservation checks, then a separately admitted partition write and readback. Studio supplies the reviewed delta; InkyOS owns SD tools and the physical operation.

Keep frame identity/TLS material, network configuration, photo access database, credentials and photos intact. The delta changes three Python files and their installed `RECORD` rows; other local metadata entries must be preserved. Publishing the repositories does not perform that maintenance.

The targeted tests and signed-package checks are documented in the source guides. They do not replace an actual QR → second iPhone → photo → reconnection test on the updated frame.
