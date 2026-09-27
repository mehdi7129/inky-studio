# Validation de la mise à jour iPhone — 27 septembre 2026

## État de livraison

La mise à jour respecte la correction de direction demandée par Mehdi : **conserver
le Bento arrondi de l’app précédente**, ajouter les fonctions validées et supprimer
les noms techniques des photos. Les planches Bento 2 définissent les fonctions et
les thèmes ; leurs formes plus carrées ne remplacent pas le style précédent.

Le candidat iPhone **1.0.0 (3)**, source **`9bd24bd`**, a été archivé en Release
avec signature, exporté pour App Store Connect et **uploadé avec succès à
11:24:45 UTC**. Apple affiche **Terminé** et le build est affecté au groupe interne
**Mehdi — test iPhone** (un testeur), avec les notes françaises enregistrées. L’archive est conservée dans
`build/ios/archives/InkyStudio-1.0.0-3.xcarchive`.
La disponibilité dans le groupe TestFlight est vérifiée côté App Store Connect.
Mehdi a validé l’étape de recette iPhone le 27 septembre (« je valide le 1 »).
Cette acceptation utilisateur ne constitue pas un relevé instrumenté de chaque
scénario physique. La PR #8 est fusionnée (`b31046d`) ; aucune publication publique
App Store n’a été effectuée.

Le backend de personnalisation du mot de passe a ensuite été qualifié et déployé
sur le Raspberry en **v0.5.0-rc.1**, après migration du lanceur. Le secret initial
fonctionne toujours ; voir [les preuves de livraison](../SERVER-CANDIDATE-DELIVERY.md).
Le banc Bluetooth C1 a échangé des données réelles entre le Mac et le Pi ;
la configuration Wi-Fi Bluetooth C2 **n’est pas implémentée**.

## Changements livrés dans les sources

| Demande | Réalisation et limites |
|---|---|
| Style précédent | Quatre onglets conservés. Rayons existants : cartes 20 pt, photos 12 pt, boutons 14/12 pt. Pas de remplacement par les cartes plus carrées des nouvelles planches. |
| Noms de photos | Supprimés de Cadre, File et Historique. Les labels VoiceOver utilisent le contexte, l’ordre ou la date, sans nom de fichier technique. Les fichiers restent identifiés techniquement dans les échanges avec le serveur. |
| Vide supérieur | Titres natifs compacts explicites à la place des grands titres dont le rendu était absent sur iOS 27. Aucune compensation par un offset propre à un appareil. Cela remplace le chemin de rendu défaillant sans affirmer qu’un modifier précis était sa cause. |
| Bas de Cadre | Marge de défilement supplémentaire avant la tab bar. Les commandes restent accessibles par défilement ; il n’est pas requis que tout tienne dans un écran avec de grands caractères. |
| File | Poignée trompeuse supprimée hors édition ; réordonnancement et actions de déplacement conservés. |
| Clair/sombre | Couleurs sémantiques adaptatives, suppression du mode clair forcé et des apparences UIKit fixes. L’app suit le système. |
| Icône A | Nouvelle icône de cadre simplifiée et lisible, intégrée au candidat. Son rendu final sur l’écran d’accueil d’un iPhone physique reste à vérifier. |
| Portrait | Orientation portrait seule dans le projet/plist ; contrôle automatisé du maintien en portrait. La capture native sur appareil réel reste à qualifier. |
| Appareil photo | Choix Photothèque/Appareil photo, permission et états de refus/indisponibilité, puis traitement et cadrage communs. Les parcours Simulator sont testés ; aucune capture réelle par le capteur d’un iPhone n’est revendiquée. |
| Mot de passe du cadre | Parcours iPhone et contrat serveur de rotation, capacité annoncée par le serveur, mise à jour de l’accès local/Face ID et révocation côté backend. Un serveur ancien ne doit pas être présenté comme capable de changer le mot de passe. Il ne s’agit pas du mot de passe Linux/SSH ou Wi-Fi. |
| Bluetooth | Banc C1 temporaire, avec protocole de diagnostic et données synthétiques. Aucune configuration réseau, association de propriétaire ou transmission de secret. |

Les cartes de Cadre, leurs commandes et les lignes photo s’adaptent verticalement
aux tailles de texte d’accessibilité. Les boutons acceptent des labels multilignes.
Ce travail n’est pas présenté comme un audit exhaustif Dynamic Type ou VoiceOver.

