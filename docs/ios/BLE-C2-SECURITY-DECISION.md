# C2 — décision de sécurité pour l’adoption et le Wi-Fi par BLE

Date de recherche : **27 septembre 2026**. Statut : **architecture candidate,
premier banc en buffers réussi**, pas une intégration validée ni une fonctionnalité livrée. Cette
note précise le [plan produit](PRODUCT-EVOLUTION-PLAN.md) ; le résultat matériel
de référence reste le [banc C1](BLUETOOTH-BENCH.md).

## Décision proposée

Retenir pour qualification **TLS 1.3 sur un transport BLE fragmenté**, avec Mbed TLS **4.1.1**
côté client et Python/OpenSSL `SSLObject`/`MemoryBIO` côté Pi. L’identité du cadre
vient d’une empreinte de clé publique lue sur son écran physique, avant tout envoi
de secret. Le QR contient aussi un jeton d’adoption aléatoire à usage unique.
L’adoption établit ensuite une autorisation propriétaire durable, utilisable
pour reconfigurer le Wi-Fi même lorsque l’API réseau est inaccessible.

TLS est standard ; les commandes et la machine d’état Inky restent à concevoir,
tester et revoir. Ce choix ne constitue donc pas un protocole d’adoption standard
complet. Aucun échange cryptographique, chiffrement ou dérivation de clé maison.
Le premier prototype valide les APIs C et l’interopérabilité en buffers ;
l’adaptation Swift et son coût restent à qualifier. Une compilation Mac ne
prouve pas la compatibilité iOS.

## État des preuves

| Élément | État au moment de cette décision |
|---|---|
| Pi Zero 2 W, Debian 13, BlueZ 5.82, NetworkManager 1.52.1 | Versions relevées pendant C1 |
| GATT Mac ↔ Pi, fragmentation, doublon et reconnexion | C1 PASS, données synthétiques uniquement |
| API NetworkManager Checkpoint | Méthodes présentes ; aucun appel de bascule/rollback effectué |
| Appairage BLE authentifié, identité et ownership | Non testés par C1 |
| TLS Mbed TLS ↔ OpenSSL, en buffers Mac | C2.0 : trois cas PASS, CA synthétique préapprouvée + pin SPKI |
| Wrapper Swift et confiance fondée seulement sur le QR | Non implémentés/qualifiés |
| TLS sur BLE iPhone, adoption durable, HTTPS lié au QR | Non implémentés/qualifiés |
| Changement Wi-Fi, rollback, coupure électrique | Non implémentés/qualifiés par ce travail |

La formulation ancienne « C1 vérifie son identité » décrit un objectif, pas le
résultat réalisé : l’echo C1 ne prouve aucune identité. Le service C1 n’a reçu
aucun credential. Son serveur temporaire a été arrêté, supprimé du Pi et la radio
restaurée dans son état initial. Les preuves publiées sont synthétiques.

## Version Mbed TLS réellement disponible

La disponibilité n’est plus une hypothèse de roadmap. Les releases GitHub
officielles déclarent `draft=false` et `prerelease=false` :

