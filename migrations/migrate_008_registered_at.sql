-- Migration 008: registered_at for users
-- Run: psql -U postgres reimbursement -f migrations/migrate_008_registered_at.sql

ALTER TABLE users ADD COLUMN IF NOT EXISTS registered_at TIMESTAMP;
