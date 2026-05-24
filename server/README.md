# Inky Studio — Backend

FastAPI service that drives the Inky display and serves the React frontend.

## Run locally (Mac/dev)

```bash
cd server
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
inky-studio-server
```

Then open http://localhost:8000/api/health — should return `{"status":"ok"}`.

On macOS, the display driver auto-falls back to a **mock** that pretends to be
an Inky Impression 7.3" — no hardware required for development.

## Run on the Raspberry Pi

```bash
pip install -e ".[pi]"
```

This installs the real Pimoroni `inky` driver. The controller auto-detects the
connected display (7.3" classic / 7.3" 2025 / 13.3" 2025).

## Tests

```bash
pytest
```
