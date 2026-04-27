-- Sample Neon/Postgres schema for TiShift demos and tests.
-- Covers: PKs, FKs, PL/pgSQL function, JSONB with operators, array column,
--         UUID column, ENUM type, sequence, GIN index, TEXT column, RETURNING usage.

-- Named ENUM type (WARNING-1)
CREATE TYPE order_status AS ENUM ('pending', 'processing', 'shipped', 'delivered', 'cancelled');

-- Sequence (WARNING-2)
CREATE SEQUENCE invoice_number_seq START 1000 INCREMENT 1;

-- Users table with UUID primary key (WARNING-4)
CREATE TABLE users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       VARCHAR(255) NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    tags        TEXT[] DEFAULT '{}',              -- BLOCKER-1: array column
    preferences JSONB DEFAULT '{}',               -- WARNING-11: JSONB column
    created_at  TIMESTAMPTZ DEFAULT now(),         -- WARNING-13: timestamptz
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- Products table
CREATE TABLE products (
    id          BIGSERIAL PRIMARY KEY,             -- WARNING-5: BIGSERIAL
    sku         VARCHAR(50) NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    description TEXT,                              -- large text column
    price       NUMERIC(10,2) NOT NULL,
    metadata    JSONB DEFAULT '{}',
    categories  TEXT[] DEFAULT '{}',               -- BLOCKER-1: array column
    is_active   BOOLEAN DEFAULT TRUE,              -- WARNING-8: boolean
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Orders table with FK and ENUM
CREATE TABLE orders (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES users(id),      -- FK
    invoice_number  BIGINT DEFAULT nextval('invoice_number_seq'),
    status          order_status DEFAULT 'pending',          -- uses ENUM type
    total_amount    NUMERIC(12,2) NOT NULL,
    shipping_info   JSONB,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- Order items table
CREATE TABLE order_items (
    id          BIGSERIAL PRIMARY KEY,
    order_id    BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id  BIGINT NOT NULL REFERENCES products(id),
    quantity    INT NOT NULL CHECK (quantity > 0),
    unit_price  NUMERIC(10,2) NOT NULL,
    line_total  NUMERIC(12,2) GENERATED ALWAYS AS (quantity * unit_price) STORED
);

-- Indexes
CREATE INDEX idx_users_tags ON users USING GIN (tags);           -- GIN on array
CREATE INDEX idx_products_metadata ON products USING GIN (metadata);  -- GIN on JSONB
CREATE INDEX idx_orders_user ON orders (user_id);
CREATE INDEX idx_orders_status ON orders (status);
CREATE INDEX idx_order_items_order ON order_items (order_id);

-- PL/pgSQL function (BLOCKER-6) — uses RETURNING (WARNING-3) and JSONB operators (BLOCKER-2)
CREATE OR REPLACE FUNCTION create_order(
    p_user_id UUID,
    p_items JSONB,     -- [{"product_id": 1, "quantity": 2}, ...]
    p_notes TEXT DEFAULT NULL
) RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    v_order_id BIGINT;
    v_item JSONB;
    v_product RECORD;
    v_total NUMERIC(12,2) := 0;
BEGIN
    -- Create order with RETURNING
    INSERT INTO orders (user_id, total_amount, notes)
    VALUES (p_user_id, 0, p_notes)
    RETURNING id INTO v_order_id;

    -- Process items from JSONB array
    FOR v_item IN SELECT * FROM jsonb_array_elements(p_items)
    LOOP
        SELECT id, price INTO v_product
        FROM products
        WHERE id = (v_item->>'product_id')::BIGINT
          AND is_active = TRUE;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'Product % not found or inactive', v_item->>'product_id';
        END IF;

        INSERT INTO order_items (order_id, product_id, quantity, unit_price)
        VALUES (v_order_id, v_product.id, (v_item->>'quantity')::INT, v_product.price);

        v_total := v_total + (v_product.price * (v_item->>'quantity')::INT);
    END LOOP;

    -- Update order total
    UPDATE orders SET total_amount = v_total WHERE id = v_order_id;

    RETURN v_order_id;
END;
$$;

-- Query using JSONB operators (BLOCKER-2) — for scan detection
-- Example: Find users whose preferences contain a specific key
-- SELECT * FROM users WHERE preferences @> '{"theme": "dark"}';
-- SELECT * FROM users WHERE preferences ? 'newsletter';
-- SELECT * FROM products WHERE metadata #>> '{dimensions,weight}' IS NOT NULL;
