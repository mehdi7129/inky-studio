# Prototype SoftAP France / 2,4 GHz

Ce transport opt-in remplace BLE pour le parcours initial du prototype. Le mode BLE existant reste le comportement par défaut. L'OS possède l'AP, son admission pays FR, DHCP et son cycle de vie ; Studio possède le protocole TLS, l'adoption et les transactions réseau.

## Intégration OS

Injecter le même client system-setup attesté dans le contrôleur et le runtime :

```python
from inky_web.provisioning.softap import SoftAPController

runtime = FactoryContinuationRuntime(
    result, verify_epoch, display, directory,
    system_setup=system_setup, network=network,
    softap=SoftAPController(system_setup),
)
```

Les opérations `setup.ap.start/status/stop` utilisent le socket system-setup existant, l'enveloppe v/id/op/args et le Workflow consommé. Elles n'ajoutent aucun service privilégié Studio. Le schéma AP de référence du prototype est `101d169b3eb5a1ecbfd9345e874dbf686095b304efe1db678963ceac16e81a06`. Les tests contiennent sa projection AP fermée.

Un AP dure au maximum 1 800 secondes BOOTTIME, sans renouvellement implicite. Son SSID est `Inky-` suivi de huit caractères hexadécimaux minuscules et sa clé WPA2 comporte 24 caractères hexadécimaux minuscules. L'arrêt n'interrompt jamais une station. Le backend draine ses connexions et opérations ; l'OS arrête l'AP à l'expiration, à la désadmission de Main et à l'arrêt de son service.

## QR et transport

Le QR v3 JSON fermé contient exactement `v,p,id,k,t,s,w,u` : v=3, p=softap, UUID du cadre, pin SPKI, token claim, SSID, passphrase AP et `tcp://192.168.4.1:9443`. Taille maximale 1 024 octets. Le QR v2 conserve sa signification.

Chaque connexion TCP commence par une longueur uint32 big endian et un manifeste JSON fermé `{v:1,p:"bootstrap"|"normal",id:<UUID>,c:<DER base64>}` limité à 4 096 octets, dont un certificat DER de 2 048 octets au plus. Après contrôle du UUID et du pin, le client établit TLS 1.3. Le profil bootstrap impose ALPN `inky-bootstrap/1` et conserve ses seules règles de date spécifiques. Le profil normal reste strict.

Les commandes existantes sont ensuite encadrées par une longueur uint32BE, au maximum 16 384 octets. Les mécanismes GATT ne s'appliquent pas au TCP. Le serveur factory écoute uniquement l'adresse AP ; le serveur normal peut reprendre sur le LAN au port 9443. La confirmation réseau et les photos utilisent toujours HTTPS au port 8443.

## Adoption, reprise et réseau

Le parcours est QR → AP → TLS bootstrap → claim → setup heure/pays FR → identité normale → TLS normal → Wi-Fi prepare → activate → arrêt AP → station → confirmation HTTPS sur le LAN → continuation et photos.

`wifi.prepare` persiste la même intention/transaction avant sa réponse. Le helper stocke une phase interne `staged` distincte de sa phase historique `prepared`. Les credentials domestiques restent en RAM pendant 30 secondes, sans mutation NetworkManager. L'iPhone reçoit cet ACK avant d'envoyer `wifi.activate`, puis le backend revalide owner/epoch, arrête l'AP et active le checkpoint réseau de 180 secondes. `begin` BLE conserve son comportement historique.

Un ACK perdu se récupère sous les mêmes owner et transaction ID. Aucun nouveau claim ou replay de mutation n'est implicite. Le QR de reprise ADOPTED n'ouvre aucune fenêtre de claim ; le credential owner déjà enregistré reste indispensable.

Le candidat `expected_https_origin` vient du hostname réellement observé par OS/Avahi. Il ne se déduit pas du UUID et n'atteste pas que le LAN est accessible. Le nom cryptographique TLS reste `frame-<UUID>.inky.invalid`. La confirmation exige la station cible et son checkpoint ; les photos et `setup.complete` exigent l'état réseau confirmé.

Après échec/cancel/timeout, le backend attend pendant au plus 30 secondes une observation `settled=true`, avec revalidation owner/epoch avant tout retour AP. Le helper vérifie l'absence de checkpoint NM et la fin du nettoyage ; un simple état terminal ne suffit pas. Une situation incertaine reste fermée. Un cadre déjà connecté et complètement initialisé ne relance pas l'AP et ne réécrit pas sa photo au démarrage.

## Validation et limites

Les tests ciblés couvrent le helper et ses précédents parcours, le vrai TCP/TLS et SQLite, les reprises, l'attente de rollback et les barrières de livraison des réponses. La radio, NetworkManager et le writer OS sont simulés côté Studio. Le harness `server/tests/softap_interop_server.py` est réservé aux tests localhost Swift/Python.

Le consentement Hotspot iOS, DHCP, la bascule AP/STA et le parcours iPhone/Pi doivent encore être qualifiés sur le matériel. Ce document ne constitue pas une qualification physique.
