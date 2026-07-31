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


@app.after_request
def set_security_headers(response):
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    response.headers['Server'] = 'reimbursement-app'
    return response


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
PAYMENT_PROVIDER = None  # 'liqpay' | 'stripe' | None — підключити пізніше

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

def validate_password(password):
    if len(password) < 8: return 'password_too_short'
    if re.search(r'[^\x00-\x7F]', password): return 'password_too_short'
    if not re.search(r'[A-Z]', password): return 'password_too_short'
    if not re.search(r'[a-z]', password): return 'password_too_short'
    if not re.search(r'[0-9]', password): return 'password_too_short'
    return None

def init_db():
    # Tables are created via schema_pg.sql — here we only ensure defaults exist
    conn = get_db()
    existing = conn.execute("select id from users where email='admin@local.app'").fetchone()
    if not existing:
        pwd_hash = hashlib.sha256('admin123'.encode()).hexdigest()
        admin_id = str(uuid.uuid4())
        conn.execute(
            "insert into users (id, email, password_hash, full_name, is_superadmin, email_verified, registered_at) "
            "values (%s,%s,%s,%s,TRUE,TRUE,now())",
            (admin_id, 'admin@local.app', pwd_hash, 'Admin')
        )
        conn.commit()
    conn.close()
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    print("Database initialized")

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
        'scope=openid%20email%20profile',
        f'state={state}',
        f'code_challenge={challenge}',
        'code_challenge_method=S256',
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
    token_data   = token_resp.json()
    access_token = token_data.get('access_token')

    user_info = http_requests.get(
        'https://www.googleapis.com/oauth2/v2/userinfo',
        headers={'Authorization': f'Bearer {access_token}'}
    ).json()

    email     = user_info.get('email', '')
    full_name = user_info.get('name', '')

    conn = get_db()
    user = conn.execute(
        "select id, password_hash, is_suspended, is_superadmin from users where email=%s", (email,)
    ).fetchone()
    if not user:
        # Реєстрація закрита — Google-логін не створює нових юзерів, тільки існуючих
        conn.close()
        return redirect('/?google_error=registration_closed')
    if user['is_suspended'] and not user['is_superadmin']:
        conn.close()
        return redirect('/?google_error=user_suspended')

    user_id = user['id']
    if user['password_hash'] == 'PENDING':
        # Перший Google-логін для запрошеного юзера = активація (мірор /auth/activate)
        conn.execute("update users set email_verified=TRUE, registered_at=now() where id=%s", (user_id,))
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


def send_reset_password_email(to_email, full_name, reset_url):
    if not SMTP_USER or not SMTP_PASS:
        print('[SMTP] credentials not configured')
        return False
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Скидання паролю — Reimbursement App'
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
    Ми отримали запит на скидання паролю для вашого акаунту.<br>
    Натисни кнопку нижче щоб встановити новий пароль:
  </p>
  <a href="{reset_url}"
    style="display:inline-block;padding:12px 28px;background:#6c63ff;color:#fff;
border-radius:8px;text-decoration:none;font-size:14px;font-weight:600">
    Встановити новий пароль
  </a>
  <p style="color:#555;font-size:11px;margin-top:24px">
    Посилання дійсне 1 годину.<br>
    Якщо ти не запитував скидання паролю — проігноруй цей лист. Твій пароль залишається незмінним.
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


def send_google_login_hint_email(to_email, full_name):
    if not SMTP_USER or not SMTP_PASS:
        return False
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Відновлення паролю — Reimbursement App'
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
    Ваш акаунт прив'язаний до Google — пароль не встановлено.<br>
    Для входу використовуйте кнопку <strong style="color:#fff">«Увійти через Google»</strong>.
  </p>
  <p style="color:#555;font-size:11px;margin-top:24px">
    Якщо ти не запитував скидання паролю — проігноруй цей лист.
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


# ── First-run setup ──
@app.route('/setup', methods=['POST'])
def setup_first_superadmin():
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) AS c FROM users WHERE is_superadmin=TRUE").fetchone()['c']
    if count > 0:
        conn.close()
        return jsonify({'error': 'already_setup'}), 403
    data      = request.json or {}
    email     = (data.get('email') or '').strip().lower()
    password  = data.get('password') or ''
    full_name = (data.get('full_name') or '').strip()
    if not email or validate_password(password):
        conn.close()
        return jsonify({'error': 'invalid_input'}), 400
    existing = conn.execute("SELECT id FROM users WHERE email=%s", (email,)).fetchone()
    if existing:
        # Upgrade existing user to superadmin
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()
        conn.execute(
            "UPDATE users SET is_superadmin=TRUE, password_hash=%s, email_verified=TRUE, registered_at=now() WHERE id=%s",
            (pwd_hash, existing['id'])
        )
        conn.commit(); conn.close()
        return jsonify({'ok': True})
    new_id   = str(uuid.uuid4())
    pwd_hash = hashlib.sha256(password.encode()).hexdigest()
    conn.execute(
        "INSERT INTO users (id, email, password_hash, full_name, email_verified, is_superadmin, registered_at) "
        "VALUES (%s,%s,%s,%s,TRUE,TRUE,now())",
        (new_id, email, pwd_hash, full_name or email)
    )
    conn.commit(); conn.close()
    return jsonify({'ok': True})


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
        "SELECT email_verified, is_superadmin, plan, is_suspended, password_hash FROM users WHERE id=%s", (user_id,)
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
        'has_password':     (row['password_hash'] != 'GOOGLE_AUTH') if row else True,
        'plan':             (row['plan'] or 'free')       if row else 'free',
        'org_limit':        None if (row and row['is_superadmin']) else USER_ORG_LIMITS.get((row['plan'] or 'free') if row else 'free', USER_ORG_LIMITS['free']),
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
    if not token or validate_password(password):
        return jsonify({'error': 'invalid_input'}), 400
    conn = get_db()
    row  = conn.execute(
        "SELECT ev.user_id, ev.token_type, u.email, u.full_name, u.password_hash "
        "FROM email_verifications ev JOIN users u ON ev.user_id=u.id "
        "WHERE ev.token=%s AND ev.expires_at > (now() AT TIME ZONE 'utc')",
        (token,)
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'invalid_or_expired_token'}), 400
    token_type = row['token_type'] or 'activation'
    # Activation tokens only work for PENDING users
    if token_type == 'activation' and row['password_hash'] != 'PENDING':
        conn.close()
        return jsonify({'error': 'invalid_or_expired_token'}), 400
    pwd_hash = hashlib.sha256(password.encode()).hexdigest()
    if token_type == 'activation':
        conn.execute(
            "UPDATE users SET password_hash=%s, email_verified=TRUE, registered_at=now() WHERE id=%s",
            (pwd_hash, row['user_id'])
        )
    else:
        # Reset token — just update password, keep email_verified/registered_at
        conn.execute("UPDATE users SET password_hash=%s WHERE id=%s", (pwd_hash, row['user_id']))
    conn.execute("DELETE FROM email_verifications WHERE token=%s", (token,))
    conn.commit()
    conn.close()
    flask_session['user_id']   = row['user_id']
    flask_session['email']     = row['email']
    flask_session['full_name'] = row['full_name']
    flask_session.permanent    = True
    return jsonify({'ok': True})


@app.route('/auth/forgot-password', methods=['POST'])
def auth_forgot_password():
    data  = request.json or {}
    email = (data.get('email') or '').strip().lower()
    if not email:
        return jsonify({'error': 'email_required'}), 400
    conn = get_db()
    user = conn.execute(
        "SELECT id, full_name, password_hash FROM users WHERE email=%s", (email,)
    ).fetchone()
    if not user:
        conn.close()
        return jsonify({'ok': True})  # Don't reveal if email exists
    if user['password_hash'] == 'GOOGLE_AUTH':
        conn.close()
        send_google_login_hint_email(email, user['full_name'])
        return jsonify({'ok': True})
    if user['password_hash'] == 'PENDING':
        # Resend activation link
        conn.execute("DELETE FROM email_verifications WHERE user_id=%s", (user['id'],))
        token      = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + __import__('datetime').timedelta(hours=48)
        conn.execute(
            "INSERT INTO email_verifications (id, user_id, token, expires_at, token_type) VALUES (%s,%s,%s,%s,'activation')",
            (str(uuid.uuid4()), user['id'], token, expires_at)
        )
        conn.commit(); conn.close()
        activate_url = request.host_url.rstrip('/') + f'/auth/activate?token={token}'
        send_activation_email(email, user['full_name'], None, activate_url)
        return jsonify({'ok': True})
    # Normal user — generate reset token
    conn.execute("DELETE FROM email_verifications WHERE user_id=%s AND token_type='reset'", (user['id'],))
    token      = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + __import__('datetime').timedelta(hours=1)
    conn.execute(
        "INSERT INTO email_verifications (id, user_id, token, expires_at, token_type) VALUES (%s,%s,%s,%s,'reset')",
        (str(uuid.uuid4()), user['id'], token, expires_at)
    )
    conn.commit(); conn.close()
    reset_url = request.host_url.rstrip('/') + f'/auth/activate?token={token}'
    send_reset_password_email(email, user['full_name'], reset_url)
    return jsonify({'ok': True})


