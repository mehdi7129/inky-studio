# Inventaire cryptographique et conformité iOS

## Build 1.0.0 (9) distribué en interne — 9 octobre 2026

Le build 9 provient du checkout propre
`181edb2f89034bb0c411b145c95fe303f112b460`. L'archive Release signée et l'IPA
exportée contiennent `ITSAppUsesNonExemptEncryption=true` et le code approuvé
fourni par Apple. Les **76 contrôles de paquet passent** ; le SHA-256 de l'IPA
est `c7642ef10fca15494a41cf8581249dbcce6e25a85328a908f62f51bc49ff1070`.

L'upload a réussi à **06:46:08 UTC**. À **06:48 UTC**, App Store Connect affiche
le build traité, **Prêt à soumettre**, sans informations de conformité
manquantes : le code approuvé est reconnu. À **07:04 UTC**, l'affectation au
groupe interne **Mehdi — test iPhone**, un testeur, est confirmée. L'installation
du build 9 reste à vérifier ; aucune soumission publique n'a été faite. La CI native du même
commit est verte : 109 tests unitaires et 17 tests UI réussis, un test Face ID
simulé ignoré comme prévu, zéro échec et build iPhone Release réussi.
Cette réception Apple et ces contrôles de paquet ne qualifient
pas le Bluetooth ou le changement de Wi-Fi sur le matériel réel.
Voir [la livraison du build 9](TESTFLIGHT-DELIVERY.md).

## Approbation Apple — 8 octobre 2026

Apple a approuvé les documents de chiffrement ; la déclaration approuvée est
associée au build **1.0.0 (8)**, désormais distribué au groupe TestFlight interne.
Le code fourni par App Store Connect est reporté dans `Info.plist` avec
`ITSAppUsesNonExemptEncryption=true` pour les prochains builds conservant ces
caractéristiques cryptographiques. Aucun algorithme ni paramètre TLS n'est
modifié par ce changement de métadonnées. Toute évolution du chiffrement doit
faire réexaminer la déclaration.

