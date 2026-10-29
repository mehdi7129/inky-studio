# Audit final de release — backend et iOS

**1 octobre 2026.** Baseline inspectée : `8c525d6`. Le correctif iOS et sa validation locale décrits ci-dessous lui succèdent ; leur CI et l'archive build 7 doivent être liés à leur propre révision.

**Résultat : un nouveau P2 iOS reproduit puis corrigé et validé localement ; aucun autre nouveau défaut concret confirmé dans le périmètre relu.** Les limites historiques restent ouvertes. Cette conclusion porte sur le logiciel : elle ne constitue ni une distribution Apple, ni une qualification iPhone–cadre physique.

L'audit couvre connexion/session, rotation du mot de passe, Photos/caméra/démo, QR/identité, transport BLE, confirmation/rollback Wi-Fi, lancement, installer et updater. Les revues backend et iOS ont d'abord lu sources, tests et preuves existantes sans opération sur les services, les réseaux ou les identifiants réels. Seule la reproduction ciblée et la validation du correctif ont ensuite exécuté des tests locaux avec données synthétiques et un namespace Keychain propre aux tests. Aucun changement Wi-Fi, accès au Keychain de production ou essai matériel n'en découle.

## Nouveau constat et correction

**IOS-01 — P2 : le 17e endpoint distinct bloque la finalisation locale du Wi-Fi.** Sur la baseline, un record claimed valide avec 16 adresses HTTPS accepte encore la confirmation du serveur au nouvel endpoint, puis `markClaimed` ajoute cette adresse et lève `invalidRecord`. Le coordinator ne rejoint donc pas `finishWiFiTransaction`/`didFinish` et suspend le parcours alors que le cadre a déjà répondu `committed`. La reprise conserve la même transaction et peut rencontrer à nouveau la borne. Pas de corruption ni de divulgation de secret démontrée.

Références : [OwnershipVault.swift](../../ios/InkyStudio/Provisioning/OwnershipVault.swift), méthode `markClaimed` ligne 72 ; [BluetoothSetupCoordinator.swift](../../ios/InkyStudio/Provisioning/BluetoothSetupCoordinator.swift), finalisation après confirmation lignes 369–402.

La reproduction applique les quatre nouveaux [OwnershipVaultTests](../../ios/InkyStudioTests/OwnershipVaultTests.swift) au code baseline : **3 FAIL, 1 PASS**, dont l'erreur `invalidRecord` au 17e endpoint. Les deux autres échecs révèlent l'absence de remise à jour de la récence et de déduplication ; le refus d'un endpoint invalide passe déjà.

Le correctif valide la nouvelle adresse avant écriture, conserve la dernière occurrence de chaque endpoint et les 16 plus récents. L'identité, le certificat, les identifiants, le token et la transaction pending restent conservés. La relecture indépendante du patch est favorable. La validation locale du candidat build 7 donne **103 PASS, 0 FAIL, 0 SKIP**, incluant les quatre nouveaux tests : éviction, revisite, doublons, refus d'une adresse invalide sans altération du record. Elle vérifie aussi relecture du record persisté et clôture de la transaction après éviction.

L'invocation initiale rejetée parce qu'un target de package TLS n'appartenait pas au scheme a exécuté **zéro test** ; elle n'est pas un échec runtime du correctif. Les warnings Security sur le main thread dans les fixtures TLS synthétiques ne démontrent pas un nouveau défaut de production. La CI de `24d9295` confirme ensuite les 103 tests unitaires ; l'archive build 7 de cette révision passe 75 contrôles distincts.

## Ancien audit : corrections intégrées et garanties

