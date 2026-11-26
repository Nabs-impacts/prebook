# iPay Money (iMoney Encaissement) : API de paiement, résumé pour Prebook

Source officielle : https://docs.i-pay.money (index : https://docs.i-pay.money/llms.txt).
Ce fichier résume TOUTES les pages de la doc utiles au projet. En cas de doute ou de contradiction, la doc officielle fait foi. Ne pas deviner ce qui n'est pas écrit ici : le noter dans PROGRESS.md.

## 1. Base et authentification

- URL de base (sandbox et live) : `https://i-pay.money/api/v1`
- Sandbox et Live sont deux comptes séparés, avec des clés différentes. Une clé d'un environnement utilisée avec l'autre renvoie 401. Prévoir une configuration par environnement (variables distinctes), pas un simple booléen.
- Clé secrète `sk_sandbox_...` / `sk_live_...` : serveur uniquement. Clé publique `pk_...` : jamais utilisée par notre backend.
- Ne jamais journaliser l'en-tête `Authorization`, ni les clés, ni les numéros de téléphone ou données de paiement des clients.

En-têtes communs (tous les appels authentifiés, y compris les GET) :

```
Content-Type: application/json
Authorization: Bearer <SECRET_KEY>
Ipay-Target-Environment: sandbox | live
Ipay-Payment-Type: <voir chaque opération>
```

Erreurs d'authentification, vérifiées dans cet ordre : 400 `Bad Request: Missing params` (en-tête absent), 406 `Not Acceptable: Invalid Content Type`, 400 `Not Allowed Environment`, 400 `Not Allowed Payment Type`, 400 `Missing Authentication Key`, 401 `Unauthorized: No Valid Key`, 403 `Forbidden: Environment Not Available` (compte non validé pour l'environnement). Un 403 `Contact le support: support@i-pay.money` signifie compte non actif.

Règle de traitement : ne jamais rejouer automatiquement une erreur 400/401/403/404/406/422 sans corriger la requête. En cas de timeout sur une création, vérifier l'état réel avant de retenter.

## 2. Choix d'intégration pour Prebook : LIEN DE PAIEMENT HÉBERGÉ

`POST /payments` ne gère que le mobile money en appel direct et exige le numéro `msisdn` du client. Amana et Nita Online (MyNita) ne passent PAS par `POST /payments` : seulement par les liens de paiement. Décision : utiliser `POST /external_payments` pour toutes les commandes. Le client est redirigé vers la page iPay où il choisit son moyen de paiement (selon ceux activés sur le compte marchand). Notre site ne demande ni moyen de paiement ni numéro de téléphone.

Alternative non retenue : SDK JavaScript (`https://i-pay.money/checkout.js`, bouton avec clé publique et callback navigateur). Non retenu car la clé publique et le callback dépendent du navigateur ; la création côté serveur est plus sûre.

## 3. Créer un lien de paiement : `POST /external_payments`

En-tête : `Ipay-Payment-Type: external_payment`

| Champ | Type | Règle |
| - | - | - |
| `title` | string | Obligatoire |
| `description` | string | Optionnel |
| `amount` | entier ou null | Minimum 50 (XOF) |
| `reference` | string | Optionnel, min 32 caractères. Si fournie : valeur aléatoire privée d'au moins 128 bits. Si omise : générée par l'API (recommandé) |
| `shouldExpire` | bool | Toujours vrai en v1 |
| `on_success_redirection_url` | string | HTTPS obligatoire |
| `on_failed_redirection_url` | string | HTTPS obligatoire |

Exemple :

```json
{
  "title": "Commande #1001",
  "description": "Transaction de la commande #1001",
  "amount": 15000,
  "on_success_redirection_url": "https://votre-site.com/commandes/1001/succes",
  "on_failed_redirection_url": "https://votre-site.com/commandes/1001/echec"
}
```

