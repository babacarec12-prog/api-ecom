-- AI Commerce Assistant — schéma PostgreSQL/Supabase.
-- Exécuter ce fichier une seule fois dans l'éditeur SQL Supabase.

BEGIN;

CREATE TABLE IF NOT EXISTS carts (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    product_id VARCHAR(50) NOT NULL,
    product_name VARCHAR(255) DEFAULT '',
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    price DECIMAL(10,2) NOT NULL CHECK (price >= 0),
    platform VARCHAR(20) NOT NULL DEFAULT 'woocommerce',
    idempotency_key VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT carts_user_product_unique UNIQUE (user_id, product_id)
);
CREATE INDEX IF NOT EXISTS carts_user_id_idx ON carts(user_id);

CREATE TABLE IF NOT EXISTS product_selections (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    session_key VARCHAR(100) NOT NULL,
    position INTEGER NOT NULL CHECK (position > 0),
    product_id VARCHAR(50) NOT NULL,
    product_name VARCHAR(255) DEFAULT '',
    price DECIMAL(10,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT selection_position_unique UNIQUE (user_id, session_key, position)
);
CREATE INDEX IF NOT EXISTS product_selections_user_idx ON product_selections(user_id);

CREATE TABLE IF NOT EXISTS conversation_states (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(50) UNIQUE NOT NULL,
    state VARCHAR(50) NOT NULL DEFAULT 'browsing',
    previous_state VARCHAR(50) NOT NULL DEFAULT 'browsing',
    pending_product_id VARCHAR(50),
    pending_order_id VARCHAR(50),
    pending_amount DECIMAL(10,2),
    pending_action VARCHAR(50),
    pending_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Mise a niveau sure d'une base deja creee par une version precedente.
ALTER TABLE conversation_states
    ADD COLUMN IF NOT EXISTS pending_action VARCHAR(50);
ALTER TABLE conversation_states
    ADD COLUMN IF NOT EXISTS pending_payload JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS processed_requests (
    id BIGSERIAL PRIMARY KEY,
    idempotency_key VARCHAR(100) UNIQUE NOT NULL,
    action VARCHAR(50) NOT NULL,
    result JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_orders (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    order_id VARCHAR(50) UNIQUE NOT NULL,
    platform VARCHAR(20) NOT NULL DEFAULT 'woocommerce',
    amount_total DECIMAL(10,2),
    currency VARCHAR(10) NOT NULL DEFAULT 'XOF',
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    items JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS user_orders_user_idx ON user_orders(user_id);

ALTER TABLE user_orders ADD COLUMN IF NOT EXISTS amount_total DECIMAL(10,2);
ALTER TABLE user_orders ADD COLUMN IF NOT EXISTS currency VARCHAR(10) NOT NULL DEFAULT 'XOF';
ALTER TABLE user_orders ADD COLUMN IF NOT EXISTS status VARCHAR(30) NOT NULL DEFAULT 'pending';
ALTER TABLE user_orders ADD COLUMN IF NOT EXISTS items JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE IF NOT EXISTS products (
    id BIGSERIAL PRIMARY KEY,
    external_id VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT DEFAULT '',
    category VARCHAR(100) DEFAULT '',
    price DECIMAL(10,2) NOT NULL CHECK (price >= 0),
    stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    sku VARCHAR(100) DEFAULT '',
    image_url VARCHAR(200) DEFAULT '',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS products_category_idx ON products(category);
CREATE INDEX IF NOT EXISTS products_active_idx ON products(active);

INSERT INTO products (external_id, name, description, category, price, stock, sku) VALUES
    ('DB-001', 'Batterie externe 10 000 mAh', 'Batterie portable USB-C avec charge rapide.', 'Électronique', 22000, 15, 'BAT-10000'),
    ('DB-002', 'Écouteurs Bluetooth Nomad', 'Écouteurs sans fil avec boîtier de recharge.', 'Électronique', 18500, 20, 'ECO-NOMAD'),
    ('DB-003', 'Bissap naturel 1 litre', 'Boisson artisanale au bissap, sans conservateur.', 'Boissons', 2500, 40, 'BIS-1L'),
    ('DB-004', 'Sac à dos urbain Dakar', 'Sac résistant avec compartiment pour ordinateur portable.', 'Accessoires', 15000, 12, 'SAC-DAKAR'),
    ('DB-005', 'T-shirt coton Sénégal', 'T-shirt unisexe en coton, tailles S à XXL.', 'Vêtements', 7500, 30, 'TS-SEN')
ON CONFLICT (external_id) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    category = EXCLUDED.category,
    price = EXCLUDED.price,
    sku = EXCLUDED.sku,
    active = TRUE,
    updated_at = NOW();

CREATE TABLE IF NOT EXISTS human_transfers (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    reason TEXT DEFAULT '',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS human_transfers_user_idx ON human_transfers(user_id);

CREATE TABLE IF NOT EXISTS shop_policies (
    id BIGSERIAL PRIMARY KEY,
    policy_type VARCHAR(50) UNIQUE NOT NULL,
    content TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO shop_policies (policy_type, content) VALUES
    ('delivery', 'Livraison sous 3-5 jours ouvrés. Gratuite dès 50 € d''achats.'),
    ('returns', 'Retours acceptés sous 14 jours. Produit non utilisé dans son emballage d''origine.'),
    ('refund', 'Remboursement sous 5-7 jours ouvrés après réception du retour.')
ON CONFLICT (policy_type) DO UPDATE
SET content = EXCLUDED.content, updated_at = NOW();

-- Valeurs par defaut adaptees a une boutique senegalaise.
UPDATE shop_policies SET content =
    'Livraison sous 3 à 5 jours ouvrés. Les frais et le délai exact sont confirmés selon la zone de livraison au Sénégal.',
    updated_at = NOW()
WHERE policy_type = 'delivery';
UPDATE shop_policies SET content =
    'Retours acceptés sous 14 jours pour un produit non utilisé, complet et dans son emballage d''origine.',
    updated_at = NOW()
WHERE policy_type = 'returns';
UPDATE shop_policies SET content =
    'Après validation du retour, le remboursement est enregistré puis traité selon le moyen de paiement utilisé.',
    updated_at = NOW()
WHERE policy_type = 'refund';

COMMIT;
