# Candidat driver Inky 2.5.0

Lot source séparé du 12 octobre 2026, basé sur la PR #33. Cette migration
prépare les trois Spectra et les Impression 7 couleurs, dont le 5,7″ UC8159.
Elle ne modifie pas le payload TEST `c31b13a`, le build iOS 9 ni le bundle
immuable `a071f19`. Aucun panneau, EEPROM, GPIO, réseau, service ou SD n'est
modifié par les tests de ce lot.

## Driver et identité

Le pin [des extras Pi](../../server/pyproject.toml) devient `inky==2.5.0`,
distribution officielle, sans fork ni patch redistribué. Le commit du tag
officiel `v2.5.0` est
`29e1af86db54dad8c997db544fc5deb3b047d779` ; le wheel `py3-none-any` a pour SHA-256
`8589ad753b094ec5da482c090f88d5e8560457f15502221517993dc01b021573`.
[Release Pimoroni](https://github.com/pimoroni/inky/releases/tag/v2.5.0),
[artefact PyPI](https://pypi.org/project/inky/2.5.0/).

| Famille | Module du driver | Variante EEPROM | Dimensions | Couleurs |
|---|---|---|---|---|
| Spectra 4″ | `inky.inky_e640` | 25 | 600 × 400 | 6 |
| Spectra 7,3″ | `inky.inky_e673` | 22, 26 AC | 800 × 480 | 6 |
| Spectra 13,3″ | `inky.inky_el133uf1` | 21, 27 AC | 1600 × 1200 | 6 |
| Impression 7,3″ | `inky.inky_ac073tc1a` | 20 | 800 × 480 | 7 |
| Impression 5,7″ | `inky.inky_uc8159` | 14 | 600 × 448 | 7 |
| Impression 4″ classique | `inky.inky_uc8159` | 15, 16 | 640 × 400 | 7 |

La sélection utilise toujours le véritable `inky.auto`, avec résolution
explicite issue de sa table EEPROM. Studio vérifie module, dimensions et pin ;
les champs EEPROM sont conservés dans les diagnostics. Le gate strict sur leur
type entier et leur tuple concerne l'AC073 ; les autres familles suivent la
sélection upstream et ne disposent pas de ce gate supplémentaire. Une taille
seule ne distingue pas les familles. Le
profil existant `ac073-800x480` reste nécessaire pour la couleur EEPROM brute 4
non interprétée du banc AC073. Aucun nouveau profil, override ou écriture EEPROM.
[Table de sélection 2.5.0](https://github.com/pimoroni/inky/blob/v2.5.0/inky/auto.py),
[EEPROM 2.5.0](https://github.com/pimoroni/inky/blob/v2.5.0/inky/eeprom.py).

Les autres variantes de métadonnées déjà reconnues restent présentes ; elles
ne reçoivent pas par analogie les nouveaux contrats BUSY.

## Pourquoi 2.5.0

Le Spectra 13,3″ utilise BUSY actif LOW pendant le refresh. La
[PR officielle #265](https://github.com/pimoroni/inky/pull/265), postérieure à
2.4.0 et incluse dans 2.5.0, corrige l'attente avant POF. Un simple passage à
2.4.0 aurait conservé cette erreur. L'attente corrigée emploie une deadline
monotonic et suit LOW puis HIGH.

2.5.0 change aussi l'attente GPIO AC073/UC8159 et la commande de bordure AC073.
Ce sont des changements à requalifier, pas une mise à jour interchangeable avec
2.3.0. Les palettes, dimensions et signatures publiques des familles ciblées
restent celles du driver officiel.
[Comparaison upstream](https://github.com/pimoroni/inky/compare/v2.4.0...v2.5.0).

## Observation BUSY par famille

Les hooks temporaires sont propres à l'instance et restaurés même en cas
d'échec. Les fonctions originales sont exécutées avec leurs budgets et clocks ;
aucun patch global, reset supplémentaire, deuxième refresh ou arrêt forcé du
thread GPIO n'est ajouté. Le verrou du contrôleur garde l'owner pendant l'appel
et les drains existants restent inchangés.

| Driver | Phases / budgets upstream en secondes | Observation du refresh |
|---|---|---|
| AC073 | setup 1 ; power-on 0,4 ; refresh 45 ; power-off 0,4 | Événement RISING_EDGE sur la ligne BUSY renvoyé par `gpiodevice.wait_for_edge` |
| UC8159, deux formats | setup 1 ; power-on 0,2 ; refresh 32 ; power-off 0,2 | Même API d'événement, contrat et budgets UC8159 distincts |
| E640 | setup 0,3 ; power-on 0,3 ; refresh 40 ; power-off 0,3 | Lectures LOW puis HIGH par l'attente originale |
| E673 | setup 0,3 ; power-on 0,3 ; refresh 32 ; power-off 0,3 ; standby PSR 0,3 | Lectures LOW puis HIGH par l'attente originale |
| EL133UF1 | setup 0,3 ; power-on 0,2 ; refresh 65 ; power-off 0,2 | LOW observé puis HIGH dans `_refresh_wait` |

Un niveau initial HIGH avec simple délai ne prouve pas le refresh. Une réponse
absente, une mauvaise phase, une autre ligne/type d'événement ou un timeout ne
permet pas d'acquitter la photo. L'erreur reste latched, la file et l'historique
restent inchangés ; la reprise exige vérification opérateur et redémarrage.

**Exception EL133UF1 :** l'upstream avertit puis retourne même après un timeout.
Studio laisse terminer `_refresh_wait`, puis refuse de continuer vers POF si la
transition LOW→HIGH n'est pas prouvée. Cela évite la coupure d'alimentation en
milieu de refresh qui motive #265. Le chemin nominal conserve ses commandes.
Aucune attente n'est annulée, aucun POF de secours ou nettoyage GPIO n'est ajouté.
La fin de l'attente ou du thread après timeout n'est pas la fin physique du
refresh : son état reste inconnu. Les autres familles gardent le verdict après
leur séquence originale.

Les événements renvoyés par `gpiodevice` peuvent être déjà en file : leur type et
ligne ne prouvent pas leur fraîcheur par rapport à la commande ni les pixels du
panneau. E640 utilise encore l'horloge murale upstream ; un saut d'heure peut
modifier son délai. Ces limites font partie de la qualification native et
physique restante, sans être masquées par un succès de fixture.
[Drivers officiels](https://github.com/pimoroni/inky/tree/v2.5.0/inky),
[contrat du helper GPIO 0.1.0](https://github.com/pimoroni/gpiodevice-python/blob/v0.1.0/gpiodevice/watch.py).

## Couleurs et tests du code réel

Studio transmet du RGB à `set_image`, sans palette locale ni image `P`
préquantifiée. Les indices Spectra 0–5 deviennent les codes matériels
`[0, 1, 2, 3, 5, 6]` ; les sept couleurs AC073/UC8159 ont un ordre distinct.
Les rotations internes E640 et la séparation des buffers EL133UF1 appartiennent
au driver. Le nominal n'est pas réimplémenté par Studio.

Les tests chargent les modules complets du wheel officiel vérifié SHA-256 et
RECORD, avec NumPy/Pillow réels. Les ports GPIO/SPI/I²C sont doublés. Les tests
de packing interceptent `_update` pour examiner les buffers produits par le
véritable `show` : ils ne déroulent pas ensuite les commandes SPI. Le
cache de test est préparé avant pytest avec une requirement hashée ; pytest ne
télécharge rien et ce cache ne constitue pas un payload Pi. Autodétection,
EEPROM, RGB/palettes, résolution, buffer et contrats d'attente doivent être
vérifiés sans remplacer `inky.auto` par un driver fabriqué.

La matrice API teste upload PNG, stockage et acquittement mock aux six couples
dimensions/couleurs (cinq tailles distinctes).
Le test iOS applique l'orientation EXIF avant cadrage et exporte un vrai PNG
sRGB aux cinq dimensions distinctes. Le test web enregistre la géométrie canvas
et vérifie qu'un crop portrait/paysage couvre le panneau ; il ne qualifie pas
un encodeur PNG de navigateur. Les rendus accueil/QR utilisent les dimensions
existantes. Aucun composant Bento, flow ASGI, endpoint ou champ obligatoire du
protocole n'est modifié.

## Frontière de livraison

Le wheel Inky est Python pur ; cela ne qualifie pas NumPy, Pillow, spidev,
gpiod ou leurs dépendances ELF pour CPython 3.13 Linux ARM64. `gpiodevice>=0.1.0`
utilise gpiod v2 ; toute la fermeture doit être figée avec versions, hashes,
architecture et libc. La provenance ARM64 2.3.0 existante reste historique et
incompatible avec ce nouveau pin. La validation de fermeture doit refuser sa
réutilisation pour ces sources.

Ordre de livraison coordonné avec InkyOS :

1. Revue indépendante du nouveau code et tests source/driver complets.
2. Nouveau manifeste, fermeture native, vérification support/ELF et bundle
   immuable construit depuis le commit accepté ; jamais réécrire `a071f19`.
3. Graphe installé inactif : UID applicatif, PID1/peer, admission watcher et drain
   des opérations, sans accès concurrent Studio aux médias ou au Pi.
4. Sur chaque panneau exact : refreshs successifs, photo/couleurs/bordure/rotation,
   accueil/QR lisible, erreur BUSY, arrêt/reboot et parcours iPhone.
5. Image active et release uniquement après ces preuves et validation humaine.

Une CI verte ou la présence d'un wheel ARM64 ne remplace aucune de ces preuves.
