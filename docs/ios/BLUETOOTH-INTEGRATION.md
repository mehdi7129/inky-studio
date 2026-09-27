# C2 — intégration Bluetooth et configuration Wi-Fi

État au 27 septembre 2026 : le candidat **`0.5.0-rc.2`**, source `ae61df1`,
est déployé sur le cadre ; **la qualification iPhone et Wi-Fi réelle reste
ouverte**. Voir [le compte-rendu de déploiement](SERVER-BLUETOOTH-DELIVERY.md).
La bêta disponible reste `1.0.0 (3)` ; le build `1.0.0 (4)`
a été traité par Apple en mode interne uniquement, mais sa distribution attend
les documents de chiffrement demandés dans le questionnaire du build. Aucun
nouveau réseau n'a été configuré par cette opération. Le chemin des données et
le mot de passe personnalisé ont été conservés ; l'opérateur n'a ni lu ni
restauré le contenu du répertoire de données.
Le changement de mot de passe et le rejet de l’ancien/du mauvais mot de passe
ont été confirmés par Mehdi avant ce lot.

## Parcours implémenté

1. Sur le réseau habituel, un utilisateur connecté ouvre l’adoption depuis les
   réglages. Le cadre affiche un QR temporaire pendant dix minutes. Le scheduler
   réserve l’écran ; l’API ne renvoie jamais le secret du QR.
2. L’iPhone scanne ce QR physique, découvre le cadre et contrôle l’empreinte de
   sa clé avant d’envoyer un secret. TLS 1.3 protège les commandes sur GATT.
3. L’autorisation du téléphone est conservée dans son Keychain et dans une base
   de vérificateurs côté cadre. Lors d’un déplacement, cette autorisation permet
   d’ouvrir le parcours Bluetooth depuis l’écran de connexion, sans Wi-Fi commun.
4. L’utilisateur choisit un réseau WPA2 personnel en 2,4 GHz et saisit son mot
   de passe dans l’app. Le cadre tente la connexion pendant 180 secondes.
5. L’iPhone rejoint ce même réseau et confirme en HTTPS avec la clé du cadre
   déjà adoptée. Le profil est alors enregistré durablement. Sans confirmation,
   ou après annulation/interruption, le helper revient vers l’ancien profil.

Le SSID et l’identifiant d’un essai en cours permettent sa reprise ; le mot de
passe Wi-Fi n’est pas conservé sur l’iPhone ni dans le journal de transaction.
Le profil NetworkManager validé conserve naturellement le secret nécessaire à
sa reconnexion. L’autorisation Bluetooth est distincte du mot de passe app/SSH.
Changer le mot de passe révoque les autres téléphones et annule un essai Wi-Fi
en cours avant d’enregistrer le nouveau secret. Oublier le cadre localement ne
constitue pas une révocation côté Raspberry.

## Séparation des privilèges

Le backend conserve son utilisateur habituel et un seul propriétaire de l’écran.
HTTP `8000` reste disponible aux clients existants ; HTTPS `8443` partage le même
lifespan, les sessions, le scheduler et l’identité TLS utilisée en Bluetooth.
Un cadre adopté sur iPhone utilise HTTPS sans repli HTTP.

`scripts/inky-network-helper.py` est indépendant du backend, chargé par le Python
système en mode isolé. Le service `inky-network` reçoit quatre permissions
NetworkManager explicites, accessibles uniquement à son compte dédié. Son socket
local accepte un protocole borné et des opérations fixes, aucune commande shell.
Le compte existant de l’app rejoint le groupe `inky-provisioning` pour permettre
aussi à sa CLI de récupération d’annuler un essai avant de réinitialiser le mot
de passe. Ce groupe ne reçoit aucune permission NetworkManager directe.
Il ne modifie que `wlan0` et ses propres profils Inky.

L’essai crée un checkpoint NetworkManager et un profil mémoire sans autoconnect.
La confirmation sauvegarde le profil, réactive la connexion sans liaison au
client D-Bus puis détruit le checkpoint. Les états intermédiaires sont journalisés
avant mutation. Un redémarrage traite tout essai incomplet comme une annulation ;
un identifiant de checkpoint d’une ancienne instance NetworkManager n’est jamais
réutilisé. Les tests simulent aussi les coupures pendant la finalisation.

