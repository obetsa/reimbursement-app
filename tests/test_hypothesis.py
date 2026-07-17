"""
Property-based tests using Hypothesis.
Перевіряє що ключові властивості безпеки виконуються для будь-яких вхідних даних.

Властивості:
  1. Role restrictions — 'user' роль завжди отримує 403 на write-операції
  2. Org isolation   — довільні UUID ніколи не дають доступ до чужої org
  3. Input robustness — сервер ніколи не повертає 500 на довільні входи

Usage: pytest tests/test_hypothesis.py -v
Requires: server running on localhost:5500, DATABASE_URL in .env
"""
import pytest
import requests
import uuid
import hashlib
import psycopg2
import psycopg2.extras
import os
import datetime
from dotenv import load_dotenv
from hypothesis import given, settings, assume
from hypothesis import strategies as st

load_dotenv()
BASE = 'http://localhost:5500'

def pwd_hash(p): return hashlib.sha256(p.encode()).hexdigest()

def db_conn():
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    conn.cursor_factory = psycopg2.extras.RealDictCursor
    return conn

def login(email, password):
    s = requests.Session()
    r = s.post(f'{BASE}/auth/login', json={'email': email, 'password': password})
    return s if r.ok and r.json().get('ok') else None


# ── Fixture: один раз на весь модуль ────────────────────────────────────────

@pytest.fixture(scope='module')
def ctx():
    """Створює тестові org/users. Прибирає після всіх тестів."""
    conn = db_conn(); cur = conn.cursor()
    suffix = uuid.uuid4().hex[:6]
    password = 'hyptest123'

    admin_email   = f'_hyp_admin_{suffix}@test.local'
    user_email    = f'_hyp_user_{suffix}@test.local'
    manager_email = f'_hyp_manager_{suffix}@test.local'
    org2_email    = f'_hyp_org2_{suffix}@test.local'

    admin_id   = str(uuid.uuid4())
    user_id    = str(uuid.uuid4())
    manager_id = str(uuid.uuid4())
    org2_id_u  = str(uuid.uuid4())
    org_id     = str(uuid.uuid4())
    org2_id    = str(uuid.uuid4())

    for uid, email in [(admin_id, admin_email), (user_id, user_email),
                        (manager_id, manager_email), (org2_id_u, org2_email)]:
        cur.execute(
            "INSERT INTO users (id, email, password_hash, full_name, email_verified) "
            "VALUES (%s,%s,%s,'Hyp Test',TRUE)",
            (uid, email, pwd_hash(password))
        )

    for oid, name, owner in [
        (org_id,  f'_HypOrg_{suffix}',  admin_id),
        (org2_id, f'_HypOrg2_{suffix}', org2_id_u),
    ]:
        cur.execute(
            "INSERT INTO organizations (id, name, invite_code, password_hash, owner_id) "
            "VALUES (%s,%s,%s,'x',%s)",
            (oid, name, uuid.uuid4().hex[:8].upper(), owner)
        )

    cur.execute("INSERT INTO org_members (id, org_id, user_id, role) VALUES (%s,%s,%s,'admin')",
                (str(uuid.uuid4()), org_id, admin_id))
    cur.execute("INSERT INTO org_members (id, org_id, user_id, role) VALUES (%s,%s,%s,'user')",
                (str(uuid.uuid4()), org_id, user_id))
    # manager БЕЗ доступу до жодної компанії (org_member_companies порожній) — для IDOR-тестів
    cur.execute("INSERT INTO org_members (id, org_id, user_id, role) VALUES (%s,%s,%s,'manager')",
                (str(uuid.uuid4()), org_id, manager_id))
    cur.execute("INSERT INTO org_members (id, org_id, user_id, role) VALUES (%s,%s,%s,'admin')",
                (str(uuid.uuid4()), org2_id, org2_id_u))
    conn.commit(); conn.close()

    admin_s   = login(admin_email, password)
    user_s    = login(user_email, password)
    manager_s = login(manager_email, password)
    org2_s    = login(org2_email, password)

    assert admin_s and user_s and manager_s and org2_s, 'Не вдалось залогінитись — сервер запущений?'

    # Запис в org1 для тестів ізоляції
    r = admin_s.post(f'{BASE}/records', json={
        'title': 'Hyp Org1 Record', 'date': '2026-01-01',
        'amount': 99, 'currency': 'EUR', 'pay_type': 'personal', 'pay_method': 'cash',
    })
    org1_record_id = r.json().get('id') if r.status_code in (200, 201) else None

    # Компанія в org1 (admin-створена, manager до неї доступу НЕ має) — для company_expenses і IDOR-тестів корзини
    r = admin_s.post(f'{BASE}/companies', json={'name': f'_HypCo_{suffix}', 'sort_order': 0})
    org1_company_id = r.json().get('id') if r.status_code in (200, 201) else None

    # Витрата по компанії в org1 — для тестів ізоляції company_expenses
    org1_cexp_id = None
    if org1_company_id:
        r = admin_s.post(f'{BASE}/company-expenses', json={
            'date': '2026-01-01', 'paying_company_id': org1_company_id,
            'amount': 50, 'note': 'Hyp cexp',
        })
        org1_cexp_id = r.json().get('id') if r.status_code in (200, 201) else None

    # Інструмент, створений admin-ом (не manager-ом) — для ownership-тесту restore
    r = admin_s.post(f'{BASE}/instruments', json={'name': f'_HypInst_{suffix}', 'type': 'private_card'})
    org1_instrument_id = r.json().get('id') if r.status_code in (200, 201) else None

    yield {
        'admin_s': admin_s,
        'user_s':  user_s,
        'manager_s': manager_s,
        'org2_s':  org2_s,
        'org_id':  org_id,
        'org1_record_id': org1_record_id,
        'org1_company_id': org1_company_id,
        'org1_cexp_id': org1_cexp_id,
        'org1_instrument_id': org1_instrument_id,
    }

    # Cleanup
    conn = db_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM org_members WHERE org_id IN (%s,%s)", (org_id, org2_id))
    cur.execute("DELETE FROM records WHERE org_id IN (%s,%s)", (org_id, org2_id))
    cur.execute("DELETE FROM company_expenses WHERE org_id IN (%s,%s)", (org_id, org2_id))
    cur.execute("DELETE FROM companies WHERE org_id IN (%s,%s)", (org_id, org2_id))
    cur.execute("DELETE FROM payment_instruments WHERE org_id IN (%s,%s)", (org_id, org2_id))
    cur.execute("DELETE FROM organizations WHERE id IN (%s,%s)", (org_id, org2_id))
    cur.execute("DELETE FROM users WHERE id IN (%s,%s,%s,%s)", (admin_id, user_id, manager_id, org2_id_u))
    conn.commit(); conn.close()


