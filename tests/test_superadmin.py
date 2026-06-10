"""
Superadmin tests — SA delete org with member notifications.
Verifies: SA deletes org → org_deletion_notices written → /auth/me returns deletion_notice

Usage: python tests/test_superadmin.py
Requires: server running on localhost:5500, DATABASE_URL in .env
"""
import requests
import uuid
import hashlib
import psycopg2
import psycopg2.extras
import os
from dotenv import load_dotenv

load_dotenv()

BASE = 'http://localhost:5500'
OK   = '✅'
FAIL = '❌'
results = []

def check(name, condition, detail=''):
    mark = OK if condition else FAIL
    results.append((mark, name, detail))
    print(f'{mark}  {name}' + (f'  — {detail}' if detail else ''))

def db():
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn

def pwd_hash(p): return hashlib.sha256(p.encode()).hexdigest()

def make_session(email, password):
    s = requests.Session()
    r = s.post(BASE + '/auth/login', json={'email': email, 'password': password})
    return s if r.ok and r.json().get('ok') else None

# ── Setup ──
print('── Setup: створення тестових даних ──')

conn = db(); cur = conn.cursor()
PASSWORD = 'testpass123'

SA_EMAIL    = f'_sa_{uuid.uuid4().hex[:6]}@test.local'
OWNER_EMAIL = f'_owner_{uuid.uuid4().hex[:6]}@test.local'
MEMB_EMAIL  = f'_memb_{uuid.uuid4().hex[:6]}@test.local'
ORG_NAME    = f'_TestSAOrg_{uuid.uuid4().hex[:6]}'

# Create SA user
sa_id = str(uuid.uuid4())
cur.execute(
    "INSERT INTO users (id, email, password_hash, full_name, email_verified, is_superadmin) VALUES (%s,%s,%s,'SA',TRUE,TRUE)",
    (sa_id, SA_EMAIL, pwd_hash(PASSWORD))
)

# Create org owner
owner_id = str(uuid.uuid4())
cur.execute(
    "INSERT INTO users (id, email, password_hash, full_name, email_verified) VALUES (%s,%s,%s,'Owner',TRUE)",
    (owner_id, OWNER_EMAIL, pwd_hash(PASSWORD))
)

# Create org member
memb_id = str(uuid.uuid4())
cur.execute(
    "INSERT INTO users (id, email, password_hash, full_name, email_verified) VALUES (%s,%s,%s,'Member',TRUE)",
    (memb_id, MEMB_EMAIL, pwd_hash(PASSWORD))
)

# Create org
org_id = str(uuid.uuid4())
inv = uuid.uuid4().hex[:8].upper()
cur.execute(
    "INSERT INTO organizations (id, name, invite_code, password_hash, owner_id) VALUES (%s,%s,%s,'x',%s)",
    (org_id, ORG_NAME, inv, owner_id)
)

# Add owner and member
cur.execute(
    "INSERT INTO org_members (id, org_id, user_id, role) VALUES (%s,%s,%s,'admin')",
    (str(uuid.uuid4()), org_id, owner_id)
)
cur.execute(
    "INSERT INTO org_members (id, org_id, user_id, role) VALUES (%s,%s,%s,'user')",
    (str(uuid.uuid4()), org_id, memb_id)
)

conn.commit()
print(f'  SA:     {SA_EMAIL}')
print(f'  Owner:  {OWNER_EMAIL}')
print(f'  Member: {MEMB_EMAIL}')
print(f'  Org:    {ORG_NAME} ({org_id})\n')

# ── Tests ──
print('── Тести ──')

# 1. SA login
sa_session = make_session(SA_EMAIL, PASSWORD)
check('SA: логін успішний', sa_session is not None)

# 1b. SA also authenticates with ADMIN_TOKEN (required by /superadmin/* since AND-logic fix)
if sa_session:
    r = sa_session.post(BASE + '/admin/login', json={'token': os.environ['ADMIN_TOKEN']})
    check('SA: /admin/login з ADMIN_TOKEN → 200', r.status_code == 200, f'status={r.status_code}')

# 2. SA can see org in list
r = sa_session.get(BASE + '/superadmin/orgs') if sa_session else None
if r and r.ok:
    orgs = r.json()
    found = any(o['id'] == org_id for o in orgs)
    check('SA: org є в /superadmin/orgs', found)
else:
    check('SA: /superadmin/orgs відповідає', False, r.status_code if r else 'no session')

# 3. SA deletes org
r = sa_session.delete(BASE + f'/superadmin/orgs/{org_id}') if sa_session else None
check('SA: DELETE /superadmin/orgs/{id} → 200', r is not None and r.status_code == 200)

# Refresh snapshot: server committed changes, need a new read transaction
conn.commit()

# 4. org_deletion_notices created for owner
cur2 = conn.cursor()
cur2.execute("SELECT * FROM org_deletion_notices WHERE user_id=%s AND org_name=%s", (owner_id, ORG_NAME))
owner_notice = cur2.fetchone()
check('owner: org_deletion_notices запис існує', owner_notice is not None)

# 5. org_deletion_notices created for member
cur2.execute("SELECT * FROM org_deletion_notices WHERE user_id=%s AND org_name=%s", (memb_id, ORG_NAME))
memb_notice = cur2.fetchone()
check('member: org_deletion_notices запис існує', memb_notice is not None)

# 6. owner's /auth/me returns deletion_notice (reads and deletes it)
owner_session = make_session(OWNER_EMAIL, PASSWORD)
check('owner: логін успішний', owner_session is not None)
if owner_session:
    r = owner_session.get(BASE + '/auth/me')
    data = r.json() if r.ok else {}
    check('owner: /auth/me повертає deletion_notice', data.get('deletion_notice') == ORG_NAME,
          repr(data.get('deletion_notice')))

# 7. member's /auth/me returns deletion_notice
memb_session = make_session(MEMB_EMAIL, PASSWORD)
check('member: логін успішний', memb_session is not None)
if memb_session:
    r = memb_session.get(BASE + '/auth/me')
    data = r.json() if r.ok else {}
    check('member: /auth/me повертає deletion_notice', data.get('deletion_notice') == ORG_NAME,
          repr(data.get('deletion_notice')))

# 8. After /auth/me consumed the notice, it should be gone from DB
cur2.execute("SELECT * FROM org_deletion_notices WHERE user_id=%s AND org_name=%s", (owner_id, ORG_NAME))
check('owner: notice видалено після /auth/me', cur2.fetchone() is None)

# 9. Org no longer exists
cur2.execute("SELECT id FROM organizations WHERE id=%s", (org_id,))
check('org: видалена з БД', cur2.fetchone() is None)

# ── Cleanup ──
print('\n── Cleanup ──')
try:
    cur2.execute("DELETE FROM org_deletion_notices WHERE user_id IN (%s,%s)", (owner_id, memb_id))
    cur2.execute("DELETE FROM users WHERE id IN (%s,%s,%s)", (sa_id, owner_id, memb_id))
    conn.commit()
    print('  Cleanup OK')
except Exception as e:
    print(f'  Cleanup error: {e}')
finally:
    conn.close()

# ── Summary ──
passed = sum(1 for r in results if r[0] == OK)
failed = sum(1 for r in results if r[0] == FAIL)
print(f'\n── {passed}/{len(results)} passed' + (f', {failed} failed ──' if failed else ' ──'))
if failed:
    raise SystemExit(1)
