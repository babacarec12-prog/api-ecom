# Compte rendu des tests Commerce

- URL : `https://scavenger-babied-tingly.ngrok-free.dev/api/commerce/`
- Résultat : **2 réussi(s), 0 échec(s), 9 ignoré(s)**

| Action | État | HTTP | Durée | Détail |
|---|---:|---:|---:|---|
| `search_products` | PASS | 200 | 2429 ms | Réponse conforme |
| `get_product` | PASS | 200 | 1361 ms | Réponse conforme |
| `check_variant_stock` | SKIP | - | 0 ms | Fournir --variant-id et un produit variable |
| `validate_coupon` | SKIP | - | 0 ms | Fournir --coupon |
| `get_order_status` | SKIP | - | 0 ms | Fournir --order-id |
| `get_tracking` | SKIP | - | 0 ms | Fournir --order-id |
| `create_order` | SKIP | - | 0 ms | Nécessite --allow-writes, --user-id et un produit |
| `update_order` | SKIP | - | 0 ms | Nécessite --allow-writes, --order-id et --line-item-id |
| `request_refund` | SKIP | - | 0 ms | Nécessite --allow-writes, --order-id et --refund-amount |
| `generate_payment` | SKIP | - | 0 ms | Nécessite --allow-payment, --order-id et --payment-amount |
| `cancel_order` | SKIP | - | 0 ms | Nécessite --allow-writes, --confirm-cancel, --order-id et --user-id |