| Release | Publication UTC vérifiée dans l’API GitHub |
|---|---|
| [4.1.0](https://github.com/Mbed-TLS/mbedtls/releases/tag/mbedtls-4.1.0) | 31 mars 2026, 13:42:41 |
| [4.1.1](https://github.com/Mbed-TLS/mbedtls/releases/tag/mbedtls-4.1.1) | 7 juillet 2026, 14:43:41 |

L’[annonce TrustedFirmware du 31 mars 2026][mbed-announcement] et le
[document des branches au tag 4.1.1][mbed-branches] confirment le support de la
branche 4.1 jusqu’à mars 2029. La branche 3.6 reste supportée jusqu’à mars 2027 :
elle n’apporte pas une meilleure durée de maintenance pour cette nouvelle intégration.

Base du prototype : archive officielle `mbedtls-4.1.1.tar.bz2`, incluant ses
dépendances, plutôt que les snapshots GitHub « Source code » incomplets.
SHA-256 annoncé par la release et son asset :
`3359a349e23db3d5536fcee032ae7b2ecbfc08972fab643089b5cbf2a375c98c`.
Le hash du téléchargement a été contrôlé avant la compilation C2.0. Épingler aussi la
configuration, le compilateur et le contenu TF-PSA-Crypto fourni ; ne pas mélanger
des versions choisies séparément. [Release 4.1.1][mbed-release].

La maintenance demeure une charge Inky : surveillance des avis de sécurité,
mise à jour des patchs, rebuild des variantes device/simulator, notices de licence
et requalification. Le [README versionné][mbed-readme] décrit la séparation
TLS/X.509/TF-PSA-Crypto et les licences. Aucun XCFramework ou wrapper Swift officiel
prêt à intégrer n’a été établi dans cette recherche. Le poids final iOS et la mémoire
ne sont pas connus ; le binaire Mac mesuré ci-dessous ne les prédit pas.

## C2.0 — résultat limité, reproductible

Sources du [banc en buffers](../../scripts/bt-tls-bench/README.md) et
[preuve JSON](../../scripts/bt-tls-bench/result.json). Sur Mac arm64, client C
Mbed TLS 4.1.1 via callbacks BIO publics et serveur Python 3.13.3/OpenSSL 3.6.3
via MemoryBIO : **trois cas PASS**. Aucun socket, Pi, radio ou changement Wi-Fi.

- TLS 1.3 / `TLS_AES_256_GCM_SHA384`, echo de 600 octets dans chaque sens,
  découpé en fragments de 20 octets maximum : données identiques.
- Pin `SHA256(DER SubjectPublicKeyInfo)` vérifié pendant la validation X.509,
  avant toute écriture applicative. Mauvaise empreinte : refus, zéro payload.
- Record chiffré altéré : erreur OpenSSL, zéro plaintext livré au serveur.
- Preuve conservée : handshake **3,971 ms**, handshake + echo **4,493 ms** ;
  dylib native liée statiquement/dead stripping/strip : **637 784 octets**.
  Mesures locales, sans latence radio, pas un benchmark statistique ou une taille iOS.

**La CA synthétique est préapprouvée en plus du pin.** Le callback conserve les
erreurs de chaîne, nom et dates et le wrapper refuse les écritures avant handshake.
Ce succès ne qualifie donc pas encore la confiance uniquement issue du QR,
l’horloge hors ligne, Swift/iOS, GATT ou l’ownership. Aucun bypass de validation
n’a été nécessaire. Le bundle ne contient ni certificat/clé générée, ni copie de
bibliothèque tierce, ni binaire ; son script fixe archive/hash et place les artifacts dans `/tmp`.

## Options examinées

| Option | Décision et raison |
|---|---|
| Mbed TLS 4.1.1 + fin wrapper C/Swift | Candidate : API publique `mbedtls_ssl_set_bio`, callbacks non bloquants ; dépendance/configuration à maintenir et qualification iOS à faire. [API versionnée][mbed-api] |
| Python/OpenSSL `wrap_bio` sur Pi | Candidate : séparation TLS/transport documentée ; lire la version OpenSSL effective avant le banc Pi. [Python 3.13][python-ssl] |
| SecureTransport avec callbacks I/O | Écarté pour une nouvelle intégration : API legacy dépréciée. [Apple][apple-securetransport] |
| Network.framework seul | Pas de voie publique équivalente à MemoryBIO trouvée dans les APIs consultées. `NWProtocolFramer` décrit un framing applicatif ; il ne documente pas un branchement TLS direct sur GATT. Ce constat n’est pas une preuve d’impossibilité. [Apple][apple-framer] |
| SwiftNIO SSL / BoringSSL | Alternative maintenue, mais ajoute NIO et un adaptateur `Channel`. Les handlers publics sécurisent un Channel ; `EmbeddedChannel` est principalement conçu pour les tests, sans I/O réelle et non thread-safe. Ne pas bâtir la production sur un raccourci de test non qualifié. [NIOSSL][nio-ssl], [NIOEmbedded][nio-embedded] |
| Matter | Véritable commissioning standard QR/BLE, avec support Apple. Il impose de faire du cadre un appareil Matter, avec son modèle de credentials, fabric et attestation ; ce n’est pas une brique générique pour amorcer notre HTTPS. Écarté de C2 minimal, pas disqualifié pour un autre produit. [Apple Matter][apple-matter], [SDK Matter][matter-sdk] |
| GATT chiffré « Just Works », UUID/nom BLE, adresse MAC | Insuffisants comme preuve de propriété. Ni découverte, ni chiffrement de lien sans authentification ne remplacent le QR et l’autorisation applicative. |
| PIN fixe, confiance au premier serveur réseau, chiffrement ad hoc | Rejetés. Aucun repli silencieux quand la preuve d’identité échoue. |

## Pourquoi ne pas retenir le passkey e-ink comme mécanisme principal

BlueZ permet un agent `DisplayOnly` et appelle `DisplayPasskey` pendant
l’appairage. Une variante fondée sur cette voie devrait exiger le niveau de
sécurité authentifié approprié et refuser Just Works, sans PIN fixe. Les flags
GATT `encrypt-*`, `encrypt-authenticated-*` et `secure-*` ne sont pas équivalents.
Le code BlueZ 5.82 applique un niveau supérieur aux permissions `secure-*` ; le
nom interne `BT_ATT_SECURITY_FIPS` ne constitue pas une certification du produit.
[Agent][bluez-agent], [GATT][bluez-gatt], [contrôle effectif][bluez-security].

Le problème matériel est la fenêtre de temps. Le timer SMP expire après
**30 secondes**, avec réinitialisation sur certains échanges : ce n’est pas une
limite globale de 30 secondes pour tout le parcours. Un code disponible pendant
l’appairage doit pourtant être affiché puis saisi à temps. Pimoroni annonce pour
les panneaux actuels des cycles réels de **20 à 35 secondes**, dont 28 secondes
de rafraîchissement nominal pour le 7,3 pouces récent. La variante exacte du
panneau de Mehdi et sa latence ne sont pas mesurées ici : risque crédible, pas
échec prouvé sur son matériel. [Bluetooth SIG, §3.4][smp], [Pimoroni][pimoroni].

Un QR affiché **avant** la connexion TLS évite cette dépendance au timer SMP.
Toute écriture e-ink devra passer par le propriétaire/verrou d’affichage existant,
sans second écrivain SPI et sans remplacement intempestif par le scheduler.
AccessorySetupKit peut fournir un parcours de découverte/appairage iOS ; il ne
remplace pas l’autorisation Inky. [Apple, WWDC24][apple-ask].

## Contrat de sécurité candidat

### Identité physique, TLS et HTTPS

1. Générer une identité unique par cadre et un jeton d’adoption issu de l’aléa
   système, au moins 128 bits. Afficher un QR versionné contenant l’empreinte
   SHA-256 de la clé publique encodée de façon canonique, et le jeton unique.
   La représentation exacte, par exemple DER SubjectPublicKeyInfo, doit être
   fixée et testée entre les bibliothèques. Le QR n’est pas une URL envoyée à un tiers.
2. Établir TLS 1.3 et vérifier la possession de la clé et son empreinte attendue
   **avant** l’envoi du jeton, d’un credential propriétaire ou du secret Wi-Fi.
   Une empreinte reçue par le même BLE n’est pas une racine de confiance.
   La politique X.509, le nom stable et l’horloge sans Internet restent à qualifier ;
   aucune option globale « accepter tous les certificats » ne sera livrée.
3. Après authentification propriétaire, envoyer des commandes versionnées dans
   TLS. Pas de 0-RTT pour les mutations ; le premier prototype désactive aussi
   la reprise de session pour réduire les états à vérifier.
4. L’API HTTPS doit présenter une identité rattachée à celle adoptée. L’adresse IP,
   mDNS ou une annonce BLE peuvent localiser le cadre, jamais autoriser une nouvelle
   clé. Refuser le changement inattendu et tout fallback HTTP pour ces opérations.
   Définir une rotation de clé autorisée ou une réadoption physique explicite.
   [Validation de confiance côté Apple][apple-trust].

Le QR secret prouve l’accès à ce qui est affiché, pas l’identité d’une personne.
Quelqu’un qui en obtient une copie avant consommation peut tenter l’adoption.
Fenêtre bornée, limitation de tentatives et action physique de récupération sont
donc nécessaires. Les boutons réellement accessibles restent à inventorier ;
ne pas supposer que le boîtier permet une confirmation physique particulière.

### Ownership, révocation et idempotence

- Un bond Bluetooth ne vaut pas ownership. Enregistrer une autorisation durable
  par téléphone, protégée dans le Keychain, avec un mécanisme standard à arrêter
  avant la production : credential aléatoire de forte entropie dans TLS ou mTLS.
  Ne pas transformer le mot de passe Wi-Fi/SSH ou le nom du téléphone en identité.
- Préparer et sauvegarder le credential futur côté client avant la finalisation.
  Côté Pi, consommation du jeton QR et enregistrement du propriétaire forment
  une transition durable atomique. Une réponse perdue se reprend avec le même
  initiateur et sa nouvelle autorisation, sans rouvrir une adoption à tout tiers.
- Chaque mutation possède un identifiant de requête et un état consultable après
  reconnexion authentifiée. Même requête/même intention : même résultat ; même
  identifiant/intention différente : refus. Sérialiser les mutations Wi-Fi et
  rattacher transaction et résultat au propriétaire. Borner rétention et taille.
- Révoquer un téléphone invalide ses credentials, transactions/autorisations
  concernées et sessions actives ; nettoyer les bonds éventuels séparément.
  Oublier le cadre uniquement sur l’iPhone n’effectue pas cette révocation serveur.
- Téléphone perdu : récupération propriétaire définie ou reset physique explicite,
  avec effet annoncé sur accès et données. Perte du Wi-Fi, reboot ou fichier d’état
  illisible ne doivent jamais provoquer une réadoption ouverte automatique.
- Un vieux QR reste parfois visible sans alimentation : il doit être invalide
  côté serveur dès consommation, avant même son effacement physique.

Ce sont des invariants à implémenter/tester, pas des garanties déjà obtenues.
L’articulation avec la rotation du mot de passe de l’API et les sessions existantes
doit être spécifiée sans affaiblir [le lot B](PASSWORD-ROTATION.md).

### Transport BLE et privilèges

Le framing C1 n’est pas prêt pour TLS : limite 768 octets, sortie de notification
partagée et absence de contrôle propriétaire. Concevoir un flux ordonné, borné,
avec backpressure, isolation des connexions et fermeture explicite. Tester
fragmentation/agrégation, doublons, pertes, reconnexions et clients concurrents.
Une reconnexion démarre une nouvelle session TLS ; ne pas recoller des fragments
de sessions distinctes. Seuls les octets TLS chiffrés transitent après le framing.

Service BLE sans privilèges système étendus ; helper séparé et étroit pour le
réseau, interface structurée et validation des entrées, sans shell libre. Les
droits GATT vérifiés sous `pi` ne prouvent pas ceux d’un futur service dédié.
Vérifier D-Bus/polkit pour enregistrement GATT/advertising et, si retenu,
`RequestDefaultAgent` qui peut exiger des droits particuliers. [BlueZ][bluez-manager].

## Transaction NetworkManager candidate

Le helper devra disposer des autorisations nécessaires, notamment `wifi.scan`,
`network-control`, `settings.modify.system` et `checkpoint-rollback` ; vérifier
`GetPermissions` sous son UID réel. La politique 1.52.1 définit ces actions,
mais leurs résultats sur le futur compte Inky ne sont pas établis.
[Politique versionnée][nm-policy], [API][nm-api].

1. Sous verrou de transaction, prendre un checkpoint limité à l’interface Wi-Fi
   choisie, timeout non nul. Ne pas viser toutes les interfaces par défaut.
2. Créer un nouveau profil avec `AddAndActivateConnection2`, `persist=memory`
   ou `volatile`, sans écraser l’ancien. Décider explicitement de
   `bind-activation=dbus-client` selon le cycle de vie du helper.
3. Suivre association, authentification et adresse IP. Le propriétaire confirme
   l’accès réel à l’API HTTPS avec l’identité épinglée ; un DHCP réussi seul ne
   valide pas le parcours iPhone → cadre.
4. Après confirmation authentifiée, persister le profil et finaliser le checkpoint.
   Au timeout/annulation/échec, rollback et nettoyage du seul profil créé par la
   transaction ; examiner le résultat par interface. Conserver le canal BLE de reprise.

Les options et méthodes existent dans [NetworkManager 1.52.1][nm-xml]. Ne pas
utiliser `DESTROY_ALL` pour contourner un checkpoint concurrent. Éviter aussi
`DELETE_NEW_CONNECTIONS` sans exclusivité démontrée : il peut supprimer d’autres
connexions créées depuis le checkpoint. [Flags versionnés][nm-flags].

**Limite power loss : un checkpoint n’est pas un journal durable de l’application.**
Conserver les anciens profils sur disque et un journal minimal de transaction
sans secret. Qualifier la reprise après arrêt de NetworkManager, crash du helper
et coupure à chaque frontière, notamment entre sauvegarde du profil et destruction
du checkpoint. Aucune atomicité inter-services n’est présumée. Si l’ancien réseau
n’existe plus, rollback ne recrée pas un LAN : la récupération doit rester en BLE.

Limiter initialement la qualification à un réseau personnel compatible de test.
Un hôtel avec portail captif ou isolation des clients peut laisser le Wi-Fi
connecté tout en empêchant l’usage local. Ne pas annoncer ce cas comme résolu.
Profils NetworkManager protégés, secrets exclus des logs/arguments/captures ;
aucune promesse de chiffrement intégral de la microSD.

## Plan C2 progressif et critères de passage

| Étape | Périmètre et preuve attendue |
|---|---|
| C2.0 — buffers sans radio | **PASS dans le périmètre ci-dessus** : build natif Mac, callbacks BIO publics ↔ Python/OpenSSL, TLS 1.3, CA de test + pin ; mauvaise empreinte refusée sans payload ; découpes 20 octets et record altéré testés. Sources/protocole de reproduction conservés, aucun Pi ni Wi-Fi. |
| C2.1 — adaptation iOS | Wrapper minimal C/Swift, builds device/simulator, confiance/erreurs/backpressure, concurrence et lifecycle. Quantifier la dépendance réelle ; décider de poursuivre ou de changer d’option. |
| C2.2 — BLE synthétique | Nouveau banc temporaire Mac ↔ Pi, puis iPhone ↔ Pi, TLS et données sans secrets personnels. Refus mauvais pin, fragmentation, interruption, reconnexion, client non autorisé et isolation. Aucun changement Wi-Fi. |
| C2.3 — adoption durable | QR physique lisible, credential Keychain, consommation atomique, réponse perdue, replay, révocation, reboot et vieux QR. Identité HTTPS cohérente avant intégration réseau. |
| C2.4 — réseau isolé | Helper à droits limités et réseau de test avec accès de secours ; mauvaise clé, timeout, concurrence, panne helper/NM et coupure électrique. Réussite : photos via HTTPS sur nouveau LAN, anciennes autorisations rejetées et rollback/reprise observés. |

Les inconnues bloquantes sont donc mesurables : coût/intégration iOS de Mbed TLS,
validation X.509 hors ligne et identité HTTPS, transport GATT par session, protocole
durable d’ownership, droits du helper et comportement réel du rollback. Aucun
déploiement de provisioning sur le réseau actuel n’est requis pour C2.0–C2.3.

## Sources primaires et datation

Toutes les sources ci-dessous ont été consultées le **27 septembre 2026**.
Les tags Mbed TLS 4.1.1, BlueZ 5.82 et NetworkManager 1.52.1 sont volontairement
figés ; les pages Apple/Pimoroni et manuels `latest` sont des états consultés à
cette date, sans date de publication inventée. Les décisions de produit et les
invariants ci-dessus sont des propositions Inky, pas des prescriptions de ces sources.

[mbed-announcement]: https://lists.trustedfirmware.org/archives/list/mbed-tls-announce@lists.trustedfirmware.org/message/NQORITLKPVKSDLN366JYB7WGT4EVUDTY/
[mbed-branches]: https://raw.githubusercontent.com/Mbed-TLS/mbedtls/mbedtls-4.1.1/BRANCHES.md
[mbed-release]: https://github.com/Mbed-TLS/mbedtls/releases/tag/mbedtls-4.1.1
[mbed-readme]: https://raw.githubusercontent.com/Mbed-TLS/mbedtls/mbedtls-4.1.1/README.md
[mbed-api]: https://raw.githubusercontent.com/Mbed-TLS/mbedtls/mbedtls-4.1.1/include/mbedtls/ssl.h
[python-ssl]: https://docs.python.org/3.13/library/ssl.html#memory-bio-support
[apple-securetransport]: https://developer.apple.com/documentation/security/secure-transport
[apple-framer]: https://developer.apple.com/documentation/network/nwprotocolframer
[apple-trust]: https://developer.apple.com/documentation/foundation/performing-manual-server-trust-authentication
[apple-ask]: https://developer.apple.com/videos/play/wwdc2024/10203/
[nio-ssl]: https://github.com/apple/swift-nio-ssl
[nio-embedded]: https://github.com/apple/swift-nio/blob/main/Sources/NIOEmbedded/Embedded.swift
[apple-matter]: https://developer.apple.com/apple-home/matter/
[matter-sdk]: https://github.com/project-chip/connectedhomeip
[bluez-agent]: https://raw.githubusercontent.com/bluez/bluez/5.82/doc/org.bluez.Agent.rst
[bluez-gatt]: https://raw.githubusercontent.com/bluez/bluez/5.82/doc/org.bluez.GattCharacteristic.rst
[bluez-security]: https://raw.githubusercontent.com/bluez/bluez/5.82/src/shared/gatt-server.c
[bluez-manager]: https://raw.githubusercontent.com/bluez/bluez/5.82/doc/org.bluez.AgentManager.rst
[smp]: https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/Core-54/out/en/host/security-manager-specification.html
[pimoroni]: https://shop.pimoroni.com/products/inky-impression
[nm-policy]: https://raw.githubusercontent.com/NetworkManager/NetworkManager/1.52.1/data/org.freedesktop.NetworkManager.policy.in.in
[nm-api]: https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.html
[nm-xml]: https://raw.githubusercontent.com/NetworkManager/NetworkManager/1.52.1/introspection/org.freedesktop.NetworkManager.xml
[nm-flags]: https://raw.githubusercontent.com/NetworkManager/NetworkManager/1.52.1/src/libnm-core-public/nm-dbus-interface.h
