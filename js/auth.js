// ══════════════════════════════════════════
// AUTH — Google OAuth
// ══════════════════════════════════════════

function signInWithGoogle() {
  window.location.href = '/auth/google';
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
