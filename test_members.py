"""
Member management tests — invite, activate, exclude, restore, permanent delete.
Usage: python test_members.py <session_cookie>

session_cookie — admin session (e.g. from 1@1 / 123456).
"""
import requests
import sys
import uuid
import psycopg2
import psycopg2.extras
import os
from dotenv import load_dotenv

load_dotenv()

if len(sys.argv) < 2:
    print('Usage: python test_members.py <session_cookie>')
    sys.exit(1)

BASE    = 'http://localhost:5500'
session = requests.Session()
session.headers.update({'Cookie': f'session={sys.argv[1]}'})

OK   = '✅'
FAIL = '❌'
results = []

def check(name, condition, detail=''):
    mark = OK if condition else FAIL
    results.append((mark, name, detail))
    print(f'{mark}  {name}' + (f'  — {detail}' if detail else ''))

def get(path):             return session.get(BASE + path)
def post(path, **kw):      return session.post(BASE + path, **kw)
def put(path, **kw):       return session.put(BASE + path, **kw)
def delete(path):          return session.delete(BASE + path)

def db():
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn

TEST_EMAIL = f'_test_{uuid.uuid4().hex[:8]}@test.local'
invited_user_id = None
activate_token  = None


# ══════════════════════════════════════════
print('── Передумови ──')
# ══════════════════════════════════════════

r = get('/auth/me')
check('Сервер відповідає', r.status_code == 200)
check('Залогінений як admin', r.status_code == 200 and r.json().get('email'))

r = get('/org/me')
check('Є активна org', r.status_code == 200)
org = r.json() if r.ok else {}
check('  role = admin', org.get('role') == 'admin', f"role={org.get('role')}")


# ══════════════════════════════════════════
print('\n── Реєстрація закрита ──')
# ══════════════════════════════════════════

r = post('/auth/register', json={'email': TEST_EMAIL, 'password': 'test123'})
check('POST /auth/register → 403', r.status_code == 403, f'status={r.status_code}')
check('  error=registration_closed', r.json().get('error') == 'registration_closed')


# ══════════════════════════════════════════
print('\n── Invite нового юзера ──')
# ══════════════════════════════════════════

r = post('/org/members/invite', json={
    'email':     TEST_EMAIL,
    'full_name': 'Test Member',
    'role':      'user',
})
check('POST /org/members/invite → 200', r.status_code == 200, f'status={r.status_code}')
data = r.json() if r.ok else {}
check('  ok=True',          data.get('ok') is True)
check('  existing_user=False', data.get('existing_user') is False)

# Перевіряємо БД
conn = db()
cur  = conn.cursor()
cur.execute("SELECT id, password_hash, email_verified FROM users WHERE email=%s", (TEST_EMAIL,))
u = cur.fetchone()
check('  юзер створений в БД',          u is not None)
check('  password_hash = PENDING',       u and u['password_hash'] == 'PENDING')
check('  email_verified = False',        u and u['email_verified'] is False)
invited_user_id = u['id'] if u else None

cur.execute("SELECT role, left_at FROM org_members WHERE user_id=%s", (invited_user_id,))
m = cur.fetchone()
check('  доданий в org_members',   m is not None)
check('  role = user',             m and m['role'] == 'user')
check('  left_at = NULL',          m and m['left_at'] is None)

cur.execute("SELECT token FROM email_verifications WHERE user_id=%s AND expires_at > now()", (invited_user_id,))
ev = cur.fetchone()
check('  activation token в БД',   ev is not None)
activate_token = ev['token'] if ev else None
conn.close()


# ══════════════════════════════════════════
print('\n── Pending в списку членів ──')
# ══════════════════════════════════════════

r = get('/org/members')
check('GET /org/members → 200', r.status_code == 200)
members  = r.json() if r.ok else []
pending  = [m for m in members if m.get('user_id') == invited_user_id]
check('  invited user є в списку',  len(pending) == 1)
check('  is_pending = True',        pending and pending[0].get('is_pending') is True)
check('  left_at = None',           pending and pending[0].get('left_at') is None)


# ══════════════════════════════════════════
print('\n── Повторне запрошення (resend) ──')
# ══════════════════════════════════════════

r = post(f'/org/members/{invited_user_id}/resend-invite')
check('POST /resend-invite → 200', r.status_code == 200, f'status={r.status_code}')

conn = db(); cur = conn.cursor()
cur.execute("SELECT token FROM email_verifications WHERE user_id=%s AND expires_at > now()", (invited_user_id,))
ev2 = cur.fetchone()
conn.close()
check('  новий токен в БД',          ev2 is not None)
check('  токен змінився',            ev2 and ev2['token'] != activate_token)
activate_token = ev2['token'] if ev2 else activate_token


# ══════════════════════════════════════════
print('\n── Activation flow ──')
# ══════════════════════════════════════════

# Невірний токен
r = post('/auth/activate', json={'token': 'wrongtoken', 'password': 'newpass1'})
check('POST /auth/activate з невірним токеном → 400', r.status_code == 400, f'status={r.status_code}')

# Занадто короткий пароль
r = post('/auth/activate', json={'token': activate_token, 'password': '123'})
check('POST /auth/activate з коротким паролем → 400', r.status_code == 400, f'status={r.status_code}')

# Правильна активація
new_session = requests.Session()
r = new_session.post(BASE + '/auth/activate', json={'token': activate_token, 'password': 'activated123'})
check('POST /auth/activate з правильним токеном → 200', r.status_code == 200, f'status={r.status_code}')
check('  ok=True', r.json().get('ok') is True)

