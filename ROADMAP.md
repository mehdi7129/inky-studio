# Roadmap — Inky Studio v1.0

Détail des 7 phases qui mènent au MVP. Chaque phase produit un livrable testable.

---

## Phase 0 — Scaffolding ✅

**Objectif** : repo prêt à recevoir du code, structure cohérente, smoke tests qui passent.

**Livrables**
- `server/` — projet Python FastAPI avec mock display, test `/api/health` qui passe
- `client/` — projet React + Vite + Tailwind + TS, page d'accueil qui ping `/api/health`
- `README.md`, `ROADMAP.md`, `LICENSE`, `CHANGELOG.md`, `.gitignore`
- Repo GitHub public créé + premier commit

---

## Phase 1 — Backend coeur

**Objectif** : l'API expose l'état de l'écran, accepte des uploads, gère une queue et un scheduler.

**Endpoints**
- `GET  /api/health`
- `GET  /api/display` — modèle, résolution, couleurs, mode couleur actuel
- `GET  /api/queue` — liste des photos en attente
- `POST /api/queue` — ajouter une photo (PNG converti) à la queue
- `DELETE /api/queue/{id}` — retirer une photo
- `POST /api/queue/reorder` — réordonner
- `POST /api/display/next` — passer à la photo suivante
- `POST /api/display/previous` — revenir en arrière
- `GET  /api/history` — photos déjà affichées
- `GET  /api/settings` / `POST /api/settings` — color_mode, schedule
- `WS   /api/ws` — état temps réel (image actuelle, prochain changement, progression conversion serveur)

**Persistance** : SQLite (`server/data/inky_studio.db`). Schéma : `photos`, `queue`, `history`, `settings`.

**Port du code v2.0** : `display.py`, `buttons.py`, `welcome.py`, `image_processor.py` (sans la pipeline de conversion lourde — déléguée au navigateur).

**Critère d'acceptance** : `pytest` passe avec >80% de couverture sur les services.

---

## Phase 2 — Frontend coeur (conversion image)

**Objectif** : un utilisateur peut sélectionner une photo, la voir convertie en preview, et l'envoyer au Pi.

**Pipeline conversion (dans le browser)**
1. `<input type="file">` accepte JPEG, PNG, **HEIC**, WebP
2. Decode HEIC via `libheif-js` (WASM, lazy-loaded ~2 Mo)
3. Resize à la résolution cible (récupérée depuis `/api/display`)
4. Crop interactif (slider position + zoom)
5. Application de la palette du modèle (Pimoroni / Spectra)
6. Floyd-Steinberg dithering en JS (ou Web Worker si > 100 ms)
7. Preview live dans un `<canvas>` côté à côte avec l'original
8. Validation → POST `/api/queue` avec le PNG final

**Choix techniques**
- Pas de lib de dithering existante satisfaisante → algo custom (~150 lignes TS)
- Palettes constantes en JSON : `client/src/lib/converter/palettes.json`
- Web Worker pour ne pas freezer l'UI sur le 13.3" (1600×1200 = 1.9M pixels)

**Critère d'acceptance** : convertir une HEIC iPhone 4032×3024 en <3 s sur iPhone 12, preview pixel-accurate vs ce que produit Pillow côté serveur.

---

## Phase 3 — Dashboard

**Objectif** : page d'accueil qui affiche l'état complet de l'écran.

**Maquette**
```
+------------------------------+--------------------+
| [    photo actuelle      ]   | Inky 13.3"         |
| [                        ]   | 1600×1200          |
| [                        ]   | 6 couleurs Spectra |
| [                        ]   | Mode: spectra      |
+------------------------------+ Prochain : 5h00    |
| Suivantes en file (3) →      | Queue: 8 photos    |
| [thumb][thumb][thumb] ...    +--------------------+
+----------------------------------------------------+
```

**Critère d'acceptance** : reflet WebSocket en temps réel quand la photo change (test : déclencher `/api/display/next`, dashboard se met à jour <1s).

---

## Phase 4 — Gestion de file

**Objectif** : drag & drop pour réordonner, bouton supprimer par photo, next/previous.

**Lib** : `@dnd-kit/core` (accessible, tactile-friendly).

