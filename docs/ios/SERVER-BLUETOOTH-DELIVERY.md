# Déploiement serveur Bluetooth — 0.5.0-rc.2

Le **27 septembre 2026**, le candidat serveur `0.5.0-rc.2`, source
[`ae61df1`](https://github.com/mehdi7129/inky-studio/commit/ae61df1c0f01408861ccb1210ec85986768d6784),
a été déployé sur le Raspberry. Ce déploiement ne constitue ni une release
publique ni une qualification du parcours iPhone/Wi-Fi complet. La
[PR #11](https://github.com/mehdi7129/inky-studio/pull/11) reste draft.

## Installation active

| Élément | État vérifié après bascule |
|---|---|
| Service app | `inky-studio.service` actif, `MainPID=29664`, `NRestarts=0` au relevé final |
| Chemin stable | `/home/pi/inky-studio` est un lien vers `/home/pi/inky-candidates/bluetooth-rc2-ae61df1` |
| Ancien code | `/home/pi/inky-backups/pre-bluetooth-rc2-ae61df1` |
| Données | Chemin conservé : `/var/lib/inky-studio` ; aucun contenu lu, copié ou restauré par le script opérateur |
| Helper | `inky-network.service` actif ; installation et permissions existantes conservées |
| iOS disponible | TestFlight `1.0.0 (3)` ; le build Bluetooth 4 attend toujours la conformité Apple et n'a aucun groupe |

Le backend reprend son lifecycle et son scheduler habituels au démarrage. Le
déploiement ne prétend donc pas que la base ou l'écran restent immobiles après
le restart. Il n'a pas changé le mot de passe applicatif ni configuré de nouveau
réseau. Les identités et associations persistantes ne sont pas restaurées depuis
une ancienne sauvegarde.

## Bascule et récupération

Le préflight final est **PASS** : payload et manifeste contrôlés, dépendances,
chemins, service, HTTP/auth, driver et disponibilité du helper vérifiés. Le
contrôle `health` du helper ne permet pas de connaître une éventuelle transaction
en cours : le rapport conserve explicitement `pending_state: unknown`.

L'application est arrêtée sous trois verrous : verrou de bascule, verrou updater
de l'ancien code et verrou updater du candidat. L'arrêt effectif est confirmé,
puis un `cancel_pending` avec ACK strict précède tout déplacement. Cette
annulation peut rétablir l'ancien réseau d'un essai non validé ; ce n'est pas une
lecture seule. L'ancien code est renommé, le lien publié, puis le candidat
démarré et vérifié. Aucune commande de login, de création de session, de scan
Wi-Fi, d'écriture GATT ou de refresh écran n'est exécutée par l'opérateur.

Un premier essai a déclenché un **rollback du code réussi** : le vérificateur
tentait de lire un objet D-Bus privé refusé par la politique système
(`AccessDenied`). Le problème a été reproduit dans un probe isolé. Le contrôle
utilise désormais les propriétés publiques BlueZ, sans modifier les permissions.
Le préflight et la bascule corrigés réussissent ; le rapport final indique
`result: deployed`, version `0.5.0-rc.2` et `data_accessed: false`.

Les **26 tests de défauts sur Linux passent** : interruptions, signaux réels,
perte de réponse, démarrage partiel, échec d'annulation, locks, refus d'écrasement,
manifest altéré et contrôles Bluetooth. Après exposition du candidat, toute
restauration exige arrêt confirmé et nouvel ACK d'annulation. Une annulation
incertaine impose une récupération manuelle, sans redémarrage automatique de
l'ancien backend. SIGKILL et coupure électrique ne sont pas couverts par cette
récupération automatique. Le script ne peut pas être rejoué tel quel après
réussite : son préflight refuse une production déjà devenue un lien.

## Vérifications et portée des preuves

- HTTP depuis le Mac : **PASS**, version `0.5.0-rc.2`.
- Listeners HTTP/HTTPS locaux, TLS 1.3 et refus des routes protégées sans
  authentification : **PASS**. Ce contrôle HTTPS de disponibilité n'est pas une
  validation du pin d'identité par l'iPhone.
- Driver réel détecté dans le journal de l'invocation courante : **PASS**.
  Aucun refresh commandé ni nouvelle photo envoyée pendant cette vérification.
- Bluetooth : bus du PID courant, UUID Inky nouvellement présent dans
  `Adapter1.UUIDs`, `ActiveInstances` supérieur à la baseline après arrêt.
  Ces propriétés sont des agrégats publics. Leur corrélation pendant une
  maintenance sans autre banc concurrent étaye l'enregistrement du candidat ;
  elle ne prouve pas un échange radio, une connexion iPhone ou un scan du QR.
- CI backend et iOS du commit `ae61df1` : **SUCCESS**. Les bancs antérieurs
  [Mac/Pi et backend isolé](reviews/2026-09-27-bluetooth/README.md) complètent ces
  contrôles, avec leurs limites propres.

Les preuves opérateur restent hors Git dans `build/ops/rc2-deployment/` :
`live-check-final.jsonl`, `live-apply-attempt1.jsonl`, `live-apply-final.jsonl`,
`test-result.txt`, script, tests et `SHA256SUMS`. Le README privé de préparation
est historique ; les rapports finaux ci-dessus établissent la bascule réalisée.

## Reste à qualifier

Rendre le build 4 disponible après conformité Apple, puis tester sur iPhone le
QR physique, l'adoption, le mauvais mot de passe Wi-Fi, le partage de connexion
2,4 GHz et la confirmation HTTPS. Observer réellement rollback, perte de BLE,
fermeture de l'app, reboot et coupures aux phases critiques, avec accès de
secours. Aucun de ces tests physiques n'est déclaré réussi par le déploiement.

Voir [l'intégration Bluetooth](BLUETOOTH-INTEGRATION.md) et
[la livraison TestFlight](TESTFLIGHT-DELIVERY.md). InkyOS et l'adoption initiale
entièrement hors ligne restent des travaux ultérieurs.
