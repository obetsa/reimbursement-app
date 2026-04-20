// ══════════════════════════════════════════
// AUTH — Local
// ══════════════════════════════════════════
let authMode = 'login';

function switchAuthTab(mode) {
  authMode = mode;
  document.getElementById('tab-login').classList.toggle('active', mode === 'login');
  document.getElementById('tab-register').classList.toggle('active', mode === 'register');
  document.getElementById('auth-name-group').style.display = mode === 'register' ? '' : 'none';
  document.getElementById('auth-submit-btn').textContent = mode === 'login' ? t('auth.submit_login') : t('auth.submit_register');
  document.getElementById('auth-error').classList.remove('show');
  document.getElementById('auth-error').style = '';
}

async function handleAuth() {
  const email = document.getElementById('auth-email').value.trim();
  const password = document.getElementById('auth-password').value;
  const btn = document.getElementById('auth-submit-btn');

  if(!email || !password) {
    showAuthError(t('toast.fill_required'));
    return;
  }

  btn.disabled = true;
  btn.textContent = authMode === 'login' ? t('auth.processing_login') : t('auth.processing_register');
  document.getElementById('auth-error').classList.remove('show');

  try {
    let user;
    if(authMode === 'login') {
      user = await authLogin(email, password);
    } else {
      const name = document.getElementById('auth-name').value.trim();
      user = await authRegister(email, password, name);
    }
    await initApp(user);
  } catch(e) {
    showAuthError(e.message || t('toast.connection_error'));
    btn.disabled = false;
    btn.textContent = authMode === 'login' ? t('auth.submit_login') : t('auth.submit_register');
  }
}

function showAuthError(msg) {
  const el = document.getElementById('auth-error');
  el.textContent = msg;
  el.style = '';
  el.classList.add('show');
}

async function signOut() {
  authSignOut();
  currentUser = null;
  sampleDocs.length = 0;
  document.getElementById('auth-screen').classList.remove('hidden');
  document.getElementById('auth-email').value = '';
  document.getElementById('auth-password').value = '';
}

function showAuthScreen() {
  document.getElementById('loading-overlay').classList.add('hidden');
  document.getElementById('auth-screen').classList.remove('hidden');
}

function showApp() {
  document.getElementById('loading-overlay').classList.add('hidden');
  document.getElementById('auth-screen').classList.add('hidden');
}