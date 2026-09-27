# Inky Studio - annexe technique de préparation

INKY STUDIO

Annexe technique - Chiffrement de l’app iPhone

Brouillon pour revue - 27 septembre 2026. Aucun formulaire signé ou envoyé. Ce document technique ne constitue ni une déclaration administrative, ni une attestation ANSSI, ni une autorisation Apple.

## 1. Produit concerné

| Élément | Périmètre décrit |
| --- | --- |
| Produit final | Inky Studio, application iPhone pour cadre photo à encre électronique. |
| Version | iOS 1.0.0, build 4 ; bundle fr.mehdiguiard.inkystudio. Source 70148f5. |
| Distribution actuelle | Upload TestFlight interne traité ; distribution suspendue à la conformité documentaire. Aucune publication App Store. |
| Composant associé | Backend Inky Studio pour Raspberry Pi. Backend Bluetooth 0.5.0-rc.2 déployé sur le cadre de qualification ; la validation physique iPhone/Wi-Fi reste ouverte. |

## Fonctions accessibles

L’app permet de choisir ou prendre une photo, la cadrer, l’envoyer au cadre, organiser la file et programmer les changements d’image. La nouvelle fonction Bluetooth sert à associer un téléphone et à configurer le Wi-Fi du cadre lors d’un déplacement.

Le produit ne fournit ni VPN, ni messagerie, ni service général de chiffrement de fichiers. Il n’utilise aucun compte cloud Inky Studio, publicité ou service de suivi intégré. Les images et identifiants de réseau restent dans le circuit local iPhone/cadre.

## Description fonctionnelle prête à reporter en B.2

Application logicielle iOS de commande d’un cadre photo local. Le chiffrement protège l’authentification du cadre et les informations de configuration Wi-Fi transportées par Bluetooth ; HTTPS protège ensuite les échanges avec un cadre associé. La fonction principale est la gestion et l’affichage de photographies. La catégorie administrative de cette fonction doit être confirmée par le déclarant.


---

ÉCHANGES ET CLÉS

2. Fonctionnement de la sécurité

## Association et configuration

1. Depuis une session authentifiée sur le réseau habituel, l’utilisateur demande au cadre d’afficher un QR temporaire. Le QR contient l’identifiant du cadre, l’empreinte de sa clé publique et un jeton d’association.

2. L’iPhone lit physiquement ce QR, découvre le cadre en Bluetooth et vérifie son identité avant d’envoyer des secrets. La découverte GATT ne constitue pas, seule, une authentification.

3. Un canal TLS 1.3 est établi sur le transport GATT fragmenté. Un identifiant de propriétaire et un secret aléatoire durable autorisent le téléphone à reconfigurer ce cadre.

4. Le nom et le mot de passe du réseau sont transmis dans le canal TLS. Le helper local demande à NetworkManager un essai de connexion avec checkpoint et délai de retour.

5. L’iPhone rejoint le même réseau et confirme en HTTPS l’identité du cadre et l’autorisation du propriétaire. Le nouveau profil n’est conservé qu’après cette confirmation ; les échecs prévoient un rollback.

## Conservation et cycle de vie

Le cadre génère sa propre clé EC P-256 et un certificat X.509 auto-signé. L’empreinte SHA-256 de la clé publique est lue dans le QR. Les clés privées restent dans les fichiers protégés du cadre ; les autorisations du téléphone sont conservées dans le Keychain Apple, propres à cet appareil.

Les jetons de propriétaire contiennent 32 octets aléatoires ; le serveur conserve leurs empreintes. Le jeton de QR est temporaire et consommé à l’association. La personnalisation du mot de passe de l’app révoque les anciennes autorisations selon le protocole décrit dans le dépôt.

Le mot de passe Wi-Fi n’est pas conservé dans le journal de reprise ni dans le stockage du téléphone. NetworkManager conserve le profil après confirmation. Les mots de passe de l’app sont stockés côté cadre avec sel et scrypt. Aucun algorithme cryptographique maison n’est utilisé.

## Compatibilité et limite du périmètre

Les clients non associés peuvent encore accéder à l’API HTTP locale historique. Le présent document ne prétend donc pas que tout accès historique au cadre est chiffré. Après association, les échanges de l’app avec ce cadre utilisent HTTPS avec contrôle de son identité. Le transport GATT personnalisé organise les paquets ; la cryptographie reste celle de TLS.


---

PROTOCOLES ET IMPLÉMENTATIONS

3. Inventaire cryptographique

| Usage | Algorithme / taille | Implémentation |
| --- | --- | --- |
| Commandes Bluetooth | TLS 1.3 uniquement ; chiffrement authentifié AES-128/256 GCM, ChaCha20-Poly1305 ; autres suites TLS 1.3 présentes dans la configuration upstream. | Mbed TLS 4.1.1 + TF-PSA-Crypto 1.1.1, liés statiquement. |
| Identité du cadre | EC P-256 ; signature ECDSA ; empreinte SHA-256 du SPKI. | Certificat généré sur le cadre ; validation et pin avant données applicatives. |
| Échange de clés TLS | Groupes éphémères négociés par TLS 1.3 ; configuration upstream conservée. | Mbed TLS côté iOS, OpenSSL côté backend. |
| HTTPS / WebSocket | TLS fourni par les API Apple ; pin de l’identité associée. | URLSession / Security Apple. |
| Autorisations locales | Secret aléatoire de 256 bits ; stockage Keychain et empreinte côté cadre. | APIs système et bibliothèques standard. |

