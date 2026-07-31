CREATE TABLE IF NOT EXISTS company_expense_attachments (
    id           TEXT PRIMARY KEY,
    cexp_id      TEXT NOT NULL REFERENCES company_expenses(id) ON DELETE CASCADE,
    file_name    TEXT NOT NULL,
    file_type    TEXT,
    file_path    TEXT,
    created_at   TIMESTAMP DEFAULT now()
);