# ── Стратегії ───────────────────────────────────────────────────────────────

safe_text = st.text(
    min_size=1, max_size=200,
    alphabet=st.characters(blacklist_categories=['Cs'], blacklist_characters=['\x00'])
)

any_title = st.one_of(
    safe_text,
    st.just(''),
    st.just('<script>alert(1)</script>'),
    st.just("'; DROP TABLE records; --"),
    st.just('A' * 5000),
)

valid_amount = st.floats(min_value=0.01, max_value=999999.99, allow_nan=False, allow_infinity=False)

any_amount = st.one_of(
    valid_amount,
    st.just(-1.0),
    st.just(0.0),
    st.just(None),
)

random_uuid = st.uuids().map(str)


# ── 1. Role restrictions ─────────────────────────────────────────────────────

class TestRoleRestrictions:
    """Роль 'user' завжди отримує 403 на будь-які write-операції."""

    @given(title=safe_text, amount=valid_amount)
    @settings(max_examples=25, deadline=8000)
    def test_user_cannot_create_record(self, ctx, title, amount):
        r = ctx['user_s'].post(f'{BASE}/records', json={
            'title': title, 'date': '2026-01-01',
            'amount': round(amount, 2), 'currency': 'EUR',
            'pay_type': 'personal', 'pay_method': 'cash',
        })
        assert r.status_code == 403, \
            f"user роль створила запис! title={title[:50]!r}, status={r.status_code}"

    @given(name=safe_text)
    @settings(max_examples=20, deadline=8000)
    def test_user_cannot_create_company(self, ctx, name):
        r = ctx['user_s'].post(f'{BASE}/companies', json={'name': name, 'sort_order': 0})
        assert r.status_code == 403, \
            f"user роль створила компанію! name={name[:50]!r}, status={r.status_code}"

    @given(name=safe_text)
    @settings(max_examples=20, deadline=8000)
    def test_user_cannot_create_instrument(self, ctx, name):
        r = ctx['user_s'].post(f'{BASE}/instruments', json={'name': name, 'type': 'private_card'})
        assert r.status_code == 403, \
            f"user роль створила інструмент! name={name[:50]!r}, status={r.status_code}"


