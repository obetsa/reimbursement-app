from flask import Flask, request, jsonify, send_from_directory, session as flask_session, redirect
from flask_cors import CORS
from dotenv import load_dotenv
import requests as http_requests
import sqlite3
import uuid
import os
import re
import secrets
import hashlib
import base64
from datetime import datetime
import shutil
import zipfile
import io

load_dotenv()

app = Flask(__name__, static_folder='.')
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-prod')
CORS(app, supports_credentials=True)

os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # HTTP allowed in development

GOOGLE_CLIENT_ID     = os.environ.get('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
REDIRECT_URI         = os.environ.get('REDIRECT_URI', 'http://localhost:5500/auth/callback')

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

    # Migrate attachments: add storage_type, file_path, drive_id if missing
    try:
        c.execute("alter table attachments add column storage_type text default 'local'")
    except Exception:
        pass
    try:
        c.execute("alter table attachments add column file_path text")
    except Exception:
        pass
    try:
        c.execute("alter table attachments add column drive_id text")
    except Exception:
        pass

    # Migrate users: add refresh_token if missing
    try:
        c.execute("alter table users add column refresh_token text")
    except Exception:
        pass

    # Migrate unprocessed_imports: add drive_folder if missing
    try:
        c.execute("alter table unprocessed_imports add column drive_folder text default ''")
    except Exception:
        pass

    # Unprocessed imports from Drive
    c.execute('''
        create table if not exists unprocessed_imports (
            id text primary key,
            user_id text not null,
            drive_id text not null,
            file_name text not null,
            mime_type text,
            synced_at text default (datetime('now'))
        )
    ''')

    conn.commit()
    conn.close()

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    print("✅ Database initialized")

# ══════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════

def get_user_from_token(request):
    return flask_session.get('user_id')

def _pkce_pair():
    verifier  = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b'=').decode()
    return verifier, challenge

@app.route('/auth/google')
def auth_google():
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    flask_session['oauth_state']    = state
    flask_session['code_verifier']  = verifier

    params = '&'.join([
        f'client_id={GOOGLE_CLIENT_ID}',
        f'redirect_uri={REDIRECT_URI}',
        'response_type=code',
        'scope=openid%20email%20profile%20https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fdrive',
        f'state={state}',
        f'code_challenge={challenge}',
        'code_challenge_method=S256',
        'prompt=consent',
        'access_type=offline',
    ])
    return redirect(f'https://accounts.google.com/o/oauth2/auth?{params}')

@app.route('/auth/callback')
def auth_callback():
    code          = request.args.get('code')
    code_verifier = flask_session.pop('code_verifier', '')

    token_resp = http_requests.post('https://oauth2.googleapis.com/token', data={
        'client_id':     GOOGLE_CLIENT_ID,
        'client_secret': GOOGLE_CLIENT_SECRET,
        'redirect_uri':  REDIRECT_URI,
        'grant_type':    'authorization_code',
        'code':          code,
        'code_verifier': code_verifier,
    })
    token_data    = token_resp.json()
    access_token  = token_data.get('access_token')
    refresh_token = token_data.get('refresh_token', '')

    user_info = http_requests.get(
        'https://www.googleapis.com/oauth2/v2/userinfo',
        headers={'Authorization': f'Bearer {access_token}'}
    ).json()

    email     = user_info.get('email', '')
    full_name = user_info.get('name', '')

    conn = get_db()
    user = conn.execute("select id from users where email=?", (email,)).fetchone()
    if user:
        user_id = user['id']
        if refresh_token:
            conn.execute("update users set refresh_token=? where id=?", (refresh_token, user_id))
            conn.commit()
    else:
        user_id = str(uuid.uuid4())
        conn.execute(
            "insert into users (id, email, password_hash, full_name, refresh_token) values (?,?,?,?,?)",
            (user_id, email, 'GOOGLE_AUTH', full_name, refresh_token)
        )
        conn.commit()
    conn.close()

    flask_session['user_id']   = user_id
    flask_session['email']     = email
    flask_session['full_name'] = full_name
    flask_session.permanent    = True

    return redirect('/')


@app.route('/auth/logout', methods=['POST'])
def logout():
    flask_session.clear()
    return jsonify({'ok': True})

