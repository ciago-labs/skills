CREATE TABLE merchants (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE orders (
    id INT PRIMARY KEY,
    customer_id BIGINT NOT NULL,
    merchant_id INT NOT NULL REFERENCES merchants(id),
    status TEXT NOT NULL,
    total_cents INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE audit_events (
    event_type TEXT NOT NULL,
    payload JSONB
);

CREATE INDEX idx_orders_created_at ON orders (created_at);
