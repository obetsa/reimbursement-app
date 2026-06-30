"""
Migration runner: накатує pending SQL-міграції при старті застосунку.
Працює з app-контейнера (не з db) — файли вже всередині образу через Dockerfile COPY,
нічого не треба окремо закидати на сервер.

Трекає застосовані міграції в таблиці schema_migrations — безпечно і на порожній БД
(застосує все з нуля), і на вже існуючій (пропустить те, що вже там є).
"""
import os

MIGRATIONS_DIR = os.path.dirname(os.path.abspath(__file__))

# Порядок важливий — кожен файл може залежати від попередніх
ORDERED_FILES = [
    'schema_pg.sql',
    'migrate_001_org_hierarchy.sql',
    'migrate_002_leave_org.sql',
    'migrate_003_email_verification.sql',
    'migrate_005_superadmin.sql',
    'migrate_006_multiorg.sql',
    'migrate_007_suspended.sql',
    'migrate_008_registered_at.sql',
    'migrate_009_user_suspended.sql',
    'migrate_010_org_plan.sql',
    'migrate_011_org_settings.sql',
    'migrate_012_plan_tiers.sql',
    'migrate_013_payments.sql',
    'migrate_014_org_name_unique.sql',
    'migrate_015_token_type.sql',
    'migrate_016_org_invites_member_companies.sql',
    'migrate_017_fix_org_members_role_check.sql',
    'migrate_018_remove_drive_columns.sql',
]


def run_pending_migrations(database_url):
    import psycopg2

    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename    TEXT PRIMARY KEY,
            applied_at  TIMESTAMP DEFAULT now()
        )
    """)
    conn.commit()

    cur.execute("SELECT filename FROM schema_migrations")
    applied = {row[0] for row in cur.fetchall()}

    for filename in ORDERED_FILES:
        if filename in applied:
            continue
        path = os.path.join(MIGRATIONS_DIR, filename)
        with open(path, 'r', encoding='utf-8') as f:
            sql = f.read()
        print(f"[migrations] застосовую {filename}...")
        try:
            cur.execute(sql)
            cur.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (filename,))
            conn.commit()
        except Exception:
            conn.rollback()
            cur.close()
            conn.close()
            raise

    cur.close()
    conn.close()
