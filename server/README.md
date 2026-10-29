# Inky Studio — Backend

FastAPI service that drives the Inky display and serves the React frontend.

## Current frame service

The current LAN service is0.5.0rc2 from716104. It is included in the
[generic InkyOS prerelease](https://github.com/mehdi7129/inkyOS/releases/tag/2026.10.29-rc1),
with inky2.5.0 and the explicit AC073 profile. The maintainer's existing frame was
updated25/10 and photo sharing is confirmed; the new generic image's first
physical boot is a separate pending qualification. See [IMAGER-LAN](../docs/IMAGER-LAN.md)
and [current provenance](../docs/releases/ios-v1.0.0-build19.json). The hardware
migration notes below retain their original diagnostic scope; old2.3 TEST images
and other screen families are not the current reference installation.

## Run locally (Mac/dev)

```bash
cd server
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
INKY_STUDIO_DISPLAY_MODE=mock inky-studio-server
```

Then open http://localhost:8000/api/health — the response includes `status: "ok"`
and the server version. This indicates service availability, not panel health.

`INKY_STUDIO_DISPLAY_MODE=auto` (default) selects hardware on Linux and a **mock**
elsewhere. `mock` explicitly prevents hardware imports/access on every platform.
`hardware` never turns an initialization/refresh failure into simulated success.

## Run on the Raspberry Pi

```bash
pip install -e ".[pi]"
```

This installs the pinned Pimoroni `inky` driver. The installer selects
`INKY_STUDIO_DISPLAY_MODE=hardware`. Autodetection selects a driver; it does not
establish physical qualification. This source candidate pins **2.5.0** and has
separate BUSY contracts for AC073, UC8159 and the three Spectra families.
The existing 2.3.0 TEST payload is a distinct artifact. A new native dependency
closure and physical qualification are required before deployment; see
[the migration contract](../docs/inkyos/DISPLAY-DRIVER-250.md).

Hardware errors remain latched until an operator has checked the frame and
restarted the service. `/api/state`, `/api/display`, uploads and display actions
then return **503** with a French `detail` and a stable error `code`; queue and
history are not acknowledged as successfully displayed. Authenticated operators
can still read `/api/display/status`, including during a refresh.

The reviewed 800×480 / variant 20 / raw color 4 bench additionally requires
`INKY_STUDIO_DISPLAY_PROFILE=ac073-800x480`. Color 4 remains uninterpreted; there
is no EEPROM write or driver override. See the [candidate contract](../docs/inkyos/HARDWARE-CANDIDATE.md)
for scope, diagnostics and physical qualification limits.

## Tests

```bash
pip download --no-deps --require-hashes -r tests/fixtures/inky_250_requirement.txt -d .test-wheels
pytest
```

Install `.[dev]` first. The driver tests load the SHA-256/RECORD-verified official
wheel from this cache, with real NumPy/Pillow and simulated GPIO/SPI ports.
Pytest does not download dependencies or touch hardware.
