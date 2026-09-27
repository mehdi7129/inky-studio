# Formulaire ANSSI pour Inky Studio — préparation non signée

Recherche primaire du 27 septembre 2026. Aucun contact externe, envoi ou signature.
Les coordonnées fournies ensuite par Mehdi servent uniquement au brouillon local
privé ; elles ne sont pas reproduites dans ce document ni dans Git. L’[annexe technique](ANNEXE-TECHNIQUE.md) et l’[inventaire de configuration](build4-crypto-configuration.json)
sont préparés séparément ; ce mémo fournit le formulaire, les rubriques
administratives et leur correspondance avec cette annexe.

## Document officiel récupéré et méthode de lecture

- [Page ANSSI des formulaires](https://cyber.gouv.fr/reglementation/reglementation-identite-confiance-numerique/controles-reglementaires-cryptographie/controle-moyen-de-cryptologie/controle-reglementaire-cryptographie-formulaires/).
- [Téléchargement officiel : déclaration et demande d’autorisation d’opérations relatives à un moyen de cryptologie, annexe I v2](https://cyber.gouv.fr/documents/330/crypto_declaration-demande_autorisation_operations_annexe1_v2.pdf).
- Format vérifié : PDF 1.7, **XFA dynamique**, 2 308 710 octets, non chiffré,
  contenant du JavaScript. Original non modifié conservé dans
  `/tmp/inky-encryption-official/annexe1-v2.pdf`.
- SHA-256 : `149cf1324cc144c5891b085ed0ace5e8b90888bba61db7a4faf5822ee7ebf8e7`.

Le téléchargement officiel redirige vers un hébergement CloudGouv signé et
temporaire : conserver le lien ANSSI ci-dessus, pas l’URL de redirection.
Le téléchargement a réussi en ajoutant `?download=1` au lien ANSSI.

Poppler rend seulement une page invitant à utiliser un lecteur PDF compatible
(le PDF cite Adobe Reader). Les rubriques, valeurs par défaut et aides intégrées
ont été lues dans les données XML XFA, **sans exécuter le JavaScript**. Ce n’est
pas une validation visuelle d’un formulaire rempli. Le modèle original doit être
ouvert avec un lecteur prenant en charge XFA pour le remplissage final.

La [FAQ ANSSI](https://cyber.gouv.fr/reglementation/reglementation-identite-confiance-numerique/controles-reglementaires-cryptographie/controle-moyen-de-cryptologie/faq-demande-dautorisation/)
demande de consulter la notice explicative. La page des formulaires consultée ne
propose qu’un téléchargement : ce PDF, qui contient des aides contextuelles.
Ces aides ont été lues ; aucun lien officiel distinct vers une notice autonome
n’a été identifié dans les pages consultées. Leur extraction textuelle locale est
dans les artifacts privés de préparation ; le formulaire original reste la référence.

## Rubriques à compléter ou à réserver au titulaire

Correspondance extraite de l’annexe I officielle ; ce tableau n’est pas un
formulaire soumis ni une sélection juridique effectuée.

| Rubrique | Données demandées / préparation possible |
|---|---|
| Première page : opération | Déclaration seule, autorisation seule, renouvellement, ou combinaison déclaration + autorisation. **La combinaison est cochée par défaut dans le modèle** (`CB_DeclDemaAuto`). Ne pas interpréter ce défaut comme le choix applicable au projet. |
| A.1 : personne morale | Dénomination, SIRET, nationalité, adresse, téléphone ; interlocuteur administratif avec identité et coordonnées. À utiliser seulement si le déclarant est effectivement une société/association/autre personne morale. |
| A.2 : personne physique | Le formulaire prévoit explicitement le **particulier** : civilité, nom/prénoms, nationalité, adresse complète, téléphone, courriel. Aucun SIRET n’est demandé dans cette rubrique. Ne rien extraire d’autres comptes ou documents pour la remplir. |
| Contact technique | Identité, adresse, téléphone et courriel de la personne pouvant répondre sur le moyen. À confirmer par le titulaire ; ce rôle n’est pas attribué à un agent IA. |
| B.1 : produit final | Nom du moyen, marque, référence, version, date de mise sur le marché ; fabricant et dénomination d’origine si le déclarant n’est pas le fabricant. L’aide impose le **produit final**, pas seulement sa bibliothèque cryptographique. Nom technique disponible : Inky Studio ; version concernée : iOS 1.0.0 (4). Périmètre exact et date de mise sur le marché à confirmer, sans assimiler automatiquement date d’upload et commercialisation. |
| B.2 : fonction | Nature matériel/logiciel, description générale, puis catégorie de la fonction principale. La liste distingue sécurité de l’information, ordinateur, envoi/stockage/réception d’informations, réseau, autres. Décrire réellement l’app photo et sa configuration du cadre ; ne pas choisir « autres » pour présumer une exemption. |
| B.3 : cryptographie | Description, fonctions, protocoles, puis tableau algorithme/mode/taille maximale de clé/fonction. L’annexe technique préparée séparément alimentera ces champs. |
| C : grand public | Case et justification sur commercialisation/marché, difficulté de modification de la cryptographie par l’utilisateur, et installation sans assistance importante ultérieure. Réservé à la qualification retenue par le titulaire ; ce n’est pas une case automatiquement vraie parce que l’app est personnelle. |
| D : renouvellement | Références et date d’une autorisation existante, seulement si cette situation existe. Aucun numéro à inventer. |
| E : pièces | Présentation de société, Kbis récent ou équivalent étranger, brochure commerciale, brochure technique, manuels utilisateur/administrateur lorsqu’ils existent. Le modèle contient A.2 pour le particulier mais ne précise pas dans E comment adapter les pièces de société à ce cas : indiquer le statut réel et faire préciser les pièces inapplicables, sans créer de faux Kbis. |
| F : attestation | Nom/prénoms, qualité, entité représentée, date et signature de la personne habilitée. **À laisser vierge dans le brouillon** ; il s’agit d’un engagement sur l’exactitude et le suivi des informations. |

Pour brancher l’annexe technique au PDF : `T_B22Description` (description
fonctionnelle), `T_B31Description` (description cryptographique), cases B.3.2
(authentification/intégrité/confidentialité/signature), `CB_B33SSL` (SSL/TLS),
puis lignes répétables `T_B34Algo`, `T_B34Mode`, `T_B34Taille`, `T_B34Fonction`.
Ne renseigner les fonctions réellement exercées qu’après revue de l’annexe.

Le formulaire distingue aussi des éléments détaillés **à communiquer sur demande**
de l’ANSSI : exemplaires/installation/activation, protection de l’implémentation,
traitement des données, sorties de référence, code source et recompilation,
composants et mémoires. Ce ne sont pas tous des envois spontanés exigés par la
rubrique E. Aucune clé réelle, secret Wi-Fi ou donnée utilisateur n’est collecté
dans la préparation ; d’éventuels exemples techniques doivent rester synthétiques.

## Conditions et limites établies

L’ANSSI distingue l’utilisation libre en France des opérations de fourniture,
importation ou exportation qui relèvent de formalités sauf exception. Le régime
dépend du produit et des opérations ; ce n’est pas un classement déterminé par
le seul usage de TLS. [ANSSI : contrôle du moyen](https://cyber.gouv.fr/reglementation/reglementation-identite-confiance-numerique/controles-reglementaires-cryptographie/controle-moyen-de-cryptologie/).

La liste indicative ANSSI mentionne des exceptions pour Bluetooth, certains
équipements de configuration et l’usage personnel. Elle ne désigne pas
explicitement une app photo iOS intégrant TLS applicatif sur GATT ; aucune
exemption exacte de ce produit n’a donc été établie par cette recherche. Le
classement grand public est soumis à validation ANSSI. Les cases juridiques de
la première page et de C restent réservées au titulaire et à la qualification
retenue. [ANSSI : contrôle export et exceptions](https://cyber.gouv.fr/reglementation/reglementation-identite-confiance-numerique/controles-reglementaires-cryptographie/controle-export/).

Pour notre build 4, le parcours Apple réel avec standard hors OS et France `Oui`
demande déjà des documents ; ce fait est consigné dans
`docs/ios/ENCRYPTION-INVENTORY.md`. Il ne prouve pas qu’Apple accepte un simple
PDF non signé, ni qu’un dossier préparé équivaut à une attestation ANSSI.
Le traitement Apple est distinct : dépôt dans Documents sur le chiffrement,
review au cas par cas, puis code de conformité après approbation.
[Procédure Apple](https://developer.apple.com/help/app-store-connect/manage-app-information/determine-and-upload-app-encryption-documentation).

## Informations confirmées et rubriques personnelles restantes

1. Déclarant confirmé par Mehdi : **Mehdi Guiard, personne physique**, rubrique
   A.2. Aucune société ni SIRET déclarés. Les coordonnées fournies par le titulaire
   ont été préremplies dans une copie locale privée. Aucun justificatif
   nominatif ni coordonnée personnelle n’est conservé dans le dépôt.
2. Périmètre déjà demandé par Mehdi : usage personnel puis TestFlight, avant
   publication publique de l’app. La France est conservée. L’annexe décrit
   l’app iOS finale et son backend associé ; la date de publication publique
   reste indéterminée. Ces faits ne choisissent pas à eux seuls le régime applicable.
3. Dispose-t-il déjà d’une déclaration/autorisation concernant ce **produit
   complet** ? Sinon, laisser les références vides. Une éventuelle référence
   Mbed TLS seule ne remplace pas la désignation du produit final.

Le titulaire doit relire les données préremplies, compléter les rubriques
administratives encore réservées, choisir les formalités appropriées et valider
C s’il demande ce classement. Les coordonnées restent dans les fichiers privés.

La copie du formulaire est préremplie par mise à jour incrémentale de ses données
XFA : original et template conservés, champs relus structurellement, aucun script
PDF exécuté. Le rendu XFA et les droits Reader ne sont pas vérifiés ; un compagnon
PDF statique inspecté visuellement permet de relire les valeurs. Il ne remplace
pas le formulaire officiel. La formalité « Combiné » était précochée dans
l’original ; elle n’est pas confirmée par le préremplissage. Aucune attestation
signée ni soumission ne résulte de cette préparation.

## Pièces et procédure, sans exécution

Préparation utile maintenant : original officiel intact, correspondance B.1-B.3
avec l’annexe technique, présentation fonctionnelle de l’app et guides existants,
liste des pièces administratives applicables selon A.1/A.2. Le brouillon peut
être techniquement préparé tout en réservant les choix juridiques et l’attestation
au titulaire.

La page ANSSI décrit un éventuel dépôt électronique à son bureau de contrôle,
avec formulaire électronique sauvegardé, exemplaire signé numérisé et pièces
documentaires (`.pdf`, `.xls`, `.doc`), sujet identifié par marque/produit. C’est
une description de la procédure, **pas un envoi effectué ni autorisé ici**.
La FAQ cite notamment un Kbis de moins de trois mois pour les sociétés et les
brochures/guides. [Formulaires et modalités](https://cyber.gouv.fr/reglementation/reglementation-identite-confiance-numerique/controles-reglementaires-cryptographie/controle-moyen-de-cryptologie/controle-reglementaire-cryptographie-formulaires/),
[FAQ pièces du dossier](https://cyber.gouv.fr/reglementation/reglementation-identite-confiance-numerique/controles-reglementaires-cryptographie/controle-moyen-de-cryptologie/faq-demande-dautorisation/).

Point encore ouvert : nature précise du justificatif qu’Apple acceptera pour
ce dossier et, si le titulaire est un particulier, adaptation de la liste E.
Aucune garantie de déblocage Apple n’est attachée au seul brouillon.
