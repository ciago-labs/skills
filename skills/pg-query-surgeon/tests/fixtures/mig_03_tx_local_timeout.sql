BEGIN;
SET LOCAL lock_timeout = '2s';
ALTER TABLE users ADD COLUMN new_field TEXT;
COMMIT;
ALTER TABLE users ADD COLUMN second_unguarded_field TEXT;
