# Audit et gap analysis — AI Commerce Assistant MVP

Date : 30 juin 2026  
Périmètre demandé : WooCommerce, WhatsApp texte, Django REST, n8n, Qwen gratuit et mémoire Supabase.

## 1. Cas d’usage actuellement couverts

### API Django

L’API conserve un endpoint unique : `POST /api/commerce/`, avec le contrat `action + data` et les réponses `{success, data}` ou `{success, error}`.

Fonctions présentes avant cet audit :

- `search_products` : recherche WooCommerce, catalogue complet avec `query: "*"`, correction de fautes simples et réponse avec identifiant, nom, prix et stock ;
- `get_product` : description, images, prix, stock et variantes ;
- `create_order` : commande WooCommerce avec quantité et variante facultative ;
- `generate_payment` : création d’un lien de paiement ;
- `get_order_status` : lecture et traduction partielle du statut d’une commande.

Le endpoint valide les champs obligatoires, refuse les actions inconnues, intercepte les erreurs WooCommerce/réseau et retourne toujours un JSON uniforme.

### Agent et workflow n8n

Le workflow actuel sait :

- extraire un message texte OpenWA et son identifiant client ;
- rechercher un produit ou afficher jusqu’à dix produits du catalogue ;
- tolérer certaines fautes de frappe ;
- numéroter les résultats et comprendre une sélection `1`, `2`, etc. ;
- mémoriser temporairement le dernier résultat sélectionné ;
- présenter les détails d’un produit ;
- résumer une commande et demander une confirmation ;
- créer une commande simple mono-produit ;
- générer un paiement et consulter un statut via les outils existants ;
- conserver l’historique conversationnel dans PostgreSQL/Supabase ;
- notifier un conseiller via un sous-workflow ;
- répondre en français et filtrer quelques fuites de JSON/raisonnement.

### Robustesse déjà présente

- Recherche floue locale limitée à 100 produits ;
- blocage du fallback flou sur `oui`, `non`, `ok`, salutations et requêtes numériques ;
- séparation des erreurs affichables et des traces serveur ;
- variables secrètes chargées depuis `.env` ;
- tests du contrat HTTP, du paiement et de la recherche.

## 2. Gap analysis

### Commerce et commandes

| Cas client | État avant audit | Besoin |
|---|---|---|
| Annuler une commande | Absent | Vérifier la commande, son état, sa propriété et demander confirmation |
| Demander un remboursement | Absent | Montant, motif, état payé, confirmation et éventuellement validation humaine |
| Modifier une commande | Absent | Modifier les lignes WooCommerce tant que la commande le permet |
| Modifier/vider le panier | Fragile | Créer un vrai panier persistant par utilisateur, avec ajout, retrait et quantité |
| Taille/couleur/variante | Partiel | Sélectionner une variante et vérifier son stock exact avant commande |
| Comparer des produits | Absent | Charger plusieurs fiches et comparer uniquement les champs réels |
| Code promo | Absent | Valider le coupon, son expiration et ses limites ; ne jamais inventer de réduction |
| Suivi de colis | Partiel | Retourner transporteur, numéro et URL provenant des métadonnées WooCommerce |
| Frais/délais de livraison | Absent | Interroger les zones/méthodes ou fournir une politique configurée |
| Adresse de livraison | Absent | Collecter et valider nom, téléphone et adresse avant la commande |
| Historique des commandes | Absent | Rechercher uniquement les commandes appartenant au client WhatsApp |
| Paiement confirmé | Absent | Traiter l’IPN/webhook du prestataire et rapprocher paiement et commande |

### Conversation et expérience client

- **Politique de livraison, retour et échange** : aucune source structurée ; le modèle pourrait inventer. Prévoir un contexte administrable ou un transfert humain.
- **Hors-sujet** : aucune règle déterministe avant l’agent. Répondre brièvement puis recentrer sur la boutique.
- **Abus, insultes et spam** : aucune politique explicite. Rester calme, poser une limite et ne jamais répondre agressivement.
- **Questions répétées** : pas de compteur fiable. Après deux répétitions sans progrès, proposer un humain.
- **Webhooks dupliqués** : l’identifiant OpenWA n’est pas persisté pour garantir l’idempotence. Une répétition peut créer plusieurs commandes.
- **Demande explicite d’humain** : l’outil existe, mais ses entrées ne sont pas mappées dans le workflow principal et le bot n’est pas mis en pause après transfert.
- **Message vide** : l’extracteur initial levait une erreur. La version auditée ajoute un normaliseur et une réponse de clarification.
- **Emoji seul** : auparavant envoyé à la recherche produit. Il faut demander une précision textuelle.
- **Image seule** : non analysée dans ce MVP. Répondre que seuls les messages texte sont pris en charge.
- **Changement de langue** : la langue n’est pas mémorisée. Le prompt v2 demande de poursuivre dans la langue du dernier message, français par défaut.
- **Boucle OpenWA** : sans filtrage `fromMe`, le bot peut retraiter ses propres réponses. Le normaliseur ajoute ce filtre.

### Robustesse Qwen gratuit

Avant audit : une seule tentative, aucune sortie d’erreur et aucun fallback garanti.

Risques :

- timeouts et réponses 429 ;
- arrêt complet du workflow ;
- double commande si un retry rejoue une action non idempotente ;
- hallucination d’identifiants ou d’arguments d’outil ;
- prompt trop long et mémoire polluée par les anciennes erreurs.

Correctifs retenus : deux tentatives **au total**, pause de trois secondes, sortie d’erreur dédiée, fallback sans nouvel appel IA et prompt compact.

### Sécurité et intégrité

- L’API utilise encore `AllowAny` et aucune authentification interne : toute personne connaissant l’URL ngrok peut appeler des actions sensibles.
- Il manque une clé partagée n8n/Django, une limite de débit et une vérification de propriété des commandes par `user_id`.
- `generate_payment` accepte encore un montant transmis par l’agent au lieu de relire le total WooCommerce.
- Il manque une clé d’idempotence sur `create_order`, l’annulation et le remboursement.
- La mémoire métier repose en partie sur `$getWorkflowStaticData`, fragile avec plusieurs workers ; Supabase doit devenir la source d’état pour un SaaS multi-boutiques.

### Incohérences observées

- Le périmètre demandé est WooCommerce-only, mais des branches historiques Shopify restent dans le code. Elles ne sont pas utilisées par les nouvelles actions et devront être retirées séparément après validation de non-régression.
- Le code actuel utilise **PayTech**, alors que le texte de la demande mentionne Stripe. Cet audit conserve le prestataire réellement implémenté afin de ne rien casser.
- Le modèle configuré dans l’export n8n est `qwen/qwen3-235b-a22b-2507`, alors que le contexte parle de Qwen 2.5. Aucun changement de modèle n’a été effectué.
- Le workflow exporté contenait deux clés `systemMessage`; en JSON, la dernière remplace silencieusement la première.

## Priorités recommandées après le MVP

1. Authentifier les appels n8n → Django et ajouter l’idempotence de commande.
2. Stocker panier, sélection, transfert humain et répétitions dans Supabase.
3. Vérifier la propriété d’une commande avant statut, modification, annulation ou remboursement.
4. Rapprocher le montant du paiement avec le total réel WooCommerce.
5. Ajouter une source administrable pour livraison, retours et FAQ.
6. Retirer proprement le code historique hors périmètre après une passe de tests dédiée.
