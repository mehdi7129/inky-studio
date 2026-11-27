# Candidat backend factory system setup — 16 octobre 2026

Candidat source local pour qualification TEST, non déployé. Parent exact :
`d67db9e44c37eb72b94851b4bba923228479cf00`, branche
`codex/factory-system-setup-20261016`. Le code OS correspondant est livré séparément ;
son wrapper doit composer les vrais guards et setters attestés. Les anciens
checkouts PHOTO/legacy, iOS, Pi, SD et VM n'ont pas été modifiés.

## Portée réalisée

- QR bootstrap v2 et claim/status v1 compatibles ; setup RPC v2 explicitement
  négocié sur les profils bootstrap et normal. Session UUID/génération locale
  invalidée par RESET, disconnect, CLOSE, expiration, rotation et drain.
- Client AF_UNIX réellement connecté, borné et strict, proof conservé jusqu'au
  drain. Challenge BOOTTIME et résultats heure/pays/radio proviennent du service
  OS attesté ; aucun booléen local ne les remplace.
- Apply répond vite `applying/registered/not_confirmed`, puis le Registry garde
  la tâche. Intention UTC/pays exacte persistée avant IPC, sans secret owner.
  Status/inspect sont readonly ; absence, pending et uncertain ne rejouent rien.
- Publication initiale après résultat courant lié au même boot/session/epoch ;
  continuation DATA-ONLY limitée aux octets déjà journalisés. UUID, clé et SPKI
  restent identiques. Un renouvellement existant n'est jamais remplacé par
  l'ancien DER du journal initial.
- Handoff après fermeture et drain des channels, sans shutdown display/store,
  welcome ni second initialize. Vrais listeners HTTP/HTTPS normaux, TLS strict,
  `proxy_headers=False`, store v2 et NetworkClient injectés ; échec listener
  ferme l'admission et draine la durée de vie extérieure.
- Confirmation Wi-Fi HTTPS owner existante, puis completion OS réelle et
  enrôlement PHOTO factory HTTPS dédié, sans password/cookie comme autorité.
  Credential PHOTO neuf, distinct du BLE ; retry exact par claim dans le store
  PHOTO existant. L'origin vient des observations OS explicites Avahi/NM,
  jamais de Host/SAN/IP. Origin absente : wait_origin ; BLE Wi-Fi reste possible.
- Reboot positivement NORMAL à partir de completion root + publication/ledger
  cohérents, sans owner encore actif ni ancien téléphone. La photo et les
  identités existantes sont conservées si le réseau reste fermé. Aucun nouveau
  factory begin lorsque le reçu consumed est déjà attesté.
- Recovery après completion : nouvelle completion courante uniquement après
  nouvelle opération explicite et vrai complete ; historique OS borné à64 sans
  éviction. Avant approbation, la nouvelle opération reste pending/uncertain et
  le PHOTO enrollment refuse l'ancienne completion. Un changement Wi-Fi normal
  seul modifie le network_head, pas la completion. Les lectures acceptent un
  head historique distinct des observations réseau courantes.
- Helper : inspections committed/latest readonly, réservées au vrai service
  setup attesté ; anciennes lignes sans provenance boot ne sont pas promues.
  READY=1 envoyé après bind/listen, pour la composition OS Type=notify.

## Composition attendue

```python
from inky_web.provisioning.factory_continuation import FactoryContinuationRuntime
from inky_web.provisioning.system_setup_ipc import SystemSetupClient
from inky_web.provisioning.network import NetworkClient

runtime_factory = lambda result, display, verify_epoch: FactoryContinuationRuntime(
    result, verify_epoch, display, data_directory / "provisioning",
    system_setup=SystemSetupClient(peer_guard=proof.setup_guard),
    network=NetworkClient(peer_guard=proof.network_guard),
)
```

`serve_factory_phase_a` conserve sa signature. Il lie le callback de fermeture
au runtime et reste propriétaire du writer lease jusqu'au drain final. Aucun
fallback installé factory→legacy n'est ajouté. Les entrypoints génériques sans
wrapper OS qualifié restent fermés pour un état factory.

## Données et écritures

Les médias, `inky_studio.db`, `credentials.json`, `ownership.sqlite3` v2 et
`photo-access/access.sqlite3` existants sont réutilisés. Le core normal ouvre les
schémas PHOTO/historique existants sans restauration d'ancienne sauvegarde.
Les credentials factory sont lus, jamais créés ou réinitialisés par le handoff.

Nouveau fichier applicatif : `provisioning/system-setup-intents.json` (64 intentions
maximum), écrit atomiquement sous lock ; c'est une donnée de retry, aucune
autorité OS. `PreparedFactoryIdentity` garde son format existant et écrit
uniquement son candidat initial/sa publication explicite. Le journal système,
les completions et le network_head restent root-only dans le composant OS.

