# Inventaire cryptographique pour le prochain build iOS

27 septembre 2026 — préparation technique, aucune déclaration administrative
envoyée par ce document. Le build TestFlight 1.0.0 (3) n’intègre pas Mbed TLS.

| Usage | Implémentation du nouveau code |
|---|---|
| Confidentialité et intégrité des commandes Bluetooth | Mbed TLS 4.1.1 et TF-PSA-Crypto embarqués, TLS 1.3 uniquement |
| Preuve du cadre | Certificat X.509 auto-signé, EC P-256, ECDSA/SHA-256, pin SHA-256 du SPKI lu sur le QR physique |
| HTTPS, photos, WebSocket | URLSession / Security Apple, identité adoptée vérifiée |
| Autorisations et mot de passe local | Keychain Apple ; propriétaire aléatoire de 32 octets, pas un algorithme propriétaire |
| Portée fonctionnelle | Configuration locale d’un cadre photo, aucun VPN ou outil général de chiffrement |

Le build script conserve la configuration cryptographique upstream ; la capacité
du binaire ne se limite donc pas à la seule cipher suite négociée pendant le banc.
Inventorier les fonctions embarquées depuis l’archive/configuration épinglées si le
formulaire l’exige. Les tickets de session et le 0-RTT ne sont pas utilisés.
Le framing GATT et les commandes Inky ne sont pas des algorithmes cryptographiques.

Apple distingue le chiffrement fourni par le système et les algorithmes standard
embarqués hors du système. Sa page de référence demande une déclaration française
pour la seconde catégorie lorsque l’app est distribuée en France.
[Référence Apple consultée le 27 septembre 2026](https://developer.apple.com/help/app-store-connect/reference/app-information/export-compliance-documentation-for-encryption).

L’ancienne déclaration automatique `ITSAppUsesNonExemptEncryption=false` est
retirée. Le prochain upload nécessitera les réponses exactes au questionnaire
App Store Connect et les éventuels documents demandés ; ni exemption, ni référence
d’autorisation, ni dépôt auprès de l’ANSSI ne sont inventés. Conserver la France
dans le périmètre souhaité et traiter les formalités avant distribution publique.

[Guide du questionnaire et des documents Apple](https://developer.apple.com/help/app-store-connect/manage-app-information/determine-and-upload-app-encryption-documentation).
