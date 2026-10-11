# Phase B — frontière système heure et pays

Proposition de contrat du 11 octobre 2026, à relire conjointement par Studio et
InkyOS avant de figer des octets de protocole. Ce document ne rend aucun endpoint
disponible. IPC-A reste limité à inspect/begin et son client reste inactif.
Aucun changement de service, privilège, horloge, radio, Pi ou SD n'est autorisé
par la présence de ce document.

## Périmètre et ordre du parcours

Studio authentifie le téléphone, conserve les preuves d'ownership et pilote
l'expérience iOS. Le helper Studio transmet seulement des opérations système
étroites. InkyOS possède leur service root, leur journal durable et le contrôle
effectif de l'horloge et de la radio.

Le parcours neuf reste : autorité IPC-A → identité/ledger → QR → claim durable
→ assertion d'heure authentifiée → certificat normal renouvelé avec la même
clé/UUID → nouvelle connexion TLS normale stricte → clôture bootstrap durable
→ pays confirmé → gate radio qualifié → transaction Wi-Fi → confirmation HTTPS
épinglée → photo.

Une assertion d'heure issue d'un owner n'est pas une preuve UTC indépendante.
Un résultat système heure n'est ni une confirmation TLS ni une autorisation
Wi-Fi. Une réponse pays n'est ni une association réseau ni une livraison photo.
Le bootstrap ne transporte aucun mot de passe Wi-Fi/photo. Le pays ne transite
qu'après la reconnexion normale stricte, conformément au contrat existant.

### Périmètre v0 retenu pour la frontière heure

L'orientation v0 convenue entre Studio et InkyOS limite le réglage de l'heure
à une phase de bootstrap initial **durable et explicitement encore ouverte**.
Le premier claim a déjà adopté le cadre : « bootstrap en cours » ne signifie
donc pas `factory` et ne permet jamais un second premier claim. L'autorisation
d'heure intervient après ce claim, avant l'admission de toute activité normale
pays/Wi-Fi/photo. Une reconnexion TLS normale stricte peut être nécessaire pour
valider le candidat avant clôture ; elle n'ouvre pas encore ces activités.
Un owner valide sur un cadre adopté ne suffit pas : il faut aussi la preuve de
cette phase initiale non clôturée.

| Situation | Proposition v0 | Besoin produit ultérieur |
|---|---|---|
| Cadre neuf, premier claim durable, phase initiale ouverte | Assertion fraîche autorisée, opération journalisée, certificat puis clôture | Aucun élargissement implicite |
| Premier parcours interrompu avant clôture | Reprise du même intent/frame/owner autorisé et des résultats durables ; jamais rejeu d'heure | Tester toutes les coupures de processus |
| Candidat prêt, TLS stricte pas encore confirmée, phase encore ouverte | Lecture du DER exact ; correction fraîche seulement sous admission bootstrap et invalidation cohérente du candidat précédent | Mécanisme de confirmation et de remplacement à figer avant wire |
| Phase en clôture ou clôturée, ACK perdu | Lecture/reprise du candidat exact et de la clôture, sans nouveau setter | Reconnexion TLS normale stricte |
| Cadre utilisé puis horloge invalide ou certificat expiré | Pas de setter général ; récupération explicite, sans réouverture factory | Réparation authentifiée par l'owner, à concevoir séparément |
| Fonctionnement normal après clôture | Politique NTP normale de l'OS ; aucune nouvelle assertion d'heure via cette frontière v0 | Qualification hors réseau et après stockage prolongé |

Cette réduction de périmètre ne supprime pas le besoin de réparation ultérieure.
Il reste dans le [plan commun](PRODUCT-COMPLETION-PLAN.md), lots 5/7 et cas
« Certificat expiré ou horloge future », ainsi que dans FB-07 du
[contrat premier boot](FIRST-BOOT-CONTRACT.md). La ligne « Already adopted » de
la [décision TLS](BOOTSTRAP-TLS-DECISION.md) décrit une cible plus large : en v0,
seule sa reprise d'installation initiale encore ouverte est admise. La réparation
d'un cadre dont le bootstrap a été clôturé reste un lot distinct ; elle n'est
ni implémentée ni rendue optionnelle pour déclarer le produit global terminé.

