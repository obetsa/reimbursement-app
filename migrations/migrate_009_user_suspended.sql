-- Migration 009: suspend/unsuspend user
-- Run: psql -U postgres reimbursement -f migrations/migrate_009_user_suspended.sql

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_suspended BOOLEAN DEFAULT FALSE;
