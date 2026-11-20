SELECT * FROM orders WHERE LOWER(customer_email) = 'alice@example.com' AND status = 'PAID' ORDER BY created_at DESC OFFSET 5000;
SELECT id, total_cents FROM orders WHERE notes ILIKE '%urgent%' AND created_at >= '2026-01-01';
SELECT id FROM customers WHERE id NOT IN (SELECT customer_id FROM orders);
SELECT id, status FROM orders WHERE customer_id = 101;
SELECT id, status FROM orders WHERE customer_id = 102;
SELECT id, status FROM orders WHERE customer_id = 103;
SELECT id, status FROM orders WHERE customer_id = 104;