## Contrats figés et addendum revu

Les quatre fichiers normatifs ont été figés avant la première mutation produit.
Leur titre de conception « aucun GO code » décrit ce moment historique ; le GO
source et les deltas revus sont conservés dans les deux REVIEW.

| Fichier | SHA-256 |
|---|---|
| wire-contract.json | bdd7de1aefde53b2315597f0715fe9a98b7061963426fa888bf1031a38377f67 |
| ipc-contract.json | 9ee767fbdb75250546ca950c4d1fff58c8e1d0b6b9029742b61efea9bd2a7b52 |
| STARTUP-TRANSITION.md | 9333d1f401ce8e6b3788490bc985e4e0b4f6c5864304703dcc4d1bbd047bd070 |
| OS-FACTS.md | f9c7b6c9869ad9bf7fb1ac5c86ea0fb6a13a4697178f258028a62b3d22ab6eb8 |
| REVIEW-ROOT.json | d6067fd1f0c75ed4e60b7731a8aaf0b2dd7778eeb311cbc7c53b219f2abfa375 |
| REVIEW-ADDENDUM-COMPLETIONS.json | 5256f655d159faa7f93904d7cc0a1567145640c263f3be5e1a5e9e0aeb57b834 |
| REVIEW-ADDENDUM-COMPLETIONS.md | bbcba3256e5b4bfbbab82ae6ef79484d9662bac24c7372d4de50e16114998d46 |

## Validation Mac

Python3.13.15/Ruff0.17.0 du venv existant
`inky-display-250-validation-venv`, sans installation. Tests ciblés seulement,
`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m pytest -q -p no:cacheprovider`.
Les groupes ci-dessous sont rapportés séparément, sans addition de passages
successifs ni de tests qui se chevauchent.

| Passage ciblé | Résultat |
|---|---|
| Bootstrap runtime/identity, first_boot, factory_phase_a | 161 PASS |
| factory_runtime, runtime_entrypoints, factory_session, provisioning_integration, provisioning_factory | 174 PASS |
| Auth, auth_storage, PHOTO, vrais listeners legacy loopback | 118 PASS |
| Lot regroupé lifecycle + wire + IPC + helper/inspection/factory | 230 PASS |
| Après derniers ajustements : lifecycle factory système seul | 25 PASS |
| Après addendum : IPC + wire seuls | 62 PASS |

Les passages230/25/62 se chevauchent et **ne sont pas additionnés**. Les deux
derniers contrôlent les deltas finaux (concurrence réseau, rotation, historique
completion/head). Ruff sur tous les fichiers Python modifiés/ajoutés et
`git diff --check` : PASS. Le warning Starlette/httpx déjà existant demeure.

Les régressions listeners vérifient de vrais processus/sockets TLS locaux ; le
nouveau core injecté est couvert par les tests de durée de vie, d'échec de bind,
de mort après ready et de réutilisation sans initialize/welcome. Une fixture
TLS complète du candidat propre est préparée séparément par l'orchestrateur.

Les tests utilisent de vrais fichiers SQLite/certificats, de vrais streams Unix
et des records TLS MemoryBIO. Les boundaries BlueZ/NM/setters/écran sont inertes
sur Mac ; ces preuves ne qualifient pas les effets natifs Linux ni le panneau.
Revue indépendante root + worker IPC : drain du handoff, listener failure,
entier UTC lexical, challenge interrompu, historique réseau et completion ont
été corrigés puis couverts par tests ciblés.

## Limites avant qualification générale

- Le driver reste **Inky2.5.0**, exactement comme d67. Le Pi actuel PHOTO validé
  physiquement était sur Inky2.3 ; cette preuve ne se transfère pas au2.5.
- Le certificat courant est conservé après reboot. Sa durée de validité normale
  est396jours. Graph/Ready et une completion historique ne prouvent aucune UTC
  actuelle : le renouvellement automatique factory est donc différé. Aucun
  NTP grant implicite, exception de date TLS normale ni ClockResult historique
  n'est introduit. Une politique durable de renouvellement sans owner après
  reboot doit être close avant une release générale.
- Setup/recovery système reste limité au **first owner encore autorisé**,
  conformément au contrat initial. Une révocation ne rouvre jamais factory et
  ne bloque pas le boot NORMAL/la photo. La récupération administrative après
  perte/révocation de ce first owner est un lot futur explicite ; les invités
  PHOTO/média ne reçoivent aucune autorité BLE/setup.
- Aucun package, wheel, image, archive, build OS, Pi, SD, VM ou déploiement ;
  aucune publication/push. Qualification Linux native, vraie Avahi/NM/rfkill,
  fixture HTTPS avec pin public puis contrôle physique restent à livrer dans
  les lots autorisés séparément. Ce candidat n'est pas un produit final prêt
  pour une release générale.