@app.route('/auth/change-password', methods=['PUT'])
def auth_change_password():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    data        = request.json or {}
    old_password = data.get('old_password') or ''
    new_password = data.get('new_password') or ''
    if validate_password(new_password):
        return jsonify({'error': 'password_too_short'}), 400
    conn = get_db()
    user = conn.execute("SELECT password_hash FROM users WHERE id=%s", (user_id,)).fetchone()
    if not user:
        conn.close(); return jsonify({'error': 'not_found'}), 404
    if user['password_hash'] == 'GOOGLE_AUTH':
        conn.close(); return jsonify({'error': 'google_auth_no_password'}), 400
    if user['password_hash'] == 'PENDING':
        conn.close(); return jsonify({'error': 'account_not_activated'}), 400
    # Verify old password
    old_hash = hashlib.sha256(old_password.encode()).hexdigest()
    if user['password_hash'] != old_hash:
        conn.close(); return jsonify({'error': 'invalid_old_password'}), 403
    new_hash = hashlib.sha256(new_password.encode()).hexdigest()
    conn.execute("UPDATE users SET password_hash=%s WHERE id=%s", (new_hash, user_id))
    conn.commit(); conn.close()
    flask_session.clear()  # Force logout
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
    if mode == 'password' and validate_password(password):
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


@app.route('/superadmin/users/<target_user_id>/details', methods=['GET'])
def superadmin_user_details(target_user_id):
    conn = get_db()
    user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err
    user = conn.execute(
        "SELECT id, email, full_name, password_hash, email_verified, is_superadmin, plan, is_suspended, registered_at "
        "FROM users WHERE id=%s", (target_user_id,)
    ).fetchone()
    if not user:
        conn.close(); return jsonify({'error': 'not_found'}), 404
    orgs = conn.execute(
        "SELECT o.id, o.name, m.role FROM org_members m "
        "JOIN organizations o ON o.id=m.org_id "
        "WHERE m.user_id=%s AND m.left_at IS NULL ORDER BY m.joined_at",
        (target_user_id,)
    ).fetchall()
    conn.close()
    if user['password_hash'] == 'PENDING':
        status = 'pending'
    elif user['email_verified']:
        status = 'active'
    else:
        status = 'unverified'
    return jsonify({
        'id':           user['id'],
        'email':        user['email'],
        'full_name':    user['full_name'] or '',
        'status':       status,
        'is_superadmin': bool(user['is_superadmin']),
        'plan':         user['plan'] or 'free',
        'is_suspended': bool(user['is_suspended']),
        'has_password': user['password_hash'] not in ('GOOGLE_AUTH', 'PENDING'),
        'registered_at': user['registered_at'].isoformat() if user['registered_at'] else None,
        'orgs': [{'id': o['id'], 'name': o['name'], 'role': o['role']} for o in orgs],
    })


@app.route('/superadmin/users/<target_user_id>/set-superadmin', methods=['PUT'])
def superadmin_set_superadmin(target_user_id):
    conn = get_db()
    user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err
    if target_user_id == user_id:
        conn.close(); return jsonify({'error': 'cannot_change_own_sa'}), 400
    data = request.json or {}
    is_sa = bool(data.get('is_superadmin', False))
    target = conn.execute("SELECT id FROM users WHERE id=%s", (target_user_id,)).fetchone()
    if not target:
        conn.close(); return jsonify({'error': 'not_found'}), 404
    conn.execute("UPDATE users SET is_superadmin=%s WHERE id=%s", (is_sa, target_user_id))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'is_superadmin': is_sa})


@app.route('/superadmin/users/<target_user_id>/name', methods=['PUT'])
def superadmin_set_user_name(target_user_id):
    conn = get_db()
    user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err
    full_name = ((request.json or {}).get('full_name') or '').strip()
    if not full_name:
        conn.close()
        return jsonify({'error': 'full_name_required'}), 400
    target = conn.execute("SELECT id FROM users WHERE id=%s", (target_user_id,)).fetchone()
    if not target:
        conn.close(); return jsonify({'error': 'not_found'}), 404
    conn.execute("UPDATE users SET full_name=%s WHERE id=%s", (full_name, target_user_id))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'full_name': full_name})


@app.route('/superadmin/users/<target_user_id>/reset-password', methods=['POST'])
def superadmin_reset_user_password(target_user_id):
    conn = get_db()
    user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err
    target = conn.execute(
        "SELECT id, email, full_name, password_hash FROM users WHERE id=%s", (target_user_id,)
    ).fetchone()
    if not target:
        conn.close(); return jsonify({'error': 'not_found'}), 404
    if target['password_hash'] == 'GOOGLE_AUTH':
        conn.close(); return jsonify({'error': 'google_auth_no_password'}), 400
    # Generate reset token (1-time, 48h)
    conn.execute("DELETE FROM email_verifications WHERE user_id=%s AND token_type='reset'", (target_user_id,))
    token      = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + __import__('datetime').timedelta(hours=48)
    conn.execute(
        "INSERT INTO email_verifications (id, user_id, token, expires_at, token_type) VALUES (%s,%s,%s,%s,'reset')",
        (str(uuid.uuid4()), target_user_id, token, expires_at)
    )
    conn.commit(); conn.close()
    reset_url = request.host_url.rstrip('/') + f'/auth/activate?token={token}'
    send_reset_password_email(target['email'], target['full_name'], reset_url)
    return jsonify({'ok': True})


@app.route('/superadmin/users/<target_user_id>/set-plan', methods=['POST'])
def superadmin_set_user_plan(target_user_id):
    conn = get_db()
    user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err
    data = request.json or {}
    plan = data.get('plan', 'free')
    if plan not in ('free', 'pro', 'ultimate', 'zero'):
        conn.close(); return jsonify({'error': 'invalid_plan'}), 400
    target = conn.execute("SELECT id FROM users WHERE id=%s", (target_user_id,)).fetchone()
    if not target: conn.close(); return jsonify({'error': 'not_found'}), 404
    conn.execute("UPDATE users SET plan=%s WHERE id=%s", (plan, target_user_id))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'plan': plan})


@app.route('/superadmin/users/<target_user_id>/suspend', methods=['POST'])
def superadmin_suspend_user(target_user_id):
    conn = get_db()
    user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err
    if target_user_id == user_id:
        conn.close(); return jsonify({'error': 'cannot_suspend_self'}), 400
    target = conn.execute("SELECT is_superadmin FROM users WHERE id=%s", (target_user_id,)).fetchone()
    if not target:
        conn.close(); return jsonify({'error': 'not_found'}), 404
    # Suspending another SA requires password confirmation
    if target['is_superadmin']:
        data     = request.json or {}
        password = data.get('password') or ''
        if not password:
            conn.close(); return jsonify({'error': 'password_required'}), 400
        sa_row = conn.execute("SELECT password_hash FROM users WHERE id=%s", (user_id,)).fetchone()
        if not sa_row or sa_row['password_hash'] != hashlib.sha256(password.encode()).hexdigest():
            conn.close(); return jsonify({'error': 'invalid_password'}), 403
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
    atts = conn.execute(
        "SELECT file_path FROM attachments WHERE record_id IN (SELECT id FROM records WHERE user_id=%s) AND file_path IS NOT NULL",
        (target_user_id,)
    ).fetchall()
    for att in atts:
        try:
            os.remove(os.path.join(UPLOAD_FOLDER, att['file_path'].replace('/', os.sep)))
        except OSError:
            pass

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
               (SELECT COUNT(*) FROM companies c
                WHERE c.org_id=o.id AND (c.is_deleted=0 OR c.is_deleted IS NULL)) AS companies_count,
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
    result = []
    for r in rows:
        d = dict(r)
        if d.get('created_at'):
            d['created_at'] = d['created_at'].isoformat()
        if d.get('last_activity'):
            d['last_activity'] = d['last_activity'].isoformat()
        d['storage_mb'] = get_org_storage_mb(d['id'])
        result.append(d)
    return jsonify(result)


@app.route('/superadmin/orgs/<org_id>/members', methods=['GET'])
def superadmin_org_members(org_id):
    conn = get_db()
    user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err
    rows = conn.execute(
        "SELECT u.id, u.email, u.full_name, u.password_hash, u.email_verified, u.is_suspended, "
        "m.role, m.joined_at "
        "FROM org_members m JOIN users u ON m.user_id=u.id "
        "WHERE m.org_id=%s AND m.left_at IS NULL "
        "ORDER BY m.joined_at",
        (org_id,)
    ).fetchall()
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
            'role':         r['role'],
            'status':       status,
            'is_suspended': bool(r['is_suspended']),
        })
    return jsonify(result)


