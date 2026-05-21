-- Migration 005: superadmin flag
-- Run: psql -U postgres reimbursement -f migrate_005_superadmin.sql

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_superadmin BOOLEAN DEFAULT FALSE;

-- Bootstrap: set the system owner as superadmin
UPDATE users SET is_superadmin = TRUE WHERE email = 'obetsa@gmail.com';
