# Credentials factory — sérialiseur Studio, publication InkyOS

Contrat proposé le 11 octobre 2026, option A convenue entre Studio et InkyOS.
Le sérialiseur est isolé du runtime : ce document n'active aucun service, hook
d'image, création d'autorité IPC-A ni parcours premier boot. La qualification
Linux et la publication root restent la responsabilité InkyOS.

## Invocation et sortie

Invocation installée confirmée par InkyOS, sans shell, sous UID/GID **1000** :

```text
/home/inky/inky-studio/server/.venv/bin/python -I -B -m inky_web.provisioning.factory_credentials --emit-v2
```

Ce chemin n'est pas un paramètre fourni par l'application ou le téléphone.
Le payload installé et son interpréteur doivent être ceux vérifiés par l'image ;
`-I` seul ne prouve pas leur intégrité. Le code et le venv appartiennent à
UID/GID 1000 : **le publisher root ne doit jamais les exécuter sous root**.
Il abandonne UID/GID root avant exec, vide les groupes supplémentaires, fournit
un environnement fixe sans secret ni `PYTHONPATH`, un cwd neutre et stdin
`DEVNULL`. `-B` interdit l'écriture de bytecode pendant cette invocation.
Aucun mot de passe ou salt n'est fourni
par argument, environnement, fichier d'entrée ou image commune.

Le seul argument admis est `--emit-v2`. Avant génération, la CLI vérifie par
`fstat(1)` que stdout est un FIFO. Elle refuse terminal, fichier ordinaire,
socket ou descripteur invalide. Ce contrôle de type ne prouve pas la confidentialité
du pipe : InkyOS crée lui-même un tuyau anonyme privé, ne transmet que les FDs
nécessaires et ne raccorde jamais stdout au terminal, à journald ou à un log.

| Élément | Contrat |
|---|---|
| Succès | Exit **0**, stdout terminé par EOF, exactement un document JSON ASCII compact suivi d'une seule LF |
| Taille | **8192 octets maximum, LF comprise** ; le résultat non vide tient sur une ligne |
| Usage ou stdout invalide | Exit **64**, aucune génération, stderr fixe `factory_credentials_usage` + LF |
| Génération ou écriture échouée | Exit **70**, stderr fixe `factory_credentials_failed` + LF |
| stderr au succès | Vide |

Le document est le `Credentials.record()` v2 de Studio, avec ses paramètres
scrypt constants. Chaque invocation génère un nouveau mot de passe bootstrap
de **16 caractères alphanumériques** et un salt indépendant de **16 octets** via
les fonctions existantes de Studio. Le mot de passe bootstrap figure dans le
record privé, conformément au format utilisé par le premier affichage ; aucun
secret n'est écrit dans les diagnostics. Les erreurs ne reprennent aucun
argument, contenu d'environnement, record ou exception interne.

Une erreur d'écriture peut survenir **après émission d'un préfixe** sur le pipe.
Le programme ne peut pas retirer ces octets. Le parent doit jeter l'intégralité
du buffer sur exit non nul, signal, timeout, absence d'EOF ou framing invalide ;
il ne journalise jamais le buffer ni un extrait de celui-ci. Exit 0 exige une
écriture complète non bufferisée ; le parent attend aussi la fin normale du
processus, sans traiter l'arrivée d'une LF comme un succès suffisant.

InkyOS conserve les octets comme un payload opaque : il peut contrôler la borne,
l'ASCII, la LF unique finale et le statut/EOF, sans dupliquer le schéma credentials
ou le KDF. Studio produit le JSON v2 valide depuis le code épinglé et ses tests.
La validation complète existante sera ensuite appliquée par le factory guard.
Un contrôle de framing OS seul n'est pas une validation indépendante du JSON.

## Autorité et ordre de publication OS

Le sérialiseur ne lit ni n'écrit le state applicatif, ne crée aucun répertoire,
ne vérifie aucun grant et ne contacte ni IPC-A, ni réseau, ni écran. L'API ne
possède pas de destination de publication. Pouvoir lancer ce générateur ne
donne donc aucune autorité d'installation : **root possède la publication**.
Les lectures normales du code Python, de la stdlib et des dépendances importées
restent nécessaires ; l'absence d'accès au state ne signifie pas zéro lecture
du filesystem par l'interpréteur.

