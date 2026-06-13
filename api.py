from flask import Flask, request, jsonify, send_from_directory, session as flask_session, redirect
from flask_cors import CORS
from dotenv import load_dotenv
import requests as http_requests
import psycopg2
import psycopg2.extras
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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv()

app = Flask(__name__, static_folder='.')
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-prod')
CORS(app, supports_credentials=True)

os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # HTTP allowed in development

GOOGLE_CLIENT_ID     = os.environ.get('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
REDIRECT_URI         = os.environ.get('REDIRECT_URI', 'http://localhost:5500/auth/callback')

DATABASE_URL = os.environ.get('DATABASE_URL')

SMTP_HOST = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASS = os.environ.get('SMTP_PASS', '')
SMTP_FROM = os.environ.get('SMTP_FROM', SMTP_USER)

ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', '')


def send_verification_email(to_email, verify_url):
    if not SMTP_USER or not SMTP_PASS:
        print('[SMTP] credentials not configured')
        return False
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Підтвердження email — Reimbursement App'
        msg['From']    = SMTP_FROM
        msg['To']      = to_email
        html = f"""<div style="font-family:sans-serif;max-width:480px;margin:40px auto;padding:32px;
background:#16213e;border:1px solid #2d2d4e;border-radius:14px">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:28px">
    <div style="width:44px;height:44px;background:#6c63ff;border-radius:10px;
display:flex;align-items:center;justify-content:center;font-size:22px">💳</div>
    <div>
      <div style="color:#fff;font-size:17px;font-weight:600">Reimbursement App</div>
      <div style="color:#888;font-size:11px">Управління витратами</div>
    </div>
  </div>
  <p style="color:#ccc;font-size:14px;margin:0 0 8px">Привіт!</p>
  <p style="color:#ccc;font-size:14px;margin:0 0 24px">
    Натисни кнопку нижче щоб підтвердити свій email і активувати акаунт:
  </p>
  <a href="{verify_url}"
    style="display:inline-block;padding:12px 28px;background:#6c63ff;color:#fff;
border-radius:8px;text-decoration:none;font-size:14px;font-weight:600">
    Підтвердити email
  </a>
  <p style="color:#555;font-size:11px;margin-top:24px">
    Посилання дійсне 24 години.<br>
    Якщо ти не реєструвався — проігноруй цей лист.
  </p>
</div>"""
        msg.attach(MIMEText(html, 'html', 'utf-8'))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.ehlo()
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_FROM, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f'[SMTP] {e}')
        return False
DB_PATH = os.path.join('data', 'local.db')  # kept for backup/restore routes
UPLOAD_FOLDER = os.path.join('data', 'uploads')
DRIVE_ROOT = 'ReceiptsManager'
DRIVE_ENABLED = False  # disabled until Drive sync is rebuilt

# ══════════════════════════════════════════
# DATABASE INIT
# ══════════════════════════════════════════
class _PGConn:
    """Thin wrapper so conn.execute/fetchone/fetchall/commit/close work like SQLite."""
    def __init__(self):
        self._conn = psycopg2.connect(DATABASE_URL)

    def execute(self, sql, params=()):
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        return cur

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

def get_db():
    return _PGConn()

def init_db():
    # Tables are created via schema_pg.sql — here we only ensure defaults exist
    conn = get_db()
    existing = conn.execute("select id from users where email='admin@local.app'").fetchone()
    if not existing:
        pwd_hash = hashlib.sha256('admin123'.encode()).hexdigest()
        admin_id = str(uuid.uuid4())
        conn.execute(
            "insert into users (id, email, password_hash, full_name) values (%s,%s,%s,%s)",
            (admin_id, 'admin@local.app', pwd_hash, 'Admin')
        )
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
    user = conn.execute("select id from users where email=%s", (email,)).fetchone()
    if user:
        user_id = user['id']
        if refresh_token:
            conn.execute("update users set refresh_token=%s where id=%s", (refresh_token, user_id))
            conn.commit()
    else:
        user_id = str(uuid.uuid4())
        conn.execute(
            "insert into users (id, email, password_hash, full_name, refresh_token, email_verified) values (%s,%s,%s,%s,%s,TRUE)",
            (user_id, email, 'GOOGLE_AUTH', full_name, refresh_token)
        )
        conn.commit()
    conn.close()

    flask_session['user_id']   = user_id
    flask_session['email']     = email
    flask_session['full_name'] = full_name
    flask_session.permanent    = True

    return redirect('/')


def send_activation_email(to_email, full_name, org_name, activate_url):
    if not SMTP_USER or not SMTP_PASS:
        print('[SMTP] credentials not configured')
        return False
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'Запрошення в {org_name} — Reimbursement App' if org_name else 'Активація акаунту — Reimbursement App'
        msg['From']    = SMTP_FROM
        msg['To']      = to_email
        name_str = full_name or to_email
        html = f"""<div style="font-family:sans-serif;max-width:480px;margin:40px auto;padding:32px;
background:#16213e;border:1px solid #2d2d4e;border-radius:14px">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:28px">
    <div style="width:44px;height:44px;background:#6c63ff;border-radius:10px;
display:flex;align-items:center;justify-content:center;font-size:22px">💳</div>
    <div>
      <div style="color:#fff;font-size:17px;font-weight:600">Reimbursement App</div>
      <div style="color:#888;font-size:11px">Управління витратами</div>
    </div>
  </div>
  <p style="color:#ccc;font-size:14px;margin:0 0 8px">Привіт, {name_str}!</p>
  <p style="color:#ccc;font-size:14px;margin:0 0 24px">
    {f'Тебе запросили в організацію <strong style="color:#fff">{org_name}</strong>.<br>' if org_name else ''}
    Натисни кнопку нижче щоб встановити пароль і активувати акаунт:
  </p>
  <a href="{activate_url}"
    style="display:inline-block;padding:12px 28px;background:#6c63ff;color:#fff;
border-radius:8px;text-decoration:none;font-size:14px;font-weight:600">
    Встановити пароль
  </a>
  <p style="color:#555;font-size:11px;margin-top:24px">
    Посилання дійсне 48 годин.<br>
    Якщо ти не очікував цього листа — проігноруй його.
  </p>
</div>"""
        msg.attach(MIMEText(html, 'html', 'utf-8'))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.ehlo(); s.starttls(); s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_FROM, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f'[SMTP] {e}')
        return False


@app.route('/auth/register', methods=['POST'])
def auth_register():
    return jsonify({'error': 'registration_closed'}), 403
    data      = request.json or {}
    email     = (data.get('email') or '').strip().lower()
    password  = data.get('password') or ''
    full_name = (data.get('full_name') or '').strip()

    if not email or not password:
        return jsonify({'error': 'email_and_password_required'}), 400
    if len(password) < 6:
        return jsonify({'error': 'password_too_short'}), 400

    conn = get_db()
    existing = conn.execute("select id from users where email=%s", (email,)).fetchone()
    if existing:
        conn.close()
        return jsonify({'error': 'email_taken'}), 409

    user_id   = str(uuid.uuid4())
    pwd_hash  = hashlib.sha256(password.encode()).hexdigest()
    conn.execute(
        "insert into users (id, email, password_hash, full_name) values (%s,%s,%s,%s)",
        (user_id, email, pwd_hash, full_name)
    )
    token      = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + __import__('datetime').timedelta(hours=24)
    conn.execute(
        "INSERT INTO email_verifications (id, user_id, token, expires_at) VALUES (%s,%s,%s,%s)",
        (str(uuid.uuid4()), user_id, token, expires_at)
    )
    conn.commit()
    conn.close()

    verify_url = request.host_url.rstrip('/') + f'/auth/verify-email?token={token}'
    send_verification_email(email, verify_url)

    flask_session['user_id']   = user_id
    flask_session['email']     = email
    flask_session['full_name'] = full_name
    flask_session.permanent    = True
    return jsonify({'ok': True, 'verify_email': True})


@app.route('/auth/login', methods=['POST'])
def auth_login():
    data     = request.json or {}
    email    = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({'error': 'email_and_password_required'}), 400

    pwd_hash = hashlib.sha256(password.encode()).hexdigest()
    conn     = get_db()
    user     = conn.execute(
        "select id, full_name from users where email=%s and password_hash=%s",
        (email, pwd_hash)
    ).fetchone()
    conn.close()

    if not user:
        return jsonify({'error': 'invalid_credentials'}), 401

    flask_session['user_id']   = user['id']
    flask_session['email']     = email
    flask_session['full_name'] = user['full_name'] or ''
    flask_session.permanent    = True
    return jsonify({'ok': True})


@app.route('/auth/logout', methods=['POST'])
def logout():
    flask_session.clear()
    return jsonify({'ok': True})

@app.route('/auth/me', methods=['GET'])
def me():
    user_id = flask_session.get('user_id')
    if not user_id:
        return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    row  = conn.execute(
        "SELECT email_verified, is_superadmin, plan, is_suspended FROM users WHERE id=%s", (user_id,)
    ).fetchone()
    if row and row['is_suspended'] and not row['is_superadmin']:
        conn.close(); flask_session.clear()
        return jsonify({'error': 'user_suspended'}), 403
    notice = conn.execute(
        "SELECT id, org_name FROM org_deletion_notices WHERE user_id=%s ORDER BY created_at LIMIT 1",
        (user_id,)
    ).fetchone()
    if notice:
        conn.execute("DELETE FROM org_deletion_notices WHERE id=%s", (notice['id'],))
        conn.commit()
    needs_org_pick = False
    if not flask_session.get('active_org_id'):
        count = conn.execute(
            "SELECT COUNT(*) as c FROM org_members WHERE user_id=%s AND left_at IS NULL",
            (user_id,)
        ).fetchone()['c']
        needs_org_pick = count > 1
    conn.close()
    return jsonify({
        'id':               user_id,
        'email':            flask_session.get('email', ''),
        'full_name':        flask_session.get('full_name', ''),
        'email_verified':   bool(row['email_verified'])  if row else False,
        'is_superadmin':    bool(row['is_superadmin'])   if row else False,
        'plan':             (row['plan'] or 'free')       if row else 'free',
        'deletion_notice':  notice['org_name']            if notice else None,
        'needs_org_pick':   needs_org_pick,
    })


