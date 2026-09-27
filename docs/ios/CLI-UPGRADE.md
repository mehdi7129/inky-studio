# Migration du lanceur Inky Studio sur Raspberry Pi

Le lanceur installé dans `/usr/local/bin/inky-studio` appartient à `root:root`
avec les permissions `0755`. Il contient uniquement les chemins par défaut et
un `exec` vers `INSTALL_DIR/scripts/inky-studio-cli`. Les commandes, les messages
et la récupération du mot de passe restent dans ce dernier fichier, inclus dans
chaque release. Une mise à jour de l’app met donc aussi à jour la logique CLI.

Le lanceur s’exécute avec les droits de l’utilisateur qui l’appelle. Il ne change
aucune règle sudoers. Utiliser `inky-studio …` avec l’utilisateur normal du
service, sans préfixer la commande par `sudo` ; les commandes de service
existantes appellent elles-mêmes le `sudo` limité prévu par l’installation.

## Migration d’une installation existante

Les anciennes versions copiaient toute la logique CLI dans `/usr/local/bin`.
Leur updater remplace uniquement les fichiers du dossier d’installation. Il
**ne peut donc pas effectuer cette migration administrative à lui seul**.
Après migration des identifiants vers le format hashé, l’ancien `password` ne
sait plus lire le fichier et l’ancien `reset-password` conserve sa suppression
non transactionnelle. Ne pas les utiliser pendant la transition.

Avant la commande ci-dessous :

- Mettre le nouveau générateur `scripts/inky-studio-launcher` à disposition dans
  le dossier réel d’installation. La logique `scripts/inky-studio-cli` doit déjà
  y exister ; elle peut encore être celle de l’ancienne release. Installer le
  lanceur **avant** de mettre à jour et redémarrer le backend : il déléguera
  d’abord à l’ancienne logique, puis automatiquement à la nouvelle.
- Vérifier que la session SSH utilise le compte qui possède l’installation.
  Conserver une copie administrative de l’ancien lanceur pour le retour arrière.

Pour les chemins standards de l’installateur (`$HOME/inky-studio` et
`/var/lib/inky-studio`), cette **unique commande de migration** génère puis
installe le lanceur. Elle demande le mot de passe `sudo` si nécessaire :

```bash
bash "$HOME/inky-studio/scripts/inky-studio-launcher" --install "$HOME/inky-studio" /var/lib/inky-studio
```

Pour une installation personnalisée, fournir ses deux chemins absolus :

```bash
bash '/srv/mon cadre/scripts/inky-studio-launcher' --install '/srv/mon cadre' '/var/lib/mon cadre'
```

La commande peut être exécutée pendant que l’ancienne release fonctionne. Elle
ne démarre ni n’arrête le service, ne lance aucune commande métier
et ne lit pas les identifiants. Elle vérifie la présence de la logique CLI,
génère un fichier temporaire privé, vérifie sa syntaxe Bash, puis invoque
`sudo install -o root -g root -m 0755` vers `/usr/local/bin/inky-studio`.
Une fois la migration réussie, arrêter le service, effectuer la sauvegarde
protégée, puis déployer les fichiers du backend et de la CLI correspondante et
redémarrer selon [PASSWORD-ROTATION.md](PASSWORD-ROTATION.md). Ne pas publier le
nouveau backend sur ce Pi avant cette migration du lanceur.

Une mise à jour lancée par l’ancien updater peut remplacer les fichiers et
redémarrer le backend avant que cette intervention soit faite. Pour cette
transition, utiliser le déploiement administratif coordonné ; ne pas annoncer
une récupération CLI fonctionnelle sur un Pi conservant l’ancienne copie.

## Vérification sans mutation du cadre

```bash
sed -n '1,30p' /usr/local/bin/inky-studio
stat -c '%U:%G %a' /usr/local/bin/inky-studio
inky-studio help
```

Le fichier doit contenir les deux chemins attendus, puis `exec /bin/bash` vers
`scripts/inky-studio-cli`. Le propriétaire et le mode attendus sont
`root:root 755`. La commande `help` ne touche ni le service ni les identifiants.

Pour inspecter la génération avant une migration, sans écriture privilégiée :

```bash
bash "$HOME/inky-studio/scripts/inky-studio-launcher" --print "$HOME/inky-studio" /var/lib/inky-studio
```

`INKY_STUDIO_INSTALL_DIR` et `INKY_STUDIO_DATA_DIR` restent surchargeables dans
l’environnement, comme auparavant. Les arguments et le code de sortie de la
logique CLI sont transmis intégralement. Si celle-ci manque ou n’est plus
lisible, le lanceur sort avec le code `127`, indique le chemin à réparer et ne
touche pas au service. Restaurer la release ou corriger le chemin avant de
réessayer.

Pour un retour à une ancienne release, vérifier d’abord la compatibilité du
format des identifiants ; restaurer seulement le lanceur ne rend pas un ancien
backend compatible avec un mot de passe personnalisé hashé. La procédure de
retour complète reste celle de [PASSWORD-ROTATION.md](PASSWORD-ROTATION.md).

## Validation automatisée

`server/tests/test_cli.py` vérifie le lanceur généré avec des chemins contenant
espaces, quotes, accents, substitutions shell littérales et retours à la ligne,
la conservation des arguments, les surcharges d’environnement et le code de
sortie. Le remplacement de la logique par une deuxième version est détecté sans
réinstaller le lanceur. Un stub de `sudo` valide la commande d’installation et
ses permissions dans un dossier temporaire ; aucun vrai `sudo` ni service
système n’est utilisé. Les tests existants de lecture et de reset des
identifiants passent désormais aussi par le lanceur généré.
