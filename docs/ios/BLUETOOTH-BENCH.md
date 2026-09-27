# Banc Bluetooth Mac ↔ Raspberry — C1

Date : 27 septembre 2026. **Prototype de diagnostic temporaire**, indépendant de
l’app iPhone et du serveur Inky Studio. Il ne configure aucun réseau Wi-Fi.

## Matériel et accès vérifiés

Diagnostic SSH en lecture avec l’utilisateur `pi`, authentification par clé,
`BatchMode=yes`, `ConnectTimeout=5` et `StrictHostKeyChecking=yes` :

| Élément | Résultat |
|---|---|
| Raspberry | Pi Zero 2 W Rev 1.0 |
| OS | Debian GNU/Linux 13 Trixie |
| Kernel | `6.12.75+rpt-rpi-v8` |
| BlueZ | `5.82` |
| NetworkManager | `1.52.1` |
| Services | `bluetooth`, `NetworkManager`, `inky-studio` actifs |
| Contrôleur | LE, advertising et Secure Connections annoncés |
| BlueZ D-Bus | `GattManager1`, `LEAdvertisingManager1`, cinq instances advertising possibles |
| NetworkManager D-Bus | CheckpointCreate, CheckpointRollback, CheckpointDestroy, CheckpointAdjustRollbackTimeout présents |
| État initial | Bluetooth Powered=false, rfkill soft=1 / hard=0 ; Wi-Fi soft=0 / hard=0 |
| Python Pi | 3.13.5 ; `dbus-python` et PyGObject déjà installés |

Le compte `pi` peut écrire `/dev/rfkill`. L’activation Bluetooth temporaire est
possible sans sudo ; une réponse D-Bus `Busy` immédiatement après le déblocage
peut être transitoire. Le bench gère cette attente bornée.

La présence de Secure Connections dans les capacités **ne prouve pas** que le
prototype établit une session appairée/authentifiée. Il n’en demande pas.

## Ce que fait le prototype

Sources : [`scripts/bt-bench/`](../../scripts/bt-bench/).

- Serveur Python BlueZ dans un répertoire `/tmp` du Pi, sans installation globale,
  sans unité systemd et sans accès à l’API, aux photos ou aux identifiants Inky.
- Service UUID `713a0001-8890-4cc9-a2bf-26f32c43db22`, nom public générique
  `Inky Bench`, sans nom de propriétaire, SSID, adresse IP ou identifiant du cadre.
- Trois caractéristiques : version en lecture (`...0002`), entrée en écriture
  avec réponse (`...0003`), sortie en lecture/notification (`...0004`).
- App macOS Swift CoreBluetooth, bundle `fr.mehdiguiard.inkystudio.blebench`,
  signée ad hoc, permission `NSBluetoothAlwaysUsageDescription`, scan limité
  au service du bench et durée totale limitée à 90 secondes.
- Données exclusivement synthétiques : petit challenge aléatoire, motif de
  600 octets, texte de diagnostic après reconnexion. Les logs indiquent les
  longueurs et résultats, jamais le contenu ou l’adresse matérielle des pairs.
- Trois cas : echo initial ; fragmentation avec répétition du premier fragment ;
  déconnexion volontaire puis reconnexion, echo et relecture du dernier fragment.

Le challenge/echo vérifie seulement l’intégrité du transport dans ce test.
**Il n’authentifie ni le téléphone, ni le cadre, ni un propriétaire.** Un tiers
à proximité peut reproduire le service ou écrire des données de bench. Aucun
mot de passe, token d’adoption ou secret Wi-Fi ne doit être envoyé ici. Ce code
n’est pas un protocole de provisioning prêt à livrer.

## Encadrement du protocole

Header de huit octets : `IK`, version `1`, flags `0`, transaction uint16 big
endian, index uint8, nombre de fragments uint8. Payload total limité à 768 octets
et 64 fragments. Les tests utilisent des frames de 20 octets, donc 12 octets utiles,
pour exercer une fragmentation réelle même si la MTU négociée est supérieure.

Le serveur refuse version/flags/longueurs invalides, fragments manquants,
répétitions contradictoires et payloads trop grands. Une répétition identique
est sans effet. Une transaction partielle expire après 15 secondes. Ces limites
ne remplacent pas l’authentification, la limitation d’accès ou le protocole de
sécurité nécessaires à la configuration Wi-Fi future.

## Reproduire

Le Pi doit avoir BlueZ, `python3-dbus` et `python3-gi`. Vérifier leur présence
avant tout ajout de dépendance. Le matériel testé possède un seul contrôleur
Bluetooth `hci0` ; qualifier la sélection du contrôleur avant usage multi-adaptateur.

Depuis la racine du dépôt :

```bash
python3 -m unittest discover -s scripts/bt-bench -p 'test_*.py' -v
bash scripts/bt-bench/build-mac.sh
```

Créer un dossier temporaire sur **la cible déjà vérifiée**, copier uniquement
`protocol.py` et `pi-gatt-bench.py`, puis lancer :

