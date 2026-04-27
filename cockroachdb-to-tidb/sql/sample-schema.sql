-- TiShift CockroachDB — Sample Schema for Demos and Tests
--
-- Exercises key CockroachDB features TiShift must handle:
-- UUID PKs, SERIAL, JSONB with operators, arrays, hash-sharded index,
-- inverted index, enum type, computed column, sequence, FK, view,
-- row-level TTL, and multi-region annotation (commented out for single-region).

-- Enum type
CREATE TYPE order_status AS ENUM ('pending', 'processing', 'shipped', 'delivered', 'cancelled');

-- Sequence
CREATE SEQUENCE invoice_seq START 1000 INCREMENT 1;

-- Users table: UUID PK (idiomatic CRDB pattern)
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email STRING NOT NULL,
    name STRING(200) NOT NULL,
    metadata JSONB DEFAULT '{}',
    tags STRING[],  -- array column
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (email)
);

-- Products table: SERIAL PK, hash-sharded index
CREATE TABLE products (
    id INT8 PRIMARY KEY DEFAULT unique_rowid(),
    name STRING NOT NULL,
    description STRING,
    price DECIMAL(10,2) NOT NULL,
    attributes JSONB DEFAULT '{}',
    category STRING(100),
    is_active BOOL DEFAULT true,
    INDEX idx_products_category (category) USING HASH WITH BUCKET_COUNT = 8
);

-- Inverted index on JSONB
CREATE INVERTED INDEX idx_products_attrs ON products(attributes);

-- Orders table: FK, enum, computed column
CREATE TABLE orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    status order_status DEFAULT 'pending',
    total DECIMAL(12,2) NOT NULL,
    item_count INT4 DEFAULT 0,
    order_date TIMESTAMPTZ DEFAULT now(),
    total_with_tax DECIMAL(12,2) AS (total * 1.08) STORED,
    CONSTRAINT orders_total_positive CHECK (total >= 0)
);

-- Order items: composite FK
CREATE TABLE order_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES orders(id),
    product_id INT8 NOT NULL REFERENCES products(id),
    quantity INT4 NOT NULL DEFAULT 1,
    unit_price DECIMAL(10,2) NOT NULL
);

-- Audit log: row-level TTL (expire after 90 days)
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    table_name STRING NOT NULL,
    action STRING NOT NULL,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
) WITH (
    ttl_expiration_expression = 'created_at + INTERVAL ''90 days''',
    ttl_job_cron = '@daily'
);

-- View using JSONB operators (will need rewrite)
CREATE VIEW user_preferences AS
SELECT id, email, name,
       metadata->>'theme' AS theme,
       metadata->>'lang' AS language
FROM users
WHERE metadata @> '{"active": true}';

-- View with string_agg (maps to GROUP_CONCAT)
CREATE VIEW category_products AS
SELECT category,
       count(*) AS product_count,
       string_agg(name, ', ' ORDER BY name) AS product_names
FROM products
WHERE is_active = true
GROUP BY category;

-- Sample data
INSERT INTO users (email, name, metadata, tags) VALUES
    ('alice@example.com', 'Alice Chen', '{"active": true, "theme": "dark", "lang": "en"}', ARRAY['admin', 'beta']),
    ('bob@example.com', 'Bob Kumar', '{"active": true, "theme": "light", "lang": "pt"}', ARRAY['user']),
    ('carol@example.com', 'Carol Santos', '{"active": false, "theme": "dark", "lang": "es"}', NULL);

INSERT INTO products (name, description, price, attributes, category) VALUES
    ('Widget Pro', 'Professional widget', 29.99, '{"color": "blue", "weight_kg": 0.5}', 'widgets'),
    ('Gadget Max', 'Maximum gadget', 149.99, '{"color": "red", "weight_kg": 1.2, "battery": true}', 'gadgets'),
    ('Widget Basic', 'Basic widget', 9.99, '{"color": "green", "weight_kg": 0.2}', 'widgets');

-- Multi-region annotation (uncomment for multi-region clusters):
-- ALTER DATABASE myapp SET PRIMARY REGION "us-east1";
-- ALTER DATABASE myapp ADD REGION "us-west1";
-- ALTER TABLE users SET LOCALITY REGIONAL BY ROW;
