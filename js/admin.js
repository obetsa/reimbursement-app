// ══════════════════════════════════════════
// ADMIN PANEL — окремий модуль /admin
// ══════════════════════════════════════════

function showToast(msg, type = 'success') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = 'toast ' + type;
  toast.innerHTML = (type === 'success' ? '✓' : '✕') + ' ' + msg;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

// ── Auth ──

async function adminCheckAuth() {
  try {
    const res = await fetch('/superadmin/stats', { credentials: 'include' });
    return res.ok;
  } catch { return false; }
}

async function adminLogin() {
  const input = document.getElementById('admin-token-input');
  const errEl = document.getElementById('admin-login-error');
  const btn   = document.getElementById('admin-login-btn');
  errEl.style.display = 'none';
  btn.disabled = true;
  try {
    const res = await fetch('/admin/login', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: input.value }),
    });
    if (res.ok) {
      showAdminPanel();
    } else {
      errEl.textContent = 'Невірний токен';
      errEl.style.display = '';
      input.value = '';
      input.focus();
    }
  } catch {
    errEl.textContent = 'Помилка з\'єднання';
    errEl.style.display = '';
  }
  btn.disabled = false;
}

async function adminLogout() {
  await fetch('/admin/logout', { method: 'POST', credentials: 'include' });
  showLoginScreen();
}

function showLoginScreen() {
  document.getElementById('admin-login-screen').style.display = 'flex';
  document.getElementById('admin-main').style.display = 'none';
}

function showAdminPanel() {
  document.getElementById('admin-login-screen').style.display = 'none';
  document.getElementById('admin-main').style.display = 'block';
  loadSuperadmin();
}

// ── Tabs ──

function saTab(name) {
  const tabs     = { orgs: 'sa-tab-orgs',     users: 'sa-tab-users'     };
  const contents = { orgs: 'sa-orgs-content', users: 'sa-users-content' };
  Object.keys(tabs).forEach(k => {
    const btn = document.getElementById(tabs[k]);
    const cnt = document.getElementById(contents[k]);
    const active = k === name;
    if (btn) { btn.style.color = active ? 'var(--accent)' : 'var(--text3)'; btn.style.borderBottomColor = active ? 'var(--accent)' : 'transparent'; }
    if (cnt) cnt.style.display = active ? '' : 'none';
  });
  const btnOrg  = document.getElementById('sa-btn-new-org');
  const btnUser = document.getElementById('sa-btn-new-user');
  if (btnOrg)  btnOrg.style.display  = name === 'orgs'  ? '' : 'none';
  if (btnUser) btnUser.style.display = name === 'users' ? '' : 'none';
  if (name === 'users') loadSAUsers();
}

// ── Create User Modal ──