## Vérifications réalisées

Les résultats suivants concernent les suites et configurations réellement
exécutées. Les essais séparés ne sont pas additionnés artificiellement en une
unique exécution complète.

| Vérification | Résultat observé |
|---|---|
| Unit tests iOS 18.5 | **46 PASS**, aucun échec. |
| UI tests iOS 18.5, clair | **8 tests réussis** dans le premier lot. Le parcours caméra a ensuite été corrigé et son **rerun ciblé est passé**. |
| UI tests iOS 18.5, sombre | **3 PASS** dans le sous-ensemble exécuté ; cela ne constitue pas une exécution sombre exhaustive de tous les parcours. |
| UI tests iOS 27, suite complète | **9/10 PASS**, notamment le parcours Face ID simulé. Le test des quatre onglets a été perturbé par un reset concurrent de la fixture provoqué par le smoke API. |
| UI iOS 27, rerun quatre onglets clair | **PASS**, exécution isolée en **49,892 s**. Quatre captures produites, copiées et examinées. |
| UI iOS 27, quatre onglets sombre et portrait | **PASS**, **49,969 s**. Quatre captures sombres produites, copiées et examinées. |
| Smoke API | **45 checks PASS** sur une fixture indépendante, port 8767, incluant annonce de capacité et rotation du mot de passe. |
| Archive iPhone Release signée | **PASS**, version 1.0.0, build 3. |
| Export App Store Connect | **PASS**. |
| Upload build 3 | **PASS**, **11:24:45 UTC**. Traitement Apple terminé et affectation au groupe interne vérifiés dans App Store Connect. |
| Backend Python 3.13 | **180 PASS**, puis assertion ciblée supplémentaire sur l’absence de secrets dans les logs réussie. |
| Backend Python 3.11 | **178 PASS** avant les derniers changements de permissions des images d’accueil, puis **31 tests ciblés affectés PASS**. La suite complète de 178 tests n’est pas présentée comme relancée après ces derniers changements. |
| Framing du banc BLE | **4 PASS** : fragmentation, répétition, rejet de frames invalides et expiration. |
| Mac ↔ Pi BLE réel | **PASS**, découverte, connexion, version, echo, fragmentation, répétition, déconnexion/reconnexion et relecture. |

L’échec initial du test quatre onglets sous iOS 27 n’est pas imputé à un défaut
de navigation démontré : le smoke API a réinitialisé le serveur de fixture pendant
l’exécution UI. La correction de méthode consiste à laisser la fixture exclusivement
au test UI pendant son rerun. Ce rerun isolé est passé. Xcode est resté bloqué pendant la collecte des diagnostics
de l’exécution initiale et a été interrompu après la fin des dix tests ; les bundles
des reruns réussis sont complets. Le smoke utilise désormais
une autre instance, sur le port 8767.

Face ID dans le Simulator exerce le parcours de l’app et du Keychain de test.
Il ne remplace pas l’essai du capteur biométrique physique.

## Backend : sécurité et coût sur le Pi

Le détail du contrat HTTP, du stockage, de la migration et des erreurs est dans
[PASSWORD-ROTATION.md](../PASSWORD-ROTATION.md). Les tests couvrent notamment la
migration des anciens credentials, le stockage privé, les échecs d’écriture,
la concurrence login/rotation et la révocation des sessions/WebSockets.

Sur le Pi Zero 2 W réel, trois appels **synthétiques** à scrypt ont donné une
médiane de **492,160 ms** et une hausse de mémoire maximale du processus d’environ
**32,19 MiB**. Ce benchmark n’a utilisé aucun secret du cadre. Il mesure la primitive
cryptographique ; ce n’est pas une mesure de latence HTTP ou de rotation de bout
en bout. Le coût cryptographique d’une rotation est estimé à environ 0,98 s
pour la vérification puis le nouveau hash, hors autres traitements.

**Déploiement réalisé ensuite** : procédure contrôlée et mise à jour du lanceur
effectuées avant migration des credentials, avec preuve de connexion conservée.
Le CLI installé par v0.4.2 n’est pas remplacé automatiquement par l’updater actuel.
Les prérequis et la procédure de récupération sont explicités dans le document
de rotation. Aucun changement du mot de passe réel de Mehdi n’a été effectué.

## Bluetooth : preuve réelle et frontière C1/C2

Le [rapport de banc Bluetooth](../BLUETOOTH-BENCH.md) conserve les scripts,
les logs non sensibles, les versions système et les contrôles après nettoyage.

