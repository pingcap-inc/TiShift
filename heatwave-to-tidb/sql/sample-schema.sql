-- Sample HeatWave schema exercising the features the scanner must detect.
-- Load into a HeatWave DB System (or plain MySQL 8.0+/9.x — VECTOR and
-- SECONDARY_ENGINE statements will fail on older/community builds; that is
-- expected and useful for testing graceful degradation).

CREATE DATABASE IF NOT EXISTS tishift_demo;
USE tishift_demo;

-- Plain InnoDB table — fully compatible baseline
CREATE TABLE customers (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  email VARCHAR(255) NOT NULL UNIQUE,
  name VARCHAR(120) NOT NULL,
  profile JSON,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;  -- WARNING-4 collation

-- RAPID-offloaded fact table — HW-WARNING-1, maps to TiFlash replica
CREATE TABLE orders (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  customer_id BIGINT UNSIGNED NOT NULL,
  status ENUM('new','paid','shipped','cancelled') NOT NULL DEFAULT 'new',
  amount DECIMAL(12,2) NOT NULL,
  notes TEXT NOT SECONDARY,          -- column excluded from RAPID
  ordered_at DATETIME NOT NULL,
  CONSTRAINT fk_orders_customer FOREIGN KEY (customer_id) REFERENCES customers (id)  -- WARNING-1
) ENGINE=InnoDB SECONDARY_ENGINE=RAPID;
-- ALTER TABLE orders SECONDARY_LOAD;   -- run when a HeatWave cluster is attached

-- Spatial column — BLOCKER-4
CREATE TABLE stores (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(80) NOT NULL,
  location POINT NOT NULL SRID 4326,
  SPATIAL INDEX idx_location (location)
) ENGINE=InnoDB;

-- FULLTEXT index — WARNING-2 on self-hosted targets
CREATE TABLE articles (
  id INT AUTO_INCREMENT PRIMARY KEY,
  title VARCHAR(200) NOT NULL,
  body MEDIUMTEXT,
  FULLTEXT INDEX idx_body (title, body)
) ENGINE=InnoDB;

-- VECTOR column (MySQL 9 / HeatWave GenAI) — HW-WARNING-2
-- CREATE TABLE embeddings (
--   id BIGINT AUTO_INCREMENT PRIMARY KEY,
--   article_id INT NOT NULL,
--   embedding VECTOR(1536)
-- ) ENGINE=InnoDB;

-- Stored procedure — BLOCKER-1
DELIMITER //
CREATE PROCEDURE settle_order(IN p_order_id BIGINT)
BEGIN
  UPDATE orders SET status = 'paid' WHERE id = p_order_id;
END//
DELIMITER ;

-- Trigger — BLOCKER-2
DELIMITER //
CREATE TRIGGER trg_orders_audit AFTER UPDATE ON orders
FOR EACH ROW
BEGIN
  INSERT INTO order_audit (order_id, old_status, new_status)
  VALUES (OLD.id, OLD.status, NEW.status);
END//
DELIMITER ;

CREATE TABLE order_audit (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  order_id BIGINT NOT NULL,
  old_status VARCHAR(20),
  new_status VARCHAR(20),
  changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- Scheduled event — BLOCKER-3
CREATE EVENT IF NOT EXISTS ev_purge_audit
ON SCHEDULE EVERY 1 DAY
DO DELETE FROM order_audit WHERE changed_at < NOW() - INTERVAL 90 DAY;
