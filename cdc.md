# Cahier des Charges — AI Commerce Assistant

**Version :** 1.1  
**Date :** Juillet 2026  
**Statut :** En cours de développement (Phase 1 - MVP)

### Règle de pilotage

- Ce document est la source de vérité fonctionnelle et technique du projet.
- Toute modification d'architecture, de fournisseur ou de périmètre doit être inscrite ici avant son implémentation.
- Une fonctionnalité n'est considérée terminée qu'après implémentation, tests automatisés et validation de bout en bout.
- Décision validée en juillet 2026 : **PayTech remplace Stripe** pour les paiements clients et la facturation SaaS.
- Architecture verrouillée : le workflow n8n à 13 nœuds reste la cible. Il ne sera pas remplacé par une nouvelle architecture pendant l'implémentation des autres lots.

---

## 1. Présentation du Projet

**Nom :** AI Commerce Assistant  
**Type :** SaaS (Software as a Service)  
**Objectif principal :** Permettre aux e-commerçants de vendre leurs produits directement via WhatsApp grâce à un agent conversationnel basé sur l'intelligence artificielle.

---

## 2. Objectifs

### Objectif Principal
Fournir aux e-commerçants un outil SaaS permettant de convertir WhatsApp en canal de vente direct et automatisé via une IA.

### Objectifs Secondaires
- Augmenter les ventes via une expérience d'achat personnalisée et instantanée
- Réduire la charge du service client par l'automatisation
- Simplifier l'intégration avec les plateformes e-commerce existantes
- Fournir des outils d'analyse des performances de vente via WhatsApp

---

## 3. Périmètre Fonctionnel

### 3.1 Module Agent IA (Core)

| Fonctionnalité | Description |
|---|---|
| Connexion catalogue | Synchronisation avec WooCommerce (nom, prix, stock, images, variantes) |
| NLU | Comprend le langage naturel, l'argot, le wolof mélangé au français, les fautes d'orthographe |
| Recommandation produits | Suggestions basées sur la requête et l'historique du client |
| Réponses FAQ | Livraison, retours, remboursements depuis base de connaissances configurable |
| Statut commande | Consultation en temps réel depuis WooCommerce |
| Gestion panier | Ajouter, retirer, modifier quantité, afficher, vider |
| Processus commande | Création commande + génération lien de paiement sécurisé PayTech |
| Transfert humain | Transfert vers agent + notification commerçant + suspension du bot |
| Personnalisation | Messages configurables + réponses dynamiques adaptées au style du client |

### 3.2 Module Intégration E-commerce

| Fonctionnalité | Phase | Description |
|---|---|---|
| Plugin WooCommerce | Phase 1 ✅ | Synchronisation catalogue, création commandes, suivi statut |
| Plugin Shopify | Phase 2 | Fonctionnalités identiques à WooCommerce |
| API RESTful | Phase 2 | Pour plateformes custom (Laravel, Magento, Prestashop) |

### 3.3 Module Back-Office SaaS

| Fonctionnalité | Description |
|---|---|
| Dashboard commerçant | Stats conversations, ventes IA, produits les plus vendus, taux de conversion |
| Configuration IA | FAQ, messages d'accueil, tonalité, règles de transfert humain |
| Gestion intégrations | Ajout/suppression boutiques, clés API WhatsApp/WooCommerce/PayTech |
| Gestion agents humains | Ajout/suppression, rôles, permissions, interface chat pour transferts |
| Facturation | Plans d'abonnement, historique paiements, upgrade/downgrade |
| Super Admin | Vue globale tous les commerçants, MRR, métriques IA, alertes |

---

## 4. Architecture Technique

```
Client WhatsApp
      │
      ▼
OpenWA (réception/envoi messages)
      │
      ▼
n8n Cloud (orchestration workflow)
      │
      ▼
Kimi API moonshot-v1-8k (analyse intention LLM)
      │
      ▼
Django REST API (logique métier)
      │
      ├──► WooCommerce REST API (catalogue, commandes)
      ├──► PayTech API (paiements)
      └──► Supabase PostgreSQL (panier, états, mémoire)
      │
      ▼
n8n (formulation réponse via Kimi)
      │
      ▼
OpenWA (envoi réponse WhatsApp client)
```

