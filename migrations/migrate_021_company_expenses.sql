CREATE TABLE IF NOT EXISTS company_expenses (
    id                     TEXT PRIMARY KEY,
    org_id                 TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    date                   DATE NOT NULL,
    paying_company_id      TEXT REFERENCES companies(id) ON DELETE SET NULL,
    beneficiary_company_id TEXT REFERENCES companies(id) ON DELETE SET NULL,
    amount                 NUMERIC(12,2) NOT NULL DEFAULT 0,
    note                   TEXT,
    created_by             TEXT REFERENCES users(id) ON DELETE SET NULL,
    updated_by             TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at             TIMESTAMP DEFAULT now(),
    updated_at             TIMESTAMP DEFAULT now()
);
