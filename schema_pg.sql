-- PostgreSQL schema for reimbursement-app
-- Run: psql -U postgres reimbursement < docs/schema_pg.sql

CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    email       TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name   TEXT,
    refresh_token TEXT,
    created_at  TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS companies (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    name        TEXT NOT NULL,
    is_shared   INTEGER DEFAULT 0,
    is_active   INTEGER DEFAULT 1,
    sort_order  INTEGER DEFAULT 0,
    is_deleted  INTEGER DEFAULT 0,
    deleted_at  TIMESTAMP,
    created_at  TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS payment_instruments (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,
    is_active   INTEGER DEFAULT 1,
    sort_order  INTEGER DEFAULT 0,
    is_deleted  INTEGER DEFAULT 0,
    deleted_at  TIMESTAMP,
    created_at  TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS records (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    title           TEXT NOT NULL,
    note            TEXT,
    date            TEXT NOT NULL,
    created_at      TIMESTAMP DEFAULT now(),
    amount          REAL NOT NULL,
    currency        TEXT DEFAULT 'EUR',
    pay_type        TEXT NOT NULL,
    pay_method      TEXT NOT NULL,
    card_id         TEXT,
    company_id      TEXT,
    status          TEXT DEFAULT 'waiting',
    previous_status TEXT,
    to_return       REAL DEFAULT 0,
    returned        REAL DEFAULT 0,
    remainder       REAL DEFAULT 0,
    is_archived     INTEGER DEFAULT 0,
    is_deleted      INTEGER DEFAULT 0,
    deleted_at      TIMESTAMP
);

CREATE TABLE IF NOT EXISTS return_events (
    id          TEXT PRIMARY KEY,
    record_id   TEXT NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    amount      REAL NOT NULL,
    date        TEXT NOT NULL,
    method      TEXT,
    created_at  TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS attachments (
    id           TEXT PRIMARY KEY,
    record_id    TEXT NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    file_name    TEXT NOT NULL,
    file_type    TEXT,
    file_url     TEXT,
    file_path    TEXT,
    storage_type TEXT DEFAULT 'local',
    drive_id     TEXT,
    created_at   TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS unprocessed_imports (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    drive_id     TEXT NOT NULL,
    file_name    TEXT NOT NULL,
    mime_type    TEXT,
    drive_folder TEXT DEFAULT '',
    synced_at    TIMESTAMP DEFAULT now()
);