@app.route('/auth/verify-email', methods=['GET'])
def auth_verify_email():
    token = request.args.get('token', '').strip()
    if not token:
        return redirect('/?verify_error=1')
    conn = get_db()
    row  = conn.execute(
        "SELECT user_id FROM email_verifications WHERE token=%s AND expires_at > (now() AT TIME ZONE 'utc')",
        (token,)
    ).fetchone()
    if not row:
        conn.close()
        return redirect('/?verify_error=1')
    conn.execute("UPDATE users SET email_verified=TRUE WHERE id=%s", (row['user_id'],))
    conn.execute("DELETE FROM email_verifications WHERE token=%s", (token,))
    conn.commit()
    conn.close()
    return redirect('/?email_verified=1')


@app.route('/auth/resend-verification', methods=['POST'])
def auth_resend_verification():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    user = conn.execute("SELECT email, email_verified FROM users WHERE id=%s", (user_id,)).fetchone()
    if not user or user['email_verified']:
        conn.close()
        return jsonify({'error': 'already_verified'}), 400
    token      = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + __import__('datetime').timedelta(hours=24)
    conn.execute("DELETE FROM email_verifications WHERE user_id=%s", (user_id,))
    conn.execute(
        "INSERT INTO email_verifications (id, user_id, token, expires_at) VALUES (%s,%s,%s,%s)",
        (str(uuid.uuid4()), user_id, token, expires_at)
    )
    conn.commit()
    conn.close()
    verify_url = request.host_url.rstrip('/') + f'/auth/verify-email?token={token}'
    send_verification_email(user['email'], verify_url)
    return jsonify({'ok': True})


@app.route('/auth/activate', methods=['GET'])
def auth_activate_get():
    token = request.args.get('token', '').strip()
    if not token:
        return redirect('/?activate_error=1')
    return redirect(f'/?activate_token={token}')


@app.route('/auth/activate', methods=['POST'])
def auth_activate_post():
    data     = request.json or {}
    token    = (data.get('token') or '').strip()
    password = data.get('password') or ''
    if not token or len(password) < 6:
        return jsonify({'error': 'invalid_input'}), 400
    conn = get_db()
    row  = conn.execute(
        "SELECT ev.user_id, u.email, u.full_name "
        "FROM email_verifications ev JOIN users u ON ev.user_id=u.id "
        "WHERE ev.token=%s AND ev.expires_at > (now() AT TIME ZONE 'utc') AND u.password_hash='PENDING'",
        (token,)
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'invalid_or_expired_token'}), 400
    pwd_hash = hashlib.sha256(password.encode()).hexdigest()
    conn.execute(
        "UPDATE users SET password_hash=%s, email_verified=TRUE, registered_at=now() WHERE id=%s",
        (pwd_hash, row['user_id'])
    )
    conn.execute("DELETE FROM email_verifications WHERE token=%s", (token,))
    conn.commit()
    conn.close()
    flask_session['user_id']   = row['user_id']
    flask_session['email']     = row['email']
    flask_session['full_name'] = row['full_name']
    flask_session.permanent    = True
    return jsonify({'ok': True})

# ══════════════════════════════════════════
# SUPERADMIN API
# ══════════════════════════════════════════

def require_superadmin(request, conn):
    if not flask_session.get('admin_auth'):
        return None, (jsonify({'error': 'Unauthorized'}), 401)
    user_id = get_user_from_token(request)
    if not user_id:
        return None, (jsonify({'error': 'Unauthorized'}), 401)
    row = conn.execute("SELECT is_superadmin FROM users WHERE id=%s", (user_id,)).fetchone()
    if not row or not row['is_superadmin']:
        return None, (jsonify({'error': 'forbidden'}), 403)
    return user_id, None


@app.route('/superadmin/users', methods=['GET'])
def superadmin_list_users():
    conn = get_db()
    user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err
    rows = conn.execute("""
        SELECT u.id, u.email, u.full_name, u.email_verified, u.is_superadmin,
               u.plan, u.password_hash, u.created_at, u.registered_at, u.is_suspended,
               array_agg(DISTINCT o.name) FILTER (WHERE o.name IS NOT NULL) AS orgs
        FROM users u
        LEFT JOIN org_members m ON m.user_id = u.id AND m.left_at IS NULL
        LEFT JOIN organizations o ON o.id = m.org_id
        GROUP BY u.id, u.email, u.full_name, u.email_verified, u.is_superadmin,
                 u.plan, u.password_hash, u.created_at, u.registered_at, u.is_suspended
        ORDER BY u.created_at DESC
    """).fetchall()
    conn.close()
    result = []
    for r in rows:
        if r['password_hash'] == 'PENDING':
            status = 'pending'
        elif r['email_verified']:
            status = 'active'
        else:
            status = 'unverified'
        result.append({
            'id':           r['id'],
            'email':        r['email'],
            'full_name':    r['full_name'] or '',
            'status':       status,
            'is_superadmin': bool(r['is_superadmin']),
            'plan':         r['plan'] or 'free',
            'orgs':         r['orgs'] or [],
            'created_at':    r['created_at'].isoformat()    if r['created_at']    else None,
            'registered_at': r['registered_at'].isoformat() if r['registered_at'] else None,
            'is_suspended':  bool(r['is_suspended']),
        })
    return jsonify(result)


@app.route('/superadmin/users', methods=['POST'])
def superadmin_create_user():
    conn = get_db()
    user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err
    data      = request.json or {}
    email     = (data.get('email') or '').strip().lower()
    full_name = (data.get('full_name') or '').strip()
    mode      = data.get('mode')  # 'invite' or 'password'
    password  = data.get('password') or ''
    if not email:
        conn.close(); return jsonify({'error': 'email_required'}), 400
    if mode not in ('invite', 'password'):
        conn.close(); return jsonify({'error': 'invalid_mode'}), 400
    if mode == 'password' and len(password) < 6:
        conn.close(); return jsonify({'error': 'password_too_short'}), 400
    existing = conn.execute("SELECT id FROM users WHERE email=%s", (email,)).fetchone()
    if existing:
        conn.close(); return jsonify({'error': 'email_exists'}), 409
    new_id = str(uuid.uuid4())
    if mode == 'password':
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()
        conn.execute(
            "INSERT INTO users (id, email, password_hash, full_name, email_verified, registered_at) VALUES (%s,%s,%s,%s,TRUE,now())",
            (new_id, email, pwd_hash, full_name)
        )
        conn.commit(); conn.close()
        return jsonify({'ok': True, 'user_id': new_id})
    else:
        conn.execute(
            "INSERT INTO users (id, email, password_hash, full_name, email_verified) VALUES (%s,%s,'PENDING',%s,FALSE)",
            (new_id, email, full_name)
        )
        token      = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + __import__('datetime').timedelta(hours=48)
        conn.execute(
            "INSERT INTO email_verifications (id, user_id, token, expires_at) VALUES (%s,%s,%s,%s)",
            (str(uuid.uuid4()), new_id, token, expires_at)
        )
        conn.commit(); conn.close()
        activate_url = request.host_url.rstrip('/') + f'/auth/activate?token={token}'
        send_activation_email(email, full_name, None, activate_url)
        return jsonify({'ok': True, 'user_id': new_id})