| Échange réel | Mesure |
|---|---|
| Echo 36 octets | 3 écritures acquittées, 3 notifications, **391 ms** |
| Echo 600 octets fragmentés | 51 écritures avec répétition identique, 50 notifications, **3 957 ms** |
| Echo après déconnexion/reconnexion | 25 octets, **211 ms**, puis relecture exacte du dernier fragment |

Ces mesures correspondent à des frames volontairement limitées à 20 octets et
à des notifications espacées. Elles ne mesurent pas le débit maximal du Bluetooth.
Le protocole echo **n’authentifie pas** la propriété du cadre et ne doit recevoir
aucun mot de passe ou token d’adoption.

Après le test : processus temporaire arrêté, dossier `/tmp` du Pi supprimé,
Bluetooth remis dans son état initial éteint/bloqué logiciellement, aucun
advertising actif. Le Wi-Fi est inchangé et l’API Inky répond `ok`, version
`0.4.2`. Aucune dépendance globale, unité systemd ou configuration réseau n’a été
installée par ce banc.

C2 reste à construire : adoption authentifiée, identité durable, transport protégé,
client iPhone, helper NetworkManager limité, bascule réseau et rollback. La présence
des APIs de checkpoint a été vérifiée, mais **aucun changement de réseau ni rollback
réel n’a été exécuté**. InkyOS reste une phase ultérieure.

## Captures et protection des données

Les captures de validation doivent provenir uniquement de la **fixture synthétique**,
avec ses images générées et ses comptes de test. Aucune photo personnelle, aucun
mot de passe réel, SSID privé ou credential du Raspberry ne doit être ajouté aux
preuves versionnées.

Le dossier est `./2026-09-27-refinement/`, relatif à ce rapport. Les **huit captures
claires/sombres iOS 27** ont été produites, copiées et examinées après les tests
isolés réussis. Deux captures supplémentaires documentent le refus de permission
caméra et le succès du changement de mot de passe sur fixture :

| Vue | Capture ou emplacement prévu |
|---|---|
| Cadre clair, iOS 27 | [Capture vérifiée](2026-09-27-refinement/01-cadre-light-ios27.png) |
| File claire, iOS 27 | [Capture vérifiée](2026-09-27-refinement/02-file-light-ios27.png) |
| Historique clair, iOS 27 | [Capture vérifiée](2026-09-27-refinement/03-historique-light-ios27.png) |
| Réglages clairs, iOS 27 | [Capture vérifiée](2026-09-27-refinement/04-reglages-light-ios27.png) |
| Cadre sombre, iOS 27 | [Capture vérifiée](2026-09-27-refinement/01-cadre-dark-ios27.png) |
| File sombre, iOS 27 | [Capture vérifiée](2026-09-27-refinement/02-file-dark-ios27.png) |
| Historique sombre, iOS 27 | [Capture vérifiée](2026-09-27-refinement/03-historique-dark-ios27.png) |
| Réglages sombres, iOS 27 | [Capture vérifiée](2026-09-27-refinement/04-reglages-dark-ios27.png) |
| Permission caméra refusée, iOS 18.5 | [Capture vérifiée](2026-09-27-refinement/09-camera-permission-ios18.png) |
| Changement de mot de passe, fixture | [Capture vérifiée](2026-09-27-refinement/10-password-ios27.png) |

Les captures originales de l’audit précédent restent accessibles dans
[l’audit du défaut visuel](2026-09-27-ux-audit.md). Les visuels générés de design ne
doivent pas être présentés comme des captures de l’app exécutée.

## Validation restant à terminer

1. Installer le build 3 depuis TestFlight sur l’iPhone.
2. Sur iPhone physique : capture réelle, orientation, refus/reprise de permission,
   cadrage, upload, Face ID réel et icône sur l’écran d’accueil.
3. Déployer séparément le backend après la procédure prévue, puis vérifier la
   rotation réelle et l’accès depuis un autre client, sans modifier un secret
   utilisateur comme simple effet de bord d’un test.

Références : [plan d’évolution](../PRODUCT-EVOLUTION-PLAN.md),
[distribution](../DISTRIBUTION.md), [bêta précédente](../TESTFLIGHT-DELIVERY.md),
[rotation du mot de passe](../PASSWORD-ROTATION.md) et
[banc Bluetooth](../BLUETOOTH-BENCH.md).