## Capacités compilées et fonctions exposées

La bibliothèque n’a pas été réduite à une seule suite. Sa configuration inclut aussi des primitives non exposées par le parcours Bluetooth : AES, ARIA et Camellia jusqu’à 256 bits, ChaCha20, RSA, ECDH/ECDSA, FFDH, hachages et dérivations. Les limites de configuration relevées incluent MPI 1024 octets et courbes jusqu’à 521 bits ; les groupes FFDH demandés vont jusqu’à 8192 bits.

L’inventaire JSON joint conserve les configurations source, leurs empreintes et 262 macros pertinentes réellement prétraitées pour arm64 iOS 18. Il distingue la configuration de compilation des fonctions présentes après édition de liens et de celles accessibles à l’utilisateur. Ce relevé ne prétend pas certifier que chaque primitive est conservée dans le binaire final.

Les suites TLS 1.3 listées par upstream incluent également AES-128-CCM et CCM-8. Le wrapper impose TLS 1.3, validation X.509 obligatoire, contrôle de l’empreinte, absence de tickets de session et absence de 0-RTT. Le banc d’interopérabilité a notamment négocié TLS_AES_256_GCM_SHA384 ; une négociation unique ne résume pas toutes les capacités.

## Traçabilité

Archive upstream Mbed TLS vérifiée par SHA-256 ; configuration et empreinte de l’exécutable archivé du build 4 : build4-crypto-configuration.json. Le hash de cet exécutable local ne désigne pas un éventuel binaire reconditionné par Apple. Les notices de licences sont incluses dans l’app.


---

ÉTAT ET PIÈCES À COMPLÉTER

4. Préparation du dossier

## Preuves techniques disponibles

329 tests backend passent sur Python 3.11 et 3.13. Les tests iOS couvrent les modèles, l’interface et les parcours simulés sur iOS 18.5 et iOS 27. Les bancs TLS, GATT et HTTPS vérifient notamment le refus d’une identité incorrecte avant transmission de données applicatives.

Un banc Bluetooth réel Mac/Raspberry a réussi l’échange chiffré, le refus d’une mauvaise empreinte et la reconnexion. Le backend candidat passe 11 contrôles sur le Pi avec BlueZ réel, données privées temporaires et écran forcé simulé. Le changement réel de Wi-Fi, l’association physique iPhone et les coupures restent à qualifier ; aucune certification de sécurité n’est revendiquée.

## Correspondance avec le formulaire officiel

B.1 : désigner le produit final Inky Studio, version iOS 1.0.0 (4), avec son backend associé décrit comme contexte. B.2 : reprendre la description fonctionnelle. B.3 : reprendre le protocole, les fonctions et les implémentations ci-dessus, en joignant l’inventaire détaillé. La date de mise sur le marché n’est pas la date d’upload : elle reste à définir.

Déclarant confirmé : Mehdi Guiard, personne physique, rubrique A.2. Les coordonnées privées et le contact technique fournis par le titulaire sont préremplis dans une copie locale du formulaire officiel, avec les données techniques. Ils ne figurent pas dans cette annexe. Aucune société ni référence SIRET n’est déclarée. Le formulaire est un PDF XFA dynamique à ouvrir dans un lecteur compatible.

Les choix déclaration/autorisation, le classement grand public, les opérations et territoires ainsi que la signature restent à confirmer par la personne habilitée. Aucune référence de déclaration antérieure n’est supposée. L’annexe technique seule n’est pas présentée comme un justificatif approuvé par Apple.

## Sources et documents associés

[ANSSI - formulaire officiel, annexe I v2](https://cyber.gouv.fr/documents/330/crypto_declaration-demande_autorisation_operations_annexe1_v2.pdf)

[ANSSI - formulaires et modalités de dépôt](https://cyber.gouv.fr/reglementation/reglementation-identite-confiance-numerique/controles-reglementaires-cryptographie/controle-moyen-de-cryptologie/controle-reglementaire-cryptographie-formulaires/)

[Apple - déterminer et transmettre les documents de chiffrement](https://developer.apple.com/help/app-store-connect/manage-app-information/determine-and-upload-app-encryption-documentation)

[Code source Inky Studio et PR de qualification](https://github.com/mehdi7129/inky-studio/pull/11)

Pièces techniques du dépôt : ENCRYPTION-INVENTORY.md ; BLE-PROTOCOL-V1.md ; BLUETOOTH-INTEGRATION.md ; export/build4-crypto-configuration.json ; rapport et captures reviews/2026-09-27-bluetooth/.
