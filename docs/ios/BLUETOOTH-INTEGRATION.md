# C2 — intégration Bluetooth et configuration Wi-Fi

État au 27 septembre 2026 : implémentation sur `codex/bluetooth-wifi-setup`,
**qualification matérielle encore ouverte**. Le cadre de Mehdi reste en
`0.5.0-rc.1`, et TestFlight reste en `1.0.0 (3)`. Aucun changement de son réseau,
de ses photos ou de son mot de passe personnalisé pendant le développement.
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

## Installation à qualifier sur Raspberry

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
  physique. Radio rétablie éteinte/bloquée après essai, service photo actif.
- Aucun test réel de changement Wi-Fi, de rollback NetworkManager ou de coupure
  électrique n’est encore déclaré réussi. Le helper n’est pas installé en production.

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

Un nouveau numéro de build, la qualification matérielle et la déclaration export
précèdent la prochaine distribution TestFlight. La sortie publique et InkyOS
restent des lots ultérieurs.