L'exclusion d'activité normale doit être imposée par le lifecycle serveur,
le helper et la frontière OS, y compris après reboot : pas de scheduler photo,
d'API photo, de scan/association ni de transaction Wi-Fi pendant cette phase.
L'absence de bouton iOS, de réseau disponible ou de photos n'en constitue pas
une preuve. L'écran d'accueil/QR peut avoir un refresh en cours : il conserve
son unique propriétaire SPI et ses exigences de drain.

Les primitives Studio utilisées comme référence sont figées dans `2ed52cd` :
`ownership.py` atomise claim/owner/adoption ; `bootstrap_identity.py` lie le
résultat d'heure à l'opération de certificat ; `first_boot.py` conserve l'intent
d'initialisation. Un `ClockResult` construit en mémoire ne prouve pas un appel
système. Sa plage 2026–9998 est une limite de sérialisation du certificat, pas
une politique admissible de réglage de l'horloge.

La lecture OS porte sur le checkout isolé local `609e3baa` :
`scripts/bootstrap-system-model.py` contient encore des adaptateurs fictifs
pour heure/pays ; `scripts/initialization-server.py` n'accepte qu'IPC-A.
Le modèle heure n'a ni ID durable ni journal NTP et répète le setter si on le
rappelle. Le modèle pays ne prouve pas lui-même l'admission sous TLS stricte.
Les principes de persistance de `scripts/initialization-receipt.py` (fichier
root, verrou stable, fsync fichier/remplacement/répertoire) sont réutilisables,
mais ce reçu d'initialisation n'est pas un journal de mutations heure/pays.
L'unité `staging/bootstrap/inkyos-initialization.service` protège l'horloge et
isole réseau/périphériques : ne pas y ajouter simplement des setters privilégiés.

### État durable à réutiliser et clôture à compléter

