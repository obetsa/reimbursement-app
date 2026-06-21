-- Migration 016: org_invites + org_member_companies
-- Ці таблиці існували на проді, але ніколи не були зафіксовані як SQL-міграція
-- (створені вручну в БД при розробці org-ієрархії та company access).
-- Run: psql -U postgres reimbursement -f migrations/migrate_016_org_invites_member_companies.sql

CREATE TABLE IF NOT EXISTS org_invites (
    id          TEXT PRIMARY KEY,
    org_id      TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    token       TEXT NOT NULL,
    expires_at  TIMESTAMP NOT NULL,
    created_by  TEXT NOT NULL REFERENCES users(id),
    created_at  TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS org_member_companies (
    id          TEXT PRIMARY KEY,
    org_id      TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company_id  TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    granted_by  TEXT REFERENCES users(id),
    created_at  TIMESTAMP DEFAULT now()
);
