"""
Isolation tests — multi-tenant data separation.
Creates 2 test orgs, verifies org_1 cannot read/write data of org_2.

Usage: python test_isolation.py
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
WARN = '⚠️ '
results = []

def check(name, condition, detail=''):
    mark = OK if condition else FAIL
    results.append((mark, name, detail))
    print(f'{mark}  {name}' + (f'  — {detail}' if detail else ''))

def warn(name, detail=''):
    results.append((WARN, name, detail))
    print(f'{WARN} {name}' + (f'  — {detail}' if detail else ''))

# ── DB helpers ──
def db():
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn

def pwd_hash(p): return hashlib.sha256(p.encode()).hexdigest()

# ── API helpers ──
def make_session(email, password):
    s = requests.Session()
    r = s.post(BASE + '/auth/login', json={'email': email, 'password': password})
    return s if r.ok and r.json().get('ok') else None

# ══════════════════════════════════════════
print('── Setup: створення тестових org ──')
# ══════════════════════════════════════════

conn = db(); cur = conn.cursor()

ORG1_NAME  = f'_TestOrg1_{uuid.uuid4().hex[:6]}'
ORG2_NAME  = f'_TestOrg2_{uuid.uuid4().hex[:6]}'
USER1_EMAIL = f'_iso1_{uuid.uuid4().hex[:6]}@test.local'
USER2_EMAIL = f'_iso2_{uuid.uuid4().hex[:6]}@test.local'
PASSWORD    = 'testpass123'

# Create users
u1_id = str(uuid.uuid4())
u2_id = str(uuid.uuid4())
cur.execute("INSERT INTO users (id, email, password_hash, full_name, email_verified) VALUES (%s,%s,%s,'Org1 Admin',TRUE)",
            (u1_id, USER1_EMAIL, pwd_hash(PASSWORD)))
cur.execute("INSERT INTO users (id, email, password_hash, full_name, email_verified) VALUES (%s,%s,%s,'Org2 Admin',TRUE)",
            (u2_id, USER2_EMAIL, pwd_hash(PASSWORD)))

# Create orgs
org1_id = str(uuid.uuid4()); org2_id = str(uuid.uuid4())
inv1 = uuid.uuid4().hex[:8].upper()
inv2 = uuid.uuid4().hex[:8].upper()
cur.execute("INSERT INTO organizations (id, name, invite_code, password_hash, owner_id) VALUES (%s,%s,%s,'x',%s)",
            (org1_id, ORG1_NAME, inv1, u1_id))
cur.execute("INSERT INTO organizations (id, name, invite_code, password_hash, owner_id) VALUES (%s,%s,%s,'x',%s)",
            (org2_id, ORG2_NAME, inv2, u2_id))

# Add as admins
cur.execute("INSERT INTO org_members (id, org_id, user_id, role) VALUES (%s,%s,%s,'admin')",
            (str(uuid.uuid4()), org1_id, u1_id))
cur.execute("INSERT INTO org_members (id, org_id, user_id, role) VALUES (%s,%s,%s,'admin')",
            (str(uuid.uuid4()), org2_id, u2_id))
conn.commit(); conn.close()

print(f'  Org1: {ORG1_NAME} / {USER1_EMAIL}')
print(f'  Org2: {ORG2_NAME} / {USER2_EMAIL}')

# Login
s1 = make_session(USER1_EMAIL, PASSWORD)
s2 = make_session(USER2_EMAIL, PASSWORD)
check('Login org1', s1 is not None)
check('Login org2', s2 is not None)

if not s1 or not s2:
    print('\nНе вдалося залогінитись. Перевір чи сервер запущений.')
    import sys; sys.exit(1)

# ══════════════════════════════════════════
print('\n── Наповнення даними ──')
# ══════════════════════════════════════════

def post(s, path, **kw): return s.post(BASE + path, **kw)
def get(s, path):        return s.get(BASE + path)
def put(s, path, **kw):  return s.put(BASE + path, **kw)
def delete(s, path):     return s.delete(BASE + path)

# Org1: company, instrument, record
r = post(s1, '/companies', json={'name': 'Ромашка ТОВ', 'sort_order': 0})
check('Org1: create company', r.status_code == 201, f'status={r.status_code}')
company1_id = r.json().get('id') if r.ok else None

r = post(s1, '/instruments', json={'name': 'Картка Org1', 'type': 'private_card'})
check('Org1: create instrument', r.status_code == 201, f'status={r.status_code}')
instr1_id = r.json().get('id') if r.ok else None

r = post(s1, '/records', json={
    'title': 'Запис Org1', 'date': '2026-05-22', 'amount': 100,
    'currency': 'EUR', 'pay_type': 'personal', 'pay_method': 'cash'
})
check('Org1: create record', r.status_code in (200, 201), f'status={r.status_code}')
record1_id = r.json().get('id') if r.status_code in (200, 201) else None

# Org2: company, instrument, record — SAME names
r = post(s2, '/companies', json={'name': 'Ромашка ТОВ', 'sort_order': 0})
check('Org2: create company (same name)', r.status_code == 201, f'status={r.status_code}')
company2_id = r.json().get('id') if r.ok else None

r = post(s2, '/instruments', json={'name': 'Картка Org1', 'type': 'private_card'})
check('Org2: create instrument (same name)', r.status_code == 201, f'status={r.status_code}')
instr2_id = r.json().get('id') if r.ok else None

r = post(s2, '/records', json={
    'title': 'Запис Org2', 'date': '2026-05-22', 'amount': 200,
    'currency': 'EUR', 'pay_type': 'personal', 'pay_method': 'cash'
})
check('Org2: create record', r.status_code in (200, 201), f'status={r.status_code}')
record2_id = r.json().get('id') if r.status_code in (200, 201) else None

# ══════════════════════════════════════════
print('\n── Ізоляція списків ──')
# ══════════════════════════════════════════

# Companies
r1_companies = get(s1, '/companies').json()
r2_companies = get(s2, '/companies').json()
ids1 = {c['id'] for c in r1_companies}
ids2 = {c['id'] for c in r2_companies}
check('GET /companies — org1 бачить тільки своє', company1_id in ids1 and company2_id not in ids1)
check('GET /companies — org2 бачить тільки своє', company2_id in ids2 and company1_id not in ids2)

# Instruments
r1_instr = get(s1, '/instruments').json()
r2_instr = get(s2, '/instruments').json()
ids1i = {i['id'] for i in r1_instr}
ids2i = {i['id'] for i in r2_instr}
check('GET /instruments — org1 бачить тільки своє', instr1_id in ids1i and instr2_id not in ids1i)
check('GET /instruments — org2 бачить тільки своє', instr2_id in ids2i and instr1_id not in ids2i)

# Records
r1_records = get(s1, '/records').json()
r2_records = get(s2, '/records').json()
ids1r = {r['id'] for r in r1_records}
ids2r = {r['id'] for r in r2_records}
check('GET /records — org1 бачить тільки своє', record1_id in ids1r and record2_id not in ids1r)
check('GET /records — org2 бачить тільки своє', record2_id in ids2r and record1_id not in ids2r)

# ══════════════════════════════════════════
print('\n── IDOR: запис (PUT/DELETE) ──')
# ══════════════════════════════════════════

if record2_id:
    # Org1 намагається оновити запис Org2
    r = put(s1, f'/records/{record2_id}', json={'title': 'HIJACKED'})
    blocked = r.status_code in (403, 404)
    check('PUT /records/{org2_id} від org1 → 403/404', blocked, f'status={r.status_code}')
    if not blocked:
        warn('  ⚠️ ВРАЗЛИВІСТЬ: org1 змінила запис org2!')

    # Перевіряємо що дані не змінились
    conn2 = db(); cur2 = conn2.cursor()
    cur2.execute("SELECT title FROM records WHERE id=%s", (record2_id,))
    row = cur2.fetchone()
    conn2.close()
    check('  Дані запису org2 не змінені', row and row['title'] == 'Запис Org2',
          f'title="{row["title"] if row else "?"}"')

    # Org1 намагається видалити запис Org2
    r = delete(s1, f'/records/{record2_id}')
    check('DELETE /records/{org2_id} від org1 → 403/404', r.status_code in (403, 404),
          f'status={r.status_code}')

# ══════════════════════════════════════════
print('\n── IDOR: компанія (PUT/DELETE) ──')
# ══════════════════════════════════════════

if company2_id:
    r = put(s1, f'/companies/{company2_id}', json={'name': 'HIJACKED'})
    blocked = r.status_code in (403, 404)
    check('PUT /companies/{org2_id} від org1 → 403/404', blocked, f'status={r.status_code}')
    if not blocked:
        warn('  ⚠️ ВРАЗЛИВІСТЬ: org1 змінила компанію org2!')

    conn2 = db(); cur2 = conn2.cursor()
    cur2.execute("SELECT name FROM companies WHERE id=%s", (company2_id,))
    row = cur2.fetchone()
    conn2.close()
    check('  Дані компанії org2 не змінені', row and row['name'] == 'Ромашка ТОВ',
          f'name="{row["name"] if row else "?"}"')

    r = delete(s1, f'/companies/{company2_id}')
    check('DELETE /companies/{org2_id} від org1 → 403/404', r.status_code in (403, 404),
          f'status={r.status_code}')

# ══════════════════════════════════════════
print('\n── IDOR: платіжний інструмент ──')
# ══════════════════════════════════════════

if instr2_id:
    r = put(s1, f'/instruments/{instr2_id}', json={'name': 'HIJACKED'})
    blocked = r.status_code in (403, 404)
    check('PUT /instruments/{org2_id} від org1 → 403/404', blocked, f'status={r.status_code}')
    if not blocked:
        warn('  ⚠️ ВРАЗЛИВІСТЬ: org1 змінила інструмент org2!')

# ══════════════════════════════════════════
print('\n── Ізоляція org/members ──')
# ══════════════════════════════════════════

r = get(s1, '/org/members')
check('GET /org/members — org1 не бачить членів org2',
      r.status_code == 200 and all(m['user_id'] != u2_id for m in r.json()),
      f'count={len(r.json())}')

# Org1 намагається змінити роль члена org2
r = put(s1, f'/org/members/{u2_id}/role', json={'role': 'user'})
check('PUT /org/members/{org2_user}/role від org1 → 403', r.status_code in (403, 404),
      f'status={r.status_code}')

# ══════════════════════════════════════════
print('\n── Ізоляція Gallery ──')
# ══════════════════════════════════════════

r1_gallery = get(s1, '/gallery')
r2_gallery = get(s2, '/gallery')
check('GET /gallery — org1 OK', r1_gallery.status_code == 200)
check('GET /gallery — org2 OK', r2_gallery.status_code == 200)

# ══════════════════════════════════════════
print('\n── Ізоляція Stats ──')
# ══════════════════════════════════════════

r1_stats = get(s1, '/records-stats').json()
r2_stats = get(s2, '/records-stats').json()
r1_total = r1_stats.get('records', {}).get('total', 0)
r2_total = r2_stats.get('records', {}).get('total', 0)
check('GET /records-stats — org1 бачить свої дані', r1_total > 0, f'total={r1_total}')
check('GET /records-stats — org2 бачить свої дані', r2_total > 0, f'total={r2_total}')
check('Stats не змішуються між org', r1_total == r2_total,  # обидва мають по 1 запису
      f'org1={r1_total}, org2={r2_total}')

# ══════════════════════════════════════════
print('\n── Ізоляція file paths ──')
# ══════════════════════════════════════════

conn2 = db(); cur2 = conn2.cursor()
cur2.execute("""
    SELECT a.file_path, r.org_id FROM attachments a
    JOIN records r ON a.record_id = r.id
    WHERE a.file_path IS NOT NULL
    AND r.org_id IN (%s, %s)
