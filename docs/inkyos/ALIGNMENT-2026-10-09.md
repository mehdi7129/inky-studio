# Alignement InkyOS / Studio pour le banc matériel

Relevé du **9 octobre 2026**, destiné à la session InkyOS. Ce document distingue
le banc LAN possible aujourd'hui de la cible de premier allumage sans LAN.
Il ne donne pas à l'image le statut de release qualifiée.
Dernier retour daté du **11 octobre** : Wi-Fi connecté et deux échanges SSH
authentifiés observés sur la SD corrigée. Préflight OS bloqué, app et helper
toujours arrêtés et masqués. La stabilité réseau, BLE, l'affichage et l'appairage
restent à qualifier ; les observations d'échec précédentes restent historiques.

## Complément du 10 octobre — retour SD et installation iPhone

La session InkyOS a publié le
[diagnostic réseau](https://github.com/mehdi7129/inkyOS/blob/7462944261d5a548a67f2e723c7c0d5e67ff85be/docs/BOOT-NETWORK-DIAGNOSIS.md)
au commit documentaire `7462944261d5a548a67f2e723c7c0d5e67ff85be`.
Studio a relu ce rapport ; l'acquisition SD n'a pas été reproduite ici.

- Installation de **TestFlight build 9** confirmée par l'opérateur, relayée
  par InkyOS ; pas d'observation directe de l'installation par Studio.
- Le retour SD en lecture seule contient un état `enrolled` valide et un cache
  Wi-Fi `imported` complet. Capsule, signature et bindings sont cohérents.
  Cela confirme un import au moins une fois, pas une connexion réseau.
- Configuration opérateur absente, `WirelessEnabled=false` enregistré, aucun
  profil de connexion persistant et journaux persistants vides. Aucune
  connexion/SSH n'est validée. L'état sauvegardé ne permet pas d'identifier la
  cause du dernier échec ni d'exclure toute association Wi-Fi antérieure.
- Après la coupure, les données volatiles sont perdues et les fichiers
  persistants peuvent précéder le dernier boot ; aucun replay/réparation du
  journal ext4 n'a été effectué par InkyOS pendant cette lecture.
- App/helper non activés ; photo, affichage et QR/BLE attendent le réseau.

Le diagnostic de boot durable demandé après ce retour SD est maintenant
intégré à l'image de diagnostic décrite ci-dessous. Les courses rfkill/pays
reproduites sur fixtures restent des hypothèses, pas la cause matérielle
confirmée. Studio ne modifie ni protocole, payload ou services dans cette
mise à jour documentaire.

Le relevé du 9 octobre ci-dessous reste historique ; ce complément précise
l'installation et l'état du banc sans qualifier les parcours matériels.

## Complément du 10 octobre — image de diagnostic construite

InkyOS a publié les preuves au commit
[`f3eb35589834251769bc4a63495dcdedf8f32dcf`](https://github.com/mehdi7129/inkyOS/commit/f3eb35589834251769bc4a63495dcdedf8f32dcf).
Studio a relu les rapports expurgés et vérifié la
[CI réussie sur ce commit](https://github.com/mehdi7129/inkyOS/actions/runs/38083401924).
Les builds, bancs VM et hashes d'images sont rapportés par InkyOS ; Studio
n'a ni reconstruit ni inspecté l'image privée.

| Référence | SHA-256 / portée |
|---|---|
| Parent TEST LAN reconstruit | `dcc451dc927eeb5ba202ca480005351a7516c13bc057f6946e4023efea91a595` |
| Manifeste runtime de l'image de diagnostic | `bedfc3c6b9854bde2081b3b00ebfe5cc4d48c4cd4c1cbb7db9942a72dbd5277b` |
| Payload Studio | Source `c31b13a`, manifeste `c4183e7` détaillés ci-dessous, inchangés |
| App iPhone | Build 9, source `181edb2`, inchangée |

Le [rapport du parent reconstruit](https://github.com/mehdi7129/inkyOS/blob/f3eb35589834251769bc4a63495dcdedf8f32dcf/docs/validation/2026-10-10-rebuilt-test-lan-parent.json)
conserve les mêmes entrées système et applicatives épinglées. Les anciennes
images étant indisponibles, la comparaison porte sur leurs inventaires
enregistrés, pas sur une nouvelle lecture des anciennes images. Un premier
essai natif a échoué sans détail ; la reprise a revérifié le parent vierge
avant personnalisation et les exports finaux passent les contrôles d'intégrité.

Les [preuves logicielles du diagnostic](https://github.com/mehdi7129/inkyOS/blob/f3eb35589834251769bc4a63495dcdedf8f32dcf/docs/validation/2026-10-10-persistent-boot-diagnostics.json)
rapportent **1 031 tests par plateforme**, sans échec ni erreur : 4 ignorés sur
macOS, 1 sur Linux ARM64. Les 23 scripts passent la vérification de syntaxe
sur chaque plateforme ; le banc inerte systemd de stockage des rapports passe.
Le diagnostic reste à schéma fermé, sans SSID, mot de passe, clé, identité de
cadre ni sortie brute ; il n'accorde aucune autorisation réseau ou applicative. Un
ancien rapport peut survivre à une écriture échouée : sa présence seule ne
prouve pas le résultat du dernier boot.

Le [rapport de l'image privée](https://github.com/mehdi7129/inkyOS/blob/f3eb35589834251769bc4a63495dcdedf8f32dcf/docs/validation/2026-10-10-diagnostic-access-image.json)
rapporte les contrôles **17 parent / 62 système / 26 application / 18 accès**
réussis, ainsi que fsck ext4/FAT, unités systemd, sudoers et différences de
fichiers autorisées. Il conserve la provenance de construction
`db034269a14c7585df9cf4962807819fa048d7ae` avec arbre modifié et concordance
des hashes des sources avec les tests logiciels ; le commit `f3eb355` est la
publication des preuves, pas une assertion de build depuis un arbre propre.
Le vérificateur contrôle la cohérence de l'export, sans démarrer l'image ni
authentifier indépendamment des manifestes locaux non signés.

**État au relevé de construction : préflight de flash réussi, SD non écrite,
image non démarrée.** Le retour SD ultérieur est décrit dans le complément
suivant. Le runtime et les profils d'accès sont liés au nouveau manifeste ;
le cycle prévu par InkyOS exigeait un flash vérifié, un premier boot
d'enrôlement suivi d'un arrêt, puis une nouvelle capsule signée avant l'essai
réseau. Ne pas réutiliser l'ancienne capsule ni remplacer un script isolé sur
la SD. Le parcours de premier allumage sans LAN reste à intégrer.

## Complément du 10 octobre — retour d'enrôlement et capsule installée

Le [nouveau retour SD](https://github.com/mehdi7129/inkyOS/blob/56aa8d43521804525a062ce37ce6e24585da5990/docs/validation/2026-10-10-diagnostic-sd-enrollment-return.json)
est publié au commit `56aa8d43521804525a062ce37ce6e24585da5990`, dont la
[CI passe](https://github.com/mehdi7129/inkyOS/actions/runs/38086886342).
Studio a relu cette preuve ; les opérations sur la carte sont rapportées
par InkyOS et n'ont pas été reproduites ici.

- **Enrôlement : 35 contrôles de fichiers et 10 d'infrastructure réussis**,
  contexte SSH privé exporté. L'acquisition intégrale est conservée ; la
  vérification utilise un dérivé `e2image`, qui omet les blocs libres et
  certaines métadonnées inutilisées, sans replay du journal ni exécution
  du code cible. Ce PASS établit la cohérence des fichiers avec l'export
  attendu, pas une attestation indépendante du matériel ou de son exécution.
- Le reçu de flash infère écriture, flush et relecture depuis l'endroit précis
  de l'échec d'éjection ; aucune nouvelle relecture indépendante n'a été faite
  à cette étape. L'éjection a été récupérée sans réécriture. L'acquisition
  ultérieure a été relue et rehashée localement, sans seconde lecture de la SD ;
  macOS avait initialement monté FAT, donc l'acquisition n'est pas protégée
  contre toute écriture dès l'insertion.
- **Deux diagnostics persistants valides** : garde WLAN, 10 contrôles réussis ;
  boot, marqueur initial incomplet. Aucune cause de panne ni observation
  indépendante de l'arrêt n'en est déduite. Ces diagnostics n'autorisent
  aucune connexion ou activation.
- **Nouvelle capsule signée**, liée au nouveau contexte, installée sur la SD
  et relue ; carte éjectée. À ce relevé du 10 octobre, son import au runtime
  n'était pas encore prouvé et le boot réseau attendait l'opérateur.
  Le retour suivant est décrit dans le complément du 11 octobre.

Backend `c31b13a`, manifeste applicatif `c4183e7` et build iOS 9 inchangés.
Aucune connexion Wi-Fi/SSH, activation applicative, photo, affichage ou adoption
iPhone n'est confirmée par ce retour. La suite reste le banc réseau puis
préflight/activation piloté par InkyOS, avant les essais de l'app ci-dessous.

## Complément du 11 octobre — échec d'activation réseau observé

Le [retour réseau ciblé](https://github.com/mehdi7129/inkyOS/blob/07271cf849e24d3a09307898d6fd166253f27a89/docs/validation/2026-10-11-network-activation-return.json)
est publié au commit `07271cf849e24d3a09307898d6fd166253f27a89`, dont la
[CI passe](https://github.com/mehdi7129/inkyOS/actions/runs/38090421106).
Studio a relu cette preuve ; l'inspection SD est rapportée par InkyOS.
Le PASS porte sur la lecture de deux reçus valides et complets ; le résultat
de connexion est **`CONNECTION_FAILED`**.

- Le reçu d'import indique un nouvel import signé réussi ; garde WLAN 10/10,
  profil et contrôles préalables réussis. Les observations pays FR passent
  pour firmware, kernel et canaux ; la commande d'allumage radio est acquittée.
- L'activation NetworkManager échoue, puis l'arrêt radio est demandé, acquitté
  et vérifié. Aucun démarrage SSH n'est demandé ; aucune activation de l'app.
  Les contrôles post-connexion à `false` n'ont pas été atteints et ne sont pas
  des échecs indépendants.
- Les deux reçus correspondent au même boot, différent de celui de
  l'enrôlement précédent, sans attestation indépendante du dernier boot.
  Le code de sortie et la raison NetworkManager manquent dans cette variante :
  **cause exacte inconnue, rejet du mot de passe non démontré**.
- Lecture `debugfs` ciblée en read-only, sans montage ext4, replay, lecture de
  clés/capsule ni réseau. Ni acquisition intégrale ni contrôles d'enrôlement
  35 + 10 répétés. Le journal ext4 à récupérer peut masquer des mises à jour ;
  les reçus peuvent précéder le dernier boot. La lecture n'établit pas une
  protection contre toute écriture depuis l'insertion, et le démontage peut
  vider des écritures macOS déjà en attente.

Les [tests du diagnostic supplémentaire](https://github.com/mehdi7129/inkyOS/blob/07271cf849e24d3a09307898d6fd166253f27a89/docs/validation/2026-10-11-activation-diagnostics-tests.json)
rapportent **1 039 tests par plateforme**, zéro échec/erreur, 4 ignorés macOS
et 1 Linux ARM64 ; 23 scripts passent la vérification de syntaxe.
Le nouveau code conserve le code de sortie connu et, sur échec seulement,
un snapshot numérique fermé état/raison, dans un budget borné protégeant le
nettoyage. Aucun texte brut, secret ou nouvel essai d'activation n'est ajouté.
Ce snapshot futur ne prouvera pas à lui seul la cause de l'échec initial.

Au relevé `07271cf`, aucune nouvelle image n'était encore construite ou
déployée pour cette extension. La préparation suivante est documentée ci-dessous.
Les lecteurs de la future image doivent accepter et valider indépendamment le
champ `connection.activation` ; l'ancienne SD garde son schéma actuel.

### Journaux existants et nouvelle image de diagnostic

Les deux preuves suivantes sont publiées au commit InkyOS
`846bea52ecea12302dfdbd919952acb2e86cc296`, dont la
[CI passe](https://github.com/mehdi7129/inkyOS/actions/runs/38091438323).
Studio a relu ces preuves publiques ; l'inspection et la construction privées
restent rapportées par InkyOS.

L'[inventaire ciblé des journaux](https://github.com/mehdi7129/inkyOS/blob/846bea52ecea12302dfdbd919952acb2e86cc296/docs/validation/2026-10-11-system-log-inventory.json)
passe en lecture seule : **zéro fichier sélectionné, zéro octet copié**.
La recherche couvre les journaux système autorisés et trois fichiers texte,
sans journaux utilisateur ou fichiers auxiliaires. Elle ne démontre pas une
absence générale de traces, ne récupère pas les journaux volatils et n'apporte
aucune raison supplémentaire de l'échec. Le journal ext4 n'est pas rejoué ;
les mêmes limites d'écritures en attente et de lecture depuis l'insertion
s'appliquent. Aucun nouveau boot ou essai réseau n'a lieu pendant cet inventaire.

La [nouvelle image privée](https://github.com/mehdi7129/inkyOS/blob/846bea52ecea12302dfdbd919952acb2e86cc296/docs/validation/2026-10-11-nm-diagnostic-access-image.json)
est construite depuis les sources publiques vérifiées de `07271cf`, avec
arbre modifié uniquement par des changements documentaires concurrents.
Son hash privé est vérifié ; **18 contrôles de configuration, 17 du parent,
62 système et 26 applicatifs passent**. Le parent reste `dcc451dc…a595`,
le backend `c31b13a` et son manifeste `c4183e7` ; le build iOS 9 est inchangé.
Cette image ajoute le diagnostic, sans correction de connexion revendiquée.

Au relevé `846bea5`, l'image n'était pas flashée et aucun boot cible n'était
testé. Le cycle suivant devait produire un nouvel enrôlement et une nouvelle
capsule, sans réutiliser l'ancienne identité du cadre. Le retour est décrit
ci-dessous ; les manifestes et bindings des deux images restent distincts.

### Retour natif de la SD au diagnostic NetworkManager enrichi

Le [retour complet](https://github.com/mehdi7129/inkyOS/blob/caa3ad5d1d31160aca3f71713e3146ad53bcb39c/docs/validation/2026-10-11-nm-diagnostic-enrollment-return.json)
est publié au commit `caa3ad5d1d31160aca3f71713e3146ad53bcb39c`, dont la
[CI passe](https://github.com/mehdi7129/inkyOS/actions/runs/38095394102).
Studio a relu cette preuve ; aucune opération sur la SD n'est reproduite ici.

- **35 contrôles natifs et 10 d'infrastructure réussis**. Le nettoyage est
  vérifié indépendamment et le nouveau contexte SSH privé exporté avec ses
  permissions et bindings vérifiés. Ce PASS établit la cohérence des fichiers
  d'enrôlement avec l'export attendu, pas une attestation du Pi ou du runtime.
- Acquisition directe d'un dérivé `e2image` depuis la SD ouverte en lecture
  seule, hashes du flux émission/réception concordants et relecture VM vérifiée.
  **Aucun clone intégral ni seconde lecture indépendante de la SD** ; le
  marqueur ext4 clean ne prouve ni l'intégrité globale ni un arrêt physique.
  Aucun replay ou code cible exécuté. Les clés ne sont pas ouvertes par le
  vérificateur, mais le dérivé privé peut contenir clés et autres données.
  Le démontage peut vider des écritures macOS en attente ; la protection
  contre toute écriture depuis l'insertion n'est pas établie.
- **Nouvelle capsule liée au contexte**, signature vérifiée, installée et
  relue sur la SD, puis carte éjectée. Au relevé `caa3ad5`, le prochain boot
  réseau restait à effectuer ; le retour suivant est distingué ci-dessous.
  L'installation seule ne prouve pas l'import runtime ni la connexion.

Source OS `07271cf`, backend `c31b13a`, manifeste applicatif `c4183e7` et build
iOS 9 inchangés. Aucun Wi-Fi/SSH, Bluetooth, activation de l'app, photo,
affichage ou appairage iPhone qualifié. InkyOS pilote le prochain démarrage
et la collecte du diagnostic, avant toute reprise du banc applicatif. Le lecteur
hors ligne doit rester épinglé au média de retour et valider le nouveau champ
`connection.activation` du runtime correspondant.

### Attente de disponibilité radio — validation logicielle uniquement

InkyOS a publié les [tests de readiness](https://github.com/mehdi7129/inkyOS/blob/52ddfc1a2040888f3d77196819029a74d234205b/docs/validation/2026-10-11-radio-readiness-tests.json)
au commit `52ddfc1a2040888f3d77196819029a74d234205b`, dont la
[CI passe](https://github.com/mehdi7129/inkyOS/actions/runs/38097341268).
Studio a relu les preuves ; les tests et la reproduction sur fixtures inertes
sont rapportés par InkyOS, sans association Wi-Fi réelle ou hwsim.

Le banc reproduit une disponibilité NetworkManager retardée après l'acquittement
de la commande radio. Le correctif attend `wlan0` managed, état 30 (disconnected)
et UUID actif vide, pendant **10 secondes au maximum**. Le budget global de
90 secondes préserve 37 secondes pour l'unique activation, 9 pour les contrôles
suivants et 6 pour le nettoyage. État invalide, délai dépassé ou budget
insuffisant empêchent l'activation ; le nettoyage reste prévu. Aucun nouvel
essai d'activation n'est ajouté.

**Schéma inchangé, sens renforcé pour les nouveaux reçus uniquement** :
`radio_enable_acknowledged` exige maintenant l'acquittement et la disponibilité.
Les reçus de la SD `07271cf` gardent leur sens antérieur ; une valeur à `true`
ne doit pas être réinterprétée comme une preuve de readiness sur cette SD.

**39 tests ciblés et 1 047 tests par plateforme**, zéro échec/erreur, 4 ignorés
macOS et 1 Linux ARM64 ; syntaxe de 23 scripts validée et revue indépendante
rapportée. Cette reproduction ne démontre pas la cause du boot réel.
Au relevé `52ddfc1`, aucune nouvelle image n'était construite ni SD modifiée
pour ce correctif. La carte reste sur `07271cf`, backend `c31b13a`. Son retour
et la construction suivante sont décrits ci-dessous. Aucun parcours Wi-Fi/SSH,
application, écran ou BLE n'est qualifié par ces tests logiciels.

### Retour recoupé avec état NetworkManager

Le [retour avec état du périphérique](https://github.com/mehdi7129/inkyOS/blob/2e435c9684bc6a6c59f0e6bceec04fb540371444/docs/validation/2026-10-11-network-device-state-return.json)
est publié au commit `2e435c9684bc6a6c59f0e6bceec04fb540371444`, dont la
[CI passe](https://github.com/mehdi7129/inkyOS/actions/runs/38131449503).
Studio a relu les preuves ; la lecture ciblée de la SD reste rapportée par
InkyOS. Les contrôles de média et de binding FAT passent ; les deux reçus
partagent le même identifiant de boot privé, pour la source SD `07271cf`.

| Champ du diagnostic | Valeur et portée |
|---|---|
| Sortie `nmcli` | `4` : échec d'activation, pas un rejet spécifique du mot de passe |
| État de l'interface | `20`, `UNAVAILABLE` : interface indisponible |
| Raison d'état | `2`, `NOW_MANAGED` : interface désormais prise en gestion ; ce n'est pas nécessairement la cause de l'échec |
| Budget | Attente complète disponible, budget de travail non épuisé |

L'état est échantillonné **après l'échec de l'activation et avant le nettoyage
qui coupe la radio** : l'indisponibilité observée n'est donc pas créée par cette
coupure. Ce n'est pas un historique des transitions. Import, garde radio et
pays passent ; arrêt radio vérifié ensuite, aucun démarrage SSH demandé ni
activation applicative autorisée. La disponibilité retardée est cohérente
avec ce résultat, **sans cause exacte ni rejet PSK démontrés**.

L'horloge peu fiable et le journal ext4 à récupérer, sans replay, limitent la
fraîcheur du constat : même identifiant de boot ne prouve pas indépendamment
le dernier démarrage et des mises à jour en attente peuvent manquer.
Le correctif `52ddfc1` reste absent de cette SD ; aucune réussite Wi-Fi,
validation du correctif sur matériel, SSH, BLE ou appairage n'est établie.
Au relevé `2e435c9`, InkyOS préparait la reconstruction avec ce correctif ;
aucun nouveau flash n'était rapporté. L'app et le protocole Studio restent inchangés.

### Construction de l'image avec attente radio intégrée

La [preuve de construction](https://github.com/mehdi7129/inkyOS/blob/84cbdc708284b6275a6fa560c35fd1d170e1546c/docs/validation/2026-10-11-radio-readiness-access-image.json)
est publiée au commit `84cbdc708284b6275a6fa560c35fd1d170e1546c`, dont la
[CI passe](https://github.com/mehdi7129/inkyOS/actions/runs/38132394298).
Studio a relu la preuve ; construction et revue de l'export privé sont
rapportées par InkyOS, pas reproduites ici.

- Recette `2e435c9` avec arbre propre et sources publiques concordantes ;
  correctif `52ddfc1` intégré à l'image, incluant l'attente de readiness.
- **123 contrôles offline réussis** : 18 configuration, 17 parent, 62 système,
  26 applicatifs. Hash de l'image privée vérifié et revue indépendante de
  l'export validée. Ces hashes locaux non signés prouvent la cohérence des
  fichiers, pas une authenticité indépendante.
- Parent `dcc451dc…a595`, backend `c31b13a` et manifeste `c4183e7` inchangés.
  Aucune identité de cadre existante ni clé opérateur privée copiée ; clé
  publique opérateur réutilisée, aucun identifiant Wi-Fi embarqué.
- Au relevé `84cbdc7`, aucun flash ni boot cible n'était effectué par cette
  préparation et la SD conservait `07271cf`. Le cycle demandé comprenait flash,
  nouvel enrôlement avec arrêt, retour 35 + 10 contrôles, nouveau contexte puis
  capsule signée, sans réutiliser les anciens bindings. Son résultat suit.

La construction ne confirme ni la cause du précédent échec, ni l'efficacité
du correctif sur le Pi. Wi-Fi/SSH, photo/affichage et QR/BLE restent à qualifier.
La PR Studio reste ouverte et non fusionnée ; aucune modification de l'app
ou du protocole n'est apportée par cette synchronisation.

### Retour d'enrôlement de la SD avec attente radio

La [preuve de flash](https://github.com/mehdi7129/inkyOS/blob/b1860209b1bf5eb2a740e81dc5d49ff1c41afb60/docs/validation/2026-10-11-radio-readiness-sd-flash.json)
rapporte écriture, flush et relecture hashée du préfixe de la longueur de
l'image ; les octets restants de la carte ne sont pas effacés. L'éjection
initialement refusée par macOS est récupérée séparément, après vérification
du même média, sans réécriture. Le [retour natif suivant](https://github.com/mehdi7129/inkyOS/blob/b1860209b1bf5eb2a740e81dc5d49ff1c41afb60/docs/validation/2026-10-11-radio-readiness-enrollment-return.json)
est publié au commit `b1860209b1bf5eb2a740e81dc5d49ff1c41afb60`, dont la
[CI passe](https://github.com/mehdi7129/inkyOS/actions/runs/38135413005).
Studio relit les preuves publiques ; ces opérations sont rapportées par InkyOS.

- **SD source `2e435c9`, correctif `52ddfc1` présent** ; backend `c31b13a`
  inchangé. Le précédent état SD `07271cf` est historique.
- **35 contrôles natifs et 10 d'infrastructure réussis**, nettoyage vérifié
  indépendamment. Nouveau contexte privé exporté avec permissions et bindings
  vérifiés ; ancien contexte non réutilisé.
- Dérivé `e2image` acquis directement en lecture seule, hashes du flux et
  relecture VM concordants, sans clone intégral ni seconde lecture indépendante
  de la SD. Aucun replay ou code cible exécuté. Le marqueur ext4 clean et le
  PASS ne qualifient ni intégrité globale, exécution runtime ou arrêt physique.
  La dérivée reste privée et peut contenir des clés ; la protection contre
  toute écriture depuis l'insertion n'est pas établie.
- **Nouvelle capsule signée, installée et relue, puis SD éjectée**. Le prochain
  boot réseau n'a pas été effectué au relevé : import runtime, Wi-Fi/SSH,
  Bluetooth, app et écran restent non qualifiés. L'efficacité du correctif
  sur le Pi reste à observer dans cet essai, piloté par InkyOS.

### Réseau observé, préflight OS encore bloqué

La [preuve réseau authentifiée](https://github.com/mehdi7129/inkyOS/blob/28ccf9abe47dfec3e3d63ae43164562de9711602/docs/validation/2026-10-11-radio-readiness-network-observation.json)
est publiée au commit `28ccf9abe47dfec3e3d63ae43164562de9711602`, dont la
[CI passe](https://github.com/mehdi7129/inkyOS/actions/runs/38137459511).
Studio a relu la preuve ; les échanges avec le Pi sont rapportés par InkyOS,
sans connexion parallèle effectuée ici. Recette `2e435c9`, correctif `52ddfc1`
et backend `c31b13a` inchangés.

Deux STATUS authentifiés répondent PASS. Le premier préflight reste
`UNCONFIRMED` ; un préflight ultérieur vérifié répond **BLOCKED, 17/24 contrôles
réussis**. Sa sortie SSH 1 correspond au blocage distant, pas à un échec
d'authentification. Il observe directement NetworkManager gérant `wlan0`
connecté. Cela établit la connectivité lors de ces échanges, pas sa stabilité
durable ni la cause certaine du précédent échec.

| Contrôles faux | Portée |
|---|---|
| `bluetooth_unblocked`, `hci0_powered`, `utc_synchronized`, `system_packages_present` | Quatre conditions requises non satisfaites par le préflight ; ces booléens seuls n'identifient pas leur cause |
| `country_phy_matches`, `panel_inventory_supplied_and_valid`, `panel_runtime_evidence_verified` | Trois contrôles historiques remplacés par des gardes dédiées dans le contrat TEST ; ces gardes n'ont pas été évaluées et ne sont pas réputées réussies |

BlueZ tourne, le contrôle `firstboot_success` passe et l'UTC concorde avec une
référence indépendante récente. Ce dernier résultat ne prouve pas la
synchronisation NTP ; `firstboot_success` n'est pas une attestation indépendante
du runtime ou de l'arrêt. App et helper restent arrêtés et masqués, sans demande
d'activation. Aucun affichage, photo, QR/BLE ou appairage iOS validé.

L'[inspection OS distincte](https://github.com/mehdi7129/inkyOS/blob/28ccf9abe47dfec3e3d63ae43164562de9711602/docs/BOOT-NETWORK-DIAGNOSIS.md)
identifie trois corrections à préparer ensemble :

- Ajouter `i2c-tools`, absent de l'inventaire scellé ; les six autres paquets
  requis sont présents. Cette conclusion vient de l'inventaire, pas du seul
  booléen `system_packages_present`.
- Reprendre la préparation radio de l'installateur dans le lifecycle OS.
  Le [script c31b13a](https://github.com/mehdi7129/inky-studio/blob/c31b13afdc957425571810c46230eaaf52fa5d14/scripts/install-bluetooth.sh#L102-L104)
  débloque rfkill et met `hci0` sous tension ; le backend ne le fait pas.
  La copie offline des fichiers n'exécute pas ces actions au boot. L'état
  précis du contrôleur reste distinct d'une commande d'observation en échec.
- Fiabiliser la lecture `NTPSynchronized` : la requête actuelle interdit
  l'activation D-Bus de `timedated`, qui peut être inactif. Le faux négatif est
  reproduit en VM ; il ne prouve pas une désynchronisation du Pi. Le préflight
  et le contrôle d'heure précédant l'activation doivent être couverts ensemble.

Aucun correctif de ces trois points n'est déployé à ce relevé. Leur traitement
reste côté InkyOS, en conservant SSH si la préparation Bluetooth échoue.
L'app, son protocole et le payload restent inchangés ; PR Studio non fusionnée.

## Couple à conserver pour l'essai

| Élément | Référence et portée |
|---|---|
| Backend / payload SD | `c31b13afdc957425571810c46230eaaf52fa5d14`, candidat `0.5.0-rc.2`, branche `codex/display-hardware-qualification`, PR #20 encore draft |
| Helper réseau | Celui du même payload ; aucune migration v1 requise par le build iOS 9 |
| App iPhone | TestFlight **1.0.0 (9)**, source `181edb2f89034bb0c411b145c95fe303f112b460` |
| Distribution Apple | Revérifiée en lecture seule vers **11:17 UTC** : binaire **Validé**, groupe interne affecté avec un testeur. Le blocage de conformité des anciens builds n'empêche plus cet essai |
| Source de ce relevé | Branche de documentation issue de `966711f` ; elle n'ajoute aucun code applicatif depuis la source iOS ci-dessus |
| OS / SD | La session InkyOS annonce base système `0f2d222`, documentation d'alignement poussée à `688140d`, capsule Wi-Fi signée installée/relue, retour natif 35 + 10 PASS, app/helper masqués et SSH bloqué par `name_resolution_failed`. Cette SD TEST exige une admission et un état applicatif vierge par boot ; la reprise produit après reboot n'est pas qualifiée. Résultats rapportés par InkyOS, pas reproduits par Studio |

Au relevé du 9 octobre, le retour positif ne précisait pas le build installé.
La confirmation opérateur du 10 octobre ci-dessus établit le build 9 rapporté
installé ; elle ne qualifie pas le cadre. Relever la version à chaque nouvel essai.
Les détails d'archive et de CI sont dans [la livraison iOS](../ios/TESTFLIGHT-DELIVERY.md).

## Payload ARM64 exact

Conserver le candidat déjà associé à la SD. Le répertoire local vérifié est :

```text
~/Desktop/inky-studio/build/display-hardware-qualification-2026-10-03/build/offline-candidate-c31b13a
```

Les quatre fichiers ont été rehashés le 9 octobre. Le tar contient
`server/SOURCE_COMMIT = c31b13afdc957425571810c46230eaaf52fa5d14`.

| Fichier | SHA-256 |
|---|---|
| `inky-studio-manifest-v1.json` | `c4183e7304e3ff979450977b36e4a007b30016de68bb23ef121c7ca733cd26a1` |
| `inky-studio-v0.5.0-rc.2.tar.gz` | `c00b6f57026c9b6fae5560b9c457ce70adda15cff6d85255501199116b7c753b` |
| `inky-studio-python-arm64-cp313.zip` | `2892a4777109623589f3f506095d667e1637bc72f5c954b02b491eb2568b9718` |
| `requirements-arm64-cp313.lock` | `5e618486d108e306cf5ce0324bf20073a328683986d85723686dad17943e805c` |

Cible du manifeste : **ARM64, Debian Trixie, CPython 3.13**. Sa liste
`qualification.evidence` est vide : le manifeste ne certifie aucun essai matériel.
Ce bundle est un **candidat local**, pas une release GitHub rc.2 publiée.
InkyOS doit comparer les hashes du payload effectivement intégré ; cette lecture
des archives locales n'atteste pas des octets présents sur la SD.

## Contrats depuis c31b13a

Comparaison de `c31b13a`, source iOS `181edb2`, documentation `966711f`, branche
resource-limits `168db15` et first-boot `5b5ad6e` : helper et installateur Bluetooth
identiques. Hashes attendus :

```text
scripts/inky-network-helper.py
6e5c00862bff1d02c575b422f2d1e1112cd20f2c9e9141894557a698e2d5f431
scripts/install-bluetooth.sh
e0f301c97830860bcc1778579d7f4181370fb4cef8d64aeac4c226ab8aeafb69
```

Le contrat BLE v1 et les modules réseau/BlueZ/API sont inchangés. Le helper
garde ses opérations strictes `scan`, `begin`, `status`, `confirm`, `cancel`,
avec les hooks internes `health`, `cancel_pending`, `cancel_owner`. Aucune
opération heure/pays/reçu OS n'a été ajoutée à ce helper.

Le QR normal reste `{v,id,k,t}` ; les commandes restent
`{v,id,op,owner_id,owner_token,…}`. La confirmation passe par
`POST /api/provisioning/wifi/confirm` en HTTPS épinglé, authentifiée par le
propriétaire, puis par l'opération `confirm` du helper. Ce n'est pas une commande
BLE v1 ; une adresse DHCP seule n'est pas un succès.
Le contrôle iOS supplémentaire de `digitalSignature` accepte les certificats
générés par `c31b13a`, qui portent déjà cet usage.

Cette compatibilité est établie **par inspection des sources**, pas par un essai
physique du couple SD/iPhone. Les branches sont parallèles : le HEAD iOS et la
branche resource-limits ne contiennent pas le packaging offline et toutes les
protections d'arrêt/diagnostics matériels de `c31b13a`. Ne pas remplacer le
payload ARM64 par le SHA de compilation iOS. Une version intégrée demandera une
fusion revue, des tests combinés et un nouveau manifeste.

## Protocole après validation des prérequis OS

Le dernier relevé `28ccf9a` observe Wi-Fi connecté et SSH authentifié, mais le
préflight reste bloqué. InkyOS doit corriger les trois écarts système décrits
ci-dessus et valider les gardes TEST requises avant l'activation de l'app.

1. InkyOS identifie le boot réel, l'IP/SSH, le panneau exact, l'état système,
   le pays radio, l'heure et le payload. Les services restent masqués pendant
   ce préflight ; leur activation appartient au banc piloté par InkyOS.
2. Avec un LAN déjà établi par le parcours OS actuel, vérifier l'accueil
   physique et la disponibilité locale du mot de passe **de l'app**.
3. Sur le même LAN, connecter l'iPhone et vérifier le diagnostic authentifié
   `/api/display/status` ; `/api/health` ne prouve pas l'état du panneau. Envoyer
   ensuite une photo, observer réellement le rafraîchissement et le rendu e-ink.
4. Depuis une session authentifiée, demander le QR dans Réglages, le scanner
   sur le cadre et associer l'iPhone par BLE.
5. **Reporter les changements Wi-Fi tant qu'un chemin de récupération n'est pas
   éprouvé.** Sur cette SD TEST, le contrôle réseau est lié au profil signé et
   ce secours n'est pas encore établi. Le futur banc dédié testera mauvais mot
   de passe/rollback, puis réseau WPA2 personnel 2,4 GHz et confirmation HTTPS.
6. Terminer cet essai par le drain et l'arrêt effectif `inactive/dead`.
   Reboot/coupure et reprise produit avec ownership conservé relèvent d'un banc
   distinct : la règle d'admission de cette SD TEST ne les qualifie pas.

Priorité convenue : **réseau → préflight → accueil → photo → QR/BLE → drain**.
Cette liste ne transforme pas la capsule Wi-Fi TEST en parcours produit final.

L'association BLE ne crée pas à elle seule une session photo : l'app reprend
le mot de passe déverrouillé par Face ID s'il existe, sinon demande le mot de
passe habituel. L'iPhone doit pouvoir joindre le cadre sur le réseau utilisé.

Le profil `ac073-800x480` ne s'applique qu'au panneau correspondant : le modèle,
l'EEPROM et le driver doivent concorder. Le démarrage hardware peut déjà
rafraîchir l'accueil. Le [contrat matériel de c31b13a](https://github.com/mehdi7129/inky-studio/blob/c31b13afdc957425571810c46230eaaf52fa5d14/docs/inkyos/HARDWARE-CANDIDATE.md)
précise le tuple EEPROM, les erreurs persistantes et les critères de drain.
Préserver le contrat d'arrêt du candidat :

```ini
KillSignal=SIGTERM
KillMode=mixed
TimeoutStopSec=infinity
SendSIGKILL=no
```

Pas de kill forcé ni de coupure pendant un rafraîchissement/drain en cours.
Les essais de coupure contrôlée nécessitent leur protocole dédié et une SD de
test ; ils ne sont pas implicitement validés par cette liste.

## Cible utilisateur : premier allumage sans LAN

Cible commune proposée : **allumer → QR physique → app et permissions
contextuelles → claim authentifié → heure transmise sans saisie → pays confirmé
→ Wi-Fi → première photo**. Aucun Terminal, accès à la box, login LAN préalable
ni préparation Wi-Fi sur Mac pour l'utilisateur final. Ce parcours n'est pas
encore celui du build 9.

| Domaine | Existant | Intégration manquante pour cette cible |
|---|---|---|
| iOS | Types de confiance/bootstrap TLS compilés et testés isolément | Entrée avant connexion LAN, QR usine distinct, canal bootstrap, claim, heure fournie par l'iPhone, pays confirmé, progression/reprise et bascule vers TLS strict. Le parcours actuel construit toujours le canal TLS normal |
| Backend | Ledger factory, identité préparée, réparation de certificat et `FirstBootCoordinator` prototypes | Branchement au lifecycle, QR usine physique, service GATT/dispatcher bootstrap, validation et consommation du reçu OS, transitions persistantes et fermeture définitive de l'autorité factory |
| OS / helper | Prérequis d'image et adaptateurs étudiés séparément | IPC restreint et reçu root effectivement validé, application de l'heure/pays, barrière radio/NetworkManager, recovery et unités revues de bout en bout |
| Intégration | Primitives et fixtures partielles | Séquence claim/heure/pays/réseau, réparation de certificat et retour à TLS strict sans cercle de dépendance, accès photo initial et qualification des interruptions |

`FirstBootCoordinator` n'est pas importé au runtime. `BootstrapFrameTrust` est
compilé dans l'app, mais n'est pas appelé depuis le parcours courant. Les types
`InitializationReceipt` et `ClockResult` sont des assertions locales ; ils ne
prouvent ni privilège système ni heure UTC. Il n'existe pas actuellement de
flag magique à activer pour rendre ce parcours complet.

Invariants à conserver et à tester : un échec Wi-Fi se corrige via le canal BLE
autorisé ; reboot, coupure ou base applicative perdue ne rouvrent jamais
l'autorité usine. Le reçu OS consommé, conservé hors des données applicatives,
et le ledger applicatif doivent être réconciliés. Perte ou incohérence des données
après consommation ferme l'accès et exige la reprise explicitement prévue,
sans réinitialisation usine implicite. Cette reprise doit être bornée et refuser
le replay. La confirmation HTTPS reste distincte de la connexion réseau. Le
contrat détaillé doit figer ces transitions avant tout branchement dans l'image.

Références : [premier boot](FIRST-BOOT-CONTRACT.md),
[état factory](FACTORY-STATE.md), [coordination](FIRST-BOOT-COORDINATOR.md),
[décision TLS](BOOTSTRAP-TLS-DECISION.md),
[prototype TLS](BOOTSTRAP-TLS-PROTOTYPE.md),
[identité](BOOTSTRAP-IDENTITY.md).

## Responsabilités et preuves

Studio possède iOS/backend/protocoles/helpers ; InkyOS possède image, OS, SD et
banc matériel. Aucun installer, service, identité, profil Wi-Fi ou contenu SD
n'a été modifié par cette vérification. Aucun secret ni QR réel n'est échangé.

Les checks CI de la [PR #20](https://github.com/mehdi7129/inky-studio/pull/20)
sont verts au relevé (7 checks), et ceux du build 9 sont documentés séparément.
Les 35 + 10 checks rapportés par InkyOS, les hashes et la disponibilité TestFlight
ne qualifient pas le QR affiché, le BLE iPhone, la bascule/rollback Wi-Fi,
le rafraîchissement e-ink ou la résistance aux coupures. Ces preuves matérielles
restent à recueillir sur le couple exact ci-dessus.
