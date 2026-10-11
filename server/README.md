# Inky Studio — Backend

FastAPI service that drives the Inky display and serves the React frontend.

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
establish physical qualification. The AC073 busy observer targets **2.3.0** only.

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
pytest
```
