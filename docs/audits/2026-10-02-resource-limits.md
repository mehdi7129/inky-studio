# Suivi de stabilisation — limites HTTP et updater

**2 octobre 2026.** Baseline : `39fa57d882e80b78976c7027656537aea9b91d2e`,
branche `codex/ios-demo-onboarding` de la PR #12. Ce correctif traite les limites
de ressources encore signalées dans les audits du 26 septembre et du
[1 octobre](2026-10-01-release-audit.md). Le code iOS, le design Bento et les
versions du produit restent identiques à cette baseline.

## Constats reproduits et corrections

| Constat confirmé sur la baseline | Correction et preuve de non-régression |
| --- | --- |
| Le plafond de 10 MiB d'une photo est vérifié après parsing multipart. Une requête de **13 631 604 octets** est entièrement consommée en 15 chunks et spoolée avant la réponse 413. | Middleware ASGI : corps HTTP limité à **11 MiB**, enveloppe incluse ; longueur déclarée excessive rejetée avant lecture ; compteur des octets réels sans drainage après dépassement. Le scénario corrigé ferme le tempfile après 10 MiB écrits, sans photo ni événement créé. Un PNG valide de 10 MiB avec son enveloppe reste accepté. |
| Le téléchargement de release accepte **67 108 865 octets**, soit 64 MiB + 1, sans plafond effectif. | Lectures de 64 KiB maximum, budget réel de **64 MiB** pour l'archive et **1 MiB** pour le JSON GitHub. Le seuil exact est accepté ; l'octet supplémentaire provoque une erreur et la suppression du fichier partiel. Les tests couvrent longueur absente, sous-déclarée et erreur de lecture. |
| Le nombre et la taille des membres TAR sont vérifiés après `getmembers()` ; les extensions PAX/GNU peuvent déjà avoir alloué leurs données. | Contrôle dans `TarInfo._proc_member`, immédiatement après chaque header de 512 octets et avant traitement des extensions : **10 000 headers / 512 MiB**, tailles négatives et répertoires non vides refusés. Seuls fichiers ordinaires et répertoires sont acceptés. Les spies vérifient le refus avant lecture du corps des extensions. Tous les chemins sont validés avant extraction. |
| La première exécution avec FastAPI 0.115.0 échoue dès l'import de la route `DELETE /api/queue/{photo_id}` : l'annotation `-> None` avec status 204 est refusée. Cette déclaration existait avant le correctif de limites. | La route renvoie explicitement `Response(status_code=204)`, comme les routes history. L'assertion existante vérifie désormais aussi le corps vide ; le contrat HTTP public reste identique. Le job minimum complet passe ensuite. |

L'ordre des middlewares reste **CORS → authentification → limite du corps →
routes**. L'authentification devient ASGI pure pour éviter la lecture concurrente
de fin de réponse de l'ancien `BaseHTTPMiddleware`, qui pouvait consommer le
corps hors du compteur. Les exemptions existantes, sessions, réponses 401 sans
lecture, WebSocket et lifespan sont testés. Le handler ne traduit en 413 que
l'exception de dépassement propre au middleware ; les erreurs 400/422 ordinaires
conservent leur comportement.

Le producteur de release utilise désormais USTAR et vérifie le vrai payload
construit avec `_safe_extract` puis `_validate_payload`. La CI de PR et la
publication utilisent le même script de packaging. Une archive rejetée n'est
pas publiée par ce script. Les en-têtes GNU ordinaires restent acceptés ; les
extensions PAX, GNU long-name et sparse sont volontairement refusées. **Les
anciens assets publiés n'ont pas tous été examinés** : aucune compatibilité
universelle avec ces archives n'est affirmée.

