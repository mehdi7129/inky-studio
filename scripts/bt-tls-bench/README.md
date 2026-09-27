# C2.0 — Mbed TLS ↔ Python/OpenSSL, en buffers

Banc synthétique daté du **27 septembre 2026**, pour macOS. Il utilise les APIs
publiques `mbedtls_ssl_set_bio` et `SSLObject`/`MemoryBIO`, sans socket, radio,
Raspberry ni mutation Wi-Fi. **Il ne valide pas l’intégration iOS ou le provisioning.**

## Exécuter

Pré-requis déjà installés : Clang, CMake, Python ≥3.12 lié à OpenSSL avec TLS1.3,
et CLI OpenSSL capable de générer un certificat EC avec `-addext`. Le script
n’installe aucune dépendance globale. Sur le Mac testé, Python système est lié
à LibreSSL : utiliser le Python Homebrew. Aucun droit administrateur nécessaire.

```sh
sh build.sh
```

Pour choisir explicitement les exécutables :

```sh
INKY_BENCH_PYTHON=/opt/homebrew/bin/python3.13 \
INKY_BENCH_OPENSSL=/opt/homebrew/opt/openssl@3/bin/openssl \
sh build.sh
```

Le script crée un nouveau dossier temporaire `inky-c2-tls-bench.XXXXXX`, affiche
son chemin, et y place tous les téléchargements, builds, certificats et logs.
Il ne modifie pas le dossier source. En cas d’échec, examiner `configure.log`,
`build.log` ou `certificates.log` dans ce dossier. Une exécution complète affiche
trois cas `pass: true`, puis le chemin du nouveau `result.json` ; un lancement
du script ou une compilation seule ne suffit pas à valider le banc.

Les clés de test restent dans le dossier temporaire créé avec permissions
restrictives ; la CA expire après deux jours, le leaf après un jour. Chaque run
les régénère. Supprimer ce dossier après conservation des preuves souhaitées.
Ne jamais copier les clés, certificats, bibliothèques ou binaires dans le dépôt.

## Sources et sécurité de téléchargement

`build.sh` télécharge l’archive officielle **Mbed TLS 4.1.1**, avec ses dépendances
incluses, puis impose ce SHA-256 **avant extraction et compilation** :

`3359a349e23db3d5536fcee032ae7b2ecbfc08972fab643089b5cbf2a375c98c`

[Release officielle](https://github.com/Mbed-TLS/mbedtls/releases/tag/mbedtls-4.1.1).
L’archive initialement contrôlée fait 7 099 934 octets. Un hash différent fait
échouer le script ; aucun fallback vers une branche mouvante. `source.json`
enregistre la provenance dans les artifacts temporaires.

## Ce qui est testé

1. TLS **1.3** exclusivement, early data et tickets désactivés. CA locale
   synthétique préapprouvée, vérification REQUIRED de la chaîne, du nom et
   des dates, plus pin **SHA256(DER SubjectPublicKeyInfo)** du serveur.
   Le callback ajoute une erreur si le pin diffère et ne supprime jamais les
   erreurs X.509. Toute écriture applicative avant handshake authentifié est refusée.
2. Handshake et echo de **600 octets dans chaque sens**, transportés par fragments
   d’au plus **20 octets**, sans corruption.
3. Mauvais pin : refus X.509 et **zéro octet applicatif envoyé**.
4. Record chiffré altéré après un bon handshake : erreur TLS, **zéro plaintext
   reçu** côté serveur. Les erreurs WANT_READ/WANT_WRITE sont traitées séparément.

[Preuve initiale](result.json) : Mac arm64, Python 3.13.3 / OpenSSL 3.6.3,
trois cas PASS. La dylib liée statiquement avec dead stripping et `strip -x`
mesure **637 784 octets**. Les durées du JSON sont des observations locales en
buffers, pas un débit BLE ni un benchmark statistique. Les compteurs chiffrés
couvrent handshake et echo, pas la fermeture qui suit.

[Reproduction depuis les sources du dépôt](result-reproduction.json) : nouveau
téléchargement vérifié, compilation propre et certificats régénérés ; trois cas
PASS, même taille de dylib. Handshake observé à 7,709 ms et echo terminé à
8,384 ms sur ce deuxième run. Ces deux exécutions ne constituent pas une mesure
statistique ou une estimation de la latence radio.

## Limites

**Le banc a une CA préapprouvée en plus du pin.** Il ne qualifie pas une adoption
reposant uniquement sur le QR, la confiance HTTPS ou l’horloge hors ligne. Ne pas
réutiliser ce code en désactivant globalement la validation des certificats.

La compilation native C/ctypes n’est ni un wrapper Swift ni un XCFramework iOS.
La configuration crypto amont par défaut et les buffers de 64 KiB ne sont pas
un choix de production ni une taille minimale. Pas de GATT multi-client,
ownership/révocation, persistance, NetworkManager ou reprise après coupure.
Les tests amont Mbed TLS n’ont pas été exécutés ; les tests d’interopérabilité
ne sont pas un audit cryptographique ou un audit de l’app.

Étapes ultérieures seulement : politique de confiance, adaptation iOS, transport
BLE isolé par session, adoption durable et qualification Wi-Fi sur un réseau de test.
