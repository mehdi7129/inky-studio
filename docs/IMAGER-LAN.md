# Inky Imager — démarrage PHOTO sur LAN préconfiguré

Ce mode démarre directement le service PHOTO sur le réseau fourni par Imager. Il ne lance ni BLE, ni SoftAP, ni coordination factory. La build iOS15 existante sait lire son invitation PHOTO ; aucune nouvelle version iOS n'est nécessaire pour ce périmètre.

## Contrat OS

Commande du service, sous l'utilisateur `inky` UID1000 :

```text
/usr/lib/inky-studio/server/.venv/bin/python3 -I -B -m inky_web.imager_lan
```

L'OS configure NetworkManager depuis les paramètres du flash, fixe son hostname unique et persistant, publie ce nom avec Avahi et fournit une horloge normale avant de démarrer l'application. Le backend ne lit jamais le SSID ni le mot de passe Wi-Fi.

Variables :

```text
INKY_STUDIO_DATA_DIR=/var/lib/inky-studio
INKY_STUDIO_DISPLAY_MODE=hardware
INKY_STUDIO_DISPLAY_PROFILE=ac073-800x480-timed-wait
```

Le profil écran reprend celui déjà qualifié par InkyOS. Aucun changement n'est apporté aux modules display/BUSY/confirmation/SPI. L'OS conserve les permissions matérielles normales nécessaires à l'utilisateur du service.

`INKY_STUDIO_PHOTO_ACCESS_URL` peut donner une origine HTTPS canonique au port8443. Si elle est absente, le backend utilise `https://<socket.gethostname()>.local:8443`, sans doubler un suffixe `.local` existant. Ce nom réseau ne se déduit jamais du UUID du cadre. Une valeur explicitement vide ou non canonique est refusée.

L'authentification doit rester activée ; `INKY_STUDIO_BLUETOOTH` doit être absent ou valoir0. Aucun `INKY_STUDIO_FACTORY_REQUIRED`, signal writer factory, marqueur ou trace factory ne doit exister. La sélection et le writer guard sont conservés ; le mode LAN refuse une ancienne image factory au lieu de la convertir.

Préparer `/var/lib/inky-studio` propriétaire UID/GID du service, mode0700. L'application crée ses données : `credentials.json`, `inky_studio.db`, `photos/`, identité et fichiers TLS sous `provisioning/`, ainsi que `photo-access/access.sqlite3`. Les clés et credentials sont privés. L'image générique ne contient aucune identité ni credential personnalisé.

## QR et accès iOS15

Le seul listener est HTTPS8443 ; aucun HTTP8000 n'est ouvert. Le QR n'est affiché qu'après l'ouverture du listener. Le Bento clair affiche un grand QR et des instructions, sans adresse IP, mot de passe ou SSID visibles.

Enveloppe JSON fermée,1024octets au plus :

```json
{"v":1,"p":"invite","id":"11111111-2222-4333-8444-555555555555","k":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","url":"https://inky-example.local:8443","i":"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee","t":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}
```

Cet exemple est entièrement synthétique. `id` est le UUID réel du cadre, `k` son pin SPKI SHA256 et `i/t` l'invitation à usage unique. Le TLS normal conserve la signature, les dates et le SAN cryptographique `frame-<UUID>.inky.invalid`. Aucun profil bootstrap ou assouplissement de confiance n'est utilisé.

L'app protège ses device_id/device_token/request_id avant le POST HTTPS `/api/auth/invitations/claim`. Le serveur donne un rôle PHOTO `media`, sans créer de propriétaire fictif. L'app conserve ce credential dans le Keychain ; après fermeture ou redémarrage du cadre, FaceID/code de l'iPhone puis `/api/auth/device-session` rétablissent l'accès sans nouveau QR.

L'issuer initial est local au mode LAN, opt-in et distinct des devices. Il n'est disponible que si aucun appareil n'a déjà été associé dans l'epoch courant. Aucune API HTTP ne permet de le créer ou de le renouveler. Le même QR est renouvelé avant son échéance300s tant qu'il n'est pas réclamé, sans repeindre l'écran ni faire grossir le registre à chaque tick. Un claim arrête le renouvellement ; une expiration ou une horloge invalide n'autorise pas une nouvelle invitation implicite.

Au reboot sans association, l'invitation précédente est invalidée et un QR neuf est affiché. Après association, les credentials survivent. Une photo existante n'est jamais remplacée par le welcome. Les opérations écran restent sérialisées et drainées lors de l'arrêt.

## Périmètre et qualification

L'accès media permet envoi de photos, file, affichage et planning. Il ne permet pas de générer un nouveau QR de partage, d'administrer le Wi-Fi ou de modifier la saturation. Il ne donne aucun droit owner/BLE/factory. Un autre téléphone après perte du premier accès exige une procédure de réinitialisation hors de ce v0.

Les contrôles automatisés couvrent les stores, le vrai HTTPS, les credentials, les appels photo et la reprise après reboot avec écran inerte. Le QR peut être décodé depuis ses pixels synthétiques. Ils ne qualifient ni le Wi-Fi du Pi, ni FaceID sur l'iPhone, ni les pixels physiques. L'installation OS et l'essai matériel appartiennent à InkyOS.
