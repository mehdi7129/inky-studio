# Inky Studio

> Web UI pour piloter un cadre photo e-ink Inky depuis n'importe quel navigateur — local, sans cloud.

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-Phase%200%20%28scaffolding%29-orange)]()
[![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi-red)](https://www.raspberrypi.org/)

**Inky Studio** est une interface web auto-hébergée sur le Raspberry Pi qui pilote un écran [Inky Impression](https://shop.pimoroni.com/products/inky-impression-7-3). Conçue pour remplacer le partage Samba par une UX moderne avec **conversion d'image côté navigateur**.

## ✨ Ce qui change par rapport à l'approche Samba

| Avant (Samba) | Avec Inky Studio |
|---|---|
| Drag photo brute (5-20 Mo) | Photo convertie en navigateur (~200 Ko) |
| Pi convertit à l'affichage | Pi reçoit du déjà-prêt |
| Pas de preview | Preview live du rendu e-ink avant upload |
| Config par SSH + restart | Tout depuis le navigateur |
| iPhone : app Fichiers | iPhone : web app |

## 🎯 Écrans supportés

Auto-détection via [`inky.auto`](https://github.com/pimoroni/inky) :

| Modèle | Résolution | Couleurs |
|---|---|---|
| Inky Impression 7.3" | 800×480 | 7 |
| Inky Impression 7.3" (2025) | 800×480 | 6 (Spectra) |
| Inky Impression 13.3" (2025) | 1600×1200 | 6 (Spectra) |

## 🚧 Statut

Le projet est en **Phase 0 — scaffolding**. La feuille de route complète est dans [ROADMAP.md](ROADMAP.md).

- [x] Phase 0 — Scaffolding repo (backend + frontend + doc)
- [ ] Phase 1 — Backend coeur (API, queue, scheduler, WebSocket)
- [ ] Phase 2 — Frontend coeur (HEIC decode + palette + dither + preview)
- [ ] Phase 3 — Dashboard (image actuelle + specs)
- [ ] Phase 4 — Gestion de file (réorder, next/prev)
- [ ] Phase 5 — Settings avancés (color mode, schedule, historique)
- [ ] Phase 6 — Auth + installer
- [ ] Phase 7 — Polish + release v1.0

## 🏗️ Architecture

```
[ Browser ]                            [ Raspberry Pi ]
React SPA                              FastAPI + Inky driver
  • libheif-js (HEIC decode)             • REST + WebSocket
  • Canvas palette + Floyd-Steinberg     • SQLite (queue + history)
  • Preview live                         • Static files (React build)
       │                                       ▲
       └── upload PNG ~200 Ko ─── HTTP ────────┘
```

La conversion image se fait **à 100% dans le navigateur**. Le Pi ne reçoit que des PNG déjà à la résolution finale, avec la palette du modèle déjà appliquée.

## 🛠️ Développement

### Backend (Mac ou Linux)

```bash
cd server
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
inky-studio-server          # http://localhost:8000
pytest                      # tests
```

Sur Mac, le driver Inky se replie automatiquement sur un **mock** — pas besoin de matériel pour développer.

### Frontend

```bash
cd client
npm install
npm run dev                 # http://localhost:5173
```

Le frontend en dev parle au backend via CORS (origines autorisées : `http://localhost:5173`).

### Build production

```bash
cd client && npm run build      # → client/dist/
cd ../server && inky-studio-server   # FastAPI sert client/dist/ sur /
```

## 📦 Installation sur le Raspberry Pi

> ⏳ Disponible à la Phase 6. En attendant, voir [ROADMAP.md](ROADMAP.md).

## 🔗 Projet parent

Inky Studio est la suite logique de [inky-photo-frame](https://github.com/mehdi7129/inky-photo-frame) (qui continue d'exister pour les utilisateurs de Samba).

## 📄 Licence

MIT — voir [LICENSE](LICENSE).
