# Factory system setup — contrat commun pour revue, aucun GO code

Backend source `d67db9e44c37eb72b94851b4bba923228479cf00` ; OS source `e674e96`.
Fichiers normatifs : `wire-contract.json`, `ipc-contract.json`, `OS-FACTS.md`.
Ce dossier décrit le prochain lot. Aucun setter, build, package, Pi, SD, VM ou
déploiement n'est exécuté. Aucun schéma Phase B historique n'est repris.

## Autorité et transport

Le QR bootstrap v2, son profil GATT et ALPN `inky-bootstrap/1` restent identiques.
`bootstrap.claim/status` RPC v1 restent compatibles. Les nouveaux clients
négocient explicitement RPC v2 par `system_setup.negotiate` après une claim
vérifiée. Aucun `next_step` ne déclenche un effet. Le même RPC v2 est disponible
sur le profil TLS normal pour reprendre une continuation interrompue.

Chaque peer TLS possède une fermeture locale avec session UUID serveur et
génération. Le nonce RESET/client n'est jamais une autorité. RESET remplacé,
disconnect, expiration, changement d'epoch/admission, drain et changement de
profil invalident ce contexte et ferment sa connexion IPC persistante.
Avant chaque nouvelle admission et avant remise de réponse : writer lease,
admission OS, epoch actuel, binding préparé, ledger v2 ADOPTED/first_owner,
`owners.status(owner_id, owner_token, request_id=claim_request_id)` sont vérifiés.
`authenticate()` seul ne lie pas la claim. Les secrets owner restent dans main,
jamais dans le journal ou les arguments root.

Un syscall/subprocess/thread déjà admis reste possédé et drainé ; il n'est pas
annulé à la disparition du téléphone. Avant chaque sous-effet suivant, le
contexte est revérifié. Une perte de session après l'heure, avant pays/radio,
laisse un résultat partiel incertain, jamais une autorisation implicite de finir.

Le RPC client expire à20s, l'apply OS peut durer45s : `system_setup.apply`
enregistre immédiatement sa tâche possédée dans OperationRegistry puis répond
`applying/submission=registered/durability=not_confirmed`, sans attendre l'OS et
sans prétendre que le journal root est déjà durable. Le worker sauvegarde
l'intention et le UTC exacts avant toute soumission IPC ; `status` readonly suit
ensuite la progression. Un retry conserve les mêmes UTC/pays/octets, sans
rééchantillonnage transparent. Le client sauve op_id/défi avant challenge puis
l'intention exacte avant apply.

`negotiate` authentifié retourne `latest_operation_id` nullable à partir de
`setup.inspect` réussi et scopé à init/owner/claim. null signifie not_started
observé, jamais erreur masquée. Un client sans checkpoint peut ainsi retrouver
l'opération et consulter status ; il ne rejoue aucun effet pour la découvrir.

## Effets système et reprise

Le nouveau service privilégié fournit le vrai challenge `CLOCK_BOOTTIME`, nonce
CSPRNG32, TTL30s. `apply` lie op_id, intention, boot/candidate/contexte, init
receipt, UUID/SPKI, epoch et owner/claim/session. Son journal root est fsync
`pending` AVANT les effets. Ordre : setter heure réel et readback borné ; pays
explicitement choisi et observations firmware/kernel/canaux ; activation radio
contrôlée. La réponse mesure ces faits ; aucun booléen `ClockResult` ne remplace
le setter. Le UTC fourni reste une déclaration du téléphone autorisé, pas une
source UTC indépendante.

Même op_id/mêmes arguments : résultat durable identique, sans prolonger un défi.
Arguments différents : conflit. Pending interrompu : `uncertain`, jamais rejoué.
Une récupération réelle exige nouveau op_id + supersedes_op_id, propriétaire
réauthentifié, ancien travail drainé, état réel observé/radio fermée, défi courant
et intention explicite. Elle ne relance jamais l'initialisation factory.

`setup.inspect` est une lecture sous admission main actuelle, sans ancien
téléphone : elle retrouve op_id/completion_id et état à partir du binding
d'initialisation. Elle résout le cas apply/complete appliqué mais réponse perdue.
L'absence d'une ligne ou un ancien reçu n'autorise aucun effet.

`setup.complete` intervient après vraie confirmation Wi-Fi et inspection du
profil commité. La nouvelle RPC helper `inspect_committed` est strictement
readonly et réservée au service setup attesté ; elle expose id, owner_id, état
committed, profile_uuid, device wlan0, unique owner NM, boot_id et IPv4, sans
secret. Le service setup recoupe directement NM puis écrit son propre résultat
root. Le binding final contient UUID/SPKI et provenance de publication initiale ;
`publication_op_id` historique peut être différent du `setup_op_id` courant
après récupération explicite. Le même binding d'initialisation/UUID/SPKI et un
setup courant réellement terminé sont exigés, jamais une recertification pour
forcer l'égalité des identifiants. Le DER courant n'est pas immuable.
`setup.resume(completion_id)` vérifie une nouvelle
admission/boot et ne dépend pas de la présence d'un téléphone ou d'un owner actif.

