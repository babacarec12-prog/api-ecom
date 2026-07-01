Contexte du projet :
SaaS "AI Commerce Assistant" — agent IA WhatsApp qui vend des 
produits WooCommerce via n8n + Django REST API + Supabase PostgreSQL
+ Stripe. Phase test : Qwen 2.5 gratuit, ngrok local, WooCommerce.

Un audit a révélé ces manquements critiques à corriger DANS L'ORDRE.
Ne touche à rien qui marche déjà (catalogue, search_products, 
get_product fonctionnent à 80%).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRIORITÉ 1 — PANIER STRUCTURÉ DANS SUPABASE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROBLÈME : Le panier est stocké en mémoire n8n (volatile, perdu 
si restart) et dépend de Qwen pour le maintenir.

SOLUTION : 
- Crée une table "carts" dans Supabase :
  CREATE TABLE carts (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    product_id VARCHAR(50) NOT NULL,
    product_name VARCHAR(255),
    quantity INTEGER DEFAULT 1,
    price DECIMAL(10,2),
    platform VARCHAR(20) DEFAULT 'woocommerce',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
  );
- Ajoute dans /api/commerce/ ces nouvelles actions :
  * action: "cart_add" 
    data: {user_id, product_id, product_name, quantity, price}
  * action: "cart_remove"
    data: {user_id, product_id}
  * action: "cart_update_quantity"
    data: {user_id, product_id, quantity}
  * action: "cart_view"
    data: {user_id}
  * action: "cart_clear"
    data: {user_id}
- Le panier doit survivre aux redémarrages de n8n et ngrok
- Retourner toujours le panier complet + total après chaque action

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRIORITÉ 2 — SÉLECTION NUMÉRIQUE DÉTERMINISTE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROBLÈME : Quand l'agent affiche plusieurs produits et que le 
client répond "je prends le 2", Qwen peut sélectionner le 
mauvais produit par hallucination.

SOLUTION :
- Crée une table "product_selections" dans Supabase :
  CREATE TABLE product_selections (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    session_key VARCHAR(50) NOT NULL,
    position INTEGER NOT NULL,
    product_id VARCHAR(50) NOT NULL,
    product_name VARCHAR(255),
    price DECIMAL(10,2),
    created_at TIMESTAMP DEFAULT NOW()
  );
- Ajoute dans /api/commerce/ :
  * action: "save_selection_list"
    data: {user_id, products: [{position:1, product_id, 
           product_name, price}, ...]}
    → sauvegarde la liste affichée au client
  * action: "get_product_by_position"
    data: {user_id, position: 2}
    → retourne le produit exact à la position demandée
- Le system prompt devra appeler save_selection_list à chaque 
  fois qu'il affiche une liste de produits

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRIORITÉ 3 — MACHINE À ÉTATS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROBLÈME : La conversation peut sauter des étapes (ex: créer une 
commande sans confirmation, payer sans commande créée).

SOLUTION :
- Crée une table "conversation_states" dans Supabase :
  CREATE TABLE conversation_states (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) UNIQUE NOT NULL,
    state VARCHAR(50) DEFAULT 'browsing',
    pending_product_id VARCHAR(50),
    pending_order_id VARCHAR(50),
    pending_amount DECIMAL(10,2),
    last_updated TIMESTAMP DEFAULT NOW()
  );
- États possibles (dans cet ordre strict) :
  browsing → selecting → cart_review → confirming 
  → ordering → payment_pending → completed
- Ajoute dans /api/commerce/ :
  * action: "get_state"
    data: {user_id}
  * action: "set_state"
    data: {user_id, state, pending_product_id(opt), 
           pending_order_id(opt), pending_amount(opt)}
- RÈGLES STRICTES à documenter pour le system prompt :
  * "create_order" bloqué si state != "confirming"
  * "generate_payment" bloqué si state != "ordering"
  * Paiement déclenché UNIQUEMENT après order_id réel retourné
    par WooCommerce (pas avant)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRIORITÉ 4 — CORRECTIONS ET NÉGATIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROBLÈME : Si le client dit "non finalement", "annule ça", 
"je voulais dire le 3 pas le 2", l'agent ne gère pas bien.

SOLUTION dans le system prompt (pas de code Django) :
- Détecte les mots clés de négation/correction :
  "non", "annule", "pas ça", "finalement", "en fait", 
  "je voulais dire", "erreur", "oublie"
- Si détecté → appelle "get_state" et revient à l'état 
  précédent dans la machine à états
- Si double message rapide (2 messages en moins de 5 secondes) 
  → traite uniquement le dernier message
- Ajoute dans /api/commerce/ :
  * action: "revert_state"
    data: {user_id}
    → revient à l'état précédent (browsing si incertain)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRIORITÉ 5 — IDEMPOTENCE (PAS DE DOUBLON)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROBLÈME : Si n8n relance une requête (retry), une commande peut 
être créée deux fois.

SOLUTION :
- Ajoute un champ "idempotency_key" dans la table carts 
  et dans create_order
