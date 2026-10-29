# Inky Studio iOS1.0.0 (19) / PHOTO0.5.0rc2

GitHub source **prerelease**, 29 October2026. This is not a public AppStore
release, external TestFlight link or installable IPA.

## Included

- QR-first LAN connection with a pinned frame identity and protected saved access.
- Import/camera/crop, queue/history, scheduling and private photo access sharing.
- Five-minute single-use invitation QR; authorized PHOTO members may invite peers
  on the compatible LAN service, without admin or Wi-Fi authority.
- The obsolete Settings protected-access card and product demo are removed;
  FaceID/iPhone-passcode protection remains.
- Build19 fixes the inactive-to-active window transition after unlocking: saved
  PHOTO restoration resumes without a second retry tap, retaining cancellation,
  background and credential-generation guards.

## Exact components and evidence

The frozen iPhone source is65e626e; service716104 supplies LAN media delegation.
The release tree preserves their runtime and test subtrees. Build metadata for
Apple was supplied explicitly during archive/export; the public project's default
build number is not evidence of the installed TestFlight build.

Previous signed delivery:100 AppStoreTests passed on iOS27,87 package checks,
IPA hash `ece5fcaeba0017727ee3ebd7eae0e822cc34e6be796019cfd57dbf16e4a9f4e1`.
That private IPA is deliberately not a GitHub asset. The backend's focused sharing
qualification passed138 tests, including real loopback HTTPS delegation. Current
combined-tree CI is reported separately in the GitHub checks, without changing
these historical counts. The maintainer confirms physical use/sharing on the
existing frame; this is not independent execution of every detailed recipe.

## Downloads

The `.whl` is the exact generic service package used by the composed system image,
not a complete SD image or an iPhone installer. Prefer the
[notarized Mac installer](https://github.com/mehdi7129/inkyImager/releases/tag/v0.1.2)
and [InkyOS image release](https://github.com/mehdi7129/inkyOS/releases/tag/2026.10.29-rc1)
for a new card. Never overwrite an existing working card as an iOS-update step.

Compare SHA256SUMS before using an asset. The public provenance describes only
source/image/package identities, with no private card data or live credentials.

## Remaining qualification and public release

- The generic image's first physical boot has not been observed; OS stays prerelease.
- The final Mac package passes Apple notarization/Gatekeeper and native GUI launch;
  no SD write was performed by the Studio release workflow.
- iOS AppReview/public AppStore release and the production website deployment have
  not been performed. The externally filmed iPhone/frame demonstration remains
  required in the review dossier.
- Do not infer support for other screen SKUs, networks or recovery/OTA paths from
  the existing PiZero2W/AC073 reference.