function openCreateSAUserModal() {
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
  overlay.innerHTML = `
    <div style="background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:28px;max-width:400px;width:100%">
      <div style="font-size:15px;font-weight:600;color:var(--text);margin-bottom:20px">${t('superadmin.create_user_title')}</div>
      <div style="margin-bottom:12px">
        <div style="font-size:12px;color:var(--text3);margin-bottom:4px">Email *</div>
        <input id="_sau_email" type="email" placeholder="user@example.com"
          style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg3);color:var(--text);font-size:13px;box-sizing:border-box">
      </div>
      <div style="margin-bottom:16px">
        <div style="font-size:12px;color:var(--text3);margin-bottom:4px">${t('superadmin.col_fullname')}</div>
        <input id="_sau_name" type="text"
          style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg3);color:var(--text);font-size:13px;box-sizing:border-box">
      </div>
      <div style="margin-bottom:16px">
        <div style="font-size:12px;color:var(--text3);margin-bottom:8px">${t('superadmin.create_user_mode')}</div>
        <div style="display:flex;gap:8px">
          <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px;color:var(--text)">
            <input type="radio" name="_sau_mode" value="invite" checked onchange="saUserModeChange()"> ${t('superadmin.mode_invite')}
          </label>
          <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px;color:var(--text)">
            <input type="radio" name="_sau_mode" value="password" onchange="saUserModeChange()"> ${t('superadmin.mode_password')}
          </label>
        </div>
      </div>
      <div id="_sau_pwd_block" style="display:none;margin-bottom:16px">
        <div style="font-size:12px;color:var(--text3);margin-bottom:4px">${t('superadmin.create_user_pwd')}</div>
        <input id="_sau_pwd" type="password" placeholder="min 6 символів"
          style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg3);color:var(--text);font-size:13px;box-sizing:border-box">
      </div>
      <div id="_sau_error" style="display:none;color:var(--red);font-size:12px;margin-bottom:10px"></div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button id="_sau_cancel" class="btn btn-ghost">${t('org.delete_permanent_cancel')}</button>
        <button id="_sau_submit" class="btn btn-primary">${t('superadmin.create_user_btn')}</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector('#_sau_cancel').onclick = () => overlay.remove();
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  overlay.querySelector('#_sau_submit').onclick = async () => {
    const email    = overlay.querySelector('#_sau_email').value.trim();
    const fullName = overlay.querySelector('#_sau_name').value.trim();
    const mode     = overlay.querySelector('input[name="_sau_mode"]:checked').value;
    const password = overlay.querySelector('#_sau_pwd').value;
    const errEl    = overlay.querySelector('#_sau_error');
    errEl.style.display = 'none';
    if (!email) { errEl.textContent = t('superadmin.err_email_required'); errEl.style.display = ''; return; }
    if (mode === 'password' && password.length < 6) { errEl.textContent = t('superadmin.err_pwd_short'); errEl.style.display = ''; return; }
    const btn = overlay.querySelector('#_sau_submit');
    btn.disabled = true;
    const res = await fetch('/superadmin/users', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, full_name: fullName, mode, password }),
    });
    btn.disabled = false;
    if (res.ok) {
      overlay.remove();
      showToast(t('superadmin.create_user_toast'), 'success');
      loadSAUsers();
    } else {
      const d = await res.json();
      errEl.textContent = d.error === 'email_exists' ? t('superadmin.err_email_exists') : t('toast.error');
      errEl.style.display = '';
    }
  };
  setTimeout(() => overlay.querySelector('#_sau_email').focus(), 50);
}

function saUserModeChange() {
  const mode  = document.querySelector('input[name="_sau_mode"]:checked')?.value;
  const block = document.getElementById('_sau_pwd_block');
  if (block) block.style.display = mode === 'password' ? '' : 'none';
}

// ── Users ──

async function superadminToggleUserSuspend(userId, suspend, email) {
  const action = suspend ? 'suspend' : 'unsuspend';
  const res = await fetch(`/superadmin/users/${userId}/${action}`, { method: 'POST', credentials: 'include' });
  if (res.ok) { showToast(t(suspend ? 'superadmin.suspend_user_toast' : 'superadmin.unsuspend_user_toast'), 'success'); loadSAUsers(); }
  else showToast(t('toast.error'), 'error');
}

function superadminDeleteUser(userId, email) {
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
  overlay.innerHTML = `
    <div style="background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:28px;max-width:400px;width:100%">
      <div style="font-size:15px;font-weight:600;color:var(--text);margin-bottom:8px">${t('superadmin.delete_user_title')}</div>
      <div style="font-size:13px;color:var(--text2);margin-bottom:16px">${t('superadmin.delete_user_desc').replace('{email}', email)}</div>
      <input id="_sud_input" type="text" placeholder="${email}"
        style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg3);color:var(--text);font-size:13px;box-sizing:border-box;margin-bottom:16px">
      <div id="_sud_error" style="display:none;color:var(--red);font-size:12px;margin-bottom:10px"></div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button id="_sud_cancel" class="btn btn-ghost">${t('org.delete_permanent_cancel')}</button>
        <button id="_sud_confirm" class="btn btn-danger" disabled style="opacity:0.4">${t('superadmin.delete_user_btn')}</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  const input      = overlay.querySelector('#_sud_input');
  const confirmBtn = overlay.querySelector('#_sud_confirm');
  input.addEventListener('input', () => {
    const match = input.value.trim() === email;
    confirmBtn.disabled = !match;
    confirmBtn.style.opacity = match ? '1' : '0.4';
  });
  overlay.querySelector('#_sud_cancel').onclick = () => overlay.remove();
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  confirmBtn.onclick = async () => {
    confirmBtn.disabled = true;
    const res = await fetch(`/superadmin/users/${userId}`, { method: 'DELETE', credentials: 'include' });
    overlay.remove();
    if (res.ok) { showToast(t('superadmin.delete_user_toast'), 'success'); loadSAUsers(); }
    else showToast(t('toast.error'), 'error');
  };
  setTimeout(() => input.focus(), 50);
}

