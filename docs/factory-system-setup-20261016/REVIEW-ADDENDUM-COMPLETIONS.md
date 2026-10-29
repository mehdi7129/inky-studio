# Décision de revue source — récupération après completion

2026-10-16. Ce delta s'ajoute au GO source de `REVIEW-ROOT.json` ; les quatre
fichiers et leurs hashes figés restent inchangés. Aucun schéma JSON, droit
runtime, effet matériel, publication ou flash n'est autorisé par ce document.

Une récupération système explicite peut être nécessaire après un boot NORMAL
dont le réseau est resté fermé. Le journal root conserve un historique borné de
64 completions immuables maximum, sans évincement. Une nouvelle opération
explicitement admise utilise un nouveau défi/session/boot/intention et peut
produire une nouvelle completion courante seulement après les vrais effets
setup et la vraie confirmation/inspection helper + NM. Les anciennes
completions restent de l'audit historique, jamais des grants d'effets.

La nouvelle completion a un nouvel identifiant et l'opération courante ; sa
publication initiale, l'initialisation, l'UUID, la clé et le SPKI restent les
mêmes. Le pays courant est porté par la nouvelle completion et son network-head.
Aucun ancien certificat n'est réinstallé et aucune recertification n'est
effectuée pour faire coïncider deux identifiants d'opération.

Pendant une nouvelle récupération non approuvée, le snapshot root conserve la
completion historique pour la sélection NORMAL, mais son état suit la nouvelle
opération. Le backend retourne `completion_id=null` sur le wire tant que cette
opération n'a pas sa completion courante. PHOTO factory exige que la completion
courante corresponde à la dernière opération approuvée ; une ancienne
completion ne permet pas de passer une récupération en cours. Les parseurs et
tests doivent distinguer historique de sélection et état de l'opération.

Un changement Wi-Fi normal sans nouvelle opération setup ne crée aucune
completion : seul le network-head suit le dernier vrai profil committed.
`inspect/status` sont readonly et peuvent retourner ce head historique avec
une observation live plus récente ; ils ne doivent ni modifier le head ni
exiger l'égalité de ces deux snapshots distincts. Une réponse de mutation
`resume` qui vient effectivement de rafraîchir le head lie ses nouveaux faits.

Pour ce lot, les mutations setup restent réservées au premier owner de la claim,
encore autorisé dans l'epoch courante. Les invités PHOTO n'obtiennent pas de
droits BLE/admin. L'absence ou la révocation du premier owner ne change pas la
sélection NORMAL et ne réaffiche jamais le QR factory. La récupération admin
après perte/révocation de cet owner n'est pas livrée par ce lot.
