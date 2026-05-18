-- Migration 001: org hierarchy
-- Run: psql -U postgres reimbursement -f migrate_001_org_hierarchy.sql

CREATE TABLE IF NOT EXISTS organizations (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    invite_code  TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    owner_id     TEXT NOT NULL REFERENCES users(id),
    created_at   TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS org_members (
    id         TEXT PRIMARY KEY,
    org_id     TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role       TEXT NOT NULL CHECK (role IN ('admin', 'user', 'viewer')),
    joined_at  TIMESTAMP DEFAULT now(),
    UNIQUE (org_id, user_id)
);

ALTER TABLE companies            ADD COLUMN IF NOT EXISTS org_id TEXT REFERENCES organizations(id);
ALTER TABLE payment_instruments  ADD COLUMN IF NOT EXISTS org_id TEXT REFERENCES organizations(id);
ALTER TABLE records              ADD COLUMN IF NOT EXISTS org_id TEXT REFERENCES organizations(id);
ALTER TABLE unprocessed_imports  ADD COLUMN IF NOT EXISTS org_id TEXT REFERENCES organizations(id);
