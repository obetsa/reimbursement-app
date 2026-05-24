-- Migration 003: email verification
-- Run: psql -U postgres reimbursement -f migrate_003_email_verification.sql

ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT FALSE;

-- All existing users are already active — mark as verified
UPDATE users SET email_verified = TRUE;

CREATE TABLE IF NOT EXISTS email_verifications (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token      TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT now()
);
