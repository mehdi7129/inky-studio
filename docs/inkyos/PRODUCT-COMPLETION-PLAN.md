# Finalisation commune Inky Studio / InkyOS

État vérifié le 11 octobre 2026. Objectif : un ensemble cohérent, du premier
allumage sans réseau à la photo affichée, avec changement de Wi-Fi et reprise.
Ce document distingue le code existant, les raccords à développer et les preuves
sur matériel. Un build ou une fixture ne valide pas un parcours physique.

## Candidats et responsabilités

- Banc actuel InkyOS : backend `c31b13afdc957425571810c46230eaaf52fa5d14` ;
  iOS TestFlight 1.0.0 (9), source `181edb2f89034bb0c411b145c95fe303f112b460`.
- Nouvelle branche Studio `codex/frame-runtime-integration` : fusion Git réelle
  des branches iOS `52a5c64` et backend `c31b13a`, commit de réunion `daa1381`.
  Les protections de drain/erreurs écran coexistent avec le ledger factory, les
  primitives bootstrap et les sessions à durée monotonic. Ce n'est pas encore
  un nouveau payload installé ou un build TestFlight distribué.
- Studio possède backend, app iPhone, rendu, helpers et protocole applicatif.
  InkyOS possède image, services OS, SD, préflight et essai matériel. Aucun accès
  Pi/SD parallèle depuis Studio. La PR documentaire #22 reste séparée et ouverte.
- InkyOS corrige la préparation Bluetooth, l'inventaire `i2c-tools` et la lecture
  NTP avant le prochain essai applicatif. Le Wi-Fi et SSH observés sur le banc
  ne prouvent pas le parcours usine sans LAN.

## Lots et critères de sortie

| Lot | Code existant et travail concret | Critère de sortie |
|---|---|---|
| 1. État réel de l'écran | Le backend publie `/api/display/status` et `display_error`. Raccorder iOS, distinguer connexion et panne écran, conserver l'état incertain après timeout, bloquer les commandes jusqu'au retour confirmé. Adapter le QR aux petits panneaux. | Tests API/concurrence et UI clair/sombre, QR entier aux huit résolutions ; ensuite observation physique sur le panneau exact. |
| 2. Autorité d'initialisation | Reçu OS durable et `FirstBootCoordinator` déjà testés isolément. Implémenter client/serveur IPC-A avec UID kernel, schémas fermés et réponse de consommation à usage unique. | Vecteurs communs, refus app/helper/root inadmissibles, coupures de processus, réponse perdue, aucune recréation après consommation. |
| 3. Premier démarrage backend | Sélectionner explicitement le lifecycle factory avant les créations legacy ; credentials persistés, identité préparée, ledger et QR physique sous le seul propriétaire de l'écran. | Démarrage neuf sans horloge plausible ; ancien cadre et état perdu/corrompu ne deviennent jamais factory ; interruption à chaque écriture. |
| 4. Canal bootstrap et iPhone | Fixer QR/service GATT distincts et dispatcher strict ; utiliser le TLS bootstrap existant et un stockage Keychain typé, avec owner et IDs persistés avant mutation. | Vrais échanges Python/Mbed/Swift, refus mauvais profil/ALPN/pin/owner/epoch, double claim et reprise de réponse perdue. |
| 5. Heure, certificat et pays | Frontière système distincte, opération durable sans répétition d'un ancien timestamp, bornes UTC/NTP explicites, pays confirmé et état radio vérifié. | Même UUID/SPKI ; certificat normal renouvelé ; nouvelle connexion TLS stricte avant opérations réseau ; aucune association avant pays accepté. |
| 6. Premier Wi-Fi et photos | Réutiliser le journal Wi-Fi, checkpoint et confirmation HTTPS épinglée. Rendre le mot de passe photo initial disponible après disparition du QR ; Face ID reste optionnel. | Échec sans ancien réseau récupérable, owner conservé, premier upload et photo réellement affichée. DHCP ou association BLE seuls ne signifient pas réussite. |
| 7. Voyage et reprise | Changement de réseau, mauvais mot de passe/rollback, perte BLE, restart helper et reprise après reboot. | Essais sur SD dédiée avec voie de récupération éprouvée, état adopté conservé, aucun reset implicite. |
| 8. Livraison | Figer commit unique, dépendances, manifeste/hash et build iOS ; faire l'essai complet sur ce couple. | Nouveau TestFlight testé, PRs relues et autorisation de merge ; image InkyOS et instructions avancées cohérentes. |

## Ce qui fonctionne déjà dans le code

L'app gère Photos/caméra, HEIC/JPEG/PNG, orientation, cadrage aux dimensions du
panneau et sortie PNG sRGB sans métadonnées source privées. Le design Bento
arrondi, clair/sombre système et portrait restent les références.