**Critère d'acceptance** : réorder persiste après refresh ; supprime une photo → elle disparaît de la queue et l'ordre reste cohérent.

---

## Phase 5 — Settings avancés

**Objectif** : tout configurable depuis l'UI.

**Sections**
- **Mode couleur** : 3 boutons (pimoroni / spectra_palette / warmth_boost) avec preview du dernier upload appliqué
- **Schedule** : fréquence (manuelle, toutes les heures, 1×/jour à HH:MM)
- **Historique** : galerie paginée avec date d'affichage, bouton "remettre en queue"

**Critère d'acceptance** : changer le color_mode rerender la preview du dashboard.

---

## Phase 6 — Auth + Installer

**Objectif** : le projet s'installe en une commande sur un Pi propre.

**Auth**
- Mot de passe alphanumérique 10 caractères généré à l'installation
- Stocké dans `/etc/inky-studio/credentials` (mode 600)
- Affiché sur l'écran d'accueil Inky (port du `welcome.py`)
- Cookie de session signé (clé dans `/etc/inky-studio/secret`)
- Rate limiting basique (5 essais / minute)

**Installer**
- `scripts/install.sh` — clone repo, crée venv, installe deps (mode `[pi]`), build le client (npm install + build), service systemd `inky-studio.service`
- `scripts/update.sh` — pull + rebuild + restart
- `scripts/uninstall.sh`
- CLI wrapper `inky-studio` avec sous-commandes `status`, `logs`, `restart`, `reset-password`

**Critère d'acceptance** : sur un Pi neuf avec Raspberry Pi OS, `curl -sSL .../install.sh | bash` produit un service qui démarre au boot.

---

## Phase 7 — Polish + release v1.0

- Captures d'écran, GIF démo dans le README
- CHANGELOG complet
- Tag `v1.0.0`, release GitHub
- Documentation des palettes (palette JSON commentée + comparaison entre modes)
- Annoncer sur le repo `inky-photo-frame`

---

## 🔍 Contraintes matérielles confirmées (recon Pi 2026-05-24)

Validées en lisant l'environnement du Pi de prod :

| Contrainte | Valeur | Conséquence sur le plan |
|---|---|---|
| Hardware | Raspberry Pi Zero 2 W (aarch64) | RAM limitée — éviter tout process Python lourd côté serveur |
| RAM totale | 416 Mo (200 Mo libres avec service actuel en marche) | FastAPI + Uvicorn + SQLite doivent rester < 100 Mo. Pas de modèle ML, pas de cache image en RAM > 20 Mo. |
| Python | 3.11.2 (système, OK) | Compatible avec `requires-python = ">=3.11"` |
| Inky lib | v2.3.0 | Pin dans `pyproject.toml [pi]` |
| Écran réel | Inky Impression 7.3" (2025 Spectra 6) — 800×480 | Mock backend ajusté à ce modèle. Le 13.3" reste supporté mais non testé en prod. |
| Port 8000 | Libre | OK pour FastAPI |
| Samba (139, 445) | Actif | Sera désactivé par l'installer en Phase 6 (option), ou laissé tourner si l'utilisateur veut le garder |
| Service systemd actuel | `inky-photo-frame.service` actif | **Conflit hardware** : un seul process peut piloter l'Inky. L'installer Phase 6 DOIT `systemctl disable --now inky-photo-frame` avant d'activer `inky-studio.service`. À documenter dans les release notes. |
| Code déployé | Pas de `.git` (curl via update.sh) | L'installer Phase 6 fera pareil : `git clone --depth=1` puis `npm install && npm run build` |
| Photos actuelles | `/home/pi/Images/` (gérées par v2.0) | Phase 6 : option "importer la queue existante" pour migration douce |
| Credentials Samba | `/home/pi/.inky_credentials` | Phase 6 réutilise ce pattern : `/etc/inky-studio/credentials` (mode 600) |

## Hors-scope v1.0 (peut-être v1.1+)

- Multi-écrans (plusieurs Pi pilotés depuis une UI centrale)
- Albums Google Photos / Apple Photos
- Edit avancé (filtres, recadrage non-linéaire)
- PWA installable offline
- Accès distant via tunnel Cloudflare
