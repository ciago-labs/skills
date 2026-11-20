-- Connection: postgresql://dbadmin:SuperSecretPass123!@prod-db.internal:5432/orders_db
BEGIN;

CREATE INDEX idx_orders_customer_status ON orders (customer_id, status);

CREATE INDEX CONCURRENTLY idx_orders_concurrent_in_tx ON orders (created_at);

ALTER TABLE orders ALTER COLUMN total_cents TYPE BIGINT;

ALTER TABLE orders ADD COLUMN audit_token TEXT DEFAULT gen_random_uuid()::text;

ALTER TABLE orders ALTER COLUMN shipping_address SET NOT NULL;

ALTER TABLE orders ADD CONSTRAINT fk_orders_merchant FOREIGN KEY (merchant_id) REFERENCES merchants (id);

ALTER TABLE orders DROP COLUMN legacy_coupon_code;

COMMIT;