## Installation et qualification sur Raspberry

Le helper et le backend candidat sont maintenant installés sur le cadre de
Mehdi. Les instructions ci-dessous décrivent les prérequis pour une autre
installation ; elles ne constituent pas une qualification universelle.

Prérequis : NetworkManager, BlueZ, `python3-dbus`, utilisateur du service identifié,
accès local de secours et version de backend correspondant à ce protocole.
Depuis un checkout/release vérifié :

```sh
sudo bash scripts/install-bluetooth.sh pi
```

Le script installe le helper root-owned, les unités et la règle polkit limitée,
active la radio et ajoute `INKY_STUDIO_BLUETOOTH=1` au service app. Il ne redémarre
pas l’app et ne lance aucun changement Wi-Fi. Reconnecter SSH pour prendre en
compte le nouveau groupe avant d’utiliser la CLI de récupération. Celle-ci refuse
de changer le mot de passe si un essai Wi-Fi ne peut pas être annulé avec certitude.
Installer ensuite le backend qualifié
et redémarrer le service avec son mécanisme de déploiement habituel. Ne pas ajouter
de règle sudo générale au compte de l’app. Pour désactiver l’intégration, retirer
le drop-in `inky-studio.service.d/bluetooth.conf`, recharger systemd et redémarrer
l’app ; conserver l’identité et l’ownership pour un prochain rétablissement.

Avant d’arrêter le helper, annuler tout essai Wi-Fi et vérifier `rolled_back` ou
`committed`. Son journal et son watchdog servent à récupérer une interruption,
ils ne remplacent pas un accès de secours lors de la première qualification.

## Preuves et limites

- Build propre de Mbed TLS 4.1.1 pour cinq architectures Apple ; archive officielle
  contrôlée par SHA-256. Les notices sont incluses dans le bundle app.
- Tests TLS, transport GATT en mémoire, QR, trust, ownership, révocation,
  lifecycle et transactions simulées exécutés ; résultats finaux dans la PR.
- Parcours Simulator avec réseaux synthétiques, saisie, attente et annulation.
  Ces fixtures DEBUG n’ouvrent aucune radio et n’écrivent aucun propriétaire.
- Le banc radio sécurisé Mac ↔ Pi passe : deux échanges de 600 octets, refus
  d’un pin incorrect avant écriture applicative, reconnexion avec un nouveau TLS.
  Le test a révélé une MTU encore à 20 octets lors de `didConnect`, puis à 182
  après découverte ; le client consulte maintenant la limite courante.
  L’empreinte de ce banc arrive par SSH connu ; cela ne valide pas le scan du QR
  physique. À la fin de ce banc initial, la radio avait été rétablie
  éteinte/bloquée ; l'installation ultérieure du helper l'a activée.
- Le helper a ensuite été installé sur le Pi par Mehdi. Service actif sous
  `inky-network`, code root-owned `0555`, socket de groupe `0660`,
  `NoNewPrivileges=yes` et `health` protocole 1 vérifiés. Le scan réel renvoie
  un réseau WPA2 ; les noms des réseaux ne sont pas conservés dans les preuves.
- Le backend candidat `9351ae8` a été qualifié séparément dans un environnement
  isolé sur le Pi : [11 contrôles PASS](reviews/2026-09-27-bluetooth/pi-backend.json).
  BlueZ réel, HTTP/HTTPS sur loopback, auth/session commune, TLS 1.3,
  claim et statut owner via un flux GATT en mémoire, lifecycle et QR mock.
  Zéro appel SPI ; le vrai helper ne reçoit que `health`, ses mutations sont
  bloquées et le scan Wi-Fi est ignoré dans ce banc. Les données temporaires
  ont été supprimées ; le service photo et le helper étaient restés actifs.
  Cela complète la preuve radio Mac ↔ Pi, sans valider l’adoption QR physique
  ni le changement de réseau.
- Le déploiement final de `ae61df1` en `0.5.0-rc.2` a passé son préflight et son
  postflight : HTTP depuis le Mac, HTTP/HTTPS local TLS 1.3, authentification
  requise et driver détecté. L'enregistrement Bluetooth est corroboré par le
  bus du PID courant, un nouvel UUID Inky dans les propriétés publiques BlueZ
  et une hausse d'`ActiveInstances`. Cette corrélation locale ne prouve pas un
  échange radio iPhone ni le scan du QR. Le helper reste actif.
