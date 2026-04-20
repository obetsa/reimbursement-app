from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3
import uuid
import os
import re
from datetime import datetime

app = Flask(__name__, static_folder='.')
CORS(app)

DB_PATH = os.path.join('data', 'local.db')
UPLOAD_FOLDER = os.path.join('data', 'uploads')
DRIVE_ROOT = 'ReceiptsManager'

# ══════════════════════════════════════════
# DATABASE INIT
# ══════════════════════════════════════════
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''
        create table if not exists users (
            id text primary key,
            email text unique not null,
            password_hash text not null,
            full_name text,
            created_at text default (datetime('now'))
        )
    ''')

    c.execute('''
        create table if not exists companies (
            id text primary key,
            user_id text not null,
            name text not null,
            is_shared integer default 0,
            is_active integer default 1,
            sort_order integer default 0,
            created_at text default (datetime('now'))
        )
    ''')

    c.execute('''
        create table if not exists payment_instruments (
            id text primary key,
            user_id text not null,
            name text not null,
            type text not null,
            is_active integer default 1,
            sort_order integer default 0,
            created_at text default (datetime('now'))
        )
    ''')

    c.execute('''
        create table if not exists records (
            id text primary key,
            user_id text not null,
            title text not null,
            note text,
            date text not null,
            created_at text default (datetime('now')),
            amount real not null,
            currency text default 'EUR',
            pay_type text not null,
            pay_method text not null,
            card_id text,
            company_id text,
            status text default 'waiting',
            to_return real default 0,
            returned real default 0,
            remainder real default 0,
            is_archived integer default 0,
            is_deleted integer default 0,
            deleted_at text
        )
    ''')

    c.execute('''
        create table if not exists return_events (
            id text primary key,
            record_id text not null,
            amount real not null,
            date text not null,
            method text,
            created_at text default (datetime('now')),
            foreign key (record_id) references records(id) on delete cascade
        )
    ''')

    c.execute('''
        create table if not exists attachments (
            id text primary key,
            record_id text not null,
            file_name text not null,
            file_type text,
            file_url text,
            created_at text default (datetime('now')),
            foreign key (record_id) references records(id) on delete cascade
        )
    ''')

    # Create default admin user if not exists
    existing = c.execute("select id from users where email='admin@local.app'").fetchone()
    if not existing:
        import hashlib
        pwd_hash = hashlib.sha256('admin123'.encode()).hexdigest()
        admin_id = str(uuid.uuid4())
        c.execute("insert into users (id, email, password_hash, full_name) values (?,?,?,?)",
                  (admin_id, 'admin@local.app', pwd_hash, 'Admin'))

    # Migrate companies: add soft-delete columns if missing
    try:
        c.execute("alter table companies add column is_deleted integer default 0")
    except Exception:
        pass
    try:
        c.execute("alter table companies add column deleted_at text")
    except Exception:
        pass

    # Migrate payment_instruments: add soft-delete columns if missing
    try:
        c.execute("alter table payment_instruments add column is_deleted integer default 0")
    except Exception:
        pass
    try:
        c.execute("alter table payment_instruments add column deleted_at text")
    except Exception:
        pass

    # Migrate records: add previous_status if missing
    try:
        c.execute("alter table records add column previous_status text")
    except Exception:
        pass

    # Migrate attachments: add storage_type and file_path if missing
    try:
        c.execute("alter table attachments add column storage_type text default 'local'")
    except Exception:
        pass
    try:
        c.execute("alter table attachments add column file_path text")
    except Exception:
        pass

    conn.commit()
    conn.close()

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    print("✅ Database initialized")

# ══════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════
import hashlib
import json
import time

# Simple in-memory sessions
sessions = {}

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_user_from_token(request):
    # TODO: restore auth — remove this line and uncomment the block below
    return '6895da8f-e07e-4b06-b64b-255d50a1a32e'
    # token = request.headers.get('Authorization', '').replace('Bearer ', '')
    # if not token or token not in sessions:
    #     return None
    # session = sessions[token]
    # if session['expires'] < time.time():
    #     del sessions[token]
    #     return None
    # return session['user_id']

@app.route('/auth/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email', '').strip()
    password = data.get('password', '')

    conn = get_db()
    user = conn.execute(
        "select * from users where email=? and password_hash=?",
        (email, hash_password(password))
    ).fetchone()
    conn.close()

    if not user:
        return jsonify({'error': 'Невірний email або пароль'}), 401

    token = str(uuid.uuid4())
    sessions[token] = {
        'user_id': user['id'],
        'email': user['email'],
        'expires': time.time() + 86400 * 7  # 7 days
    }

    return jsonify({
        'token': token,
        'user': {'id': user['id'], 'email': user['email'], 'full_name': user['full_name']}
    })

@app.route('/auth/register', methods=['POST'])
def register():
    data = request.json
    email = data.get('email', '').strip()
    password = data.get('password', '')
    full_name = data.get('full_name', '')

    if not email or not password:
        return jsonify({'error': 'Email і пароль обовʼязкові'}), 400

    conn = get_db()
    existing = conn.execute("select id from users where email=?", (email,)).fetchone()
    if existing:
        conn.close()
        return jsonify({'error': 'Цей email вже зареєстровано'}), 400

    user_id = str(uuid.uuid4())
    conn.execute(
        "insert into users (id, email, password_hash, full_name) values (?,?,?,?)",
        (user_id, email, hash_password(password), full_name)
    )
    conn.commit()
    conn.close()

    token = str(uuid.uuid4())
    sessions[token] = {
        'user_id': user_id,
        'email': email,
        'expires': time.time() + 86400 * 7
    }

    return jsonify({
        'token': token,
        'user': {'id': user_id, 'email': email, 'full_name': full_name}
    })

@app.route('/auth/me', methods=['GET'])
def me():
    user_id = get_user_from_token(request)
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    user = conn.execute("select id, email, full_name from users where id=?", (user_id,)).fetchone()
    conn.close()

    if not user:
        return jsonify({'error': 'User not found'}), 404

    return jsonify({'id': user['id'], 'email': user['email'], 'full_name': user['full_name']})

# ══════════════════════════════════════════
# COMPANIES
# ══════════════════════════════════════════
@app.route('/companies', methods=['GET'])
def get_companies():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    rows = conn.execute(
        "select * from companies where user_id=? and (is_deleted=0 or is_deleted is null) order by sort_order, name",
        (user_id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/companies', methods=['POST'])
def create_company():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    company_id = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        "insert into companies (id, user_id, name, is_shared, is_active, sort_order) values (?,?,?,?,1,?)",
        (company_id, user_id, data['name'], 1 if data.get('is_shared') else 0, data.get('sort_order', 0))
    )
    conn.commit()
    row = conn.execute("select * from companies where id=?", (company_id,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201

@app.route('/companies/<company_id>', methods=['PUT'])
def update_company(company_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    conn = get_db()
    fields = []
    values = []
    for key in ['name', 'is_shared', 'is_active', 'sort_order']:
        if key in data:
            fields.append(f"{key}=?")
            values.append(1 if data[key] is True else (0 if data[key] is False else data[key]))
    values.append(company_id)
    conn.execute(f"update companies set {', '.join(fields)} where id=?", values)
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/companies/<company_id>', methods=['DELETE'])
def delete_company(company_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    conn.execute(
        "update companies set is_deleted=1, deleted_at=? where id=? and user_id=?",
        (datetime.utcnow().isoformat(), company_id, user_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/companies/trash', methods=['GET'])
def get_companies_trash():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    rows = conn.execute(
        "select * from companies where user_id=? and is_deleted=1 order by deleted_at desc",
        (user_id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/companies/<company_id>/restore', methods=['POST'])
def restore_company(company_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    conn.execute(
        "update companies set is_deleted=0, deleted_at=null where id=? and user_id=?",
        (company_id, user_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/companies/<company_id>/permanent', methods=['DELETE'])
def permanent_delete_company(company_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    conn.execute("delete from companies where id=? and user_id=?", (company_id, user_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ══════════════════════════════════════════
# PAYMENT INSTRUMENTS
# ══════════════════════════════════════════
@app.route('/instruments', methods=['GET'])
def get_instruments():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    rows = conn.execute(
        "select * from payment_instruments where user_id=? and (is_deleted=0 or is_deleted is null) order by sort_order, name",
        (user_id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/instruments', methods=['POST'])
def create_instrument():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    inst_id = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        "insert into payment_instruments (id, user_id, name, type, is_active, sort_order) values (?,?,?,?,1,?)",
        (inst_id, user_id, data['name'], data['type'], data.get('sort_order', 0))
    )
    conn.commit()
    row = conn.execute("select * from payment_instruments where id=?", (inst_id,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201

@app.route('/instruments/<inst_id>', methods=['PUT'])
def update_instrument(inst_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    conn = get_db()
    fields = []
    values = []
    for key in ['name', 'type', 'is_active', 'sort_order']:
        if key in data:
            fields.append(f"{key}=?")
            values.append(1 if data[key] is True else (0 if data[key] is False else data[key]))
    values.append(inst_id)
    conn.execute(f"update payment_instruments set {', '.join(fields)} where id=?", values)
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/instruments/<inst_id>', methods=['DELETE'])
def delete_instrument(inst_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    conn.execute(
        "update payment_instruments set is_deleted=1, deleted_at=? where id=? and user_id=?",
        (datetime.utcnow().isoformat(), inst_id, user_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/instruments/trash', methods=['GET'])
def get_instruments_trash():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    rows = conn.execute(
        "select * from payment_instruments where user_id=? and is_deleted=1 order by deleted_at desc",
        (user_id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/instruments/<inst_id>/restore', methods=['POST'])
def restore_instrument(inst_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    conn.execute(
        "update payment_instruments set is_deleted=0, deleted_at=null where id=? and user_id=?",
        (inst_id, user_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/instruments/<inst_id>/permanent', methods=['DELETE'])
def permanent_delete_instrument(inst_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    conn.execute("delete from payment_instruments where id=? and user_id=?", (inst_id, user_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ══════════════════════════════════════════
# RECORDS
# ══════════════════════════════════════════
def format_record(r, return_events=None, attachments=None):
    d = dict(r)
    d['return_events'] = return_events or []
    d['attachments'] = attachments or []
    d['is_archived'] = bool(d.get('is_archived'))
    d['is_deleted'] = bool(d.get('is_deleted'))
    return d

@app.route('/records', methods=['GET'])
def get_records():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    include_archived = request.args.get('archived') == '1'
    include_deleted = request.args.get('deleted') == '1'

    conn = get_db()
    query = '''
        select r.*, c.name as company_name, p.name as card_name
        from records r
        left join companies c on r.company_id = c.id
        left join payment_instruments p on r.card_id = p.id
        where r.user_id=?
    '''
    params = [user_id]

    if not include_deleted:
        query += " and r.is_deleted=0"
    if not include_archived:
        query += " and r.is_archived=0"

    query += " order by r.date desc, r.created_at desc"

    rows = conn.execute(query, params).fetchall()

    result = []
    for row in rows:
        d = dict(row)
        events = conn.execute(
            "select * from return_events where record_id=? order by date",
            (d['id'],)
        ).fetchall()
        atts = conn.execute(
            "select * from attachments where record_id=?",
            (d['id'],)
        ).fetchall()
        d['return_events'] = [dict(e) for e in events]
        d['attachments'] = [dict(a) for a in atts]
        d['is_archived'] = bool(d.get('is_archived'))
        d['is_deleted'] = bool(d.get('is_deleted'))
        result.append(d)

    conn.close()
    return jsonify(result)

@app.route('/records', methods=['POST'])
def create_record():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    record_id = str(uuid.uuid4())
    conn = get_db()
    conn.execute('''
        insert into records
        (id, user_id, title, note, date, amount, currency, pay_type, pay_method,
         card_id, company_id, status, to_return, returned, remainder)
        values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        record_id, user_id,
        data['title'], data.get('note', ''),
        data['date'], data['amount'],
        data.get('currency', 'EUR'),
        data['pay_type'], data['pay_method'],
        data.get('card_id'), data.get('company_id'),
        data.get('status', 'waiting'),
        data.get('to_return', 0),
        data.get('returned', 0),
        data.get('remainder', 0)
    ))
    conn.commit()

    row = conn.execute('''
        select r.*, c.name as company_name, p.name as card_name
        from records r
        left join companies c on r.company_id = c.id
        left join payment_instruments p on r.card_id = p.id
        where r.id=?
    ''', (record_id,)).fetchone()
    conn.close()

    d = dict(row)
    d['return_events'] = []
    d['attachments'] = []
    d['is_archived'] = False
    d['is_deleted'] = False
    return jsonify(d), 201

