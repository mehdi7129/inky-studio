# Candidat d’association initiale — lot A

Ce candidat implémente le parcours de la [proposition wire](BOOTSTRAP-WIRE-PROPOSAL.md) : QR physique v2, service GATT bootstrap distinct, TLS 1.3 avec ALPN `inky-bootstrap/1`, puis `bootstrap.claim` et `bootstrap.status`. Le résultat confirmé est une association durable **en attente de préparation du système**.

Il reste inactif dans les entrées installées. `run()`, `serve()` et le lifespan ASGI continuent d’arrêter le mode factory avec le code 78 `factory_runtime_pending`. Aucun flag supplémentaire n’active le runtime backend. La version physique de test backend c31 / iOS build 9 reste distincte de cette branche.

## Backend

- `prepare_factory()` expose le résultat du coordinator existant, avec ses mêmes contrôles des credentials, de l’IPC et du stockage. Ce résultat ne prouve ni une lease OS ni l’admission d’un service.
- `BootstrapRuntime` reçoit explicitement ce résultat, le callback de vérification des credentials, le contrôleur d’écran et le répertoire privé. Les tests injectent les adaptateurs OS, radio et écran.
- L’identité et l’état factory sont relus avant le démarrage et chaque commande. Une identité normale déjà publiée ferme ce candidat : le lot A ne possède pas encore le contrat de réouverture/fermeture de la phase B.
- Le store durable existant reste l’unique ledger. Le premier claim choisit un owner ; les reprises conservent owner, token et request ID. Un statut authentifie l’owner avant de rechercher son reçu.
- Le QR a une fenêtre limitée à dix minutes. Après adoption, le redémarrage n’ouvre aucun nouveau QR. Avant adoption, l’ancien QR ne survit pas au redémarrage.
- Les tâches admises restent enregistrées après la disparition d’un client Bluetooth. L’arrêt ferme l’admission puis attend les transactions et les refreshs d’écran avant de relâcher leur propriété.
- `serve_prepared_factory()` fournit une jonction testable avec création de runtime injectée. L’initialisation de l’écran, sa disponibilité et son shutdown restent sous un seul propriétaire. Cette fonction n’est appelée par aucune entrée installée.

## iPhone

`factoryBootstrapEnabled` est fermé par défaut. Son activation de candidat ajoute un sheet distinct « Associer un nouveau cadre », avec les composants Bento existants, le thème système et les coins arrondis.

Le QR v2, les métadonnées GATT, le canal TLS, le vault Keychain et le coordinator portent une provenance bootstrap distincte. Aucun échec de pin, de date, de profil ou de handshake ne provoque une conversion vers le parcours normal.

Avant un claim, l’app enregistre et relit l’owner, son token et le request ID dans le Keychain. Le token du QR reste en mémoire. Une reprise commence par `bootstrap.status` avec un RPC ID distinct ; une réponse manquante ou non corrélée conserve une issue incertaine. Aucun nouvel owner n’est créé pour contourner un conflit.

Le succès affiche « Cet iPhone est associé » et « Préparation du cadre en attente ». Il n’enregistre aucun endpoint HTTPS et n’ouvre ni recherche de réseaux ni écran de confirmation Wi-Fi.

## Périmètre fermé

Ce lot ne règle ni l’heure, ni le pays radio, ni le Wi-Fi. Il ne publie pas de certificat normal, ne démarre pas de renouvellement, de scheduler ou de serveur HTTP normal et ne charge pas la DB de photos.

L’activation installée dépend encore du contrat exact InkyOS : fichiers root protégés, admission du boot et du candidat, lease maintenue jusqu’au drainage, wrappers des autres writers, et preuve `Ready` publiée par le supervisor. Aucun objet ou booléen de test ne remplace cette preuve.

## Vérification reproductible

Le corpus raw commun reste dans `bootstrap-wire-proposal/vectors.json`. Python et Swift utilisent les mêmes octets pour conserver les doublons, les nombres non entiers et les encodages invalides au lieu de les normaliser avant la validation.

Les tests backend s’exécutent avec `python -m pytest` depuis `server/`. Le banc natif `scripts/test-bootstrap-channel.sh` compile les sources Swift de production contre le runtime Python de production, sur des pipes privés et un ledger temporaire. Il n’utilise aucune radio, aucun GPIO ni service système. Le banc normal `scripts/test-bluetooth-channel.sh` demeure une vérification séparée de compatibilité v1.

La CI iOS exécute les deux bancs ainsi que les tests du bridge TLS, les tests de l’app et le build Release. Les tests simulateur ou les adaptateurs inertes ne qualifient pas le QR affiché, BlueZ, les permissions iPhone ou la chaîne Raspberry réelle.

Validation locale du candidat, le 11 octobre 2026 :

| Vérification | Résultat |
| --- | --- |
| Suite backend complète | 1 025 tests PASS |
| Scripts de packaging | 80 tests PASS |
| Bridge TLS natif | 15 tests PASS |
| Canal Bluetooth normal v1 | 13 tests PASS |
| Interop bootstrap Swift/Python | 5 tests PASS |
| HTTPS adopté sur sockets réels de loopback | 52 tests PASS |
| Unit tests iOS signés | 144 tests PASS |
| Tests UI ciblés sur le lot A | 2 tests PASS |
| Build Release iPhone | PASS |

Les essais iOS locaux utilisent uniquement le simulateur iPhone 15 Pro Max existant. Les [six captures et leur revue visuelle](../ios/reviews/2026-10-11-bootstrap-lot-a/README.md) documentent les états clair/sombre du sheet, avec les limites de la palette DEBUG. Les tests UI existants du reste de l'app sont exécutés séparément par la CI.

Avant merge ou distribution : revue indépendante du candidat, raccord InkyOS qualifié, puis essais physiques du premier démarrage, de la reprise après réponse perdue et de l’arrêt/redémarrage. La phase B reste un lot ultérieur.