@app.route('/superadmin/users/<target_user_id>/suspend', methods=['POST'])
def superadmin_suspend_user(target_user_id):
    conn = get_db()
    user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err
    target = conn.execute("SELECT is_superadmin FROM users WHERE id=%s", (target_user_id,)).fetchone()
    if target and target['is_superadmin']:
        conn.close(); return jsonify({'error': 'cannot_act_on_superadmin'}), 400
    conn.execute("UPDATE users SET is_suspended=TRUE WHERE id=%s", (target_user_id,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/superadmin/users/<target_user_id>/unsuspend', methods=['POST'])
def superadmin_unsuspend_user(target_user_id):
    conn = get_db()
    user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err
    conn.execute("UPDATE users SET is_suspended=FALSE WHERE id=%s", (target_user_id,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/superadmin/users/<target_user_id>', methods=['DELETE'])
def superadmin_delete_user(target_user_id):
    conn = get_db()
    user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err
    if target_user_id == user_id:
        conn.close(); return jsonify({'error': 'cannot_delete_self'}), 400
    target = conn.execute("SELECT is_superadmin FROM users WHERE id=%s", (target_user_id,)).fetchone()
    if target and target['is_superadmin']:
        conn.close(); return jsonify({'error': 'cannot_act_on_superadmin'}), 400
    owned_orgs = conn.execute("SELECT name FROM organizations WHERE owner_id=%s", (target_user_id,)).fetchall()
    if owned_orgs:
        conn.close()
        return jsonify({'error': 'is_org_owner', 'orgs': [o['name'] for o in owned_orgs]}), 409
    conn.execute("DELETE FROM return_events WHERE record_id IN (SELECT id FROM records WHERE user_id=%s)", (target_user_id,))
    conn.execute("DELETE FROM attachments  WHERE record_id IN (SELECT id FROM records WHERE user_id=%s)", (target_user_id,))
    conn.execute("DELETE FROM records WHERE user_id=%s", (target_user_id,))
    conn.execute("DELETE FROM org_deletion_notices WHERE user_id=%s", (target_user_id,))
    conn.execute("DELETE FROM email_verifications WHERE user_id=%s", (target_user_id,))
    conn.execute("DELETE FROM org_members WHERE user_id=%s", (target_user_id,))
    conn.execute("DELETE FROM users WHERE id=%s", (target_user_id,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/superadmin/orgs', methods=['GET'])
def superadmin_list_orgs():
    conn = get_db()
    user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err
    rows = conn.execute("""
        SELECT o.id, o.name, o.created_at, o.is_suspended, o.plan,
               u.email  AS owner_email,
               u.full_name AS owner_name,
               (SELECT COUNT(*) FROM org_members m
                WHERE m.org_id=o.id AND m.left_at IS NULL)          AS members_count,
               (SELECT COUNT(*) FROM records r
                WHERE r.org_id=o.id AND (r.is_deleted=0 OR r.is_deleted IS NULL)) AS records_count,
               (SELECT COUNT(*) FROM org_members m
                JOIN users pu ON m.user_id=pu.id
                WHERE m.org_id=o.id AND m.left_at IS NULL
                  AND pu.password_hash='PENDING')                    AS pending_count,
               (SELECT MAX(r.created_at) FROM records r
                WHERE r.org_id=o.id AND (r.is_deleted=0 OR r.is_deleted IS NULL)) AS last_activity
        FROM organizations o
        JOIN users u ON o.owner_id=u.id
        ORDER BY o.created_at DESC
    """).fetchall()
    conn.close()
    data_root = os.path.join(os.path.dirname(__file__), 'data')
    result = []
    for r in rows:
        d = dict(r)
        if d.get('created_at'):
            d['created_at'] = d['created_at'].isoformat()
        if d.get('last_activity'):
            d['last_activity'] = d['last_activity'].isoformat()
        org_dir = os.path.join(data_root, d['id'])
        size_bytes = 0
        if os.path.isdir(org_dir):
            for dirpath, _, filenames in os.walk(org_dir):
                for fname in filenames:
                    try:
                        size_bytes += os.path.getsize(os.path.join(dirpath, fname))
                    except OSError:
                        pass
        d['storage_mb'] = round(size_bytes / (1024 * 1024), 2)
        result.append(d)
    return jsonify(result)


@app.route('/superadmin/stats', methods=['GET'])
def superadmin_stats():
    conn = get_db()
    user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err

    total_orgs = conn.execute("SELECT COUNT(*) AS c FROM organizations").fetchone()['c']
    active_users = conn.execute(
        "SELECT COUNT(DISTINCT user_id) AS c FROM org_members WHERE left_at IS NULL"
    ).fetchone()['c']
    total_records = conn.execute(
        "SELECT COUNT(*) AS c FROM records WHERE is_deleted IS NULL OR is_deleted=0"
    ).fetchone()['c']
    conn.close()

    total_storage_mb = 0.0
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    if os.path.isdir(data_dir):
        for dirpath, dirnames, filenames in os.walk(data_dir):
            for fname in filenames:
                try:
                    total_storage_mb += os.path.getsize(os.path.join(dirpath, fname))
                except OSError:
                    pass
        total_storage_mb = round(total_storage_mb / (1024 * 1024), 2)

    return jsonify({
        'total_orgs': total_orgs,
        'active_users': active_users,
        'total_records': total_records,
        'total_storage_mb': total_storage_mb
    })


@app.route('/superadmin/orgs/<org_id_to_delete>', methods=['DELETE'])
def superadmin_delete_org(org_id_to_delete):
    conn = get_db()
    user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err

    org = conn.execute(
        "SELECT id, name FROM organizations WHERE id=%s", (org_id_to_delete,)
    ).fetchone()
    if not org:
        conn.close()
        return jsonify({'error': 'not_found'}), 404

    # 1. Notify active members
    members = conn.execute(
        "SELECT user_id FROM org_members WHERE org_id=%s AND left_at IS NULL",
        (org_id_to_delete,)
    ).fetchall()
    for m in members:
        conn.execute(
            "INSERT INTO org_deletion_notices (id, user_id, org_name) VALUES (%s,%s,%s)",
            (str(uuid.uuid4()), m['user_id'], org['name'])
        )

    # 2. Delete files from disk
    org_folder = os.path.join(UPLOAD_FOLDER, DRIVE_ROOT, org_id_to_delete)
    if os.path.exists(org_folder):
        try:
            shutil.rmtree(org_folder)
        except Exception as e:
            print(f'[delete_org] rmtree failed: {e}')

    # 3. Collect PENDING users (only in this org) before deleting members
    pending_users = conn.execute("""
        SELECT u.id FROM users u
        JOIN org_members m ON m.user_id = u.id
        WHERE m.org_id=%s AND u.password_hash='PENDING'
        AND NOT EXISTS (
            SELECT 1 FROM org_members m2
            WHERE m2.user_id=u.id AND m2.org_id<>%s AND m2.left_at IS NULL
        )
    """, (org_id_to_delete, org_id_to_delete)).fetchall()
    pending_ids = [r['id'] for r in pending_users]

    # 4. Clean up data tables (NO ACTION FKs must go first)
    conn.execute("DELETE FROM unprocessed_imports WHERE org_id=%s", (org_id_to_delete,))
    conn.execute("DELETE FROM return_events WHERE record_id IN (SELECT id FROM records WHERE org_id=%s)", (org_id_to_delete,))
    conn.execute("DELETE FROM attachments  WHERE record_id IN (SELECT id FROM records WHERE org_id=%s)", (org_id_to_delete,))
    conn.execute("DELETE FROM records             WHERE org_id=%s", (org_id_to_delete,))
    conn.execute("DELETE FROM payment_instruments WHERE org_id=%s", (org_id_to_delete,))
    conn.execute("DELETE FROM companies           WHERE org_id=%s", (org_id_to_delete,))

    # 5. Delete PENDING users and their verification tokens
    if pending_ids:
        placeholders = ','.join(['%s'] * len(pending_ids))
        conn.execute(f"DELETE FROM email_verifications WHERE user_id IN ({placeholders})", pending_ids)
        conn.execute(f"DELETE FROM users WHERE id IN ({placeholders})", pending_ids)

    # 6. Delete org (cascades: org_members, org_member_companies, org_invites)
    conn.execute("DELETE FROM organizations WHERE id=%s", (org_id_to_delete,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'deleted_org': dict(org)})


@app.route('/superadmin/orgs/<org_id_to_suspend>/suspend', methods=['POST'])
def superadmin_suspend_org(org_id_to_suspend):
    conn = get_db()
    user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err
    org = conn.execute("SELECT id FROM organizations WHERE id=%s", (org_id_to_suspend,)).fetchone()
    if not org: conn.close(); return jsonify({'error': 'not_found'}), 404
    conn.execute("UPDATE organizations SET is_suspended=TRUE WHERE id=%s", (org_id_to_suspend,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/superadmin/orgs/<org_id_to_suspend>/unsuspend', methods=['POST'])
def superadmin_unsuspend_org(org_id_to_suspend):
    conn = get_db()
    user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err
    org = conn.execute("SELECT id FROM organizations WHERE id=%s", (org_id_to_suspend,)).fetchone()
    if not org: conn.close(); return jsonify({'error': 'not_found'}), 404
    conn.execute("UPDATE organizations SET is_suspended=FALSE WHERE id=%s", (org_id_to_suspend,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})


@app.route('/superadmin/orgs/<org_id>/set-plan', methods=['POST'])
def superadmin_set_org_plan(org_id):
    conn = get_db()
    user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err
    data = request.json or {}
    plan = data.get('plan', 'free')
    if plan not in ('free', 'pro', 'ultimate', 'zero'):
        conn.close(); return jsonify({'error': 'invalid_plan'}), 400
    org = conn.execute("SELECT id FROM organizations WHERE id=%s", (org_id,)).fetchone()
    if not org: conn.close(); return jsonify({'error': 'not_found'}), 404
    conn.execute("UPDATE organizations SET plan=%s WHERE id=%s", (plan, org_id))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'plan': plan})


@app.route('/superadmin/orgs', methods=['POST'])
def superadmin_create_org():
    conn = get_db()
    user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err
    data       = request.json or {}
    org_name   = (data.get('org_name')    or '').strip()
    admin_email= (data.get('admin_email') or '').strip().lower()
    admin_name = (data.get('admin_name')  or '').strip()
    if not org_name or not admin_email:
        conn.close()
        return jsonify({'error': 'org_name_and_admin_email_required'}), 400

    # Org name must be unique
    existing_org = conn.execute(
        "SELECT id FROM organizations WHERE lower(name)=lower(%s)", (org_name,)
    ).fetchone()
    if existing_org:
        conn.close()
        return jsonify({'error': 'org_name_taken'}), 409

    # Create org
    import secrets as _sec
    org_id      = str(uuid.uuid4())
    invite_code = _sec.token_hex(4).upper()
    pwd_hash    = hashlib.sha256(invite_code.encode()).hexdigest()

    # Check if admin user already exists
    existing_user = conn.execute("SELECT id FROM users WHERE email=%s", (admin_email,)).fetchone()
    if existing_user:
        admin_id = existing_user['id']
        # Check not already in an org
        active_m = conn.execute(
            "SELECT id FROM org_members WHERE user_id=%s AND left_at IS NULL", (admin_id,)
        ).fetchone()
        if active_m:
            conn.close()
            return jsonify({'error': 'admin_already_in_org'}), 409
    else:
        admin_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO users (id, email, password_hash, full_name) VALUES (%s,%s,'PENDING',%s)",
            (admin_id, admin_email, admin_name)
        )

    conn.execute(
        "INSERT INTO organizations (id, name, invite_code, password_hash, owner_id) VALUES (%s,%s,%s,%s,%s)",
        (org_id, org_name, invite_code, pwd_hash, admin_id)
    )
    conn.execute(
        "INSERT INTO org_members (id, org_id, user_id, role) VALUES (%s,%s,%s,'admin')",
        (str(uuid.uuid4()), org_id, admin_id)
    )

    # Activation token (only for PENDING users)
    if not existing_user:
        token      = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + __import__('datetime').timedelta(hours=48)
        conn.execute("DELETE FROM email_verifications WHERE user_id=%s", (admin_id,))
        conn.execute(
            "INSERT INTO email_verifications (id, user_id, token, expires_at) VALUES (%s,%s,%s,%s)",
            (str(uuid.uuid4()), admin_id, token, expires_at)
        )
        conn.commit()
        conn.close()
        activate_url = request.host_url.rstrip('/') + f'/auth/activate?token={token}'
        send_activation_email(admin_email, admin_name, org_name, activate_url)
    else:
        conn.commit()
        conn.close()

    return jsonify({'ok': True, 'org_id': org_id, 'existing_user': bool(existing_user)})


# ══════════════════════════════════════════
# ORG API
# ══════════════════════════════════════════
@app.route('/org/me', methods=['GET'])
def org_me():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role = get_user_org(user_id, conn)
    if not org_id:
        conn.close()
        return jsonify({'error': 'no_org'}), 404
    row = conn.execute(
        "SELECT o.id, o.name, o.invite_code, o.owner_id, o.is_suspended, o.plan, o.settings, m.role "
        "FROM org_members m JOIN organizations o ON m.org_id=o.id "
        "WHERE m.user_id=%s AND m.org_id=%s AND m.left_at IS NULL",
        (user_id, org_id)
    ).fetchone()
    if not row: conn.close(); return jsonify({'error': 'no_org'}), 404
    if row['is_suspended']:
        sa_row = conn.execute("SELECT is_superadmin FROM users WHERE id=%s", (user_id,)).fetchone()
        if not (sa_row and sa_row['is_superadmin']):
            conn.close(); return jsonify({'error': 'org_suspended'}), 403
    conn.close()
    d = dict(row)
    d['is_owner'] = (d['owner_id'] == user_id)
    d['settings'] = d.get('settings') or {}
    return jsonify(d)


ORG_CURRENCIES = ('EUR', 'UAH', 'USD')

@app.route('/org/settings', methods=['PUT'])
def org_settings_update():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='admin')
    if err: conn.close(); return err

    data = request.json or {}
    currency = data.get('default_currency')
    if currency not in ORG_CURRENCIES:
        conn.close()
        return jsonify({'error': 'invalid_currency'}), 400

    conn.execute(
        "UPDATE organizations SET settings = settings || %s::jsonb WHERE id=%s",
        (psycopg2.extras.Json({'default_currency': currency}), org_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/org/usage', methods=['GET'])
def org_usage():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role = get_user_org(user_id, conn)
    if not org_id:
        conn.close()
        return jsonify({'error': 'no_org'}), 404
    org = conn.execute("SELECT plan FROM organizations WHERE id=%s", (org_id,)).fetchone()
    plan = (org['plan'] or 'free') if org else 'free'
    usage = get_org_usage(org_id, conn)
    conn.close()
    return jsonify({
        'plan': plan,
        'usage': usage,
        'limits': ORG_USAGE_LIMITS.get(plan, ORG_USAGE_LIMITS['free']),
    })


@app.route('/org/create', methods=['POST'])
def org_create():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    data = request.json or {}
    name = (data.get('name') or '').strip()
    if not name: return jsonify({'error': 'name_required'}), 400

    conn = get_db()
    if not check_org_limit(user_id, conn):
        conn.close()
        return jsonify({'error': 'org_limit_reached'}), 403

    import secrets as _secrets
    org_id      = str(uuid.uuid4())
    invite_code = _secrets.token_hex(4).upper()
    pwd_hash    = hashlib.sha256(invite_code.encode()).hexdigest()

    conn.execute(
        "INSERT INTO organizations (id, name, invite_code, password_hash, owner_id) VALUES (%s,%s,%s,%s,%s)",
        (org_id, name, invite_code, pwd_hash, user_id)
    )
    conn.execute(
        "INSERT INTO org_members (id, org_id, user_id, role) VALUES (%s,%s,%s,'admin')",
        (str(uuid.uuid4()), org_id, user_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'org_id': org_id, 'invite_code': invite_code})


@app.route('/org/invite/generate', methods=['POST'])
def org_invite_generate():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='admin')
    if err: conn.close(); return err

    import secrets as _secrets
    token      = _secrets.token_hex(16)
    expires_at = datetime.utcnow().replace(microsecond=0) + __import__('datetime').timedelta(minutes=10)

    # Delete previous invites for this org
    conn.execute("DELETE FROM org_invites WHERE org_id=%s", (org_id,))
    conn.execute(
        "INSERT INTO org_invites (id, org_id, token, expires_at, created_by) VALUES (%s,%s,%s,%s,%s)",
        (str(uuid.uuid4()), org_id, token, expires_at, user_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'token': token, 'expires_at': expires_at.isoformat()})


@app.route('/org/invite/current', methods=['GET'])
def org_invite_current():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='admin')
    if err: conn.close(); return err

    row = conn.execute(
        "SELECT token, expires_at FROM org_invites WHERE org_id=%s AND expires_at > (now() AT TIME ZONE 'utc') ORDER BY expires_at DESC LIMIT 1",
        (org_id,)
    ).fetchone()
    conn.close()
    if not row: return jsonify({'token': None})
    return jsonify({'token': row['token'], 'expires_at': row['expires_at'].isoformat()})


@app.route('/org/members', methods=['GET'])
def org_members():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='admin')
    if err: conn.close(); return err
    rows = conn.execute(
        "SELECT m.id as member_id, m.user_id, m.role, m.joined_at, m.left_at, "
        "u.email, u.full_name, (u.password_hash='PENDING') as is_pending "
        "FROM org_members m JOIN users u ON m.user_id=u.id "
        "WHERE m.org_id=%s ORDER BY m.left_at NULLS FIRST, m.joined_at",
        (org_id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/org/members/invite', methods=['POST'])
def org_member_invite():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    data      = request.json or {}
    email     = (data.get('email') or '').strip().lower()
    full_name = (data.get('full_name') or '').strip()
    role      = data.get('role', 'user')
    if not email:
        return jsonify({'error': 'email_required'}), 400
    if role not in ('manager', 'user'):
        return jsonify({'error': 'invalid_role'}), 400
    conn = get_db()
    org_id, admin_role, err = require_org(user_id, conn, min_role='admin')
    if err: conn.close(); return err
    if not check_free_limit(org_id, 'members', conn):
        conn.close()
        return jsonify({'error': 'limit_reached', 'resource': 'members', 'limit': get_org_limits(org_id, conn)['members']}), 403
    org      = conn.execute("SELECT name FROM organizations WHERE id=%s", (org_id,)).fetchone()
    org_name = org['name'] if org else ''
    existing = conn.execute("SELECT id, password_hash FROM users WHERE email=%s", (email,)).fetchone()
    if existing:
        new_user_id  = existing['id']
        # Check org limit for the invited user
        if not check_org_limit(new_user_id, conn):
            conn.close()
            return jsonify({'error': 'invitee_org_limit_reached'}), 403
        active_m = conn.execute(
            "SELECT id FROM org_members WHERE user_id=%s AND org_id=%s AND left_at IS NULL",
            (new_user_id, org_id)
        ).fetchone()
        if active_m:
            conn.close()
            return jsonify({'error': 'already_in_org'}), 409
        left_m = conn.execute(
            "SELECT id FROM org_members WHERE user_id=%s AND org_id=%s AND left_at IS NOT NULL",
            (new_user_id, org_id)
        ).fetchone()
        if left_m:
            conn.execute(
                "UPDATE org_members SET left_at=NULL, role=%s WHERE user_id=%s AND org_id=%s",
                (role, new_user_id, org_id)
            )
        else:
            conn.execute(
                "INSERT INTO org_members (id, org_id, user_id, role) VALUES (%s,%s,%s,%s)",
                (str(uuid.uuid4()), org_id, new_user_id, role)
            )
        conn.commit()
        conn.close()
        return jsonify({'ok': True, 'existing_user': True})
    else:
        new_user_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO users (id, email, password_hash, full_name) VALUES (%s,%s,'PENDING',%s)",
            (new_user_id, email, full_name)
        )
        conn.execute(
            "INSERT INTO org_members (id, org_id, user_id, role) VALUES (%s,%s,%s,%s)",
            (str(uuid.uuid4()), org_id, new_user_id, role)
        )
        token      = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + __import__('datetime').timedelta(hours=48)
        conn.execute("DELETE FROM email_verifications WHERE user_id=%s", (new_user_id,))
        conn.execute(
            "INSERT INTO email_verifications (id, user_id, token, expires_at) VALUES (%s,%s,%s,%s)",
            (str(uuid.uuid4()), new_user_id, token, expires_at)
        )
        conn.commit()
        conn.close()
        activate_url = request.host_url.rstrip('/') + f'/auth/activate?token={token}'
        send_activation_email(email, full_name, org_name, activate_url)
        return jsonify({'ok': True, 'existing_user': False})


@app.route('/org/members/<member_user_id>/resend-invite', methods=['POST'])
def org_member_resend_invite(member_user_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='admin')
    if err: conn.close(); return err
    org  = conn.execute("SELECT name FROM organizations WHERE id=%s", (org_id,)).fetchone()
    org_name = org['name'] if org else ''
    row  = conn.execute(
        "SELECT u.email, u.full_name FROM users u JOIN org_members m ON m.user_id=u.id "
        "WHERE u.id=%s AND u.password_hash='PENDING' AND m.org_id=%s",
        (member_user_id, org_id)
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'user_not_pending'}), 400
    token      = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + __import__('datetime').timedelta(hours=48)
    conn.execute("DELETE FROM email_verifications WHERE user_id=%s", (member_user_id,))
    conn.execute(
        "INSERT INTO email_verifications (id, user_id, token, expires_at) VALUES (%s,%s,%s,%s)",
        (str(uuid.uuid4()), member_user_id, token, expires_at)
    )
    conn.commit()
    conn.close()
    activate_url = request.host_url.rstrip('/') + f'/auth/activate?token={token}'
    send_activation_email(row['email'], row['full_name'], org_name, activate_url)
    return jsonify({'ok': True})


@app.route('/org/members/<member_user_id>/role', methods=['PUT'])
def org_member_set_role(member_user_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='admin')
    if err: conn.close(); return err
    if member_user_id == user_id:
        conn.close()
        return jsonify({'error': 'cannot_change_own_role'}), 400
    new_role = (request.json or {}).get('role')
    if new_role not in ('manager', 'user'):
        conn.close()
        return jsonify({'error': 'invalid_role'}), 400
    member = conn.execute(
        "SELECT id FROM org_members WHERE org_id=%s AND user_id=%s AND left_at IS NULL",
        (org_id, member_user_id)
    ).fetchone()
    if not member:
        conn.close()
        return jsonify({'error': 'not_found'}), 404
    conn.execute(
        "UPDATE org_members SET role=%s WHERE org_id=%s AND user_id=%s",
        (new_role, org_id, member_user_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/org/members/<member_user_id>', methods=['DELETE'])
def org_member_remove(member_user_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='admin')
    if err: conn.close(); return err
    if member_user_id == user_id:
        conn.close()
        return jsonify({'error': 'cannot_remove_self'}), 400
    conn.execute(
        "UPDATE org_members SET left_at=now() WHERE org_id=%s AND user_id=%s AND left_at IS NULL",
        (org_id, member_user_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/org/members/<member_user_id>/restore', methods=['PUT'])
def org_member_restore(member_user_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='admin')
    if err: conn.close(); return err
    conn.execute(
        "UPDATE org_members SET left_at=NULL WHERE org_id=%s AND user_id=%s",
        (org_id, member_user_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/org/members/<member_user_id>/permanent', methods=['DELETE'])
def org_member_delete_permanent(member_user_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='admin')
    if err: conn.close(); return err
    if member_user_id == user_id:
        conn.close()
        return jsonify({'error': 'cannot_remove_self'}), 400
    conn.execute("DELETE FROM org_member_companies WHERE user_id=%s AND org_id=%s", (member_user_id, org_id))
    conn.execute("DELETE FROM org_members WHERE org_id=%s AND user_id=%s", (org_id, member_user_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/org/members/<member_user_id>/companies', methods=['GET'])
def org_member_get_companies(member_user_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='admin')
    if err: conn.close(); return err
    rows = conn.execute(
        "SELECT company_id FROM org_member_companies WHERE user_id=%s AND org_id=%s",
        (member_user_id, org_id)
    ).fetchall()
    conn.close()
    return jsonify([r['company_id'] for r in rows])


@app.route('/org/members/<member_user_id>/companies/<company_id>', methods=['PUT'])
def org_member_grant_company(member_user_id, company_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='admin')
    if err: conn.close(); return err
    existing = conn.execute(
        "SELECT id FROM org_member_companies WHERE user_id=%s AND company_id=%s",
        (member_user_id, company_id)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO org_member_companies (id, org_id, user_id, company_id, granted_by) VALUES (%s,%s,%s,%s,%s)",
            (str(uuid.uuid4()), org_id, member_user_id, company_id, user_id)
        )
        conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/org/members/<member_user_id>/companies/<company_id>', methods=['DELETE'])
def org_member_revoke_company(member_user_id, company_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='admin')
    if err: conn.close(); return err
    conn.execute(
        "DELETE FROM org_member_companies WHERE user_id=%s AND company_id=%s AND org_id=%s",
        (member_user_id, company_id, org_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


def get_accessible_companies(user_id, org_id, role, conn):
    """For admin → None (no filter). For others → list of company_ids."""
    if role == 'admin':
        return None
    rows = conn.execute(
        "SELECT company_id FROM org_member_companies WHERE user_id=%s AND org_id=%s",
        (user_id, org_id)
    ).fetchall()
    return [r['company_id'] for r in rows]


@app.route('/org/join', methods=['POST'])
def org_join():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    data     = request.json or {}
    org_name = (data.get('org_name') or '').strip()
    token    = (data.get('token') or '').strip()
    if not org_name or not token:
        return jsonify({'error': 'org_name_and_token_required'}), 400

    conn = get_db()
    if not check_org_limit(user_id, conn):
        conn.close()
        return jsonify({'error': 'org_limit_reached'}), 403

    invite = conn.execute(
        "SELECT i.org_id FROM org_invites i "
        "JOIN organizations o ON i.org_id=o.id "
        "WHERE i.token=%s AND i.expires_at > (now() AT TIME ZONE 'utc') AND lower(o.name)=lower(%s)",
        (token, org_name)
    ).fetchone()
    if not invite:
        conn.close()
        return jsonify({'error': 'invalid_token_or_name'}), 401

    prev = conn.execute(
        "SELECT id FROM org_members WHERE user_id=%s AND org_id=%s AND left_at IS NOT NULL",
        (user_id, invite['org_id'])
    ).fetchone()
    if prev:
        conn.execute(
            "UPDATE org_members SET left_at=NULL, role='user' WHERE id=%s",
            (prev['id'],)
        )
    else:
        conn.execute(
            "INSERT INTO org_members (id, org_id, user_id, role) VALUES (%s,%s,%s,'user')",
            (str(uuid.uuid4()), invite['org_id'], user_id)
        )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/org/list', methods=['GET'])
def org_list():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    rows = conn.execute(
        "SELECT o.id, o.name, o.owner_id, m.role, m.joined_at "
        "FROM org_members m JOIN organizations o ON m.org_id=o.id "
        "WHERE m.user_id=%s AND m.left_at IS NULL ORDER BY m.joined_at",
        (user_id,)
    ).fetchall()
    conn.close()
    active_org_id = flask_session.get('active_org_id')
    result = []
    for r in rows:
        d = dict(r)
        d['is_owner']  = (d['owner_id'] == user_id)
        d['is_active'] = (d['id'] == active_org_id)
        if d.get('joined_at'):
            d['joined_at'] = d['joined_at'].isoformat()
        result.append(d)
    # Mark first as active if nothing selected
    if result and not any(r['is_active'] for r in result):
        result[0]['is_active'] = True
    return jsonify(result)


@app.route('/org/switch', methods=['POST'])
def org_switch():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    org_id = (request.json or {}).get('org_id', '').strip()
    if not org_id:
        return jsonify({'error': 'org_id_required'}), 400
    conn = get_db()
    member = conn.execute(
        "SELECT id FROM org_members WHERE user_id=%s AND org_id=%s AND left_at IS NULL",
        (user_id, org_id)
    ).fetchone()
    conn.close()
    if not member:
        return jsonify({'error': 'not_member'}), 403
    flask_session['active_org_id'] = org_id
    return jsonify({'ok': True})


@app.route('/org/delete', methods=['DELETE'])
def org_delete_own():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role = get_user_org(user_id, conn)
    if not org_id:
        conn.close()
        return jsonify({'error': 'no_org'}), 404
    org = conn.execute(
        "SELECT id, name, owner_id FROM organizations WHERE id=%s", (org_id,)
    ).fetchone()
    if not org or org['owner_id'] != user_id:
        conn.close()
        return jsonify({'error': 'not_owner'}), 403
    org_name = org['name']

    # Notify active members (except owner)
    members = conn.execute(
        "SELECT user_id FROM org_members WHERE org_id=%s AND user_id<>%s AND left_at IS NULL",
        (org_id, user_id)
    ).fetchall()
    for m in members:
        conn.execute(
            "INSERT INTO org_deletion_notices (id, user_id, org_name) VALUES (%s,%s,%s)",
            (str(uuid.uuid4()), m['user_id'], org_name)
        )

    # Delete files from disk
    org_folder = os.path.join(UPLOAD_FOLDER, DRIVE_ROOT, org_id)
    if os.path.exists(org_folder):
        try:
            shutil.rmtree(org_folder)
        except Exception as e:
            print(f'[delete_org] {e}')

    # Cascade delete data
    conn.execute("DELETE FROM unprocessed_imports WHERE org_id=%s", (org_id,))
    conn.execute("DELETE FROM return_events WHERE record_id IN (SELECT id FROM records WHERE org_id=%s)", (org_id,))
    conn.execute("DELETE FROM attachments  WHERE record_id IN (SELECT id FROM records WHERE org_id=%s)", (org_id,))
    conn.execute("DELETE FROM records             WHERE org_id=%s", (org_id,))
    conn.execute("DELETE FROM payment_instruments WHERE org_id=%s", (org_id,))
    conn.execute("DELETE FROM companies           WHERE org_id=%s", (org_id,))

    # Delete PENDING users of this org without other orgs
    pending = conn.execute("""
        SELECT u.id FROM users u
        JOIN org_members m ON m.user_id=u.id
        WHERE m.org_id=%s AND u.password_hash='PENDING'
        AND NOT EXISTS (
            SELECT 1 FROM org_members m2
            WHERE m2.user_id=u.id AND m2.org_id<>%s AND m2.left_at IS NULL
        )
    """, (org_id, org_id)).fetchall()
    if pending:
        ph = ','.join(['%s'] * len(pending))
        pids = [r['id'] for r in pending]
        conn.execute(f"DELETE FROM email_verifications WHERE user_id IN ({ph})", pids)
        conn.execute(f"DELETE FROM users WHERE id IN ({ph})", pids)

    conn.execute("DELETE FROM organizations WHERE id=%s", (org_id,))
    conn.commit()
    flask_session.pop('active_org_id', None)
    conn.close()
    return jsonify({'ok': True})


@app.route('/org/leave', methods=['POST'])
def org_leave():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn)
    if err: conn.close(); return err
    if role == 'admin':
        conn.close()
        return jsonify({'error': 'admin_cannot_leave'}), 403
    conn.execute(
        "UPDATE org_members SET left_at=now() WHERE user_id=%s AND org_id=%s AND left_at IS NULL",
        (user_id, org_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


# ══════════════════════════════════════════
# ORG HELPERS
# ══════════════════════════════════════════

# Скільки org може мати юзер (узгоджено 13.06.2026, без терміну дії)
USER_ORG_LIMITS = {'free': 1, 'pro': 3, 'ultimate': 10, 'zero': None}


def check_org_limit(user_id, conn):
    """Returns True if user can join/create more orgs."""
    row = conn.execute(
        "SELECT is_superadmin, plan FROM users WHERE id=%s", (user_id,)
    ).fetchone()
    if not row or row['is_superadmin']:
        return True
    limit = USER_ORG_LIMITS.get(row['plan'] or 'free', USER_ORG_LIMITS['free'])
    if limit is None:
        return True
    count = conn.execute(
        "SELECT COUNT(*) as c FROM org_members WHERE user_id=%s AND left_at IS NULL",
        (user_id,)
    ).fetchone()['c']
    return count < limit


# Ліміти ресурсів всередині org за планом (узгоджено 13.06.2026, без терміну дії)
ORG_USAGE_LIMITS = {
    'free':     {'members': 9,  'records': 100,  'companies': 5,  'storage_mb': 300},
    'pro':      {'members': 24, 'records': 500,  'companies': 20, 'storage_mb': 1024},
    'ultimate': {'members': 99, 'records': 1000, 'companies': 50, 'storage_mb': 5120},
    'zero':     None,
}

def get_org_usage(org_id, conn):
    """Return current usage counts for an org."""
    members   = conn.execute(
        "SELECT COUNT(*) as c FROM org_members WHERE org_id=%s AND left_at IS NULL", (org_id,)
    ).fetchone()['c']
    records   = conn.execute(
        "SELECT COUNT(*) as c FROM records WHERE org_id=%s AND (is_deleted IS NULL OR is_deleted=0)", (org_id,)
    ).fetchone()['c']
    companies = conn.execute(
        "SELECT COUNT(*) as c FROM companies WHERE org_id=%s AND (is_active IS NULL OR is_active=1)", (org_id,)
    ).fetchone()['c']
    return {'members': members, 'records': records, 'companies': companies}

def get_org_limits(org_id, conn):
    """Return the usage-limits dict for an org's plan, or None if unlimited (zero plan)."""
    org = conn.execute("SELECT plan FROM organizations WHERE id=%s", (org_id,)).fetchone()
    plan = (org['plan'] or 'free') if org else 'free'
    return ORG_USAGE_LIMITS.get(plan, ORG_USAGE_LIMITS['free'])

def check_free_limit(org_id, resource, conn):
    """Returns True if org can add more of 'resource'. Always True for unlimited (zero) plan."""
    limits = get_org_limits(org_id, conn)
    if limits is None:
        return True
    usage = get_org_usage(org_id, conn)
    return usage[resource] < limits[resource]


def get_user_org(user_id, conn=None):
    """Return (org_id, role) for active org, or (None, None) if not in any org.
    Uses active_org_id from session; falls back to first available org."""
    close = conn is None
    if close:
        conn = get_db()

    active_org_id = flask_session.get('active_org_id')
    if active_org_id:
        row = conn.execute(
            "SELECT m.org_id, m.role FROM org_members m "
            "WHERE m.user_id=%s AND m.org_id=%s AND m.left_at IS NULL",
            (user_id, active_org_id)
        ).fetchone()
        if row:
            if close: conn.close()
            return row['org_id'], row['role']
        flask_session.pop('active_org_id', None)

    row = conn.execute(
        "SELECT m.org_id, m.role FROM org_members m "
        "WHERE m.user_id=%s AND m.left_at IS NULL ORDER BY m.joined_at LIMIT 1",
        (user_id,)
    ).fetchone()
    if close: conn.close()
    if not row:
        return None, None
    flask_session['active_org_id'] = row['org_id']
    return row['org_id'], row['role']


def require_org(user_id, conn, min_role='user'):
    """Return (org_id, role, error_response).
    error_response is None if access granted, or a Flask response to return immediately."""
    org_id, role = get_user_org(user_id, conn)
    if not org_id:
        return None, None, (jsonify({'error': 'no_org'}), 403)
    sa_row = conn.execute("SELECT is_superadmin FROM users WHERE id=%s", (user_id,)).fetchone()
    is_sa = sa_row and sa_row['is_superadmin']
    if not is_sa:
        suspended = conn.execute(
            "SELECT is_suspended FROM organizations WHERE id=%s", (org_id,)
        ).fetchone()
        if suspended and suspended['is_suspended']:
            return org_id, role, (jsonify({'error': 'org_suspended'}), 403)
    order = {'user': 0, 'manager': 1, 'admin': 2}
    if order.get(role, -1) < order.get(min_role, 0):
        return org_id, role, (jsonify({'error': 'forbidden'}), 403)
    return org_id, role, None

# ══════════════════════════════════════════
# COMPANIES
# ══════════════════════════════════════════
@app.route('/companies', methods=['GET'])
def get_companies():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn)
    if err: conn.close(); return err
    accessible = get_accessible_companies(user_id, org_id, role, conn)
    if accessible is None:
        rows = conn.execute(
            "select * from companies where org_id=%s and (is_deleted=0 or is_deleted is null) order by sort_order, name",
            (org_id,)
        ).fetchall()
    elif not accessible:
        rows = []
    else:
        placeholders = ','.join(['%s'] * len(accessible))
        rows = conn.execute(
            f"select * from companies where org_id=%s and id IN ({placeholders}) and (is_deleted=0 or is_deleted is null) order by sort_order, name",
            [org_id] + accessible
        ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/companies', methods=['POST'])
def create_company():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='manager')
    if err: conn.close(); return err
    if not check_free_limit(org_id, 'companies', conn):
        conn.close()
        return jsonify({'error': 'limit_reached', 'resource': 'companies', 'limit': get_org_limits(org_id, conn)['companies']}), 403
    data = request.json
    company_id = str(uuid.uuid4())
    conn.execute(
        "insert into companies (id, user_id, org_id, name, is_shared, is_active, sort_order) values (%s,%s,%s,%s,%s,1,%s)",
        (company_id, user_id, org_id, data['name'], 1 if data.get('is_shared') else 0, data.get('sort_order', 0))
    )
    conn.commit()
    row = conn.execute("select * from companies where id=%s", (company_id,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201

@app.route('/companies/<company_id>', methods=['PUT'])
def update_company(company_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='manager')
    if err: conn.close(); return err
    data = request.json

    old_row = conn.execute(
        "select name from companies where id=%s and org_id=%s", (company_id, org_id)
    ).fetchone()
    if not old_row:
        conn.close()
        return jsonify({'error': 'not_found'}), 404

    fields = []
    values = []
    for key in ['name', 'is_shared', 'is_active', 'sort_order']:
        if key in data:
            fields.append(f"{key}=%s")
            values.append(1 if data[key] is True else (0 if data[key] is False else data[key]))
    values.extend([company_id, org_id])
    conn.execute(f"update companies set {', '.join(fields)} where id=%s AND org_id=%s", values)
    conn.commit()

    if old_row and 'name' in data and data['name'] != old_row['name']:
        old_safe = re.sub(r'[^\w\s\-]', '', old_row['name']).strip().replace(' ', '_') or 'Unassigned'
        new_safe = re.sub(r'[^\w\s\-]', '', data['name']).strip().replace(' ', '_') or 'Unassigned'

        if old_safe != new_safe:
            atts = conn.execute(
                "select a.id, a.file_path, a.drive_id from attachments a "
                "join records r on a.record_id=r.id "
                "where r.company_id=%s and r.org_id=%s and a.file_path is not null",
                (company_id, org_id)
            ).fetchall()

            old_dirs = set()
            for att in atts:
                parts = att['file_path'].replace('\\', '/').split('/')
                if len(parts) >= 5:
                    old_dirs.add('/'.join(parts[:5]))

            for old_dir in old_dirs:
                dir_parts = old_dir.split('/')
                new_dir = '/'.join(dir_parts[:4] + [new_safe])
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
                if len(parts) >= 5 and parts[4] == old_safe:
                    parts[4] = new_safe
                    conn.execute("update attachments set file_path=%s where id=%s",
                                 ('/'.join(parts), att['id']))
            conn.commit()

    conn.close()
    return jsonify({'ok': True})

@app.route('/companies/<company_id>', methods=['DELETE'])
def delete_company(company_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='manager')
    if err: conn.close(); return err
    exists = conn.execute(
        "select id from companies where id=%s and org_id=%s and (is_deleted=0 or is_deleted is null)",
        (company_id, org_id)
    ).fetchone()
    if not exists:
        conn.close()
        return jsonify({'error': 'not_found'}), 404
    conn.execute(
        "update companies set is_deleted=1, deleted_at=%s where id=%s and org_id=%s",
        (datetime.utcnow().isoformat(), company_id, org_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/companies/trash', methods=['GET'])
def get_companies_trash():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn)
    if err: conn.close(); return err
    rows = conn.execute(
        "select * from companies where org_id=%s and is_deleted=1 order by deleted_at desc",
        (org_id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/companies/<company_id>/restore', methods=['POST'])
def restore_company(company_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='manager')
    if err: conn.close(); return err
    conn.execute(
        "update companies set is_deleted=0, deleted_at=null where id=%s and org_id=%s",
        (company_id, org_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/companies/<company_id>/permanent', methods=['DELETE'])
def permanent_delete_company(company_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='manager')
    if err: conn.close(); return err
    exists = conn.execute(
        "select id from companies where id=%s and org_id=%s", (company_id, org_id)
    ).fetchone()
    if not exists:
        conn.close()
        return jsonify({'error': 'not_found'}), 404
    conn.execute("delete from org_member_companies where company_id=%s and org_id=%s", (company_id, org_id))
    conn.execute("delete from companies where id=%s and org_id=%s", (company_id, org_id))
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
    org_id, role, err = require_org(user_id, conn)
    if err: conn.close(); return err
    rows = conn.execute(
        "select * from payment_instruments where org_id=%s and (is_deleted=0 or is_deleted is null) order by sort_order, name",
        (org_id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/instruments', methods=['POST'])
def create_instrument():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='manager')
    if err: conn.close(); return err
    data = request.json
    inst_id = str(uuid.uuid4())
    conn.execute(
        "insert into payment_instruments (id, user_id, org_id, name, type, is_active, sort_order) values (%s,%s,%s,%s,%s,1,%s)",
        (inst_id, user_id, org_id, data['name'], data['type'], data.get('sort_order', 0))
    )
    conn.commit()
    row = conn.execute("select * from payment_instruments where id=%s", (inst_id,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201

@app.route('/instruments/<inst_id>', methods=['PUT'])
def update_instrument(inst_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='manager')
    if err: conn.close(); return err
    exists = conn.execute(
        "select id from payment_instruments where id=%s and org_id=%s", (inst_id, org_id)
    ).fetchone()
    if not exists:
        conn.close()
        return jsonify({'error': 'not_found'}), 404
    data = request.json
    fields = []
    values = []
    for key in ['name', 'type', 'is_active', 'sort_order']:
        if key in data:
            fields.append(f"{key}=%s")
            values.append(1 if data[key] is True else (0 if data[key] is False else data[key]))
    values.extend([inst_id, org_id])
    conn.execute(f"update payment_instruments set {', '.join(fields)} where id=%s AND org_id=%s", values)
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/instruments/<inst_id>', methods=['DELETE'])
def delete_instrument(inst_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='manager')
    if err: conn.close(); return err
    conn.execute(
        "update payment_instruments set is_deleted=1, deleted_at=%s where id=%s and org_id=%s",
        (datetime.utcnow().isoformat(), inst_id, org_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/instruments/trash', methods=['GET'])
def get_instruments_trash():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn)
    if err: conn.close(); return err
    rows = conn.execute(
        "select * from payment_instruments where org_id=%s and is_deleted=1 order by deleted_at desc",
        (org_id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/instruments/<inst_id>/restore', methods=['POST'])
def restore_instrument(inst_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='manager')
    if err: conn.close(); return err
    conn.execute(
        "update payment_instruments set is_deleted=0, deleted_at=null where id=%s and org_id=%s",
        (inst_id, org_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/instruments/<inst_id>/permanent', methods=['DELETE'])
def permanent_delete_instrument(inst_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='manager')
    if err: conn.close(); return err
    conn.execute("delete from payment_instruments where id=%s and org_id=%s", (inst_id, org_id))
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
    org_id, role, err = require_org(user_id, conn)
    if err: conn.close(); return err

    accessible = get_accessible_companies(user_id, org_id, role, conn)

    if accessible is not None and not accessible:
        conn.close()
        return jsonify([])

    query = '''
        select r.*, c.name as company_name, p.name as card_name
        from records r
        left join companies c on r.company_id = c.id
        left join payment_instruments p on r.card_id = p.id
        where r.org_id=%s
    '''
    params = [org_id]

    if accessible is not None:
        placeholders = ','.join(['%s'] * len(accessible))
        query += f" and r.company_id IN ({placeholders})"
        params += accessible

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
            "select * from return_events where record_id=%s order by date",
            (d['id'],)
        ).fetchall()
        atts = conn.execute(
            "select * from attachments where record_id=%s",
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
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='manager')
    if err: conn.close(); return err
    if not check_free_limit(org_id, 'records', conn):
        conn.close()
        return jsonify({'error': 'limit_reached', 'resource': 'records', 'limit': get_org_limits(org_id, conn)['records']}), 403

    data = request.json
    record_id = str(uuid.uuid4())
    org_row = conn.execute("SELECT settings FROM organizations WHERE id=%s", (org_id,)).fetchone()
    default_currency = (org_row['settings'] or {}).get('default_currency', 'EUR') if org_row else 'EUR'
    conn.execute('''
        insert into records
        (id, user_id, org_id, title, note, date, amount, currency, pay_type, pay_method,
         card_id, company_id, status, to_return, returned, remainder)
        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ''', (
        record_id, user_id, org_id,
        data['title'], data.get('note', ''),
        data['date'], data['amount'],
        data.get('currency', default_currency),
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
        where r.id=%s
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
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='manager')
    if err: conn.close(); return err

    data = request.json

    # Snapshot before update to detect date/company changes
    old = conn.execute(
        "select r.date, r.company_id, c.name as company_name "
        "from records r left join companies c on r.company_id=c.id "
        "where r.id=%s and r.org_id=%s",
        (record_id, org_id)
    ).fetchone()
    if not old:
        conn.close()
        return jsonify({'error': 'not_found'}), 404

    fields = []
    values = []
    allowed = ['title', 'note', 'date', 'amount', 'pay_type', 'pay_method',
               'card_id', 'company_id', 'status', 'previous_status', 'to_return', 'returned',
               'remainder', 'is_archived', 'is_deleted', 'deleted_at']
    for key in allowed:
        if key in data:
            fields.append(f"{key}=%s")
            val = data[key]
            if isinstance(val, bool):
                val = 1 if val else 0
            values.append(val)
    values.extend([record_id, org_id])
    conn.execute(f"update records set {', '.join(fields)} where id=%s AND org_id=%s", values)
    conn.commit()

    # Move files if date or company changed
    if old:
        new_date       = data.get('date',       old['date'])
        new_company_id = data.get('company_id', old['company_id'])
        date_changed    = 'date'       in data and data['date']       != old['date']
        company_changed = 'company_id' in data and data['company_id'] != old['company_id']

        if (date_changed or company_changed) and new_date:
            new_company_row = conn.execute(
                "select name from companies where id=%s", (new_company_id,)
            ).fetchone() if new_company_id else None
            new_company_name = (new_company_row['name'] if new_company_row else None) or 'Unassigned'
            new_safe = re.sub(r'[^\w\s\-]', '', new_company_name).strip().replace(' ', '_') or 'Unassigned'
            new_year  = new_date[:4]
            new_month = new_date[5:7]
            new_folder = '/'.join([DRIVE_ROOT, org_id, new_year, new_month, new_safe])

            atts = conn.execute(
                "select * from attachments where record_id=%s and file_path is not null",
                (record_id,)
            ).fetchall()

            access_token = None
            if DRIVE_ENABLED and any(a['drive_id'] for a in atts):
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
                conn.execute("update attachments set file_path=%s where id=%s", (new_path, att['id']))

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
    org_id, role, err = require_org(user_id, conn, min_role='manager')
    if err: conn.close(); return err

    exists = conn.execute(
        "select id from records where id=%s and org_id=%s and (is_deleted=0 or is_deleted is null)",
        (record_id, org_id)
    ).fetchone()
    if not exists:
        conn.close()
        return jsonify({'error': 'not_found'}), 404

    atts = conn.execute(
        "select a.* from attachments a join records r on a.record_id=r.id "
        "where a.record_id=%s and r.org_id=%s",
        (record_id, org_id)
    ).fetchall()

    for att in atts:
        if att['file_path']:
            try:
                os.remove(os.path.join(UPLOAD_FOLDER, att['file_path'].replace('/', os.sep)))
            except OSError:
                pass

    conn.execute("delete from records where id=%s and org_id=%s", (record_id, org_id))
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
        "insert into return_events (id, record_id, amount, date, method) values (%s,%s,%s,%s,%s)",
        (event_id, record_id, data['amount'], data['date'], data.get('method'))
    )

    # Recalculate totals
    events = conn.execute(
        "select sum(amount) as total from return_events where record_id=%s",
        (record_id,)
    ).fetchone()
    total_returned = events['total'] or 0

    record = conn.execute("select amount from records where id=%s", (record_id,)).fetchone()
    if record:
        remainder = max(0, record['amount'] - total_returned)
        if total_returned <= 0:
            status = 'waiting'
        elif total_returned < record['amount']:
            status = 'partial'
        else:
            status = 'done'
        conn.execute(
            "update records set returned=%s, remainder=%s, status=%s where id=%s",
            (total_returned, remainder, status, record_id)
        )

    conn.commit()
    row = conn.execute("select * from return_events where id=%s", (event_id,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201

@app.route('/returns/<event_id>', methods=['DELETE'])
def delete_return(event_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    event = conn.execute("select * from return_events where id=%s", (event_id,)).fetchone()
    if event:
        record_id = event['record_id']
        conn.execute("delete from return_events where id=%s", (event_id,))

        events = conn.execute(
            "select sum(amount) as total from return_events where record_id=%s",
            (record_id,)
        ).fetchone()
        total_returned = events['total'] or 0

        record = conn.execute("select amount from records where id=%s", (record_id,)).fetchone()
        if record:
            remainder = max(0, record['amount'] - total_returned)
            if total_returned <= 0:
                status = 'waiting'
            elif total_returned < record['amount']:
                status = 'partial'
            else:
                status = 'done'
            conn.execute(
                "update records set returned=%s, remainder=%s, status=%s where id=%s",
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
    org_id, role, err = require_org(user_id, conn, min_role='manager')
    if err: conn.close(); return err
    rec = conn.execute(
        "select r.date, c.name as company_name from records r "
        "left join companies c on r.company_id=c.id "
        "where r.id=%s and r.org_id=%s",
        (record_id, org_id)
    ).fetchone()
    if not rec:
        conn.close()
        return jsonify({'error': 'Not found'}), 404

    # Build folder: ReceiptsManager/org_id/YYYY/MM/CompanyName
    record_date = rec['date'] or datetime.utcnow().strftime('%Y-%m-%d')
    year  = record_date[:4]
    month = record_date[5:7]
    raw_company = rec['company_name'] or 'Unassigned'
    safe_company = re.sub(r'[^\w\s\-]', '', raw_company).strip().replace(' ', '_') or 'Unassigned'

    rel_folder = '/'.join([DRIVE_ROOT, org_id, year, month, safe_company])
    abs_folder = os.path.join(UPLOAD_FOLDER, DRIVE_ROOT, org_id, year, month, safe_company)
    os.makedirs(abs_folder, exist_ok=True)

    att_id = str(uuid.uuid4())
    orig_name = file.filename
    ext = os.path.splitext(orig_name)[1].lower()
    stored_name = att_id + ext
    file_path = rel_folder + '/' + stored_name      # stored with forward slashes
    file.save(os.path.join(abs_folder, stored_name))

    file_type = file.content_type or 'application/octet-stream'

    drive_id = None
    if DRIVE_ENABLED:
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
        "insert into attachments (id, record_id, file_name, file_type, file_path, storage_type, drive_id) values (%s,%s,%s,%s,%s,%s,%s)",
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
    org_id, role, err = require_org(user_id, conn)
    if err: conn.close(); return err
    att = conn.execute(
        "select a.* from attachments a join records r on a.record_id=r.id where a.id=%s and r.org_id=%s",
        (att_id, org_id)
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
    org_id, role, err = require_org(user_id, conn, min_role='manager')
    if err: conn.close(); return err
    att = conn.execute(
        "select a.* from attachments a join records r on a.record_id=r.id where a.id=%s and r.org_id=%s",
        (att_id, org_id)
    ).fetchone()
    if not att:
        conn.close()
        return jsonify({'error': 'Not found'}), 404

    drive_warning = None
    if DRIVE_ENABLED and att['drive_id']:
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

    conn.execute("delete from attachments where id=%s", (att_id,))
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
    row = conn.execute("select refresh_token from users where id=%s", (user_id,)).fetchone()
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
        'https://www.googleapis.com/upload/drive/v3/files%suploadType=multipart',
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
    if not DRIVE_ENABLED: return jsonify({'error': 'drive_disabled'}), 503

    conn = get_db()
    all_atts = conn.execute(
        "select a.id, a.file_name, a.file_path, a.drive_id, a.storage_type, "
        "r.is_deleted, r.is_archived "
        "from attachments a join records r on a.record_id=r.id "
        "where r.user_id=%s",
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
    if not DRIVE_ENABLED: return jsonify({'error': 'drive_disabled'}), 503

    if not get_drive_token(user_id):
        return jsonify({'error': 'no_drive_token'}), 403

    conn = get_db()
    to_upload_rows = conn.execute(
        "select a.file_name from attachments a join records r on a.record_id=r.id "
        "where r.user_id=%s and r.is_deleted=0 and a.file_path is not null "
        "and (a.drive_id is null or a.storage_type='local')",
        (user_id,)
    ).fetchall()
    conn.close()

    return jsonify({'to_upload': [r['file_name'] for r in to_upload_rows]})


@app.route('/sync', methods=['POST'])
def sync_drive():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    if not DRIVE_ENABLED: return jsonify({'error': 'drive_disabled'}), 503

    access_token = get_drive_token(user_id)
    if not access_token:
        return jsonify({'ok': False, 'message': 'no_drive_token'})

    conn = get_db()
    uploaded = 0

    # ── Push: local → Drive ──
    unsynced = conn.execute(
        "select a.* from attachments a join records r on a.record_id=r.id "
        "where r.user_id=%s and r.is_deleted=0 and a.file_path is not null "
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
                conn.execute("update attachments set drive_id=%s, storage_type='drive' where id=%s", (drive_id, att['id']))
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
    if not DRIVE_ENABLED: return jsonify({'error': 'drive_disabled'}), 503

    access_token = get_drive_token(user_id)
    if not access_token:
        return jsonify({'ok': False, 'message': 'no_drive_token'})

    conn = get_db()
    atts = conn.execute(
        "select a.id, a.drive_id from attachments a join records r on a.record_id=r.id "
        "where r.user_id=%s and a.drive_id is not null",
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
                    "update attachments set drive_id=null, storage_type='local' where id=%s",
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
    if not DRIVE_ENABLED: return jsonify({'error': 'drive_disabled'}), 503

    access_token = get_drive_token(user_id)
    if not access_token:
        return jsonify({'ok': False, 'message': 'no_drive_token'})

    conn = get_db()
    known_ids = {r['drive_id'] for r in conn.execute(
        "select a.drive_id from attachments a join records r on a.record_id=r.id "
        "where r.user_id=%s and a.drive_id is not null", (user_id,)
    ).fetchall()}
    known_ids |= {r['drive_id'] for r in conn.execute(
        "select drive_id from unprocessed_imports where user_id=%s", (user_id,)
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
    if not DRIVE_ENABLED: return jsonify({'error': 'drive_disabled'}), 503

    access_token = get_drive_token(user_id)
    if not access_token:
        return jsonify({'ok': False, 'message': 'no_drive_token'})

    conn = get_db()
    known_ids = {r['drive_id'] for r in conn.execute(
        "select a.drive_id from attachments a join records r on a.record_id=r.id "
        "where r.user_id=%s and a.drive_id is not null", (user_id,)
    ).fetchall()}
    known_ids |= {r['drive_id'] for r in conn.execute(
        "select drive_id from unprocessed_imports where user_id=%s", (user_id,)
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
                    "insert into unprocessed_imports (id, user_id, drive_id, file_name, mime_type, drive_folder) values (%s,%s,%s,%s,%s,%s)",
                    (str(uuid.uuid4()), user_id, f['id'], f['name'], f.get('mimeType', ''), f.get('folder_path', ''))
                )
                imported += 1

        # Remove stale unprocessed entries whose file no longer exists on Drive
        existing = conn.execute(
            "select id, drive_id from unprocessed_imports where user_id=%s", (user_id,)
        ).fetchall()
        for row in existing:
            if row['drive_id'] not in drive_ids_on_drive:
                conn.execute("delete from unprocessed_imports where id=%s", (row['id'],))
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
    org_id, role, err = require_org(user_id, conn)
    if err: conn.close(); return err
    att_rows = conn.execute('''
        select
            a.id, a.file_name, a.file_type, a.file_path, a.drive_id,
            a.storage_type, a.created_at,
            r.id as record_id,
            r.title as record_title,
            r.date as record_date,
            c.name as company_name,
            p.name as card_name,
            'assigned' as source
        from attachments a
        join records r on a.record_id = r.id
        left join companies c on r.company_id = c.id
        left join payment_instruments p on r.card_id = p.id
        where r.org_id = %s and r.is_deleted = 0 and a.file_path is not null
        order by r.date desc, a.created_at desc
    ''', (org_id,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in att_rows])

@app.route('/unprocessed', methods=['GET'])
def get_unprocessed():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    if not DRIVE_ENABLED: return jsonify([])
    conn = get_db()
    rows = conn.execute(
        "select * from unprocessed_imports where user_id=%s order by synced_at desc",
        (user_id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/unprocessed/<imp_id>/assign', methods=['POST'])
def assign_unprocessed(imp_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    if not DRIVE_ENABLED: return jsonify({'error': 'drive_disabled'}), 503

    data = request.json or {}
    record_id = data.get('record_id')
    if not record_id:
        return jsonify({'error': 'record_id required'}), 400

    conn = get_db()
    exists = conn.execute(
        "select id from unprocessed_imports where id=%s and user_id=%s", (imp_id, user_id)
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
    if not DRIVE_ENABLED: return jsonify({'error': 'drive_disabled'}), 503

    data = request.json or {}
    conn = get_db()
    imp = conn.execute(
        "select * from unprocessed_imports where id=%s and user_id=%s", (imp_id, user_id)
    ).fetchone()
    if not imp:
        conn.close()
        return jsonify({'error': 'Not found'}), 404

    record_id = str(uuid.uuid4())
    conn.execute('''
        insert into records
        (id, user_id, title, note, date, amount, currency, pay_type, pay_method,
         card_id, company_id, status, to_return, returned, remainder)
        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
        "select * from unprocessed_imports where id=%s and user_id=%s", (imp_id, user_id)
    ).fetchone()
    if not imp:
        conn.close()
        return

    rec = conn.execute(
        "select r.date, r.org_id, c.name as company_name from records r "
        "left join companies c on r.company_id=c.id where r.id=%s and r.user_id=%s",
        (record_id, user_id)
    ).fetchone()
    if not rec:
        conn.close()
        return

    record_date = rec['date'] or datetime.utcnow().strftime('%Y-%m-%d')
    year  = record_date[:4]
    month = record_date[5:7]
    rec_org_id   = rec['org_id'] or 'unknown'
    raw_company  = rec['company_name'] or 'Unassigned'
    safe_company = re.sub(r'[^\w\s\-]', '', raw_company).strip().replace(' ', '_') or 'Unassigned'

    rel_folder = '/'.join([DRIVE_ROOT, rec_org_id, year, month, safe_company])
    abs_folder = os.path.join(UPLOAD_FOLDER, DRIVE_ROOT, rec_org_id, year, month, safe_company)
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
        "insert into attachments (id, record_id, file_name, file_type, file_path, storage_type, drive_id) values (%s,%s,%s,%s,%s,%s,%s)",
        (att_id, record_id, orig_name, mime_type, file_path, 'local', None)
    )
    conn.execute("delete from unprocessed_imports where id=%s", (imp_id,))
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
    if not DRIVE_ENABLED: return jsonify({'error': 'drive_disabled'}), 503

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
    if not DRIVE_ENABLED: return jsonify({'error': 'drive_disabled'}), 503

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
    if not DRIVE_ENABLED: return jsonify({'error': 'drive_disabled'}), 503

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
        "select email, full_name, refresh_token from users where id=%s", (user_id,)
    ).fetchone()
    conn.close()
    if not row: return jsonify({'error': 'Not found'}), 404

    return jsonify({
        'email':        row['email'] or '',
        'full_name':    row['full_name'] or '',
        'drive_connected': DRIVE_ENABLED and bool(row['refresh_token']),
    })


# ══════════════════════════════════════════
# STORAGE INFO
# ══════════════════════════════════════════

@app.route('/storage-cleanup', methods=['POST'])
def storage_cleanup():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='admin')
    if err: conn.close(); return err
    db_atts = conn.execute(
        "select a.file_path from attachments a join records r on a.record_id=r.id "
        "where r.org_id=%s and a.file_path is not null",
        (org_id,)
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
    org_id, role, err = require_org(user_id, conn)
    if err: conn.close(); return err

    rec_total    = conn.execute("SELECT COUNT(*) FROM records WHERE org_id=%s", (org_id,)).fetchone()['count']
    rec_active   = conn.execute("SELECT COUNT(*) FROM records WHERE org_id=%s AND is_deleted=0 AND is_archived=0", (org_id,)).fetchone()['count']
    rec_archived = conn.execute("SELECT COUNT(*) FROM records WHERE org_id=%s AND is_archived=1 AND is_deleted=0", (org_id,)).fetchone()['count']
    rec_deleted  = conn.execute("SELECT COUNT(*) FROM records WHERE org_id=%s AND is_deleted=1", (org_id,)).fetchone()['count']
    att_total   = conn.execute("SELECT COUNT(*) FROM attachments a JOIN records r ON a.record_id=r.id WHERE r.org_id=%s", (org_id,)).fetchone()['count']
    att_local   = conn.execute(
        "SELECT COUNT(*) FROM attachments a JOIN records r ON a.record_id=r.id "
        "WHERE r.org_id=%s AND a.file_path IS NOT NULL",
        (org_id,)).fetchone()['count']
    att_drive   = conn.execute(
        "SELECT COUNT(*) FROM attachments a JOIN records r ON a.record_id=r.id "
        "WHERE r.org_id=%s AND a.drive_id IS NOT NULL AND a.storage_type='drive'",
        (org_id,)).fetchone()['count']
    unprocessed = conn.execute("SELECT COUNT(*) FROM unprocessed_imports WHERE user_id=%s", (user_id,)).fetchone()['count']
    conn.close()

    drive_real = None
    drive_error = None
    if not DRIVE_ENABLED:
        drive_error = 'drive_disabled'
    else:
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
    if not DRIVE_ENABLED: return jsonify({'error': 'drive_disabled'}), 503

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
    if not DRIVE_ENABLED: return jsonify({'error': 'drive_disabled'}), 503

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
        "where r.id=%s and r.user_id=%s",
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
        "values (%s,%s,%s,%s,%s,%s,%s)",
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
# ADMIN PANEL
# ══════════════════════════════════════════
@app.route('/admin')
def admin_panel():
    return send_from_directory('.', 'admin.html')

@app.route('/admin/login', methods=['POST'])
def admin_login():
    data = request.json or {}
    token = data.get('token', '')
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        return jsonify({'error': 'invalid_token'}), 401
    user_id = flask_session.get('user_id')
    if not user_id:
        return jsonify({'error': 'login_required'}), 401
    conn = get_db()
    row = conn.execute("SELECT is_superadmin FROM users WHERE id=%s", (user_id,)).fetchone()
    conn.close()
    if not row or not row['is_superadmin']:
        return jsonify({'error': 'forbidden'}), 403
    flask_session['admin_auth'] = True
    return jsonify({'ok': True})

@app.route('/admin/logout', methods=['POST'])
def admin_logout():
    flask_session.pop('admin_auth', None)
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
    print("─" * 40)
    app.run(host='0.0.0.0', port=5500, debug=False)
