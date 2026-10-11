# Admission injectée de la phase A — candidat inactif

Ce raccord prolonge le [lifecycle de la phase A](FACTORY-PHASE-A-LIFECYCLE.md).
Il ne fournit ni gate OS installé, ni nouveau caller console. `initialize_factory()`
reste terminal par `factory_runtime_pending` (78). Les octets TEST `c31b13a` /
iOS build 9 et le bundle `a071f19` ne sont pas remplacés. Aucun flag iOS,
payload QR, protocole wire ou design Bento ne change.

## API de composition

```python
async def serve_factory_phase_a(
    data_directory: Path,
    *,
    stop_requested: asyncio.Event,
    display_factory: Callable[[], DisplayController],
    runtime_factory: Callable[
        [FirstBootResult, DisplayController, Callable[[], str]],
        FactorySessionRuntime,
    ],
    admission_check: Callable[[], None],
    initialization_peer_guard: ConnectedPeerGuard,
) -> NoReturn: ...
```

Les deux hooks sont obligatoires et directement transmis. `admission_check()`
doit revenir exactement avec `None` ou lever une exception. `False`, `True`,
une string ou un objet ne constituent jamais une autorisation. Le callback doit
être réentrant, utilisable depuis la loop et les workers, et disposer lui-même
des preuves OS dont il est responsable ; aucun `ContextVar` applicatif ne sert
de cache d'admission.

Le runner valide le contexte de son caller, crée une tâche dans un `Context()`
neuf, puis détient sa propre SH main jusqu'à la fin de tous ses drains. Ses
callbacks et ceux du coordinator/store effectuent :

1. Check OS courant et vérification de la lease main.
2. Lecture et validation des vrais credentials persistés.
3. Nouveau check OS et vérification de la lease.
4. Retour de l'epoch canonique courant `str`, inchangé.

Le callback `verify_epoch` du runner compare en plus cet epoch à celui du début
de session. Le callback credentials conservé par le coordinator/store relit
l'epoch courant ; il n'effectue pas lui-même cette comparaison de session.

`prepare_factory(config, *, admission_check=None,
initialization_peer_guard=None)` conserve son comportement legacy lorsque les
deux hooks sont absents. En composition injectée, ils doivent être fournis
ensemble et être callables. Le callback de credentials reste attaché au store
et accompagne les appels `to_thread` ; il ne devient pas un snapshot booléen.

Le coordinator injecté revalide l'admission et les credentials juste avant
`begin`, après la préparation de l'identité. Après un `begin` IPC éventuellement
consommé, il les revalide avant de créer ou rouvrir le store. Un refus après `begin`
reste `uncertain` : aucun nouveau ledger, aucun reset, aucun retry automatique
du `begin`. Le chemin legacy garde son ordre existant.

## Preuve du peer réellement connecté

```python
ConnectedPeerGuard = Callable[
    [ConnectedSocket], AbstractContextManager[None]
]

InitializationIPCClient(*, peer_guard=None)
NetworkClient(path=None, *, peer_guard=None)
```

`ConnectedSocket` expose `fileno()` et `getsockopt()` ; il s'agit du vrai socket
déjà connecté. Dans le client IPC, le check existant `SO_PEERCRED` UID root
précède le hook. Dans le client helper async, le hook reçoit le `TransportSocket`
du `StreamWriter`. La preuve d'une connexion d'observation séparée ne suffit pas.

Le context manager doit entrer avant le premier send/write et revenir exactement
avec `None`. Il possède la preuve acquise à l'entrée jusqu'à EOF, validation de
la réponse et fermeture du socket/writer. Son exit peut vérifier sa preuve
possédée, mais ne doit pas consulter le socket déjà fermé. Un retour d'entrée
invalide libère le manager entré puis refuse avant l'envoi. Une suppression
d'exception demandée par le manager n'est pas honorée ; ses diagnostics privés
ne sont pas exposés.

Un échec du guard après soumission de `begin` est `initialization_uncertain`.
Une cancellation du client helper draine sa fermeture malgré les annulations
répétées avant de libérer la preuve. En mode attesté, le helper exige une seule
réponse JSONL complète suivie d'EOF, dans la deadline totale existante (15 s sync,
20 s async), sans prolongation après le check du peer. Ces budgets couvrent
connexion/envoi/lecture ; la fermeture possédée reste drainée au-delà si
nécessaire. Le callback synchrone OS doit lui-même être borné ; Python ne peut
pas préempter son entrée ou son exit.

Les defaults `peer_guard=None` des clients restent legacy, sans nouvelle
attestation implicite. Une future composition helper active doit injecter
explicitement son propre adaptateur OS.

Cette API atteste seulement le **peer connecté**. Elle n'atteste pas l'émetteur
de chaque message avec `SCM_PIDFD`, un fd hérité, un broker, la phase B ou un
grant réutilisable. Aucun syscall PIDFD ou adaptateur Linux n'est livré ici.

## Invalidation et ownership

Le watcher OS doit latch son état `INVALID`, puis demander STOP sur la loop
avec `stop_requested`. Il ne doit pas arrêter IPC/helper pour provoquer ce STOP :
ils doivent rester vivants jusqu'à la fin des échanges et effets déjà admis.
Le raccord ferme immédiatement le gate thread-safe du contrôleur d'écran et
planifie l'arrêt du runtime sur sa loop lorsqu'un check échoue depuis un worker.

Les checks précèdent la réservation, le rendu, le refresh QR/statut et
l'enregistrement BlueZ, avec un nouveau check après l'enregistrement avant
l'ouverture de l'admission. Une invalidation bloque les nouvelles opérations.
Un claim SQLite admis, un refresh SPI admis ou une registration BlueZ engagée
termine sous son owner. Les releases, fermetures et drains n'exigent pas de gate
positif. STOP ne rouvre jamais l'admission.

Ces frontières ne constituent pas un check atomique au moment GPIO. La stabilité
du graphe, le watcher permanent et les politiques d'arrêt systemd restent à
qualifier par InkyOS. Le futur raccord installé doit épingler un module de gate
protégé root, fournir les droits runtime UID 1000 et prouver le graphe réellement
installé. Il reste fermé tant que cette qualification manque.

## Preuves et limites des tests

Les tests utilisent de vrais sockets Unix, EOF et transactions SQLite, avec
des guards OS et des délais radio/SPI synthétiques. Une barrière SQLite observe
l'INSERT du claim sur la même connexion avant COMMIT ; l'invalidation et les
cancellations n'effacent pas ce claim admis. Les tests couvrent aussi STOP via
l'Event du runner, Context neuf, threads, consommation `begin` sans création de
store après refus, et conservation des ressources jusqu'au drainage.

Ils ne qualifient pas un watcher OS installé, PIDFD, D-Bus UID 1000, BlueZ réel,
le panneau, une SD ou l'association iPhone. Aucune ancienne qualification de
bundle n'est transférée à ces nouveaux octets.

## Sources

- [Runner et ownership](../../server/inky_web/provisioning/factory_phase_a.py).
- [Propagation coordinator/store](../../server/inky_web/provisioning/factory_runtime.py).
- [Scope du peer connecté](../../server/inky_web/provisioning/connected_peer.py).
- [Transport IPC](../../server/inky_web/provisioning/initialization_ipc.py).
- [Transport helper](../../server/inky_web/provisioning/network.py).
- [Tests de composition](../../server/tests/test_factory_admission.py).
- [Tests des frontières écran/runtime](../../server/tests/test_bootstrap_admission.py).
- [Tests du helper attesté](../../server/tests/test_network_peer_guard.py).
