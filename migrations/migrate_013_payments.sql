-- Фаза 3 (Крок 1): архітектура оплат — без провайдера, підключення пізніше.
-- Один платіж = план назавжди (поки SA не змінить вручну), без plan_expires_at.
-- valid_until лишено NULL і не використовується зараз — підготовка під майбутні періоди (місяць/рік),
-- щоб ввести їх пізніше без нової міграції.

CREATE TABLE IF NOT EXISTS payments (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_id              TEXT REFERENCES organizations(id) ON DELETE CASCADE,
    target              TEXT NOT NULL,              -- 'user_plan' | 'org_plan'
    plan                TEXT NOT NULL,              -- 'pro' | 'ultimate'
    provider            TEXT,                       -- 'liqpay' | 'stripe' | NULL (поки не обрано)
    provider_payment_id TEXT,
    amount              NUMERIC(10,2),
    currency            TEXT,
    status              TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'completed' | 'failed'
    valid_until         TIMESTAMP,                  -- NULL = довічно (поточна модель)
    created_at          TIMESTAMP DEFAULT now(),
    completed_at        TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id);
CREATE INDEX IF NOT EXISTS idx_payments_org_id ON payments(org_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