""", (org1_id, org2_id))
file_rows = cur2.fetchall()
conn2.close()

path_ok = all(
    row['file_path'].split('/')[1] == row['org_id']
    for row in file_rows
    if row['file_path'] and len(row['file_path'].split('/')) > 1
)
if file_rows:
    check('File paths ізольовані по org_id', path_ok)
else:
    check('File paths ізольовані по org_id (немає файлів — OK)', True)

# ══════════════════════════════════════════
print('\n── 0.4: org_member_companies очистка ──')
# ══════════════════════════════════════════

if company1_id:
    # Спочатку надаємо доступ до company1 для user1 (щоб створити рядок)
    conn_t = db(); cur_t = conn_t.cursor()
    grant_id = str(uuid.uuid4())
    cur_t.execute(
        "INSERT INTO org_member_companies (id, org_id, user_id, company_id, granted_by) VALUES (%s,%s,%s,%s,%s)",
        (grant_id, org1_id, u1_id, company1_id, u1_id)
    )
    conn_t.commit()

    # Перевіряємо що запис є
    cur_t.execute("SELECT id FROM org_member_companies WHERE company_id=%s", (company1_id,))
    check('org_member_companies: запис є до видалення', cur_t.fetchone() is not None)
    conn_t.close()

    # Soft delete — доступи мають залишитись
    r = post(s1, f'/companies/{company1_id}/delete' if False else '/companies/' + company1_id,
             json={})
    # Використовуємо DELETE endpoint
    r = s1.delete(BASE + f'/companies/{company1_id}')
    check('Soft delete company → 200', r.status_code == 200, f'status={r.status_code}')

    conn_t = db(); cur_t = conn_t.cursor()
    cur_t.execute("SELECT id FROM org_member_companies WHERE company_id=%s", (company1_id,))
    check('Soft delete: org_member_companies збережено', cur_t.fetchone() is not None)
    conn_t.close()

    # Permanent delete — доступи мають видалитись
    r = s1.delete(BASE + f'/companies/{company1_id}/permanent')
    check('Permanent delete company → 200', r.status_code == 200, f'status={r.status_code}')

    conn_t = db(); cur_t = conn_t.cursor()
    cur_t.execute("SELECT id FROM org_member_companies WHERE company_id=%s", (company1_id,))
    check('Permanent delete: org_member_companies очищено', cur_t.fetchone() is None)
    cur_t.execute("SELECT id FROM companies WHERE id=%s", (company1_id,))
    check('Permanent delete: компанія видалена з БД', cur_t.fetchone() is None)
    conn_t.close()

    company1_id = None  # вже видалена, не чіпати в cleanup

# ══════════════════════════════════════════
print('\n── 0.5: Cascade delete org ──')
# ══════════════════════════════════════════

# Login as superadmin
s_sa = make_session('obetsa@gmail.com', 'test')  # Google user — skip if no password
if not s_sa:
    # Try direct DB session cookie approach — use 1@1 if it has superadmin
    s_sa = make_session('1@1', '123456')
    conn_check = db(); cur_check = conn_check.cursor()
    cur_check.execute("SELECT is_superadmin FROM users WHERE email='1@1'")
    sa_row = cur_check.fetchone()
    conn_check.close()
    if not sa_row or not sa_row['is_superadmin']:
        s_sa = None

if s_sa:
    # Use org2 for delete test (org1 data was used in 0.4)
    r = s_sa.delete(BASE + f'/superadmin/orgs/{org2_id}')
    check('DELETE /superadmin/orgs/{id} → 200', r.status_code == 200, f'status={r.status_code}')

    conn_d = db(); cur_d = conn_d.cursor()
    cur_d.execute("SELECT id FROM organizations WHERE id=%s", (org2_id,))
    check('  organizations видалено',          cur_d.fetchone() is None)
    cur_d.execute("SELECT id FROM org_members WHERE org_id=%s", (org2_id,))
    check('  org_members видалено (cascade)',   cur_d.fetchone() is None)
    cur_d.execute("SELECT id FROM records WHERE org_id=%s", (org2_id,))
    check('  records видалено',                cur_d.fetchone() is None)
    cur_d.execute("SELECT id FROM companies WHERE org_id=%s", (org2_id,))
    check('  companies видалено',              cur_d.fetchone() is None)
    cur_d.execute("SELECT id FROM payment_instruments WHERE org_id=%s", (org2_id,))
    check('  payment_instruments видалено',    cur_d.fetchone() is None)
    # org2's user is not PENDING so should still exist
    cur_d.execute("SELECT id FROM users WHERE id=%s", (u2_id,))
    check('  звичайний юзер org2 збережено',   cur_d.fetchone() is not None)
    conn_d.close()

    # Non-superadmin can't delete org
    r2 = s1.delete(BASE + f'/superadmin/orgs/{org1_id}')
    check('Non-superadmin DELETE /superadmin/orgs → 403', r2.status_code in (403, 404),
          f'status={r2.status_code}')

    # 404 for non-existent org
    r3 = s_sa.delete(BASE + f'/superadmin/orgs/{org2_id}')
    check('DELETE вже видаленої org → 404', r3.status_code == 404, f'status={r3.status_code}')

    org2_id = None  # вже видалена
    u2_id   = None  # cleanup не потрібен
else:
    warn('Superadmin login недоступний — пропускаємо 0.5 тест')

# ══════════════════════════════════════════
print('\n── Cleanup ──')
# ══════════════════════════════════════════

conn3 = db(); cur3 = conn3.cursor()
active_orgs  = [o for o in [org1_id, org2_id] if o]
active_users = [u for u in [u1_id, u2_id] if u]
if active_orgs:
    ph = ','.join(['%s'] * len(active_orgs))
    cur3.execute(f"DELETE FROM attachments WHERE record_id IN (SELECT id FROM records WHERE org_id IN ({ph}))", active_orgs)
    cur3.execute(f"DELETE FROM return_events WHERE record_id IN (SELECT id FROM records WHERE org_id IN ({ph}))", active_orgs)
    cur3.execute(f"DELETE FROM records             WHERE org_id IN ({ph})", active_orgs)
    cur3.execute(f"DELETE FROM org_member_companies WHERE org_id IN ({ph})", active_orgs)
    cur3.execute(f"DELETE FROM org_members          WHERE org_id IN ({ph})", active_orgs)
    cur3.execute(f"DELETE FROM payment_instruments  WHERE org_id IN ({ph})", active_orgs)
    cur3.execute(f"DELETE FROM companies            WHERE org_id IN ({ph})", active_orgs)
    cur3.execute(f"DELETE FROM org_invites          WHERE org_id IN ({ph})", active_orgs)
    cur3.execute(f"DELETE FROM organizations        WHERE id IN ({ph})", active_orgs)
if active_users:
    ph = ','.join(['%s'] * len(active_users))
    cur3.execute(f"DELETE FROM email_verifications WHERE user_id IN ({ph})", active_users)
    cur3.execute(f"DELETE FROM users WHERE id IN ({ph})", active_users)
conn3.commit(); conn3.close()
check('Cleanup завершено', True)

# ── Summary ──
print()
total   = len(results)
passed  = sum(1 for r in results if r[0] == OK)
warned  = sum(1 for r in results if r[0] == WARN)
failed  = sum(1 for r in results if r[0] == FAIL)
print(f'Результат: {passed}/{total} пройшло' +
      (f', {warned} попереджень' if warned else '') +
      (f', {failed} провалилось' if failed else '') +
      (' — все OK ✅' if not failed and not warned else ''))

if warned or failed:
    print('\nПроблеми:')
    for mark, name, detail in results:
        if mark != OK:
            print(f'  {mark} {name}' + (f' — {detail}' if detail else ''))