# ── 2. Org isolation ─────────────────────────────────────────────────────────

class TestOrgIsolation:
    """Org2 не може отримати дані Org1 через будь-які ID."""

    @given(record_id=random_uuid)
    @settings(max_examples=30, deadline=8000)
    def test_random_uuid_never_returns_200(self, ctx, record_id):
        r = ctx['org2_s'].get(f'{BASE}/records/{record_id}')
        assert r.status_code in (403, 404, 400), \
            f"Несподіваний статус {r.status_code} для random UUID {record_id}"

    def test_org1_record_blocked_for_org2(self, ctx):
        """Конкретний запис Org1 недоступний для Org2."""
        rid = ctx['org1_record_id']
        if not rid:
            pytest.skip('Org1 record не створено')
        r = ctx['org2_s'].get(f'{BASE}/records/{rid}')
        assert r.status_code in (403, 404), \
            f"Org2 отримала доступ до запису Org1! status={r.status_code}"

    @given(record_id=random_uuid)
    @settings(max_examples=20, deadline=8000)
    def test_random_delete_never_succeeds_for_other_org(self, ctx, record_id):
        """Org2 не може видалити записи Org1 через довільні UUID."""
        r = ctx['org2_s'].delete(f'{BASE}/records/{record_id}')
        # 200 можливий тільки якщо це власний запис Org2 (малоймовірно з random UUID)
        if r.status_code == 200:
            data = r.json()
            assert data.get('org_id') != ctx['org_id'], \
                f"Org2 видалила запис Org1! id={record_id}"


# ── 3. Input robustness ──────────────────────────────────────────────────────

class TestInputRobustness:
    """Сервер ніколи не повертає 500 на довільні вхідні дані."""

    @given(title=any_title, amount=any_amount)
    @settings(max_examples=30, deadline=10000)
    def test_create_record_never_500(self, ctx, title, amount):
        r = ctx['admin_s'].post(f'{BASE}/records', json={
            'title': title, 'date': '2026-01-01',
            'amount': amount, 'currency': 'EUR',
            'pay_type': 'personal', 'pay_method': 'cash',
        })
        assert r.status_code != 500, \
            f"Server 500! title={title[:80]!r}, amount={amount}"

    @given(name=any_title)
    @settings(max_examples=20, deadline=8000)
    def test_create_company_never_500(self, ctx, name):
        r = ctx['admin_s'].post(f'{BASE}/companies', json={'name': name, 'sort_order': 0})
        assert r.status_code != 500, \
            f"Server 500 на назву компанії: {name[:80]!r}"

    @given(record_id=random_uuid)
    @settings(max_examples=20, deadline=8000)
    def test_get_record_arbitrary_id_never_500(self, ctx, record_id):
        r = ctx['admin_s'].get(f'{BASE}/records/{record_id}')
        assert r.status_code != 500, \
            f"Server 500 на GET /records/{record_id}"


# ── 4. Company expenses — role restrictions ──────────────────────────────────

class TestCompanyExpenseRoleRestrictions:
    """Роль 'user' не може писати в company_expenses (той самий інваріант, що й records)."""

    @given(amount=valid_amount, note=safe_text)
    @settings(max_examples=20, deadline=8000)
    def test_user_cannot_create_company_expense(self, ctx, amount, note):
        r = ctx['user_s'].post(f'{BASE}/company-expenses', json={
            'date': '2026-01-01', 'amount': round(amount, 2), 'note': note,
        })
        assert r.status_code == 403, \
            f"user роль створила company_expense! status={r.status_code}"

    @given(amount=valid_amount)
    @settings(max_examples=10, deadline=8000)
    def test_user_cannot_delete_company_expense(self, ctx, amount):
        exp_id = ctx['org1_cexp_id']
        if not exp_id:
            pytest.skip('org1_cexp_id не створено')
        r = ctx['user_s'].delete(f'{BASE}/company-expenses/{exp_id}')
        assert r.status_code == 403, \
            f"user роль видалила company_expense! status={r.status_code}"