@app.route('/auth/me', methods=['GET'])
def me():
    user_id = flask_session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify({
        'id':        user_id,
        'email':     flask_session.get('email', ''),
        'full_name': flask_session.get('full_name', '')
    })

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

    old_row = conn.execute(
        "select name from companies where id=? and user_id=?", (company_id, user_id)
    ).fetchone()

    fields = []
    values = []
    for key in ['name', 'is_shared', 'is_active', 'sort_order']:
        if key in data:
            fields.append(f"{key}=?")
            values.append(1 if data[key] is True else (0 if data[key] is False else data[key]))
    values.append(company_id)
    conn.execute(f"update companies set {', '.join(fields)} where id=?", values)
    conn.commit()

    if old_row and 'name' in data and data['name'] != old_row['name']:
        old_safe = re.sub(r'[^\w\s\-]', '', old_row['name']).strip().replace(' ', '_') or 'Unassigned'
        new_safe = re.sub(r'[^\w\s\-]', '', data['name']).strip().replace(' ', '_') or 'Unassigned'

        if old_safe != new_safe:
            atts = conn.execute(
                "select a.id, a.file_path, a.drive_id from attachments a "
                "join records r on a.record_id=r.id "
                "where r.company_id=? and r.user_id=? and a.file_path is not null",
                (company_id, user_id)
            ).fetchall()

            old_dirs = set()
            for att in atts:
                parts = att['file_path'].replace('\\', '/').split('/')
                if len(parts) >= 4:
                    old_dirs.add('/'.join(parts[:4]))

            for old_dir in old_dirs:
                dir_parts = old_dir.split('/')
                new_dir = '/'.join(dir_parts[:3] + [new_safe])
                old_abs = os.path.join(UPLOAD_FOLDER, *dir_parts)
                new_abs = os.path.join(UPLOAD_FOLDER, *new_dir.split('/'))
                if os.path.exists(old_abs):
                    if not os.path.exists(new_abs):
                        os.rename(old_abs, new_abs)
                    else:
                        for fname in os.listdir(old_abs):
                            os.rename(os.path.join(old_abs, fname), os.path.join(new_abs, fname))
                        os.rmdir(old_abs)

            for att in atts:
                parts = att['file_path'].replace('\\', '/').split('/')
                if len(parts) >= 4 and parts[3] == old_safe:
                    parts[3] = new_safe
                    conn.execute("update attachments set file_path=? where id=?",
                                 ('/'.join(parts), att['id']))
            conn.commit()

            access_token = get_drive_token(user_id)
            if access_token:
                for old_dir in old_dirs:
                    dir_parts = old_dir.split('/')
                    year, month = dir_parts[1], dir_parts[2]
                    try:
                        parent_id = drive_ensure_folder_path(access_token, [DRIVE_ROOT, year, month])
                        escaped = old_safe.replace("'", "\\'")
                        resp = http_requests.get(
                            'https://www.googleapis.com/drive/v3/files',
                            headers={'Authorization': f'Bearer {access_token}'},
                            params={
                                'q': f"name='{escaped}' and mimeType='application/vnd.google-apps.folder' and trashed=false and '{parent_id}' in parents",
                                'fields': 'files(id)',
                                'spaces': 'drive'
                            }
                        ).json()
                        for folder in resp.get('files', []):
                            http_requests.patch(
                                f'https://www.googleapis.com/drive/v3/files/{folder["id"]}',
                                headers={'Authorization': f'Bearer {access_token}'},
                                json={'name': new_safe}
                            )
                    except Exception:
                        pass

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

    # Snapshot before update to detect date/company changes
    old = conn.execute(
        "select r.date, r.company_id, c.name as company_name "
        "from records r left join companies c on r.company_id=c.id "
        "where r.id=? and r.user_id=?",
        (record_id, user_id)
    ).fetchone()

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

    # Move files if date or company changed
    if old:
        new_date       = data.get('date',       old['date'])
        new_company_id = data.get('company_id', old['company_id'])
        date_changed    = 'date'       in data and data['date']       != old['date']
        company_changed = 'company_id' in data and data['company_id'] != old['company_id']

        if (date_changed or company_changed) and new_date:
            new_company_row = conn.execute(
                "select name from companies where id=?", (new_company_id,)
            ).fetchone() if new_company_id else None
            new_company_name = (new_company_row['name'] if new_company_row else None) or 'Unassigned'
            new_safe = re.sub(r'[^\w\s\-]', '', new_company_name).strip().replace(' ', '_') or 'Unassigned'
            new_year  = new_date[:4]
            new_month = new_date[5:7]
            new_folder = '/'.join([DRIVE_ROOT, new_year, new_month, new_safe])

            atts = conn.execute(
                "select * from attachments where record_id=? and file_path is not null",
                (record_id,)
            ).fetchall()

            access_token = None
            if any(a['drive_id'] for a in atts):
                try:
                    access_token = get_drive_token(user_id)
                except Exception:
                    pass

            for att in atts:
                old_path = att['file_path'].replace('\\', '/')
                filename = old_path.split('/')[-1]
                new_path = new_folder + '/' + filename

                if old_path == new_path:
                    continue

                # Move local file
                old_abs = os.path.join(UPLOAD_FOLDER, old_path.replace('/', os.sep))
                new_abs = os.path.join(UPLOAD_FOLDER, new_path.replace('/', os.sep))
                if os.path.exists(old_abs):
                    try:
                        os.makedirs(os.path.dirname(new_abs), exist_ok=True)
                        shutil.move(old_abs, new_abs)
                    except Exception:
                        pass

                # Update DB path
                conn.execute("update attachments set file_path=? where id=?", (new_path, att['id']))

                # Move on Drive
                if att['drive_id'] and access_token:
                    try:
                        old_folder_parts = old_path.split('/')[:-1]
                        new_folder_parts = new_folder.split('/')
                        old_folder_id = drive_ensure_folder_path(access_token, old_folder_parts)
                        new_folder_id = drive_ensure_folder_path(access_token, new_folder_parts)
                        drive_move_file(access_token, att['drive_id'], new_folder_id, old_folder_id)
                    except Exception:
                        pass

            conn.commit()

            # Clean up empty old folders (local + Drive)
            if atts:
                old_folder_rel = atts[0]['file_path'].replace('\\', '/').rsplit('/', 1)[0]
                old_folder_abs = os.path.join(UPLOAD_FOLDER, old_folder_rel.replace('/', os.sep))
                try:
                    os.rmdir(old_folder_abs)
                except Exception:
                    pass

                if access_token:
                    try:
                        old_folder_parts = old_folder_rel.split('/')
                        old_folder_id = drive_ensure_folder_path(access_token, old_folder_parts)
                        r = http_requests.get(
                            'https://www.googleapis.com/drive/v3/files',
                            headers={'Authorization': f'Bearer {access_token}'},
                            params={'q': f"'{old_folder_id}' in parents and trashed=false",
                                    'fields': 'files(id)', 'pageSize': 1}
                        ).json()
                        if not r.get('files'):
                            http_requests.delete(
                                f'https://www.googleapis.com/drive/v3/files/{old_folder_id}',
                                headers={'Authorization': f'Bearer {access_token}'}
                            )
                    except Exception:
                        pass

    conn.close()
    return jsonify({'ok': True})

