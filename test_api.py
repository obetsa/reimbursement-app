"""
Basic API smoke tests — run while the server is running on localhost:5500.
Usage: python test_api.py <session_cookie>

Як отримати session cookie:
  1. Відкрий браузер → F12 → Application → Cookies → localhost:5500
  2. Знайди cookie з назвою 'session'
  3. Скопіюй значення і передай як аргумент:
     python test_api.py <значення>
"""
import requests
import sys

BASE = 'http://localhost:5500'
session = requests.Session()

# Auth via session cookie from browser
if len(sys.argv) > 1:
    session.headers.update({'Cookie': f'session={sys.argv[1]}'})
    print(f'🔑 Використовую session cookie\n')
else:
    print('⚠️  Session cookie не передано — автентифіковані тести будуть 401')
    print('   Запуск: python test_api.py <session_cookie>\n')

OK   = '✅'
FAIL = '❌'
results = []

def check(name, condition, detail=''):
    mark = OK if condition else FAIL
    results.append((mark, name, detail))
    print(f'{mark}  {name}' + (f'  — {detail}' if detail else ''))

def get(path):
    return session.get(BASE + path)

def post(path, **kw):
    return session.post(BASE + path, **kw)

# ── 1. Server ──
try:
    r = get('/auth/me')
    check('Сервер відповідає', r.status_code in (200, 401))
except Exception as e:
    check('Сервер відповідає', False, str(e))
    print('\nСервер не відповідає. Запусти python api.py')
    sys.exit(1)

# ── 2. Auth ──
r = get('/auth/me')
check('GET /auth/me → JSON', r.headers.get('content-type','').startswith('application/json'))
authed = r.status_code == 200
check('Авторизований', authed, 'передай session cookie якщо ні')

# ── 3. Companies ──
r = get('/companies')
check('GET /companies', r.status_code == 200, f'status={r.status_code}')
if r.status_code == 200:
    check('  повертає список', isinstance(r.json(), list), f'count={len(r.json())}')

# ── 4. Instruments ──
r = get('/instruments')
check('GET /instruments', r.status_code == 200, f'status={r.status_code}')
if r.status_code == 200:
    check('  повертає список', isinstance(r.json(), list), f'count={len(r.json())}')

# ── 5. Records ──
r = get('/records')
check('GET /records', r.status_code == 200, f'status={r.status_code}')
if r.status_code == 200:
    records = r.json()
    check('  повертає список', isinstance(records, list), f'count={len(records)}')

# ── 6. Create record ──
r = post('/records', json={
    'title': '_test_record_',
    'date': '2026-05-16',
    'amount': 1.11,
    'currency': 'EUR',
    'pay_type': 'personal',
    'pay_method': 'cash',
})
check('POST /records (створити)', r.status_code in (200, 201), f'status={r.status_code}')
new_id = r.json().get('id') if r.status_code == 200 else None
if new_id:
    check('  повертає id', bool(new_id))

# ── 7. Soft delete test record ──
if new_id:
    r = post(f'/records/{new_id}/delete')
    check('POST /records/<id>/delete', r.status_code == 200, f'status={r.status_code}')

# ── 8. Gallery ──
r = get('/gallery')
check('GET /gallery', r.status_code == 200, f'status={r.status_code}')

# ── 9. Profile ──
r = get('/profile')
check('GET /profile', r.status_code == 200, f'status={r.status_code}')
if r.status_code == 200:
    d = r.json()
    check('  є email', bool(d.get('email')), d.get('email','—'))

# ── 10. Storage info ──
r = get('/storage-info')
check('GET /storage-info', r.status_code == 200, f'status={r.status_code}')

# ── 11. Records stats ──
r = get('/records-stats')
check('GET /records-stats', r.status_code == 200, f'status={r.status_code}')
if r.status_code == 200:
    d = r.json()
    check('  records.total > 0', d.get('records',{}).get('total',0) > 0,
          f"total={d.get('records',{}).get('total')}")

# ── Summary ──
print()
total = len(results)
passed = sum(1 for r in results if r[0] == OK)
failed = total - passed
print(f'Результат: {passed}/{total} пройшло' + (f', {failed} провалилось' if failed else ' — все OK ✅'))