@app.route('/superadmin/orgs/<org_id>/members', methods=['POST'])
def superadmin_add_org_member(org_id):
    conn = get_db()
    sa_user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err

    data = request.json or {}
    target_user_id = (data.get('user_id') or '').strip()
    role = (data.get('role') or '').strip()
    if not target_user_id or role not in ('manager', 'user'):
        conn.close()
        return jsonify({'error': 'user_id_and_role_required'}), 400

    org = conn.execute("SELECT id FROM organizations WHERE id=%s", (org_id,)).fetchone()
    if not org:
        conn.close()
        return jsonify({'error': 'org_not_found'}), 404
    user = conn.execute("SELECT id FROM users WHERE id=%s", (target_user_id,)).fetchone()
    if not user:
        conn.close()
        return jsonify({'error': 'user_not_found'}), 404

    existing = conn.execute(
        "SELECT id, left_at FROM org_members WHERE org_id=%s AND user_id=%s",
        (org_id, target_user_id)
    ).fetchone()
    if existing and existing['left_at'] is None:
        conn.close()
        return jsonify({'error': 'already_member'}), 409

    if existing:
        conn.execute(
            "UPDATE org_members SET left_at=NULL, role=%s WHERE id=%s",
            (role, existing['id'])
        )
    else:
        conn.execute(
            "INSERT INTO org_members (id, org_id, user_id, role) VALUES (%s,%s,%s,%s)",
            (str(uuid.uuid4()), org_id, target_user_id, role)
        )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/superadmin/orgs/<org_id>/members/<member_user_id>/role', methods=['PUT'])
def superadmin_set_org_member_role(org_id, member_user_id):
    conn = get_db()
    sa_user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err

    new_role = (request.json or {}).get('role')
    if new_role not in ('manager', 'user'):
        conn.close()
        return jsonify({'error': 'invalid_role'}), 400

    member = conn.execute(
        "SELECT id, role FROM org_members WHERE org_id=%s AND user_id=%s AND left_at IS NULL",
        (org_id, member_user_id)
    ).fetchone()
    if not member:
        conn.close()
        return jsonify({'error': 'not_found'}), 404
    if member['role'] == 'admin':
        conn.close()
        return jsonify({'error': 'cannot_change_admin_role'}), 400

    conn.execute("UPDATE org_members SET role=%s WHERE id=%s", (new_role, member['id']))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/superadmin/orgs/<org_id>/members/<member_user_id>', methods=['DELETE'])
def superadmin_remove_org_member(org_id, member_user_id):
    conn = get_db()
    sa_user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err

    member = conn.execute(
        "SELECT id, role FROM org_members WHERE org_id=%s AND user_id=%s AND left_at IS NULL",
        (org_id, member_user_id)
    ).fetchone()
    if not member:
        conn.close()
        return jsonify({'error': 'not_found'}), 404
    if member['role'] == 'admin':
        conn.close()
        return jsonify({'error': 'cannot_remove_admin'}), 400

    conn.execute("UPDATE org_members SET left_at=now() WHERE id=%s", (member['id'],))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


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
    total_companies = conn.execute(
        "SELECT COUNT(*) AS c FROM companies WHERE is_active IS NULL OR is_active=1"
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
        'total_companies': total_companies,
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


@app.route('/org/rename', methods=['PUT'])
def org_rename():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='admin')
    if err: conn.close(); return err

    data = request.json or {}
    name = (data.get('name') or '').strip()
    if not name:
        conn.close()
        return jsonify({'error': 'name_required'}), 400

    existing_org = conn.execute(
        "SELECT id FROM organizations WHERE lower(name)=lower(%s) AND id!=%s", (name, org_id)
    ).fetchone()
    if existing_org:
        conn.close()
        return jsonify({'error': 'org_name_taken'}), 409

    conn.execute("UPDATE organizations SET name=%s WHERE id=%s", (name, org_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'name': name})


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


# ══════════════════════════════════════════
# BILLING (Фаза 3) — без провайдера, підключення пізніше
# ══════════════════════════════════════════
@app.route('/billing/checkout', methods=['POST'])
def billing_checkout():
    if not PAYMENT_PROVIDER:
        return jsonify({'error': 'payment_provider_not_configured'}), 503

    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    data = request.json or {}
    target = data.get('target')
    plan = data.get('plan')
    if target not in ('org_plan', 'user_plan'):
        return jsonify({'error': 'invalid_target'}), 400
    if plan not in ('pro', 'ultimate'):
        return jsonify({'error': 'invalid_plan'}), 400

    conn = get_db()
    org_id = None
    if target == 'org_plan':
        org_id, role, err = require_org(user_id, conn, min_role='admin')
        if err: conn.close(); return err

    payment_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO payments (id, user_id, org_id, target, plan, provider, status) VALUES (%s,%s,%s,%s,%s,%s,'pending')",
        (payment_id, user_id, org_id, target, plan, PAYMENT_PROVIDER)
    )
    conn.commit()
    conn.close()

    # TODO: створити checkout-сесію у провайдера і повернути checkout_url
    return jsonify({'payment_id': payment_id})


@app.route('/billing/webhook/<provider>', methods=['POST'])
def billing_webhook(provider):
    if not PAYMENT_PROVIDER or provider != PAYMENT_PROVIDER:
        return jsonify({'error': 'payment_provider_not_configured'}), 503

    # TODO: перевірка підпису вебхука конкретного провайдера
    return jsonify({'error': 'not_implemented'}), 501


