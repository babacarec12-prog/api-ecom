# Actions WooCommerce ajoutées

## Synchroniser le catalogue

Après avoir configuré `WOO_STORE_URL`, `WOO_CONSUMER_KEY` et
`WOO_CONSUMER_SECRET`, lancer :

```bash
python manage.py sync_woocommerce_catalog
```

La commande est idempotente. Elle synchronise les noms, descriptions,
catégories, prix, stocks, SKU, images et variantes dans PostgreSQL. Les produits
WooCommerce qui ne sont plus publiés sont désactivés localement sans être
supprimés. En production, cette commande devra être planifiée après la
connexion de la boutique réelle.

Toutes les opérations utilisent le même endpoint :

```http
POST /api/commerce/
Content-Type: application/json
```

Les actions ci-dessous sont WooCommerce-only. Le champ `platform` est facultatif ; s’il est fourni, il doit valoir `woocommerce`.

## Annuler une commande

```json
{
  "action": "cancel_order",
  "data": {
    "order_id": "38",
    "user_id": "221700000000",
    "reason": "Le client a changé d’avis",
    "platform": "woocommerce"
  }
}
```

WooCommerce : `PUT /wp-json/wc/v3/orders/{order_id}` avec `status=cancelled`.

## Demander un remboursement

```json
{
  "action": "request_refund",
  "data": {
    "order_id": "38",
    "amount": 2500,
    "reason": "Produit retourné",
    "platform": "woocommerce"
  }
}
```

WooCommerce : `POST /wp-json/wc/v3/orders/{order_id}/refunds`. Le MVP utilise `api_refund=false` : il enregistre le remboursement dans WooCommerce sans déclencher automatiquement un mouvement financier. L’exécution financière reste soumise à une validation humaine.

## Modifier les quantités d’une commande

`line_item_id` est l’identifiant de la ligne WooCommerce, pas le `product_id`. Une quantité `0` supprime la ligne.

```json
{
  "action": "update_order",
  "data": {
    "order_id": "38",
    "line_items": [
      {"line_item_id": "12", "quantity": 2},
      {"line_item_id": "13", "quantity": 0}
    ],
    "platform": "woocommerce"
  }
}
```

WooCommerce : `PUT /wp-json/wc/v3/orders/{order_id}`.

## Suivre un colis

```json
{
  "action": "get_tracking",
  "data": {
    "order_id": "38",
    "platform": "woocommerce"
  }
}
```

La réponse lit les métadonnées courantes des extensions de tracking et retourne `numero_suivi`, `transporteur`, `url_suivi` et `suivi_disponible`. WooCommerce natif ne fournit pas toujours ces informations sans extension de livraison.

## Valider un code promo

```json
{
  "action": "validate_coupon",
  "data": {
    "code": "BIENVENUE10",
    "platform": "woocommerce"
  }
}
```

WooCommerce : `GET /wp-json/wc/v3/coupons?code=...`.

## Vérifier le stock précis d’une variante

```json
{
  "action": "check_variant_stock",
  "data": {
    "product_id": "100",
    "variant_id": "105",
    "platform": "woocommerce"
  }
}
```

WooCommerce : `GET /wp-json/wc/v3/products/{product_id}/variations/{variant_id}`.

## Cas ne nécessitant pas une nouvelle action WooCommerce

- Comparer des produits : appeler `get_product` pour chaque identifiant puis comparer uniquement les champs retournés.
- Modifier ou vider un panier non commandé : stocker un panier conversationnel dans Supabase ; aucune commande WooCommerce ne doit être créée avant confirmation.
- Politique de livraison/retour : utiliser une FAQ ou une configuration administrable, pas une réponse inventée par Qwen.
- Hors-sujet, abus, répétition, message vide, emoji, image seule et langue : gérer dans n8n et le prompt.
- Demande humaine : exécuter le sous-workflow de transfert et mettre le bot en pause pour ce client.
