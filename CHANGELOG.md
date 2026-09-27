# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/).

## [0.5.0-rc.2] - Unreleased

Candidate for physical Bluetooth/Wi-Fi qualification, not a public release.

### Added
- Pair an iPhone with the frame's physical QR code, then configure WPA2 Wi-Fi
  over authenticated TLS 1.3 on Bluetooth. Confirm the same frame over HTTPS
  before preserving the new NetworkManager profile.
- Isolated network helper, rollback checkpoints, durable recovery journal,
  and revocable phone ownership tied to the personalized frame password.
- iPhone build 4 with rounded light/dark setup screens and bundled TLS notices.

### Validation
- Automated backend, iOS, TLS and HTTPS tests; real Mac/Pi Bluetooth bench;
  isolated backend qualification on Pi with the actual network helper.
- Physical iPhone adoption, Wi-Fi commit/rollback and power interruption remain
  open. TestFlight build 4 is uploaded but requires Apple's export documentation.

## [0.5.0-rc.1] - 2026-09-27

Candidate for controlled installation; not offered by the stable updater.
Refresh the installed CLI before migrating credentials. See
`docs/ios/PASSWORD-ROTATION.md` and `docs/ios/CLI-UPGRADE.md`.

### Added
- Personalize the Inky Studio application password from iPhone build 3.
  Password changes revoke previous HTTP and WebSocket sessions.
- Salted scrypt credential storage, legacy migration without changing the
  existing password, atomic writes and explicit local reset/recovery.

### Fixed
- Keep first-boot password images private and retry an interrupted welcome.
- Allow a manually installed candidate to discover its matching final release.
- Reject downgrade/reinstall requests in the updater itself, including direct
  API calls, before downloading or changing the installation.

### Maintenance
- Install a small CLI launcher so future updates also update command behavior.
- Publish candidate tags as prereleases without replacing the stable release.
- Include isolated on-Pi authentication qualification without driving the screen.

Bluetooth Wi-Fi provisioning is not included in this candidate.

## [0.4.2] - 2026-09-26

### Fixed
- Import recent HEIC/HEIF photos with native browser decoding when available,
  or the current libheif decoder through lazily loaded `heic-to` 1.5.2. The
  fallback returns a bitmap directly, avoiding intermediate JPEG recompression.
- Show readable conversion errors instead of `[object Object]`, including a
  useful fallback message for failures without a text description.
- Shield WebSocket task cleanup from AnyIO scope cancellation, preventing an
  intermittent teardown error without swallowing external cancellation.

## [0.4.1] - 2026-09-26

### Fixed
- Release WebSocket event subscriptions before awaiting task cleanup so repeated
  cancellation cannot leave a disconnected client registered on the event bus.
  This fixes a cancellation race found during the v0.4.0 release checks.

## [0.4.0] - 2026-09-26

This version was held as a prerelease after the cancellation issue above was
identified. Use v0.4.1 for the stable bento release.

### Changed
- **Monochrome bento interface.** A responsive white/black dashboard brings the
  current photo, schedule, upload, upcoming queue and detected display together.
  Queue, history, settings, login and crop preparation share the same controls,
  restrained color accents and keyboard focus styles.
- Photo previews preserve their actual aspect ratio. Mock mode is identified
  explicitly, and the page title, favicon and language match Inky Studio.

### Fixed
- Scheduling now handles the first daily rotation and local daylight-saving
  changes consistently. Failed display operations retain queued photos, missing
  source files are skipped, and display operations are serialized per process.
- Previous-photo navigation, concurrent history changes and settings updates
  preserve consistent state. Reconnected clients resynchronize their panels and
  return to login when a session has expired.
- Crop uploads reject stale conversions; empty successful display responses no
  longer appear as client errors. Uploaded PNGs are fully decoded and validated
  against the connected display before deduplication.
- Hardened SPA paths, WebSocket authentication, credential storage, upload reads
  and release extraction. Update rollback removes newly introduced code files,
  and existing CLI installations retain their legacy update entrypoint.

### Maintenance
- Added regression coverage and CI checks for frontend, Python 3.11/3.13 and
  installer/CLI scripts. Release builds run lint and tests before packaging.
- The Pimoroni driver remains pinned to `inky==2.3.0`; image quantization remains
  on the Raspberry Pi with the existing saturation setting.

## [0.3.3]

### Changed
- **Installer now auto-detects the user.** The one-liner no longer assumes the
  account is `pi` — it installs for whoever runs it (their real home dir and
  primary group), and bakes the right paths into the global `inky-studio` CLI.
  So the one-line install works on any Raspberry Pi OS setup, whatever username
  was chosen. Override with `INKY_STUDIO_USER` only for a different account.

## [0.3.2]

### Added
- **Delete history entries.** The History tab now has a 🗑 button per photo and a
  "Tout supprimer" (clear all, with inline confirm). Removes log entries only —
  photo files and the queue are untouched.