@app.route('/records/<record_id>', methods=['DELETE'])
def delete_record_permanent(record_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    atts = conn.execute(
        "select a.* from attachments a join records r on a.record_id=r.id "
        "where a.record_id=? and r.user_id=?",
        (record_id, user_id)
    ).fetchall()

    access_token = get_drive_token(user_id)
    for att in atts:
        if att['file_path']:
            try:
                os.remove(os.path.join(UPLOAD_FOLDER, att['file_path'].replace('/', os.sep)))
            except OSError:
                pass
        if att['drive_id'] and access_token:
            try:
                http_requests.delete(
                    f'https://www.googleapis.com/drive/v3/files/{att["drive_id"]}',
                    headers={'Authorization': f'Bearer {access_token}'}
                )
            except Exception:
                pass

    conn.execute("PRAGMA foreign_keys=ON")
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

    # Try Drive upload immediately
    drive_id = None
    access_token = get_drive_token(user_id)
    if access_token:
        try:
            folder_id = drive_ensure_folder_path(access_token, [DRIVE_ROOT, year, month, safe_company])
            with open(os.path.join(abs_folder, stored_name), 'rb') as f:
                drive_id = drive_upload_file(access_token, folder_id, orig_name, f.read(), file_type)
        except Exception:
            pass

    storage = 'drive' if drive_id else 'local'
    conn.execute(
        "insert into attachments (id, record_id, file_name, file_type, file_path, storage_type, drive_id) values (?,?,?,?,?,?,?)",
        (att_id, record_id, orig_name, file_type, file_path, storage, drive_id)
    )
    conn.commit()
    conn.close()

    return jsonify({'id': att_id, 'record_id': record_id, 'file_name': orig_name, 'file_type': file_type, 'storage_type': storage, 'drive_id': drive_id})

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

    drive_warning = None
    if att['drive_id']:
        access_token = get_drive_token(user_id)
        if access_token:
            try:
                resp = http_requests.delete(
                    f'https://www.googleapis.com/drive/v3/files/{att["drive_id"]}',
                    headers={'Authorization': f'Bearer {access_token}'}
                )
                if resp.status_code not in (204, 404):
                    drive_warning = f'Drive error: {resp.status_code}'
            except Exception as e:
                drive_warning = str(e)
        else:
            drive_warning = 'no_drive_token'

    if att['file_path']:
        try:
            os.remove(os.path.join(UPLOAD_FOLDER, att['file_path'].replace('/', os.sep)))
        except Exception:
            pass

    conn.execute("delete from attachments where id=?", (att_id,))
    conn.commit()
    conn.close()

    return jsonify({'ok': True, 'drive_warning': drive_warning})

# ══════════════════════════════════════════
# GOOGLE DRIVE HELPERS
# ══════════════════════════════════════════
def _drive_refresh_access_token(refresh_token):
    resp = http_requests.post('https://oauth2.googleapis.com/token', data={
        'client_id':     GOOGLE_CLIENT_ID,
        'client_secret': GOOGLE_CLIENT_SECRET,
        'refresh_token': refresh_token,
        'grant_type':    'refresh_token',
    })
    return resp.json().get('access_token')

def get_drive_token(user_id):
    conn = get_db()
    row = conn.execute("select refresh_token from users where id=?", (user_id,)).fetchone()
    conn.close()
    if not row or not row['refresh_token']:
        return None
    return _drive_refresh_access_token(row['refresh_token'])

def drive_ensure_folder(access_token, name, parent_id=None):
    safe_name = name.replace("'", "\\'")
    q = f"name='{safe_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    resp = http_requests.get(
        'https://www.googleapis.com/drive/v3/files',
        headers={'Authorization': f'Bearer {access_token}'},
        params={'q': q, 'fields': 'files(id)', 'spaces': 'drive'}
    ).json()
    files = resp.get('files', [])
    if files:
        return files[0]['id']
    meta = {'name': name, 'mimeType': 'application/vnd.google-apps.folder'}
    if parent_id:
        meta['parents'] = [parent_id]
    resp = http_requests.post(
        'https://www.googleapis.com/drive/v3/files',
        headers={'Authorization': f'Bearer {access_token}'},
        json=meta
    ).json()
    return resp.get('id')

def drive_ensure_folder_path(access_token, path_parts):
    parent_id = None
    for part in path_parts:
        parent_id = drive_ensure_folder(access_token, part, parent_id)
    return parent_id

def drive_upload_file(access_token, folder_id, filename, file_bytes, mime_type):
    import json as _json
    meta = _json.dumps({'name': filename, 'parents': [folder_id] if folder_id else []})
    resp = http_requests.post(
        'https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart',
        headers={'Authorization': f'Bearer {access_token}'},
        files={
            'metadata': ('metadata', meta, 'application/json; charset=UTF-8'),
            'file':     (filename, file_bytes, mime_type),
        }
    ).json()
    return resp.get('id')

# ══════════════════════════════════════════
# SYNC
# ══════════════════════════════════════════
def drive_list_recursive(access_token, folder_id, result=None, depth=0, skip_folders=None, current_path=''):
    if result is None: result = []
    if skip_folders is None: skip_folders = set()
    if depth >= 5 or len(result) >= 500:
        return result
    try:
        resp = http_requests.get(
            'https://www.googleapis.com/drive/v3/files',
            headers={'Authorization': f'Bearer {access_token}'},
            params={
                'q': f"'{folder_id}' in parents and mimeType!='application/vnd.google-apps.folder' and trashed=false",
                'fields': 'files(id,name,mimeType)', 'spaces': 'drive', 'pageSize': 100,
            }
        ).json()
        for f in resp.get('files', []):
            f['folder_path'] = current_path
            result.append(f)
        resp2 = http_requests.get(
            'https://www.googleapis.com/drive/v3/files',
            headers={'Authorization': f'Bearer {access_token}'},
            params={
                'q': f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
                'fields': 'files(id,name)', 'spaces': 'drive', 'pageSize': 50,
            }
        ).json()
        for sub in resp2.get('files', []):
            if sub.get('name') in skip_folders or len(result) >= 500:
                continue
            sub_path = sub['name'] if not current_path else f"{current_path}/{sub['name']}"
            drive_list_recursive(access_token, sub['id'], result, depth + 1, skip_folders, sub_path)
    except Exception:
        pass
    return result


def drive_list_folder(access_token, folder_id):
    resp = http_requests.get(
        'https://www.googleapis.com/drive/v3/files',
        headers={'Authorization': f'Bearer {access_token}'},
        params={
            'q': f"'{folder_id}' in parents and trashed=false and mimeType!='application/vnd.google-apps.folder'",
            'fields': 'files(id,name,mimeType)',
            'spaces': 'drive',
        }
    ).json()
    return resp.get('files', [])

