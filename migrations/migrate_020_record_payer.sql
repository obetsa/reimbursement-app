-- Платник запису (хто фактично платив)
ALTER TABLE records ADD COLUMN IF NOT EXISTS payer_id TEXT REFERENCES users(id) ON DELETE SET NULL;
