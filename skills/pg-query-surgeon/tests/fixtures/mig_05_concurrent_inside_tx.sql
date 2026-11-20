BEGIN;
SET LOCAL lock_timeout = '2s';
CREATE INDEX CONCURRENTLY idx_users_new_field ON users(new_field);
COMMIT;
