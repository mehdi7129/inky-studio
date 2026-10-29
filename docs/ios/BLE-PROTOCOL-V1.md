# Bluetooth Wi-Fi — contrat d’implémentation v1

Travail en cours sur `codex/bluetooth-wifi-setup`. Ce document décrit le code en
cours, **pas une qualification matérielle ni une fonctionnalité déjà livrée**.
Le 27 septembre 2026, Mehdi a confirmé le changement du mot de passe existant,
la reconnexion avec le nouveau et le rejet d’un mot de passe erroné sur iPhone.

## Confiance

QR non URL : JSON UTF-8 <=512 octets, exactement `v`, `id`, `k`, `t`.
`v=1`, `id` UUID, `k` SHA256 du DER SubjectPublicKeyInfo (64 hex minuscules),
`t` aléa 32 octets (64 hex minuscules), secret d’adoption valable 10 minutes.
Une nouvelle fenêtre exige une action authentifiée ; un reboot invalide la fenêtre.
Le jeton est consommé atomiquement avec l’adoption. Aucun secret dans les logs.

Le cadre conserve une clé EC P-256 et un certificat auto-signé propre au cadre,
SAN `frame-<uuid>.inky.invalid`, CA:TRUE + serverAuth. La policy SSL Apple rejette
un certificat présenté à validité longue, même avec une ancre privée épinglée
(mesuré avec Security sur macOS 27). Le certificat a donc une validité de 396 jours,
avec renouvellement à moins de 90 jours **sans changer la clé ni son empreinte**.
Une horloge du Pi plausible est nécessaire pour émettre/renouveler. Hors ligne,
le certificat déjà créé reste utilisable jusqu’à son échéance ; une horloge RTC
en arrière ne déclenche pas de réémission. Le client vérifie dates, nom, signature
et usage. Le certificat public
reçu par BLE est comparé à l’empreinte **du QR** avant d’en faire son unique ancre.
La même clé est présentée en HTTPS. Une identité persistée illisible bloque le
service ; elle ne rouvre pas l’adoption. Pas de repli HTTP pour un cadre adopté.

Le téléphone prépare et sauvegarde son token propriétaire aléatoire de 32 octets
dans un service Keychain distinct avant `claim`. Ce token est indépendant du
mot de passe de l’app, de Face ID, de SSH et du réseau. Le serveur ne stocke que
son hash. Toute commande authentifie à nouveau ce token et vérifie sa révocation.

La rotation de mot de passe utilise un identifiant de génération dérivé de son
salt/hash. Avant la mutation atomique du mot de passe, seule l’autorisation du
téléphone appelant est préparée pour la nouvelle génération. Les autres restent
liées à l’ancienne. Une interruption entre les deux écritures ne maintient donc
jamais un ancien propriétaire après la rotation. Sans appelant identifié, tous
les propriétaires sont révoqués. L’API legacy reste compatible.

## GATT

Service `713b0001-8890-4cc9-a2bf-26f32c43db22`.

| Caractéristique | UUID suffixe | Usage |
|---|---|---|
| Identity | `0002` | read : JSON `{v:1,id:<uuid>,cert_length:<bytes>}` public, non fiable avant comparaison QR |
| Stream | `0003` | write-with-response puis read ; TLS 1.3 uniquement |
| Certificate 0 | `0004` | read : premiers 480 octets du certificat DER |
| Certificate 1 | `0005` | read : reste du certificat DER (<=480 octets) |

Un attribut ATT est borné à 512 octets, y compris avec ReadBlob. Le certificat
est donc scindé explicitement, puis reconstruit et contrôlé sur l’iPhone avant
TLS. Les deux parties doivent mesurer exactement `cert_length` (1..960).
Le JSON+base64 dans un seul attribut a été rejeté en revue (757 octets mesurés).

Pas de notifications partagées. L’état est associé au chemin device fourni par
BlueZ. Deux connexions maximum, buffers TLS 64 KiB, commande JSON 16 KiB.
La déconnexion détruit l’état. La reconnexion recommence TLS ; aucun ticket/0-RTT.

RESET : octet `0` puis nonce client aléatoire de 16 octets. Le read doit rendre
exactement cet écho. Retransmettre le même RESET avant DATA est idempotent.

DATA write : `1 | sequence:uint16BE | acknowledgement:uint16BE | TLS bytes`.
La séquence commence à 1, l’ACK commence à 0. DATA read :
`1 | acknowledgedClient:uint16BE | serverSequence:uint16BE | TLS bytes`.
Le serveur utilise la même séquence pour sa réponse, même si le payload est vide.
Un write ne suit le précédent qu’après son read. Les polls ont un payload vide.
Un retry de write doit être strictement identique. Les reads sont idempotents.
Séquence omise, doublon modifié, débordement ou 65535 : fermeture.
Chaque valeur tient en `min(MTU-3,244)` octets ; le client utilise son maximum
write-with-response et sans réponse, plafonné à 244, afin d’éviter les long writes.
Aucun offset/reliable write accepté sur Stream ; les lectures du certificat
acceptent ReadBlob pour une petite MTU.

CLOSE : octet `2`. Expiration après 180 s sans progrès et handshake limité à 45 s.
Le nonce RESET confirme une nouvelle session de transport ; la preuve d’identité
reste exclusivement TLS et l’empreinte physique.

## Commandes dans TLS

Chaque message : longueur uint32BE puis JSON UTF-8 (1..16384 octets).
Un seul appel en vol. Champs communs : `v:1`, `id:<request UUID>`, `op:<operation>`.
Après adoption : `owner_id:<UUID>` et `owner_token:<64 hex minuscules>`.
Réponse : `v:1,id:<same>,ok:true,result:{...}` ou `ok:false,error:<stable code>`.
Erreurs sans écho de payload. Secrets conservés seulement le temps nécessaire.

Opérations implémentées : `claim`, `status`, `wifi.scan`, `wifi.begin`, `wifi.status`,
`wifi.cancel`, `owner.revoke`. La confirmation Wi-Fi n’est acceptée qu’en HTTPS
épinglé avec le propriétaire de la transaction. Un simple DHCP ne valide rien.

La bascule Wi-Fi passe par un helper séparé à interface étroite, un checkpoint
limité à wlan0 avec timeout, un profil temporaire et un journal sans secrets.
Un crash/redémarrage doit conserver l’ancien profil et annuler l’essai incomplet.
Les détails de finalisation, l’installation et les limites de qualification sont
suivis dans [BLUETOOTH-INTEGRATION.md](BLUETOOTH-INTEGRATION.md).
