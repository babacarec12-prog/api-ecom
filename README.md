# AI Commerce Assistant API

API Django REST à endpoint unique pour relier un agent IA/n8n à Shopify,
WooCommerce et Stripe.

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

Pour `create_order`, la plateforme peut être indiquée une fois :

```json
{
  "action": "create_order",
  "data": {
    "user_id": "2250XXXXXXXX",
    "platform": "shopify",
    "cart": [
      {"product_id": "123", "variant_id": "789", "quantity": 2}
    ]
  }
}
```

Elle peut également figurer dans chaque article. Un panier mixant Shopify et
WooCommerce est refusé, car chaque plateforme doit créer sa propre commande.
`variant_id` est facultatif : la première variante Shopify est alors utilisée.

Pour `get_order_status`, fournir `platform` est recommandé. Sans ce champ, l'API
cherche la commande successivement sur Shopify et WooCommerce.

Le champ `amount` de `generate_payment` doit être exprimé dans la plus petite
unité Stripe de la devise configurée (par exemple `8900` XOF).

## Démarrage public pour n8n Cloud

Renseigner le vrai token dans `.env` :

```dotenv
NGROK_AUTHTOKEN=votre_token_ngrok
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

Utiliser cette URL dans le nœud HTTP Request de n8n. Le tunnel et Django restent
actifs tant que le terminal reste ouvert ; `Ctrl+C` arrête proprement les deux.
Si Django est déjà actif sur le port 8000, le script le réutilise et ne l'arrête
pas à la fermeture.

## Vérification

```powershell
python manage.py check
python manage.py test
```

En production, remplacer `DJANGO_SECRET_KEY`, désactiver `DJANGO_DEBUG`, limiter
`DJANGO_ALLOWED_HOSTS`, servir Django derrière HTTPS et protéger cet endpoint au
niveau de la passerelle/API ou de n8n.
