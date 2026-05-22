-- Migration 006: multi-org support
-- Run: psql -U postgres reimbursement -f migrate_006_multiorg.sql

-- User plan (free / premium)
ALTER TABLE users ADD COLUMN IF NOT EXISTS plan TEXT DEFAULT 'free';

-- Org deletion notices — shown once to members when owner deletes org
CREATE TABLE IF NOT EXISTS org_deletion_notices (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_name   TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT now()
);
