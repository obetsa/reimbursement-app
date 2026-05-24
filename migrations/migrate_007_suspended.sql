-- SA.5: Suspend/unsuspend org
-- Run: psql -U postgres reimbursement -f migrations/migrate_007_suspended.sql

ALTER TABLE organizations ADD COLUMN IF NOT EXISTS is_suspended BOOLEAN DEFAULT FALSE;