let _saUsers = [];

async function loadSAUsers() {
  const el = document.getElementById('superadmin-users-list');
  if (!el) return;
  try {
    const res = await fetch('/superadmin/users', { credentials: 'include' });
    if (!res.ok) { el.innerHTML = `<div style="padding:40px;text-align:center;color:var(--red)">${t('toast.forbidden')}</div>`; return; }
    _saUsers = await res.json();
    superadminUsersFilter();
  } catch { el.innerHTML = `<div style="padding:40px;text-align:center;color:var(--red)">${t('toast.error')}</div>`; }
}

function superadminUsersFilter() {
  const q      = (document.getElementById('sa-users-search')?.value || '').trim().toLowerCase();
  const status = document.getElementById('sa-users-status')?.value || '';
  const sort   = document.getElementById('sa-users-sort')?.value   || 'registered_desc';

  let list = _saUsers.filter(u => {
    if (q && !u.email.toLowerCase().includes(q) && !(u.full_name || '').toLowerCase().includes(q)) return false;
    if (status === 'blocked') return !!u.is_suspended;
    if (status && status !== 'blocked') return u.status === status && !u.is_suspended;
    return true;
  });

  list = list.slice().sort((a, b) => {
    if (sort === 'email_asc')      return (a.email || '').localeCompare(b.email || '');
    if (sort === 'email_desc')     return (b.email || '').localeCompare(a.email || '');
    if (sort === 'registered_asc') return (a.registered_at || '').localeCompare(b.registered_at || '');
    return (b.registered_at || '').localeCompare(a.registered_at || '');
  });

  _renderSAUsers(list);
}

