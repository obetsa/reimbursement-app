-- Migration 017: fix stale CHECK constraint on org_members.role
-- Old constraint allowed only ('admin', 'user', 'viewer') — 'viewer' is removed, 'manager' was missing
-- Drop all CHECK constraints on role column and recreate with correct values

ALTER TABLE org_members DROP CONSTRAINT IF EXISTS org_members_role_check;

ALTER TABLE org_members ADD CONSTRAINT org_members_role_check
    CHECK (role IN ('admin', 'manager', 'user'));
