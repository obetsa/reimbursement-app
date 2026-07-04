ALTER TABLE company_expenses ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'waiting' CHECK (status IN ('waiting','partial','done'));
ALTER TABLE company_expenses ADD COLUMN IF NOT EXISTS returned_amount NUMERIC(12,2) NOT NULL DEFAULT 0;
