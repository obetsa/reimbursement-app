# -*- coding: utf-8 -*-
"""Generate sample companies/instruments/records for the org owned by EMAIL."""
import os, uuid, random
from datetime import datetime, timedelta
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

EMAIL = 'obetsa@gmail.com'

cur.execute("SELECT id FROM users WHERE email=%s", (EMAIL,))
user = cur.fetchone()
if not user:
    raise SystemExit(f'User {EMAIL} not found')
USER_ID = user['id']

cur.execute("SELECT org_id FROM org_members WHERE user_id=%s LIMIT 1", (USER_ID,))
member = cur.fetchone()
if not member:
    raise SystemExit(f'No org membership found for {EMAIL}')
ORG_ID = member['org_id']

companies = [
    'Siemens AG', 'Deutsche Bahn', 'Lufthansa', 'Bosch GmbH',
    'SAP SE', 'Allianz Group', 'BMW Group', 'Volkswagen AG',
]

instruments = [
    ('Visa Corporate *4521', 'company_card'),
    ('Mastercard Business *9834', 'company_card'),
    ('Diners Club *0012', 'company_card'),
    ('Cash EUR', 'cash'),
    ('Personal Visa *7701', 'private_card'),
]

titles = [
    'Flight ticket to {city}', 'Hotel {city} ({n} nights)', 'Taxi to airport',
    'Business lunch with client', 'Car rental {city}', 'Train ticket',
    'Conference {conf}', 'Software license', 'Office supplies',
    'Mobile roaming charges', 'Airport parking', 'Representation expenses',
    'Technical maintenance', 'Document translation', 'Corporate training {conf}',
    'Internet services', 'Courier delivery', 'Subscription to {conf}',
    'Consumables', 'Hotel overnight {city}',
]
cities = ['Berlin', 'Munich', 'Vienna', 'Warsaw', 'London', 'Paris', 'Prague', 'Zurich']
confs  = ['AWS Summit', 'SAP TechEd', 'Google Cloud Next', 'KubeCon', 'DevOpsDays']
statuses = ['waiting', 'waiting', 'waiting', 'partial', 'done', 'done', 'no-return']
notes = [
    'Receipt attached', 'Waiting for accounting confirmation',
    'Paid with personal card', '', '', '',
    'Original receipt required', 'Approved by manager',
]

# Companies
comp_ids = []
cur.execute("SELECT id, name FROM companies WHERE org_id=%s", (ORG_ID,))
existing = {r['name']: r['id'] for r in cur.fetchall()}
for i, name in enumerate(companies):
    if name in existing:
        cid = existing[name]
    else:
        cid = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO companies (id, user_id, org_id, name, is_shared, sort_order) VALUES (%s,%s,%s,%s,0,%s)",
            (cid, USER_ID, ORG_ID, name, i)
        )
    comp_ids.append(cid)
print(f'Companies: {len(comp_ids)}')

# Payment instruments
inst_ids = []
inst_types = {}
cur.execute("SELECT id, name, type FROM payment_instruments WHERE org_id=%s", (ORG_ID,))
existing_inst = {r['name']: (r['id'], r['type']) for r in cur.fetchall()}
for i, (name, itype) in enumerate(instruments):
    if name in existing_inst:
        iid, itype = existing_inst[name]
    else:
        iid = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO payment_instruments (id, user_id, org_id, name, type, is_active, sort_order) VALUES (%s,%s,%s,%s,%s,1,%s)",
            (iid, USER_ID, ORG_ID, name, itype, i)
        )
    inst_ids.append(iid)
    inst_types[iid] = itype
print(f'Instruments: {len(inst_ids)}')

# Records
base_date = datetime(2025, 1, 1)
count = 0
for _ in range(60):
    rid = str(uuid.uuid4())
    days_offset = random.randint(0, 500)
    rec_date = (base_date + timedelta(days=days_offset)).strftime('%Y-%m-%d')

    tmpl = random.choice(titles)
    title = tmpl.format(city=random.choice(cities), conf=random.choice(confs), n=random.randint(1, 5))

    amount = round(random.uniform(12, 2400), 2)
    pay_type = random.choice(['private', 'private', 'company'])
    inst = random.choice(inst_ids)
    pay_method = 'cash' if inst_types[inst] == 'cash' else 'card'
    comp = random.choice(comp_ids)
    status = random.choice(statuses)

    if status == 'done':
        returned = amount
        to_return = amount
        remainder = 0.0
    elif status == 'partial':
        returned = round(random.uniform(amount * 0.1, amount * 0.8), 2)
        to_return = amount
        remainder = round(amount - returned, 2)
    elif status == 'no-return':
        returned, to_return, remainder = 0.0, 0.0, 0.0
    else:
        returned = 0.0
        to_return = amount if pay_type == 'private' else 0.0
        remainder = to_return

    is_archived = 1 if random.random() < 0.12 else 0
    note = random.choice(notes)

    cur.execute('''
        INSERT INTO records
        (id, user_id, org_id, title, note, date, amount, currency, pay_type, pay_method,
         card_id, company_id, status, to_return, returned, remainder, is_archived, is_deleted)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0)
    ''', (rid, USER_ID, ORG_ID, title, note, rec_date, amount, 'EUR',
          pay_type, pay_method, inst, comp,
          status, to_return, returned, remainder, is_archived))

    if status in ('done', 'partial') and returned > 0:
        cur.execute(
            "INSERT INTO return_events (id, record_id, amount, date, method) VALUES (%s,%s,%s,%s,%s)",
            (str(uuid.uuid4()), rid, returned,
             (base_date + timedelta(days=days_offset + random.randint(5, 60))).strftime('%Y-%m-%d'),
             'bank_transfer')
        )
    count += 1

conn.commit()
cur.close()
conn.close()
print(f'Records inserted: {count}')
print('Done!')
