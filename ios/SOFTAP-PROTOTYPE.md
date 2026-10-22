# Prototype iOS SoftAP

Le QR v3 active un parcours Wi-Fi temporaire sans BLE. Le QR v2 conserve le parcours existant.

L'app utilise `NEHotspotConfiguration.joinOnce`, avec consentement iOS, puis une connexion TCP limitée au Wi-Fi. Elle vérifie le manifeste borné, le UUID et le pin SPKI avant le handshake TLS 1.3 MbedTLS existant. Le bootstrap exige son ALPN ; le profil normal conserve ses contrôles de date et d'identité.

Après claim et setup heure/pays FR, l'app reprend en TLS normal sur l'AP. Elle enregistre la transaction avant `wifi.prepare`, attend sa réponse durable, puis demande explicitement `wifi.activate`. Elle quitte ensuite sa configuration AP et confirme via HTTPS sur le LAN. Une connexion normale TCP au port 9443 du hostname LAN permet de terminer le setup et d'accéder aux photos.

Le locator réseau vient de l'origine observée par l'OS, indépendamment du UUID du cadre. Le nom cryptographique reste `frame-<UUID>.inky.invalid` ; un hostname réseau différent ne justifie aucune modification du pin ou des règles de certificat.

Les owner et transaction ID sont conservés dans le Keychain existant. Les paramètres AP restent en RAM, bornés à 30 minutes ; après relaunch, un nouveau scan est nécessaire. Le mot de passe domestique n'est pas persisté. Le QR ADOPTED ne crée pas de nouvelle autorité de claim.

Un refus explicite d'activate conserve l'AP et consulte le statut. Une issue ambiguë telle qu'un EOF peut conduire à chercher le LAN sous le même identifiant, sans replay automatique. Si le claim n'a jamais atteint le serveur, seule une nouvelle lecture du QR et une action explicite permettent de reprendre le même claimRequestID. La déconnexion invalide l'ancienne association joinOnce, qui doit être redemandée lors d'un retour AP ; une reprise LAN ne rejoint pas cet AP.

Le projet déclare l'entitlement `com.apple.developer.networking.HotspotConfiguration` et la description Local Network. Une livraison physique exige un provisioning profile contenant cet entitlement. Le Simulator compile l'app et valide les interfaces injectées, mais ne valide pas le consentement Hotspot, l'association radio ni le retour au LAN. Les tests host comprennent de vrais échanges TLS Swift/MbedTLS vers Python/OpenSSL.

La qualification iPhone/Pi et la livraison TestFlight sont des étapes distinctes de cette validation des sources.
