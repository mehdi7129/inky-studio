# Factory runtime guard — raccord inactif

Ce raccord sélectionne explicitement le premier démarrage InkyOS avant toute
création legacy. Il ne fournit pas encore un premier démarrage utilisable : même
après une préparation réussie, le processus s'arrête avec le statut **78**,
`factory_runtime_pending`, avant les listeners, le SPI et l'affichage du QR.
Ne pas l'activer dans une image utilisateur tant que le canal bootstrap complet
n'est pas intégré et qualifié.

## Sélection convenue avec InkyOS

Le 11 octobre 2026, les sessions Studio et InkyOS ont fixé le contrat suivant :

- L'unité OS fixe `INKY_STUDIO_FACTORY_REQUIRED=1` et
  `INKY_STUDIO_DATA_DIR=/var/lib/inky-studio` pour l'utilisateur d'UID **1000**.
- Le marker permanent est `/etc/inky-studio/factory-v1.json`, fichier ordinaire
  `root:root`, mode `0644`, lien unique, sous des parents root non modifiables
  par les autres utilisateurs. Aucun composant ne peut être un lien symbolique.
- Son JSON fermé est exactement :

```json
{"version":1,"app_uid":1000,"data_dir":"/var/lib/inky-studio"}
```

La configuration ne fournit aucun chemin de socket, UID alternatif ou méthode
de contournement. L'authentification de l'application doit rester activée.

| Configuration observée | Résultat |
|---|---|
| Flag absent, marker absent, aucune trace factory | Démarrage legacy inchangé |
| Flag présent mais invalide | Refus avant toute création |
| Mode requis, marker absent, invalide ou non sûr | Refus, aucun fallback legacy |
| Marker présent sans le flag requis | Refus de configuration |
| Traces factory alors que le mode requis n'est plus configuré | Refus de downgrade |
| Mode requis et prérequis locaux cohérents | Coordinator + IPC-A, puis arrêt explicite |

Le marker sélectionne le lifecycle. Il n'est **pas** l'autorité positive
consommable détenue par le service root InkyOS, ni une preuve de première
installation. La présence de données factory sert seulement à interdire un
retour implicite vers le chemin legacy. Le journal DELETE d’une base legacy v1
reste à son gestionnaire habituel ; la sélection ne le rejoue ni ne le supprime.
Elle ne peut pas reconstituer une preuve d’installation si l’administrateur
supprime simultanément la configuration OS et toutes les traces applicatives.
Le flag fixé par l’unité OS évite le fallback lorsque seul le marker disparaît.

## Préconditions et ordre

1. Résoudre le dossier de données sans créer de répertoire, puis vérifier la
   sélection OS, ses permissions et la concordance du dossier/UID.
2. Lire des credentials **v2 déjà persistés**, privés et propres à ce cadre,
   avant tout `begin`. Refuser un fichier absent, corrompu, legacy, lié ou de
   permissions inadéquates. Ne jamais appeler le loader qui crée ou migre les
   credentials dans ce parcours.
3. Appeler `FirstBootCoordinator` avec le véritable
   `InitializationIPCClient`. Le callback credentials relit le fichier et son
   epoch lors des vérifications successives ; aucun grant n'est mis en cache.
4. Conserver les garanties du coordinator : seule la réponse du `begin`
   courant `newly_consumed` peut créer le ledger ; `already_consumed` exige une
   réouverture cohérente. Une consommation dont la réponse a été perdue
   n'autorise pas la recréation d'un ledger manquant.
5. Après succès, arrêter explicitement ce raccord de développement. Aucun
   transfert du ledger factory au constructeur `OwnershipStore` legacy.

Le démarrage HTTP/HTTPS et l'entrée ASGI directe sont protégés. Les commandes
locales `welcome`, `password` et `reset-password` refusent le mode factory sans
appeler IPC-A, avant l'écran, une rotation de mot de passe ou une opération
réseau. Leur parcours factory futur reste à implémenter.

## Responsabilités de l'image OS avant activation future

- Créer et persister **une fois par appareil** ses credentials individuels par
  un hook explicitement autorisé, distinct de ce raccord. Aucun mot de passe,
  salt, hash ou secret individuel commun ne doit être embarqué dans l'image.
- Définir séparément la création durable de l'autorité d'initialisation root
  et sa reprise après coupure. Un marker, un receipt absent ou des fichiers
  applicatifs vides n'accordent jamais cette autorité.
- Vérifier la readiness effective d'IPC-A et ses identités Unix avant le
  lancement. Un ordre systemd `After=` seul ne prouve pas qu'il répond.
- Éviter une boucle sur le statut 78 de ce raccord incomplet : `Restart=always`
  et le `Restart=on-failure` de l'installateur courant le relanceraient tous deux.
  La recette courante et les upgrades ordinaires n'installent ni flag ni marker.
- Terminer le canal bootstrap, l'adoption, l'heure, le certificat normal, le
  pays et le Wi-Fi avant toute activation dans une image utilisateur.

Studio ne modifie ici aucune unité OS, autorité root, image, carte SD ou cadre.
Les tests portables avec UID/chemins injectés ne prouvent pas les droits du
vrai service Linux ni le résultat matériel.

## Liens

- [Contrat IPC-A](INITIALIZATION-IPC-V1.md)
- [Plan produit et limites de qualification](PRODUCT-COMPLETION-PLAN.md)
- [Coordinator](../../server/inky_web/provisioning/first_boot.py)
- [Client IPC-A](../../server/inky_web/provisioning/initialization_ipc.py)
