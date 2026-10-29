# Inky ecosystem — 29 October 2026

| Project | Delivery and ownership |
|---|---|
| [inkyImager0.1.2](https://github.com/mehdi7129/inkyImager/releases/tag/v0.1.2) | Mac SD writer, DeveloperID signed/notarized; macOS14+, AppleSilicon. |
| [InkyOS2026.10.29-rc1](https://github.com/mehdi7129/inkyOS/releases/tag/2026.10.29-rc1) | Prerelease clean system image, Wi-Fi import, display profile and SD operations. |
| [Inky Studio1.0.0(19)](https://github.com/mehdi7129/inky-studio/releases/tag/ios-v1.0.0-build19) | iPhone sources and existing internal TestFlight beta; PHOTO service0.5.0rc2. No public AppStore release. |

The reference frame's service716104 was installed on25 October with its identity,
photos, access and Wi-Fi preserved. QR sharing then succeeded on two iPhones;
the maintainer accepted functional behavior on29 October after several days.
The clean generic image is a separate new artifact. Its first physical boot is
not observed, even though software/image checks and notarized Mac packaging pass.
Keep it labeled as a prerelease and preserve the working frame.

## Frozen sources

- iPhone: `65e626e8760bc956e17a118f2a18175b184a6f3c`, branch
  [release/ios-1.0.0-build19](https://github.com/mehdi7129/inky-studio/tree/release/ios-1.0.0-build19).
- PHOTO service: `716104b130d34d1973001e78f15e25989d4c2e76`, branch
  [release/backend-lan-photo-sharing-20261023](https://github.com/mehdi7129/inky-studio/tree/release/backend-lan-photo-sharing-20261023).
- Image OS code: `a70197adcc9168bf826d9c6ac7376d23056b23fe`.
- Mac compiled code: `d434d5fa3ed67cb21350aca44cf56a1d7225b129`.

The source release tag integrates the frozen iPhone and backend runtime
subtrees. Main retains its earlier implementation and current entry-point documentation. Documentation updates do not imply that a new iOS binary was uploaded.
Build19 remains the previously signed/delivered binary from65e626e. Read
[the machine-readable provenance](releases/ios-v1.0.0-build19.json) for tree hashes.

## Contracts and installation

Use the Mac release guide for a new card. The qualified reference is PiZero2W,
InkyImpression7.3-inch800×480 with an explicit AC073 profile, France/WPA2/2.4GHz.
No exact panel SKU or support for every revision is claimed. The app and frame
must communicate on the same LAN; an Internet connection does not replace it.

The LAN frame advertises a pinned HTTPS PHOTO endpoint and `can_invite` capability.
Its initial QR grants photo access; it does not manufacture owner/admin authority.
Every authorized photo member may invite a further member on this runtime.
Invitations are5-minute, single-use; device authorizations outlive consumed QR codes.
See [IMAGER-LAN](https://github.com/mehdi7129/inky-studio/blob/release/backend-lan-photo-sharing-20261023/docs/IMAGER-LAN.md), [release notes](releases/ios-v1.0.0-build19.md)
and the respective OS/Mac release pages. Legacy browser/installer paths and inactive
factory/SoftAP/Bluetooth prototypes are distinct. Paused work is not resumed.

GitHub sources, internal TestFlight availability, public AppReview, generic image
software checks and physical qualification are separate states. No IPA, signed
mobile archive, personalized SD image, live QR or private support receipt belongs
in these public releases. AppReview still needs the external hardware video and
final dossier; the production website is handled separately.