Cette approbation porte sur la conformité export. Elle ne constitue ni une
validation fonctionnelle du Bluetooth, ni une approbation publique App Review.
Voir [l'état de livraison](TESTFLIGHT-DELIVERY.md). Les sections suivantes
conservent les constats historiques, antérieurs à cette approbation.

## Préparation de 1.0.0 (6) — 1 octobre 2026

Le candidat source 6 conserve Mbed TLS 4.1.1, TF-PSA-Crypto 1.1.1 et la
configuration upstream du build script. Il utilise le questionnaire manuel
d'App Store Connect : `ITSAppUsesNonExemptEncryption` et
`ITSEncryptionExportComplianceCode` restent absents jusqu'à l'approbation des
documents. L'absence de ces clés ne déclare aucune exemption. Son export App Store est normal
(`testFlightInternalTestingOnly=false`), pour permettre une future réutilisation
publique ; cette option ne résout pas la conformité et ne distribue pas le build.
Les builds 4 et 5 restent internal-only, en informations manquantes dans le
constat App Store Connect du 1 octobre. Aucun document signé ni code
d'approbation n'est ajouté par cette préparation.

Une première tentative d'upload du build 6 avec
`ITSAppUsesNonExemptEncryption=true`, sans code approuvé, a été refusée le
1 octobre : **Invalid Export Compliance Code**, valeur `[]`. Apple documente
explicitement le questionnaire manuel en l'absence de la première clé et
demande son code approuvé avec la déclaration automatique. Le candidat est
reconstruit pour ce parcours manuel, avec les mêmes réponses techniques et
le même blocage documentaire avant distribution.
[Clé et questionnaire Apple](https://developer.apple.com/documentation/bundleresources/information-property-list/itsappusesnonexemptencryption),
[code d'approbation Apple](https://developer.apple.com/documentation/bundleresources/information-property-list/itsencryptionexportcompliancecode).

Depuis le build 5 (`80dfc37`), la validation de confiance et les wrappers TLS ont
changé. Un prototype de confiance au premier démarrage utilise un ALPN distinct
(`inky-bootstrap/1`) et accepte une date de certificat non valide uniquement
pour une feuille auto-signée vérifiée, EC P-256, conforme aux usages requis et
dont le pin SPKI correspond exactement au cadre attendu. Cette politique reste
séparée de la confiance normale, dont les usages de signature sont renforcés.
Le prototype ne possède aucun appel dans les parcours de l'app iOS ; le service
et le parcours de correction de l'horloge ne sont pas activés. Voir
[le périmètre du prototype](../inkyos/BOOTSTRAP-TLS-PROTOTYPE.md).

L'inventaire des primitives du build 5 reste une référence pour cette
configuration, mais son descriptif fonctionnel et ses hashes de binaire ne
doivent pas être attribués au build 6. Un nouveau hash d'archive/IPA et le commit
source doivent accompagner tout complément documentaire de ce candidat.
Les bancs macOS du 1 octobre passent : 15 tests InkyTLS, 13 tests du canal
applicatif GATT/TLS via pipes et 52 contrôles HTTPS/WSS loopback, sans échec ni
skip. Ces bancs ne qualifient pas la radio Bluetooth ou le changement Wi-Fi sur
un vrai iPhone et Raspberry.

## Historique du build 1.0.0 (4)

État au 27 septembre 2026 : le build **1.0.0 (4)**, issu de `70148f5`, a été
téléversé avec succès à **14:04:25 UTC** et son traitement Apple est terminé.
Il est marqué `testFlightInternalTestingOnly=true`, mais reste en
**Informations manquantes**, sans groupe de testeurs. Son questionnaire de
conformité exige des documents avec les réponses décrites ci-dessous.
L’upload du binaire a bien eu lieu ; aucun document de conformité ni déclaration
administrative n’a été envoyé. L’ancien build `1.0.0 (3)` n’intègre pas Mbed TLS.
Une demande de précision sur les justificatifs a été envoyée à Apple Developer
Support ; sa réception est confirmée. La question préalable ANSSI a également
été envoyée depuis le contact public choisi par Mehdi. Aucune réponse de fond
ni approbation n’est enregistrée à ce stade.
Voir [l'état des échanges](export/PREPARATION-FORMULAIRE.md#demandes-de-précision--état-du-27-septembre-2026).

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
retirée. Aucun numéro d’autorisation, dépôt ANSSI ou code d’approbation Apple
n’est inventé. La France reste dans le périmètre souhaité.

[Guide du questionnaire et des documents Apple](https://developer.apple.com/help/app-store-connect/manage-app-information/determine-and-upload-app-encryption-documentation).

## Constat App Store Connect pour ce build

Les deux parcours ci-dessous ont été consultés le 27 septembre 2026 puis
annulés sans enregistrer de déclaration ni joindre de fichier. Aucune démarche
ANSSI n’a été engagée.

### Documents au niveau de l’app

Dans **Informations sur l’app → Documents de chiffrement → Charger**, une
description de l’objectif technique, les algorithmes standard hors du système
Apple et la disponibilité en France (`Oui`) ont été renseignés. Le dialogue
a demandé le **« Formulaire français de
déclaration et demande d’autorisation d’opérations relatives à un moyen de
cryptologie »**. Le bouton **Enregistrer** est resté désactivé sans fichier.
Le parcours a été quitté avec **Annuler**.

### Questionnaire du build 4 dans TestFlight

Après traitement de l’upload, **Gérer** à côté de la conformité du build 4 a été
ouvert. Le parcours **algorithmes standard hors du système Apple → Suivant →
France : Oui** a affiché l’obligation de charger les documents de conformité
dans **Documents sur le chiffrement des apps**. Le message précise qu’après
approbation des documents, Apple fournira la valeur de clé à saisir dans Xcode.

Ce dialogue ne proposait aucun bouton **Enregistrer** ; il renvoyait vers la
page d’informations sur l’app. Il a été quitté avec **Annuler**. Le build 4
reste en **Informations manquantes**, sans groupe associé.

Preuve privée locale, consultée pour cette synthèse et non ajoutée au dépôt :
`build/ios/app-store-evidence/build4/apple-export-document-required.png`.

**Conséquence observée : pour notre build 4, y compris marqué Internal Only,
ce parcours avec France : Oui demande des documents et leur approbation Apple
avant de résoudre la conformité.** Ce blocage n’est plus une hypothèse tirée de
la seule documentation générale. Il n’établit pas à lui seul la qualification
juridique ANSSI du produit ou la pièce qu’Apple accepterait au titre d’une
éventuelle exemption.

## Documentation générale Apple et ANSSI

La recherche documentaire du 27 septembre 2026 avait laissé ouverte la réponse
du questionnaire d’une bêta interne. Le constat effectif ci-dessus tranche ce
point pour notre build, sans transformer les règles publiques en une affirmation
générale concernant tous les builds internes.

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
cas. Ces intitulés ne sont donc pas une base retenue pour déclarer une exemption.
Le questionnaire du build 4 a bien été consulté et demande les documents ;
l’existence et la recevabilité d’une exemption restent à établir séparément.

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
- La distribution TestFlight du **build 4** reste suspendue à la résolution de
  sa conformité : le parcours réel exige les documents puis leur approbation.
  Les réponses techniques retenues décrivent du chiffrement standard embarqué
  hors OS, TLS pour la configuration d’un cadre, sans VPN ni algorithme maison.
  Le mode `Internal Only` n’a pas levé cette exigence pour ce build.
- Pour la publication française, prévoir le parcours documentaire Apple ; si
  une exemption ANSSI s’applique, sa portée et le justificatif accepté par Apple
  restent à établir. Ni un reçu inexistant ni une classification ne sont fournis
  par cet inventaire. La consultation réelle du dialogue documentaire de l’app
  a confirmé la demande de fichier pour « France : Oui » ; elle a été annulée.
- Incertitudes restantes : applicabilité des exceptions au **produit logiciel
  complet** et aux opérations envisagées ; pièces qu’Apple accepterait pour une
  exemption française. Le résultat du questionnaire du build 4 est désormais
  connu. La question sur le justificatif a été envoyée à Apple et la demande
  préalable à l’ANSSI ; les deux réponses restent attendues.
  Aucune réponse de ces interlocuteurs n'est présumée.
- Un export de développement signé du build 4 est prêt ; le branchement d’un
  iPhone a été demandé pour la qualification sur appareil. Le backend Bluetooth `0.5.0-rc.2` a ensuite été déployé et vérifié sur le
  cadre de qualification ; aucun essai réel de changement Wi-Fi n’est déclaré
  réussi. Voir [le déploiement serveur](SERVER-BLUETOOTH-DELIVERY.md).

Aucun changement de disponibilité géographique enregistré, formulaire soumis, signature,
attestation d’exemption ou engagement au nom de Mehdi n’est réalisé ici.

### Éléments à préparer sans données personnelles

Cette liste est une préparation technique proposée, pas un formulaire officiel :

- Description courte du cadre photo, de l’app et du parcours de configuration ;
  guide utilisateur montrant les fonctions réellement accessibles.
- Version/hash du binaire concerné, versions et configurations exactes de Mbed TLS
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

Mehdi a confirmé être le déclarant en personne physique (rubrique A.2), avec
TestFlight personnel puis une publication publique envisagée. Il a fourni les
coordonnées nécessaires au préremplissage local le 27 septembre ; elles restent
hors du dépôt. Les formalités applicables, les pièces administratives encore
requises et une éventuelle référence de classement restent à vérifier avant
signature et dépôt. Les builds locaux, les bancs techniques et la PR
d’intégration peuvent avancer ; la distribution TestFlight du build 4 reste
dans l’état documentaire constaté ci-dessus.


## Artifacts préparatoires disponibles

[Annexe technique relue](export/ANNEXE-TECHNIQUE.md),
[inventaire de configuration du build 4](export/build4-crypto-configuration.json),
et [formulaire officiel, rubriques et pièces](export/PREPARATION-FORMULAIRE.md).
Le PDF de l’annexe est un brouillon local non signé, distinct du formulaire
officiel XFA dont une copie est désormais préremplie localement (49 valeurs).
Le rendu XFA reste à vérifier dans un lecteur compatible ; le compagnon statique
de relecture est inspecté. Les coordonnées et choix administratifs ne sont pas publiés.
Mehdi préfère TestFlight et les tests Simulator ; l’alternative d’installation
directe Xcode n’est pas poursuivie.