---

## 5. Stack Technique

| Couche | Technologie | Justification |
|---|---|---|
| **Workflow** | n8n Cloud | Orchestration visuelle, facile à maintenir |
| **LLM** | Kimi (moonshot-v1-8k) | Comprend le français informel et l'argot sénégalais |
| **Backend** | Python / Django REST Framework | Robuste, bien documenté, adapté aux API REST |
| **Base de données** | PostgreSQL via Supabase | Gratuit, persistant, compatible n8n |
| **E-commerce** | WooCommerce REST API | Phase 1, API bien documentée |
| **Paiement** | PayTech | Paiements locaux et génération de liens de paiement adaptés au marché sénégalais |
| **WhatsApp** | OpenWA | Compatible avec n8n, stable |
| **Hébergement API** | Render | Gratuit, URL permanente, déploiement simple |
| **Frontend** | Bootstrap 5 + Vanilla JS | Connu de l'équipe, rapide à développer |

---

## 6. Modèle de Données

```sql
-- Panier persistant (indépendant de l'IA)
CREATE TABLE carts (
  id            SERIAL PRIMARY KEY,
  user_id       VARCHAR(50)    NOT NULL,
  product_id    VARCHAR(50)    NOT NULL,
  product_name  VARCHAR(255),
  quantity      INTEGER        DEFAULT 1,
  price         DECIMAL(10,2),
  platform      VARCHAR(20)    DEFAULT 'woocommerce',
  created_at    TIMESTAMP      DEFAULT NOW(),
  updated_at    TIMESTAMP      DEFAULT NOW()
);

-- Machine à états de la conversation
CREATE TABLE conversation_states (
  id                 SERIAL PRIMARY KEY,
  user_id            VARCHAR(50)  UNIQUE NOT NULL,
  state              VARCHAR(50)  DEFAULT 'browsing',
  pending_product_id VARCHAR(50),
  pending_order_id   VARCHAR(50),
  pending_amount     DECIMAL(10,2),
  last_updated       TIMESTAMP    DEFAULT NOW()
);

-- États valides (transitions strictes)
-- browsing → selecting → cart_review
-- → confirming → ordering
-- → payment_pending → completed
-- → human_takeover

-- Mémoire des conversations
CREATE TABLE message_history (
  id         SERIAL PRIMARY KEY,
  session_id VARCHAR(255) NOT NULL,
  message    JSONB        NOT NULL,
  created_at TIMESTAMP    DEFAULT NOW()
);

-- Transferts vers agents humains
CREATE TABLE human_transfers (
  id         SERIAL PRIMARY KEY,
  user_id    VARCHAR(50) NOT NULL,
  reason     TEXT,
  status     VARCHAR(20) DEFAULT 'pending',
  created_at TIMESTAMP   DEFAULT NOW()
);

-- Propriété des commandes (sécurité)
CREATE TABLE user_orders (
  id         SERIAL PRIMARY KEY,
  user_id    VARCHAR(50) NOT NULL,
  order_id   VARCHAR(50) NOT NULL,
  platform   VARCHAR(20) DEFAULT 'woocommerce',
  created_at TIMESTAMP   DEFAULT NOW()
);

-- Politiques de la boutique
CREATE TABLE shop_policies (
  id          SERIAL PRIMARY KEY,
  policy_type VARCHAR(50) NOT NULL,
  content     TEXT        NOT NULL,
  updated_at  TIMESTAMP   DEFAULT NOW()
);
-- Types : delivery, returns, refund

-- Sélections numérotées (anti-hallucination)
CREATE TABLE product_selections (
  id           SERIAL PRIMARY KEY,
  user_id      VARCHAR(50) NOT NULL,
  session_key  VARCHAR(50) NOT NULL,
  position     INTEGER     NOT NULL,
  product_id   VARCHAR(50) NOT NULL,
  product_name VARCHAR(255),
  price        DECIMAL(10,2),
  created_at   TIMESTAMP   DEFAULT NOW()
);

-- Idempotence anti-doublons commandes
CREATE TABLE processed_requests (
  id               SERIAL PRIMARY KEY,
  idempotency_key  VARCHAR(100) UNIQUE NOT NULL,
  action           VARCHAR(50),
  result           JSONB,
  created_at       TIMESTAMP DEFAULT NOW()
);

-- Logs API pour monitoring
CREATE TABLE api_logs (
  id            SERIAL PRIMARY KEY,
  user_id       VARCHAR(50),
  action        VARCHAR(50),
  success       BOOLEAN,
  error_message TEXT,
  duration_ms   INTEGER,
  created_at    TIMESTAMP DEFAULT NOW()
);
```

