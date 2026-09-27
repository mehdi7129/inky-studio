# Inky Studio — proposition Bento 2

Statut : **direction validée avec corrections ; build 3 archivé et uploadé**.
Mehdi a validé les thèmes clair/sombre et l’icône **A**, avec deux corrections
prioritaires : conserver les formes arrondies et la disposition de l’app précédente,
et retirer les noms de photos/fichiers de Cadre, File et Historique. Les noms
présents dans les planches exploratoires ci-dessous ne doivent donc pas être livrés.
Mehdi confirme le 27 septembre 2026 que la bêta fonctionne sur son iPhone et
signale un grand vide au-dessus de l’onglet Cadre. La demande comprend une
icône plus lisible, le portrait uniquement, les thèmes système, l’appareil
photo, le Wi-Fi par Bluetooth, un mot de passe personnalisable et, plus tard,
une image Raspberry Pi OS préconfigurée appelée provisoirement InkyOS.

## Visuels à examiner

| Planche | Contenu |
|---|---|
| [01 — Clair](01-bento-light.png) | Les quatre onglets : Cadre, File, Historique, Réglages |
| [02 — Sombre](02-bento-dark.png) | Les mêmes écrans suivant l’apparence système |
| [03 — Icônes](03-icon-directions.png) | A : Le cadre (recommandée), B : Bento, C : Inky |
| [04 — Nouveaux parcours](04-photo-wifi-security.png) | Source photo/caméra, Wi-Fi du cadre, mot de passe personnalisé |

Ces images ont été générées avec le **tool Imagegen intégré**, à partir des
maquettes approuvées et de l’ancienne icône. Les prompts sont conservés dans
[prompts.json](prompts.json). Les photos sont des illustrations ; les captures
de test réelles sont identifiées séparément dans l’audit. Aucun portrait privé
de Mehdi n’a servi de référence aux générations.

## Choix recommandés

- Conserver le Bento blanc/noir avec un bleu et un ambre mesurés.
- Un seul en-tête compact, une vraie marge de sécurité au-dessus de la tab bar.
- Conserver quatre onglets, leurs libellés et les gestes natifs ; ne pas ajouter
  un cinquième onglet Bluetooth.
- Réserver le noir/blanc contrasté à l’action principale. Donner la priorité à
  l’image du cadre et aux actions courantes.
- Les propositions de sous-pages Réglages restent exploratoires : la réalisation conserve les cartes arrondies de la page existante, selon la correction de Mehdi.
- Suivre automatiquement le système. « Apparence · Système » est une information,
  pas un sélecteur : le chevron dessiné dans la planche claire est à ignorer.
- Recommander l’icône **A** pour la reconnaissance immédiate d’un cadre photo.
  B conserve davantage la référence Bento ; C est plus abstraite.

## Contrat à respecter lors du développement

Les planches sont des directions visuelles, pas des assets à découper et livrer.
L’icône choisie sera reconstruite proprement avec une source vectorielle ou
Icon Composer, puis exportée et vérifiée aux tailles réelles 29/40/60/120 px.
Les petites tailles dessinées dans la planche ne constituent pas cette mesure.
Prévoir les apparences d’icône prises en charge par les OS ciblés ; ne pas
confondre variante d’icône et thème de l’interface.

Le ratio photo vient toujours du panneau réel (5:3 pour le cadre actuellement
testé). La typographie reste Dynamic Type. Les cartes et boutons passent sur
plusieurs lignes aux grandes tailles. Cibles tactiles d’au moins 44 pt.
Contraste mesuré dans le code final : 4,5:1 pour le texte courant, 3:1 pour les
éléments et grands textes concernés ; aucune validation numérique n’est déduite
d’une image générée. Les symboles de la tab bar seront des SF Symbols cohérents.

Les barres natives peuvent varier selon iOS ; ce qui doit rester constant est
la hiérarchie, la lisibilité et l’absence de recouvrement. Ne pas forcer une
ancienne tab bar uniquement pour reproduire la planche.

Les deux sources photo rejoignent le même cadrage puis « Ajouter à la file ».
L’appareil photo ne sauvegarde pas automatiquement dans Photos. Demander la
permission au moment du choix, avec une alternative en cas de refus.

Le statut « Cadre vérifié » du parcours Wi-Fi ne s’affiche qu’après vérification
de son identité. Le choix des réseaux provient du Raspberry. Le mot de passe
du cadre, celui du Wi-Fi et l’administration Linux restent trois sujets séparés.
« Face ID sera mis à jour » est conditionnel à son activation ; après un échec
Keychain, préciser que le changement serveur a tout de même réussi.

## Décision retenue

1. Clair/sombre automatiques, sur le style arrondi existant (cartes 20 pt,
   photos 12 pt et boutons 14/12 pt), sans refonte carrée.
2. Icône A validée ; source vectorielle native dans `ios/scripts/generate-icon.swift`.
3. Noms techniques retirés de l’interface et des labels VoiceOver des photos ;
   ordre, dates/heures et actions restent disponibles.
4. Parcours photo, mot de passe et Bluetooth validés comme fonctions à intégrer
   par lots vérifiés, puis InkyOS ultérieurement.

Le [plan technique](../../../docs/ios/PRODUCT-EVOLUTION-PLAN.md) décrit l’ordre,
les dépendances et les critères de livraison. InkyOS reste une phase ultérieure,
après qualification des services sur le Raspberry existant.

La réalisation et ses captures sont documentées dans le [rapport de validation](../../../docs/ios/reviews/2026-09-27-refinement-validation.md). Les états de livraison y sont distingués de la proposition.