- Les CI backend et iOS de `ae61df1` sont vertes. Le script privé de bascule
  passe 26 tests de défauts sur Linux. Son premier essai réel a restauré le code
  précédent après un refus D-Bus du vérificateur ; le contrôle corrigé utilise
  les propriétés publiques, sans changer les permissions. La bascule finale
  réussit. Voir [détails et limites](SERVER-BLUETOOTH-DELIVERY.md).
- Aucun test physique d'adoption iPhone, de changement Wi-Fi, de rollback
  NetworkManager ou de coupure électrique n’est encore déclaré réussi.

Test matériel suivant : adoption sur iPhone, essai avec mauvais mot de passe,
retour au réseau initial, puis transfert vers un partage de connexion **2,4 GHz**
(choix confirmé par Mehdi) et confirmation HTTPS. Tester aussi fermeture de l’app,
perte de BLE, reboot Pi et mot de passe changé depuis un autre client. Aucun mot
de passe Wi-Fi ne doit être envoyé dans le chat ou dans les preuves publiées.

Non inclus : portails captifs d’hôtel, WPA Enterprise, réseaux ouverts, 5 GHz,
accès Internet distant aux photos, récupération sans propriétaire ni réseau,
image InkyOS ou premier boot d’un nouveau cadre. Un premier propriétaire doit
actuellement pouvoir demander son QR depuis une session réseau authentifiée.

## Distribution iOS

L’ajout de Mbed TLS change l’inventaire cryptographique par rapport au build 3,
qui utilisait seulement le chiffrement système Apple. L’ancienne valeur
`ITSAppUsesNonExemptEncryption=false` est retirée ; le questionnaire App Store
Connect doit être renseigné pour le nouveau build. Aucune réponse d’exemption
n’est supposée. Voir [ENCRYPTION-INVENTORY.md](ENCRYPTION-INVENTORY.md).

La prochaine **bêta interne de qualification** peut précisément servir aux tests
iPhone et Wi-Fi encore ouverts. Leur réussite complète ne précède donc pas
nécessairement cette bêta. Le build 4 est déjà téléversé ; sa distribution demande
de résoudre le contrôle export avec les réponses exactes et les documents
effectivement demandés. Le questionnaire du build
interne avec algorithmes standard hors OS et France `Oui` exige bien des documents
approuvés par Apple. Un brouillon privé du formulaire comporte 49 champs
préremplis ; son rendu XFA n'est pas vérifié. Un compagnon de relecture de cinq
pages a été contrôlé visuellement. Ces documents ne sont ni signés ni soumis et
ne valent pas approbation Apple. Une version
de développement signée existe, mais Mehdi préfère poursuivre via TestFlight
et les tests Simulator ; aucune installation directe sur son iPhone n’est prévue.

Le merge final et la release publique attendent la fermeture des critères
matériels, notamment adoption iPhone et commit/rollback NetworkManager réel.
La PR reste draft pendant cette qualification ; la bêta interne peut la précéder.
La sortie publique nécessite également son parcours de conformité et de review.
InkyOS reste un lot ultérieur. Voir [la livraison TestFlight](TESTFLIGHT-DELIVERY.md)
pour distinguer upload, conformité et disponibilité effective.

Préparation historique sur le Pi : `/home/pi/inky-upgrades/bluetooth-c2-9351ae8/`
contenait les scripts installés et une copie du backend pour qualification isolée.
Son venv ne partageait pas les packages système (`pip check` passé). Les extras
Pi ont ensuite été installés en conservant les versions de la chaîne e-ink
alors en production. Le banc isolé a repassé ses 11 contrôles avec ces
packages présents, toujours sans initialiser le SPI. Cet arbre partiel ne
constitue pas une installation complète de remplacement. Le numéro interne `0.5.0rc1` de cette copie n’en fait pas une release :
la source testée est le commit de PR `9351ae8`. Le déploiement actuel utilise
l'arbre complet `/home/pi/inky-candidates/bluetooth-rc2-ae61df1`, atteint par le
lien `/home/pi/inky-studio` ; cet ancien arbre de qualification n'est pas la
production.