@app.route('/billing/plans', methods=['GET'])
def billing_plans():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    return jsonify({
        'user_plans': {p: limit for p, limit in USER_ORG_LIMITS.items() if p != 'zero'},
        'org_plans':  {p: limits for p, limits in ORG_USAGE_LIMITS.items() if p != 'zero'},
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

    existing_org = conn.execute(
        "SELECT id FROM organizations WHERE lower(name)=lower(%s)", (name,)
    ).fetchone()
    if existing_org:
        conn.close()
        return jsonify({'error': 'org_name_taken'}), 409

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


@app.route('/org/members/active', methods=['GET'])
def org_members_active():
    """Активні члени org для dropdown платника — доступно всім ролям."""
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='user')
    if err: conn.close(); return err
    rows = conn.execute(
        "SELECT u.id as user_id, COALESCE(NULLIF(u.full_name,''), u.email) as display_name "
        "FROM org_members m JOIN users u ON m.user_id=u.id "
        "WHERE m.org_id=%s AND m.left_at IS NULL AND u.password_hash != 'PENDING' "
        "ORDER BY display_name",
        (org_id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


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
        limit = get_org_limits(org_id, conn)['members']
        conn.close()
        return jsonify({'error': 'limit_reached', 'resource': 'members', 'limit': limit}), 403
    org      = conn.execute("SELECT name FROM organizations WHERE id=%s", (org_id,)).fetchone()
    org_name = org['name'] if org else ''
    existing = conn.execute("SELECT id, password_hash FROM users WHERE email=%s", (email,)).fetchone()
    if existing:
        new_user_id  = existing['id']
        # Check org limit for the invited user
        if not check_org_limit(new_user_id, conn, role=role):
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
    if not check_org_limit(user_id, conn, role='user'):
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

    user = conn.execute("SELECT password_hash FROM users WHERE id=%s", (user_id,)).fetchone()
    if user and user['password_hash'] != 'GOOGLE_AUTH':
        data     = request.json or {}
        password = data.get('password') or ''
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()
        if pwd_hash != user['password_hash']:
            conn.close()
            return jsonify({'error': 'invalid_password'}), 403

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


def check_org_limit(user_id, conn, role='admin'):
    """Returns True if user can join/create more orgs with the given role.
    users.plan обмежує тільки кількість org, де юзер admin (15.06.2026)."""
    if role != 'admin':
        return True
    row = conn.execute(
        "SELECT is_superadmin, plan FROM users WHERE id=%s", (user_id,)
    ).fetchone()
    if not row or row['is_superadmin']:
        return True
    limit = USER_ORG_LIMITS.get(row['plan'] or 'free', USER_ORG_LIMITS['free'])
    if limit is None:
        return True
    count = conn.execute(
        "SELECT COUNT(*) as c FROM org_members WHERE user_id=%s AND left_at IS NULL AND role='admin'",
        (user_id,)
    ).fetchone()['c']
    return count < limit


# Ліміти ресурсів всередині org за планом (узгоджено 13.06.2026, без терміну дії)
ORG_USAGE_LIMITS = {
    'free':     {'members': 10,  'records': 100,  'companies': 5,  'storage_mb': 300},
    'pro':      {'members': 25,  'records': 500,  'companies': 20, 'storage_mb': 1024},
    'ultimate': {'members': 100, 'records': 1000, 'companies': 50, 'storage_mb': 5120},
    'zero':     None,
}

def get_org_storage_mb(org_id):
    """Return total size (MB) of files stored for this org under data/uploads/ReceiptsManager/{org_id}."""
    org_dir = os.path.join(UPLOAD_FOLDER, DRIVE_ROOT, org_id)
    size_bytes = 0
    if os.path.isdir(org_dir):
        for dirpath, _, filenames in os.walk(org_dir):
            for fname in filenames:
                try:
                    size_bytes += os.path.getsize(os.path.join(dirpath, fname))
                except OSError:
                    pass
    return round(size_bytes / (1024 * 1024), 2)

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
    storage_mb = get_org_storage_mb(org_id)
    return {'members': members, 'records': records, 'companies': companies, 'storage_mb': storage_mb}

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


def apply_plan_payment(payment_id, conn):
    """Mark a pending payment as completed and apply its plan to the user or org.
    valid_until лишається NULL (план діє назавжди, поки SA не змінить вручну)."""
    payment = conn.execute("SELECT * FROM payments WHERE id=%s AND status='pending'", (payment_id,)).fetchone()
    if not payment:
        return False
    if payment['target'] == 'org_plan':
        conn.execute("UPDATE organizations SET plan=%s WHERE id=%s", (payment['plan'], payment['org_id']))
    else:
        conn.execute("UPDATE users SET plan=%s WHERE id=%s", (payment['plan'], payment['user_id']))
    conn.execute(
        "UPDATE payments SET status='completed', completed_at=(now() AT TIME ZONE 'utc') WHERE id=%s",
        (payment_id,)
    )
    return True


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
            "select * from companies where org_id=%s and (is_deleted=0 or is_deleted is null) order by created_at",
            (org_id,)
        ).fetchall()
    elif not accessible:
        rows = []
    else:
        placeholders = ','.join(['%s'] * len(accessible))
        rows = conn.execute(
            f"select * from companies where org_id=%s and id IN ({placeholders}) and (is_deleted=0 or is_deleted is null) order by created_at",
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
        limit = get_org_limits(org_id, conn)['companies']
        conn.close()
        return jsonify({'error': 'limit_reached', 'resource': 'companies', 'limit': limit}), 403
    data = request.json
    company_id = str(uuid.uuid4())
    conn.execute(
        "insert into companies (id, user_id, org_id, name, is_shared, is_active, sort_order) values (%s,%s,%s,%s,%s,1,%s)",
        (company_id, user_id, org_id, data['name'], 1 if data.get('is_shared') else 0, data.get('sort_order', 0))
    )
    if role != 'admin':
        # manager, що створив компанію, автоматично отримує до неї доступ (інакше сам її не побачить)
        conn.execute(
            "INSERT INTO org_member_companies (id, org_id, user_id, company_id, granted_by) VALUES (%s,%s,%s,%s,%s)",
            (str(uuid.uuid4()), org_id, user_id, company_id, user_id)
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
                "select a.id, a.file_path from attachments a "
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

@app.route('/companies/<company_id>/access', methods=['GET'])
def company_get_access(company_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='admin')
    if err: conn.close(); return err
    rows = conn.execute(
        "SELECT user_id FROM org_member_companies WHERE company_id=%s AND org_id=%s",
        (company_id, org_id)
    ).fetchall()
    conn.close()
    return jsonify([r['user_id'] for r in rows])

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
    accessible = get_accessible_companies(user_id, org_id, role, conn)
    if accessible is None:
        rows = conn.execute(
            "select * from companies where org_id=%s and is_deleted=1 order by deleted_at desc",
            (org_id,)
        ).fetchall()
    elif not accessible:
        rows = []
    else:
        placeholders = ','.join(['%s'] * len(accessible))
        rows = conn.execute(
            f"select * from companies where org_id=%s and id IN ({placeholders}) and is_deleted=1 order by deleted_at desc",
            [org_id] + accessible
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
    accessible = get_accessible_companies(user_id, org_id, role, conn)
    if accessible is not None and company_id not in accessible:
        conn.close()
        return jsonify({'error': 'forbidden'}), 403
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
    org_id, role, err = require_org(user_id, conn, min_role='admin')
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
    if role == 'admin':
        rows = conn.execute(
            "select * from payment_instruments where org_id=%s and (is_deleted=0 or is_deleted is null) order by sort_order, name",
            (org_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            "select * from payment_instruments where org_id=%s and user_id=%s and (is_deleted=0 or is_deleted is null) order by sort_order, name",
            (org_id, user_id)
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
    if role == 'admin':
        rows = conn.execute(
            "select * from payment_instruments where org_id=%s and is_deleted=1 order by deleted_at desc",
            (org_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            "select * from payment_instruments where org_id=%s and user_id=%s and is_deleted=1 order by deleted_at desc",
            (org_id, user_id)
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
    if role != 'admin':
        owned = conn.execute(
            "select id from payment_instruments where id=%s and org_id=%s and user_id=%s",
            (inst_id, org_id, user_id)
        ).fetchone()
        if not owned:
            conn.close()
            return jsonify({'error': 'forbidden'}), 403
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
    org_id, role, err = require_org(user_id, conn, min_role='admin')
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
        select r.*, c.name as company_name, p.name as card_name,
          COALESCE(NULLIF(ue.full_name, ''), ue.email) as editor_name,
          COALESCE(NULLIF(uc.full_name, ''), uc.email) as creator_name,
          (r.updated_by IS NOT NULL) as author_is_editor,
          COALESCE(NULLIF(up.full_name, ''), up.email) as payer_name
        from records r
        left join companies c on r.company_id = c.id
        left join payment_instruments p on r.card_id = p.id
        left join users uc on r.created_by = uc.id
        left join users ue on r.updated_by = ue.id
        left join users up on r.payer_id = up.id
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
        editor_name = d.pop('editor_name', None)
        creator_name = d.pop('creator_name', None)
        d['author_name'] = editor_name or creator_name
        d['author_is_editor'] = bool(editor_name)
        d['payer_name'] = d.pop('payer_name', None)
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
        limit = get_org_limits(org_id, conn)['records']
        conn.close()
        return jsonify({'error': 'limit_reached', 'resource': 'records', 'limit': limit}), 403

    data = request.json or {}
    missing = [f for f in ('title', 'date', 'amount', 'pay_type', 'pay_method') if not data.get(f) and data.get(f) != 0]
    if missing:
        conn.close()
        return jsonify({'error': 'missing_fields', 'fields': missing}), 400
    try:
        float(data['amount'])
    except (TypeError, ValueError):
        conn.close()
        return jsonify({'error': 'invalid_amount'}), 400

    record_id = str(uuid.uuid4())
    org_row = conn.execute("SELECT settings FROM organizations WHERE id=%s", (org_id,)).fetchone()
    default_currency = (org_row['settings'] or {}).get('default_currency', 'EUR') if org_row else 'EUR'
    conn.execute('''
        insert into records
        (id, user_id, org_id, title, note, date, amount, currency, pay_type, pay_method,
         card_id, company_id, status, to_return, returned, remainder, created_by, payer_id)
        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
        data.get('remainder', 0),
        user_id,
        data.get('payer_id') or None
    ))
    conn.commit()

    row = conn.execute('''
        select r.*, c.name as company_name, p.name as card_name,
          COALESCE(NULLIF(ue.full_name, ''), ue.email) as editor_name,
          COALESCE(NULLIF(uc.full_name, ''), uc.email) as creator_name,
          (r.updated_by IS NOT NULL) as author_is_editor,
          COALESCE(NULLIF(up.full_name, ''), up.email) as payer_name
        from records r
        left join companies c on r.company_id = c.id
        left join payment_instruments p on r.card_id = p.id
        left join users uc on r.created_by = uc.id
        left join users ue on r.updated_by = ue.id
        left join users up on r.payer_id = up.id
        where r.id=%s
    ''', (record_id,)).fetchone()
    conn.close()

    d = dict(row)
    editor_name = d.pop('editor_name', None)
    creator_name = d.pop('creator_name', None)
    d['author_name'] = editor_name or creator_name
    d['author_is_editor'] = bool(editor_name)
    d['payer_name'] = d.pop('payer_name', None)
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
               'card_id', 'company_id', 'payer_id', 'status', 'previous_status', 'to_return', 'returned',
               'remainder', 'is_archived', 'is_deleted', 'deleted_at']
    for key in allowed:
        if key in data:
            fields.append(f"{key}=%s")
            val = data[key]
            if isinstance(val, bool):
                val = 1 if val else 0
            values.append(val)
    fields.append("updated_by=%s")
    values.append(user_id)
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
            new_folder = '/'.join([DRIVE_ROOT, org_id, 'records', new_year, new_month, new_safe])

            atts = conn.execute(
                "select * from attachments where record_id=%s and file_path is not null",
                (record_id,)
            ).fetchall()

            for att in atts:
                old_path = att['file_path'].replace('\\', '/')
                filename = old_path.split('/')[-1]
                new_path = new_folder + '/' + filename

                if old_path == new_path:
                    continue

                old_abs = os.path.join(UPLOAD_FOLDER, old_path.replace('/', os.sep))
                new_abs = os.path.join(UPLOAD_FOLDER, new_path.replace('/', os.sep))
                moved = False
                if os.path.exists(old_abs):
                    try:
                        os.makedirs(os.path.dirname(new_abs), exist_ok=True)
                        shutil.move(old_abs, new_abs)
                        moved = True
                    except Exception:
                        pass

                if moved:
                    conn.execute("update attachments set file_path=%s where id=%s", (new_path, att['id']))

            conn.commit()

            if atts:
                old_folder_rel = atts[0]['file_path'].replace('\\', '/').rsplit('/', 1)[0]
                old_folder_abs = os.path.join(UPLOAD_FOLDER, old_folder_rel.replace('/', os.sep))
                try:
                    os.rmdir(old_folder_abs)
                except Exception:
                    pass

    conn.close()
    return jsonify({'ok': True})

@app.route('/records/<record_id>', methods=['DELETE'])
def delete_record_permanent(record_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='admin')
    if err: conn.close(); return err

    exists = conn.execute(
        "select id from records where id=%s and org_id=%s",
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

    # Storage limit check
    limits = get_org_limits(org_id, conn)
    if limits is not None:
        file.seek(0, os.SEEK_END)
        file_size_mb = file.tell() / (1024 * 1024)
        file.seek(0)
        if get_org_storage_mb(org_id) + file_size_mb > limits['storage_mb']:
            conn.close()
            return jsonify({'error': 'limit_reached', 'resource': 'storage', 'limit': limits['storage_mb']}), 403

    rel_folder = '/'.join([DRIVE_ROOT, org_id, 'records', year, month, safe_company])
    abs_folder = os.path.join(UPLOAD_FOLDER, DRIVE_ROOT, org_id, 'records', year, month, safe_company)
    os.makedirs(abs_folder, exist_ok=True)

    att_id = str(uuid.uuid4())
    orig_name = file.filename
    ext = os.path.splitext(orig_name)[1].lower()
    stored_name = att_id + ext
    file_path = rel_folder + '/' + stored_name      # stored with forward slashes
    file.save(os.path.join(abs_folder, stored_name))

    file_type = file.content_type or 'application/octet-stream'

    conn.execute(
        "insert into attachments (id, record_id, file_name, file_type, file_path) values (%s,%s,%s,%s,%s)",
        (att_id, record_id, orig_name, file_type, file_path)
    )
    conn.commit()
    conn.close()

    return jsonify({'id': att_id, 'record_id': record_id, 'file_name': orig_name, 'file_type': file_type})

@app.route('/attachments/<att_id>/file', methods=['GET'])
def serve_attachment(att_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    org_id, role, err = require_org(user_id, conn)
    if err: conn.close(); return err
    att = conn.execute(
        "select a.*, r.company_id from attachments a join records r on a.record_id=r.id where a.id=%s and r.org_id=%s",
        (att_id, org_id)
    ).fetchone()
    if att:
        accessible = get_accessible_companies(user_id, org_id, role, conn)
        if accessible is not None and att['company_id'] not in accessible:
            att = None
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
        "select a.*, r.company_id from attachments a join records r on a.record_id=r.id where a.id=%s and r.org_id=%s",
        (att_id, org_id)
    ).fetchone()
    if att:
        accessible = get_accessible_companies(user_id, org_id, role, conn)
        if accessible is not None and att['company_id'] not in accessible:
            att = None
    if not att:
        conn.close()
        return jsonify({'error': 'Not found'}), 404

    if att['file_path']:
        try:
            os.remove(os.path.join(UPLOAD_FOLDER, att['file_path'].replace('/', os.sep)))
        except Exception:
            pass

    conn.execute("delete from attachments where id=%s", (att_id,))
    conn.commit()
    conn.close()

    return jsonify({'ok': True})

@app.route('/gallery', methods=['GET'])
def get_gallery():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn)
    if err: conn.close(); return err

    accessible = get_accessible_companies(user_id, org_id, role, conn)
    if accessible is not None and not accessible:
        conn.close()
        return jsonify([])

    query = '''
        select
            a.id, a.file_name, a.file_type, a.file_path, a.created_at,
            r.id as record_id,
            r.title as record_title,
            r.date as record_date,
            c.name as company_name,
            p.name as card_name
        from attachments a
        join records r on a.record_id = r.id
        left join companies c on r.company_id = c.id
        left join payment_instruments p on r.card_id = p.id
        where r.org_id = %s and r.is_deleted = 0 and a.file_path is not null
    '''
    params = [org_id]
    if accessible is not None:
        placeholders = ','.join(['%s'] * len(accessible))
        query += f" and r.company_id IN ({placeholders})"
        params += accessible
    query += " order by r.date desc, a.created_at desc"

    att_rows = conn.execute(query, params).fetchall()
    result = []
    for r in att_rows:
        d = dict(r)
        d['item_type'] = 'record'
        result.append(d)

    cexp_query = '''
        select
            a.id, a.file_name, a.file_type, a.file_path, a.created_at,
            ce.id as record_id,
            ce.date as record_date,
            cp.name as paying_name,
            cb.name as bene_name
        from company_expense_attachments a
        join company_expenses ce on a.cexp_id = ce.id
        left join companies cp on ce.paying_company_id = cp.id
        left join companies cb on ce.beneficiary_company_id = cb.id
        where ce.org_id = %s and (ce.is_deleted IS NULL OR ce.is_deleted = FALSE) and a.file_path is not null
    '''
    cexp_params = [org_id]
    if accessible is not None:
        cexp_query += " and (ce.paying_company_id = ANY(%s) or ce.beneficiary_company_id = ANY(%s))"
        cexp_params += [accessible, accessible]

    cexp_rows = conn.execute(cexp_query, cexp_params).fetchall()
    conn.close()

    for r in cexp_rows:
        d = dict(r)
        d['item_type'] = 'cexp'
        d['record_title'] = ' → '.join(filter(None, [d.pop('paying_name', None), d.pop('bene_name', None)])) or '—'
        d['company_name'] = None
        d['card_name'] = None
        # ce.date/a.created_at — справжні SQL DATE/TIMESTAMP, Flask серіалізує їх не в ISO
        # (на відміну від records.date, який зберігається як TEXT) — приводимо явно.
        if d.get('record_date') is not None:
            d['record_date'] = str(d['record_date'])
        if d.get('created_at') is not None:
            d['created_at'] = d['created_at'].isoformat()
        result.append(d)

    result.sort(key=lambda x: (str(x.get('record_date') or ''), str(x.get('created_at') or '')), reverse=True)
    return jsonify(result)

# ══════════════════════════════════════════
# BACKUP
# ══════════════════════════════════════════
import json as _json

def _rows_to_list(conn, query, params=()):
    import decimal, uuid as _uuid
    rows = conn.execute(query, params).fetchall()
    result = []
    for row in rows:
        d = {}
        for k, v in row.items():
            if hasattr(v, 'isoformat'):
                v = v.isoformat()
            elif isinstance(v, decimal.Decimal):
                v = float(v)
            elif isinstance(v, _uuid.UUID):
                v = str(v)
            d[k] = v
        result.append(d)
    return result

# ══════════════════════════════════════════
# COMPANY EXPENSES
# ══════════════════════════════════════════

def _cexp_row_to_dict(r):
    d = dict(r)
    editor = d.pop('editor_name', None)
    creator = d.pop('creator_name', None)
    d['author_name'] = editor or creator
    d['author_is_editor'] = bool(editor)
    if d.get('date'): d['date'] = str(d['date'])
    return d

CEXP_SELECT = """
    SELECT ce.*,
        cp.name as paying_company_name,
        cb.name as beneficiary_company_name,
        COALESCE(NULLIF(ue_in.full_name,''), ue_in.email) as entered_by_name,
        COALESCE(NULLIF(uc.full_name,''), uc.email) as creator_name,
        COALESCE(NULLIF(ue.full_name,''), ue.email) as editor_name
    FROM company_expenses ce
    LEFT JOIN companies cp ON ce.paying_company_id = cp.id
    LEFT JOIN companies cb ON ce.beneficiary_company_id = cb.id
    LEFT JOIN users ue_in ON ce.entered_by = ue_in.id
    LEFT JOIN users uc ON ce.created_by = uc.id
    LEFT JOIN users ue ON ce.updated_by = ue.id
"""

def _get_accessible_company_ids(user_id, org_id, conn):
    rows = conn.execute(
        "SELECT company_id FROM org_member_companies WHERE user_id=%s AND org_id=%s",
        (user_id, org_id)
    ).fetchall()
    return [r['company_id'] for r in rows]


def _cexp_user_has_access(user_id, org_id, role, conn, paying_id, beneficiary_id):
    if role == 'admin':
        return True
    company_ids = _get_accessible_company_ids(user_id, org_id, conn)
    return (paying_id in company_ids) or (beneficiary_id in company_ids)


def _cexp_safe_company(name):
    return re.sub(r'[^\w\s\-]', '', name or '').strip().replace(' ', '_') or 'Unassigned'


def _attach_cexp_attachments(rows, conn):
    """Мутує список dict-ів company_expense — додає 'attachments': [...] кожному."""
    if not rows:
        return rows
    ids = [r['id'] for r in rows]
    atts = conn.execute(
        "SELECT * FROM company_expense_attachments WHERE cexp_id = ANY(%s) ORDER BY created_at",
        (ids,)
    ).fetchall()
    by_cexp = {}
    for a in atts:
        by_cexp.setdefault(a['cexp_id'], []).append(dict(a))
    for r in rows:
        r['attachments'] = by_cexp.get(r['id'], [])
    return rows

@app.route('/company-expenses', methods=['GET'])
def get_company_expenses():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn)
    if err: conn.close(); return err

    if role == 'admin':
        rows = conn.execute(
            CEXP_SELECT + " WHERE ce.org_id=%s AND (ce.is_deleted IS NULL OR ce.is_deleted=FALSE) ORDER BY ce.date DESC, ce.created_at DESC",
            (org_id,)
        ).fetchall()
    else:
        company_ids = _get_accessible_company_ids(user_id, org_id, conn)
        if not company_ids:
            conn.close()
            return jsonify([])
        rows = conn.execute(
            CEXP_SELECT + """ WHERE ce.org_id=%s
              AND (ce.is_deleted IS NULL OR ce.is_deleted=FALSE)
              AND (ce.paying_company_id = ANY(%s) OR ce.beneficiary_company_id = ANY(%s))
              ORDER BY ce.date DESC, ce.created_at DESC""",
            (org_id, company_ids, company_ids)
        ).fetchall()

    result = _attach_cexp_attachments([_cexp_row_to_dict(r) for r in rows], conn)
    conn.close()
    return jsonify(result)

@app.route('/company-expenses/trash', methods=['GET'])
def get_company_expenses_trash():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn)
    if err: conn.close(); return err
    if role == 'admin':
        rows = conn.execute(
            CEXP_SELECT + " WHERE ce.org_id=%s AND ce.is_deleted=TRUE ORDER BY ce.deleted_at DESC",
            (org_id,)
        ).fetchall()
    else:
        company_ids = _get_accessible_company_ids(user_id, org_id, conn)
        if not company_ids:
            conn.close()
            return jsonify([])
        rows = conn.execute(
            CEXP_SELECT + """ WHERE ce.org_id=%s AND ce.is_deleted=TRUE
              AND (ce.paying_company_id = ANY(%s) OR ce.beneficiary_company_id = ANY(%s))
              ORDER BY ce.deleted_at DESC""",
            (org_id, company_ids, company_ids)
        ).fetchall()
    result = _attach_cexp_attachments([_cexp_row_to_dict(r) for r in rows], conn)
    conn.close()
    return jsonify(result)

@app.route('/company-expenses', methods=['POST'])
def create_company_expense():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='manager')
    if err: conn.close(); return err
    data = request.json or {}

    if not data.get('date'):
        conn.close()
        return jsonify({'error': 'missing_fields', 'fields': ['date']}), 400
    try:
        amount = float(data.get('amount') if data.get('amount') is not None else 0)
        returned_amount = float(data.get('returned_amount') if data.get('returned_amount') is not None else 0)
    except (TypeError, ValueError):
        conn.close()
        return jsonify({'error': 'invalid_amount'}), 400

    if role != 'admin':
        company_ids = _get_accessible_company_ids(user_id, org_id, conn)
        paying = data.get('paying_company_id')
        bene   = data.get('beneficiary_company_id')
        if (paying and paying not in company_ids) or (bene and bene not in company_ids):
            conn.close()
            return jsonify({'error': 'forbidden'}), 403

    exp_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO company_expenses
           (id, org_id, date, paying_company_id, beneficiary_company_id, amount, note, entered_by, status, returned_amount, created_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (exp_id, org_id, data['date'],
         data.get('paying_company_id') or None,
         data.get('beneficiary_company_id') or None,
         amount,
         data.get('note') or None,
         data.get('entered_by') or None,
         data.get('status', 'waiting'),
         returned_amount,
         user_id)
    )
    conn.commit()
    row = conn.execute(CEXP_SELECT + " WHERE ce.id=%s", (exp_id,)).fetchone()
    conn.close()
    return jsonify(_cexp_row_to_dict(row)), 201

@app.route('/company-expenses/<exp_id>', methods=['PUT'])
def update_company_expense(exp_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='manager')
    if err: conn.close(); return err
    row = conn.execute(
        "SELECT id, paying_company_id, beneficiary_company_id FROM company_expenses WHERE id=%s AND org_id=%s",
        (exp_id, org_id)
    ).fetchone()
    if not row: conn.close(); return jsonify({'error': 'not_found'}), 404

    data = request.json or {}

    if not data.get('date'):
        conn.close()
        return jsonify({'error': 'missing_fields', 'fields': ['date']}), 400
    try:
        amount = float(data.get('amount') if data.get('amount') is not None else 0)
        returned_amount = float(data.get('returned_amount') if data.get('returned_amount') is not None else 0)
    except (TypeError, ValueError):
        conn.close()
        return jsonify({'error': 'invalid_amount'}), 400

    if role != 'admin':
        company_ids = _get_accessible_company_ids(user_id, org_id, conn)
        paying = data.get('paying_company_id') or row['paying_company_id']
        bene   = data.get('beneficiary_company_id') or row['beneficiary_company_id']
        if (paying and paying not in company_ids) or (bene and bene not in company_ids):
            conn.close()
            return jsonify({'error': 'forbidden'}), 403
    conn.execute(
        """UPDATE company_expenses SET
           date=%s, paying_company_id=%s, beneficiary_company_id=%s,
           amount=%s, note=%s, entered_by=%s, status=%s, returned_amount=%s,
           updated_by=%s, updated_at=now()
           WHERE id=%s AND org_id=%s""",
        (data['date'],
         data.get('paying_company_id') or None,
         data.get('beneficiary_company_id') or None,
         amount,
         data.get('note') or None,
         data.get('entered_by') or None,
         data.get('status', 'waiting'),
         returned_amount,
         user_id, exp_id, org_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/company-expenses/<exp_id>', methods=['DELETE'])
def delete_company_expense(exp_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='manager')
    if err: conn.close(); return err

    row = conn.execute(
        "SELECT paying_company_id, beneficiary_company_id FROM company_expenses WHERE id=%s AND org_id=%s AND (is_deleted IS NULL OR is_deleted=FALSE)",
        (exp_id, org_id)
    ).fetchone()
    if not row: conn.close(); return jsonify({'error': 'not_found'}), 404

    if role != 'admin':
        company_ids = _get_accessible_company_ids(user_id, org_id, conn)
        if row['paying_company_id'] not in company_ids and row['beneficiary_company_id'] not in company_ids:
            conn.close()
            return jsonify({'error': 'forbidden'}), 403

    import datetime as _dt
    conn.execute(
        "UPDATE company_expenses SET is_deleted=TRUE, deleted_at=%s WHERE id=%s AND org_id=%s",
        (_dt.datetime.utcnow(), exp_id, org_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/company-expenses/<exp_id>/restore', methods=['PUT'])
def restore_company_expense(exp_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='manager')
    if err: conn.close(); return err
    conn.execute(
        "UPDATE company_expenses SET is_deleted=FALSE, deleted_at=NULL WHERE id=%s AND org_id=%s",
        (exp_id, org_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/company-expenses/<exp_id>/permanent', methods=['DELETE'])
def permanent_delete_company_expense(exp_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='admin')
    if err: conn.close(); return err

    atts = conn.execute(
        "SELECT file_path FROM company_expense_attachments WHERE cexp_id=%s", (exp_id,)
    ).fetchall()
    for a in atts:
        if a['file_path']:
            try:
                os.remove(os.path.join(UPLOAD_FOLDER, a['file_path'].replace('/', os.sep)))
            except OSError:
                pass

    conn.execute("DELETE FROM company_expenses WHERE id=%s AND org_id=%s", (exp_id, org_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/company-expenses/<exp_id>/attachments', methods=['POST'])
def upload_cexp_attachment(exp_id):
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

    exp = conn.execute(
        "select ce.date, ce.paying_company_id, ce.beneficiary_company_id, "
        "cp.name as paying_name, cb.name as bene_name "
        "from company_expenses ce "
        "left join companies cp on ce.paying_company_id=cp.id "
        "left join companies cb on ce.beneficiary_company_id=cb.id "
        "where ce.id=%s and ce.org_id=%s",
        (exp_id, org_id)
    ).fetchone()
    if not exp:
        conn.close()
        return jsonify({'error': 'Not found'}), 404

    if not _cexp_user_has_access(user_id, org_id, role, conn, exp['paying_company_id'], exp['beneficiary_company_id']):
        conn.close()
        return jsonify({'error': 'forbidden'}), 403

    exp_date = str(exp['date']) if exp['date'] else datetime.utcnow().strftime('%Y-%m-%d')
    year  = exp_date[:4]
    month = exp_date[5:7]
    pair_folder = f"{_cexp_safe_company(exp['paying_name'])}_to_{_cexp_safe_company(exp['bene_name'])}"

    limits = get_org_limits(org_id, conn)
    if limits is not None:
        file.seek(0, os.SEEK_END)
        file_size_mb = file.tell() / (1024 * 1024)
        file.seek(0)
        if get_org_storage_mb(org_id) + file_size_mb > limits['storage_mb']:
            conn.close()
            return jsonify({'error': 'limit_reached', 'resource': 'storage', 'limit': limits['storage_mb']}), 403

    rel_folder = '/'.join([DRIVE_ROOT, org_id, 'cexp', year, month, pair_folder])
    abs_folder = os.path.join(UPLOAD_FOLDER, DRIVE_ROOT, org_id, 'cexp', year, month, pair_folder)
    os.makedirs(abs_folder, exist_ok=True)

    att_id = str(uuid.uuid4())
    orig_name = file.filename
    ext = os.path.splitext(orig_name)[1].lower()
    stored_name = att_id + ext
    file_path = rel_folder + '/' + stored_name
    file.save(os.path.join(abs_folder, stored_name))

    file_type = file.content_type or 'application/octet-stream'

    conn.execute(
        "insert into company_expense_attachments (id, cexp_id, file_name, file_type, file_path) values (%s,%s,%s,%s,%s)",
        (att_id, exp_id, orig_name, file_type, file_path)
    )
    conn.commit()
    conn.close()

    return jsonify({'id': att_id, 'cexp_id': exp_id, 'file_name': orig_name, 'file_type': file_type})


@app.route('/cexp-attachments/<att_id>/file', methods=['GET'])
def serve_cexp_attachment(att_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    org_id, role, err = require_org(user_id, conn)
    if err: conn.close(); return err
    att = conn.execute(
        "select a.*, ce.paying_company_id, ce.beneficiary_company_id "
        "from company_expense_attachments a join company_expenses ce on a.cexp_id=ce.id "
        "where a.id=%s and ce.org_id=%s",
        (att_id, org_id)
    ).fetchone()
    if att and not _cexp_user_has_access(user_id, org_id, role, conn, att['paying_company_id'], att['beneficiary_company_id']):
        att = None
    conn.close()

    if not att or not att['file_path']:
        return jsonify({'error': 'Not found'}), 404

    return send_from_directory(UPLOAD_FOLDER, att['file_path'])


@app.route('/cexp-attachments/<att_id>', methods=['DELETE'])
def delete_cexp_attachment(att_id):
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='manager')
    if err: conn.close(); return err
    att = conn.execute(
        "select a.*, ce.paying_company_id, ce.beneficiary_company_id "
        "from company_expense_attachments a join company_expenses ce on a.cexp_id=ce.id "
        "where a.id=%s and ce.org_id=%s",
        (att_id, org_id)
    ).fetchone()
    if not att:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    if not _cexp_user_has_access(user_id, org_id, role, conn, att['paying_company_id'], att['beneficiary_company_id']):
        conn.close()
        return jsonify({'error': 'forbidden'}), 403

    if att['file_path']:
        try:
            os.remove(os.path.join(UPLOAD_FOLDER, att['file_path'].replace('/', os.sep)))
        except OSError:
            pass

    conn.execute("delete from company_expense_attachments where id=%s", (att_id,))
    conn.commit()
    conn.close()

    return jsonify({'ok': True})


@app.route('/company-settlements', methods=['GET'])
def get_company_settlements():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn)
    if err: conn.close(); return err

    if role == 'admin':
        access_filter = ''
        params = (org_id,)
    else:
        company_ids = _get_accessible_company_ids(user_id, org_id, conn)
        if not company_ids:
            conn.close()
            return jsonify([])
        access_filter = 'AND (ce.paying_company_id = ANY(%s) OR ce.beneficiary_company_id = ANY(%s))'
        params = (org_id, company_ids, company_ids)

    rows = conn.execute("""
        SELECT
            ce.paying_company_id,
            cp.name AS paying_name,
            ce.beneficiary_company_id,
            cb.name AS bene_name,
            SUM(ce.amount) AS total_amount,
            SUM(ce.returned_amount) AS total_returned,
            SUM(CASE WHEN ce.status != 'done' THEN ce.amount - ce.returned_amount ELSE 0 END) AS open_debt,
            COUNT(*) AS expense_count
        FROM company_expenses ce
        LEFT JOIN companies cp ON cp.id = ce.paying_company_id
        LEFT JOIN companies cb ON cb.id = ce.beneficiary_company_id
        WHERE ce.org_id = %s
          AND (ce.is_deleted IS NULL OR ce.is_deleted=FALSE)
          AND ce.paying_company_id IS NOT NULL
          AND ce.beneficiary_company_id IS NOT NULL
          AND ce.paying_company_id != ce.beneficiary_company_id
          {access_filter}
        GROUP BY ce.paying_company_id, cp.name, ce.beneficiary_company_id, cb.name
    """.format(access_filter=access_filter), params).fetchall()
    conn.close()

    # Build directional map
    direct = {}
    for r in rows:
        d = dict(r)
        key = (d['paying_company_id'], d['beneficiary_company_id'])
        direct[key] = d

    # Net out pairs
    seen = set()
    result = []
    for (paying_id, bene_id), d in direct.items():
        pair_key = tuple(sorted([paying_id, bene_id]))
        if pair_key in seen:
            continue
        seen.add(pair_key)

        reverse = direct.get((bene_id, paying_id))
        total = float(d['total_amount'])
        returned = float(d['total_returned'])
        open_d = float(d['open_debt'])

        if reverse:
            total += float(reverse['total_amount'])
            returned += float(reverse['total_returned'])
            net_open = open_d - float(reverse['open_debt'])
        else:
            net_open = open_d

        if net_open >= 0:
            debtor_id, debtor_name = bene_id, d['bene_name']
            creditor_id, creditor_name = paying_id, d['paying_name']
        else:
            debtor_id, debtor_name = paying_id, d['paying_name']
            creditor_id, creditor_name = bene_id, d['bene_name']
            net_open = abs(net_open)

        result.append({
            'debtor_id': debtor_id,
            'debtor_name': debtor_name,
            'creditor_id': creditor_id,
            'creditor_name': creditor_name,
            'open_amount': round(net_open, 2),
            'total_amount': round(total, 2),
            'total_returned': round(returned, 2),
            'is_net': bool(reverse),
            'expense_count': int(d['expense_count']) + (int(reverse['expense_count']) if reverse else 0)
        })

    result.sort(key=lambda x: x['open_amount'], reverse=True)
    return jsonify(result)


@app.route('/backup/download', methods=['GET'])
def backup_download():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='admin')
    if err: conn.close(); return err

    try:
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc)
        timestamp = now.strftime('%Y%m%d_%H%M%S')
        data = {
            'version': 1,
            'created_at': now.isoformat(),
            'org_id': org_id,
            'tables': {
                'organizations':      _rows_to_list(conn, "SELECT * FROM organizations WHERE id=%s", (org_id,)),
                'org_members':        _rows_to_list(conn, "SELECT * FROM org_members WHERE org_id=%s", (org_id,)),
                'org_member_companies': _rows_to_list(conn,
                    "SELECT omc.* FROM org_member_companies omc "
                    "JOIN org_members om ON omc.user_id=om.user_id AND omc.org_id=om.org_id "
                    "WHERE om.org_id=%s", (org_id,)),
                'companies':          _rows_to_list(conn, "SELECT * FROM companies WHERE org_id=%s", (org_id,)),
                'payment_instruments': _rows_to_list(conn, "SELECT * FROM payment_instruments WHERE org_id=%s", (org_id,)),
                'records':            _rows_to_list(conn,
                    "SELECT * FROM records WHERE org_id=%s AND is_deleted=0", (org_id,)),
                'return_events':      _rows_to_list(conn,
                    "SELECT re.* FROM return_events re "
                    "JOIN records r ON re.record_id=r.id "
                    "WHERE r.org_id=%s AND r.is_deleted=0", (org_id,)),
                'attachments':        _rows_to_list(conn,
                    "SELECT a.* FROM attachments a "
                    "JOIN records r ON a.record_id=r.id "
                    "WHERE r.org_id=%s AND r.is_deleted=0", (org_id,)),
            },
            'users_ref': _rows_to_list(conn,
                "SELECT u.id, u.email, u.full_name FROM users u "
                "JOIN org_members om ON u.id=om.user_id "
                "WHERE om.org_id=%s AND om.left_at IS NULL", (org_id,)),
        }
        json_bytes = _json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')

        buf = io.BytesIO()
        org_upload_dir = os.path.join('data', 'uploads', 'ReceiptsManager', org_id)
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('backup.json', json_bytes)
            if os.path.exists(org_upload_dir):
                for dirpath, _, filenames in os.walk(org_upload_dir):
                    for fname in filenames:
                        full = os.path.join(dirpath, fname)
                        arcname = os.path.relpath(full, os.path.join('data', 'uploads'))
                        zf.write(full, arcname.replace(os.sep, '/'))
        buf.seek(0)
        conn.close()
        from flask import Response
        return Response(
            buf.getvalue(),
            mimetype='application/zip',
            headers={'Content-Disposition': f'attachment; filename=backup_{timestamp}.zip'}
        )
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 500


@app.route('/backup/restore', methods=['POST'])
def backup_restore():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='admin')
    if err: conn.close(); return err

    if 'file' not in request.files:
        conn.close()
        return jsonify({'ok': False, 'message': 'no_file'}), 400
    f = request.files['file']
    if not f.filename.endswith('.zip'):
        conn.close()
        return jsonify({'ok': False, 'message': 'invalid_file'}), 400

    try:
        buf = io.BytesIO(f.read())
        with zipfile.ZipFile(buf, 'r') as zf:
            names = zf.namelist()
            if 'backup.json' not in names:
                conn.close()
                return jsonify({'ok': False, 'message': 'invalid_backup'}), 400

            bdata = _json.loads(zf.open('backup.json').read().decode('utf-8'))
            if bdata.get('version') != 1 or 'tables' not in bdata or 'org_id' not in bdata:
                conn.close()
                return jsonify({'ok': False, 'message': 'invalid_backup'}), 400
            if bdata['org_id'] != org_id:
                conn.close()
                return jsonify({'ok': False, 'message': 'org_mismatch'}), 400

            tables = bdata['tables']

            def upsert(table, rows, conflict_col='id'):
                for row in rows:
                    cols = list(row.keys())
                    vals = [_json.dumps(v) if isinstance(v, (dict, list)) else v for v in (row[c] for c in cols)]
                    ph = ','.join(['%s'] * len(cols))
                    set_clause = ','.join([f"{c}=EXCLUDED.{c}" for c in cols if c != conflict_col])
                    conn.execute(
                        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({ph}) "
                        f"ON CONFLICT ({conflict_col}) DO UPDATE SET {set_clause}",
                        vals
                    )

            # Delete in reverse FK order
            conn.execute("DELETE FROM return_events WHERE record_id IN (SELECT id FROM records WHERE org_id=%s)", (org_id,))
            conn.execute("DELETE FROM attachments WHERE record_id IN (SELECT id FROM records WHERE org_id=%s)", (org_id,))
            conn.execute("DELETE FROM records WHERE org_id=%s", (org_id,))
            conn.execute("DELETE FROM org_member_companies WHERE org_id=%s", (org_id,))
            conn.execute("DELETE FROM payment_instruments WHERE org_id=%s", (org_id,))
            conn.execute("DELETE FROM companies WHERE org_id=%s", (org_id,))

            # Restore in FK order
            upsert('organizations', tables.get('organizations', []))

            # org_members: тільки якщо user існує
            for row in tables.get('org_members', []):
                exists = conn.execute("SELECT id FROM users WHERE id=%s", (row['user_id'],)).fetchone()
                if exists:
                    cols = list(row.keys())
                    vals = [row[c] for c in cols]
                    ph = ','.join(['%s'] * len(cols))
                    set_clause = ','.join([f"{c}=EXCLUDED.{c}" for c in cols if c != 'id'])
                    conn.execute(
                        f"INSERT INTO org_members ({','.join(cols)}) VALUES ({ph}) "
                        f"ON CONFLICT (id) DO UPDATE SET {set_clause}", vals
                    )

            upsert('companies', tables.get('companies', []))
            upsert('payment_instruments', tables.get('payment_instruments', []))
            upsert('records', tables.get('records', []))
            upsert('return_events', tables.get('return_events', []))
            upsert('attachments', tables.get('attachments', []))
            upsert('org_member_companies', tables.get('org_member_companies', []))

            conn.commit()

            # Restore files
            org_upload_dir = os.path.join('data', 'uploads', 'ReceiptsManager', org_id)
            if os.path.exists(org_upload_dir):
                shutil.rmtree(org_upload_dir)
            file_prefix = f'ReceiptsManager/{org_id}/'
            for name in names:
                if name.startswith(file_prefix) and not name.endswith('/'):
                    dest = os.path.join('data', 'uploads', name.replace('/', os.sep))
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with zf.open(name) as src:
                        with open(dest, 'wb') as dst:
                            dst.write(src.read())

    except Exception as e:
        conn.close()
        return jsonify({'ok': False, 'message': str(e)}), 500

    conn.close()
    return jsonify({'ok': True})


# ══════════════════════════════════════════
# PROFILE
# ══════════════════════════════════════════
@app.route('/profile', methods=['GET'])
def get_profile():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    row = conn.execute(
        "select email, full_name from users where id=%s", (user_id,)
    ).fetchone()
    conn.close()
    if not row: return jsonify({'error': 'Not found'}), 404

    return jsonify({
        'email':     row['email'] or '',
        'full_name': row['full_name'] or '',
    })


@app.route('/profile', methods=['PUT'])
def update_profile():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    full_name = ((request.json or {}).get('full_name') or '').strip()
    if not full_name:
        return jsonify({'error': 'full_name_required'}), 400

    conn = get_db()
    conn.execute("UPDATE users SET full_name=%s WHERE id=%s", (full_name, user_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'full_name': full_name})


# ══════════════════════════════════════════
# STORAGE INFO
# ══════════════════════════════════════════

def _cleanup_org_files(org_id, conn, dry_run=False):
    """Знаходить файли data/uploads/ReceiptsManager/{org_id}, яких немає серед
    attachments.file_path/company_expense_attachments.file_path у БД цієї org.
    dry_run=True — тільки рахує, нічого не чіпає."""
    db_atts = conn.execute(
        "select a.file_path from attachments a join records r on a.record_id=r.id "
        "where r.org_id=%s and a.file_path is not null",
        (org_id,)
    ).fetchall()
    db_cexp_atts = conn.execute(
        "select a.file_path from company_expense_attachments a join company_expenses ce on a.cexp_id=ce.id "
        "where ce.org_id=%s and a.file_path is not null",
        (org_id,)
    ).fetchall()
    db_paths = {row['file_path'] for row in db_atts} | {row['file_path'] for row in db_cexp_atts}

    orphan_files = 0
    orphan_size_bytes = 0
    deleted_folders = 0

    org_dir = os.path.join(UPLOAD_FOLDER, DRIVE_ROOT, org_id)
    if os.path.exists(org_dir):
        for dirpath, dirnames, filenames in os.walk(org_dir):
            for fname in filenames:
                full_path = os.path.join(dirpath, fname)
                rel_path  = os.path.relpath(full_path, UPLOAD_FOLDER).replace(os.sep, '/')
                if rel_path not in db_paths:
                    if dry_run:
                        try:
                            orphan_size_bytes += os.path.getsize(full_path)
                            orphan_files += 1
                        except OSError:
                            pass
                    else:
                        try:
                            os.remove(full_path)
                            orphan_files += 1
                        except OSError:
                            pass

        if not dry_run:
            protected = {'Unprocessed Imports', 'Backup'}
            for dirpath, dirnames, filenames in os.walk(org_dir, topdown=False):
                if os.path.abspath(dirpath) == os.path.abspath(org_dir):
                    continue
                if os.path.basename(dirpath) in protected:
                    continue
                try:
                    os.rmdir(dirpath)
                    deleted_folders += 1
                except OSError:
                    pass

    return {'files': orphan_files, 'size_bytes': orphan_size_bytes, 'folders': deleted_folders}


@app.route('/storage-cleanup', methods=['POST'])
def storage_cleanup():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db()
    org_id, role, err = require_org(user_id, conn, min_role='admin')
    if err: conn.close(); return err
    result = _cleanup_org_files(org_id, conn, dry_run=False)
    conn.close()
    return jsonify({'deleted_files': result['files'], 'deleted_folders': result['folders']})


@app.route('/storage-info', methods=['GET'])
def storage_info():
    user_id = get_user_from_token(request)
    if not user_id: return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    org_id, role, err = require_org(user_id, conn)
    conn.close()
    if err: return err

    uploads_size = 0
    file_count   = 0
    org_dir = os.path.join(UPLOAD_FOLDER, DRIVE_ROOT, org_id)
    if os.path.exists(org_dir):
        for dirpath, dirnames, filenames in os.walk(org_dir):
            for fname in filenames:
                try:
                    uploads_size += os.path.getsize(os.path.join(dirpath, fname))
                    file_count   += 1
                except OSError:
                    pass

    return jsonify({
        'uploads_size': uploads_size,
        'total_size':   uploads_size,
        'file_count':   file_count,
    })


@app.route('/superadmin/storage-cleanup/preview', methods=['GET'])
def superadmin_storage_cleanup_preview():
    conn = get_db()
    user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err

    orgs = conn.execute("SELECT id, name FROM organizations ORDER BY name").fetchall()
    result = []
    for org in orgs:
        r = _cleanup_org_files(org['id'], conn, dry_run=True)
        if r['files'] > 0:
            result.append({
                'org_id': org['id'],
                'org_name': org['name'],
                'orphan_files': r['files'],
                'orphan_size_mb': round(r['size_bytes'] / (1024 * 1024), 2),
            })
    conn.close()
    return jsonify(result)


@app.route('/superadmin/storage-cleanup', methods=['POST'])
def superadmin_storage_cleanup():
    conn = get_db()
    user_id, err = require_superadmin(request, conn)
    if err: conn.close(); return err

    orgs = conn.execute("SELECT id FROM organizations").fetchall()
    total_files = 0
    total_folders = 0
    for org in orgs:
        r = _cleanup_org_files(org['id'], conn, dry_run=False)
        total_files += r['files']
        total_folders += r['folders']
    conn.close()
    return jsonify({'deleted_files': total_files, 'deleted_folders': total_folders})


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
    att_total = conn.execute("SELECT COUNT(*) FROM attachments a JOIN records r ON a.record_id=r.id WHERE r.org_id=%s", (org_id,)).fetchone()['count']
    att_local = conn.execute(
        "SELECT COUNT(*) FROM attachments a JOIN records r ON a.record_id=r.id "
        "WHERE r.org_id=%s AND a.file_path IS NOT NULL",
        (org_id,)).fetchone()['count']
    conn.close()

    return jsonify({
        'records':     {'total': rec_total, 'active': rec_active, 'archived': rec_archived, 'deleted': rec_deleted},
        'attachments': {'total': att_total, 'local': att_local},
    })


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
    from migrations.runner import run_pending_migrations
    run_pending_migrations(DATABASE_URL)
    init_db()
    print("Starting Reimbursement App server...")
    print("Open: http://localhost:5500")
    print("-" * 40)
    app.run(host='0.0.0.0', port=5500, debug=False)
