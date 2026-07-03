# AI Commerce Assistant API

API Django REST à endpoint unique pour relier un agent IA/n8n à WooCommerce
et PayTech pendant la phase MVP.

## Installation

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Renseigner auparavant les identifiants réels dans `.env`. Le fichier est ignoré
par Git afin d'éviter la publication des secrets.

Pour une boutique créée avec Local et son certificat auto-signé, utiliser son
adresse locale HTTPS et `WOO_VERIFY_SSL=False`. Cette option doit rester à
`True` sur une boutique hébergée en production.

## Endpoint

Toutes les opérations utilisent `POST /api/commerce/` avec l'en-tête
`Content-Type: application/json`.

```json
{
  "action": "search_products",
  "data": {"query": "nike air max"}
}
```

### Contrat recommandé pour n8n et OpenWA

Le workflow n8n principal utilise une seule action, `message_turn`. Django lit
l'état persistant, comprend le français ou le wolof avec Kimi, exécute l'action
WooCommerce et renvoie directement une réponse strictement en français.

```json
{
  "action": "message_turn",
  "data": {
    "user_id": "221700000000",
    "session_key": "openwa-session",
    "message_id": "message-unique-id",
    "timestamp": 1783012345000,
    "message": "dama bëgg gis produits yi"
  }
}
```

La réponse contient `message`, `silent`, `trace_id`, l'analyse et le résultat
métier. Quand un conseiller a pris la main, `silent` vaut `true` et n8n
n'envoie aucun message automatique. Le workflow à importer est
`n8n_ai_ecom_corrige.json` (Backend Unifié v13).

### Contrat avancé `execute_intent`

Le workflow conversationnel doit appeler une seule action metier, `execute_intent`.
Kimi classe le message, tandis que Django valide les parametres, lit l'etat
persistant et execute WooCommerce/PayTech.

```json
{
  "action": "execute_intent",
  "data": {
    "user_id": "221700000000",
    "session_key": "openwa-session",
    "timestamp": "message-unique-id",
    "idempotency_key": "221700000000:message-unique-id:search_products",
    "intention": "search_products",
    "params": {"query": "batterie"},
    "confidence": 0.96,
    "langue_detectee": "francais",
    "reformulation": "Le client cherche une batterie."
  }
}
```

Intentions prises en charge : catalogue et produit, variantes, panier, commande,
paiement, statut et suivi, annulation, remboursement, modification, coupon,
politiques de la boutique et transfert humain.

Les actions destructives ou financieres (`cart_clear`, `create_order`,
`cancel_order`, `request_refund`, `update_order`) ne sont jamais executees au
premier appel. L'API renvoie `requires_confirmation: true` et memorise l'action.
Le tour suivant doit envoyer `confirm_action` pour executer ou
`cancel_pending_action` pour abandonner :

```json
{
  "action": "execute_intent",
  "data": {
    "user_id": "221700000000",
    "intention": "confirm_action",
    "params": {},
    "confidence": 0.99
  }
}
```

Une confiance inferieure a `0.6` produit une clarification et aucun appel au
fournisseur. Chaque reponse contient l'intention, les indicateurs
`executed`/`requires_confirmation`/`requires_clarification`, le resultat et
l'etat transactionnel courant.

Pour `create_order`, la plateforme peut être indiquée une fois :

```json
{
  "action": "create_order",
  "data": {
    "user_id": "2250XXXXXXXX",
    "platform": "woocommerce",
    "cart": [
      {"product_id": "123", "variant_id": "789", "quantity": 2}
    ]
  }
}
```

Elle peut également figurer dans chaque article. Pendant le MVP, seule la
valeur `woocommerce` est acceptée. `variant_id` est facultatif pour un produit
WooCommerce simple et requis lorsque le client choisit une variante précise.

Pour `get_order_status`, `platform` est facultatif et vaut toujours
`woocommerce` pendant le MVP.

Actions WooCommerce complémentaires disponibles :

- `cancel_order` : annuler une commande ;
- `request_refund` : enregistrer une demande de remboursement sans mouvement financier automatique ;
- `update_order` : modifier les quantités des lignes existantes ;
- `get_tracking` : lire le transporteur, le numéro et l’URL de suivi ;
- `validate_coupon` : vérifier un code promotionnel ;
- `check_variant_stock` : vérifier le prix et le stock exacts d’une variante.

Les exemples JSON et limites sont détaillés dans `woocommerce-actions.md`.

Le champ `amount` de `generate_payment` doit être un montant entier positif dans
la devise PayTech configurée (par exemple `8900` XOF). La réponse contient
`payment_url`, `token`, `reference` et `provider: paytech`.

Configurer PayTech dans `.env` :

```dotenv
PAYTECH_API_KEY=votre_cle_api
PAYTECH_API_SECRET=votre_cle_secrete
PAYTECH_API_URL=https://paytech.sn/api/payment/request-payment
PAYTECH_CURRENCY=XOF
PAYTECH_ENV=test
PAYTECH_IPN_URL=https://votre-domaine.example/api/paytech/ipn/
PAYTECH_SUCCESS_URL=https://votre-domaine.example/paiement/succes/
PAYTECH_CANCEL_URL=https://votre-domaine.example/paiement/annule/
```

Utiliser `PAYTECH_ENV=prod` uniquement avec les clés et URL de production.

## Démarrage public pour n8n Cloud

Renseigner le vrai token dans `.env` :

```dotenv
NGROK_AUTHTOKEN=votre_token_ngrok
N8N_API_TOKEN=un-secret-long-et-aleatoire
COMMERCE_API_URL=https://xxxx.ngrok-free.app/api/commerce/
```

Puis lancer une seule commande depuis la racine du projet :

```powershell
python start.py
```

Le script utilise automatiquement `.venv`, démarre Django, attend son écoute sur
le port 8000, ouvre le tunnel ngrok, puis affiche une URL semblable à :

```text
https://xxxx.ngrok-free.app/api/commerce/
```

Le domaine de `COMMERCE_API_URL` est demandé explicitement à ngrok afin que le
workflow conserve une URL stable. Le script ferme les anciens processus de ce
projet et les tunnels périmés avant chaque démarrage. Le tunnel et Django restent
actifs tant que la fenêtre reste ouverte.

Sous Windows, il est également possible de double-cliquer sur
`DEMARRER_API.bat` sans utiliser le terminal.

### Workflow n8n (Backend Unifié v13)

Importer `n8n_ai_ecom_corrige.json` puis :

1. Vérifier le credential existant **OpenWA account 2** sur `Send OpenWA`.
2. Sauvegarder puis publier/activer le workflow.
3. Démarrer l'API avec `DEMARRER_API.bat`.

Le workflow ne contient plus Kimi ni la logique métier. Il transmet le message à
`message_turn` et renvoie la réponse française fournie par Django. Le token API
est intégré uniquement dans cette version de test et doit devenir un credential
n8n avant la production.

## Vérification

```powershell
python manage.py check
python manage.py test
```

En production, remplacer `DJANGO_SECRET_KEY`, désactiver `DJANGO_DEBUG`, limiter
`DJANGO_ALLOWED_HOSTS`, servir Django derrière HTTPS et protéger cet endpoint au
niveau de la passerelle/API ou de n8n.
