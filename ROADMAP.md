# Roadmap

A high-level view of where Inky Studio is and where it's going. For the detailed
per-release history, see [CHANGELOG.md](CHANGELOG.md).

## Shipped

- **Zero-config faithful rendering** — upload a photo; it's cropped to the panel
  and rendered by the official Pimoroni `inky` library to the exact palette of the
  auto-detected screen (single faithful pass, no colour modes).
- **Library management** — drag-and-drop upload, a reorderable queue, scheduled
  rotation (daily / interval / manual), and a browsable history.
- **Real-time UI** — WebSocket-driven updates across all panels.
- **Auth** — single-password login; the password is shown on the e-ink screen
  on first boot.
- **One-line installer** — SPI/I²C setup, dependencies, `systemd` service, and
  first-boot reboot handled automatically.
- **One-click updates** — update from the Settings panel or the CLI; the Pi
  pulls prebuilt releases (no on-device build).

## Ideas / under consideration

- Multiple albums / playlists with independent schedules.
- EXIF-aware cropping and orientation.
- Optional button controls (next/previous) on the Inky HAT.
- Backup / restore of the photo library and settings.
- Internationalised UI (the app is currently French).

Have an idea? Open an issue.
