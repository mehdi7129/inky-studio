# Changelog

Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).
Versionnement [SemVer](https://semver.org/lang/fr/).

## [Unreleased]

### Added — Phase 1 (Backend coeur)
- Schéma SQLite : tables `photos`, `queue`, `history`, `settings` avec FK cascade et indexes
- `db.py` : connection helpers, init idempotent, support de `INKY_STUDIO_DATA_DIR` pour les tests
- `models.py` : modèles Pydantic v2 (Photo, QueueEntry, HistoryEntry, Settings, DisplayState, etc.)
- Service `photos` : upload + dédupe sha256, validation taille/format, stockage filesystem dans `data/photos/`
- Service `queue` : add/remove/reorder/pop_next/count, robuste aux clients stales
- Service `history` : append-only log, `current()`, `previous_to()`, recyclage `oldest_unique_*` pour queue vide
- Service `settings` : key/value typé sur SQLite, defaults Settings()
- Service `scheduler` : tâche asyncio, 3 modes (daily/interval/manual), recyclage automatique
- `DisplayController.display_image(path)` : pousse vers le hardware en prod, logge en mock
- `EventBus` : broadcast in-process pour fan-out WebSocket (drop si subscriber lent)
- Endpoints REST : `/api/state`, `/api/queue` (list/upload/delete/reorder), `/api/display/next|previous`, `/api/history`, `/api/settings` (GET/POST), `/api/photos/{id}`
- WebSocket `/api/ws` : événements `display_changed`, `queue_updated`, `settings_changed`, `photo_uploaded`, `photo_deleted`
- Tests : 50 tests pytest (services + endpoints + WebSocket), 0 échec, 0.6s

### Added — Phase 0.1 (Recon du hardware)
- Mock display ajusté pour matcher le hardware réel : Inky 7.3" 2025 Spectra 6 (800×480, 6 couleurs)
- `shared/palettes.json` — palette Spectra calibrée extraite du déploiement de prod, prête à être consommée par le frontend en Phase 2
- ROADMAP enrichi avec les contraintes hardware confirmées (Pi Zero 2 W, RAM, conflit service)

### Added — Phase 0 (Scaffolding)
- Structure du repo : `server/` (FastAPI), `client/` (React + Vite), doc racine
- Backend : skeleton FastAPI avec endpoint `/api/health` et `/api/display`
- Display controller avec mock auto-activé sur non-Linux (dev Mac)
- Frontend : projet Vite + React + TypeScript + Tailwind, page d'accueil qui ping le backend
- Tests : `pytest` smoke test sur health + display state
- Documentation : `README.md`, `ROADMAP.md` détaillant les 7 phases, `LICENSE` MIT
