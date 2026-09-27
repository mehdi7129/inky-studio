# Validation C2 — 27 septembre 2026

Implémentation candidate, non distribuée dans TestFlight et non déployée sur le
service photo du cadre. Les réseaux, identités, photos et mots de passe des tests
ci-dessous sont synthétiques.

| Vérification | Résultat |
|---|---|
| Backend Python 3.11 et 3.13 | 329 tests PASS sur chaque version ; Ruff PASS |
| Migration mot de passe via HTTP/WS réel | PASS, ancien mot de passe/session rejetés après rotation et redémarrage |
| Client TLS Mbed TLS ↔ Python OpenSSL | 10 tests PASS, dont lecteur retardé et backpressure |
| Canal Swift ↔ transport Python GATT | 13 tests PASS, MTU 23/247, tailles asymétriques, doublons et annulation |
| iOS 18.5, iPhone 16 Pro Simulator | 81 unit tests PASS ; 11 UI tests PASS, 1 Face ID ignoré car fixture non biométrique |
| iOS 27, iPhone 18 Pro Simulator | 81 unit tests + 2 parcours Bluetooth UI PASS sur le correctif radio final |
| iPhone Release arm64 | Build PASS ; notices tierces présentes et identiques au fichier source |
| Dépendance Apple | Rebuild propre des cinq slices depuis archive officielle/hash épinglé PASS |
| HTTPS URLSession macOS, code app réel | 52 contrôles PASS, JSON/cookie/photo/WSS/confirmation, faux certificats sans données applicatives |
| Deux listeners backend réels | HTTP/HTTPS, cookie commun, TLS 1.3 seul, SIGTERM, échecs de bind et lifespan unique PASS |
| BLE Mac ↔ Pi Zero 2 W | Deux echo 600 octets, mauvaise empreinte refusée avant write, nouvelle session TLS après reconnexion : PASS |
| Réseau du Raspberry | Aucun changement ; radio restaurée off/soft-blocked, service photo actif |

L’avertissement Python restant vient de la transition `httpx` / `httpx2` de
Starlette, sans échec de test. Le build iPhone est compilé sans signature pour
qualification ; aucun upload ou numéro de build TestFlight nouveau n’est annoncé.

## Bugs trouvés et corrigés pendant la qualification

- Certificat trop grand pour un seul attribut ATT : représentation séparée en
  métadonnées et deux caractéristiques DER bornées.
- La MTU initiale CoreBluetooth était encore de 20 octets puis devenait 182 :
  lecture de la limite actuelle et borne de réponse indépendante. Reproduit puis
  corrigé sur le matériel, pas seulement supposé.
- Arrêt des listeners : un échec de bind pouvait interrompre le cleanup et une
  exception tardive pouvait être avalée. Les quatre scénarios passent sur sockets.
- Renouvellement du certificat : un échec de redémarrage BlueZ doit rester
  retentable, même après persistance du nouveau certificat.
- Annulation pendant un refresh physique : attendre la fin du worker avant de
  rendre le verrou d’écran ; pas de second écrivain SPI.
- Une transaction en cours de finalisation devait être annulée avant une
  révocation ou un reset local du mot de passe, y compris après arrêt interrompu.
- JSON ambigu/dupliqué, non fini, trop profond ou dans un autre encodage rejeté.
- Deux tests de pipes échouaient dès un poll vide d’une seconde malgré un délai
  global plus long ; le délai est désormais réellement respecté.
- Le test de doublon altéré remplaçait un octet aléatoire par une constante :
  mutation parfois identique. Un XOR garantit maintenant un vrai changement.

## Preuves partageables

[BLE réel et cleanup](ble-radio.json) — confiance injectée par SSH connu pour
le banc uniquement, **pas une adoption QR physique validée**.

[HTTPS et empreintes des sources testées](https-wire.json) — vrai URLSession
macOS, pas une qualification ATS/iPhone matériel.

Captures iOS 18.5 : [réseaux clair](bluetooth-networks-light.png),
[sombre](bluetooth-networks-dark.png), [saisie](bluetooth-credentials-light.png),
[confirmation](bluetooth-confirmation-light.png), [annulation](bluetooth-rollback-light.png).
Captures iOS 27 : [clair](bluetooth-networks-light-ios27.png),
[sombre](bluetooth-networks-dark-ios27.png). Revue visuelle : titres et actions
visibles, cartes arrondies, aucune bande vide supérieure dans le contenu.

## Critères restant ouverts avant livraison

Installation du helper et contrôle de ses permissions sur le vrai Pi ; scan et
adoption depuis un iPhone ; changement vers le partage 2,4 GHz choisi par Mehdi ;
mauvais secret, annulation, coupure de l’app/Pi, rollback et commit durables sur
NetworkManager réel. Mettre à jour le numéro de build et le questionnaire export
avant la prochaine distribution TestFlight. La PR reste draft tant que ces
critères matériels et de distribution ne sont pas clos.