L'entrée Bluetooth existe **avant le login**, pour un iPhone déjà associé.
Elle utilise encore le QR v1 `{v,id,k,t}` et le TLS normal ; ce n'est pas une
installation usine. `BootstrapFrameTrust` seul ne suffit pas : `OwnershipVault`
valide aussi un certificat normal, et `GATTTransport` construit aujourd'hui
`TLSPeer` en dur. Il faut des chemins explicitement distincts, sans fallback.

Le Wi-Fi existant comprend persistance de l'opération, reprise, annulation et
confirmation HTTPS. La cible actuelle est WPA2 Personal 2,4 GHz/IPv4. Réseaux
ouverts, entreprise et portails captifs d'hôtel ne sont pas implémentés. Le
partage de connexion compatible est le premier scénario de voyage à qualifier.

Le catalogue comporte 20 variantes de métadonnées. Le payload TEST existant
observe seulement l'AC073 avec `inky==2.3.0`. Le nouveau
[candidat 2.5.0](DISPLAY-DRIVER-250.md) ajoute des contrats distincts pour les
trois Spectra et les Impression AC073/UC8159, y compris le 5,7″ 600 × 448.
Les tests du vrai code driver utilisent des ports GPIO/SPI simulés ; chaque
panneau et nouvelle fermeture native restent à qualifier physiquement. Un QR
non tronqué dans une image ne prouve pas sa lecture caméra.

## Invariants à garder pendant l'intégration

- Une autorité OS consommée ne peut pas être reconstituée depuis un fichier
  applicatif, un dossier vide, un nombre d'owners nul ou une panne Wi-Fi.
- Seul `newly_consumed` issu du véritable appel begin courant permet de créer
  le ledger. `already_consumed` permet seulement sa réouverture cohérente.
- Claim avant réglage de l'heure ; même clé/UUID après réparation. Aucun mot de
  passe Wi-Fi/photo dans le canal bootstrap. Reconnexion TLS normale stricte
  avant pays/Wi-Fi et confirmation HTTPS distincte.
- L'heure du téléphone est une assertion d'un owner autorisé, pas une source UTC
  indépendante. Le journal doit empêcher la réapplication d'un ancien timestamp.
- Le pays est choisi selon le lieu d'utilisation, jamais déduit de la langue,
  du fuseau ou de la nationalité. NetworkManager peut démarrer avec la radio
  fermée ; bloquer tout le daemon créerait un cycle avec le helper.
- Un seul propriétaire SPI. L'arrêt ferme l'admission et termine le refresh et
  sa persistance ; timeout UI ne signifie pas arrêt physique. Pas de SIGKILL ou
  coupure pendant le drain, et pas de second refresh pendant celui-ci.

## Matrice commune E2E

| Cas | Preuve logicielle attendue | Preuve physique restante |
|---|---|---|
| Cadre neuf, aucun LAN, RTC invalide | Autorité → identité/credentials → QR → claim → heure → TLS strict → pays → Wi-Fi → login photo | QR lisible sur le panneau, scan iPhone, photo affichée |
| Deux téléphones / réponse claim perdue | Un seul premier owner, retry du gagnant avec IDs persistés | Reconnexion iPhone et absence de seconde adoption |
| Certificat expiré ou horloge future | Réparation owner autorisé sous même clé puis handshake strict | Cadre resté hors réseau puis récupération |
| Pays absent/refusé/différent | Aucun scan/association et erreur stable | Domaine réglementaire effectif sur la radio cible |
| Premier Wi-Fi erroné | Même owner, pas de faux « ancien réseau restauré », nouvel essai possible | Réseau compatible puis HTTPS et upload |
| Wi-Fi changé / confirmation absente | Transaction durable, rollback, pas de confirmation via BLE | Vrai changement et retour au réseau précédent |
| Timeout/panne écran | Pas de faux succès ni consommation de file/historique ; diagnostic distinct de la connexion | Refresh réel, lisibilité et comportement du signal busy |
| Arrêt pendant accueil/QR/photo | Admission fermée, drain, pas de nouveau propriétaire SPI | Service réellement `inactive/dead` avant arrêt du Pi |
| Reboot/perte de fichiers | Owner/identité conservés ou recovery explicite ; jamais nouvelle factory | Reboot produit, distinct des admissions uniques de la SD TEST |

Références : [premier boot](FIRST-BOOT-CONTRACT.md),
[coordinator](FIRST-BOOT-COORDINATOR.md),
[TLS bootstrap](BOOTSTRAP-TLS-PROTOTYPE.md),
[candidat matériel et drain](HARDWARE-CANDIDATE.md),
[protocole BLE v1](../ios/BLE-PROTOCOL-V1.md).
