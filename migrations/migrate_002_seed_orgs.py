"""
Migration 002: create organization for each existing user and link their data.
Run: python migrate_002_seed_orgs.py
"""
import os, uuid, secrets, hashlib
import psycopg2, psycopg2.extras
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

cur.execute("SELECT id, email FROM users")
users = cur.fetchall()

print(f"Знайдено юзерів: {len(users)}")

for user in users:
    user_id = user['id']
    email   = user['email']

    # Check if org already exists for this user
    cur.execute("SELECT id FROM organizations WHERE owner_id = %s", (user_id,))
    if cur.fetchone():
        print(f"  {email} — організація вже є, пропускаємо")
        continue

    org_id      = str(uuid.uuid4())
    invite_code = secrets.token_hex(4).upper()  # наприклад A3F9B2C1
    pwd_hash    = hashlib.sha256(invite_code.encode()).hexdigest()  # пароль = invite_code за замовчуванням
    org_name    = email.split('@')[0]  # назва = частина email до @

    # Create organization
    cur.execute(
        "INSERT INTO organizations (id, name, invite_code, password_hash, owner_id) VALUES (%s,%s,%s,%s,%s)",
        (org_id, org_name, invite_code, pwd_hash, user_id)
    )

    # Add user as admin
    cur.execute(
        "INSERT INTO org_members (id, org_id, user_id, role) VALUES (%s,%s,%s,'admin')",
        (str(uuid.uuid4()), org_id, user_id)
    )

    # Link existing data to this org
    cur.execute("UPDATE companies           SET org_id=%s WHERE user_id=%s", (org_id, user_id))
    cur.execute("UPDATE payment_instruments SET org_id=%s WHERE user_id=%s", (org_id, user_id))
    cur.execute("UPDATE records             SET org_id=%s WHERE user_id=%s", (org_id, user_id))
    cur.execute("UPDATE unprocessed_imports SET org_id=%s WHERE user_id=%s", (org_id, user_id))

    conn.commit()
    print(f"  {email} → org '{org_name}' | invite_code: {invite_code}")

# Verify
cur.execute("SELECT COUNT(*) FROM organizations")
org_count = cur.fetchone()['count']
cur.execute("SELECT COUNT(*) FROM org_members")
mem_count = cur.fetchone()['count']
cur.execute("SELECT COUNT(*) FROM records WHERE org_id IS NULL")
null_records = cur.fetchone()['count']

print(f"\nРезультат:")
print(f"  Організацій: {org_count}")
print(f"  Членів:      {mem_count}")
print(f"  Записів без org_id: {null_records}")

conn.close()
print("\nГотово.")
