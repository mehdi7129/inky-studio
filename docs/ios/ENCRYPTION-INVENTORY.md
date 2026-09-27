# Inventaire cryptographique pour le prochain build iOS

27 septembre 2026 — préparation technique, aucune déclaration administrative
envoyée par ce document. Le build TestFlight 1.0.0 (3) n’intègre pas Mbed TLS.

| Usage | Implémentation du nouveau code |
|---|---|
| Confidentialité et intégrité des commandes Bluetooth | Mbed TLS 4.1.1 et TF-PSA-Crypto embarqués, TLS 1.3 uniquement |
| Preuve du cadre | Certificat X.509 auto-signé, EC P-256, ECDSA/SHA-256, pin SHA-256 du SPKI lu sur le QR physique |
| HTTPS, photos, WebSocket | URLSession / Security Apple, identité adoptée vérifiée |
| Autorisations et mot de passe local | Keychain Apple ; propriétaire aléatoire de 32 octets, pas un algorithme propriétaire |
| Portée fonctionnelle | Configuration locale d’un cadre photo, aucun VPN ou outil général de chiffrement |

Le build script conserve la configuration cryptographique upstream ; la capacité
du binaire ne se limite donc pas à la seule cipher suite négociée pendant le banc.
Inventorier les fonctions embarquées depuis l’archive/configuration épinglées si le
formulaire l’exige. Les tickets de session et le 0-RTT ne sont pas utilisés.
Le framing GATT et les commandes Inky ne sont pas des algorithmes cryptographiques.

