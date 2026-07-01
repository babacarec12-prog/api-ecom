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
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS user_orders_user_idx ON user_orders(user_id);

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

COMMIT;