La [première CI de la PR #18](https://github.com/mehdi7129/inky-studio/actions/runs/36985139197)
a invalidé la première implémentation du garde TAR : **13 tests échouent et 584
passent** dans les logs Python 3.11.16 et 3.13.15, alors que Python 3.11.12 local
passe. Les versions récentes de CPython utilisent `_frombuf` et contournent
l'override de `frombuf`. Le contrôle est déplacé vers `_proc_member`, commun aux
deux chemins et appelé avant lecture du corps ou des extensions. Les plafonds
et assertions de lecture anticipée restent inchangés ; une régression force
également le contournement du parser public sur un ancien interpréteur. Le
premier résultat CI est conservé comme échec, pas comme qualification.

Reproduction avec les sept régressions supplémentaires : avant correction,
Python 3.11.12 donne **75 PASS / 7 FAIL**, et Python 3.11.16 comme 3.13.15 donnent
**62 PASS / 20 FAIL**. Après correction, les trois exécutent **82 PASS**. Le
dispatch a été vérifié dans les sources officielles de
[CPython 3.11.16](https://github.com/python/cpython/blob/v3.11.16/Lib/tarfile.py)
et [CPython 3.13.15](https://github.com/python/cpython/blob/v3.13.15/Lib/tarfile.py).
La relecture indépendante confirme le refus avant lecture d'extension ou saut
du corps, premier header compris, sans double comptage ni assertion affaiblie.

## Validation

- Relecture indépendante des changements HTTP, authentification et updater :
  aucun défaut concret supplémentaire identifié.
- Tests ciblés : **110 passent** pour HTTP/auth/queue/session/WebSocket et
  **82 passent** pour l'updater. Ils font partie de la suite globale, ils ne
  s'ajoutent pas à son total.
- Première exécution restreinte : **584 passent, 5 échouent sur `bind()` avec
  EPERM**, listeners TCP exclus. Ces blocages d'environnement sont conservés
  dans les preuves. Après rétablissement des permissions et correction de la
  route 204 puis du dispatch TAR, la suite locale Python 3.11.16 complète donne
  **604 tests réussis**, sockets Unix et listeners HTTP/HTTPS inclus.
- Qualification locale de migration/rotation du mot de passe : **29 contrôles
  passent** sur de vrais échanges HTTP/WebSocket, avec données temporaires.
- Ruff et `git diff --check` passent ; le frontend courant se construit.
- Packaging final local avec bsdtar et validateur Python 3.13.15 :
  **971 399 octets compressés**, 103 entrées, 3 787 037 octets de fichiers ;
  extraction et validation complètes réussies.
  Exclusion des caches et refus d'un symlink avant remplacement de l'archive
  finale vérifiés. Shellcheck, syntaxe Bash et parsing YAML passent.
- La CI exécute la suite backend complète sur Python 3.11 et 3.13, les migrations
  de mot de passe HTTP/WebSocket, puis les tests frontend et le packaging réel.
  Quatre nouveaux cas de listeners vérifient HTTP/HTTPS avec longueur déclarée
  ou chunks, sans attendre la fin du corps excessif.
- Un job distinct vérifie FastAPI **0.115.0**, Starlette **0.37.2** et
  python-multipart **0.0.12** sur les tests HTTP/auth/queue/WebSocket/listeners.
  Reproduit dans un environnement isolé Python 3.11 : **78 tests passent**,
  listeners réels inclus, après le correctif 204. L'échec de collecte initial
  reste archivé séparément. **Les checks de la PR font foi pour les validations
  distantes Linux/Python 3.11 et 3.13**.

Les logs et reproductions locaux sont conservés sous `build/validation/` dans
la copie de travail isolée, hors suivi Git. Les tests reproductibles font partie
du dépôt.

## Limites conservées

La limite HTTP porte sur les octets reçus par requête. Elle ne borne pas le nombre
de connexions simultanées, le temps de transfert ni l'espace total utilisé par
la bibliothèque. Un chunk est déjà fourni par le serveur ASGI avant que sa taille
soit vérifiée ; il n'est pas transmis au parser lorsqu'il dépasse le budget.
Les limites d'archive ne constituent pas une garantie globale de temps CPU.

Le rollback updater reste limité au code : dépendances, migrations, coupure
d'alimentation et health après restart ne deviennent pas transactionnels.
Le bootstrap installer reste un chemin distinct. Les réserves de stockage,
bibliothèque/historique, UI web et qualification matérielle du précédent rapport
restent ouvertes.

Aucune release, installation sur le Raspberry, modification du Wi-Fi,
distribution Apple ou décision réglementaire n'est réalisée par ce correctif.
