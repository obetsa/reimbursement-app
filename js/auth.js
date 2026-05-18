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
      window.location.reload();
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
    if (!res.ok) return null;
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