def drive_move_file(access_token, file_id, new_folder_id, old_folder_id):
    http_requests.patch(
        f'https://www.googleapis.com/drive/v3/files/{file_id}',
        headers={'Authorization': f'Bearer {access_token}'},
        params={'addParents': new_folder_id, 'removeParents': old_folder_id, 'fields': 'id'},
    )

def drive_download_file(access_token, file_id):
    resp = http_requests.get(
        f'https://www.googleapis.com/drive/v3/files/{file_id}?alt=media',
        headers={'Authorization': f'Bearer {access_token}'}
    )
    return resp.content

@app.route('/sync/diagnose', methods=['GET'])
def sync_diagnose():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    all_atts = conn.execute(
        "select a.id, a.file_name, a.file_path, a.drive_id, a.storage_type, "
        "r.is_deleted, r.is_archived "
        "from attachments a join records r on a.record_id=r.id "
        "where r.user_id=?",
        (user_id,)
    ).fetchall()
    conn.close()

    result = {
        'total': len(all_atts),
        'breakdown': {
            'no_drive_id':         [],
            'storage_type_local':  [],
            'storage_type_drive':  [],
            'deleted_record':      [],
            'archived_record':     [],
        }
    }
    for a in all_atts:
        row = {'id': a['id'], 'file_name': a['file_name'],
               'file_path': a['file_path'], 'drive_id': a['drive_id'],
               'storage_type': a['storage_type']}
        if a['is_deleted']:
            result['breakdown']['deleted_record'].append(row)
        elif a['is_archived']:
            result['breakdown']['archived_record'].append(row)

        if not a['drive_id']:
            result['breakdown']['no_drive_id'].append(row)
        if a['storage_type'] == 'local':
            result['breakdown']['storage_type_local'].append(row)
        elif a['storage_type'] == 'drive':
            result['breakdown']['storage_type_drive'].append(row)

    # Optional: verify each drive_id actually exists on Drive
    if request.args.get('verify') == '1':
        access_token = get_drive_token(user_id)
        verified = []
        if access_token:
            for row in result['breakdown']['storage_type_drive']:
                try:
                    r = http_requests.get(
                        f'https://www.googleapis.com/drive/v3/files/{row["drive_id"]}',
                        headers={'Authorization': f'Bearer {access_token}'},
                        params={'fields': 'id,name,trashed,parents'}
                    )
                    data = r.json()
                    parent_id = (data.get('parents') or [None])[0]
                    parent_name = None
                    if parent_id:
                        pr = http_requests.get(
                            f'https://www.googleapis.com/drive/v3/files/{parent_id}',
                            headers={'Authorization': f'Bearer {access_token}'},
                            params={'fields': 'id,name'}
                        ).json()
                        parent_name = pr.get('name')
                    verified.append({
                        'file_name':   row['file_name'],
                        'drive_id':    row['drive_id'],
                        'exists':      r.status_code == 200,
                        'trashed':     data.get('trashed', False),
                        'parent_id':   parent_id,
                        'parent_name': parent_name,
                    })
                except Exception:
                    verified.append({'file_name': row['file_name'], 'drive_id': row['drive_id'], 'exists': False, 'trashed': False})
        result['drive_verification'] = verified

    return jsonify(result)


@app.route('/sync/preview', methods=['GET'])
def sync_preview():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    if not get_drive_token(user_id):
        return jsonify({'error': 'no_drive_token'}), 403

    conn = get_db()
    to_upload_rows = conn.execute(
        "select a.file_name from attachments a join records r on a.record_id=r.id "
        "where r.user_id=? and r.is_deleted=0 and a.file_path is not null "
        "and (a.drive_id is null or a.storage_type='local')",
        (user_id,)
    ).fetchall()
    conn.close()

    return jsonify({'to_upload': [r['file_name'] for r in to_upload_rows]})


@app.route('/sync', methods=['POST'])
def sync_drive():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    access_token = get_drive_token(user_id)
    if not access_token:
        return jsonify({'ok': False, 'message': 'no_drive_token'})

    conn = get_db()
    uploaded = 0

    # ── Push: local → Drive ──
    unsynced = conn.execute(
        "select a.* from attachments a join records r on a.record_id=r.id "
        "where r.user_id=? and r.is_deleted=0 and a.file_path is not null "
        "and (a.drive_id is null or a.storage_type='local')",
        (user_id,)
    ).fetchall()
    for att in unsynced:
        abs_path = os.path.join(UPLOAD_FOLDER, att['file_path'].replace('/', os.sep))
        if not os.path.exists(abs_path):
            continue
        parts = att['file_path'].replace('\\', '/').split('/')
        try:
            folder_id = drive_ensure_folder_path(access_token, parts[:-1])
            with open(abs_path, 'rb') as f:
                drive_id = drive_upload_file(access_token, folder_id, att['file_name'], f.read(), att['file_type'] or 'application/octet-stream')
            if drive_id:
                conn.execute("update attachments set drive_id=?, storage_type='drive' where id=?", (drive_id, att['id']))
                uploaded += 1
        except Exception:
            pass

    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'uploaded': uploaded})


@app.route('/sync/verify-drive', methods=['POST'])
def sync_verify_drive():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    access_token = get_drive_token(user_id)
    if not access_token:
        return jsonify({'ok': False, 'message': 'no_drive_token'})

    conn = get_db()
    atts = conn.execute(
        "select a.id, a.drive_id from attachments a join records r on a.record_id=r.id "
        "where r.user_id=? and a.drive_id is not null",
        (user_id,)
    ).fetchall()

    fixed = 0
    for att in atts:
        try:
            resp = http_requests.get(
                f'https://www.googleapis.com/drive/v3/files/{att["drive_id"]}',
                headers={'Authorization': f'Bearer {access_token}'},
                params={'fields': 'id'}
            )
            if resp.status_code == 404:
                conn.execute(
                    "update attachments set drive_id=null, storage_type='local' where id=?",
                    (att['id'],)
                )
                fixed += 1
        except Exception:
            pass

    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'fixed': fixed})


