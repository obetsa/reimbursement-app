-- Tenant settings (Фаза 2.1): default_currency (EUR/UAH/USD), розширюється на майбутнє
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS settings JSONB DEFAULT '{}'::jsonb;
