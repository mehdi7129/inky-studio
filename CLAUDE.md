# CLAUDE.md

Guidance for Claude Code (and human contributors) working in this repository.

## What this is

Inky Studio is a self-hosted web app that drives a Pimoroni Inky Impression
e-ink display on a Raspberry Pi. The browser only decodes (HEIC) and **crops** the
photo to the panel resolution (full colour); all colour science is done **once on
the Pi** by the official Pimoroni `inky.set_image(saturation=0.5)`, which quantises
to the exact palette of the auto-detected panel. There are **no app-level colour
modes** — rendering adapts to the detected screen automatically.

## Layout

```
server/                 FastAPI backend (Python 3.11+)
  inky_web/
    main.py             app factory, AuthMiddleware, SPA static mount, run()
    auth.py             single-password auth, session cookie, require_auth dep
    events.py           in-process EventBus (broadcast → WebSocket fan-out)
    db.py               SQLite init + data_dir()
    models.py           Pydantic schemas
    api/                one APIRouter per area (auth, state, queue, display,
                        history, settings, photos, system, ws)
    services/           business logic (queue, history, scheduler, settings,
                        photos, updater)
    inky/               display controller (+ off-Pi mock); set_image passthrough
    welcome.py          renders the first-boot welcome screen
  tests/                pytest suite (display is mocked; no hardware needed)
client/                 React 19 + TypeScript + Vite 8 + Tailwind 4 frontend
  src/lib/api.ts        fetch wrappers (cookie auth via credentials:'include')
  src/lib/useWebSocket.ts  auto-reconnecting WS hook
  src/lib/converter/    decode (HEIC) + transform (crop) + encode (PNG) — no dither
  src/components/       Layout + Dashboard/Queue/Settings/History panels
scripts/                inky-studio-cli (management CLI), uninstall.sh
install.sh              one-line installer (repo root)
.github/workflows/      ci.yml (lint/test/build), release.yml (tag → tarball)
```

## Dev commands

Backend (works off-Pi — the display driver auto-mocks):

```bash
cd server
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"     # ".[pi]" only installs on a real Pi
inky-studio-server          # serves on :8000
ruff check . && pytest
```

Frontend:

```bash
cd client
npm install
npm run dev                 # :5173, talks to :8000 via CORS
npm run lint && npx tsc -b && npm test && npm run build
```

CI (`.github/workflows/ci.yml`) runs exactly these on every push/PR. Keep them green.

## Conventions

- Backend: Pydantic models for all request/response bodies. New routes go in a
  file under `api/` and are registered in `api/__init__.py`. `/api/*` is
  auth-gated by `AuthMiddleware`; only paths in `auth.PUBLIC_PATHS` are open.
  Emit UI updates with `request.app.state.bus.broadcast("<event_type>", payload)`
  and add the type to the `EventType` literal in `events.py`.
- Frontend: add API calls in `lib/api.ts` (reuse `getJSON`/`sendJSON`). Subscribe
  to backend events via `useWebSocket((event) => …)`. Styling is Tailwind, with
  `dark:` variants. The app UI is in **French**; repo docs are in **English**.
- Ruff and ESLint must pass with zero errors.

## How install & update work

The Pi runs **prebuilt releases** — the frontend is built in CI, never on the
device, so the Pi needs no Node.js at runtime.

- **`install.sh`** (one-liner): installs apt deps (incl. `python3-dev` +
  `build-essential` for the `spidev`/`RPi.GPIO` C extensions), enables SPI/I²C,
  adds `dtoverlay=spi0-0cs` to free GPIO8 for the Inky library, adds swap on
  low-RAM Pis, downloads the latest release tarball (or builds from source with
  `INKY_STUDIO_CHANNEL=source`), creates the venv + `systemd` unit, installs a
  **scoped sudoers** rule (`/etc/sudoers.d/inky-studio`) allowing the service
  user to `systemctl start/stop/restart inky-studio.service` only, and reboots
  once on first install.
- **`services/updater.py`** powers both the in-app one-click update
  (`POST /api/system/update`, streaming `system_update` WS events) and the
  `inky-studio update` CLI (`python -m inky_web.updater`). It downloads the
  latest release asset, extracts it over the install dir (preserving `.venv`),
  runs `pip install -e .[pi]`, and restarts via the scoped sudo rule.

## Releasing

The installer and updater pull the **latest GitHub Release**, so shipping is:

1. Bump `version` in `server/pyproject.toml` and `__version__` in
   `server/inky_web/__init__.py` (keep them in sync).
2. Add a `CHANGELOG.md` entry.
3. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`.
4. `release.yml` builds the frontend, bundles `inky-studio-vX.Y.Z.tar.gz`
   (server source + `client/dist` + `shared` + `scripts` + `install.sh`), and
   publishes the GitHub Release. Existing installs can then update with one click.

## Hardware notes

- The `inky` package is pinned to `2.3.0`: `2.4.0` re-claims SPI/GPIO on every
  `show()` and aborts. Don't bump without testing on real hardware.
- Newer Inky panels need `dtoverlay=spi0-0cs` (no kernel chip-select on SPI0)
  or the first refresh fails with "pins in use" on GPIO8.
- Off-Pi, `DisplayController` falls back to a mock (no SPI/GPIO required).
