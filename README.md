# Inky Studio

> A self-hosted web UI to run an Inky e-ink photo frame from any browser — local, no cloud.

[![CI](https://github.com/mehdi7129/inky-studio/actions/workflows/ci.yml/badge.svg)](https://github.com/mehdi7129/inky-studio/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Platform: Raspberry Pi](https://img.shields.io/badge/platform-Raspberry%20Pi-red)](https://www.raspberrypi.com/)

**Inky Studio** turns a Raspberry Pi + a [Pimoroni Inky Impression](https://shop.pimoroni.com/products/inky-impression-7-3) display into a digital photo frame you manage entirely from your phone or laptop's browser. Images are converted **in the browser** (HEIC decode, resize, palette mapping, Floyd–Steinberg dithering), so the Pi only ever receives a small, ready-to-display PNG.

```
┌─────────────────────────┐         ┌──────────────────────────────┐
│  Browser (phone/laptop) │         │  Raspberry Pi                │
│  • HEIC decode (WASM)    │  PNG    │  • FastAPI + Inky driver     │
│  • palette + dithering   │ ──────► │  • SQLite (queue + history)  │
│  • live e-ink preview    │ ~200 KB │  • serves the built web app  │
└─────────────────────────┘         └──────────────────────────────┘
```

## Highlights

- 🖼️ **Browser-side conversion** with a **live preview** of the exact e-ink result before you upload.
- 📥 Drag-and-drop **upload**, a reorderable **queue**, scheduled rotation (daily / interval / manual), and a browsable **history**.
- 🔄 **One-click in-app updates** — a button in Settings downloads the latest release and restarts the app for you.
- 🔌 **One-line install** that handles SPI, dependencies, the service, and first-boot setup.
- 🔒 Single-password auth (the password is shown right on the e-ink screen on first boot). Runs entirely on your LAN — no account, no cloud.

## Supported hardware

Displays are auto-detected via [`inky`](https://github.com/pimoroni/inky):

| Display | Resolution | Colours |
|---|---|---|
| Inky Impression 7.3" | 800×480 | 7 |
| Inky Impression 7.3" (2025) | 800×480 | 6 (Spectra) |
| Inky Impression 13.3" (2025) | 1600×1200 | 6 (Spectra) |

Tested on Raspberry Pi Zero 2 W, 3, 4 and 5 running Raspberry Pi OS (Debian Bookworm or Trixie, 64-bit).

## Install

On the Raspberry Pi:

```bash
curl -fsSL https://raw.githubusercontent.com/mehdi7129/inky-studio/main/install.sh | bash
```

The installer enables SPI/I²C, installs dependencies, downloads the latest prebuilt release, sets up a `systemd` service, and prints the URL + password. On the **first** install it reboots once (after a 10-second, cancellable countdown) so the SPI changes take effect — set `INKY_STUDIO_NO_REBOOT=1` to skip.

When it comes back up, open **`http://<pi-ip>:8000`**. The login password is also rendered on the e-ink display itself on first boot, and stored in `/var/lib/inky-studio/credentials.json`.

> The installer downloads a **prebuilt release** (the frontend is built in CI), so the Pi needs no Node.js and no on-device build. To build from the latest `main` instead, run it with `INKY_STUDIO_CHANNEL=source`.

## Updating

- **In the app:** open **Settings → Update** and click the button. Inky Studio downloads the latest release, swaps it in, and restarts — the page reloads automatically when it's back. Progress is shown live.
- **From the CLI:** `inky-studio update`

## Configuration

Pass these as environment variables to the installer:

| Variable | Default | Purpose |
|---|---|---|
| `INKY_STUDIO_CHANNEL` | `release` | `release` (prebuilt) or `source` (build from `main`) |
| `INKY_STUDIO_USER` | `pi` | Service user |
| `INKY_STUDIO_INSTALL_DIR` | `/home/<user>/inky-studio` | Install directory |
| `INKY_STUDIO_DATA_DIR` | `/var/lib/inky-studio` | Photos + credentials |
| `INKY_STUDIO_NO_REBOOT` | – | Set to `1` to never auto-reboot |

## CLI

A small management CLI is installed at `/usr/local/bin/inky-studio`:

```
inky-studio status          # service status
inky-studio logs            # live logs
inky-studio restart         # restart the service
inky-studio welcome         # re-show the welcome screen on the Inky
inky-studio password        # print the current login password
inky-studio reset-password  # generate a new password
inky-studio update          # download & install the latest release
inky-studio info            # paths + URL
```

## Troubleshooting

- **The display never refreshes / "pins in use".** SPI needs the `dtoverlay=spi0-0cs` overlay (the installer adds it) and a reboot. Run `sudo reboot`, then `inky-studio welcome` to test.
- **Can't reach the web UI.** Check the service: `inky-studio status` and `inky-studio logs`. It listens on port `8000`.
- **Forgot the password.** `inky-studio reset-password` prints a new one (and re-shows it on the display).
- **Pi Zero 2 W (512 MB RAM).** The installer adds a 1 GB swap file automatically when needed.

## Development

The display driver auto-falls back to a **mock** off-Pi, so you can develop on macOS/Linux with no hardware.

**Backend** (FastAPI):

```bash
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
inky-studio-server          # http://localhost:8000
ruff check . && pytest
```

**Frontend** (React + Vite):

```bash
cd client
npm install
npm run dev                 # http://localhost:5173 (talks to :8000 via CORS)
npm run lint && npm test && npm run build
```

See [CLAUDE.md](CLAUDE.md) for architecture, conventions, and the release process.

## License

MIT — see [LICENSE](LICENSE). Successor to [inky-photo-frame](https://github.com/mehdi7129/inky-photo-frame).