## Sélection positive au startup

| Preuves durables vérifiées | Branche autorisée | Effets interdits |
|---|---|---|
| Aucun signal factory, vrai état legacy | Legacy existant inchangé | Importer un état factory par absence |
| Ledger v2 FACTORY + init consumed + prepared binding valides | Bootstrap claim existant | Normal sans claim |
| ADOPTED, pas d'identité normale, setup non terminé | Bootstrap setup du même owner enregistré, sans nouveau QR/welcome | Refaire init/claim ou restaurer un ancien snapshot |
| Op pending après crash, ou statut uncertain | Reprise explicite sur profil compatible avec l'identité réellement présente | Rejouer setter/autorité BOOTTIME historique |
| Identité normale publiée, setup/confirmation incomplète | CONTINUATION_NORMAL avec même UUID/SPKI, status/reprise sous nouvelle session owner | Revenir au QR/bootstrap ou appeler le sélecteur legacy |
| Completion root durable + publication/ledger v2 cohérents | NORMAL, sans téléphone/ancien TLS/owner actif requis | Réouvrir factory après révocation/rotation, réseau absent ou zéro photo |
| Preuves contradictoires, absentes alors qu'attendues, corruption | Refus/récupération explicite avec preuves conservées | Effacer, recréer ou interpréter absence comme autorité |

La completion historique lie la claim et l'epoch historiques. Toute mutation
ultérieure requiert l'epoch et l'autorisation actuels. Une révocation ou rotation
normale ne supprime donc pas l'état NORMAL. Le marker factory, le reçu consumed,
le ledger v2 et les fichiers média/identité restent conservés.

À chaque nouveau boot, l'attestation historique et la readiness LIVE sont
distinctes. Avant toute émission WLAN/scan/autoconnect : radio maintenue fermée,
pays relu/appliqué avec observations actuelles, puis ouverture radio contrôlée
pour le dernier profil réellement confirmé et recontrôlé seulement. Aucun ancien CLOCK_BOOTTIME ou ancien UTC
n'est appliqué pour remettre l'heure. Un échec conserve NORMAL et la photo, mais
ferme les nouvelles opérations réseau ; il ne déclenche ni QR ni welcome.
Le gate rfkill/NetworkManager doit précéder le premier démarrage réseau, pas
seulement être vérifié après un autoconnect déjà réalisé.

Une configuration Wi-Fi normale ultérieure peut remplacer la transaction et le
profil initiaux : la completion n'est pas un pin de réseau immuable. Le service
OS suit la dernière transaction helper authentique `committed`, recontrôle
directement NM/UUID/interface/pays actuels et remplace atomiquement son snapshot
ROOT du réseau approuvé via `inspect_latest_committed`, réservé au service setup
attesté. « Authentique » signifie réponse du vrai processus helper attesté,
parseur strict et observations NM indépendantes ; le fichier du journal n'est
pas présenté comme cryptographiquement signé. Pendant le boot radio fermée,
`ipv4=[]` est valide si le profil persistant exact est observable ; aucune
readiness réseau n'est affirmée avant activation et acquisition d'IP.
Un journal helper absent, pending ou uncertain ne
permet aucune sélection automatique arbitraire : conserver NORMAL_RECOVERY,
réseau fermé et photo/identité/owners inchangés, puis récupération explicite par
le propriétaire sur le profil BLE normal. Aucun ancien snapshot n'est restauré.

## Publication TLS, handoff et photo

La publication initiale utilise uniquement `PreparedFactoryIdentity` après un
vrai résultat OS validé, même boot et contexte toujours autorisé. Un ancien
`status` seul ne permet jamais de fabriquer un nouveau `ClockResult` ou candidat.
Un candidat certificat déjà durable peut seulement être finalisé à octets/intent
identiques sous une admission de reprise explicite ; aucune régénération depuis
un reçu historique. L'opération de reprise doit être explicite, pas un effet
caché de `status` (voir point restant ci-dessous).

Le journal initial reste historique. `load_current_identity()` valide l'identité
normale actuelle avec même UUID/clé/SPKI sans imposer le DER initial. Après le
transfert, le seul writer de renouvellement est
`Identity.refresh_certificate_if_needed()` sous `.identity.lock` ; pas de second
writer `PreparedFactoryIdentity.repair_existing` pour un renouvellement normal.
La sélection ne fait jamais appel à `load_or_create_identity()` pour recréer ou
renouveler implicitement une identité factory. Une politique d'heure courante
doit précéder un renouvellement, sans réutiliser l'ancien BOOTTIME comme grant.

