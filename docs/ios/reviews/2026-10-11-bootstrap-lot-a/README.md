# Revue visuelle — association initiale, lot A

Captures originales du test `BootstrapSetupUITests/testAssociationScreensKeepBentoLightAndDarkWithoutPhotoOrWiFiCompletion`, le 11 octobre 2026, sur le simulateur iPhone 15 Pro Max existant sous iOS 27. Les données et les états d'association sont synthétiques ; aucune connexion au cadre n'a eu lieu.

| État | Clair | Sombre |
| --- | --- | --- |
| Introduction | [Capture](introduction-light.png) | [Capture](introduction-dark.png) |
| Association enregistrée, préparation en attente | [Capture](pending-light.png) | [Capture](pending-dark.png) |
| Keychain indisponible, association à vérifier | [Capture](recovery-light.png) | [Capture](recovery-dark.png) |

La palette DEBUG est appliquée au sheet pour vérifier ses deux apparences. Le fond et la barre d'état de la vue parente peuvent conserver l'apparence claire : ces captures ne qualifient pas la propagation du thème système dans toute l'app. La version Release conserve l'apparence système des composants existants.

La revue des six captures confirme les cartes et boutons arrondis Bento, une hiérarchie lisible et l'absence de texte coupé dans ces trois états. L'écran de succès distingue l'association de la préparation du système. L'écran de récupération ne promet pas qu'une autorisation a été sauvegardée lorsque le Keychain a refusé l'enregistrement.

Les deux tests UI ciblés passent, avec vérification des pixels des palettes. Ces captures ne prouvent ni le scan d'un vrai QR, ni les permissions de l'iPhone, ni le fonctionnement Bluetooth ou e-ink.
