# Suivi de conformité au cahier des charges

Ce fichier suit l'avancement réel du projet. La référence normative reste `cdc.md`.

## Règles de validation

Une exigence ne passe à **Terminée** que si :

1. le code est implémenté ;
2. les tests automatisés passent ;
3. le parcours de bout en bout est validé sur les services réels ;
4. la configuration de production est documentée sans secret dans le dépôt.

États utilisés : **À faire**, **En cours**, **Bloqué externe**, **Terminé**.

## Phase 1 — MVP mono-boutique

| Lot | Exigence CDC | État initial | Critère de sortie |
|---|---|---|---|
| 1 | Contrat OpenWA → n8n → Kimi → Django → Kimi → OpenWA | En cours | Une conversation complète réussit sans boucle ni réponse technique |
| 2 | API Django et 24 actions métier | En cours | Contrats, erreurs, sécurité et tests de toutes les actions validés |
| 3 | WooCommerce réel | En cours | Catalogue, variantes, stock, commande et statut testés sur une boutique réelle |
| 4 | Panier et machine d'états PostgreSQL | En cours | Parcours recherche → panier → confirmation validé de bout en bout |
| 5 | Paiement PayTech | En cours | Lien réel, callback signé, statut et idempotence validés |
| 6 | Mémoire `message_history` | À faire | Trois derniers échanges utilisés sans fuite entre clients |
| 7 | Transfert humain | En cours | Bot suspendu, commerçant notifié et reprise contrôlée |
| 8 | Déploiement Render/Supabase | En cours | Migrations, variables et health check validés en production |
| 9 | Sécurité et observabilité | En cours | Secrets retirés des JSON, limite 60/min, logs et erreurs conformes |
| 10 | Tests d'acceptation MVP | À faire | Scénarios français, wolof, panier, commande, paiement et humain réussis |

## Phase 2 — SaaS

| Lot | Exigence CDC | État initial |
|---|---|---|
| 11 | Comptes commerçants et authentification JWT | À faire |
| 12 | Isolation multi-tenant et multi-boutiques | À faire |
| 13 | Dashboard commerçant et configuration IA | À faire |
| 14 | Interface et rôles des agents humains | À faire |
| 15 | Plans, quotas et facturation PayTech | À faire |
| 16 | Super administration et métriques SaaS | À faire |

## Journal de réalisation

### 4 juillet 2026 — Lot 1

- Workflow CDC créé dans `workflow-cdc-v1.json`.
- Structure vérifiée : 13 nœuds, toutes les connexions pointent vers un nœud existant.
- Corps Moonshot et Django construits avant les nœuds HTTP afin d'éviter les erreurs d'expression complexes de n8n 2.1.5.
- Aucun token Kimi ou Django n'est enregistré en clair dans ce nouveau workflow.
- Les 62 tests Django passent.
- État maintenu à **En cours** jusqu'au test réel OpenWA → n8n → Django → OpenWA.
- Premier transport WhatsApp validé par le client.
- Actions Render validées directement : `search_products`, `cart_view` et `get_policy` répondent avec `success=true`.
- Clé Kimi validée directement avec `moonshot-v1-8k`.
- Workflow renforcé avec classification locale de secours et formulation déterministe depuis les données Django.
- Syntaxe des six nœuds Code vérifiée automatiquement.

### 4 juillet 2026 — Lot 2

- Architecture n8n à 13 nœuds verrouillée ; le débogage du nœud 09 est reporté à la recette du lot 1.
- Champ `api_logs.error_message` aligné sur le CDC avec migration de renommage.
- Limite Render alignée à 60 requêtes/minute.
- Formulation interdite « service indisponible » retirée du parcours `message_turn`.
- Les actions inconnues utilisent désormais le contrat d'erreur uniforme avec HTTP 400.
- Test automatique ajouté : les 24 actions du CDC sont exposées et chaque action autorisée possède un handler.
- 63 tests Django passent et aucune migration supplémentaire n'est détectée.

### 4 juillet 2026 — Lot 3

- Synchronisation persistante WooCommerce → PostgreSQL ajoutée.
- Noms, descriptions, catégories, prix, stocks, SKU, images et variantes sont synchronisés.
- Commande `python manage.py sync_woocommerce_catalog` ajoutée et documentée.
- Synchronisation idempotente ; les anciens produits WooCommerce sont désactivés sans suppression.
- Variables WooCommerce déclarées dans le Blueprint Render sans secret en clair.
- Test de normalisation du catalogue et test d'idempotence ajoutés.
- 65 tests Django passent ; test réel bloqué jusqu'à réception des accès WooCommerce.

### 4 juillet 2026 — Lot 4

- Le panier distingue désormais les variantes d'un même produit.
- `variant_id` est persisté, affiché dans le panier et transmis à la création de commande.
- Prix et disponibilité de la variante sont vérifiés avant ajout.
- Une modification ou suppression ambiguë exige de préciser la variante.
- Le catalogue interne et WooCommerce partagent le même contrat de vérification des variantes.
- Migration `0009_cart_variant` ajoutée.
- 66 tests Django passent et aucune migration supplémentaire n'est détectée.
- Le code du lot est terminé ; la validation WhatsApp reste rattachée à la recette du workflow.

### 4 juillet 2026 — Lot 5

- Transaction PayTech persistante ajoutée avec référence et token uniques.
- Création de lien toujours protégée par idempotence et propriété de commande.
- Endpoint public `POST /api/paytech/ipn/` ajouté.
- Vérification HMAC-SHA256 prioritaire et compatibilité SHA256 des clés selon la documentation PayTech.
- Montant, référence et événement vérifiés avant mise à jour.
- Callbacks dupliqués acceptés sans double traitement ; un paiement confirmé ne peut pas être rétrogradé.
- Commande passée à `processing` et conversation passée à `completed` après confirmation.
- Pages de retour succès et annulation ajoutées.
- Variables PayTech déclarées dans Render sans clés en clair.
- 68 tests Django passent ; recette PayTech réelle à effectuer après déploiement des migrations.

## Ordre d'exécution verrouillé

Les lots sont traités dans l'ordre suivant : **1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10**, puis la Phase 2.

On ne modifie plus simultanément n8n, Django, OpenWA et les intégrations sans avoir d'abord isolé et validé le contrat du lot concerné.
