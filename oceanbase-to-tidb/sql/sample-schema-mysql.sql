-- TiShift OceanBase — Sample Schema (MySQL Mode)
--
-- Exercises OceanBase MySQL-mode extensions that TiShift must strip:
-- TABLEGROUP, PRIMARY_ZONE, LOCALITY, partitions, triggers, stored procedures.

CREATE TABLEGROUP tg_ecommerce;

CREATE TABLE customers (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(200) NOT NULL,
    name VARCHAR(100) NOT NULL,
    metadata JSON DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_email (email)
) TABLEGROUP = 'tg_ecommerce'
  PRIMARY_ZONE = 'zone1'
  LOCALITY = 'F@zone1,F@zone2,R@zone3';

CREATE TABLE products (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    category VARCHAR(100),
    is_active TINYINT(1) DEFAULT 1,
    description TEXT,
    INDEX idx_category (category)
) TABLEGROUP = 'tg_ecommerce';

CREATE TABLE orders (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    customer_id BIGINT NOT NULL,
    total DECIMAL(12,2) NOT NULL,
    status ENUM('pending','processing','shipped','delivered') DEFAULT 'pending',
    order_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_orders_customer FOREIGN KEY (customer_id) REFERENCES customers(id)
) TABLEGROUP = 'tg_ecommerce'
  PARTITION BY RANGE COLUMNS(order_date) (
    PARTITION p2024 VALUES LESS THAN ('2025-01-01'),
    PARTITION p2025 VALUES LESS THAN ('2026-01-01'),
    PARTITION pmax VALUES LESS THAN MAXVALUE
  );

CREATE TABLE order_items (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    order_id BIGINT NOT NULL,
    product_id BIGINT NOT NULL,
    quantity INT DEFAULT 1,
    unit_price DECIMAL(10,2) NOT NULL,
    CONSTRAINT fk_items_order FOREIGN KEY (order_id) REFERENCES orders(id),
    CONSTRAINT fk_items_product FOREIGN KEY (product_id) REFERENCES products(id)
);

-- Stored procedure (TiShift must flag as BLOCKER)
DELIMITER //
CREATE PROCEDURE calculate_order_total(IN p_order_id BIGINT)
BEGIN
    UPDATE orders SET total = (
        SELECT COALESCE(SUM(quantity * unit_price), 0)
        FROM order_items WHERE order_id = p_order_id
    ) WHERE id = p_order_id;
END //
DELIMITER ;

-- Trigger (TiShift must flag as BLOCKER)
DELIMITER //
CREATE TRIGGER trg_order_item_insert AFTER INSERT ON order_items
FOR EACH ROW
BEGIN
    CALL calculate_order_total(NEW.order_id);
END //
DELIMITER ;

-- View
CREATE VIEW active_products AS
SELECT id, name, price, category
FROM products WHERE is_active = 1;

-- Sample data
INSERT INTO customers (email, name) VALUES
    ('alice@example.com', 'Alice Chen'),
    ('bob@example.com', 'Bob Kumar');

INSERT INTO products (name, price, category) VALUES
    ('Widget', 29.99, 'hardware'),
    ('Gadget', 49.99, 'electronics');
