# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres
to [Semantic Versioning](https://semver.org/).

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

[0.2.0]: https://github.com/mehdi7129/inky-studio/releases/tag/v0.2.0
[0.1.0]: https://github.com/mehdi7129/inky-studio/releases/tag/v0.1.0
