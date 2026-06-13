"""
Billing tests (Фаза 3, Крок 1) — архітектура без провайдера.
Verifies: payments-таблиця, /billing/checkout і /billing/webhook стаби (503 поки PAYMENT_PROVIDER не налаштований),
apply_plan_payment() застосовує план до user/org.

Usage: python tests/test_billing.py
Requires: server running on localhost:5500, DATABASE_URL в .env
"""
import requests
import uuid
import hashlib
import psycopg2
import psycopg2.extras
import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import api

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

USER_EMAIL = f'_pay_{uuid.uuid4().hex[:6]}@test.local'
ORG_NAME   = f'_PayOrg_{uuid.uuid4().hex[:6]}'

user_id = str(uuid.uuid4())
cur.execute(
    "INSERT INTO users (id, email, password_hash, full_name, email_verified) VALUES (%s,%s,%s,'Payer',TRUE)",
    (user_id, USER_EMAIL, pwd_hash(PASSWORD))
)

org_id = str(uuid.uuid4())
inv = uuid.uuid4().hex[:8].upper()
cur.execute(
    "INSERT INTO organizations (id, name, invite_code, password_hash, owner_id, plan) VALUES (%s,%s,%s,'x',%s,'free')",
    (org_id, ORG_NAME, inv, user_id)
)
cur.execute(
    "INSERT INTO org_members (id, org_id, user_id, role) VALUES (%s,%s,%s,'admin')",
    (str(uuid.uuid4()), org_id, user_id)
)
conn.commit()
print(f'  User: {USER_EMAIL}')
print(f'  Org:  {ORG_NAME} ({org_id})\n')

# ── Тести ──
print('── Тести ──')

# 1. payments table exists
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='payments'")
cols = {r['column_name'] for r in cur.fetchall()}
check('payments: таблиця існує', len(cols) > 0)
for c in ('id', 'user_id', 'org_id', 'target', 'plan', 'provider', 'status', 'valid_until', 'created_at', 'completed_at'):
    check(f'payments: колонка {c}', c in cols)

# 2. /billing/checkout -> 503 поки PAYMENT_PROVIDER не налаштований
session = make_session(USER_EMAIL, PASSWORD)
check('user: логін успішний', session is not None)
if session:
    r = session.post(BASE + '/billing/checkout', json={'target': 'user_plan', 'plan': 'pro'})
    check('checkout: 503 без провайдера', r.status_code == 503, f'status={r.status_code}')

# 3. /billing/webhook/<provider> -> 503 поки PAYMENT_PROVIDER не налаштований
r = requests.post(BASE + '/billing/webhook/liqpay', json={})
check('webhook: 503 без провайдера', r.status_code == 503, f'status={r.status_code}')

# 4. apply_plan_payment(): user_plan
payment_id = str(uuid.uuid4())
cur.execute(
    "INSERT INTO payments (id, user_id, org_id, target, plan, status) VALUES (%s,%s,NULL,'user_plan','pro','pending')",
    (payment_id, user_id)
)
conn.commit()

pay_conn = api.get_db()
applied = api.apply_plan_payment(payment_id, pay_conn)
pay_conn.commit()
pay_conn.close()
check('apply_plan_payment: повертає True', applied)

cur.execute("SELECT plan FROM users WHERE id=%s", (user_id,))
check('apply_plan_payment: users.plan = pro', cur.fetchone()['plan'] == 'pro')
cur.execute("SELECT status, completed_at FROM payments WHERE id=%s", (payment_id,))
row = cur.fetchone()
check('apply_plan_payment: payments.status = completed', row['status'] == 'completed')
check('apply_plan_payment: completed_at заповнено', row['completed_at'] is not None)

# 5. apply_plan_payment(): org_plan
payment_id2 = str(uuid.uuid4())
cur.execute(
    "INSERT INTO payments (id, user_id, org_id, target, plan, status) VALUES (%s,%s,%s,'org_plan','ultimate','pending')",
    (payment_id2, user_id, org_id)
)
conn.commit()

pay_conn = api.get_db()
applied2 = api.apply_plan_payment(payment_id2, pay_conn)
pay_conn.commit()
pay_conn.close()
check('apply_plan_payment (org): повертає True', applied2)

cur.execute("SELECT plan FROM organizations WHERE id=%s", (org_id,))
check('apply_plan_payment (org): organizations.plan = ultimate', cur.fetchone()['plan'] == 'ultimate')

# 6. apply_plan_payment(): повторний виклик на completed -> False
pay_conn = api.get_db()
applied3 = api.apply_plan_payment(payment_id, pay_conn)
pay_conn.close()
check('apply_plan_payment: повторно на completed -> False', applied3 is False)

# ── Cleanup ──
print('\n── Cleanup ──')
try:
    cur.execute("DELETE FROM payments WHERE user_id=%s", (user_id,))
    cur.execute("DELETE FROM org_members WHERE org_id=%s", (org_id,))
    cur.execute("DELETE FROM organizations WHERE id=%s", (org_id,))
    cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
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
