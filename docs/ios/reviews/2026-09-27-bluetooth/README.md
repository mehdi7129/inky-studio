# Validation C2 — 27 septembre 2026

Implémentation candidate : build TestFlight 4 envoyé et traité, mais non distribué
(conformité documentaire en attente). Backend non déployé sur le service photo du cadre. Les identités, photos et mots de passe des bancs sont
synthétiques. Les parcours Simulator utilisent des réseaux synthétiques ; le
scan WPA2 du helper installé a interrogé le réseau réel sans conserver son nom.

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
| Installation du helper, ensuite par Mehdi | Service actif, compte dédié, droits `0555`/socket `0660`, `NoNewPrivileges=yes`, health et scan WPA2 réels PASS |
| Backend candidat isolé sur Pi Zero 2 W | 11 contrôles PASS, BlueZ réel, listeners HTTP/HTTPS et claim TLS/GATT en mémoire ; écran mock sans SPI, helper limité à `health` |

L’avertissement Python restant vient de la transition `httpx` / `httpx2` de
Starlette, sans échec de test. Le build iPhone a ensuite été archivé et signé en version 1.0.0 (4). L’upload
interne et l’export Development réussissent ; Apple demande encore les documents
de chiffrement avant distribution. Voir [la livraison](../../TESTFLIGHT-DELIVERY.md).

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

[Backend candidat isolé sur Pi](pi-backend.json) — commit `9351ae8`,
11 contrôles PASS : listeners loopback HTTP/HTTPS, auth et session commune,
TLS 1.3, health du vrai helper, QR mock privé, claim TLS/GATT en mémoire,
statut owner, restauration du QR mock, blocage des mutations helper et cleanup
unique. BlueZ est réel, mais le flux GATT de ce banc reste en mémoire ; la radio
est couverte séparément par `ble-radio.json`. Zéro appel SPI, aucun scan Wi-Fi
dans ce banc, seule opération helper `health`. Données temporaires supprimées,
service photo et helper actifs après l’essai. Cette preuve ne valide ni le QR
sur l’écran physique ni une transaction NetworkManager.

Captures iOS 18.5 : [réseaux clair](bluetooth-networks-light.png),
[sombre](bluetooth-networks-dark.png), [saisie](bluetooth-credentials-light.png),
[confirmation](bluetooth-confirmation-light.png), [annulation](bluetooth-rollback-light.png).
Captures iOS 27 : [clair](bluetooth-networks-light-ios27.png),
[sombre](bluetooth-networks-dark-ios27.png). Revue visuelle : titres et actions
visibles, cartes arrondies, aucune bande vide supérieure dans le contenu.

## Bêta interne de qualification

Une prochaine bêta interne peut servir à exécuter les tests iPhone encore ouverts
ci-dessous : leur réussite complète n’est donc pas un préalable à cette bêta.
Avant sa distribution, préparer le nouveau numéro de build et résoudre le
contrôle export du build avec les réponses exactes et les documents effectivement
demandés. Le dialogue documentaire au niveau de l’app a été consulté puis annulé ;
le questionnaire du nouveau build/TestFlight reste non consulté. Voir
[l’inventaire et le constat ASC](../../ENCRYPTION-INVENTORY.md).

Cette bêta doit présenter explicitement ses limites de qualification ; elle ne
constitue pas une release publique. Aucun upload ni nouveau numéro TestFlight
n’est annoncé par ce rapport.

## Critères restant ouverts avant merge final et release publique

Adoption depuis un iPhone ; changement vers le partage 2,4 GHz choisi par Mehdi ;
mauvais secret, annulation, coupure de l’app/Pi, rollback et commit durables sur
NetworkManager réel. La PR reste draft pendant cette qualification matérielle.
Les résultats obtenus via la bêta interne peuvent fermer ces critères avant le
merge final ; la distribution publique reste également soumise à son propre
parcours de conformité et de review.

CI complète sur `9351ae8` : [backend/frontend](https://github.com/mehdi7129/inky-studio/actions/runs/36323572209) et [iOS](https://github.com/mehdi7129/inky-studio/actions/runs/36323572206), succès.

CI complète du build 4 `70148f5` : [backend/frontend](https://github.com/mehdi7129/inky-studio/actions/runs/36324581335) et [iOS](https://github.com/mehdi7129/inky-studio/actions/runs/36324581369), succès.
Le passage de la version backend à `0.5.0-rc.2` Unreleased est également
vérifié localement : Ruff et 329 tests Python 3.13 passent.
