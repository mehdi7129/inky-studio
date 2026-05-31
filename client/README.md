# Inky Studio — Frontend

React 19 + TypeScript + Vite 8 + Tailwind 4 single-page app. All image
conversion (HEIC decode, resize, palette mapping, Floyd–Steinberg dithering)
runs here in the browser; the backend only stores and displays the result.

## Develop

```bash
npm install
npm run dev        # http://localhost:5173 — talks to the backend on :8000 via CORS
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
