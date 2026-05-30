// ══════════════════════════════════════════
// AUTH — Google OAuth + Email/Password
// ══════════════════════════════════════════

function signInWithGoogle() {
  window.location.href = '/auth/google';
}

let _authMode = 'login';

function authShowTab(mode) {
  _authMode = mode;
  const isReg = mode === 'register';
  document.getElementById('auth-name-group').style.display = isReg ? '' : 'none';
  document.getElementById('auth-submit-btn').textContent = isReg ? t('auth.register_btn') : t('auth.login_btn');
  document.getElementById('tab-login').style.background    = isReg ? 'var(--bg2)' : 'var(--accent)';
  document.getElementById('tab-login').style.color         = isReg ? 'var(--text2)' : '#fff';
  document.getElementById('tab-register').style.background = isReg ? 'var(--accent)' : 'var(--bg2)';
  document.getElementById('tab-register').style.color      = isReg ? '#fff' : 'var(--text2)';
  document.getElementById('auth-error').style.display = 'none';
}

async function authSubmit() {
  const email    = (document.getElementById('auth-email').value || '').trim();
  const password = (document.getElementById('auth-password').value || '');
  const name     = (document.getElementById('auth-name').value || '').trim();
  const errEl    = document.getElementById('auth-error');
  const btn      = document.getElementById('auth-submit-btn');

  if(!email || !password) { errEl.textContent = t('auth.err_enter_email_password'); errEl.style.display=''; return; }

  btn.disabled = true;
  errEl.style.display = 'none';

  try {
    const url  = _authMode === 'register' ? '/auth/register' : '/auth/login';
    const body = _authMode === 'register' ? { email, password, full_name: name } : { email, password };
    const res  = await fetch(url, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if(data.ok) {
      if(_authMode === 'register' && data.verify_email) {
        showVerifyEmailScreen(email);
      } else {
        window.location.reload();
      }
    } else {
      const msgs = {
        email_taken: t('auth.err_email_taken'),
        invalid_credentials: t('auth.err_invalid_credentials'),
        password_too_short: t('auth.err_password_too_short'),
        email_and_password_required: t('auth.err_enter_email_password'),
      };
      errEl.textContent = msgs[data.error] || t('auth.err_generic');
      errEl.style.display = '';
    }
  } catch {
    errEl.textContent = t('auth.err_connection');
    errEl.style.display = '';
  } finally {
    btn.disabled = false;
  }
}

async function authGetCurrentUser() {
  try {
    const res = await fetch('/auth/me', { credentials: 'include' });
    if(!res.ok) {
      if(res.status === 403) {
        const d = await res.json().catch(() => ({}));
        if(d.error === 'user_suspended') return { __suspended: true };
      }
      return null;
    }
    return await res.json();
  } catch {
    return null;
  }
}

async function authSignOut() {
  await fetch('/auth/logout', { method: 'POST', credentials: 'include' });
}

function showAuthScreen() {
  document.getElementById('loading-overlay').classList.add('hidden');
  document.getElementById('auth-screen').classList.remove('hidden');
  applyTranslations();
}

function showApp() {
  document.getElementById('loading-overlay').classList.add('hidden');
  document.getElementById('auth-screen').classList.add('hidden');
}

async function signOut() {
  await authSignOut();
  window.location.href = '/';
}

// ── ONBOARDING ──
let _obMode = 'create';

function showOnboarding() {
  document.getElementById('loading-overlay').classList.add('hidden');
  document.getElementById('auth-screen').classList.add('hidden');
  document.getElementById('onboarding-screen').classList.remove('hidden');
  const notice = sessionStorage.getItem('_deletion_notice');
  if(notice) {
    sessionStorage.removeItem('_deletion_notice');
    const el = document.getElementById('ob-deletion-notice');
    if(el) {
      el.textContent = t('org.deleted_notice').replace('{name}', notice);
      el.style.display = '';
    }
  }
}

function obShowTab(mode) {
  _obMode = mode;
  const isJoin = mode === 'join';
  document.getElementById('ob-create-form').style.display = isJoin ? 'none' : '';
  document.getElementById('ob-join-form').style.display   = isJoin ? '' : 'none';
  document.getElementById('ob-tab-create').style.background = isJoin ? 'var(--bg2)' : 'var(--accent)';
  document.getElementById('ob-tab-create').style.color      = isJoin ? 'var(--text2)' : '#fff';
  document.getElementById('ob-tab-join').style.background   = isJoin ? 'var(--accent)' : 'var(--bg2)';
  document.getElementById('ob-tab-join').style.color        = isJoin ? '#fff' : 'var(--text2)';
}

async function obSubmit() {
  const errEl = document.getElementById(_obMode === 'create' ? 'ob-error-create' : 'ob-error-join');
  errEl.style.display = 'none';

  let url, body;
  if(_obMode === 'create') {
    const name = (document.getElementById('ob-org-name').value || '').trim();
    if(!name) { errEl.textContent = t('onboarding.err_enter_name'); errEl.style.display = ''; return; }
    url  = '/org/create';
    body = { name };
  } else {
    const org_name = (document.getElementById('ob-org-name-join').value || '').trim();
    const token    = (document.getElementById('ob-token').value || '').trim();
    if(!org_name || !token) { errEl.textContent = t('onboarding.err_enter_name_token'); errEl.style.display = ''; return; }
    url  = '/org/join';
    body = { org_name, token };
  }

  try {
    const res  = await fetch(url, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if(data.ok) {
      window.location.reload();
    } else {
      const msgs = {
        name_required:               t('onboarding.err_enter_name'),
        already_in_org:              t('onboarding.err_already_in_org'),
        invalid_token_or_name:       t('onboarding.err_invalid_token'),
        org_name_and_token_required: t('onboarding.err_enter_name_token'),
      };
      errEl.textContent = msgs[data.error] || t('onboarding.err_generic');
      errEl.style.display = '';
    }
  } catch {
    errEl.textContent = t('onboarding.err_connection');
    errEl.style.display = '';
  }
}

// ── ORG PICKER ──
function showOrgPicker(orgs) {
  document.getElementById('loading-overlay').classList.add('hidden');
  document.getElementById('auth-screen').classList.add('hidden');
  const screen = document.getElementById('org-picker-screen');
  if(screen) screen.classList.remove('hidden');
  applyTranslations();
  const list = document.getElementById('org-picker-list');
  if(!list) return;
  const roleKey = { admin: 'org.role_admin', manager: 'org.role_manager', user: 'org.role_user' };
  const roleBadgeColor = { admin: 'background:var(--accent);color:#fff', manager: 'background:#f59e0b;color:#fff', user: 'background:var(--bg3);color:var(--text2);border:1px solid var(--border)' };
  const avatarColors = ['#6366f1','#0ea5e9','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899'];
  list.innerHTML = orgs.map((o, i) => {
    const initial = (o.name || '?')[0].toUpperCase();
    const color = avatarColors[i % avatarColors.length];
    const badgeStyle = roleBadgeColor[o.role] || 'background:var(--bg3);color:var(--text2)';
    const roleText = roleKey[o.role] ? t(roleKey[o.role]) : o.role;
    return `
    <button onclick="pickOrg('${o.id}')"
      style="width:100%;padding:12px 14px;background:var(--bg2);border:1.5px solid var(--border);border-radius:var(--radius-sm);cursor:pointer;text-align:left;transition:border-color 0.12s;display:flex;align-items:center;gap:12px;box-sizing:border-box"
      onmouseenter="this.style.borderColor='var(--accent)'"
      onmouseleave="this.style.borderColor='var(--border)'">
      <div style="width:40px;height:40px;border-radius:50%;background:${color};display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:17px;font-weight:700;color:#fff">${initial}</div>
      <div style="flex:1;min-width:0">
        <div style="font-size:14px;font-weight:600;color:var(--accent);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${o.name}</div>
        <div style="margin-top:5px"><span style="font-size:11px;font-weight:600;padding:2px 8px;border-radius:10px;${badgeStyle}">${roleText}</span></div>
      </div>
      <svg width="16" height="16" fill="none" stroke="var(--text3)" stroke-width="2" viewBox="0 0 24 24" style="flex-shrink:0"><path stroke-linecap="round" stroke-linejoin="round" d="M9 18l6-6-6-6"/></svg>
    </button>`;
  }).join('');
}

async function pickOrg(orgId) {
  const res = await fetch('/org/switch', {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ org_id: orgId }),
  });
  if(res.ok) window.location.reload();
}

