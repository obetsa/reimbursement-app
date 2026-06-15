-- Migration 014: organizations.name unique (case-insensitive)
-- Run: psql -U postgres reimbursement -f migrate_014_org_name_unique.sql
--
-- Підготовчий крок перед переходом шляхів файлів на org_name (наступний реліз).

CREATE UNIQUE INDEX IF NOT EXISTS organizations_name_lower_idx ON organizations (lower(name));
