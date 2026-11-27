# Budgets des clients sous preuve de peer

Ce raccord accompagne le passage de la preuve OS de 10 à 15 secondes. Il ne
constitue ni un délai global du boot, ni une garantie de timing sur matériel.
Les opérations restent sans retry implicite et sans changement de contrat Wi-Fi.

## Initialization IPC

Le client Initialization IPC utilise une borne absolue de **20 secondes**,
établie avant la connexion. Connexion, preuve de peer, écriture, lecture et EOF
partagent cette borne ; son expiration ne réinitialise pas le budget. La preuve
OS peut en consommer 15 secondes : il reste au plus 5 secondes au transport et
à la réponse. Le contrat détaillé est dans [INITIALIZATION-IPC-V1.md](INITIALIZATION-IPC-V1.md).

## NetworkClient

| Chemin | Sans peer guard (legacy) | Avec peer guard attesté |
| --- | --- | --- |
| `cancel_pending_sync` | 15 s, comportement existant | 20 s absolues |
| `call` asynchrone | 20 s absolues, comportement existant | 25 s absolues |

Le client capture le guard et choisit son budget une seule fois avant de créer
le deadline et de se connecter. Sur le chemin attesté, connexion, preuve,
écriture, lecture exacte et EOF utilisent le même deadline, sans repartir de
zéro après la preuve. Une preuve de 15 secondes laisse au plus 5 secondes en
sync et 10 secondes en async, moins le temps déjà consommé par la connexion.
Si le guard revient après expiration, aucune requête n'est écrite.

Les constantes legacy restent exactement 15/20 secondes. En particulier, le
sync legacy conserve son timeout socket de 15 secondes et sa lecture de la
première ligne ; aucune borne globale nouvelle ne lui est imposée. Le chemin
attesté exige toujours la réponse exacte suivie d'EOF. La preuve reste détenue
jusqu'à la fermeture effective du socket ; les drains et l'annulation restent
inchangés et peuvent dépasser le délai d'admission de la requête. Le guard
synchrone n'est pas préempté par le client : sa propre borne appartient à l'OS.

Le timeout socket de première lecture **factory** du helper réseau passe à
**20 secondes**, selon la coordination confirmée avec InkyOS, pour permettre
la preuve avant la première requête. Il conserve la sémantique existante
`settimeout`/`readline`, par réception : ce n'est pas un deadline absolu serveur.
Le timeout legacy de lecture reste à 2 secondes et celui d'écriture est remis
à 2 secondes avant la réponse. Cette adaptation du helper est traitée
séparément du présent client.

## SystemSetup inchangé

La borne de connexion de SystemSetup reste **15 secondes**, avant la preuve.
Les bornes RPC de **15/55 secondes** démarrent après le guard. Elles ne sont
donc pas consommées par la preuve et ne sont pas étendues ici. Il n'existe pas
de borne globale SystemSetup à 20 secondes. La préparation serveur OS
`open_setup` (budgets SOURCE 180 s / INITIAL 60 s annoncés par InkyOS) n'est pas
auditée par ce raccord backend.

## Preuves ciblées

`server/tests/test_network_peer_guard.py` exerce de vrais sockets Unix avec
des guards injectés et des budgets courts : succès preuve puis réponse,
expiration de preuve avant écriture (zéro octet), expiration du cumul preuve
et réponse sans reset, EOF requis et fermeture sous preuve. Les budgets
production 15/20 et 20/25 sont également vérifiés. Ces tests ne qualifient pas
le graphe de services, le peer natif, la radio ou le Pi.
