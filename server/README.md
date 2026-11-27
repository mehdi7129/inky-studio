# Inky Studio — Backend

FastAPI service that drives the Inky display and serves the React frontend.

## Current frame service

This repository publishes the **0.5.0rc5** PHOTO service source and a Python wheel
for local qualification with iOS 1.0.1 (20). The distributed
[InkyOS image](https://github.com/mehdi7129/inkyOS/releases/tag/2026.11.27-rc3)
contains **0.5.0rc4** and the Pimoroni auto-detection profile.
See [LAN configuration](../docs/IMAGER-LAN.md), the [PHOTO API](../docs/PHOTO-API.md)
and the [release notes](../docs/releases/ios-v1.0.1-build20.md).

Use InkyOS maintenance procedures for an installed frame. After a confirmed
owner session retires an older bootstrap, reverting to a service that cannot
read that credential format requires local recovery.

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

This installs the Pimoroni `inky` **2.6.0** driver. The multi-display Imager
image selects `INKY_STUDIO_DISPLAY_MODE=hardware` and
`INKY_STUDIO_DISPLAY_PROFILE=pimoroni-auto`. The profile checks the driver,
EEPROM variant and native size for Impression, Spectra, wHAT and pHAT. It
requires a readable, supported EEPROM. BUSY observation is tailored to AC073,
UC8159 and the three Spectra driver families. Software checks use simulated
GPIO and SPI. Physical refresh and camera scanning still need hardware tests.

Hardware errors remain latched until an operator has checked the frame and
restarted the service. `/api/state`, `/api/display`, uploads and display actions
then return **503** with a French `detail` and a stable error `code`; queue and
history are not acknowledged as successfully displayed. Authenticated operators
can still read `/api/display/status`, including during a refresh.

The auto profile keeps the established timed wait only for the verified
800×480 AC073 variant 20 and EEPROM colors 4 or 5. Color 4 stays uninterpreted.
The legacy explicit profiles remain available to the bench.

## Tests

```bash
pip download --no-deps --require-hashes -r tests/fixtures/inky_250_requirement.txt -d .test-wheels
pip download --no-deps --require-hashes -r tests/fixtures/inky_260_requirement.txt -d .test-wheels
pytest
```

Install `.[dev]` first. For the pinned qualification environment on macOS arm64/Python 3.14, install with `pip install -c constraints-qualification.txt -e ".[dev]"`. The driver tests load the SHA-256/RECORD-verified official
wheels from this cache, with real NumPy/Pillow and simulated GPIO/SPI ports.
Pytest does not download dependencies or touch hardware.