# Перевіряємо що юзер залогінений
r2 = new_session.get(BASE + '/auth/me', cookies=new_session.cookies)
check('  юзер залогінений після активації', r2.status_code == 200)
check('  email збігається', r2.ok and r2.json().get('email') == TEST_EMAIL)

# Перевіряємо БД — пароль змінено, токен видалено
conn = db(); cur = conn.cursor()
cur.execute("SELECT password_hash, email_verified FROM users WHERE id=%s", (invited_user_id,))
u2 = cur.fetchone()
check('  password_hash != PENDING',    u2 and u2['password_hash'] != 'PENDING')
check('  email_verified = True',       u2 and u2['email_verified'] is True)
cur.execute("SELECT id FROM email_verifications WHERE user_id=%s", (invited_user_id,))
check('  токен видалений з БД',        cur.fetchone() is None)
conn.close()


# ══════════════════════════════════════════
print('\n── Soft exclude (м\'яке виключення) ──')
# ══════════════════════════════════════════

r = delete(f'/org/members/{invited_user_id}')
check('DELETE /org/members/{id} → 200', r.status_code == 200, f'status={r.status_code}')

conn = db(); cur = conn.cursor()
cur.execute("SELECT left_at FROM org_members WHERE user_id=%s", (invited_user_id,))
m2 = cur.fetchone()
conn.close()
check('  left_at встановлено',  m2 and m2['left_at'] is not None)

# Виключений бачиться в списку
r = get('/org/members')
members2 = r.json() if r.ok else []
excluded = [m for m in members2 if m.get('user_id') == invited_user_id]
check('  виключений є в списку',       len(excluded) == 1)
check('  left_at не NULL в response',  excluded and excluded[0].get('left_at') is not None)
check('  is_pending = False',          excluded and excluded[0].get('is_pending') is False)


# ══════════════════════════════════════════
print('\n── Restore ──')
# ══════════════════════════════════════════

r = put(f'/org/members/{invited_user_id}/restore')
check('PUT /org/members/{id}/restore → 200', r.status_code == 200, f'status={r.status_code}')

conn = db(); cur = conn.cursor()
cur.execute("SELECT left_at FROM org_members WHERE user_id=%s", (invited_user_id,))
m3 = cur.fetchone()
conn.close()
check('  left_at = NULL після restore', m3 and m3['left_at'] is None)


# ══════════════════════════════════════════
print('\n── Permanent delete ──')
# ══════════════════════════════════════════

# Soft exclude перед permanent (для реального флоу)
delete(f'/org/members/{invited_user_id}')

r = session.delete(BASE + f'/org/members/{invited_user_id}/permanent')
check('DELETE /org/members/{id}/permanent → 200', r.status_code == 200, f'status={r.status_code}')

conn = db(); cur = conn.cursor()
cur.execute("SELECT id FROM org_members WHERE user_id=%s", (invited_user_id,))
check('  рядок видалено з org_members',           cur.fetchone() is None)
cur.execute("SELECT id FROM org_member_companies WHERE user_id=%s", (invited_user_id,))
check('  company_access видалено',                 cur.fetchone() is None)
conn.close()


# ══════════════════════════════════════════
print('\n── Invite існуючого юзера ──')
# ══════════════════════════════════════════

# Запрошуємо юзера який вже є в системі (але не в цій org — 2@2 має свою org)
# Тому беремо свіжий email через пряму вставку в БД
conn = db(); cur = conn.cursor()
existing_id = str(uuid.uuid4())
cur.execute(
    "INSERT INTO users (id, email, password_hash, full_name, email_verified) VALUES (%s,%s,'existinghash','Existing User',TRUE)",
    (existing_id, f'_existing_{uuid.uuid4().hex[:6]}@test.local')
)
conn.commit()
existing_email = f'_existing_{existing_id[:6]}@test.local'
cur.execute("SELECT email FROM users WHERE id=%s", (existing_id,))
existing_email = cur.fetchone()['email']
conn.close()

r = post('/org/members/invite', json={'email': existing_email, 'role': 'manager'})
check('Invite існуючого юзера → 200',    r.status_code == 200, f'status={r.status_code}')
check('  existing_user=True',            r.ok and r.json().get('existing_user') is True)

conn = db(); cur = conn.cursor()
cur.execute("SELECT role FROM org_members WHERE user_id=%s AND left_at IS NULL", (existing_id,))
em = cur.fetchone()
check('  доданий в org_members',   em is not None)
check('  role = manager',          em and em['role'] == 'manager')

# Cleanup
cur.execute("DELETE FROM org_members WHERE user_id=%s", (existing_id,))
cur.execute("DELETE FROM users WHERE id=%s", (existing_id,))
conn.commit()
conn.close()


# ══════════════════════════════════════════
print('\n── Cleanup — видалення тестового юзера ──')
# ══════════════════════════════════════════

conn = db(); cur = conn.cursor()
cur.execute("DELETE FROM email_verifications WHERE user_id=%s", (invited_user_id,))
cur.execute("DELETE FROM org_member_companies WHERE user_id=%s", (invited_user_id,))
cur.execute("DELETE FROM org_members WHERE user_id=%s", (invited_user_id,))
cur.execute("DELETE FROM users WHERE id=%s", (invited_user_id,))
conn.commit()
conn.close()
check('Тестовий юзер прибраний з БД', True)


# ── Summary ──
print()
total  = len(results)
passed = sum(1 for r in results if r[0] == OK)
failed = total - passed
print(f'Результат: {passed}/{total} пройшло' + (f', {failed} провалилось' if failed else ' — все OK ✅'))
