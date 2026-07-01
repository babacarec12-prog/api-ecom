# Modifications n8n — panier et parcours transactionnel v3

Effectuer ces changements sur une copie du workflow, puis publier seulement après les tests.

## 1. Configurer l'accès à l'API

1. Générer un secret long et aléatoire.
2. Ajouter dans le `.env` Django : `N8N_API_TOKEN=<secret>`.
3. Redémarrer Django.
4. Dans chaque nœud HTTP vers `/api/commerce/`, ajouter le header :
   - Nom : `X-API-Token`
   - Valeur : le même secret, stocké dans un credential n8n ou une variable d'environnement.
5. Ne jamais écrire le secret dans le system prompt ou les logs.

L'API conserve son comportement actuel tant que `N8N_API_TOKEN` est vide. Cette activation en deux temps évite de casser le workflow pendant la migration.

## 2. Connecter Django à Supabase

Exécuter `migrations.sql` dans l'éditeur SQL Supabase. Ajouter ensuite la chaîne PostgreSQL Supabase dans `.env` :

```text
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/postgres
DB_SSLMODE=require
```

Redémarrer Django. En local sans `DATABASE_URL`, SQLite continue de fonctionner.

## 3. Ignorer les doubles messages rapides

Après `Extraire message OpenWA`, ajouter un nœud `Wait` de 5 secondes. Ensuite, consulter une table ou un Data Store n8n contenant `{user_id, timestamp, message_id}`. Si un message plus récent existe pour le même client, arrêter cette exécution. Seule l'exécution du dernier message continue.

Ne pas utiliser `$getWorkflowStaticData` pour ce verrou : il n'est pas fiable entre plusieurs workers.

## 4. Vérifier le transfert humain avant Qwen

Ajouter un nœud HTTP `check_human_status` immédiatement après le filtre anti-doublon :

```json
{"action":"check_human_status","data":{"user_id":"{{$json.userId}}"}}
```

Ajouter un nœud `IF` :

- si `data.human_takeover = true`, envoyer uniquement « Vous êtes en contact avec notre équipe. Un agent va vous répondre très bientôt. » puis arrêter ;
- sinon, poursuivre vers la recherche/l'agent.

## 5. Ajouter les outils persistants

Créer des outils HTTP vers le même endpoint pour :

- `cart_add`, `cart_remove`, `cart_update_quantity`, `cart_view`, `cart_clear` ;
- `save_selection_list`, `get_product_by_position` ;
- `get_state`, `set_state`, `revert_state` ;
- `transfer_to_human`, `check_human_status`, `get_policy`.

Tous les outils liés au client doivent injecter automatiquement :

```javascript
user_id: $('Extraire message OpenWA').first().json.userId
```

Qwen ne doit jamais produire `user_id`, `product_id` ou un prix lorsqu'une valeur vérifiée existe déjà dans le contexte.

## 6. Rendre la liste déterministe

Après `search_products`, construire côté Code n8n un tableau maximum de 10 produits dans l'ordre exact de l'API. Enregistrer ce tableau avec `save_selection_list` avant de l'envoyer à Qwen. La réponse `2` doit appeler `get_product_by_position(position=2)` ; ne plus utiliser l'index d'une mémoire n8n volatile.

## 7. Créer et payer une commande sans doublon

Avant `create_order` :

1. appeler `cart_view` ;
2. afficher le récapitulatif réel ;
3. obtenir une confirmation explicite ;
4. appeler `set_state(confirming)` ;
5. construire une clé : `user_id + ':' + minute UTC + ':create_order'` ;
6. appeler `create_order` avec `user_id`, `idempotency_key` et sans panier inventé.

Après succès seulement, Django place l'état à `ordering`. Appeler ensuite `generate_payment` avec le vrai `order_id`, le vrai montant, `user_id` et une autre clé terminée par `:generate_payment`.

## 8. Retry et fallback

Conserver deux tentatives totales pour Qwen, espacées de 3 secondes. Ne jamais appliquer un retry n8n aveugle à `create_order` ou `generate_payment` sans réutiliser exactement la même `idempotency_key`. Après deux échecs Qwen, envoyer le fallback existant ou proposer le transfert humain.

## 9. Remplacer le prompt

Remplacer le system prompt de l'Agent IA par `system-prompt-v3.txt`. Changer la clé de mémoire en `:commerce-v7` pour ne pas réutiliser les anciens paniers halluciné​s.

## 10. Tests manuels minimum

Tester : liste puis choix 2, ajout de deux produits, correction « le 3 pas le 2 », changement de quantité, suppression, panier vide, confirmation, double confirmation, paiement avant commande, statut d'une commande d'un autre client, transfert humain puis nouveau message, politique de retour et deux messages envoyés en moins de cinq secondes.