---

## 7. Les 25 Actions de l'API

### Catalogue
| Action | Paramètres | Description |
|---|---|---|
| `search_products` | `query` | Recherche dans WooCommerce |
| `get_product` | `product_id`, `platform` | Détails complets d'un produit |
| `check_variant_stock` | `product_id`, `variant_id` | Stock et prix d'une variante |

### Sélection Déterministe
| Action | Paramètres | Description |
|---|---|---|
| `save_selection_list` | `user_id`, `session_key`, `products` | Sauvegarde liste numérotée affichée |
| `get_product_by_position` | `user_id`, `position` | Produit exact par numéro (anti-hallucination) |

### Panier
| Action | Paramètres | Description |
|---|---|---|
| `cart_add` | `user_id`, `product_id`, `product_name`, `quantity`, `price` | Ajoute au panier persistant |
| `cart_view` | `user_id` | Affiche panier + total |
| `cart_remove` | `user_id`, `product_id` | Retire un produit |
| `cart_update_quantity` | `user_id`, `product_id`, `quantity` | Modifie quantité (0 = retire) |
| `cart_clear` | `user_id` | Vide le panier |

### Machine à États
| Action | Paramètres | Description |
|---|---|---|
| `get_state` | `user_id` | État transactionnel actuel |
| `set_state` | `user_id`, `state` | Avance dans le flux |
| `revert_state` | `user_id` | Revient à l'état précédent |

### Commandes
| Action | Paramètres | Description |
|---|---|---|
| `create_order` | `user_id`, `platform`, `idempotency_key` | Crée depuis le panier (bloqué si state != confirming) |
| `get_order_status` | `user_id`, `order_id`, `platform` | Statut réel WooCommerce |
| `cancel_order` | `user_id`, `order_id`, `reason` | Annule (vérifie propriétaire) |
| `update_order` | `user_id`, `order_id`, `line_items` | Modifie quantités |
| `get_tracking` | `user_id`, `order_id` | Numéro et URL de suivi |

### Paiement
| Action | Paramètres | Description |
|---|---|---|
| `generate_payment` | `user_id`, `order_id`, `amount`, `idempotency_key` | Lien PayTech (bloqué sans order_id réel) |

### Service Client
| Action | Paramètres | Description |
|---|---|---|
| `transfer_to_human` | `user_id`, `reason` | Enregistre transfert + suspend bot |
| `check_human_status` | `user_id` | Vérifie si bot suspendu |
| `request_refund` | `user_id`, `order_id`, `amount`, `reason` | Demande remboursement (pas auto en MVP) |
| `validate_coupon` | `code`, `platform` | Vérifie code promo WooCommerce |

### Politiques
| Action | Paramètres | Description |
|---|---|---|
| `get_policy` | `policy_type` | Retourne delivery / returns / refund |

---

## 8. Workflow n8n — 13 Nœuds