function _renderSAUsers(users) {
  const el = document.getElementById('superadmin-users-list');
  if (!el) return;
  if (!users.length) { el.innerHTML = `<div style="padding:40px;text-align:center;color:var(--text3)">${t('superadmin.no_users')}</div>`; return; }
  const statusStyle = { active: 'background:#dcfce7;color:#16a34a', pending: 'background:#fef9c3;color:#b45309', unverified: 'background:var(--bg3);color:var(--text3)' };
  const statusLabel = { active: t('superadmin.status_active'), pending: t('superadmin.status_pending'), unverified: t('superadmin.status_unverified') };
  const isMobile = window.innerWidth <= 768;
  if (isMobile) {
    el.innerHTML = users.map(u => `
      <div style="background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius-sm);padding:14px;margin-bottom:10px">
        <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:8px;margin-bottom:4px">
          <div>
            <div style="font-size:13px;font-weight:600;color:var(--text)">${u.email}${u.is_suspended ? ` <span style="font-size:10px;background:var(--red);color:#fff;border-radius:4px;padding:1px 5px">blocked</span>` : ''}</div>
            ${u.full_name ? `<div style="font-size:12px;color:var(--text2);margin-top:2px">${u.full_name}</div>` : ''}
          </div>
          <span style="font-size:10px;font-weight:600;padding:2px 7px;border-radius:10px;flex-shrink:0;${statusStyle[u.status]}">${statusLabel[u.status]}</span>
        </div>
        <div style="font-size:11px;color:var(--text3);display:flex;gap:8px;flex-wrap:wrap;margin-top:6px;margin-bottom:8px">
          ${u.is_superadmin ? `<span style="background:var(--accent);color:#fff;padding:1px 6px;border-radius:4px;font-size:10px;font-weight:600">SA</span>` : ''}
          ${u.orgs.length ? `<span>${u.orgs.join(', ')}</span>` : `<span style="color:var(--text3)">${t('superadmin.no_org')}</span>`}
          ${u.registered_at ? `<span>${u.registered_at.slice(0, 10)}</span>` : ''}
        </div>
        ${!u.is_superadmin ? `<div style="display:flex;gap:4px">
          ${u.is_suspended
            ? `<button class="btn btn-secondary" style="font-size:11px;padding:3px 8px" onclick="superadminToggleUserSuspend('${u.id}',false,'${u.email.replace(/'/g, "\\'")}')">▶ ${t('superadmin.unsuspend_user_btn')}</button>`
            : `<button class="btn btn-secondary" style="font-size:11px;padding:3px 8px;opacity:0.7" onclick="superadminToggleUserSuspend('${u.id}',true,'${u.email.replace(/'/g, "\\'")}')">⏸ ${t('superadmin.suspend_user_btn')}</button>`
          }
          <button class="btn btn-danger" style="font-size:11px;padding:3px 8px" onclick="superadminDeleteUser('${u.id}','${u.email.replace(/'/g, "\\'")}')">🗑</button>
        </div>` : ''}
      </div>`).join('');
  } else {
    el.innerHTML = `
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead>
          <tr style="border-bottom:2px solid var(--border);color:var(--text3);font-size:11px;font-weight:600">
            <th style="padding:10px 12px;text-align:left">${t('superadmin.col_email')}</th>
            <th style="padding:10px 12px;text-align:left">${t('superadmin.col_fullname')}</th>
            <th style="padding:10px 12px;text-align:left">${t('superadmin.col_status')}</th>
            <th style="padding:10px 12px;text-align:left">${t('superadmin.col_orgs')}</th>
            <th style="padding:10px 12px;text-align:left">${t('superadmin.col_registered')}</th>
            <th style="padding:10px 12px;text-align:center"></th>
          </tr>
        </thead>
        <tbody>
          ${users.map(u => `
          <tr style="border-bottom:1px solid var(--border)">
            <td style="padding:10px 12px;color:var(--text)">
              ${u.is_superadmin ? `<span style="background:var(--accent);color:#fff;padding:1px 5px;border-radius:3px;font-size:10px;font-weight:700;margin-right:5px">SA</span>` : ''}
              ${u.email}
              ${u.is_suspended ? `<span style="font-size:10px;background:var(--red);color:#fff;border-radius:4px;padding:1px 5px;margin-left:4px">blocked</span>` : ''}
            </td>
            <td style="padding:10px 12px;color:var(--text2)">${u.full_name || '—'}</td>
            <td style="padding:10px 12px"><span style="font-size:11px;font-weight:600;padding:2px 8px;border-radius:10px;${statusStyle[u.status]}">${statusLabel[u.status]}</span></td>
            <td style="padding:10px 12px;color:var(--text2);font-size:12px">${u.orgs.length ? u.orgs.join(', ') : `<span style="color:var(--text3)">—</span>`}</td>
            <td style="padding:10px 12px;color:var(--text3);font-size:11px">${u.registered_at ? u.registered_at.slice(0, 10) : '—'}</td>
            <td style="padding:6px 12px;text-align:center;white-space:nowrap">
              ${!u.is_superadmin ? `
              ${u.is_suspended
                ? `<button class="btn btn-secondary" style="font-size:11px;padding:3px 8px;margin-right:4px" onclick="superadminToggleUserSuspend('${u.id}',false,'${u.email.replace(/'/g, "\\'")}')">▶ ${t('superadmin.unsuspend_user_btn')}</button>`
                : `<button class="btn btn-secondary" style="font-size:11px;padding:3px 8px;margin-right:4px;opacity:0.7" onclick="superadminToggleUserSuspend('${u.id}',true,'${u.email.replace(/'/g, "\\'")}')">⏸ ${t('superadmin.suspend_user_btn')}</button>`
              }
              <button class="btn btn-danger" style="font-size:11px;padding:3px 8px" onclick="superadminDeleteUser('${u.id}','${u.email.replace(/'/g, "\\'")}')">🗑</button>
              ` : '—'}
            </td>
          </tr>`).join('')}
        </tbody>
      </table>`;
  }
}

// ── Orgs ──

let _saOrgs = [];

async function loadSuperadmin() {
  const el = document.getElementById('superadmin-orgs-list');
  if (!el) return;
  try {
    const [res, statsRes] = await Promise.all([
      fetch('/superadmin/orgs',  { credentials: 'include' }),
      fetch('/superadmin/stats', { credentials: 'include' }),
    ]);
    if (!res.ok) { el.innerHTML = `<div style="padding:40px;text-align:center;color:var(--red)">${t('toast.forbidden')}</div>`; return; }
    const orgs  = await res.json();
    const stats = statsRes.ok ? await statsRes.json() : null;
    if (stats) {
      const statsEl = document.getElementById('superadmin-stats');
      if (statsEl) {
        const cards = [
          { label: t('superadmin.stats_orgs'),    value: stats.total_orgs },
          { label: t('superadmin.stats_users'),   value: stats.active_users },
          { label: t('superadmin.stats_records'), value: stats.total_records },
          { label: t('superadmin.stats_storage'), value: stats.total_storage_mb + ' MB' },
        ];
        statsEl.innerHTML = cards.map(c => `
          <div style="flex:1;min-width:120px;background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius-sm);padding:14px 18px">
            <div style="font-size:22px;font-weight:600;color:var(--text)">${c.value}</div>
            <div style="font-size:11px;color:var(--text3);margin-top:4px">${c.label}</div>
          </div>`).join('');
      }
    }
    _saOrgs = orgs;
    _renderSAOrgs(orgs);
  } catch (e) { el.innerHTML = `<div style="padding:40px;text-align:center;color:var(--red)">${t('toast.error')}: ${e.message}</div>`; }
}

function superadminFilter(q) {
  const f = q.trim().toLowerCase();
  _renderSAOrgs(f ? _saOrgs.filter(o =>
    o.name.toLowerCase().includes(f) || o.owner_email.toLowerCase().includes(f)
  ) : _saOrgs);
}

function _renderSAOrgs(orgs) {
  const el = document.getElementById('superadmin-orgs-list');
  if (!el) return;
  if (!orgs.length) {
    el.innerHTML = `<div style="padding:40px;text-align:center;color:var(--text3)">${t('superadmin.no_orgs')}</div>`;
    return;
  }
  const isMobile = window.innerWidth <= 768;
  if (isMobile) {
    el.innerHTML = orgs.map(o => `
      <div style="background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius-sm);padding:14px;margin-bottom:10px">
        <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:8px;margin-bottom:8px">
          <div>
            <span style="font-size:14px;font-weight:600;color:var(--text)">${o.name}</span>
            ${o.is_suspended ? `<span style="font-size:10px;background:var(--red);color:#fff;border-radius:4px;padding:1px 5px;margin-left:6px">suspended</span>` : ''}
          </div>
          <div style="display:flex;gap:4px;flex-shrink:0">
            <button class="btn" style="font-size:11px;padding:3px 8px;background:${(o.plan || 'free') === 'pro' ? 'var(--accent)' : 'var(--bg3)'};color:${(o.plan || 'free') === 'pro' ? '#fff' : 'var(--text2)'};border:1px solid var(--border)"
              onclick="superadminToggleOrgPlan('${o.id}','${o.plan || 'free'}')">${(o.plan || 'free').toUpperCase()}</button>
            ${o.is_suspended
              ? `<button class="btn btn-secondary" style="font-size:11px;padding:3px 8px"
                  onclick="superadminToggleSuspend('${o.id}',false,'${o.name.replace(/'/g, "\\'")}')">▶</button>`
              : `<button class="btn btn-secondary" style="font-size:11px;padding:3px 8px;opacity:0.7"
                  onclick="superadminToggleSuspend('${o.id}',true,'${o.name.replace(/'/g, "\\'")}')">⏸</button>`
            }
            <button class="btn btn-danger" style="font-size:11px;padding:3px 8px"
              onclick="superadminDeleteOrg('${o.id}','${o.name.replace(/'/g, "\\'")}')">🗑</button>
          </div>
        </div>
        <div style="font-size:12px;color:var(--text2);margin-bottom:6px">${o.owner_email}</div>
        <div style="display:flex;gap:16px;font-size:11px;color:var(--text3);flex-wrap:wrap">
          <span>${t('superadmin.col_members')}: <strong style="color:var(--text2)">${o.members_count}</strong></span>
          ${o.pending_count > 0 ? `<span>${t('superadmin.col_pending')}: <strong style="color:var(--yellow,#f59e0b)">${o.pending_count}</strong></span>` : ''}
          <span>${t('superadmin.col_records')}: <strong style="color:var(--text2)">${o.records_count}</strong></span>
          <span>${t('superadmin.col_last_activity')}: <strong style="color:var(--text2)">${o.last_activity ? o.last_activity.slice(0, 10) : '—'}</strong></span>
          ${o.storage_mb > 0 ? `<span>${t('superadmin.col_storage')}: <strong style="color:var(--text2)">${o.storage_mb} MB</strong></span>` : ''}
          <span>${o.created_at ? o.created_at.slice(0, 10) : '—'}</span>
        </div>
      </div>`).join('');
  } else {
    el.innerHTML = `
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead>
          <tr style="border-bottom:2px solid var(--border);color:var(--text3);font-size:11px;font-weight:600">
            <th style="padding:10px 12px;text-align:left">${t('superadmin.col_name')}</th>
            <th style="padding:10px 12px;text-align:left">${t('superadmin.col_admin')}</th>
            <th style="padding:10px 12px;text-align:center">${t('superadmin.col_members')}</th>
            <th style="padding:10px 12px;text-align:center">${t('superadmin.col_pending')}</th>
            <th style="padding:10px 12px;text-align:center">${t('superadmin.col_records')}</th>
            <th style="padding:10px 12px;text-align:left">${t('superadmin.col_last_activity')}</th>
            <th style="padding:10px 12px;text-align:right">${t('superadmin.col_storage')}</th>
            <th style="padding:10px 12px;text-align:left">${t('superadmin.col_created')}</th>
            <th style="padding:10px 12px;text-align:center"></th>
          </tr>
        </thead>
        <tbody>
          ${orgs.map(o => `
            <tr style="border-bottom:1px solid var(--border)">
              <td style="padding:10px 12px;font-weight:500;color:var(--text)">${o.name}</td>
              <td style="padding:10px 12px;color:var(--text2)">${o.owner_email}</td>
              <td style="padding:10px 12px;text-align:center">${o.members_count}</td>
              <td style="padding:10px 12px;text-align:center">${o.pending_count > 0 ? `<span style="color:var(--yellow,#f59e0b);font-weight:600">${o.pending_count}</span>` : '<span style="color:var(--text3)">—</span>'}</td>
              <td style="padding:10px 12px;text-align:center">${o.records_count}</td>
              <td style="padding:10px 12px;color:var(--text3);font-size:11px">${o.last_activity ? o.last_activity.slice(0, 10) : '—'}</td>
              <td style="padding:10px 12px;text-align:right;font-size:11px;color:var(--text3)">${o.storage_mb > 0 ? o.storage_mb + ' MB' : '—'}</td>
              <td style="padding:10px 12px;color:var(--text3);font-size:11px">${o.created_at ? o.created_at.slice(0, 10) : '—'}</td>
              <td style="padding:6px 12px;text-align:center;white-space:nowrap">
                <button class="btn" style="font-size:11px;padding:3px 10px;margin-right:4px;background:${(o.plan || 'free') === 'pro' ? 'var(--accent)' : 'var(--bg3)'};color:${(o.plan || 'free') === 'pro' ? '#fff' : 'var(--text2)'};border:1px solid var(--border)"
                  onclick="superadminToggleOrgPlan('${o.id}','${o.plan || 'free'}')">${(o.plan || 'free').toUpperCase()}</button>
                ${o.is_suspended
                  ? `<button class="btn btn-secondary" style="font-size:11px;padding:3px 8px;margin-right:4px"
                      onclick="superadminToggleSuspend('${o.id}',false,'${o.name.replace(/'/g, "\\'")}')">▶ ${t('superadmin.unsuspend_btn')}</button>`
                  : `<button class="btn btn-secondary" style="font-size:11px;padding:3px 8px;margin-right:4px;opacity:0.7"
                      onclick="superadminToggleSuspend('${o.id}',true,'${o.name.replace(/'/g, "\\'")}')">⏸ ${t('superadmin.suspend_btn')}</button>`
                }
                <button class="btn btn-danger" style="font-size:11px;padding:3px 8px"
                  onclick="superadminDeleteOrg('${o.id}','${o.name.replace(/'/g, "\\'")}')">${t('superadmin.delete_org_btn')}</button>
              </td>
            </tr>`).join('')}
        </tbody>
      </table>`;
  }
}