Le journal de [l'identité bootstrap](../../server/inky_web/provisioning/bootstrap_identity.py)
est la première base à réutiliser : `_intent` lie l'opération à l'intent
d'initialisation, au frame et au SPKI ; `_publish` conserve les octets exacts du
candidat avant publication, puis un résultat `completed` rejouable sans nouvelle
génération de certificat. Ses 64 opérations ne sont pas évincées. En revanche,
son schéma actuel ne contient ni owner, ni credential epoch, ni phase/clôture ;
`repair_existing` peut encore créer une opération après une publication achevée.
Il ne prouve pas une mutation OS ni la fraîcheur de l'heure actuelle.
Il n'offre pas non plus de statut public d'opération indépendant de `ClockResult`,
ni de transition de remplacement d'un candidat `pending` : un nouvel ID est alors
refusé. Une invalidation de candidat n'est donc pas une capacité déjà disponible.

Le ledger [factory](../../server/inky_web/provisioning/factory.py) reste limité
à `pending`/`factory`/`adopted`. Le [claim](../../server/inky_web/provisioning/ownership.py)
enregistre atomiquement `adopted` et `first_owner_id`, mais n'enregistre pas la
fin du bootstrap. Ces primitives sont donc utiles, pas suffisantes telles quelles.

Privilégier une extension versionnée du journal identité/certificat, reliée au
ledger d'ownership, pour porter la phase et sa clôture. Si elle ne permet pas
la preuve requise entre les frontières, utiliser un latch durable explicite
lié à l'intent d'initialisation, au frame/SPKI, au premier owner et à son epoch
d'admission, puis à l'opération/candidat de clôture. Il ne remplace ni le ledger
d'ownership ni le journal root des effets OS. Ne pas créer un état concurrent
sans règle de cohérence et de reprise après chaque écriture.

Une phase absente, incohérente ou perdue exige une récupération explicite.
L'absence de réseau, d'owners, de DB ou de certificat ne crée jamais un latch
ouvert. Un reboot, un ACK perdu, un owner révoqué ou un changement d'epoch ne
rouvre pas une phase clôturée et ne la réattribue pas silencieusement.

Avant de figer le wire, définir la clôture et la publication comme une seule
séquence de reprise sous la barrière commune. Deux frontières de clôture doivent
être distinguées :

| Moment de clôture | Conséquence | État de la décision |
|---|---|---|
| Avant publication ou dès qu'un candidat est prêt | Écarte tout nouveau setter, mais peut bloquer le setup si le certificat échoue encore en TLS stricte | Non retenu implicitement : nécessiterait une récupération après clôture déjà disponible |
| Après validation du candidat et reconnexion TLS normale stricte, avant admission pays/Wi-Fi/photo | Permet de corriger un candidat pendant la phase initiale ; exige une preuve liée au candidat et une admission normale encore fermée | Direction v0 proposée, mécanisme et coupures à résoudre avant wire |

La seconde direction requiert les étapes suivantes, sans les présenter comme
déjà implémentées :

1. Après un résultat d'heure vérifié dans son contexte encore admissible,
   journaliser puis publier le candidat exact et son ID. Le candidat prêt ne
   prouve ni la clôture ni une autorisation d'activité normale.
2. Autoriser sa lecture/reprise et une connexion TLS normale stricte limitée à
   la validation de ce candidat. Le profil bootstrap reste sans pays/Wi-Fi/photo ;
   le canal normal de validation n'admet pas non plus ces opérations à ce stade.
3. Tant que la phase initiale reste ouverte, une nouvelle correction demande
   une assertion fraîche, un nouvel ID et l'owner/epoch courants sous la même
   barrière, après résolution de l'opération précédente et preuve de quiescence.
   Elle invalide durablement l'ancienne validation et tout candidat
   qu'elle remplace, sans effacer les journaux ni rejouer l'heure historique.
   Résoudre explicitement le candidat `pending`, les sessions en vol et les
   résultats tardifs ; jamais deux candidats concurrents réputés courants.
4. Après la preuve de reconnexion stricte liée au candidat courant, engager
   la clôture durable, rendre le refus du setter effectif à chaque frontière,
   y compris OS, et prouver la quiescence. Achever cette clôture avant toute
   admission pays/Wi-Fi/photo. Un état incertain interdit un nouveau setter et
   les activités normales ; la première association Wi-Fi ne sert pas de clôture.
5. Si l'ACK de clôture se perd, lire sous authentification courante le candidat
   et l'état durable, puis terminer uniquement la clôture déjà engagée. Ne pas
   répéter l'heure, régénérer le candidat ou rouvrir le setter. Une reconnexion
   normale exige toujours la validation stricte du certificat courant.

Le protocole doit préciser l'auteur et le contenu de la preuve de reconnexion,
liée à l'intent/frame/SPKI, à l'owner/epoch, à l'ID d'opération, au hash du candidat
courant et à une fraîcheur de session. Une confirmation authentifiée sur le
canal normal peut porter cette liaison ; un ACK UI non lié au candidat ou une
simple valeur booléenne transmise à l'OS ne suffisent pas. La vérification stricte
du certificat est une garantie du code iOS à tester : le serveur ne peut pas
attester à distance l'implémentation du vérificateur d'un client arbitraire.
Ne pas ajouter une exigence implicite d'attestation distante. Un ACK d'un ancien
candidat ou epoch ne clôture jamais le nouveau parcours.

Si cette preuve, l'invalidation ou la transition entre journaux ne peuvent pas
être définies sans ambiguïté, le wire reste bloqué : ne pas choisir silencieusement
une fermeture irréversible. Une phase réellement clôturée reste fermée même si
son certificat devient ensuite inutilisable : récupération explicite ou futur
lot de réparation owner, sans reset d'adoption. Le journal actuel ne réalise
pas encore cette séquence.

## Frontière locale proposée

Le service root utilise un socket distinct d'IPC-A et un groupe réservé au
helper. L'UID kernel du helper explicitement installé est l'unique client
admis ; l'UID de l'app, root comme client et les UIDs inconnus sont refusés.
Le helper vérifie l'UID root du serveur avant tout envoi. Les champs JSON
déclarant un UID ou un chemin ne confèrent jamais d'autorité.

Le nom du socket, les modes exacts, les schémas et les limites seront figés avec
les fixtures communes. Reprendre les exigences IPC-A : JSON strict sans doublon,
types fermés, tailles bornées LF inclus, une réponse/connexion puis EOF,
deadline monotonic globale, erreurs fixes sans données confidentielles.
Ne pas étendre silencieusement le protocole network-helper v1.

L'authentification locale du helper ne prouve pas à elle seule un consentement
iPhone. Studio et le helper restent responsables de l'owner courant, de son
epoch, de la fraîcheur du challenge et du profil TLS. Les IDs de corrélation
transmis au service OS ne deviennent pas des preuves cryptographiques.
Avant activation, le contrat app→helper doit rendre cette admission vérifiable
et lier sa révocation à la même barrière que les mutations OS.

## Opérations logiques à figer

Ces noms décrivent des responsabilités ; ils ne sont pas des méthodes déjà
acceptées par un socket ou par BLE.

| Opération | Entrées minimales | Résultat utile |
|---|---|---|
| Lire l'état | ID de requête frais | Disponibilité OS, état NTP observé, gate pays/radio, opération active ; aucune mutation |
| Lire une opération | ID de requête + ID durable d'opération | Résultat durable ou incertain ; aucune répétition d'effet |
| Accepter une assertion d'heure | ID durable + intent/frame/owner/epoch + preuve de phase initiale ouverte + timestamp entier UTC borné | État vérifié de l’application de l’assertion et politique NTP inchangée observée ; aucune permission après clôture |
| Clôturer la phase heure | Liaison durable à l'opération, au candidat courant et à sa preuve de reconnexion stricte, sous la barrière commune | Fermeture irréversible du setter v0 avant admission pays/Wi-Fi/photo ; résultat relisible après ACK perdu |
| Appliquer le pays confirmé | ID durable + liaison frame/epoch/admission normale + code de l'allowlist | Pays demandé, domaine effectif observé sur la radio épinglée, gate encore fermé ou qualifié |
| Réconcilier le gate | Autorité OS au boot et état pays durable existant | Réobservation courante ; un ancien ACK seul ne libère jamais la radio |

Pas de méthode générique commande/path/interface/D-Bus, de sélection du binaire,
de timezone, de mode relatif, de reset factory ou de nouveau réseau dans cette
frontière. Le matériel et l'interface cibles viennent de la configuration OS
épinglée, jamais d'un choix libre du téléphone.

## Journal et sémantique de reprise

Chaque mutation possède un ID durable conservé avant son premier envoi, distinct
de l'ID de requête RPC. Le journal lie cet ID au type d'opération, à son contenu
canonique, à l'autorité d'admission, au frame/epoch et à une génération OS.
Même ID et autre contenu : refus. Même ID et même contenu : lecture du résultat
déjà connu, jamais répétition d'un setter d'heure.

Proposition d'états durables : `prepared`, `effect_attempted`, `verified`,
`uncertain`, `rejected`. L'intention puis la marque `effect_attempted` sont
persistées et synchronisées avant l'appel pouvant muter le système. Le résultat
vérifié est persisté avant l'ACK. Un manque d'espace, une corruption ou une perte
de journal ferme l'admission et exige une récupération explicite.

Le modèle Wi-Fi actuel conserve seulement un nombre borné de demandes récentes.
Il ne doit pas être réutilisé tel quel pour l'heure : évincer un ID rendrait
possible la réapplication d'un ancien timestamp. La v0 retient 64 opérations
sans éviction ni compaction. Toute extension future
devrait conserver une preuve de rejet de tous les anciens IDs ; elle ne peut
pas rouvrir une admission par oubli d’un ID.

| Coupure | Reprise autorisée |
|---|---|
| Avant admission durable | Nouvelle admission fraîche possible après authentification et preuve de phase initiale encore ouverte |
| Après `prepared`, avant l'effet | Aucune relance automatique d'un timestamp stocké ; fermer/inspecter puis demander une assertion fraîche seulement si la phase reste ouverte |
| Après `effect_attempted`, avant résultat durable | `uncertain` ; lecture/réconciliation uniquement, jamais nouvel appel du setter avec cet ID |
| Après résultat durable, ACK perdu | Retourner le résultat mémorisé sans effet système |
| Nouveau boot | Invalider les autorisations/challenges transitoires ; conserver le journal ; ne pas rejouer les timestamps |

Une expiration côté client ne signifie pas que l'appel système est annulé.
La barrière reste occupée tant qu'un effet peut encore se terminer. Avant une
nouvelle opération, un changement d'epoch ou une reprise après crash, il faut
prouver la fin de l'ancien exécutant et des appels privilégiés en vol. Si cette
quiescence n'est pas démontrable, rester en récupération explicite. Ni une
fermeture de socket ni un timeout D-Bus n'en constituent la preuve.

Un reçu historique n'atteste jamais l'heure actuelle et n'autorise pas à lui
seul une nouvelle émission/réparation de certificat. Studio peut retrouver le
candidat exact déjà journalisé et le vérifier dans le contexte présent. S'il
faut une nouvelle correction, obtenir une assertion fraîche et un nouvel ID
d'opération, sans rejouer l'ancien timestamp ni régénérer silencieusement un
certificat sous l'ancien ID. En v0, cette nouvelle correction exige aussi une
phase initiale encore ouverte ; aucune reprise de résultat ne contourne la clôture.

La même admission doit suspendre la programmation d'images et terminer le refresh
en cours avant une correction d'heure. Le scheduler actuel utilise l'horloge
civile et `displayed_at` : après correction, recalculer explicitement son
échéance sans consommer la file ni lancer une rafale de rattrapage. Garder le
seul propriétaire SPI et les protections de drain ; ne jamais couper un refresh.
En v0, l'admission doit déjà prouver que les activités normales sont exclues,
plutôt que prétendre les avoir suspendues parce que l'UI ne les affiche pas.
Une activité photo/scheduler détectée refuse le setter et exige diagnostic ;
les exigences pause/drain/réconciliation ci-dessus restent obligatoires pour le
futur lot de réparation après clôture. Le drain d'un refresh d'accueil/QR et
les barrières révocation/epoch restent requis dès la v0.

## Politique heure v0 et observation NTP

Choix de politique convenus entre Studio et InkyOS le 11 octobre 2026, pour un
prototype isolé. Ils ne constituent ni une API installée ni une qualification du
setter réel. Le schéma d’admission owner/epoch/latch reste à figer avant le wire.

| Élément | Politique v0 retenue |
|---|---|
| Assertion | Entier UTC en **secondes**, booléens et floats refusés |
| Plage | `2026-01-01T00:00:00Z ≤ t < 2100-01-01T00:00:00Z` |
| Fraîcheur | Challenge expirant au plus 30 secondes sur `CLOCK_BOOTTIME` Linux après sa **création côté service OS**, sans nouvelle fenêtre à réception de la réponse |
| Mesure iPhone | Timestamp frais au moment de répondre ; aucune compensation implicite du payload par le serveur |
| Recul/avance | Tous deux admis seulement dans le bootstrap initial ouvert ; aucun high-water civil permanent |
| Effet | Worker dédié, un seul `clock_settime_ns(CLOCK_REALTIME, requested_seconds * 1_000_000_000)` ; aucune conversion float |
| Vérification | Intervalle complet d’erreur du readback dans ±2 secondes ; sinon `uncertain` |
| Journal | 64 opérations au maximum, sans éviction ni compaction ; plein = refus/récupération, jamais recyclage d’ID |

La fraîcheur ne dépend pas de l’horloge civile corrigée. Le service OS utilise
`clock_gettime_ns(CLOCK_BOOTTIME)` pour le TTL et les quatre bornes ci-dessous :
la suspension compte dans le délai, aucun fallback silencieux vers
`CLOCK_MONOTONIC` n’est admis. Un nouveau boot invalide le challenge ; les valeurs
monotonic ne sont jamais comparées entre deux boots. Le TTL est contrôlé à la
réception puis immédiatement avant l’effet, après drain, attentes et fsync ;
une assertion expirée pendant ces étapes ne peut pas être appliquée. Une nouvelle correction
exige une assertion fraîche et un nouvel ID, sous la même admission initiale ;
elle n’ouvre aucun setter après clôture. Les multiplications et bornes doivent
être vérifiées avant l’appel OS. `ClockResult.epoch_seconds` reste en secondes :
le résultat conserve séparément assertion demandée, readback et leurs unités ;
le choix du champ d’émission du certificat n’est pas implicite.

Encadrer l’appel du setter par les lectures `CLOCK_BOOTTIME` nanosecondes `[e0, e1]`,
puis la lecture civile `R = clock_gettime_ns(CLOCK_REALTIME)` par `[r0, r1]`,
avec `e0 ≤ e1 ≤ r0 ≤ r1`. Pour
`Q = requested_seconds * 1_000_000_000`, l’intervalle d’erreur conservateur est :

```text
[R - Q - (r1 - e0), R - Q - (r0 - e1)]
```

Exiger que cet intervalle soit **entièrement** inclus dans
`[-2_000_000_000, +2_000_000_000]`. Un simple chevauchement ne suffit pas. Le
parent constate la fin et le réapage du worker avant résultat durable/ACK ; un
timeout seul ne démontre pas la quiescence. Les marques `prepared` et
`effect_attempted` précèdent toujours l’effet, selon le journal ci-dessus.

Le worker v0 ne demande ni `SetNTP` ni changement de timezone et ne démarre/
n’arrête aucun service NTP. La politique NTP configurée reste inchangée et doit
être observée ; le réglage de l’horloge peut cependant invalider l’état de
synchronisation du kernel. Un service NTP actif peut aussi corriger l’heure en
parallèle : toute discordance au readback produit un résultat incertain, jamais
un second setter implicite. Disponibilité, activation et synchronisation sont
rapportées séparément ; un effet réussi ne prouve pas une heure UTC fiable.

Cette direction évite la gestion d’une suspension/restauration de service.
Si son implémentation nécessite finalement de modifier la politique NTP, revoir
le contrat avant de coder cet effet : journalisation préalable et récupération
durable de cette politique redeviennent obligatoires. La qualification du kernel,
des privilèges et de la politique OS réels demeure ouverte.

Sources primaires : [horloge incluant la suspension](https://docs.python.org/3.13/library/time.html#time.CLOCK_BOOTTIME),
[entiers nanosecondes Python 3.13](https://docs.python.org/3.13/library/time.html#time.clock_settime_ns),
[mise à jour du temps Linux 6.18](https://github.com/torvalds/linux/blob/v6.18/kernel/time/timekeeping.c),
[état NTP Linux 6.18](https://github.com/torvalds/linux/blob/v6.18/kernel/time/ntp.c).
L’alternative systemd `SetTime`/`SetNTP` n’est pas retenue pour ce prototype ; sa
[politique polkit](https://github.com/systemd/systemd/blob/main/src/timedate/org.freedesktop.timedate1.policy)
ne doit pas être présentée comme une permission limitée au seul setter.

## Pays, radio et transactions réseau

Le pays est un choix explicite du lieu d'utilisation, validé dans une allowlist
versionnée. Il ne vient ni de la nationalité, ni de la langue, ni du fuseau.
Une connexion Wi-Fi active ou une transaction en cours interdit le changement
de pays. Définir une déconnexion/annulation complète et vérifiée avant un nouvel
essai, sans déplacer ce travail dans le setter pays. La transition pays conserve
la radio désactivée : gate fermé → état `pending` durable → apply → observation
effective acceptée → état `confirmed` durable → ACK pays, radio toujours fermée.

Au premier boot, NetworkManager peut tourner avec scan/autoconnect/radio tenus
fermés par InkyOS. La qualification du pays doit précéder toute ouverture Wi-Fi.
Ce gate vise le Wi-Fi ; le BLE d'adoption doit rester disponible avant le pays.
Le succès exige une observation de la radio/PHY épinglée et de ses règles
effectives, pas seulement le succès de `iw reg set` ou un code global demandé.
Le noyau peut conserver des restrictions propres au pilote ; choisir une
politique conservatrice et explicite pour un domaine effectif différent.
Source : [traitement des domaines réglementaires](https://wireless.docs.kernel.org/en/latest/en/developers/regulatory/processing_rules.html).

La politique TEST OS existante (`scripts/test-access-network.py`) est limitée
à FR/Pi Zero 2 W : firmware FR/FR, domaine global FR, PHY FR **ou `99`** avec
contraintes de canaux 2,4 GHz. Une simple égalité PHY/pays casserait le cas
Broadcom prévu. Cette politique de banc n'établit aucun support multi-pays ni
certification RF ; le modèle `gate_open` est une permission logique et non une
preuve d'activation matérielle.

L'ACK pays qualifie la configuration radio fermée. Il permet ensuite une étape
distincte d'activation contrôlée, puis d'observation de disponibilité réelle
avant scan/association. Ne pas attendre une radio active pour autoriser son
activation : cela créerait un cycle. La demande d'activation seule n'est pas
un ACK de disponibilité. Observer séparément le blocage matériel et logiciel,
la disponibilité du périphérique et la politique d'autoconnect. Les propriétés NetworkManager distinguent notamment
`WirelessEnabled` et `WirelessHardwareEnabled` ; elles ne prouvent pas à elles
seules le domaine réglementaire ou la connexion.
Source : [API NetworkManager](https://www.networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.html).

Après reboot ou changement du périphérique, réconcilier le pays durable avant
d'autoriser scan/association. Un ACK d'un boot précédent ne remplace pas cette
lecture. Les anciens cadres déjà configurés ont besoin d'un parcours de migration
préservant leur configuration ; cette proposition n'ajoute aucun blocage Wi-Fi
automatique par simple mise à jour de l'app.

## Contradictions et décisions qui bloquent l'activation

| Point | Décision/proof requis |
|---|---|
| Admission limitée au bootstrap v0 | Phase initiale durable distincte d'`adopted`, owner/epoch courants et exclusion effective des activités normales sur toutes les entrées |
| Journal/latch et clôture v0 | Extension versionnée privilégiée ; liaison intent/frame/SPKI/owner/epoch, fermeture après preuve stricte avant admission pays/Wi-Fi/photo ; coordination des journaux et reprise ACK sans rouvrir le setter |
| Candidat prêt vs bootstrap terminé | Canal de validation limité, preuve stricte liée au candidat courant, invalidation/remplacement cohérent sous correction fraîche ; aucun ancien ACK ni candidat `pending` ambigu |
| Réparation après clôture | Lot produit séparé conservé dans le plan global ; aucun setter v0 général ni reset factory pour remplacer cette capacité |
| Anti-rejeu de l'heure | Schéma exact et reprise du journal borné à 64 opérations sans éviction ; aucun ancien ordre réadmis |
| Horloge propriétaire vs UTC fiable | Qualifier les bornes 2026–2100, challenge 30 s, corrections initiales et intervalle readback ±2 s ; pas de preuve UTC indépendante |
| Unités et reçu certificat | Conversion entière secondes/nanosecondes, champs assertion/readback distincts et liaison au certificat à préciser ; aucun reçu historique interprété comme preuve fraîche |
| Mutation vs révocation | Barrière commune avec rotation de mot de passe/epoch ; le mutex BLE actuel seul ne suffit pas |
| Horloge vs scheduler | V0 : exclusion prouvée des activités normales et drain du QR ; réparation ultérieure : pause/drain puis recalcul d'échéance sans consommer de photo ni rattrapage |
| Timeout vs effet terminé | Preuve de quiescence des exécutants et appels OS avant nouvelle admission |
| Politique NTP | Qualifier le worker clock_settime_ns, politique de service inchangée, observation séparée et concurrence NTP ; aucun SetNTP dans la v0 |
| Admission app→helper | Nouveau contrat strict et liaison à l'owner/epoch ; ne pas utiliser les IDs comme preuve d'autorité |
| Pays vs gate | Allowlist versionnée, PHY épinglée, politique domaine effectif et vraie disponibilité radio |
| Factory vs migration | Distinguer image neuve, cadre adopté et state manquant sans reset implicite |

## Matrice minimale de validation

- Phase initiale ouverte après premier claim, cadre adopté déjà utilisé, phase
  en clôture/clôturée, DB/journal manquant, owner révoqué ou epoch changé : seul
  le parcours initial explicitement admissible peut invoquer le setter v0.
- Coupure entre chaque écriture de candidat, fermeture Studio/helper/OS,
  publication et ACK : aucune réouverture ; reprise du candidat exact ou
  récupération explicite, sans admission pays/Wi-Fi/photo prématurée ; TLS normal
  limité à la validation tant que la clôture n'est pas achevée.
- Candidat prêt mais TLS stricte échouée, correction fraîche avant clôture,
  ancien ACK après remplacement, résultat tardif d'un autre candidat : aucune
  fausse clôture ni validation de l'ancien candidat ; reprise explicitement définie.
- ACK perdu après clôture, client relancé ou reboot : lecture authentifiée du
  résultat et nouveau handshake strict ; aucune nouvelle assertion v0 acceptée.
- Activité normale présentée pendant bootstrap, même sans UI : photo, scheduler
  et réseau refusés ; présence d'une telle activité interdit le setter.
- Vrais UIDs Linux : helper admis, app/root/autre UID refusés, serveur imposteur
  refusé avant tout octet ; schémas/tailles/deadlines stricts.
- Timestamp ancien sous même ID, même ID avec autre contenu, nouveau boot,
  corruption, journal plein/compacté : aucun second appel du setter historique.
- Coupure avant/après chaque fsync, après appel OS, avant résultat et après ACK :
  résultat conservateur, politique NTP inchangée et absence de faux succès.
- Révocation/rotation pendant admission, effet en vol et ACK perdu : aucune
  mutation tardive autorisée par un ancien epoch.
- Refresh et programmation actifs lors d'une correction : drain terminé, file
  inchangée, échéance réconciliée, jamais deux propriétaires SPI.
- Date très passée/future, correction en arrière, NTP absent/actif/non synchronisé,
  correction concurrente ou readback incertain : résultat borné et reprise documentée.
- Pays invalide/différent, transaction Wi-Fi active, PHY remplacée, radio lente,
  reboot avec ancien ACK : aucun scan/association avant qualification courante.
- Après réparation : même frame/clé, nouveau certificat valide, TLS normale
  stricte, puis seulement pays/Wi-Fi et confirmation HTTPS.

Références Studio : [contrat premier boot](FIRST-BOOT-CONTRACT.md),
[décision TLS bootstrap](BOOTSTRAP-TLS-DECISION.md),
[coordinator](FIRST-BOOT-COORDINATOR.md),
[IPC-A](INITIALIZATION-IPC-V1.md),
[plan commun](PRODUCT-COMPLETION-PLAN.md).
