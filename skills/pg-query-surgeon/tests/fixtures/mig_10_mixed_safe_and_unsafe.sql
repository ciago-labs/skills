SET lock_timeout = '2s';
ALTER TABLE users ADD COLUMN bio TEXT;
CREATE INDEX idx_users_bio_blocking ON users(bio);
