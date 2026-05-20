-- Migration 002: soft leave org
-- Run: psql -U postgres reimbursement -f migrate_002_leave_org.sql

ALTER TABLE org_members ADD COLUMN IF NOT EXISTS left_at TIMESTAMP DEFAULT NULL;
