# Changelog

Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).
Versionnement [SemVer](https://semver.org/lang/fr/).

## [Unreleased]

### Added — Phase 0 (Scaffolding)
- Structure du repo : `server/` (FastAPI), `client/` (React + Vite), doc racine
- Backend : skeleton FastAPI avec endpoint `/api/health` et `/api/display`
- Display controller avec mock auto-activé sur non-Linux (dev Mac)
- Frontend : projet Vite + React + TypeScript + Tailwind, page d'accueil qui ping le backend
- Tests : `pytest` smoke test sur health + display state
- Documentation : `README.md`, `ROADMAP.md` détaillant les 7 phases, `LICENSE` MIT