// ── VERIFY EMAIL SCREEN ──
function showVerifyEmailScreen(email) {
  document.getElementById('loading-overlay').classList.add('hidden');
  document.getElementById('auth-screen').classList.add('hidden');
  const desc = document.getElementById('verify-email-desc');
  if(desc) desc.textContent = t('verify.desc').replace('{email}', email);
  document.getElementById('verify-email-screen').classList.remove('hidden');
}

async function resendVerification() {
  const btn = document.getElementById('verify-resend-btn');
  const msg = document.getElementById('verify-msg');
  if(btn) btn.disabled = true;
  try {
    const res  = await fetch('/auth/resend-verification', { method: 'POST', credentials: 'include' });
    const data = await res.json();
    if(msg) {
      if(data.ok) {
        msg.style.background = 'var(--green-bg)';
        msg.style.color      = 'var(--green)';
        msg.textContent      = t('verify.resent');
      } else {
        msg.style.background = 'var(--red-bg, rgba(247,111,111,0.1))';
        msg.style.color      = 'var(--red)';
        msg.textContent      = t('auth.err_generic');
      }
      msg.style.display = '';
      setTimeout(() => { msg.style.display = 'none'; }, 4000);
    }
  } finally {
    if(btn) btn.disabled = false;
  }
}

function verifySkip() {
  document.getElementById('verify-email-screen').classList.add('hidden');
  window.location.reload();
}

// ── ACTIVATE ACCOUNT ──
let _activateToken = null;

function showActivateScreen(token) {
  _activateToken = token;
  document.getElementById('loading-overlay').classList.add('hidden');
  document.getElementById('auth-screen').classList.add('hidden');
  const screen = document.getElementById('activate-screen');
  if(screen) screen.classList.remove('hidden');
  applyTranslations();
  const p1 = document.getElementById('activate-password');
  const p2 = document.getElementById('activate-password2');
  if(p1) p1.placeholder = t('activate.password_placeholder');
  if(p2) p2.placeholder = t('activate.password2_placeholder');
}

async function activateSubmit() {
  const pwd  = (document.getElementById('activate-password').value  || '');
  const pwd2 = (document.getElementById('activate-password2').value || '');
  const err  = document.getElementById('activate-error');
  const btn  = document.getElementById('activate-submit-btn');
  err.style.display = 'none';
  if(pwd.length < 6)  { err.textContent = t('auth.err_password_too_short'); err.style.display=''; return; }
  if(pwd !== pwd2)    { err.textContent = t('activate.err_mismatch');        err.style.display=''; return; }
  btn.disabled = true;
  try {
    const res  = await fetch('/auth/activate', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: _activateToken, password: pwd }),
    });
    const data = await res.json();
    if(data.ok) {
      window.location.reload();
    } else {
      err.textContent = t('activate.err_invalid_token');
      err.style.display = '';
    }
  } catch {
    err.textContent = t('auth.err_connection');
    err.style.display = '';
  } finally {
    btn.disabled = false;
  }
}
