# Tester Inky Studio sans cadre

État au **9 octobre 2026** : le build **1.0.0 (9)** est distribué au groupe
TestFlight interne. Mehdi indique que l'app fonctionne bien, sans écran connecté
actuellement. Ce retour positif ne précise pas le build installé et ne valide
pas automatiquement tous les parcours ci-dessous.

## À noter avant le test

Dans TestFlight, relever la version et le numéro de build installés, puis le
modèle d'iPhone et la version d'iOS. Pour chaque étape, noter **OK**, **à corriger**
ou **non testé**. Un problème est plus facile à reproduire avec les étapes,
le résultat attendu et une capture sans données personnelles.

Entrer dans **Explorer la démo** depuis l'écran de connexion. Aucun Raspberry,
réseau local ni mot de passe n'est nécessaire. Les exemples sont générés par
l'app ; les changements restent dans la session de démonstration.

## À tester maintenant

- [ ] **Accueil et aide** : trouver « Explorer la démo », lire « Préparer mon
  cadre » et ouvrir les liens Support/Confidentialité. Les liens web nécessitent
  internet ; la démo elle-même fonctionne hors ligne.
- [ ] **Quatre onglets** : parcourir Cadre, File, Historique et Réglages ; essayer
  les actions de démonstration. Vérifier les libellés, les messages et le retour
  vers l'écran précédent, sans zone vide ni nom de fichier inutile.
- [ ] **Présentation** : passer le système en clair puis sombre, augmenter la
  taille du texte dans les réglages d'accessibilité et activer Réduire les
  animations. Vérifier les cartes Bento arrondies, les boutons et textes lisibles,
  le défilement et le maintien en portrait.
- [ ] **Image et cadrage** : utiliser d'abord une image d'exemple, puis une photo
  choisie si souhaité. Recadrer, zoomer, réinitialiser, annuler puis ajouter à la
  démo. Vérifier l'aperçu, la file et l'historique avec une image identifiable.
- [ ] **Réglages et session** : modifier/enregistrer un réglage de la démo,
  quitter puis rouvrir l'écran, mettre l'app en arrière-plan puis revenir.
  Réinitialiser la démo et la quitter ; vérifier que la connexion réelle est de
  nouveau proposée. Fermer complètement l'app termine la session de démo.
- [ ] **Caméra sur l'iPhone** : si disponible, prendre une photo en mode démo,
  vérifier le cadrage, puis essayer l'annulation. Noter séparément le refus
  d'autorisation et sa récupération dans Réglages si ces cas sont testés.
  Le Simulator ne qualifie pas la caméra physique.
- [ ] **VoiceOver sur l'iPhone** : écouter les noms et états des boutons, parcourir
  les quatre onglets, ouvrir/fermer une fenêtre et vérifier que le focus reste
  compréhensible. Les tests automatiques de libellés ne remplacent pas cette
  écoute réelle ; noter les gestes de cadrage ou de réorganisation non validés.

La démo simule l'affichage, la file et les réglages. Elle ne reproduit ni les
couleurs ni le délai d'un écran e-ink, et ne lance pas le planning automatique.
Face ID, Bluetooth, changement de mot de passe et mise à jour réelle n'y sont
pas disponibles. Voir [le fonctionnement et l'isolation de la démo](DEMO-AND-ONBOARDING.md).

## À reprendre avec le Raspberry et l'écran

- [ ] **Connexion réelle** : permission réseau local, adresse, bon/mauvais mot
  de passe, reconnexion et personnalisation du mot de passe. Le retour positif
  antérieur sur le mot de passe reste acquis, sans couvrir les autres cas.
- [ ] **Face ID** : activation, authentification réelle, annulation et retour au
  mot de passe, puis désactivation. Ne pas réinitialiser Face ID pour ce test.
- [ ] **Adoption QR et Bluetooth** : premier appairage sur le réseau local,
  identité du cadre et accès Bluetooth depuis le téléphone déjà adopté.
- [ ] **Wi-Fi** : mauvais mot de passe avec retour au réseau initial, puis
  réseau de secours 2,4 GHz autorisé et confirmation HTTPS. Consigner séparément
  le succès confirmé et le rollback ; garder un moyen de récupérer le cadre.
- [ ] **Photo et écran** : photo réelle/HEIC, cadrage aux dimensions détectées,
  envoi, rafraîchissement physique, couleurs et absence de commandes doublées.
- [ ] **État partagé et reprise** : file/historique et réglages concordants avec
  l'interface web, planning réel, arrière-plan et coupure/reprise du réseau.

Le [plan de qualification](APP-STORE-PLAN.md) détaille ces parcours et les limites
Wi-Fi. Aucun test en démo ne permet de les marquer réussis.

## Travail qui peut continuer sans matériel

Les régressions automatisées, la revue des textes et de l'accessibilité, les
captures et la préparation des informations App Store peuvent avancer. Pour les
captures locales, utiliser uniquement le **Simulator iPhone 15 Pro Max déjà
présent** ; vérifier les formats acceptés dans le gestionnaire officiel Apple
avant de déclarer le jeu de captures complet.

Le build 9 possède déjà une validation CI et des preuves d'archive/distribution :
[livraison TestFlight](TESTFLIGHT-DELIVERY.md) et
[revue de stabilité](reviews/2026-10-08-stability/README.md). Une nouvelle suite
complète n'est utile que si une modification ou un problème le justifie.

App Store Connect a été revérifié **en lecture seule le 9 octobre 2026 vers
09:10 UTC** : textes et notes démo remplis, déclaration « Données non collectées »
publiée, huit captures existantes, prix de **0 EUR** et disponibilité future en
**France uniquement**. La fiche reste à finaliser, avec publication manuelle et
ancien build 7 attaché ; le jeu de captures reste à vérifier avec le futur
candidat qualifié. Aucun champ Apple n'a été modifié. Le
[plan de publication](APP-STORE-PLAN.md) détaille ce relevé.

La fusion des PR, la soumission App Review et la publication publique restent
séparées de ces tests et de cette préparation.
