"""
Hierarchy tests — org isolation, roles, join flow.
Usage: python test_hierarchy.py <session_cookie>
"""
import requests, sys, uuid

BASE    = 'http://localhost:5500'
session = requests.Session()

if len(sys.argv) > 1:
    session.headers.update({'Cookie': f'session={sys.argv[1]}'})
else:
    print('Usage: python test_hierarchy.py <session_cookie>')
    sys.exit(1)

OK   = '✅'
FAIL = '❌'
results = []

def check(name, condition, detail=''):
    mark = OK if condition else FAIL
    results.append((mark, name, detail))
    print(f'{mark}  {name}' + (f'  — {detail}' if detail else ''))

def get(path):   return session.get(BASE + path)
def post(path, **kw): return session.post(BASE + path, **kw)
def put(path, **kw):  return session.put(BASE + path, **kw)
def delete(path): return requests.delete(BASE + path, headers=dict(session.headers))

print('── Org структура ──')

# 1. Поточний юзер має org
r = get('/org/me')
check('GET /org/me — є організація', r.status_code == 200, f'status={r.status_code}')
org = r.json() if r.status_code == 200 else {}
check('  org має name', bool(org.get('name')))
check('  org має invite_code', bool(org.get('invite_code')))
check('  org має role', org.get('role') in ('admin', 'user', 'viewer'), f"role={org.get('role')}")

# 2. Члени (тільки admin)
if org.get('role') == 'admin':
    r = get('/org/members')
    check('GET /org/members (admin)', r.status_code == 200, f'status={r.status_code}')
    members = r.json() if r.status_code == 200 else []
    check('  є хоча б 1 член', len(members) >= 1, f'count={len(members)}')
    me_in_list = any(m['role'] == 'admin' for m in members)
    check('  admin є в списку', me_in_list)
else:
    r = get('/org/members')
    check('GET /org/members (non-admin) → 403', r.status_code == 403, f'status={r.status_code}')

print('\n── Ізоляція даних ──')

# 3. Записи належать org
r = get('/records')
check('GET /records — OK', r.status_code == 200)
records = r.json() if r.status_code == 200 else []
if records:
    check('  записи мають org_id', all(rec.get('org_id') for rec in records),
          f'{sum(1 for r in records if r.get("org_id"))}/{len(records)} з org_id')

# 4. Створити запис → перевірити що він в правильній org
r = post('/records', json={
    'title': '_hierarchy_test_',
    'date': '2026-05-17',
    'amount': 1.0,
    'currency': 'EUR',
    'pay_type': 'personal',
    'pay_method': 'cash',
})
check('POST /records — створити тестовий запис', r.status_code in (200, 201))
new_id  = r.json().get('id') if r.status_code in (200, 201) else None
new_org = r.json().get('org_id') if r.status_code in (200, 201) else None
check('  новий запис має org_id', bool(new_org), f'org_id={new_org}')
check('  org_id збігається з поточною org', new_org == org.get('id'), f'{new_org} == {org.get("id")}')

# 5. Компанії належать org
r = get('/companies')
check('GET /companies — OK', r.status_code == 200)
companies = r.json() if r.status_code == 200 else []
if companies:
    check('  компанії мають org_id', all(c.get('org_id') for c in companies))

# 6. Інструменти належать org
r = get('/instruments')
check('GET /instruments — OK', r.status_code == 200)
instruments = r.json() if r.status_code == 200 else []
if instruments:
    check('  інструменти мають org_id', all(i.get('org_id') for i in instruments))

print('\n── Join flow ──')

# 7. Join з невірним токеном → 401
r = post('/org/join', json={'org_name': 'nonexistent', 'token': 'wrongtoken123'})
check('POST /org/join з невірним токеном → 401', r.status_code == 401, f'status={r.status_code}')

# 8. Join без даних → 400
r = post('/org/join', json={})
check('POST /org/join без даних → 400', r.status_code == 400, f'status={r.status_code}')

# 9. Генерація токену (тільки admin)
if org.get('role') == 'admin':
    r = post('/org/invite/generate')
    check('POST /org/invite/generate (admin)', r.status_code == 200, f'status={r.status_code}')
    token_data = r.json() if r.status_code == 200 else {}
    check('  токен згенеровано', bool(token_data.get('token')))
    check('  є expires_at', bool(token_data.get('expires_at')))

    r = get('/org/invite/current')
    check('GET /org/invite/current', r.status_code == 200)
    check('  токен активний', bool((r.json() if r.status_code == 200 else {}).get('token')))

print('\n── Cleanup ──')

# Видалити тестовий запис
if new_id:
    r = post(f'/records/{new_id}/delete')
    check('Видалити тестовий запис', r.status_code == 200)

# ── Summary ──
print()
total  = len(results)
passed = sum(1 for r in results if r[0] == OK)
failed = total - passed
print(f'Результат: {passed}/{total} пройшло' + (f', {failed} провалилось' if failed else ' — все OK ✅'))