1. Vérifier une permission root **positive**, durable et encore utilisable,
   sous le verrou de l'orchestration OS, conservé jusqu'après la création
   durable de l'autorité par `create_authorization`. Son absence/corruption
   n'en crée pas une nouvelle. L'état `authorized` d'IPC-A ne remplace pas cette
   permission. L'ordre de démarrage OS doit empêcher l'app et le helper de
   fonctionner concurremment pendant cette séquence : le répertoire applicatif
   appartient à UID 1000, et le verrou du publisher seul n'exclut pas ces autres
   processus. Seul le sous-processus de sérialisation prévu est lancé.
2. Consommer cette permission irréversiblement et synchroniser sa persistance
   **avant** de lancer une seule invocation Studio. Aucun grant d'environnement
   ou reçu applicatif mis en cache ne permet de relancer le hook.
3. Lancer l'invocation après abandon des privilèges décrit ci-dessus, puis
   capturer stdout dans le pipe privé avec une taille et un délai bornés.
   Attendre EOF et **réaper le processus avec exit 0** avant toute publication.
   Le délai OS reste à fixer ; son expiration implique arrêt/récolte de l'enfant
   avant recovery, jamais deuxième invocation concurrente.
4. Publier à l'unique destination `/var/lib/inky-studio/credentials.json`, via
   des parents vérifiés et des FDs ancrés sans liens. La création utilise
   `O_CREAT | O_EXCL | O_NOFOLLOW`, mode **0600**, propriétaire UID **1000** et
   lien unique. Ne jamais écraser, tronquer ou remplacer un fichier existant.
   `O_NOFOLLOW` sur le fichier seul ne dispense pas de vérifier les parents.
5. Écrire intégralement les octets capturés, synchroniser fichier et répertoire,
   puis relire exactement les mêmes octets et vérifier type/permissions/owner.
   Un fichier partiel ou une persistance incertaine reste un état de récupération,
   pas un prétexte à supprimer le fichier et recommencer.
6. Seulement ensuite, créer l'autorité d'initialisation root via le chemin local
   InkyOS prévu, puis permettre le factory guard et le coordinator existants.
   Le sérialiseur ne crée ni identité de cadre ni ledger d'ownership.

Le writer legacy `_write_credentials()` emploie `os.replace` : il ne convient
pas à cette publication exclusive. Le loader legacy, `reset_credentials()` et
la génération automatique sur fichier absent ne font pas partie du parcours.

Toute coupure avant l'autorité durable après consommation de permission, tout
échec/timeout de l'enfant, tout fichier déjà présent lors de la publication
initiale et toute incohérence exigent **recovery explicite**.
Si l'autorité IPC-A n'a pas été durablement créée, un fichier v2 apparemment
valide ne permet pas de poursuivre après redémarrage : il peut appartenir à une
tentative interrompue. Aucun retry automatique du générateur ou de publication.
Si l'autorité existe déjà, seules les reprises prévues par IPC-A/coordinator sont
possibles : une permission consommée n'autorise **jamais** une nouvelle
génération ou une republication. Cette reprise contrôle les metadata du fichier
courant et son format via la validation Studio existante ; elle ne compare pas
les credentials à un hash immuable du payload initial, car une rotation légitime
peut les avoir remplacés. L'égalité exacte des octets à l'étape 5 vérifie la
publication initiale uniquement. Des credentials manquants ou invalides restent
un cas de recovery, jamais une demande de recréation.

## Vérification et limites

Les tests Studio vérifient le vrai subprocess avec stdout pipe, le framing et
la vérification du record avec le code credentials existant, l'indépendance des
invocations, les refus de fichier/terminal/socket, les erreurs d'écriture et
l'absence d'accès au state ou aux secrets d'environnement.

La propriété « une seule publication » appartient au journal/root publisher OS,
pas au générateur aléatoire. InkyOS doit encore vérifier les vrais UIDs Linux,
le verrou et la consommation durable, la capture bornée, le reap, la publication
exclusive, les fsync/readbacks et toutes les coupures entre ces étapes. Un test
portable Studio ne qualifie ni ce publisher ni une SD ou un premier boot physique.

Références : [factory runtime guard](FACTORY-RUNTIME-GUARD.md),
[IPC-A](INITIALIZATION-IPC-V1.md),
[format et KDF Studio](../../server/inky_web/auth.py),
[sérialiseur](../../server/inky_web/provisioning/factory_credentials.py).
