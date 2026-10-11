# Lifecycle de la phase A — candidat inactif

## Statut

Ce lot prépare la composition de la première association : coordinator existant,
écran QR, transport Bluetooth bootstrap, claim durable et arrêt drainé.
Il n'ajoute aucun caller installé. `initialize_factory()` reste synchrone,
`NoReturn` et terminal par `factory_runtime_pending` (78). Les chemins console,
HTTP, HTTPS et ASGI actuels ne démarrent pas cette session.

Le parcours TEST backend `c31b13afdc957425571810c46230eaaf52fa5d14` / iOS build 9
reste distinct. Aucun payload SD, artifact `a071f19`, build TestFlight ou écran
iOS n'est remplacé par ce candidat. Le style Bento reste inchangé.

## Composition préparée

`serve_factory_phase_a()` est une API async injectée, sans nouveau flag, rôle,
endpoint, opération wire ou marqueur de readiness. Le caller fournit l'événement
d'arrêt et les factories d'écran et de runtime. La composition future utilise
`BootstrapRuntime` et `serve_prepared_factory` existants sur l'event loop console.
Il ne faut pas exécuter le runtime dans un second `asyncio.run()` d'un worker.

Le candidat doit valider le contexte hérité, puis posséder sa propre SH main
jusqu'à la fin de ses workers et de ses ressources. Les callbacks d'epoch
revalident la lease, le selector et les credentials persistés. Une configuration
ou un `FirstBootResult` ne remplace jamais l'admission OS.
L'epoch est figé pour cette session : une rotation de credentials provoque un
refus, sans réinitialiser le ledger ou l'identité préparée.

Ordre de la session :

1. Valider l'admission main et le selector factory courant.
2. Si l'arrêt est déjà demandé, ne pas appeler le coordinator.
3. Préparer une seule fois dans un worker possédé et drainé : le coordinator
   effectue ses propres opérations IPC courantes, distinctes de la sonde PR31.
4. Si l'arrêt arrive pendant cette préparation, attendre sa fin sans lancer
   l'écran ou la radio. Fermer le store préparé sous la lease.
5. Initialiser le contrôleur d'écran, exiger sa disponibilité, puis démarrer
   le runtime injecté. Le runtime existant pousse le QR avant l'advertising.
6. Fermer l'admission au STOP, drainer les opérations admises et le runtime,
   fermer le store et arrêter le contrôleur avant de libérer la SH.
7. Terminer sans jamais reprendre le lifecycle normal. Une fin propre reste
   terminale (78) ; une cancellation n'est propagée qu'après le drainage.

Le candidat ne crée ni DB photo, identité TLS normale, listener HTTP/HTTPS,
scheduler, ni client helper Wi-Fi. Il ne publie aucune preuve d'admission OS.

## Fin de la phase A

Un claim réussi donne `ADOPTED` et `next_step: system_setup`.
Cela prouve uniquement l'association durable. Heure, pays, Wi-Fi, publication de
l'identité normale et photos restent hors de ce lot. Un redémarrage adopté doit
conserver le même owner et présenter le statut d'attente, sans nouveau QR.
Une identité normale déjà publiée est refusée par ce runtime bootstrap.

Les quatre preuves restent distinctes : notification systemd IPC `READY=1`,
observation IPC `authorized|consumed`, ledger applicatif `FACTORY|ADOPTED`,
et admission du superviseur `/run/inkyos-admission/Ready` :

- `READY=1` constate le démarrage du service IPC, sans lire l'autorité courante.
- `inspect` observe un receipt authentifié, sans autoriser une création de ledger.
- Le ledger établit l'état applicatif, sans prouver l'admission OS ou radio.
- `Ready` du superviseur établit son admission, sans être une réponse IPC courante.

Aucune de ces valeurs ne devient un grant réutilisable en mémoire.

## Gate OS avant activation installée

InkyOS ne fournit pas encore de gate public helper + graphe IPC consommable.
La SH main et la sonde PR31 ne prouvent pas ce graphe. Le raccord installé reste
donc fermé ; aucun marqueur ou booléen applicatif de substitution n'est inventé.

La composition devra fournir et qualifier :

- Une API d'admission OS root protégée et épinglée, couvrant les vrais writers
  main/helper/ipc et le contexte du superviseur jusqu'à leur drainage.
- Le marker factory, les UIDs, les credentials privés v2 persistés et le receipt
  root distinct. Le coordinator ne crée ou ne migre pas le mot de passe.
- Le service IPC au socket fixe avec peer UID 0, caller Studio UID 1000,
  helper et root refusés comme clients, réponse complète suivie d'EOF et deadline
  existante ; `Wants/After` ne suffit pas.
- Les permissions D-Bus/BlueZ/hci0 et un propriétaire unique du panneau SPI.
- Une politique d'arrêt et de restart qui ne tue pas les opérations physiques
  admises et ne boucle pas sur le statut 78.
- De nouveaux pins et receipts pour les nouveaux octets sélectionnés. La
  qualification d'anciens artifacts n'est pas transférée à cette composition.

Les tests injectés qualifient le code et ses frontières d'ownership, avec des
identités/services OS synthétiques. Ils ne prouvent pas le graphe Linux installé,
le scan iPhone, l'enregistrement BlueZ réel ou l'affichage physique du QR.
Le ledger et ses commits sont réels ; la barrière de test SQLite est placée avant
le claim, sans prétendre bloquer une transaction interne. Les délais de refresh
SPI et d'enregistrement radio sont simulés par les adapters injectés.

## Références

- [Guard runtime et refus du démarrage incomplet](FACTORY-RUNTIME-GUARD.md).
- [Writer guards et limites de composition](FACTORY-WRITER-GUARDS.md).
- [Observation IPC indépendante](FACTORY-IPC-OBSERVATION.md).
- [Contrat wire QR/Bluetooth et séparation des phases](BOOTSTRAP-WIRE-PROPOSAL.md).
- [Runner async injecté de la phase A](../../server/inky_web/provisioning/factory_phase_a.py).
- [Lifecycle injecté de l'association](../../server/inky_web/provisioning/factory_session.py).
- [Runtime bootstrap existant](../../server/inky_web/provisioning/bootstrap_runtime.py).