```
01 Webhook OpenWA        → Reçoit le message WhatsApp
02 Normaliser message    → Ignore fromMe, gère médias/vide
03 Extraire message      → chatId, userId, messageText, sessionId
04 Message basique ?     → Détecte bonjour, merci, ok, 👍
05 Est basique ?         → Branchement IF
06 Kimi analyse          → Retourne intention JSON (confidence, params)
07 Parser intention      → Extrait intention, params, confidence
08 Appeler Django API    → POST /api/commerce/ avec X-API-Token
09 Vérifier résultat     → human_takeover ? low_confidence ?
10 Kimi formule réponse  → Réponse naturelle basée sur données Django
11 Nettoyer réponse      → Supprime Markdown, détecte fuites internes
12 Sauvegarder mémoire   → INSERT dans message_history Supabase
13 Envoyer OpenWA        → Réponse finale au client WhatsApp
```

---

## 9. Sécurité

- **Authentification API :** Token statique `X-API-Token` dans chaque requête n8n → Django
- **Rate limiting :** 60 requêtes/minute par IP
- **JWT :** Pour l'accès au back-office commerçant
- **SSL/TLS :** Obligatoire en production (Render, Supabase)
- **Conformité RGPD :** Données personnelles chiffrées, droit à l'effacement
- **Idempotence :** Sur `create_order` et `generate_payment` (anti-doublons)
- **Vérification propriétaire :** Avant toute action sensible (annulation, remboursement, statut)

---

## 10. Format de Réponse API

```json
// Succès
{
  "success": true,
  "data": { ... }
}

// Erreur métier
{
  "success": false,
  "error": "Message clair exploitable par Kimi",
  "data": {}
}
```

**Règle absolue :** Jamais de `"service indisponible"` comme réponse.  
**Jamais de HTTP 500 non géré** — tout est dans un try/except global.

---

## 11. Phases de Développement

### Phase 1 — MVP (En cours)
- Agent IA WhatsApp fonctionnel avec Kimi
- Intégration WooCommerce complète
- Panier persistant dans Supabase
- Commande + paiement PayTech
- Déploiement API sur Render
- Mémoire PostgreSQL Supabase

### Phase 2 — Enrichissement
- Back-office complet (Lovable + Bootstrap)
- Plugin Shopify
- Gestion agents humains avec interface chat
- Analytics avancées
- Messages vocaux (transcription Whisper)
- Notifications WhatsApp marketing

### Phase 3 — Production & Scale
- Optimisation performances
- Microservices
- Monitoring (Grafana, Prometheus)
- CI/CD GitHub Actions
- Système d'abonnement et facturation SaaS via PayTech
- Multi-boutiques par commerçant

---

## 12. Plans Tarifaires (SaaS)

| Plan | Prix | Inclus |
|---|---|---|
| **Basic** | 29€/mois | 1 boutique, 500 conversations/mois |
| **Pro** | 79€/mois | 3 boutiques, 2000 conversations/mois, analytics |
| **Enterprise** | 199€/mois | Boutiques illimitées, conversations illimitées, agents humains |

---

## 13. Exigences Non Fonctionnelles

| Critère | Exigence |
|---|---|
| **Disponibilité** | 99.9% pour les services critiques |
| **Temps de réponse IA** | < 3 secondes pour la majorité des requêtes |
| **Langues supportées** | Français standard, argot sénégalais, wolof mélangé |
| **Scalabilité** | Multi-commerçants simultanés |
| **Maintenabilité** | Code commenté en français, tests unitaires |
| **Support** | Documentation technique + FAQ utilisateurs |

---

## 14. Glossaire

| Terme | Définition |
|---|---|
| **SaaS** | Software as a Service |
| **NLU** | Natural Language Understanding — compréhension du langage naturel |
| **LLM** | Large Language Model — modèle de langage (ici Kimi) |
| **n8n** | Outil d'orchestration de workflows no-code/low-code |
| **OpenWA** | Bibliothèque d'intégration WhatsApp |
| **MVP** | Minimum Viable Product — version minimale fonctionnelle |
| **Idempotence** | Propriété garantissant qu'une opération répétée produit le même résultat |
| **human_takeover** | État où le bot est suspendu et un humain prend le relais |
| **Machine à états** | Système qui contrôle les transitions entre étapes d'une conversation |
| **RGPD** | Règlement Général sur la Protection des Données |
