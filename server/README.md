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

## Resource limits

HTTP request bodies are limited to **11 MiB**, including the multipart envelope.
The existing queue limit remains **10 MiB per PNG**. An oversized declared body
is rejected before reading it; streamed bodies are counted as they arrive and
stopped at the first chunk crossing the limit. The response is HTTP 413 with a
JSON `detail`. Partial multipart files are closed, and HTTP/1.x connections are
closed without draining the rest of the body. These limits apply to both HTTP
and HTTPS. Authentication still runs first for protected routes.

The release updater limits downloaded archives to **64 MiB**, release API JSON
to **1 MiB**, and archive contents to **10,000 headers / 512 MiB of file data**.
Archive limits are checked immediately after each fixed-size header, before
extension metadata can be read. Downloads are counted even without a truthful
`Content-Length`; incomplete downloads are removed.

Release archives must contain only regular files and directories. The packaging
script uses **USTAR** and validates the complete archive with the updater before
making it available to the release workflow. PAX, GNU long-name and sparse
extensions are rejected; ordinary GNU headers without extensions are accepted.
Previously published assets have not all been checked against this stricter
contract. The CI packaging check must pass before publishing a new release.

These are per-request and per-archive bounds, not aggregate disk quotas or an
atomic deployment guarantee. See the [resource-limit follow-up audit](../docs/audits/2026-10-02-resource-limits.md).