```bash
python3 -u /tmp/inky-ble-bench.XXXXXX/pi-gatt-bench.py --enable-radio --duration 240
```

`--enable-radio` mémorise Powered/rfkill, débloque et active seulement le Bluetooth,
puis restaure l’état précédent en sortie normale, SIGINT ou SIGTERM. Sans cette
option, le programme exige une radio déjà allumée et ne la modifie pas. Durée
maximale admise : 600 secondes. Ne pas fermer le processus par SIGKILL : dans ce
cas, ou après perte de courant, vérifier/restaurer explicitement l’état radio.

Après le message `ready`, lancer le client :

```bash
open -n /tmp/inky-ble-bench-build/InkyBLEBench.app --args --log /tmp/inky-ble-bench-mac.jsonl
```

Autoriser le Bluetooth pour cette app de bench si macOS le demande. Attendre un
événement terminal `PASS` ou `FAIL` dans le JSONL ; le lancement de l’app ou le
message serveur `ready` ne constituent pas un test BLE réussi. Si la permission
prend plus de 90 secondes, relancer le client et un serveur temporaire encore actif.

Arrêter le serveur après le test, contrôler `Powered`, rfkill et l’absence
d’instance advertising, puis supprimer uniquement le répertoire temporaire créé.
Vérifier que le serveur Inky et son accès HTTP sont toujours opérationnels.

## Résultats de cette exécution

- Compilation macOS et signature ad hoc : **PASS**.
- Tests de framing : **4 PASS** (600 octets/50 fragments, duplicates, erreurs,
  expiration).
- Registration GATT et advertising réels sur le Pi : **PASS**, événement `ready`.
- Découverte ciblée Mac → Pi, connexion et lecture `INKY-BENCH/1` : **PASS**.
- Echo de challenge synthétique **36 octets** : **PASS**, 3 écritures acquittées,
  3 notifications, **391 ms** entre début d’écriture et reconstitution.
- Echo fragmenté **600 octets** : **PASS**, 51 écritures acquittées dont une
  répétition identique, 50 notifications, **3 957 ms**. La longueur maximale
  d’écriture avec réponse annoncée par CoreBluetooth était 512 octets ; les frames
  du test ont volontairement été limitées à 20 octets.
- Déconnexion volontaire, nouvelle découverte/connexion, lecture de version,
  echo de **25 octets** : **PASS**, 3 écritures/notifications, **211 ms**.
- Relecture de la caractéristique de sortie après les notifications : **PASS**,
  valeur identique au dernier fragment reçu.
- Arrêt SIGTERM du serveur : **PASS**, événement `stopped` puis SSH exit 0.
- Contrôle **11:10:53 UTC** : Bluetooth Powered=false et softblock=1 restaurés,
  aucun advertising actif, Wi-Fi soft=0/hard=0, service Inky actif et
  `/api/health` répondant `ok`, version `0.4.2`. Dossier temporaire Pi supprimé.

Preuves sans données personnelles : [log Mac brut](../../scripts/bt-bench/evidence/2026-09-27-mac.jsonl)
et [contrôle après nettoyage](../../scripts/bt-bench/evidence/2026-09-27-postflight.json).
Les durées mesurent ces échanges précis à proximité, avec pacing volontaire des
notifications ; elles ne sont pas une mesure du débit radio maximal. Ce succès
ne valide pas le protocole de configuration Wi-Fi ou sa sécurité.

## Limites et prochaine étape

Le bench ne valide pas l’association sécurisée, l’identité persistante du cadre,
la récupération d’accès, une connexion iPhone, la coexistence prolongée Wi-Fi/BLE,
les coupures électriques ou une bascule réseau. Les APIs Checkpoint sont seulement
inspectées ; aucune n’a été appelée.

Avant C2 : protocole d’adoption authentifié éprouvé, stockage des clés, autorisation
des opérations, transport HTTPS lié à l’identité du cadre, helper NetworkManager
limité et tests de rollback sur un réseau de test. Aucune commande arbitraire,
aucune API de changement Wi-Fi et aucune cryptographie maison dans ce prototype.

## Références officielles consultées

- [BlueZ — GATT Characteristic API](https://github.com/bluez/bluez/blob/master/doc/org.bluez.GattCharacteristic.rst)
- [BlueZ — GATT Manager](https://github.com/bluez/bluez/blob/master/doc/org.bluez.GattManager.rst)
- [BlueZ — LE Advertisement](https://github.com/bluez/bluez/blob/master/doc/org.bluez.LEAdvertisement.rst)
- [Apple — CBPeripheral](https://developer.apple.com/documentation/corebluetooth/cbperipheral)
- [Apple — scanForPeripherals](https://developer.apple.com/documentation/corebluetooth/cbcentralmanager/scanforperipherals(withservices:options:))
- [Apple — Bluetooth usage description](https://developer.apple.com/documentation/bundleresources/information-property-list/nsbluetoothalwaysusagedescription)