@app.route('/drive-cleanup', methods=['POST'])
def drive_cleanup():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    access_token = get_drive_token(user_id)
    if not access_token:
        return jsonify({'ok': False, 'message': 'no_drive_token'})

    conn = get_db()
    known_ids = {r['drive_id'] for r in conn.execute(
        "select a.drive_id from attachments a join records r on a.record_id=r.id "
        "where r.user_id=? and a.drive_id is not null", (user_id,)
    ).fetchall()}
    known_ids |= {r['drive_id'] for r in conn.execute(
        "select drive_id from unprocessed_imports where user_id=?", (user_id,)
    ).fetchall()}
    conn.close()

    deleted_files = 0
    deleted_folders = 0
    protected = {'Unprocessed Imports', 'Backup'}

    try:
        rm_id = drive_ensure_folder_path(access_token, [DRIVE_ROOT])

        # Delete orphan files (skip Backup folder entirely)
        drive_files = drive_list_recursive(access_token, rm_id, skip_folders={'Backup'})
        for f in drive_files:
            if f['id'] not in known_ids:
                try:
                    resp = http_requests.delete(
                        f'https://www.googleapis.com/drive/v3/files/{f["id"]}',
                        headers={'Authorization': f'Bearer {access_token}'}
                    )
                    if resp.status_code == 204:
                        deleted_files += 1
                except Exception:
                    pass

        # Collect all subfolders (BFS order = parents before children)
        all_folders = []
        queue = [rm_id]
        visited = set()
        while queue:
            fid = queue.pop(0)
            if fid in visited:
                continue
            visited.add(fid)
            r = http_requests.get(
                'https://www.googleapis.com/drive/v3/files',
                headers={'Authorization': f'Bearer {access_token}'},
                params={
                    'q': f"'{fid}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
                    'fields': 'files(id,name)', 'pageSize': 100,
                }
            ).json()
            for sub in r.get('files', []):
                all_folders.append({'id': sub['id'], 'name': sub['name']})
                queue.append(sub['id'])

        # Delete empty folders bottom-up (children before parents)
        for folder in reversed(all_folders):
            if folder['name'] in protected:
                continue
            r = http_requests.get(
                'https://www.googleapis.com/drive/v3/files',
                headers={'Authorization': f'Bearer {access_token}'},
                params={'q': f"'{folder['id']}' in parents and trashed=false", 'fields': 'files(id)', 'pageSize': 1}
            ).json()
            if not r.get('files'):
                try:
                    resp = http_requests.delete(
                        f'https://www.googleapis.com/drive/v3/files/{folder["id"]}',
                        headers={'Authorization': f'Bearer {access_token}'}
                    )
                    if resp.status_code == 204:
                        deleted_folders += 1
                except Exception:
                    pass

    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)})

    return jsonify({'ok': True, 'deleted_files': deleted_files, 'deleted_folders': deleted_folders})


@app.route('/import-from-drive', methods=['POST'])
def import_from_drive():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    access_token = get_drive_token(user_id)
    if not access_token:
        return jsonify({'ok': False, 'message': 'no_drive_token'})

    conn = get_db()
    known_ids = {r['drive_id'] for r in conn.execute(
        "select a.drive_id from attachments a join records r on a.record_id=r.id "
        "where r.user_id=? and a.drive_id is not null", (user_id,)
    ).fetchall()}
    known_ids |= {r['drive_id'] for r in conn.execute(
        "select drive_id from unprocessed_imports where user_id=?", (user_id,)
    ).fetchall()}

    imported = 0
    cleaned = 0
    try:
        rm_id = drive_ensure_folder_path(access_token, [DRIVE_ROOT])
        drive_files = drive_list_recursive(access_token, rm_id, skip_folders={'Unprocessed Imports', 'Backup'})
        drive_ids_on_drive = {f['id'] for f in drive_files}

        # Add new files
        for f in drive_files:
            if f['id'] not in known_ids:
                conn.execute(
                    "insert into unprocessed_imports (id, user_id, drive_id, file_name, mime_type, drive_folder) values (?,?,?,?,?,?)",
                    (str(uuid.uuid4()), user_id, f['id'], f['name'], f.get('mimeType', ''), f.get('folder_path', ''))
                )
                imported += 1

        # Remove stale unprocessed entries whose file no longer exists on Drive
        existing = conn.execute(
            "select id, drive_id from unprocessed_imports where user_id=?", (user_id,)
        ).fetchall()
        for row in existing:
            if row['drive_id'] not in drive_ids_on_drive:
                conn.execute("delete from unprocessed_imports where id=?", (row['id'],))
                cleaned += 1

    except Exception as e:
        pass
        conn.close()
        return jsonify({'ok': False, 'message': 'drive_error'})

    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'imported': imported, 'cleaned': cleaned})

@app.route('/gallery', methods=['GET'])
def get_gallery():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    att_rows = conn.execute('''
        select
            a.id, a.file_name, a.file_type, a.file_path, a.drive_id,
            a.storage_type, a.created_at,
            r.date as record_date,
            c.name as company_name,
            p.name as card_name,
            'assigned' as source
        from attachments a
        join records r on a.record_id = r.id
        left join companies c on r.company_id = c.id
        left join payment_instruments p on r.card_id = p.id
        where r.user_id = ? and r.is_deleted = 0 and a.file_path is not null
        order by a.created_at desc
    ''', (user_id,)).fetchall()

    conn.close()
    return jsonify([dict(r) for r in att_rows])