Réponse 200 : `title`, `amount`, `reference`, `status` (`initiated`), `should_expire`, `page_url`.
Erreurs : 404 `Account not found` (compte introuvable ou inactif pour l'environnement), 422 avec `{"errors": [...]}` (validation, ou `reference` déjà utilisée).

Règles :
- Le lien expire toujours 30 minutes après sa création. Ne jamais rediffuser un vieux lien : en recréer un.
- Pas de clé d'idempotence, pas de garantie sous appels concurrents : l'idempotence se gère de notre côté.
- Stocker `reference` (identifiant de consultation, SECRET) et `page_url`.
- La redirection du client vers l'URL de succès n'est PAS une preuve de paiement.

## 4. Consulter un lien : `GET /external_payments/{reference}`

- Aucune clé requise (opération publique). `reference` : 32 caractères minimum.
- Toute personne connaissant la référence peut la consulter et voir des infos du payeur une fois payé : la référence est un secret. Ne jamais la journaliser ni l'exposer côté client ou dans une réponse publique.

Trois formes de réponse 200 :
1. Paiement terminé : `reference`, `amount`, `country`, `currency`, `transaction_id`, `msisdn`, `customer_name`, `status` (`succeeded` ou `failed` uniquement), `created_at`.
2. En attente d'un premier essai : `message`, `status: "initiated"`, `reference`, `page_url`.
3. Expiré (30 min sans paiement abouti) : `message`, `has_expire: true`, `status: "cancelled"`, `reference`. Définitif, pas une erreur transitoire.

Référence inconnue : 404 `External payment not found`.
Limite : un paiement remboursé n'est plus rattaché au lien et la route renvoie alors la forme "initiated". Cette route ne détecte donc PAS les remboursements (utiliser le webhook `payment_refunded` ou `GET /payments/{reference}`).
Un lien accepte plusieurs essais : un premier paiement `failed` n'empêche pas un second essai réussi tant que le lien n'a pas expiré.

## 5. Consulter une transaction : `GET /payments/{reference}`

- En-têtes : les 4 communs, avec `Ipay-Payment-Type: mobile`.
- `reference` accepte la référence interne iPay (champ `reference` du webhook) ou notre `transaction_id` (nommé `external_reference`).
- Réponse 200 : `public_reference`, `external_reference`, `reference`, `status` (`initiated`, `pending`, `succeeded`, `failed`, `refunded`), `msisdn`, `amount` (entier), `validated_at` (date ou null).
- 404 `Payment Not Found` si inconnue pour le compte authentifié.
- Doc FAQ : pour savoir si un paiement est réellement réussi, vérifier que cette route renvoie `succeeded`, ou traiter un webhook authentifié puis confirmer le statut pour les actions sensibles (livraison).
- À confirmer avec le support : que cette route fonctionne bien avec la `reference` iPay d'un paiement fait via un lien.

## 6. Lister les transactions : `GET /payments` (réconciliation, affichage)

- Filtres : `query` (texte libre), `status`, `created_from`, `created_to` (dates), `items` (taille de page, 25 par défaut). Filtres combinés en ET.
- Réponse : tableau JSON brut, sans métadonnées de pagination, paramètre de page non documenté.
- Les valeurs `status` et `payment_method` y sont formatées pour l'affichage (ex. `Succeeded`, `Airtel Ne`) : ne JAMAIS les comparer dans le code. À utiliser pour de l'affichage ou de l'export uniquement.
- Champs d'un élément : `id`, `reference`, `status`, `amount`, `fees`, `payment_method`, `net_amount`, `platform`, `device`, `failure_reason`, `country`, `currency`, `external_reference`, `msisdn`, `customer_name`, `created_at`, `validated_at`.
- Pour la réconciliation de nos commandes, préférer la consultation individuelle.

## 7. Paiement mobile direct : `POST /payments` (non utilisé pour l'instant)

En-tête `Ipay-Payment-Type: mobile`. Corps : `amount` (entier, min 25 XOF live, 50 sandbox), `country` (`NE` ou `BJ`), `currency` (`XOF`), `msisdn`, `transaction_id` (unique dans le compte), `customer_name`. Réponse 200 : `status`, `reference`, `public_reference`, `meta_data`. Le statut de création n'est jamais définitif. Doublon : 422 `External Reference Not Valid` (live).

## 8. Webhooks

Configuration (dashboard marchand : Développeurs, Webhooks, Ajouter) : URL HTTPS publique et stable, `Hash secret` que NOUS définissons, et les événements à recevoir. Un webhook sandbox ne s'applique pas au live : reconfigurer le webhook sur le compte live avec une URL, un secret propre et les mêmes événements.

Événements (les seuls qui existent) : `payment_created`, `payment_pending`, `payment_succeeded`, `payment_failed`, `payment_refunded`. Activer au minimum succeeded, failed, refunded (et pending si utile).

Requête reçue : `POST` JSON avec les en-têtes `Content-Type: application/json`, `Accept: application/json`, `Secret-Hash: <notre secret>`.

Vérification : `Secret-Hash` est un secret statique partagé, recopié tel quel. Ce n'est PAS un HMAC du corps. Comparer à notre secret (comparaison à temps constant). Répondre vite en `2xx`, puis traiter (traitement long en tâche de fond).

Payload :

```json
{
  "data": {
    "external_reference": "ORDER-2026-001",
    "reference": "ipay_ref_123",
    "status": "succeeded",
    "msisdn": "97000000",
    "net_amount": 950,
    "amount": 1000,
    "failure_reason": null,
    "customer_name": "Client Demo",
    "payment_method": "credit_card",
    "validated_at": "2026-06-04T10:30:00.000Z"
  }
}
```

Champs : `external_reference`, `reference` (référence interne iPay), `status` (`initiated`, `pending`, `succeeded`, `failed`, `refunded`), `msisdn`, `net_amount` (après frais), `amount` (brut), `failure_reason`, `customer_name`, `payment_method`, `validated_at`.
Champs conditionnels : `external_payment_reference` (présent quand le paiement est rattaché à un lien de paiement : c'est le champ qui doit permettre de retrouver notre commande), `dynamic_payment_reference`.

Nouvel essai : la notification est envoyée UNE fois. Un envoi qui échoue (hors 2xx, timeout, endpoint injoignable) n'est PAS rejoué (le rattrapage à 10 minutes ne couvre que le cas où aucun envoi n'a eu lieu). Il faut donc réconcilier systématiquement par consultation API ; l'absence de webhook ne signifie pas l'absence de changement. La consultation fait foi, pas la notification.

Bonnes pratiques de la doc : idempotence sur la `reference` iPay (une notification peut arriver en double), ne pas dépendre de l'ordre des notifications (se fier au `status` reçu), re-vérifier le statut pour les actions sensibles, réconcilier les paiements restés en attente.

## 9. Sandbox et tests

- Mêmes opérations qu'en live, clé sandbox et `Ipay-Target-Environment: sandbox`. Aucune transaction réelle. Le sandbox est ouvert dès la confirmation de l'inscription.
- Pour `POST /payments` mobile, pays NE, seuls ces numéros fonctionnent (autres : 400 `Incorrect MSISDN`) :
  - `40410000000`, `40410000001` : succès
  - `40410000002`, `40410000003` : erreur (failed)
  - `40410000004`, `40410000005` : fonds insuffisants (failed)
  - `40410000006`, `40410000007` : refusé (failed)
  - `40410000008`, `40410000009` : pending puis succeeded après environ 90 secondes
- Montant minimum sandbox mobile : 50 XOF.
- La doc ne décrit pas le comportement des liens de paiement en sandbox : le tester et le noter dans PROGRESS.md.
- La réponse à un doublon en sandbox n'est pas garantie identique au live : ne pas en faire une assertion de test.
- Le webhook doit pointer vers une URL HTTPS publique : en développement, utiliser un tunnel (cloudflared, ngrok).

## 10. Passage en production

- L'accès live n'est pas automatique : soumission des informations légales depuis le dashboard puis validation du dossier par l'équipe iPay. Ne promettre aucun délai.
- Confirmer les moyens de paiement activés sur le compte pour le Niger, n'ouvrir en live que ceux testés en sandbox.
- Mêmes endpoints : seuls la clé et l'en-tête d'environnement changent. Clé live dans une variable séparée.
- Reconfigurer le webhook sur le compte live.
- Faire un paiement réel contrôlé de faible montant avant l'ouverture publique : vérifier la réception du webhook et la cohérence du statut consulté. Prévoir des alertes sur erreurs API, webhooks hors 2xx et paiements durablement en attente.

## 11. Frais et reversement (info métier, hors code)

- Moyens : mobile money (MTN Bénin, Moov Bénin, Moov Niger, Airtel Niger, Zamani Niger), carte bancaire, STA (Amana, Nita Online), BOA Niger. Selon ceux activés sur le compte.
- Frais d'encaissement par moyen, supportés par le client OU par le marchand (configuration par compte et par moyen). Le payload expose `amount` (brut) et `net_amount` (net).
- Reversement : uniquement depuis le dashboard (pas d'API). Seuls les paiements réussis de plus de 3 jours sont reversables. Modes : My NITA et Amana (frais de retrait 1 %), virement bancaire (0 %), rechargement compte PayOUT (0 %).

## 12. Points à confirmer avec le support iPay (support@i-pay.money)

1. `external_payment_reference` dans le webhook est-il exactement la `reference` renvoyée à la création du lien ?
2. `GET /payments/{reference}` fonctionne-t-il avec la `reference` iPay d'un paiement fait via un lien ?
3. Quand les frais sont supportés par le client, le champ `amount` du webhook inclut-il les frais ?
4. Comportement des liens en sandbox (moyens simulés, numéros de test).
5. Limites de débit.
6. Peut-on passer un identifiant de commande ou des métadonnées dans la création du lien ?