# ── 5. Company expenses — org isolation ──────────────────────────────────────

class TestCompanyExpenseOrgIsolation:
    """Org2 не може читати/писати company_expenses Org1 через жодні ID."""

    @given(exp_id=random_uuid, amount=valid_amount)
    @settings(max_examples=20, deadline=8000)
    def test_random_uuid_update_never_succeeds_for_other_org(self, ctx, exp_id, amount):
        r = ctx['org2_s'].put(f'{BASE}/company-expenses/{exp_id}', json={
            'date': '2026-01-01', 'amount': round(amount, 2),
        })
        assert r.status_code in (403, 404), \
            f"Несподіваний статус {r.status_code} для random UUID {exp_id}"

    def test_org1_cexp_blocked_for_org2(self, ctx):
        """Конкретна витрата Org1 недоступна для Org2 (PUT і DELETE)."""
        exp_id = ctx['org1_cexp_id']
        if not exp_id:
            pytest.skip('org1_cexp_id не створено')
        r = ctx['org2_s'].put(f'{BASE}/company-expenses/{exp_id}', json={
            'date': '2026-01-01', 'amount': 1,
        })
        assert r.status_code in (403, 404), \
            f"Org2 отримала доступ до company_expense Org1! status={r.status_code}"
        r = ctx['org2_s'].delete(f'{BASE}/company-expenses/{exp_id}')
        assert r.status_code in (403, 404), \
            f"Org2 видалила company_expense Org1! status={r.status_code}"


# ── 6. Company expenses — input robustness ───────────────────────────────────

class TestCompanyExpenseInputRobustness:
    """Сервер ніколи не повертає 500 на довільні дані в company_expenses."""

    @given(amount=any_amount, note=any_title)
    @settings(max_examples=25, deadline=10000)
    def test_create_company_expense_never_500(self, ctx, amount, note):
        r = ctx['admin_s'].post(f'{BASE}/company-expenses', json={
            'date': '2026-01-01', 'amount': amount, 'note': note,
        })
        assert r.status_code != 500, \
            f"Server 500! amount={amount}, note={note[:80]!r}"


# ── 7. Trash/restore IDOR — regression на фікси 07.07.2026 ───────────────────

class TestTrashRestoreAccessControl:
    """
    manager БЕЗ гранту в org_member_companies не повинен мати можливість
    відновити чужу компанію/інструмент навіть знаючи ID напряму (IDOR-фікс).
    """

    def test_manager_without_access_cannot_restore_company(self, ctx):
        company_id = ctx['org1_company_id']
        if not company_id:
            pytest.skip('org1_company_id не створено')
        # trash його спершу (admin), інакше restore на активній компанії — інша поведінка
        ctx['admin_s'].delete(f'{BASE}/companies/{company_id}')
        r = ctx['manager_s'].post(f'{BASE}/companies/{company_id}/restore')
        assert r.status_code == 403, \
            f"manager без доступу відновив чужу компанію! status={r.status_code}"
        # прибрати за собою — відновити адміном назад
        ctx['admin_s'].post(f'{BASE}/companies/{company_id}/restore')

    def test_manager_cannot_restore_instrument_owned_by_someone_else(self, ctx):
        inst_id = ctx['org1_instrument_id']
        if not inst_id:
            pytest.skip('org1_instrument_id не створено')
        ctx['admin_s'].delete(f'{BASE}/instruments/{inst_id}')
        r = ctx['manager_s'].post(f'{BASE}/instruments/{inst_id}/restore')
        assert r.status_code == 403, \
            f"manager відновив чужий інструмент! status={r.status_code}"
        ctx['admin_s'].post(f'{BASE}/instruments/{inst_id}/restore')

    @given(company_id=random_uuid)
    @settings(max_examples=10, deadline=8000)
    def test_random_uuid_restore_never_500_or_succeeds(self, ctx, company_id):
        r = ctx['manager_s'].post(f'{BASE}/companies/{company_id}/restore')
        assert r.status_code in (403, 404), \
            f"Несподіваний статус {r.status_code} для random company restore {company_id}"
