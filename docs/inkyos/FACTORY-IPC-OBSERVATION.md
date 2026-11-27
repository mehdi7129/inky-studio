# Observation du service d'initialisation — raccord inactif

`observe_initialization_service(data_directory)` vérifie une réponse actuelle
du service IPC-A sans initialiser le cadre. Cette API interne n'a aucun caller
installé, flag d'activation ou nouveau message IPC. Elle ne change ni le parcours
TEST backend c31 / iOS build 9, ni le démarrage factory terminal par statut 78.

## Ordre et propriété du travail

La sonde valide d'abord le contexte appelant : une garde héritée déjà fermée ou
un environnement incohérent ne permet pas de contacter le service. Son opération
acquiert ensuite une **SH propre**, dans un contexte distinct. Elle ne dépend pas
de la durée de vie d'une garde externe appartenant à une autre tâche.

Sous cette garde, elle vérifie le selector factory et les credentials v2 déjà
persistés, puis effectue **une seule `initialization.inspect`**. Le client existant
utilise le socket fixe `/run/inkyos-bootstrap/control.sock`, authentifie le peer
kernel UID 0 avant toute émission et garde une seule deadline monotonic de trois
secondes jusqu'à la réponse complète et EOF.

Avant de rendre son résultat, la sonde vérifie de nouveau la garde, l'environnement,
le selector et l'epoch des credentials. La connexion est fermée et le worker
bloquant est réapé avant de quitter la propriété de la garde. Des cancellations
répétées ne libèrent pas SH pendant ce travail. Les erreurs sont expurgées.

Aucun `begin`, coordinator, lock de premier boot, identité, ledger, DB de photos,
écran, listener ou runtime bootstrap n'est créé par cette sonde.

## Portée du résultat

Le résultat immutable contient seulement `receipt_state`, égal à `authorized`
ou `consumed`. Il ne contient aucun intent, receipt, digest, epoch, credential,
FD ou objet de lease. C'est une observation ponctuelle, déjà susceptible d'être
ancienne au retour de l'appel : elle ne doit être ni persistée comme autorité,
ni utilisée comme grant ou latch d'admission.

`authorized` ne permet jamais de créer le stockage. `consumed` ne prouve pas
la cohérence du stockage applicatif. Le chemin réel du coordinator conserve ses
propres vérifications fraîches, son inspect et son begin. Seul un retour **courant**
`newly_consumed` de ce begin peut autoriser la création du ledger.

`prepare_factory()` n'est pas une sonde de disponibilité : il peut créer des
fichiers et consommer l'autorisation OS. `initialize_factory()` reste `NoReturn`
et termine par `factory_runtime_pending` après cette préparation.

## Trois preuves distinctes

Au commit OS [04159cdb](https://github.com/mehdi7129/inkyOS/tree/04159cdb26430d8f32ad83d51388aec2afd3d74c),
le service IPC staged utilise `Type=notify`, `NotifyAccess=main` et une notification
`READY=1` sous `writer_guard("ipc")`, après chargement du module receipt, ouverture
du listener et création du worker. Cette notification est destinée à systemd ;
elle ne lit pas l'état courant de l'autorité et n'apparaît pas dans le wire IPC-A.

La réponse root-authentifiée à inspect est une observation du service et du receipt.
Elle ne remplace pas la preuve de fin du superviseur factory
`/run/inkyos-admission/Ready`. Cette dernière ne remplace pas davantage la réponse
courante à inspect. `Wants=` et `After=` seuls ne garantissent pas la disponibilité
après un échec du service.

Sources OS correspondantes, à requalifier dans le futur graphe installé :

| Source | SHA-256 |
| --- | --- |
| `scripts/initialization-server.py` | `946d8bc1823852839058389f59e90b3ae34810b7508aca069c43e40ed6084057` |
| `scripts/initialization-receipt.py` | `42d2e4ac0b38a3788d41dc4dd85a8df965a5c30fc88dbbfcbd6ed213c3e47de6` |
| `scripts/factory-runtime-contract.py` | `a855327fd195abc1e57c2f421bb649804ce2ffc66676d287efa217f9e1cbc40a` |

Les preuves natives READY antérieures épinglent d'autres sources serveur/client.
La preuve shared-guard sur les sources actuelles conserve explicitement les limites
`installed_graph_qualified=false` et `installed_writer_guard_qualified=false`.
Elles ne sont pas transférées à cette sonde comme qualification de l'installation.

## Vérification et limites

Les tests ciblés vérifient les refus avant IPC, l'absence de mutation locale ou de
consommation, les contrôles après réponse et le drainage sous cancellations.
Des processus et verrous réels vérifient la durée de vie de SH ; les identités OS
et le service des fixtures restent synthétiques. Les tests transport existants
couvrent séparément le peer root, les limites de schéma, la deadline et EOF.

La composition installée, le raccord d'admission du helper, les vrais UIDs Linux,
le socket protégé et l'ensemble superviseur/services restent à qualifier côté OS.
Ce lot n'active ni le QR, ni Bluetooth, ni la phase B heure/pays/Wi-Fi. Aucun
changement de production iOS n'est nécessaire pour cette frontière locale.

Voir le [contrat IPC-A](INITIALIZATION-IPC-V1.md), la
[garde de démarrage](FACTORY-RUNTIME-GUARD.md) et les
[gardes de writers](FACTORY-WRITER-GUARDS.md).
