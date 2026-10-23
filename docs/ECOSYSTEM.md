# Inky ecosystem and source checkpoints

Status recorded on **23 October 2026**. A source branch, an internal iPhone beta and an installed SD image are distinct deliverables.

## Project ownership

- [InkyOS](https://github.com/mehdi7129/inkyOS) owns the system image, hardware support, startup and SD maintenance.
- [inkyImager](https://github.com/mehdi7129/inkyImager) owns the Mac SD preparation and installation application.
- [Inky Studio](https://github.com/mehdi7129/inky-studio) owns the iPhone photo app and local PHOTO service. Its earlier browser interface and installer remain in this repository.

## Status on 23 October 2026

| Deliverable | Verified checkpoint | Qualification |
|---|---|---|
| iPhone beta | 1.0.0 (17), source [`3930573`](https://github.com/mehdi7129/inky-studio/commit/3930573cf93b0216c6c993a5e39d89a6eaf94318) | Apple binary validated; available in the existing internal TestFlight group. 128 distinct iOS tests passed across the targeted runs and 87 signing/package checks passed. |
| Working reference | iPhone build 16 with the current LAN image/backend `b75bf1e7` | Reported working by the owner. This does not establish every hardware or recovery scenario. |
| PHOTO sharing service | [`716104b1`](https://github.com/mehdi7129/inky-studio/commit/716104b130d34d1973001e78f15e25989d4c2e76), based on `b75bf1e7` | 138 backend tests passed, including a real local HTTPS A → B → C sharing sequence and preserved synthetic device access across restart and a return to b75. |
| Service installation | Offline update package prepared and reviewed | **Not yet installed on the reference SD card.** Physical sharing between iPhones remains to be confirmed after maintenance. |

The internal beta is not an App Store release. This documentation update does not install a service or write a card.

## Source branches

- [`release/ios-1.0.0-build17`](https://github.com/mehdi7129/inky-studio/tree/release/ios-1.0.0-build17) preserves the exact iPhone build-17 source.
- [`release/backend-lan-photo-sharing-20261023`](https://github.com/mehdi7129/inky-studio/tree/release/backend-lan-photo-sharing-20261023) preserves the tested sharing-service source and [LAN contract](https://github.com/mehdi7129/inky-studio/blob/release/backend-lan-photo-sharing-20261023/docs/IMAGER-LAN.md).
- `main` keeps its existing implementation plus the updated project documentation. No release branch or paused storage work is implicitly merged by publishing these checkpoints.

Each branch includes the repository as it existed for that component. The iPhone and backend checkpoints are not interchangeable and are not a newly assembled system image. Read the corresponding branch's build instructions and dependencies before building it.

## LAN access and sharing

The current Imager-based flow prepares Wi-Fi before the frame boots. Its PHOTO service runs over HTTPS on port 8443 with the frame identity pinned by the QR. It does not require entering the legacy HTTP password during normal iPhone pairing.

The first iPhone receives a `media` device credential. Sharing-capable LAN services return the authenticated boolean `can_invite`; the app enables invitations only when permitted. An older service without that field keeps photo-member sharing disabled. Existing owner-based legacy sharing stays separate.

A sharing invitation creates a new device access. It does not copy the inviter's device token or owner credential. The QR is valid for five minutes, is single-use, and can be cancelled before use. In LAN mode each authorized photo member can invite another member, while Wi-Fi, administration and device-management operations remain unavailable to those members.

The build-17 Settings change removes the “Accès protégé” explanatory card and manual-lock button. Face ID, Touch ID or iPhone-code protection at app opening remains in place. The authorized Wi-Fi action is grouped under “Mon cadre”.

## Updating the existing reference card

InkyOS owns this maintenance. The current profile has no usable SSH or PHOTO-authorized in-app system update path. The prepared service change therefore uses offline SD maintenance, with a complete verified backup before editing a copy of the root filesystem.

The update is limited to three Python modules and their three entries in the actual installed `RECORD`. Other installed metadata entries, identity, TLS material, Wi-Fi configuration, database, device credentials and photos must be preserved. The schema remains version 1. The wheel's `RECORD` is not a replacement for the installed file, which may have extra local entries.

Preparation and fixture tests do not authorize a card write. Actual card selection, backup, candidate validation and the separate write/readback review belong to the InkyOS workflow. Installation remains pending in the status above until that workflow reports completion.

## Public material

Published source and deliberately synthetic fixtures are separate from local delivery material. Signed Apple archives, production invitations, credentials, private device state, actual SD backups and deployment logs are not part of the source publication.
