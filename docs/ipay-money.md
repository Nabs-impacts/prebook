# Webhooks — iMoney Encaissement (iPay)

> **Source officielle :** [docs.i-pay.money/guides/webhooks](https://docs.i-pay.money/guides/webhooks)  
> **Objet :** Recevez et sécurisez les notifications de changement d'état des paiements.

Les webhooks permettent à **iMoney Encaissement** d'envoyer automatiquement une notification à votre application lorsqu'un paiement change d'état. Utilisez-les pour mettre à jour une commande, synchroniser un back-office ou déclencher un traitement interne sans interroger l'API en continu.

Un webhook est un **complément** à la consultation de statut, pas un remplacement : la notification vous prévient dès qu'un état change, tandis que l'endpoint *Consulter une transaction* donne le statut à l'instant de l'appel et sert de secours ou de réconciliation.

---

## Table des matières

1. [Créer un webhook](#créer-un-webhook)
2. [Événements disponibles](#événements-disponibles)
3. [Recevoir une notification](#recevoir-une-notification)
4. [Format du payload](#format-du-payload)
5. [Champs du payload](#champs-du-payload)
6. [Comportement de nouvel essai](#comportement-de-nouvel-essai)
7. [Consulter l'historique](#consulter-lhistorique)
8. [Bonnes pratiques](#bonnes-pratiques)

---

## Créer un webhook

Depuis le tableau de bord marchand, ouvrez **Développeurs**, puis **Webhooks**. Cliquez ensuite sur **Ajouter** pour enregistrer un nouveau webhook.

Le formulaire demande les informations suivantes :

| Champ | Description |
| :--- | :--- |
| **URL** | URL de votre endpoint de réception. Si le protocole n'est pas renseigné, iMoney Encaissement ajoute automatiquement `https://`. |
| **Hash secret** | Valeur que vous définissez. iMoney Encaissement la renvoie telle quelle dans l'en-tête `Secret-Hash` de chaque notification, pour que votre serveur la compare à ce que vous avez configuré ici. |
| **Événements créés** | Active les notifications `payment_created`. |
| **Événements en attente** | Active les notifications `payment_pending`. |
| **Événements réussis** | Active les notifications `payment_succeeded`. |
| **Événements échoués** | Active les notifications `payment_failed`. |
| **Événements remboursés** | Active les notifications `payment_refunded`. |

Vous pouvez activer un ou plusieurs événements sur le même webhook. Seuls les événements cochés sont envoyés à l'URL configurée. Après avoir choisi les événements à recevoir, cliquez sur **Enregistrer**.

> **Important — Nature du `Secret-Hash` :**  
> Ce n'est **pas** une signature calculée à partir du corps de la notification (pas de HMAC, pas de hash du payload). C'est un **secret partagé statique** : vous choisissez sa valeur en créant le webhook, et iMoney Encaissement se contente de la recopier telle quelle dans l'en-tête `Secret-Hash` à chaque envoi. Votre serveur doit simplement comparer la valeur reçue à celle que vous avez configurée — il n'y a rien à recalculer.

> **Attention :**  
> Ne partagez jamais le hash secret de votre webhook. C'est la seule information qui permette à votre serveur de vérifier qu'une notification provient bien de iMoney Encaissement plutôt que d'un tiers qui aurait deviné votre URL.

---

## Événements disponibles

Cinq événements existent, tous liés au cycle de vie d'un paiement :

| Événement | Quand il est envoyé |
| :--- | :--- |
| `payment_created` | Le paiement vient d'être créé. |
| `payment_pending` | Le paiement passe à l'état en attente. |
| `payment_succeeded` | Le paiement est validé avec succès. |
| `payment_failed` | Le paiement échoue. |
| `payment_refunded` | Le paiement est remboursé. |

Il n'existe pas d'autre événement que ces cinq : n'activez que ceux dont votre intégration a réellement besoin.

---

## Recevoir une notification

Lorsqu'un événement actif se produit, iMoney Encaissement envoie une requête **`POST`** vers votre URL avec un corps JSON et les en-têtes suivants :

```http
Content-Type: application/json
Accept: application/json
Secret-Hash: votre_hash_secret
```

### Exigences pour votre endpoint

Votre serveur doit :
1. **Vérifier** que l'en-tête `Secret-Hash` correspond bien à la valeur configurée dans le dashboard.
2. **Traiter** le corps JSON de la requête.
3. **Retourner** une réponse HTTP `2xx` pour confirmer la bonne réception.

Les réponses hors `2xx` et les erreurs réseau (timeout, endpoint injoignable) sont enregistrées dans l'historique du webhook.

---

## Format du payload

Toutes les notifications utilisent la même structure JSON de base :

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

---

## Champs du payload

### Champs standards (toujours présents)

| Champ | Description |
| :--- | :--- |
| `external_reference` | Référence envoyée par votre système lors de la création du paiement (votre `transaction_id`). |
| `reference` | Référence interne iMoney Encaissement du paiement. |
| `status` | Statut actuel du paiement : `initiated`, `pending`, `succeeded`, `failed` ou `refunded`. |
| `msisdn` | Numéro de paiement du client. |
| `net_amount` | Montant net après frais. |
| `amount` | Montant brut du paiement. |
| `failure_reason` | Raison de l'échec lorsque le paiement a échoué, sinon `null`. |
| `customer_name` | Nom du client lorsque l'information est disponible. |
| `payment_method` | Moyen de paiement utilisé (voir la documentation des moyens de paiement). |
| `validated_at` | Date de validation du paiement lorsque disponible (format ISO 8601), sinon `null`. |

### Champs conditionnels

Selon l'origine du paiement, iMoney Encaissement peut aussi ajouter les champs suivants (ils ne sont pas présents sur toutes les notifications) :

| Champ conditionnel | Présent quand |
| :--- | :--- |
| `dynamic_payment_reference` | Le paiement est rattaché à un paiement dynamique. |
| `external_payment_reference` | Le paiement est rattaché à un lien de paiement. |

> **Note sur les paiements échoués :**  
> Sur un paiement échoué, `failure_reason` porte le motif du refus lorsqu'il est fourni et `validated_at` reste `null`. Les valeurs possibles de `status` et le contrat complet des champs d'un paiement (types, contraintes) sont décrits dans la section *Consulter une transaction* de la documentation API.

---

## Comportement de nouvel essai

iMoney Encaissement envoie la notification **une fois** dès que l'événement se produit, puis programme **10 minutes plus tard** un envoi de rattrapage.

Ce rattrapage ne part **que si aucune tentative d'envoi n'a été enregistrée** pour cet événement. Or, une tentative est enregistrée dans les deux cas :
- Quand votre serveur a répondu (quel que soit le code HTTP) ;
- Quand l'envoi a échoué (endpoint injoignable, réponse hors `2xx`, timeout).

### Ce qu'il faut en retenir

- **Un envoi qui échoue n'est pas rejoué :** le rattrapage de 10 minutes ne couvre que le cas où aucun envoi initial n'a eu lieu, pas celui d'un envoi qui s'est mal passé.
- **Pas de relances illimitées :** il n'existe pas de mécanisme de retry exponentiel ni de nombre de tentatives configurable.
- **Basculer sur l'API en cas d'échec :** dès lors qu'une tentative a échoué, votre application ne recevra plus de notification pour cet événement et doit se rabattre sur *Consulter une transaction* pour connaître le statut définitif.

> **Règle d'or :**  
> Ne considérez jamais l'absence de webhook comme une absence de changement d'état, et ne bâtissez pas votre intégration sur l'idée qu'un échec sera rattrapé. Réconciliez systématiquement par consultation API, en particulier pour les paiements restés `pending` plus longtemps qu'attendu. **C'est la consultation API, et non la notification, qui fait foi.**

---

## Consulter l'historique

La page **Webhooks** du tableau de bord affiche les webhooks configurés avec leur URL, les événements actifs, leur date de création et les actions disponibles.

Pour chaque webhook, le bouton **Logs** permet de consulter l'historique des tentatives d'envoi (y compris l'envoi de rattrapage le cas échéant) avec les informations suivantes :

- La référence du paiement (`reference`) ;
- L'événement envoyé ;
- Le statut HTTP retourné par votre serveur ;
- Le corps de la requête envoyée ;
- La réponse retournée par votre serveur ;
- La date d'envoi.

Le détail d'un log permet de vérifier le payload complet et les informations du paiement concerné.

---

## Bonnes pratiques

1. **Utilisez une URL HTTPS publique et stable.**
2. **Vérifiez toujours l'en-tête `Secret-Hash`** avant de traiter la notification — il s'agit d'une comparaison directe de chaîne avec la valeur configurée dans le dashboard, pas d'un calcul cryptographique.
3. **Retournez rapidement une réponse HTTP `2xx`** dès réception, avant de lancer un traitement métier lourd ou asynchrone (afin d'éviter tout timeout).
4. **Rendez votre traitement idempotent** en utilisant la référence iMoney Encaissement (`data.reference`) : ne traitez pas deux fois le même événement si une notification vous parvient en double.
5. **Ne dépendez pas de l'ordre exact des notifications :** vérifiez toujours le champ `status` reçu plutôt que de supposer une séquence stricte d'arrivée.
6. **Réconciliez les paiements en attente :** n'attendez pas indéfiniment un webhook qui n'arrive jamais et vérifiez les paiements restés `pending` via l'endpoint *Consulter une transaction*.
7. **Testez en Sandbox avant la production :** éprouvez vos règles avec les numéros de test du guide *Sandbox et tests* (qui simulent succès, échec ou mise en attente), puis reconfigurez l'URL et le `Secret-Hash` sur votre compte Live lors du passage en production.