Le bootstrap ferme son admission puis ses opérations drainées avant normal.
Le même processus garde le writer lease, le store v2 et le DisplayController.
Le handoff ne doit appeler ni `display.shutdown()`, ni `owners.close()`, ni
welcome, ni second `initialize()`. Le noyau normal reçoit identité/store/network
injectés. Il réutilise Wi-Fi scan/begin/status puis HTTPS owner `/wifi/confirm`.

Après completion, `/api/auth/factory-device-enroll` requiert HTTPS et owner/claim
actuels, pas un password/cookie. Le client protège d'abord un credential PHOTO
NEUF. request_id doit égaler claim_request_id : le store PHOTO existant garantit
un retry exact/une credential par claim sans nouveau schéma. ID et secret PHOTO
ne peuvent être ceux du BLE. Le client ouvre ensuite une device-session PHOTO.
Aucune permission BLE n'est attribuée aux invités média.

## Origin HTTPS explicite

L'image possède déjà un hostname root persistant `inky-<32hex>` ; aucune nouvelle
autorité hostname n'est créée. Le service OS compare rootstate et hostname
configuré, observe Avahi `GetHostNameFqdn`/`GetState`, interfaces et NM courants.
Il remet `https_origin` explicite quand prêt, sinon null. L'annonce réelle n'est
pas supposée à partir de la seule présence du paquet Avahi.

Le backend injecte cette origin attestée au noyau factory normal et la remet
sur le canal TLS owner après configuration réseau. Il ne la dérive jamais de
Host, SAN, socket.gethostname ni d'une IP non authentifiée. Invitation refusée
tant que l'origin n'est pas explicitement vérifiée. La configuration env legacy
`INKY_STUDIO_PHOTO_ACCESS_URL` conserve son comportement ; aucun os.environ n'est
réécrit pour simuler la nouvelle authority.

Pour une transition LAN, `https_origin=null` impose `next_step=wait_origin` et
polling readonly ; aucun confirm/enrollment LAN avant origin vérifiée. Les
commandes Wi-Fi BLE scan/begin/status du propriétaire restent disponibles sur le
profil normal pendant cette attente, afin de configurer le réseau avant son IP.
Une completion déjà durable peut donc être complète mais attendre l'origin,
sans accorder prématurément l'enrôlement PHOTO ni effacer la connexion protégée.

## Fichiers backend du prochain lot, seulement après GO

- Nouveaux `provisioning/system_setup_wire.py`, `system_setup_ipc.py`,
  `factory_continuation.py` et tests ciblés correspondants.
- `bootstrap_runtime.py`, `bootstrap_wire.py`, `transport.py` : négociation v2,
  contexte local par peer, invalidation/drain et retrait de l'ancien refus de
  publication uniquement au profit du sélecteur/coordinateur explicite.
- `factory_phase_a.py`, `factory_session.py`, `factory_runtime.py` et `main.py` :
  sélection positive, handoff et noyau normal injecté conservant l'unique SPI.
- `runtime.py` : injection owners v2/NetworkClient attesté/identité et lifecycle
  qui n'est plus propriétaire de la fermeture du store transféré.
- `bootstrap_identity.py` : reprise explicite data-only du candidat initial si
  retenue à la revue ; pas de nouveau format clé/cert ni DER immuable.
- `api/photo_access.py`, `api/__init__.py`, `auth.py`, `main.py` : route PHOTO
  factory dédiée, origine explicitement attestée et gardes transport/owner.
- `scripts/inky-network-helper.py` et ses tests : seule inspection committed
  readonly pour le rôle setup OS attesté, sans élargir les commandes app.
- Tests de sessions/disconnect/réponse perdue/startup/rotation/révocation/photo
  conservée ; pas de suite globale, packaging ou activation dans la conception.

## Reprise DATA-ONLY explicitement acceptée

`system_setup.continue(op_id)` est négocié comme capacité RPC v2 et possède sa
requête/réponse fermées dans le wire. Il exige owner/claim/epoch/session/admission
courants. Il est limité à finaliser des octets déjà journalisés ou à rendre
l'étape complete idempotente avec un vrai réseau committed/recontrôlé ; jamais
à rejouer heure/pays/radio. La réponse rend exactement l'une des actions
`publication_finalized`, `wifi_pending`, `completion_finalized`, `already_complete`
avec état/next_step cohérents. `system_setup.status` reste strictement readonly.
Si aucun candidat
durable n'existe et que l'ancien contexte/boot est perdu, il retourne
`recovery_required` et le client propose un nouveau cycle explicitement autorisé.
Un certificat déjà publié puis renouvelé n'est jamais remplacé par l'ancien DER
journalisé. La provenance du premier certificat reste historique ; une nouvelle
opération setup de récupération ne modifie pas son identité ou publication_op_id.
