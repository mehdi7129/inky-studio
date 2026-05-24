# Changelog

Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).
Versionnement [SemVer](https://semver.org/lang/fr/).

## [Unreleased]

### Added — Phase 6 (Auth + Welcome + Installer)
- **Auth backend** : `auth.py` + `api/auth.py`. Password 10 chars alphanumériques généré à la première init et persisté dans `<data>/credentials.json` (mode 600). Session in-memory avec cookie HttpOnly SameSite=Strict (TTL 30 jours). Rate limiting login : 5 tentatives / IP / minute. `AuthMiddleware` bloque `/api/*` sauf `/api/health`, `/api/auth/status`, `/api/auth/login`. `INKY_STUDIO_DISABLE_AUTH=1` pour les tests.
- **Frontend login** : `LoginScreen` avec mot de passe, gestion erreurs, redirect post-login. Bouton "Déconnexion" dans le header. Bootstrap : check /api/auth/status au load → login screen ou app selon état.
- **Welcome screen** : `welcome.py` rend une image PIL avec titre "Inky Studio" + URL `http://<ip>:8000` + mot de passe + hint. Polices DejaVu (Linux) avec fallback macOS. Couleurs Spectra-friendly (bleu `#2040b8`, rouge `#a02020`). Mock mode sauve un preview PNG dans le data dir au lieu de pousser sur l'écran.
- **Installer Pi** (`scripts/install.sh`) :
  - Idempotent (clone OU update), désactive proprement `inky-photo-frame.service` (conflit SPI)
  - apt install : git, python3-venv, nodejs, npm, fonts-dejavu
  - Clone repo → /home/pi/inky-studio, venv .[pi], npm install + build
  - Data dir `/var/lib/inky-studio` (chown pi:pi)
  - systemd unit `inky-studio.service` (Type=simple, User=pi, Restart=on-failure)
  - Pousse le welcome screen sur l'Inky une fois en place
  - Affiche URL + password à la fin
- **CLI** `inky-studio` (status / logs / restart / welcome / password / reset-password / update / info / help) installé dans `/usr/local/bin/`
- **Uninstaller** (`scripts/uninstall.sh`) : stop + disable le service, restaure l'ancien service v2.0 si présent, préserve photos et credentials

### Added — Phase 3+4+5 (Dashboard, Queue mgmt, Settings, Historique)
- **Layout à onglets** : Tableau de bord / File d'attente / Paramètres / Historique. Header sticky avec specs écran + badge de queue count.
- **Dashboard** : hero card avec l'image actuellement affichée (à grande taille) + métadonnées (nom, date, source, taille). Panneau latéral avec specs écran (modèle, résolution, couleurs, mode, queue, prochain changement). Boutons globaux ← Précédente / Suivante →. Aperçu de la file (6 premières photos).
- **Queue panel** : liste réordonnable par **drag & drop** (@dnd-kit), suppression par photo, vue numérotée. Optimistic UI sur le reorder (rollback si l'API échoue).
- **Settings panel** : 3 radios mode couleur (Spectra recommandé / Warmth boost / Pimoroni 7c) + 3 radios fréquence (Quotidien avec heure, Intervalle avec minutes, Manuel). Save automatique au moindre changement.
- **Historique** : galerie paginée des photos affichées avec date relative ("il y a 2 min"), source (next/prev/auto/recycle/upload), bouton "Remettre en file" qui re-poste le PNG via /api/queue.
- **WebSocket-driven refresh** : tous les changements backend (queue_updated, display_changed, settings_changed, photo_uploaded, photo_deleted) déclenchent un refetch automatique des states. Fix : proxy Vite `/api/ws` configuré spécifiquement comme WebSocket (avant, le matcher `/api` HTTP attrapait /api/ws en HTTP).
- **Helpers UI** : `formatRelative`, `formatAbsolute`, `formatBytes` — labels lisibles ("il y a 2 min", "24 mai, 18:19", "131 Ko").
- Refresh toutes les minutes pour garder les labels relatifs frais.

### Added — Phase 2.5 (Polish + perf depuis test E2E navigateur)
- **Perf majeure : cache de la bitmap décodée** (3 169 ms → 56 ms sur HEIC, 60× plus rapide). Re-conversions instantanées au moindre tweak de mode couleur ou slider.
- `convertBitmap()` séparé de `convert(file)` : la décode coûteuse ne se refait plus à chaque changement
- `originalImage` retourné par `convertBitmap` : plus de double décode pour la preview originale
- UX post-upload : le panel reste visible avec "✓ Ajoutée à la file · 195 Ko envoyés" et un bouton "Envoyer une autre photo" — l'utilisateur voit le succès au lieu d'être renvoyé brutalement à l'écran d'accueil
- WebSocket auto-refresh : `useWebSocket` hook se connecte à `/api/ws`, queue se met à jour live sur `queue_updated` / `photo_uploaded`. Backoff exponentiel pour reconnect (500ms → 30s).
- Hint dimensions source : "4032×3024 → 800×480" affiché à côté du nom du fichier
- États visibles pendant la conversion : "Décodage HEIC (1ère fois ~1-2 s)…" / "Conversion (resize + dither)…" / "Mise à jour du rendu…" — l'utilisateur ne se demande plus si ça plante
- vitest.config.ts dédié avec `isolate: false` (les workers Vitest 4 timeout sur boot froid de jsdom — singleton context boot en 620ms au lieu de 60+ s)
- Tests vitest : 7/7 toujours OK après refactor

### Added — Phase 2 (Conversion image dans le navigateur)
- **Pipeline conversion client-side** : decode (HEIC/JPEG/PNG/WebP) → resize+cover-crop → optional warmth → Floyd-Steinberg dithering → PNG. Le serveur reçoit du déjà-prêt.
- `lib/converter/palettes.ts` : typage strict + import de `@shared/palettes.json` (source unique avec le backend)
- `lib/converter/decode.ts` : HEIC via `heic2any` lazy-loaded (WASM 1.35 Mo seulement quand HEIC est uploadé)
- `lib/converter/transform.ts` : resize + center crop "cover" avec décalage configurable (-1 à +1 sur X et Y)
- `lib/converter/dither.ts` : Floyd-Steinberg custom (~140 lignes), nearest-color avec distance Euclidean RGB + applyWarmth pour le mode `warmth_boost`
- `lib/converter/encode.ts` : PNG via OffscreenCanvas (avec fallback `<canvas>`)
- `lib/converter/worker.ts` : Web Worker qui exécute le dither hors du main thread (préserve la fluidité UI sur 1.9 MP / 13.3")
- `lib/converter/pipeline.ts` : orchestre tout, instantie le Worker une fois, mesure la durée totale
- **UI** :
  - `Uploader` : drag & drop + file picker (JPEG/PNG/HEIC/WebP)
  - `PreviewCanvas` : affichage ImageData avec image-rendering pixelated
  - `ConverterPanel` : side-by-side original vs rendu e-ink, slider décalage X/Y, switch mode couleur, bouton Envoyer
  - `App` : refonte avec dashboard minimal (modèle + résolution + file d'attente avec thumbnails)
- Vite : alias `@shared`, proxy `/api` + `/ws`, format ES pour worker
- Tests : 7 tests vitest sur `dither` (snap noir/blanc, palette-only, préservation tons moyens, alpha, applyWarmth)
- Build : main bundle 66 Ko gzip · heic2any code-split en chunk séparé (344 Ko gzip, lazy-loaded)

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
