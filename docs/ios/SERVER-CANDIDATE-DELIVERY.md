# Livraison de la candidate serveur — 27 septembre 2026

**Candidate qualifiée et déployée en production : `0.5.0-rc.1`.** Le mot de passe
existant a été conservé et sa connexion vérifiée après migration vers le stockage
hashé. Le vrai driver d’écran est actif. Aucun changement Wi-Fi ou choix de nouveau
mot de passe n’a été effectué.

## Sources et release

- Recette iPhone acceptée par Mehdi (« je valide le 1 »), puis
  [PR #8](https://github.com/mehdi7129/inky-studio/pull/8) fusionnée : `b31046d`.
- [PR #9](https://github.com/mehdi7129/inky-studio/pull/9) fusionnée :
  `2303bd0440382024d2b7fec06f3d62bcbaaef1be` ; lanceur stable, refus du downgrade
  via appel direct à l’API, canal prerelease et qualification HTTP/WebSocket.
- [Release v0.5.0-rc.1](https://github.com/mehdi7129/inky-studio/releases/tag/v0.5.0-rc.1),
  créée par [le workflow validé](https://github.com/mehdi7129/inky-studio/actions/runs/36317870544).
  L’API GitHub confirme `prerelease=true`, `draft=false` ; `/releases/latest`
  renvoie toujours `v0.4.2` après publication.
- Archive `inky-studio-v0.5.0-rc.1.tar.gz`, **901 665 octets**.
  SHA-256 GitHub, Mac et Pi identique :
  `c5c6d598384c763a237120ed85ac253623c44e71ac2f76b92fb0bd53d5bc3521`.

La CI de la PR valide 199 tests backend sur Python 3.11 et 3.13, les 29 contrôles
HTTP/WebSocket sur ces deux versions, Ruff, ShellCheck et frontend
lint/typecheck/tests/build. Aucun code iPhone n’est modifié par la PR #9.
La CI iOS de la fusion #8 est également verte.

## Qualification de l’archive sur le Pi

Archive extraite dans un dossier de staging privé, séparé de l’installation.
Le Python 3.13.5 du venv existant a chargé explicitement les sources candidates
avec `PYTHONPATH`, sans réinstaller de dépendances ou démarrer l’application
principale. Le test crée ses propres données synthétiques et processus loopback.

| Mesure | Résultat |
|---|---|
| Contrôles réels HTTP/WebSocket | **29 PASS**, sortie 0 |
| Version chargée | `0.5.0-rc.1` |
| Connexion initiale | **510,098 ms** |
| Rotation du mot de passe | **995,755 ms** |
| Connexion après redémarrage du processus de test | **511,689 ms** |
| Durée complète | **18,030 s** |
| Anciennes sessions et WebSocket inactif | Révoqués ; fermeture WebSocket 1008 |
| Cleanup | Données synthétiques supprimées, aucun processus QA restant |
| Service de production après test | Actif ; `/api/health` → `ok`, `0.4.2` |

[Résultat JSON sans secrets](reviews/2026-09-27-server-candidate/password-qualification.json).
Ces mesures ne qualifient ni une coupure électrique, ni une rotation réelle depuis
l’iPhone, ni un rafraîchissement e-ink simultané.

## Intervention administrative terminée

SSH par clé avec `pi` fonctionne. Les droits sudo sans mot de passe couvrent
seulement le contrôle d’`inky-studio.service`. `sudo -n install` est refusé :
le mot de passe Linux doit être saisi par l’opérateur dans son Terminal.
Il est distinct du mot de passe d’accès à l’app ; aucun mot de passe n’est demandé
dans la conversation et aucune règle sudoers n’a été élargie.

Le lanceur généré est prêt sur le Pi, syntaxe Bash et commande `help` vérifiées
avec l’ancienne CLI. Son SHA-256 est :
`86f6749f045f05a75d8f90e88180c8d247e785ad3de2eea6c374e25f4e3dc3d2`.
Une copie privée de l’ancienne CLI est conservée dans le même staging.

Commande exécutée par Mehdi dans son Terminal, puis vérifiée par hash et
permissions depuis SSH :

```bash
ssh -t pi@inkyold.local 'sudo install -o root -g root -m 0755 /home/pi/inky-upgrades/0.5.0-rc.1/inky-studio /usr/local/bin/inky-studio'
```

Elle a remplacé le lanceur root-owned sans arrêter le cadre. Son hash et ses
permissions `root:root 0755` ont été confirmés avant le déploiement.

## Déploiement contrôlé réussi

[Rapport opérateur sans secrets](reviews/2026-09-27-server-candidate/deployment.json) :
`result=applied`, toutes les étapes validées, aucun rollback déclenché. Le script
opérateur privé a été relu indépendamment et son `--check` réel a réussi avant
`--apply`. SHA-256 du script exécuté :
`341894012325fdd81750be4f1b6c691164ac3518701e85bf902b648f708cd540`.

Après démarrage : health `ok`/`0.5.0-rc.1`, authentification requise,
`password_change_supported=true`, login avec le secret initial réussi,
`is_mock=false`, puis logout de la session de qualification. La CLI correspond
au payload et le fichier credentials est `pi:pi 0600`. Le backup source/données
reste privé sur le Pi pour récupération ; il contient le secret legacy et ne
doit pas être publié ou restauré après personnalisation.

La séquence utilisée et ses règles de récupération :

1. Sous le verrou `.inky-update.lock`, arrêter le service et sauvegarder source,
   lanceur et données dans un dossier privé. L’absence de credentials initiaux
   doit interrompre la migration plutôt que générer un nouveau secret.
2. Appliquer le payload validé sans déplacer/supprimer le venv editable. Les
   dépendances et le schéma DB sont inchangés depuis v0.4.2 ; seules les métadonnées
   de version du package changent. Réinstaller editable avec `--no-deps`.
3. Migrer les credentials pendant l’arrêt, vérifier le secret legacy seulement
   en mémoire et retenir le fichier v2 attendu pour détecter toute personnalisation
   intervenue ensuite. Aucun secret/hash/cookie dans les logs de qualification.
4. Démarrer, vérifier health/version/capacité, connexion locale avec le secret
   conservé en mémoire et `/api/display` avec `is_mock=false`, puis déconnecter
   uniquement cette session de qualification. Ne pas appeler la rotation réelle.
5. Si rollback nécessaire, suivre [PASSWORD-ROTATION.md](PASSWORD-ROTATION.md).
   Ne jamais restaurer silencieusement un ancien secret après personnalisation.
   Le nouveau lanceur peut rester installé et déléguer à la CLI précédente.

Le scheduler exécute son premier tick immédiatement : une échéance dépassée peut
afficher une photo et changer la file/l’historique après redémarrage. Un rollback
ordinaire ne doit donc pas restaurer aveuglément toute la sauvegarde de données.
Le schéma DB étant inchangé, conserver les photos et la base actuelles ; restaurer
source et credentials compatibles seulement si les conditions de rollback sont
remplies. `health` seul ne prouve pas que le driver matériel est actif.

La configuration Wi-Fi Bluetooth reste hors de cette candidate ; voir la
[décision C2 et ses critères de qualification](BLE-C2-SECURITY-DECISION.md).


## Bootstrap des prochaines installations

Une correction séparée protège le bootstrap courant : fallback autonome pour
les anciennes archives sans générateur de lanceur, et refus de remplacer une
version candidate par une stable plus ancienne, sans fallback implicite vers main.
Ses dix tests ajoutés portent la suite à **209 PASS** sur Python 3.11 et 3.13.
Cette correction n’altère pas rétroactivement l’archive `v0.5.0-rc.1` déployée.
Ne pas utiliser l’installateur historique de cette archive pour réinstaller une
candidate ; utiliser le bootstrap courant corrigé. La migration décrite ici a
utilisé le payload vérifié directement, sans lancer cet installateur.
