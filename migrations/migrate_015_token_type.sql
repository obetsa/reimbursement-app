-- Migration 015: add token_type to email_verifications
-- Run: psql -U postgres reimbursement -f migrations/migrate_015_token_type.sql

ALTER TABLE email_verifications
  ADD COLUMN IF NOT EXISTS token_type VARCHAR(20) DEFAULT 'activation';
