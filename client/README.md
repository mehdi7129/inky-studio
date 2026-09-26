# Inky Studio — Frontend

React 19 + TypeScript + Vite 8 + Tailwind 4 single-page app. HEIC decoding,
resizing and cropping run in the browser. The Raspberry Pi performs colour
quantisation once, using the official Pimoroni driver for the detected panel.

## Develop

```bash
npm ci
npm run dev        # http://localhost:5273 — proxies /api to the backend on :8000
```

## Checks & build

```bash
npm run lint
npx tsc -b
npm test           # vitest
npm run build      # → dist/  (served by the FastAPI backend in production)
```

In production the built `dist/` is bundled into the release tarball and served
by the backend; you never build this on the Raspberry Pi. See the root
[README.md](../README.md) and [CLAUDE.md](../CLAUDE.md).