@app.route('/records/<record_id>', methods=['PUT'])
def update_record(record_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    conn = get_db()
    fields = []
    values = []
    allowed = ['title', 'note', 'date', 'amount', 'pay_type', 'pay_method',
               'card_id', 'company_id', 'status', 'previous_status', 'to_return', 'returned',
               'remainder', 'is_archived', 'is_deleted', 'deleted_at']
    for key in allowed:
        if key in data:
            fields.append(f"{key}=?")
            val = data[key]
            if isinstance(val, bool):
                val = 1 if val else 0
            values.append(val)
    values.append(record_id)
    conn.execute(f"update records set {', '.join(fields)} where id=?", values)
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/records/<record_id>', methods=['DELETE'])
def delete_record_permanent(record_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    conn.execute("delete from records where id=? and user_id=?", (record_id, user_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ══════════════════════════════════════════
# RETURN EVENTS
# ══════════════════════════════════════════
@app.route('/records/<record_id>/returns', methods=['POST'])
def add_return(record_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    data = request.json
    event_id = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        "insert into return_events (id, record_id, amount, date, method) values (?,?,?,?,?)",
        (event_id, record_id, data['amount'], data['date'], data.get('method'))
    )

    # Recalculate totals
    events = conn.execute(
        "select sum(amount) as total from return_events where record_id=?",
        (record_id,)
    ).fetchone()
    total_returned = events['total'] or 0

    record = conn.execute("select amount from records where id=?", (record_id,)).fetchone()
    if record:
        remainder = max(0, record['amount'] - total_returned)
        if total_returned <= 0:
            status = 'waiting'
        elif total_returned < record['amount']:
            status = 'partial'
        else:
            status = 'done'
        conn.execute(
            "update records set returned=?, remainder=?, status=? where id=?",
            (total_returned, remainder, status, record_id)
        )

    conn.commit()
    row = conn.execute("select * from return_events where id=?", (event_id,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201

@app.route('/returns/<event_id>', methods=['DELETE'])
def delete_return(event_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    event = conn.execute("select * from return_events where id=?", (event_id,)).fetchone()
    if event:
        record_id = event['record_id']
        conn.execute("delete from return_events where id=?", (event_id,))

        events = conn.execute(
            "select sum(amount) as total from return_events where record_id=?",
            (record_id,)
        ).fetchone()
        total_returned = events['total'] or 0

        record = conn.execute("select amount from records where id=?", (record_id,)).fetchone()
        if record:
            remainder = max(0, record['amount'] - total_returned)
            if total_returned <= 0:
                status = 'waiting'
            elif total_returned < record['amount']:
                status = 'partial'
            else:
                status = 'done'
            conn.execute(
                "update records set returned=?, remainder=?, status=? where id=?",
                (total_returned, remainder, status, record_id)
            )

    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ══════════════════════════════════════════
# ATTACHMENTS
# ══════════════════════════════════════════
@app.route('/attachments/<record_id>', methods=['POST'])
def upload_attachment(record_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'Empty filename'}), 400

    conn = get_db()
    rec = conn.execute(
        "select r.date, c.name as company_name from records r "
        "left join companies c on r.company_id=c.id "
        "where r.id=? and r.user_id=?",
        (record_id, user_id)
    ).fetchone()
    if not rec:
        conn.close()
        return jsonify({'error': 'Not found'}), 404

    # Build folder: ReceiptsManager/YYYY/MM/CompanyName
    record_date = rec['date'] or datetime.utcnow().strftime('%Y-%m-%d')
    year  = record_date[:4]
    month = record_date[5:7]
    raw_company = rec['company_name'] or 'Unassigned'
    safe_company = re.sub(r'[^\w\s\-]', '', raw_company).strip().replace(' ', '_') or 'Unassigned'

    rel_folder = '/'.join([DRIVE_ROOT, year, month, safe_company])
    abs_folder = os.path.join(UPLOAD_FOLDER, DRIVE_ROOT, year, month, safe_company)
    os.makedirs(abs_folder, exist_ok=True)

    att_id = str(uuid.uuid4())
    orig_name = file.filename
    ext = os.path.splitext(orig_name)[1].lower()
    stored_name = att_id + ext
    file_path = rel_folder + '/' + stored_name      # stored with forward slashes
    file.save(os.path.join(abs_folder, stored_name))

    file_type = file.content_type or 'application/octet-stream'
    conn.execute(
        "insert into attachments (id, record_id, file_name, file_type, file_path, storage_type) values (?,?,?,?,?,?)",
        (att_id, record_id, orig_name, file_type, file_path, 'local')
    )
    conn.commit()
    conn.close()

    return jsonify({'id': att_id, 'record_id': record_id, 'file_name': orig_name, 'file_type': file_type, 'storage_type': 'local'})

@app.route('/attachments/<att_id>/file', methods=['GET'])
def serve_attachment(att_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    att = conn.execute(
        "select a.* from attachments a join records r on a.record_id=r.id where a.id=? and r.user_id=?",
        (att_id, user_id)
    ).fetchone()
    conn.close()

    if not att or not att['file_path']:
        return jsonify({'error': 'Not found'}), 404

    return send_from_directory(UPLOAD_FOLDER, att['file_path'])

@app.route('/attachments/<att_id>', methods=['DELETE'])
def delete_attachment(att_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    att = conn.execute(
        "select a.* from attachments a join records r on a.record_id=r.id where a.id=? and r.user_id=?",
        (att_id, user_id)
    ).fetchone()
    if not att:
        conn.close()
        return jsonify({'error': 'Not found'}), 404

    if att['storage_type'] == 'local' and att['file_path']:
        try:
            os.remove(os.path.join(UPLOAD_FOLDER, att['file_path']))
        except OSError:
            pass

    conn.execute("delete from attachments where id=?", (att_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ══════════════════════════════════════════
# STATIC FILES
# ══════════════════════════════════════════
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('.', path)

# ══════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════
if __name__ == '__main__':
    os.makedirs('data', exist_ok=True)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    init_db()
    print("🚀 Starting Reimbursement App server...")
    print("📍 Open: http://localhost:5500")
    print("👤 Default login: admin@local.app / admin123")
    print("─" * 40)
    app.run(host='0.0.0.0', port=5500, debug=False)