Apple distingue le chiffrement fourni par le système et les algorithmes standard
embarqués hors du système. Sa page de référence demande une déclaration française
pour la seconde catégorie lorsque l’app est distribuée sur l’App Store en France.
[Référence Apple consultée le 27 septembre 2026](https://developer.apple.com/help/app-store-connect/reference/app-information/export-compliance-documentation-for-encryption).

L’ancienne déclaration automatique `ITSAppUsesNonExemptEncryption=false` est
retirée. Le prochain upload nécessitera les réponses exactes au questionnaire
App Store Connect et les éventuels documents demandés ; ni exemption, ni référence
d’autorisation, ni dépôt auprès de l’ANSSI ne sont inventés. Conserver la France
dans le périmètre souhaité et traiter les formalités avant distribution publique.

[Guide du questionnaire et des documents Apple](https://developer.apple.com/help/app-store-connect/manage-app-information/determine-and-upload-app-encryption-documentation).

## Addendum — TestFlight interne et distribution en France

Recherche documentaire Apple et ANSSI du 27 septembre 2026, complétée par la
consultation App Store Connect décrite ci-dessous. Aucun enregistrement ni envoi
de déclaration, aucune démarche ANSSI engagée. Les sources publiques et le
parcours observé ne constituent pas une qualification administrative propre à
Inky Studio.

### Consultation réelle d’App Store Connect, annulée sans enregistrement

Le 27 septembre 2026, le parcours **Informations sur l’app → Documents de
chiffrement → Charger** a été ouvert. Une description de l’objectif technique,
les algorithmes standard hors du système Apple et la disponibilité en France
(`Oui`) ont été renseignés dans le dialogue, sans enregistrement.

Le dialogue a alors demandé un fichier nommé **« Formulaire français de
déclaration et demande d’autorisation d’opérations relatives à un moyen de
cryptologie »**. Le bouton **Enregistrer** est resté désactivé sans fichier.
Le parcours a été quitté avec **Annuler** : aucun document téléversé, aucune
déclaration enregistrée, aucune soumission à Apple ou à l’ANSSI.

Ce constat établit l’exigence de fichier dans **ce parcours documentaire au
niveau de l’app**, avec ces réponses. Le questionnaire rattaché à un nouveau
build/TestFlight n’a pas été consulté ; son résultat, notamment pour une bêta
`Internal Only`, reste inconnu. On ne transpose pas automatiquement le blocage
du bouton de ce dialogue à toute distribution interne.

| Point | Fait établi et conséquence pour ce build |
|---|---|
| Chiffrement de l’app | Mbed TLS embarque des algorithmes standard hors du système Apple. On peut le déclarer factuellement ; la réponse « seulement le chiffrement de l’OS » ne correspond plus au binaire. La référence Apple distingue cette catégorie des algorithmes propriétaires. [Table Apple](https://developer.apple.com/help/app-store-connect/reference/app-information/export-compliance-documentation-for-encryption). |
| Déclaration française demandée par Apple | La note 1 de cette table limite explicitement l’exigence française à une distribution **sur l’App Store en France**. Elle ne dit pas qu’une bêta exclusivement interne exige automatiquement ce document. Elle ne tranche pas non plus le cas d’un build interne rattaché à une app dont la disponibilité future inclut la France. [Même référence, note 1](https://developer.apple.com/help/app-store-connect/reference/app-information/export-compliance-documentation-for-encryption). |
| TestFlight interne | Le build bêta doit tout de même répondre au contrôle export. Apple prévoit un état `Missing Compliance`, un questionnaire dans TestFlight et, selon ses réponses, des documents. L’état `Ready to Submit` permet la distribution interne ; la review bêta concerne ensuite les testeurs externes. Les pages consultées n’établissent pas de dispense générale pour les testeurs internes. [Conformité des builds bêta](https://developer.apple.com/help/app-store-connect/test-a-beta-version/provide-export-compliance-information-for-beta-builds), [états des builds](https://developer.apple.com/help/app-store-connect/reference/app-build-statuses/). |
| Option « Internal Only » | Cette option empêche d’envoyer ce build aux testeurs externes ou aux clients. Elle définit un périmètre réel de distribution ; Apple ne la présente pas comme une exemption au contrôle export. [Testeurs internes](https://developer.apple.com/help/app-store-connect/test-a-beta-version/add-internal-testers). |
| App Store public en France | Pour les algorithmes standard embarqués hors OS, le parcours documentaire publié par Apple demande la déclaration française. Les documents demandés doivent être traités avant la review ; Apple examine les dossiers au cas par cas. [Table Apple](https://developer.apple.com/help/app-store-connect/reference/app-information/export-compliance-documentation-for-encryption), [dépôt documentaire](https://developer.apple.com/help/app-store-connect/manage-app-information/determine-and-upload-app-encryption-documentation). |

Le simple usage de `URLSession` serait généralement dispensé de dépôt documentaire
Apple, mais cette app contient aussi une bibliothèque tierce. Apple demande de
tenir compte de **toutes** les bibliothèques liées : `ITSAppUsesNonExemptEncryption`
ne doit être `false` que si aucun chiffrement n’est utilisé ou si tous les usages
sont exemptés. L’absence de clé déclenche le questionnaire ; elle ne déclare ni
une exemption ni une interdiction de distribution.
[Clé Info.plist Apple](https://developer.apple.com/documentation/BundleResources/Information-Property-List/ITSAppUsesNonExemptEncryption),
[guide Security Apple](https://developer.apple.com/documentation/Security/complying-with-encryption-export-regulations).

Aucune source documentaire Apple consultée ne fournit le texte exact d’une
exemption « stockage/périphériques » ou « fonction accessoire » applicable à ce
cas. Ces intitulés ne sont donc pas une base retenue pour préremplir le
questionnaire. Une absence de résultat public ne signifie pas qu’aucune exemption
n’existe ; le libellé et les conditions du questionnaire du nouveau build
TestFlight restent à lire avant toute réponse administrative enregistrée.

### Ce que les sources ANSSI permettent de conclure

L’ANSSI distingue l’utilisation libre en France de la fourniture, de l’importation
et de l’exportation, soumises à formalités sauf exception. Le régime dépend des
fonctions du produit **et de l’opération**. Une attestation de déclaration prouve
l’accomplissement de la démarche ; le classement « grand public » relève d’une
validation ANSSI, pas du seul fait qu’une app vise le public.
[Contrôle d’un moyen de cryptologie](https://cyber.gouv.fr/reglementation/reglementation-identite-confiance-numerique/controles-reglementaires-cryptographie/controle-moyen-de-cryptologie/),
[classement grand public](https://cyber.gouv.fr/reglementation/reglementation-identite-confiance-numerique/controles-reglementaires-cryptographie/controle-moyen-de-cryptologie/controle-rglementaire-cryptographie-demarches/).

La liste **indicative** ANSSI mentionne notamment les équipements Bluetooth,
l’administration/configuration, l’usage personnel de celui qui effectue
l’opération, et la cryptologie accessoire d’équipements hors TIC. Les périmètres
et opérations exemptés diffèrent. Elle ne qualifie pas explicitement une app iOS
qui transporte TLS applicatif sur GATT. Déduire une exemption du seul mot
« Bluetooth », « personnelle » ou « photo » serait donc insuffisamment établi.
L’exception limitée à l’authentification/intégrité ne décrit pas ce TLS, qui
protège aussi la confidentialité du mot de passe Wi-Fi.
[ANSSI : exemptions et limites de la liste](https://cyber.gouv.fr/reglementation/reglementation-identite-confiance-numerique/controles-reglementaires-cryptographie/controle-export/).

### Décision de travail et points encore ouverts

- Continuer les builds, tests et l’inventaire local est possible. Le code ne
  justifie pas de rétablir automatiquement `ITSAppUsesNonExemptEncryption=false`.
- Pour une bêta strictement interne, **l’obligation d’obtenir préalablement une
  attestation française n’est pas démontrée par la seule documentation Apple**.
  Le contrôle export du build reste à résoudre avec des réponses exactes. Les
  réponses factuelles sont : chiffrement présent, algorithmes standard embarqués
  hors OS, TLS pour la configuration d’un cadre, aucun VPN ni algorithme maison.
- Pour la publication française, prévoir le parcours documentaire Apple ; si
  une exemption ANSSI s’applique, sa portée et le justificatif accepté par Apple
  restent à établir. Ni un reçu inexistant ni une classification ne sont fournis
  par cet inventaire. La consultation réelle du dialogue documentaire de l’app
  a confirmé la demande de fichier pour « France : Oui » ; elle a été annulée.
- Incertitudes précises : applicabilité des exceptions au **produit logiciel
  complet** et aux opérations envisagées ; pièces qu’Apple accepterait pour une
  exemption française ; résultat du questionnaire pour un build `Internal Only`
  avec une future disponibilité française. Ces points peuvent être soumis aux
  interlocuteurs Apple/ANSSI, sans présumer leur réponse.

Aucun changement de disponibilité géographique enregistré, formulaire soumis, signature,
attestation d’exemption ou engagement au nom de Mehdi n’est réalisé ici.

### Éléments à préparer sans données personnelles

Cette liste est une préparation technique proposée, pas un formulaire officiel :

- Description courte du cadre photo, de l’app et du parcours de configuration ;
  guide utilisateur montrant les fonctions réellement accessibles.
- Version/hash du futur binaire, versions et configurations exactes de Mbed TLS
  et TF-PSA-Crypto, inventaire des primitives compilées et des suites utilisées.
- Schéma des échanges BLE/TLS et HTTPS ; génération, conservation, distribution
  et validation des clés/certificats ; distinction entre confidentialité,
  authentification et intégrité. Utiliser seulement des exemples synthétiques.
- Périmètre de distribution prévu pour le build : interne/externe/public,
  destinataires et territoires sous forme de catégories, sans noms de testeurs.

L’ANSSI indique, pour son dossier de demande, une présentation de l’entreprise,
un justificatif d’immatriculation ou équivalent, une brochure, un descriptif
technique et les guides disponibles. L’applicabilité des pièces d’entreprise à
un développeur individuel reste à préciser ; aucun justificatif personnel n’est
recherché ou ajouté ici.
[ANSSI : pièces du dossier](https://cyber.gouv.fr/reglementation/reglementation-identite-confiance-numerique/controles-reglementaires-cryptographie/controle-moyen-de-cryptologie/faq-demande-dautorisation/).

Points à confirmer ultérieurement par le titulaire du compte, sans répondre à
sa place : la bêta est-elle réservée à son usage propre ou à d’autres testeurs ;
quel périmètre public est effectivement prévu ; le déclarant éventuel est-il une
personne physique ou une société ; existe-t-il déjà un document de classement
applicable au produit complet. Aucun de ces points ne bloque la PR d’intégration,
les builds locaux ou les bancs techniques en cours. Le build publié numéro 3
n’est pas modifié par cet inventaire.
