BEGIN;
SET LOCAL lock_timeout = '2s';
ALTER TABLE users ADD COLUMN new_field TEXT;
COMMIT;
CREATE INDEX CONCURRENTLY idx_users_new_field ON users(new_field);