La [PR #2](https://github.com/mehdi7129/inky-studio/pull/2) est réellement fusionnée : merge `28b3681`, le **26 septembre 2026**. Les commits du premier audit `ccc6b5d` et du second `d579445` sont ancêtres de `8c525d6`. Les [premier](2026-09-26-first-audit.md) et [second](2026-09-26-second-audit.md) rapports restent les traces datées, avec leurs réserves.

| Éléments relus | État actuel et preuve source/test |
| --- | --- |
| A01/A02/A03 | README de packaging interne au package ; fallback statique contenu dans son root ; WebSocket authentifié avant accept. `server/pyproject.toml`, `main.py`, `api/ws.py` et leurs regressions existantes. |
| A06/A08, B01/B02 | Curseur chronologique sans FK ; suppression pendant refresh supportée ; source absente saute seulement l'entrée de queue inutilisable, erreur du driver conserve la queue. `db.py`, `services/history.py`, `services/scheduler.py`, `tests/test_scheduler.py`. |
| A14–A16, B03/B04 | Ancien module updater conservé ; CLI courant et restart trap ; assets requis avant application ; extraction sans traversal/liens/devices ; restauration des nouveaux fichiers après échec. `scripts/inky-studio-cli`, `inky_web/updater.py`, `services/updater.py`, `test_cli.py`, `test_updater.py`. Garantie de rollback limitée au code. |
| A17/A18 | Reset CLI désormais atomique sous stop/trap restart, renforcé depuis le second audit ; annulation Wi-Fi acquittée avant nouvel epoch. Cap fichier upload 10 MiB et logs sans password. `auth.py`, `api/auth.py`, `api/queue.py`, `test_auth_storage.py`, `test_cli.py`, `test_network_helper.py`. |
| B08/B09 | Dimensions et décodage pixels avant stockage/dedupe dans `services/photos.py`. Corrections présentes. |

Les contrats backend/iOS sont cohérents : champs snake_case, UUID canonique, BLE v1 avec ACK/sequence, cinq états Wi-Fi et confirmation HTTPS avec owner obligatoire. La rotation annule un essai pending avant changement d'autorité ; owner/QR sont liés à l'epoch durable. Le helper journalise avant mutation, commit après activation persistante indépendante du client D-Bus et récupère un essai incomplet au restart. Voir `provisioning/runtime.py`, `ownership.py`, `api.py`, `scripts/inky-network-helper.py` et leurs tests. Ces vérifications ne qualifient pas le comportement radio ou NetworkManager physique.

## Privacy : constat retiré après revalidation

L'allégation initiale selon laquelle la démo n'était pas documentée est **retirée** : la relecture complète de la section `demo` de [confidentialite.html](../../website/confidentialite.html), également recontrôlée sur la page publiée pendant la préparation, décrit déjà mémoire temporaire, reset/exit/fin d'app, arrière-plan, historique borné, fichier de préparation et éventuel téléchargement iCloud. L'affichage initial du contenu était tronqué ; aucune correction documentaire n'est justifiée par ce constat.

Les parcours relus utilisent PhotosPicker, une permission caméra contextuelle et aucun microphone ; la préparation produit un PNG sans recopier EXIF/GPS. La démo utilise un client mémoire isolé. Sessions/cookies restent propres à la connexion ; Face ID protège un secret Keychain avec opt-in. Les erreurs sensibles backend ne reflètent pas l'input et les diagnostics iOS inspectés n'émettent pas les payloads. Ce contrôle source ne vaut pas validation physique des permissions, de la caméra ou de Face ID.

## Limites historiques toujours ouvertes

Ces limites proviennent des rapports du 26 septembre ; elles ne sont pas présentées comme de nouvelles régressions.

| Niveau / scope | Limite restante |
| --- | --- |
| P2 — HTTP ingress | Le cap upload intervient après parsing/spooling multipart ; aucun plafond global de body. Téléchargement compressé updater et allocation initiale des metadata de l'archive encore non plafonnés. |
| P2 — déploiement/récupération | Copy du code en place et pip dans le venv existant : dépendances, migrations, interruption process/power-loss et health après restart non transactionnels. Progression update non persistante ; bootstrap installer distinct de l'updater durci. |
| P2 — données | History reste source du current/recycle ; clear laisse les photos mais retire ces références. Pas de quota/cleanup automatique ni garantie globale fichier/SQLite face à une coupure. |
| P2 — matériel | Lock display par process ; SPI bloqué, shutdown, rafraîchissement/couleurs, caméra, Face ID et coupure réelle restent à qualifier. Fault injections et fixtures ne ferment pas ces points. |
| P3 — UI historique | Pagination/accessibility web et cycle de bibliothèque restent ouverts. Les races React B06/B07 ne sont pas requalifiées par cet audit centré sur iOS/backend. |

## Validation et gates de release distincts

La [CI iOS de `8c525d6`](https://github.com/mehdi7129/inky-studio/actions/runs/36888352947) est **SUCCESS**, terminée le **1 octobre à 16:19:27 UTC** : 99 tests unitaires, 13 UI PASS et 1 skip Face ID explicite, build Release iPhone et artefacts réussis. Les checks backend Python 3.11/3.13, frontend et CLI du même HEAD ont été vérifiés SUCCESS pendant la préparation. Les preuves TLS existantes totalisent 15 tests InkyTLS, 13 tests du canal Swift/Python sur pipes et 52 checks HTTPS/WSS loopback ; leur portée reste logicielle. **Cette CI précède IOS-01 et ne valide pas son patch.** Les résultats suivants sont rattachés séparément à la révision corrigée.

La [qualification CI suivante sur `24d9295`](https://github.com/mehdi7129/inky-studio/actions/runs/36915478002) confirme les **103 tests unitaires, dont les quatre nouveaux tests OwnershipVault**, ainsi que les 15 TLS, 13 GATT et 52 HTTPS/WSS. Elle échoue toutefois sur un geste de `testImportPhotoCropAndUpload` : 12 UI PASS, 1 SKIP Face ID et 1 FAIL ; le Release est ensuite skipped. L'artefact montre la vignette synthétique entièrement visible dans le PhotosPicker système, sans occlusion. XCTest calcule un point `{-1,-1}` et échoue à faire `kAXScrollToVisibleAction` avant que le cadrage ou l'upload ne soient atteints. Ce constat établit une fragilité de l'automatisation, sans démontrer un défaut d'import applicatif.

Le geste est remplacé uniquement dans le test par le centre du rectangle AX observé. Une première comparaison stricte échoue localement sur iOS 27 : le bord gauche vaut `−0,00000339 pt` pour une vignette entièrement visible dans un viewport `430 × 932`. Le correctif borne ce bruit flottant à **0,001 pt** pour le rectangle, exige une taille positive et conserve le centre de clic strictement dans le viewport initial. Aucune coordonnée fixe, assertion retirée ou modification produit n'en résulte. La relecture indépendante est favorable ; le rerun ciblé sur l'iPhone 15 Pro Max / iOS 27 donne **1 PASS, 0 FAIL**, en atteignant cadrage, zoom, upload, fermeture du crop et troisième photo dans la file. Les échecs précédents sont conservés séparément ; la collecte système bloquée du rerun géométrique a été interrompue seulement après la fin du test et reste donc incomplète.

Le parcours démo complet passe également en **mode sombre** sur ce même simulateur ; sept captures originales ont été inspectées, sans correction du design requise par ces observations. Le thème du simulateur est restauré en clair. Ces deux reruns ciblés ne remplacent pas la qualification globale, consultable dans les [checks de la PR #12](https://github.com/mehdi7129/inky-studio/pull/12/checks). L'archive signée build 7 de `24d9295` a par ailleurs passé **75 contrôles** et été traitée par Apple ; le correctif limité au test et au présent rapport n'altère pas ses sources de production.

| Gate | État au présent rapport |
| --- | --- |
| Apple | Build 7 signé, uploadé et traité ; notes TestFlight enregistrées, build associé au brouillon public 1.0.0, icône et huit captures présentes. La conformité chiffrement reste « Informations manquantes » ; aucun document approuvé, groupe ou testeur affecté au build 7. Pas d'exemption/code inventé, de disponibilité testeur ni d'approbation App Review déduite des tests. |
| Cadre physique | Le contrôle récent a échoué à la résolution avant toute commande distante : version active/services inconnus. Restent QR e-ink→iPhone BLE→Wi-Fi→confirmation/rollback, mauvais password, perte BLE/app, reboot/coupures et accès de secours. |
| Release serveur | Dernière stable GitHub observée dans la préparation : `v0.4.2` ; `v0.5.0-rc.1` est une prérelease. Le déploiement `0.5.0-rc.2` décrit le 27 septembre est une preuve historique, pas une observation actuelle ni une release publique. Voir [SERVER-BLUETOOTH-DELIVERY.md](../ios/SERVER-BLUETOOTH-DELIVERY.md). |

La préparation Apple réalisée en parallèle ne constitue pas une distribution TestFlight ou une publication App Store. Aucune installation sur le cadre, modification de son réseau ou décision réglementaire n'est réalisée par cet audit. InkyOS/premier boot hors ligne demeure un chantier distinct ; la présence de primitives bootstrap ne prouve pas son intégration.