@app.route('/unprocessed', methods=['GET'])
def get_unprocessed():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    rows = conn.execute(
        "select * from unprocessed_imports where user_id=? order by synced_at desc",
        (user_id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/unprocessed/<imp_id>/assign', methods=['POST'])
def assign_unprocessed(imp_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    data = request.json or {}
    record_id = data.get('record_id')
    if not record_id:
        return jsonify({'error': 'record_id required'}), 400

    conn = get_db()
    exists = conn.execute(
        "select id from unprocessed_imports where id=? and user_id=?", (imp_id, user_id)
    ).fetchone()
    conn.close()
    if not exists:
        return jsonify({'error': 'Not found'}), 404

    drive_ok = _do_assign(imp_id, record_id, user_id)
    return jsonify({'ok': True, 'record_id': record_id, 'drive_ok': drive_ok})

@app.route('/unprocessed/<imp_id>/new-record', methods=['POST'])
def unprocessed_new_record(imp_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    data = request.json or {}
    conn = get_db()
    imp = conn.execute(
        "select * from unprocessed_imports where id=? and user_id=?", (imp_id, user_id)
    ).fetchone()
    if not imp:
        conn.close()
        return jsonify({'error': 'Not found'}), 404

    record_id = str(uuid.uuid4())
    conn.execute('''
        insert into records
        (id, user_id, title, note, date, amount, currency, pay_type, pay_method,
         card_id, company_id, status, to_return, returned, remainder)
        values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        record_id, user_id,
        data.get('title', imp['file_name']),
        data.get('note', ''),
        data.get('date', datetime.utcnow().strftime('%Y-%m-%d')),
        data.get('amount', 0),
        data.get('currency', 'EUR'),
        data.get('pay_type', 'personal'),
        data.get('pay_method', 'cash'),
        data.get('card_id'), data.get('company_id'),
        'waiting', 0, 0, 0
    ))
    conn.commit()
    conn.close()

    # Assign file to the new record using shared helper
    drive_ok = _do_assign(imp_id, record_id, user_id)
    return jsonify({'ok': True, 'record_id': record_id, 'drive_ok': drive_ok})

def _do_assign(imp_id, record_id, user_id):
    conn = get_db()
    imp = conn.execute(
        "select * from unprocessed_imports where id=? and user_id=?", (imp_id, user_id)
    ).fetchone()
    if not imp:
        conn.close()
        return

    rec = conn.execute(
        "select r.date, c.name as company_name from records r "
        "left join companies c on r.company_id=c.id where r.id=? and r.user_id=?",
        (record_id, user_id)
    ).fetchone()
    if not rec:
        conn.close()
        return

    record_date = rec['date'] or datetime.utcnow().strftime('%Y-%m-%d')
    year  = record_date[:4]
    month = record_date[5:7]
    raw_company = rec['company_name'] or 'Unassigned'
    safe_company = re.sub(r'[^\w\s\-]', '', raw_company).strip().replace(' ', '_') or 'Unassigned'

    rel_folder = '/'.join([DRIVE_ROOT, year, month, safe_company])
    abs_folder = os.path.join(UPLOAD_FOLDER, DRIVE_ROOT, year, month, safe_company)
    os.makedirs(abs_folder, exist_ok=True)

    att_id = str(uuid.uuid4())
    orig_name = imp['file_name']
    ext = os.path.splitext(orig_name)[1].lower()
    stored_name = att_id + ext
    file_path = rel_folder + '/' + stored_name
    mime_type = imp['mime_type'] or 'application/octet-stream'

    saved_locally = False
    try:
        access_token = get_drive_token(user_id)
        if access_token:
            file_bytes = drive_download_file(access_token, imp['drive_id'])
            with open(os.path.join(abs_folder, stored_name), 'wb') as f:
                f.write(file_bytes)
            saved_locally = True
    except Exception as e:
        pass

    if not saved_locally:
        open(os.path.join(abs_folder, stored_name), 'wb').close()

    conn.execute(
        "insert into attachments (id, record_id, file_name, file_type, file_path, storage_type, drive_id) values (?,?,?,?,?,?,?)",
        (att_id, record_id, orig_name, mime_type, file_path, 'local', None)
    )
    conn.execute("delete from unprocessed_imports where id=?", (imp_id,))
    conn.commit()
    conn.close()
    return True

# ══════════════════════════════════════════
# BACKUP
# ══════════════════════════════════════════
@app.route('/backup/download', methods=['GET'])
def backup_download():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    buf = io.BytesIO()
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        if os.path.exists(DB_PATH):
            zf.write(DB_PATH, 'local.db')
        if os.path.exists(UPLOAD_FOLDER):
            for dirpath, _, filenames in os.walk(UPLOAD_FOLDER):
                for fname in filenames:
                    full    = os.path.join(dirpath, fname)
                    arcname = os.path.relpath(full, os.path.dirname(UPLOAD_FOLDER))
                    zf.write(full, arcname)
    buf.seek(0)
    from flask import Response
    return Response(
        buf.getvalue(),
        mimetype='application/zip',
        headers={'Content-Disposition': f'attachment; filename=backup_{timestamp}.zip'}
    )


@app.route('/backup/list', methods=['GET'])
def backup_list():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    access_token = get_drive_token(user_id)
    if not access_token:
        return jsonify({'ok': False, 'message': 'no_drive_token'})

    try:
        folder_id = drive_ensure_folder_path(access_token, [DRIVE_ROOT, 'Backup'])
        resp = http_requests.get(
            'https://www.googleapis.com/drive/v3/files',
            headers={'Authorization': f'Bearer {access_token}'},
            params={
                'q': f"'{folder_id}' in parents and mimeType='application/zip' and trashed=false",
                'fields': 'files(id,name,modifiedTime,size)',
                'orderBy': 'modifiedTime desc',
                'pageSize': 20,
            }
        ).json()
        files = resp.get('files', [])
    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)})

    return jsonify({'ok': True, 'files': files})


@app.route('/backup/restore-from-drive', methods=['POST'])
def backup_restore_from_drive():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    drive_id = (request.json or {}).get('drive_id')
    if not drive_id:
        return jsonify({'ok': False, 'message': 'drive_id required'}), 400

    access_token = get_drive_token(user_id)
    if not access_token:
        return jsonify({'ok': False, 'message': 'no_drive_token'})

    try:
        file_bytes = drive_download_file(access_token, drive_id)
        buf = io.BytesIO(file_bytes)
        with zipfile.ZipFile(buf, 'r') as zf:
            if 'local.db' not in zf.namelist():
                return jsonify({'ok': False, 'message': 'invalid_backup'}), 400
            with zf.open('local.db') as src:
                with open(DB_PATH, 'wb') as dst:
                    dst.write(src.read())
            upload_prefix = 'uploads/'
            for name in zf.namelist():
                if name.startswith(upload_prefix) and not name.endswith('/'):
                    dest = os.path.join('data', name.replace('/', os.sep))
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with zf.open(name) as src:
                        with open(dest, 'wb') as dst:
                            dst.write(src.read())
    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)}), 500

    return jsonify({'ok': True})


@app.route('/backup/restore', methods=['POST'])
def backup_restore():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    if 'file' not in request.files:
        return jsonify({'ok': False, 'message': 'no_file'}), 400
    f = request.files['file']
    if not f.filename.endswith('.zip'):
        return jsonify({'ok': False, 'message': 'invalid_file'}), 400

    try:
        buf = io.BytesIO(f.read())
        with zipfile.ZipFile(buf, 'r') as zf:
            names = zf.namelist()
            if 'local.db' not in names:
                return jsonify({'ok': False, 'message': 'invalid_backup'}), 400

            # Restore DB
            with zf.open('local.db') as src:
                with open(DB_PATH, 'wb') as dst:
                    dst.write(src.read())

            # Restore uploads
            upload_prefix = 'uploads/'
            for name in names:
                if name.startswith(upload_prefix) and not name.endswith('/'):
                    dest = os.path.join('data', name.replace('/', os.sep))
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with zf.open(name) as src:
                        with open(dest, 'wb') as dst:
                            dst.write(src.read())
    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)}), 500

    return jsonify({'ok': True})


@app.route('/backup', methods=['POST'])
def backup():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    access_token = get_drive_token(user_id)
    if not access_token:
        return jsonify({'ok': False, 'message': 'no_drive_token'})

    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    filename  = f'backup_{timestamp}.zip'

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        if os.path.exists(DB_PATH):
            zf.write(DB_PATH, 'local.db')
        if os.path.exists(UPLOAD_FOLDER):
            for dirpath, _, filenames in os.walk(UPLOAD_FOLDER):
                for fname in filenames:
                    full    = os.path.join(dirpath, fname)
                    arcname = os.path.relpath(full, os.path.dirname(UPLOAD_FOLDER))
                    zf.write(full, arcname)
    buf.seek(0)

    try:
        folder_id = drive_ensure_folder_path(access_token, [DRIVE_ROOT, 'Backup'])
        drive_upload_file(access_token, folder_id, filename, buf.getvalue(), 'application/zip')
    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)})

    return jsonify({'ok': True, 'filename': filename})


# ══════════════════════════════════════════
# PROFILE
# ══════════════════════════════════════════
@app.route('/profile', methods=['GET'])
def get_profile():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    row = conn.execute(
        "select email, full_name, refresh_token from users where id=?", (user_id,)
    ).fetchone()
    conn.close()
    if not row: return jsonify({'error': 'Not found'}), 404

    return jsonify({
        'email':        row['email'] or '',
        'full_name':    row['full_name'] or '',
        'drive_connected': bool(row['refresh_token']),
    })


# ══════════════════════════════════════════
# STORAGE INFO
# ══════════════════════════════════════════

@app.route('/storage-cleanup', methods=['POST'])
def storage_cleanup():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    db_atts = conn.execute(
        "select a.file_path from attachments a join records r on a.record_id=r.id "
        "where r.user_id=? and a.file_path is not null",
        (user_id,)
    ).fetchall()
    conn.close()
    db_paths = {row['file_path'] for row in db_atts}

    deleted_files   = 0
    deleted_folders = 0

    if os.path.exists(UPLOAD_FOLDER):
        for dirpath, dirnames, filenames in os.walk(UPLOAD_FOLDER):
            for fname in filenames:
                full_path = os.path.join(dirpath, fname)
                rel_path  = os.path.relpath(full_path, UPLOAD_FOLDER).replace(os.sep, '/')
                if rel_path not in db_paths:
                    try:
                        os.remove(full_path)
                        deleted_files += 1
                    except OSError:
                        pass

        protected = {'Unprocessed Imports', 'Backup'}
        for dirpath, dirnames, filenames in os.walk(UPLOAD_FOLDER, topdown=False):
            if os.path.abspath(dirpath) == os.path.abspath(UPLOAD_FOLDER):
                continue
            if os.path.basename(dirpath) in protected:
                continue
            try:
                os.rmdir(dirpath)
                deleted_folders += 1
            except OSError:
                pass

    return jsonify({'deleted_files': deleted_files, 'deleted_folders': deleted_folders})


@app.route('/storage-info', methods=['GET'])
def storage_info():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    uploads_size = 0
    file_count   = 0
    if os.path.exists(UPLOAD_FOLDER):
        for dirpath, dirnames, filenames in os.walk(UPLOAD_FOLDER):
            for fname in filenames:
                try:
                    uploads_size += os.path.getsize(os.path.join(dirpath, fname))
                    file_count   += 1
                except OSError:
                    pass

    db_size = 0
    if os.path.exists(DB_PATH):
        try:
            db_size = os.path.getsize(DB_PATH)
        except OSError:
            pass

    return jsonify({
        'uploads_size': uploads_size,
        'db_size':      db_size,
        'total_size':   uploads_size + db_size,
        'file_count':   file_count,
    })


def _drive_count_files(access_token, root_name, skip=None):
    if skip is None: skip = set()
    resp = http_requests.get(
        'https://www.googleapis.com/drive/v3/files',
        headers={'Authorization': f'Bearer {access_token}'},
        params={'q': f"name='{root_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
                'fields': 'files(id)'}
    ).json()
    files = resp.get('files', [])
    if not files:
        return 0
    return _drive_count_in_folder(access_token, files[0]['id'], skip)

def _drive_count_in_folder(access_token, folder_id, skip, depth=0):
    if depth > 6:
        return 0
    total = 0
    page_token = None
    while True:
        params = {
            'q': f"'{folder_id}' in parents and mimeType!='application/vnd.google-apps.folder' and trashed=false",
            'fields': 'nextPageToken,files(id)', 'pageSize': 1000,
        }
        if page_token:
            params['pageToken'] = page_token
        resp = http_requests.get(
            'https://www.googleapis.com/drive/v3/files',
            headers={'Authorization': f'Bearer {access_token}'},
            params=params
        ).json()
        total += len(resp.get('files', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    resp2 = http_requests.get(
        'https://www.googleapis.com/drive/v3/files',
        headers={'Authorization': f'Bearer {access_token}'},
        params={'q': f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
                'fields': 'files(id,name)', 'pageSize': 100}
    ).json()
    for sub in resp2.get('files', []):
        if sub.get('name') not in skip:
            total += _drive_count_in_folder(access_token, sub['id'], skip, depth + 1)
    return total


@app.route('/records-stats', methods=['GET'])
def records_stats():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    rec_total    = conn.execute("SELECT COUNT(*) FROM records WHERE user_id=?", (user_id,)).fetchone()[0]
    rec_active   = conn.execute("SELECT COUNT(*) FROM records WHERE user_id=? AND is_deleted=0 AND is_archived=0", (user_id,)).fetchone()[0]
    rec_archived = conn.execute("SELECT COUNT(*) FROM records WHERE user_id=? AND is_archived=1 AND is_deleted=0", (user_id,)).fetchone()[0]
    rec_deleted  = conn.execute("SELECT COUNT(*) FROM records WHERE user_id=? AND is_deleted=1", (user_id,)).fetchone()[0]
    att_total   = conn.execute("SELECT COUNT(*) FROM attachments a JOIN records r ON a.record_id=r.id WHERE r.user_id=?", (user_id,)).fetchone()[0]
    att_local   = conn.execute(
        "SELECT COUNT(*) FROM attachments a JOIN records r ON a.record_id=r.id "
        "WHERE r.user_id=? AND a.file_path IS NOT NULL",
        (user_id,)).fetchone()[0]
    att_drive   = conn.execute(
        "SELECT COUNT(*) FROM attachments a JOIN records r ON a.record_id=r.id "
        "WHERE r.user_id=? AND a.drive_id IS NOT NULL AND a.storage_type='drive'",
        (user_id,)).fetchone()[0]
    unprocessed = conn.execute("SELECT COUNT(*) FROM unprocessed_imports WHERE user_id=?", (user_id,)).fetchone()[0]
    conn.close()

    drive_real = None
    drive_error = None
    access_token = get_drive_token(user_id)
    if not access_token:
        drive_error = 'no_token'
    else:
        try:
            drive_real = _drive_count_files(access_token, DRIVE_ROOT, skip={'Backup'})
        except Exception as e:
            drive_error = str(e)

    return jsonify({
        'records':     {'total': rec_total, 'active': rec_active, 'archived': rec_archived, 'deleted': rec_deleted},
        'attachments': {'total': att_total, 'local': att_local, 'drive': drive_real, 'drive_error': drive_error, 'unprocessed': unprocessed},
    })


# ══════════════════════════════════════════
# DRIVE PICKER
# ══════════════════════════════════════════
@app.route('/drive/files', methods=['GET'])
def list_drive_files():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    access_token = get_drive_token(user_id)
    if not access_token:
        return jsonify({'error': 'no_drive_token'}), 403

    search = request.args.get('q', '').strip()
    q = "mimeType!='application/vnd.google-apps.folder' and trashed=false"
    if search:
        safe = search.replace("'", "\\'")
        q += f" and name contains '{safe}'"

    resp = http_requests.get(
        'https://www.googleapis.com/drive/v3/files',
        headers={'Authorization': f'Bearer {access_token}'},
        params={
            'q': q,
            'fields': 'files(id,name,mimeType)',
            'spaces': 'drive',
            'pageSize': 50,
            'orderBy': 'modifiedTime desc',
        }
    ).json()
    return jsonify(resp.get('files', []))


@app.route('/records/<record_id>/attach-from-drive', methods=['POST'])
def attach_from_drive(record_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    data = request.json or {}
    drive_id  = data.get('drive_id')
    file_name = data.get('file_name', 'file')
    mime_type = data.get('mime_type', 'application/octet-stream')

    if not drive_id:
        return jsonify({'error': 'drive_id required'}), 400

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

    record_date  = rec['date'] or datetime.utcnow().strftime('%Y-%m-%d')
    year         = record_date[:4]
    month        = record_date[5:7]
    raw_company  = rec['company_name'] or 'Unassigned'
    safe_company = re.sub(r'[^\w\s\-]', '', raw_company).strip().replace(' ', '_') or 'Unassigned'

    rel_folder = '/'.join([DRIVE_ROOT, year, month, safe_company])
    abs_folder = os.path.join(UPLOAD_FOLDER, DRIVE_ROOT, year, month, safe_company)
    os.makedirs(abs_folder, exist_ok=True)

    att_id      = str(uuid.uuid4())
    ext         = os.path.splitext(file_name)[1].lower()
    stored_name = att_id + ext
    file_path   = rel_folder + '/' + stored_name

    access_token = get_drive_token(user_id)
    storage = 'local'

    if access_token:
        try:
            file_bytes = drive_download_file(access_token, drive_id)
            with open(os.path.join(abs_folder, stored_name), 'wb') as f:
                f.write(file_bytes)
            storage = 'drive'
        except Exception as e:
            pass
            open(os.path.join(abs_folder, stored_name), 'wb').close()
    else:
        open(os.path.join(abs_folder, stored_name), 'wb').close()

    conn.execute(
        "insert into attachments (id, record_id, file_name, file_type, file_path, storage_type, drive_id) "
        "values (?,?,?,?,?,?,?)",
        (att_id, record_id, file_name, mime_type, file_path, storage, drive_id)
    )
    conn.commit()
    conn.close()

    return jsonify({
        'id': att_id, 'record_id': record_id,
        'file_name': file_name, 'file_type': mime_type,
        'storage_type': storage, 'drive_id': drive_id,
    }), 201


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
    print("─" * 40)
    app.run(host='0.0.0.0', port=5500, debug=False)