- Crée une table "processed_requests" :
  CREATE TABLE processed_requests (
    id SERIAL PRIMARY KEY,
    idempotency_key VARCHAR(100) UNIQUE NOT NULL,
    action VARCHAR(50),
    result JSONB,
    created_at TIMESTAMP DEFAULT NOW()
  );
- Dans /api/commerce/, pour les actions create_order et 
  generate_payment :
  * Vérifie si idempotency_key existe déjà
  * Si oui → retourne le résultat stocké sans re-exécuter
  * Si non → exécute et sauvegarde le résultat
- L'idempotency_key = user_id + timestamp arrondi à la minute

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRIORITÉ 6 — VÉRIFICATION PROPRIÉTAIRE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROBLÈME : N'importe qui peut demander le statut ou annuler la 
commande d'un autre client en devinant l'order_id.

SOLUTION :
- Crée une table "user_orders" dans Supabase :
  CREATE TABLE user_orders (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    order_id VARCHAR(50) NOT NULL,
    platform VARCHAR(20) DEFAULT 'woocommerce',
    created_at TIMESTAMP DEFAULT NOW()
  );
- Modifie ces actions dans /api/commerce/ pour vérifier 
  que user_id est bien le propriétaire :
  * get_order_status
  * cancel_order (nouvelle action)
  * modify_order (nouvelle action)
  * request_refund (nouvelle action)
- Si user_id ne correspond pas → retourne :
  {"success": false, "error": "Commande introuvable 
   pour ce compte."}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRIORITÉ 7 — TRANSFERT HUMAIN RÉEL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROBLÈME : Le transfert humain actuel est juste un console.log, 
le bot continue de répondre après le transfert.

SOLUTION :
- Crée une table "human_transfers" dans Supabase :
  CREATE TABLE human_transfers (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    reason TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW()
  );
- Modifie action "transfer_to_human" dans /api/commerce/ :
  * Insère dans human_transfers
  * Met state = "human_takeover" dans conversation_states
- Ajoute action "check_human_status" :
  data: {user_id}
  → retourne si le user est en mode human_takeover
- Dans le system prompt : au début de chaque message, appelle 
  "check_human_status" — si human_takeover → réponds uniquement:
  "Vous êtes en contact avec notre équipe. 
   Un agent va vous répondre très bientôt."
  et ne traite PAS le message plus loin

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRIORITÉ 8 — POLITIQUES LIVRAISON/RETOUR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROBLÈME : L'agent ne sait pas répondre aux questions sur la 
livraison, les retours et les remboursements.

SOLUTION :
- Crée une table "shop_policies" dans Supabase :
  CREATE TABLE shop_policies (
    id SERIAL PRIMARY KEY,
    policy_type VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW()
  );
  INSERT INTO shop_policies (policy_type, content) VALUES
  ('delivery', 'Livraison sous 3-5 jours ouvrés. 
    Gratuite dès 50€ d achats.'),
  ('returns', 'Retours acceptés sous 14 jours. 
    Produit non utilisé dans son emballage d origine.'),
  ('refund', 'Remboursement sous 5-7 jours ouvrés 
    après réception du retour.');
- Ajoute dans /api/commerce/ :
  * action: "get_policy"
    data: {policy_type: "delivery"|"returns"|"refund"}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRIORITÉ 9 — SÉCURISATION API DJANGO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROBLÈME : L'API est actuellement ouverte, n'importe qui 
peut l'appeler.

SOLUTION :
- Ajoute une authentification par token statique dans .env :
  N8N_API_TOKEN=un-token-secret-long-et-aléatoire
- Vérifie ce token dans chaque requête :
  Header attendu: X-API-Token: {N8N_API_TOKEN}
  Si absent ou incorrect → retourne 401 Unauthorized
- Ajoute un rate limiting basique :
  Maximum 60 requêtes/minute par IP
  Si dépassé → retourne 429 Too Many Requests
- Ajoute une validation stricte du champ "action" :
  Si action inconnue → retourne 400 Bad Request avec 
  la liste des actions valides

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LIVRABLES ATTENDUS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Fichier "migrations.sql" : tout le SQL des nouvelles 
   tables à exécuter dans Supabase en une fois

2. "views.py" mis à jour : avec toutes les nouvelles actions

3. "system-prompt-v3.txt" : system prompt complet pour Qwen 
   intégrant la machine à états, les vérifications 
   human_takeover, les sélections déterministes et les 
   corrections/négations. IMPORTANT : garder le prompt 
   CONCIS (max 800 tokens) car Qwen gratuit a des limites

4. "n8n-changes.md" : liste des modifications à faire 
   manuellement dans n8n (ajout du header X-API-Token, 
   retry logic, check human_takeover en début de workflow)

CONTRAINTES :
- WooCommerce uniquement (pas Shopify)
- Reste sur Qwen 2.5 gratuit via OpenRouter
- Reste sur ngrok pour l'instant
- Ne casse rien de l'existant
- Commente tout en français
- Teste chaque nouvelle action avec python manage.py test