function openCreateOrgModal() {
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
  overlay.innerHTML = `
    <div style="background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:28px;max-width:400px;width:100%">
      <div style="font-size:15px;font-weight:600;color:var(--text);margin-bottom:20px">${t('superadmin.create_org_title')}</div>
      <div style="margin-bottom:10px">
        <div style="font-size:12px;color:var(--text3);margin-bottom:4px">${t('superadmin.org_name_label')} *</div>
        <input id="_sa_org_name" type="text" placeholder="${t('superadmin.org_name_placeholder')}"
          style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg3);color:var(--text);font-size:13px;box-sizing:border-box">
      </div>
      <div style="margin-bottom:10px">
        <div style="font-size:12px;color:var(--text3);margin-bottom:4px">${t('superadmin.admin_email_label')} *</div>
        <input id="_sa_admin_email" type="email" placeholder="admin@example.com"
          style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg3);color:var(--text);font-size:13px;box-sizing:border-box">
      </div>
      <div style="margin-bottom:20px">
        <div style="font-size:12px;color:var(--text3);margin-bottom:4px">${t('superadmin.admin_name_label')}</div>
        <input id="_sa_admin_name" type="text"
          style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg3);color:var(--text);font-size:13px;box-sizing:border-box">
      </div>
      <div id="_sa_error" style="display:none;color:var(--red);font-size:12px;margin-bottom:10px"></div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button id="_sa_cancel" class="btn btn-ghost">${t('org.delete_permanent_cancel')}</button>
        <button id="_sa_submit" class="btn btn-primary">${t('superadmin.create_btn')}</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  const orgInput   = overlay.querySelector('#_sa_org_name');
  const emailInput = overlay.querySelector('#_sa_admin_email');
  const nameInput  = overlay.querySelector('#_sa_admin_name');
  const errEl      = overlay.querySelector('#_sa_error');
  const submitBtn  = overlay.querySelector('#_sa_submit');
  overlay.querySelector('#_sa_cancel').onclick = () => overlay.remove();
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  submitBtn.onclick = async () => {
    const org_name    = orgInput.value.trim();
    const admin_email = emailInput.value.trim();
    const admin_name  = nameInput.value.trim();
    if (!org_name || !admin_email) {
      errEl.textContent = t('superadmin.err_required');
      errEl.style.display = '';
      return;
    }
    submitBtn.disabled = true;
    try {
      const res  = await fetch('/superadmin/orgs', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ org_name, admin_email, admin_name }),
      });
      const data = await res.json();
      if (data.ok) {
        overlay.remove();
        showToast(data.existing_user ? t('superadmin.created_existing_user') : t('superadmin.created_toast'), 'success');
        loadSuperadmin();
      } else {
        const msgs = {
          org_name_taken:        t('superadmin.err_name_taken'),
          admin_already_in_org:  t('superadmin.err_admin_in_org'),
          org_name_and_admin_email_required: t('superadmin.err_required'),
        };
        errEl.textContent = msgs[data.error] || t('toast.error');
        errEl.style.display = '';
      }
    } catch { errEl.textContent = t('auth.err_connection'); errEl.style.display = ''; }
    finally  { submitBtn.disabled = false; }
  };
  setTimeout(() => orgInput.focus(), 50);
}

async function superadminToggleOrgPlan(orgId, currentPlan) {
  const newPlan = currentPlan === 'pro' ? 'free' : 'pro';
  const res = await fetch(`/superadmin/orgs/${orgId}/set-plan`, {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ plan: newPlan }),
  });
  if (res.ok) {
    showToast(t('superadmin.plan_changed_toast').replace('{plan}', newPlan.toUpperCase()), 'success');
    loadSuperadmin();
  } else {
    showToast(t('toast.error'), 'error');
  }
}

async function superadminToggleSuspend(orgId, suspend, orgName) {
  const action = suspend ? 'suspend' : 'unsuspend';
  const res = await fetch(`/superadmin/orgs/${orgId}/${action}`, { method: 'POST', credentials: 'include' });
  if (res.ok) {
    showToast(t(suspend ? 'superadmin.suspend_toast' : 'superadmin.unsuspend_toast'), suspend ? 'error' : 'success');
    loadSuperadmin();
  } else {
    showToast(t('toast.error'), 'error');
  }
}

function superadminDeleteOrg(orgId, orgName) {
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
  overlay.innerHTML = `
    <div style="background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:28px;max-width:400px;width:100%">
      <div style="font-size:15px;font-weight:600;color:var(--text);margin-bottom:8px">${t('superadmin.delete_org_title')}</div>
      <div style="font-size:13px;color:var(--text2);margin-bottom:16px">${t('superadmin.delete_org_desc').replace('{name}', orgName)}</div>
      <input id="_sa_del_input" type="text" placeholder="${orgName}"
        style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg3);color:var(--text);font-size:13px;box-sizing:border-box;margin-bottom:16px">
      <div id="_sa_del_error" style="display:none;color:var(--red);font-size:12px;margin-bottom:10px"></div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button id="_sa_del_cancel" class="btn btn-ghost">${t('org.delete_permanent_cancel')}</button>
        <button id="_sa_del_confirm" class="btn btn-danger" disabled style="opacity:0.4">${t('superadmin.delete_org_btn')}</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  const input      = overlay.querySelector('#_sa_del_input');
  const confirmBtn = overlay.querySelector('#_sa_del_confirm');
  input.addEventListener('input', () => {
    const match = input.value.trim() === orgName;
    confirmBtn.disabled = !match;
    confirmBtn.style.opacity = match ? '1' : '0.4';
  });
  overlay.querySelector('#_sa_del_cancel').onclick = () => overlay.remove();
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  confirmBtn.onclick = async () => {
    confirmBtn.disabled = true;
    const res = await fetch(`/superadmin/orgs/${orgId}`, { method: 'DELETE', credentials: 'include' });
    overlay.remove();
    if (res.ok) { showToast(t('superadmin.delete_org_toast'), 'success'); loadSuperadmin(); }
    else        showToast(t('toast.error'), 'error');
  };
  setTimeout(() => input.focus(), 50);
}

// ── Init ──

document.addEventListener('DOMContentLoaded', async () => {
  applyTranslations();
  document.getElementById('admin-token-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') adminLogin();
  });
  const authed = await adminCheckAuth();
  if (authed) {
    showAdminPanel();
  }
  // else: login screen is already visible by default
});