### Changed
- **Saturation range extended to 0–2** with the default raised to **1.0** (the
  panel's most faithful, measured palette). 0–1 still drives Pimoroni's native
  `set_image(saturation=…)`; above 1.0 a progressive source-image vibrance boost
  (`ImageEnhance.Color`) is applied on top for extra punch — capped in practice
  by the panel's gamut.

## [0.3.1]

### Added
- **Saturation setting.** A slider in Settings (0 = muted → 1 = vivid, default
  0.5) feeds straight into Pimoroni's `set_image(saturation=…)`, so you can tune
  the colour intensity to taste. It applies to the next photo displayed.

## [0.3.0]

### Changed
- **Faithful, automatic rendering — no more colour modes.** Images are now handed
  straight to the official Pimoroni `inky.set_image(saturation=0.5)`, which does a
  single Floyd-Steinberg quantisation to the exact palette of the auto-detected
  panel. Previously the app pre-quantised to a custom palette and the library
  re-quantised on top (a double pass that injected extra speckle/orange and
  discarded the intended colours). The result is now exactly Pimoroni's reference
  rendering for each display, with zero configuration.
- The browser now only crops the photo to the panel resolution (full colour); all
  colour science happens once, on the Pi.

### Removed
- The three colour modes (`spectra` / `warmth` / `pimoroni`) and the per-image
  mode selector — rendering adapts automatically to the detected screen.
- The in-browser e-ink preview simulation and the server-side preview endpoint.

## [0.2.3]

### Fixed
- **In-app update rolled itself back.** Verifying the restart subprocess treated
  the `SIGTERM` from the service's own `--no-block restart` (exit -15) as a
  failure and reverted the update. Only positive exit codes (e.g. sudo denied)
  now count as a failure; a signal kill is the expected "we're being restarted"
  success path.

## [0.2.2]

### Changed
- **"Check for updates" now bypasses the status cache** (`?refresh=1`), so a
  newly published release is detected immediately instead of after the ~10 min
  cache window. The passive page load still uses the cache.

## [0.2.1]

### Fixed
- **In-app update could fail to restart the service.** The scoped `sudoers`
  rule didn't cover the `systemctl --no-block restart` form the updater uses,
  so the restart was denied; and an open WebSocket could make graceful shutdown
  hang until systemd's kill timeout (~90 s). The installer now allows the
  `--no-block` form, the server bounds graceful shutdown to 10 s, and the
  service unit sets `TimeoutStopSec=20`. The updater also now reports a restart
  failure instead of swallowing it.

## [0.2.0]

### Added
- **One-click in-app updates.** A new **Settings → Update** section shows the
  installed version, detects when a newer release is available, and updates with
  a single click — downloading the latest release, swapping it in, and
  restarting, with live progress and an automatic page reload.
- **Prebuilt releases via CI.** Tagging `vX.Y.Z` builds the frontend and
  publishes a ready-to-run tarball, so the Pi no longer builds anything locally.
- **`GET`/`POST /api/system/update`** endpoints and a shared updater used by both
  the web UI and the `inky-studio update` CLI.

### Changed
- **Hardened one-line installer.** Now installs `python3-dev`/`build-essential`,
  enables SPI/I²C, adds `dtoverlay=spi0-0cs` (frees GPIO8 for the Inky library),
  creates swap on low-RAM Pis, installs the latest prebuilt release by default
  (`INKY_STUDIO_CHANNEL=source` to build from `main`), and reboots once on first
  install. Moved to the repository root (`install.sh`).
- The app can restart itself for updates via a tightly-scoped `sudoers` rule
  (limited to `systemctl start/stop/restart inky-studio.service`).
- Project documentation is now in English.

## [0.1.0]

### Added
- **Browser-side image conversion** — HEIC/JPEG/PNG/WebP decode, resize with
  cover-crop, optional warmth boost, and Floyd–Steinberg dithering, all in the
  browser, with a live preview of the exact e-ink result before upload.
- **Dashboard, queue and history** — current image with metadata, a
  drag-and-drop reorderable queue, next/previous controls, and a paginated
  history with re-queue.
- **Scheduling** — daily, fixed-interval, or manual rotation modes, plus colour
  mode selection (Spectra / warmth boost / Pimoroni 7-colour).
- **Real-time UI** — a WebSocket keeps every panel in sync with the backend.
- **Auth** — single-password login; the password is generated on first boot and
  shown on the e-ink welcome screen.
- **Display support** — auto-detection of Inky Impression 7.3" (7-colour),
  7.3" 2025 and 13.3" 2025 (Spectra 6), with an off-Pi mock for development.

[0.4.1]: https://github.com/mehdi7129/inky-studio/releases/tag/v0.4.1
[0.4.0]: https://github.com/mehdi7129/inky-studio/releases/tag/v0.4.0
[0.3.3]: https://github.com/mehdi7129/inky-studio/releases/tag/v0.3.3
[0.3.2]: https://github.com/mehdi7129/inky-studio/releases/tag/v0.3.2
[0.3.1]: https://github.com/mehdi7129/inky-studio/releases/tag/v0.3.1
[0.3.0]: https://github.com/mehdi7129/inky-studio/releases/tag/v0.3.0
[0.2.3]: https://github.com/mehdi7129/inky-studio/releases/tag/v0.2.3
[0.2.2]: https://github.com/mehdi7129/inky-studio/releases/tag/v0.2.2
[0.2.1]: https://github.com/mehdi7129/inky-studio/releases/tag/v0.2.1
[0.2.0]: https://github.com/mehdi7129/inky-studio/releases/tag/v0.2.0
[0.1.0]: https://github.com/mehdi7129/inky-studio/releases/tag/v0.1.0
