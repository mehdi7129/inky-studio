# Relais InkyOS

Le projet d'image système a son dépôt distinct :
[mehdi7129/inkyOS](https://github.com/mehdi7129/inkyOS), privé au démarrage.
Le dossier local est `~/Desktop/inkyOS`.

- [Sources officielles du matériel et du système](HARDWARE-SOURCES.md).
- [Dossier de transmission InkyOS](https://github.com/mehdi7129/inkyOS/blob/main/docs/HANDOFF.md).
- [Contrat de premier démarrage — draft de coordination](FIRST-BOOT-CONTRACT.md).
- [Socle d'état factory — API interne désactivée dans le runtime](FACTORY-STATE.md).
- [Décision TLS de bootstrap](BOOTSTRAP-TLS-DECISION.md).
- [Prototype TLS isolé — périmètre et validation](BOOTSTRAP-TLS-PROTOTYPE.md).

Deux parcours sont prévus : installation avancée d'Inky Studio sur Raspberry Pi OS,
et image InkyOS préinstallée. Un prototype système et un payload applicatif
hors ligne ont maintenant des preuves séparées dans le dépôt InkyOS ; cela ne
constitue pas une image complète qualifiée pour installation sur le cadre.
La première adoption sans LAN et la gestion de l'heure/pays font l'objet du
contrat ci-dessus, distinct de la qualification Bluetooth du candidat actuel.

Le dossier de transmission distingue le code déjà testé, les limites connues et
les étapes futures. Il ne contient aucune coordonnée administrative, clé privée,
photo personnelle ou mot de passe. Le relais entre les sessions est actif :
Inky Studio possède l'app, les protocoles et helpers ; InkyOS possède l'image,
les prérequis système et les tests VM. Les résultats échangés doivent toujours
préciser leur commit, leur périmètre et les validations encore ouvertes.
