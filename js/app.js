const DRIVE_ENABLED = false;

function _errMsg(e) {
  const m = (e && e.message) || '';
  if(m.includes('forbidden') || m.includes('no_org')) return t('toast.forbidden');
  return t('toast.error');
}

document.addEventListener('DOMContentLoaded', () => {
  if(!DRIVE_ENABLED) {
    document.querySelectorAll('.drive-only').forEach(el => el.style.display = 'none');
  }
});

// ══════════════════════════════════════════
// INIT APP
// ══════════════════════════════════════════
let currentOrg = null;

async function initApp(user) {
  currentUser = user;

  // Update sidebar
  const email = user.email || '';
  const sidebarEmail = document.getElementById('sidebar-email');
  const sidebarAvatar = document.getElementById('sidebar-avatar');
  if(sidebarEmail) sidebarEmail.textContent = email;
  if(sidebarAvatar) sidebarAvatar.textContent = email[0].toUpperCase();

  // Load org info
  try {
    const orgRes = await fetch('/org/me', { credentials: 'include' });
    if(orgRes.ok) {
      currentOrg = await orgRes.json();
      const orgEl = document.getElementById('sidebar-org-name');
      if(orgEl) orgEl.textContent = currentOrg.name;
      if(currentOrg.role === 'admin') {
        const navEl = document.getElementById('nav-org-members');
        if(navEl) navEl.style.display = '';
      }
    }
  } catch { }

  // Load data
  try {
    const [records, archived, companies, instruments] = await Promise.all([
      loadRecords(),
      loadArchivedRecords(),
      loadCompanies(),
      loadInstruments()
    ]);

    sampleDocs.length = 0;
    records.forEach(r => sampleDocs.push(r));
    filteredDocs = [...sampleDocs];

    archivedDocs.length = 0;
    archived.forEach(r => archivedDocs.push(r));
    filteredArchived = [...archivedDocs];

    // Populate company dropdowns
    populateCompanyDropdowns(companies);
    populateInstrumentDropdowns(instruments);

    renderDocs();
    updateDashboard();
    await updateBadges();
    loadUnprocessed();
    applyRoleRestrictions();
    showApp();
  } catch(e) {
    console.error('initApp error', e);
    showApp();
    showToast(t('toast.load_error'), 'error');
  }
}

function canWrite() {
  return currentOrg && currentOrg.role !== 'user';
}

function applyRoleRestrictions() {
  const w = canWrite();
  document.querySelectorAll('[onclick="openModal()"]').forEach(el => el.style.display = w ? '' : 'none');
  const addComp = document.querySelector('[onclick="openCompanyModal()"]');
  if(addComp) addComp.style.display = w ? '' : 'none';
  const addInstr = document.querySelector('[onclick="openInstrumentModal()"]');
  if(addInstr) addInstr.style.display = w ? '' : 'none';
  const detailEditBtn = document.querySelector('.detail-header-actions .btn');
  if(detailEditBtn) detailEditBtn.style.display = w ? '' : 'none';
  const dangerActions = document.querySelector('.danger-actions');
  if(dangerActions) dangerActions.style.display = w ? '' : 'none';
}

function _showVerifyBanner() {
  if(document.getElementById('verify-banner')) return;
  const banner = document.createElement('div');
  banner.id        = 'verify-banner';
  banner.className = 'verify-banner';
  banner.innerHTML = `<span>${t('verify.banner')} — <a href="#" onclick="event.preventDefault();resendVerificationFromApp(this)" style="color:var(--accent);text-decoration:underline">${t('verify.banner_resend')}</a></span>
    <button onclick="this.parentElement.remove()" style="background:none;border:none;color:var(--yellow);cursor:pointer;font-size:18px;line-height:1;padding:0 2px">✕</button>`;
  const content = document.querySelector('#page-dashboard .content');
  if(content) content.prepend(banner);
}

async function resendVerificationFromApp(linkEl) {
  if(linkEl) { linkEl.textContent = t('verify.sending'); linkEl.style.pointerEvents = 'none'; }
  const res = await fetch('/auth/resend-verification', { method: 'POST', credentials: 'include' });
  if(res.ok) showToast(t('verify.resent'), 'success');
  else       showToast(t('auth.err_generic'), 'error');
  if(linkEl) { linkEl.textContent = t('verify.banner_resend'); linkEl.style.pointerEvents = ''; }
}

function populateCompanyDropdowns(companies) {
  // Form dropdown (uses id)
  const formEl = document.getElementById('field-company');
  if(formEl) {
    const cur = formEl.value;
    formEl.innerHTML = `<option value="" data-i18n="form.select">${t('form.select')}</option>`;
    companies.filter(c => c.is_active).forEach(c => {
      formEl.innerHTML += `<option value="${c.id}">${c.name}</option>`;
    });
    formEl.value = cur;
  }

  // Filter dropdown (uses name)
  const filterEl = document.getElementById('docs-filter-company');
  if(filterEl) {
    const cur = filterEl.value;
    filterEl.innerHTML = `<option value="" data-i18n="docs.all_companies">${t('docs.all_companies')}</option>`;
    companies.filter(c => c.is_active).forEach(c => {
      filterEl.innerHTML += `<option value="${c.name}">${c.name}</option>`;
    });
    filterEl.value = cur;
  }
}

function populateInstrumentDropdowns(instruments) {
  const el = document.getElementById('field-card');
  if(!el) return;
  const cur = el.value;
  el.innerHTML = `<option value="" data-i18n="form.select_card">${t('form.select_card')}</option>`;
  instruments.filter(i => i.is_active).forEach(i => {
    el.innerHTML += `<option value="${i.id}">${i.name}</option>`;
  });
  el.value = cur;
}

// ══════════════════════════════════════════
// DASHBOARD ANALYTICS
// ══════════════════════════════════════════
function updateDashboard() {
  const active = sampleDocs.filter(d => !d.isArchived && !d.isDeleted);
  const waiting = active.filter(d => d.status === 'waiting');
  const partial = active.filter(d => d.status === 'partial');
  const done    = active.filter(d => d.status === 'done');
  const noReturn = active.filter(d => d.status === 'no-return');
  const totalRemainder = active.reduce((s, d) => s + (d.remainder || 0), 0);

  // ── Hero ──
  const heroEl = document.querySelector('.dash-hero-amount');
  if(heroEl) heroEl.innerHTML = `<span>€</span>${totalRemainder.toFixed(2)}`;

  const heroSub = document.querySelector('.dash-hero-sub');
  if(heroSub) {
    const companies = [...new Set(active.filter(d=>d.remainder>0).map(d=>d.company))].length;
    heroSub.innerHTML = `<span data-i18n="dash.hero_by">${t('dash.hero_by')}</span> <strong>${companies} <span data-i18n="dash.hero_companies_unit">${t('dash.hero_companies_unit')}</span></strong> · ${active.length} <span data-i18n="dash.hero_records_unit">${t('dash.hero_records_unit')}</span>`;
  }

  // ── Stat cards ──
  const statEls = document.querySelectorAll('.stat-value');
  if(statEls[0]) statEls[0].textContent = waiting.length;
  if(statEls[1]) statEls[1].textContent = partial.length;
  if(statEls[2]) statEls[2].textContent = done.length;
  if(statEls[3]) statEls[3].textContent = noReturn.length;

  // ── Company breakdown ──
  // Show ALL companies from active docs (not just with remainder)
  const byCompany = {};
  active.forEach(d => {
    if(!byCompany[d.company]) byCompany[d.company] = { remainder: 0, count: 0, total: 0 };
    byCompany[d.company].remainder += d.remainder || 0;
    byCompany[d.company].total += d.amount || 0;
    byCompany[d.company].count++;
  });

  const companyColors = ['#4f8ef7','#3ecf8e','#f5a623','#a78bfa','#f76f6f','#38bdf8'];
  const maxAmt = Math.max(...Object.values(byCompany).map(v => v.remainder), 1);
  const companyList = document.getElementById('company-list');

  if(companyList) {
    const entries = Object.entries(byCompany).sort((a,b) => b[1].remainder - a[1].remainder);
    if(!entries.length) {
      companyList.innerHTML = `
        <div style="text-align:center;padding:32px 20px;color:var(--text3)">
          <div style="font-size:28px;margin-bottom:8px">📄</div>
          <div style="font-size:13px">${t('dash.no_records')}</div>
        </div>`;
    } else {
      companyList.innerHTML = entries.map(([name, val], i) => `
        <div class="company-row" onclick="filterByCompanyName('${name}')">
          <div class="company-dot" style="background:${companyColors[i%companyColors.length]}"></div>
          <div class="company-name">${name}</div>
          <div class="company-count">${val.count} ${t('dash.checks')}</div>
          <div class="company-amount" style="${val.remainder===0?'color:var(--text3)':''}">
            €${val.remainder.toFixed(2)}
          </div>
        </div>
        <div class="company-bar-wrap" style="margin:-6px 0 8px 20px">
          <div class="company-bar" style="width:${maxAmt>0?(val.remainder/maxAmt*100).toFixed(0):0}%;background:${companyColors[i%companyColors.length]}"></div>
        </div>
      `).join('');
    }
  }

  // ── Recent records ──
  const recentEl = document.getElementById('recent-records-list');
  if(recentEl) {
    const recent = [...active].sort((a,b) => b.date.localeCompare(a.date)).slice(0,5);
    if(!recent.length) {
      recentEl.innerHTML = `<div style="text-align:center;padding:24px;color:var(--text3);font-size:13px">${t('dash.recent_empty')}</div>`;
    } else {
      const icons = { private:'💼', company:'🏢' };
      recentEl.innerHTML = recent.map(d => `
        <div class="record-row" onclick="openDetail('${d.id}')">
          <div class="record-icon">${icons[d.payType]||'📄'}</div>
          <div class="record-info">
            <div class="record-title">${d.title}</div>
            <div class="record-meta">${formatDate(d.date)} · ${d.company}</div>
          </div>
          <div class="record-right">
            <div class="record-amount">€${d.amount.toFixed(2)}</div>
            <div style="margin-top:3px">${statusBadge(d.status)}</div>
          </div>
        </div>
      `).join('');
    }
  }
}

function filterByCompanyName(name) {
  showPage('documents', document.querySelector('[onclick*="documents"]'));
  const base = sampleDocs.filter(d => !d.isArchived && !d.isDeleted);
  filteredDocs = base.filter(d => d.company === name);
  renderDocs();
}

function showPageDocuments(el) {
  const ids = ['docs-search','docs-filter-status','docs-filter-company','docs-filter-paytype'];
  ids.forEach(id => { const e = document.getElementById(id); if(e) e.value = ''; });
  const sortEl = document.getElementById('sort-select');
  if(sortEl) sortEl.value = 'date-desc';
  showPage('documents', el);
  applyFilters();
}

function filterByStatusDash(status) {
  showPage('documents', document.querySelector('[onclick*="documents"]'));
  const statusFilter = document.getElementById('docs-filter-status');
  if(statusFilter) statusFilter.value = status;
  applyFilters();
}


// ── DATA (in-memory cache, synced from Supabase) ──
const sampleDocs = [];
let archivedDocs = [];
let filteredArchived = [];

let currentView = window.innerWidth <= 768 ? 'cards' : (localStorage.getItem('docView') || 'table');
let filteredDocs = sampleDocs.filter(d => !d.isArchived && !d.isDeleted);

// ── NAVIGATION ──
function showPage(name, el) {
  // hide all pages
  document.querySelectorAll('[id^="page-"]').forEach(p => {
    p.style.display = 'none';
    p.classList.remove('active');
  });
  // also handle non-prefixed pages
  ['inbox','unprocessed'].forEach(id => {
    const el2 = document.getElementById('page-'+id);
    if(el2) el2.style.display = 'none';
  });

  const page = document.getElementById('page-' + name);
  if(page) {
    page.style.display = '';
    page.classList.add('active');
  }

  document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
  if(el) el.classList.add('active');
  document.querySelector('.sidebar')?.classList.remove('mob-expanded');
  document.getElementById('mob-sidebar-overlay')?.classList.remove('open');

  if(name === 'documents') renderDocs();
  if(name === 'trash') loadAndRenderTrash();
  if(name === 'settings') { restoreSettingsTab(); loadProfile(); }
  if(name === 'unprocessed') { applyTranslations(); loadUnprocessed(); }
  if(name === 'gallery') { applyTranslations(); loadGallery(); }

  localStorage.setItem('currentPage', name);
}

// ── INIT ──
document.addEventListener('DOMContentLoaded', async () => {
  const _vp = new URLSearchParams(window.location.search);
  if(_vp.get('activate_token')) {
    history.replaceState(null, '', '/');
    showActivateScreen(_vp.get('activate_token'));
    return;
  }
  if(_vp.get('activate_error') === '1') {
    history.replaceState(null, '', '/');
    sessionStorage.setItem('_activate_error', '1');
  }
  if(_vp.get('email_verified') === '1') {
    history.replaceState(null, '', '/');
    sessionStorage.setItem('_email_just_verified', '1');
  }
  if(_vp.get('verify_error') === '1') {
    history.replaceState(null, '', '/');
    sessionStorage.setItem('_verify_error', '1');
  }

  const dateEl = document.getElementById('field-date');
  if(dateEl) dateEl.value = new Date().toISOString().split('T')[0];

  document.getElementById('field-status')?.addEventListener('change', function() {
    if(this.value === 'done') {
      const amount = document.getElementById('field-amount')?.value;
      if(amount) document.getElementById('field-returned').value = amount;
    }
  });
  loadSavedTheme();
  loadSavedLang();

  const user = await authGetCurrentUser();
  if(user) {
    const orgRes = await fetch('/org/me', { credentials: 'include' });
    if(orgRes.status === 404) {
      showOnboarding();
    } else {
      document.getElementById('page-dashboard').style.display = '';
      document.getElementById('page-dashboard').classList.add('active');
      await initApp(user);
      if(sessionStorage.getItem('_activate_error')) {
        sessionStorage.removeItem('_activate_error');
        showToast(t('activate.err_invalid_token'), 'error');
      } else if(sessionStorage.getItem('_email_just_verified')) {
        sessionStorage.removeItem('_email_just_verified');
        showToast(t('verify.success_toast'), 'success');
      } else if(sessionStorage.getItem('_verify_error')) {
        sessionStorage.removeItem('_verify_error');
        showToast(t('verify.error_toast'), 'error');
      } else if(user.email_verified === false) {
        _showVerifyBanner();
      }
      const savedPage = localStorage.getItem('currentPage');
      if(savedPage && savedPage !== 'dashboard') {
        const navEl = document.querySelector(`[onclick*="${savedPage}"]`);
        if(savedPage === 'documents') showPageDocuments(navEl);
        else showPage(savedPage, navEl);
      }
    }
  } else {
    showAuthScreen();
  }
});

// ── SETTINGS TABS ──
function showSettingsTab(name, el) {
  document.querySelectorAll('.settings-content').forEach(c => c.classList.remove('active'));
  document.querySelectorAll('.settings-nav-item').forEach(i => i.classList.remove('active'));
  document.getElementById('settings-' + name).classList.add('active');
  el.classList.add('active');
  localStorage.setItem('settingsTab', name);
  if(name === 'payments') loadAndRenderInstruments();
  if(name === 'companies') loadAndRenderCompanies();
  if(name === 'storage') loadStorageInfo();
  if(name === 'profile') loadProfile();
  if(name === 'org-members') loadOrgMembers();
}

async function loadProfile() {
  const container = document.getElementById('profile-content');
  if(!container) return;
  try {
    const [res, orgRes] = await Promise.all([
      fetch('/profile', { credentials: 'include' }),
      fetch('/org/me',  { credentials: 'include' }),
    ]);
    const data = await res.json();
    if(!res.ok) return;
    const org = orgRes.ok ? await orgRes.json() : null;

    const roleLabel = { admin: 'Адміністратор', manager: 'Менеджер', user: 'Користувач' };

    container.innerHTML = `
      <div class="profile-row">
        <div class="profile-label">${t('settings.name')}</div>
        <div class="profile-value">${data.full_name || '—'}</div>
      </div>
      <div class="profile-row">
        <div class="profile-label">${t('settings.email')}</div>
        <div class="profile-value">${data.email || '—'}</div>
      </div>
      ${org ? `
      <div class="profile-row">
        <div class="profile-label">${t('org.label')}</div>
        <div class="profile-value">${org.name}</div>
      </div>
      <div class="profile-row">
        <div class="profile-label">${t('org.role_label')}</div>
        <div class="profile-value">${roleLabel[org.role] || org.role}</div>
      </div>
      ${org.role !== 'admin' ? `
      <div class="profile-row" style="padding-top:8px">
        <button onclick="leaveOrg()" class="btn btn-danger" style="font-size:13px;width:100%">${t('org.leave_btn')}</button>
      </div>` : ''}` : ''}
    `;
  } catch {
    if(container) container.innerHTML = '';
  }
}

async function loadOrgMembers() {
  const container = document.getElementById('org-members-list');
  const orgInfoEl = document.getElementById('org-info-content');
  if(!container) return;
  try {
    const [membersRes, companiesRes, orgRes] = await Promise.all([
      fetch('/org/members',  { credentials: 'include' }),
      fetch('/companies',    { credentials: 'include' }),
      fetch('/org/me',       { credentials: 'include' }),
    ]);
    const members   = await membersRes.json();
    const companies = companiesRes.ok ? await companiesRes.json() : [];
    const orgData   = orgRes.ok ? await orgRes.json() : null;
    if(!membersRes.ok) { container.innerHTML = ''; return; }

    if(orgInfoEl && orgData) {
      orgInfoEl.innerHTML = `
        <div class="profile-row">
          <div class="profile-label">${t('org.label')}</div>
          <div class="profile-value" style="font-weight:500">${orgData.name}</div>
        </div>
        <div class="profile-row" style="flex-direction:column;align-items:flex-start;gap:8px">
          <div class="profile-label">${t('org.invite_label')}</div>
          <div id="invite-token-block" style="width:100%"></div>
          <button onclick="generateInvite()" class="btn btn-ghost btn-invite-generate">${t('org.invite_generate_btn')}</button>
        </div>`;
      _loadCurrentInvite();
    }

    const roleLabel = { admin: t('org.role_admin'), manager: t('org.role_manager'), user: t('org.role_user') };

    const activeMembers   = members.filter(m => !m.left_at);
    const excludedMembers = members.filter(m =>  m.left_at);

    const memberCompanies = {};
    await Promise.all(activeMembers.filter(m => m.role !== 'admin').map(async m => {
      const r = await fetch(`/org/members/${m.user_id}/companies`, { credentials: 'include' });
      memberCompanies[m.user_id] = r.ok ? await r.json() : [];
    }));

    const renderMember = m => {
      const isExcluded = !!m.left_at;
      const granted    = memberCompanies[m.user_id] || [];
      const avatarBg   = isExcluded ? 'var(--bg4)' : 'var(--accent)';
      const avatarColor= isExcluded ? 'var(--text3)' : '#fff';
      const nameColor  = isExcluded ? 'var(--text3)' : 'var(--text1)';
      const safeEmail  = (m.email || '').replace(/'/g, "\\'");
      const safeName   = (m.full_name || m.email || '').replace(/'/g, "\\'");

      const companiesHtml = !isExcluded && m.role !== 'admin' && companies.length ? `
        <div style="margin-top:8px;padding-left:46px">
          <div style="font-size:11px;color:var(--text3);margin-bottom:4px">${t('org.companies_label')}</div>
          <div style="display:flex;flex-wrap:wrap;gap:6px">
            ${companies.map(c => `
              <span class="company-access-chip ${granted.includes(c.id) ? 'granted' : ''}"
                onclick="orgChipToggle(this,'${m.user_id}','${c.id}')">
                ${c.name}
              </span>`).join('')}
          </div>
        </div>` : '';

      const controls = isExcluded ? `
        <button onclick="orgMemberRestore('${m.user_id}')"
          class="btn btn-ghost" style="font-size:11px;padding:3px 8px;color:var(--green);border-color:var(--green)">
          ${t('org.restore_btn')}
        </button>
        <button onclick="orgMemberDeletePermanent('${m.user_id}','${safeEmail}','${safeName}')"
          class="btn btn-danger" style="font-size:11px;padding:3px 8px">
          ${t('org.delete_permanent_btn')}
        </button>` : m.is_pending ? `
        <span style="font-size:11px;color:var(--yellow);margin-right:4px">⏳ ${t('invite.pending_label')}</span>
        <button onclick="orgMemberResendInvite('${m.user_id}')"
          class="btn btn-ghost" style="font-size:11px;padding:3px 8px">
          ${t('invite.resend_btn')}
        </button>
        <button onclick="orgMemberExclude('${m.user_id}')"
          title="${t('org.exclude_tooltip')}"
          style="background:none;border:none;color:var(--red,#e05555);font-size:18px;cursor:pointer;padding:0 4px">✕</button>
        ` : m.role !== 'admin' ? `
        <select onchange="orgMemberSetRole('${m.user_id}', this.value)"
          style="font-size:12px;padding:4px 6px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg2);color:var(--text1);cursor:pointer">
          <option value="manager" ${m.role==='manager' ? 'selected' : ''}>${t('org.role_manager')}</option>
          <option value="user"    ${m.role==='user'    ? 'selected' : ''}>${t('org.role_user')}</option>
        </select>
        <button onclick="orgMemberExclude('${m.user_id}')"
          title="${t('org.exclude_tooltip')}"
          style="background:none;border:none;color:var(--red,#e05555);font-size:18px;cursor:pointer;padding:0 4px">✕</button>
        ` : `<span style="font-size:12px;color:var(--text3);padding:4px 8px">${roleLabel[m.role]}</span>`;

      return `
        <div style="padding:10px 0;border-bottom:1px solid var(--border);${isExcluded ? 'opacity:0.55' : ''}">
          <div style="display:flex;align-items:center;gap:10px">
            <div style="width:36px;height:36px;border-radius:50%;background:${avatarBg};color:${avatarColor};display:flex;align-items:center;justify-content:center;font-weight:600;font-size:14px;flex-shrink:0">
              ${(m.full_name || m.email || '?')[0].toUpperCase()}
            </div>
            <div style="flex:1;min-width:0">
              <div style="font-size:13px;font-weight:500;color:${nameColor}">${m.full_name || m.email}</div>
              <div style="font-size:11px;color:var(--text3)">${m.email}${isExcluded ? ` · <span style="color:var(--red)">${t('org.excluded_label')}</span>` : ''}</div>
            </div>
            <div style="display:flex;align-items:center;gap:6px;flex-shrink:0">
              ${controls}
            </div>
          </div>
          ${companiesHtml}
        </div>`;
    };

    container.innerHTML = [
      ...activeMembers.map(renderMember),
      ...excludedMembers.map(renderMember),
    ].join('');
  } catch {
    container.innerHTML = '';
  }
}

async function orgToggleCompany(userId, companyId, granted) {
  const method = granted ? 'PUT' : 'DELETE';
  await fetch(`/org/members/${userId}/companies/${companyId}`, { method, credentials: 'include' });
}

function orgChipToggle(el, userId, companyId) {
  const nowGranted = !el.classList.contains('granted');
  el.classList.toggle('granted');
  orgToggleCompany(userId, companyId, nowGranted);
}

async function orgMemberSetRole(userId, newRole) {
  const res = await fetch(`/org/members/${userId}/role`, {
    method: 'PUT', credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role: newRole }),
  });
  if(!res.ok) { showToast('Помилка зміни ролі', 'error'); loadOrgMembers(); }
}

async function orgMemberExclude(userId) {
  const res = await fetch(`/org/members/${userId}`, { method: 'DELETE', credentials: 'include' });
  if(res.ok) loadOrgMembers();
  else showToast(t('toast.error'), 'error');
}

async function orgMemberRestore(userId) {
  const res = await fetch(`/org/members/${userId}/restore`, { method: 'PUT', credentials: 'include' });
  if(res.ok) loadOrgMembers();
  else showToast(t('toast.error'), 'error');
}

function orgMemberDeletePermanent(userId, email, name) {
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
  overlay.innerHTML = `
    <div style="background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:28px;max-width:380px;width:100%">
      <div style="font-size:15px;font-weight:600;color:var(--text1);margin-bottom:8px">${t('org.delete_permanent_title')}</div>
      <div style="font-size:13px;color:var(--text2);margin-bottom:4px">${name}</div>
      <div style="font-size:13px;color:var(--text2);margin-bottom:16px">${t('org.delete_permanent_desc')}</div>
      <input id="_del_confirm_input" type="email" autocomplete="off" placeholder="${email}"
        style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg3);color:var(--text1);font-size:13px;box-sizing:border-box;margin-bottom:16px">
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button id="_del_cancel_btn" class="btn btn-ghost">${t('org.delete_permanent_cancel')}</button>
        <button id="_del_confirm_btn" class="btn btn-danger" disabled style="opacity:0.4">${t('org.delete_permanent_confirm')}</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);

  const input   = overlay.querySelector('#_del_confirm_input');
  const confirmBtn = overlay.querySelector('#_del_confirm_btn');
  const cancelBtn  = overlay.querySelector('#_del_cancel_btn');

  input.addEventListener('input', () => {
    const match = input.value.trim() === email;
    confirmBtn.disabled = !match;
    confirmBtn.style.opacity = match ? '1' : '0.4';
  });

  cancelBtn.onclick = () => overlay.remove();
  overlay.addEventListener('click', e => { if(e.target === overlay) overlay.remove(); });

  confirmBtn.onclick = async () => {
    confirmBtn.disabled = true;
    const res = await fetch(`/org/members/${userId}/permanent`, { method: 'DELETE', credentials: 'include' });
    overlay.remove();
    if(res.ok) { showToast(t('toast.deleted'), 'success'); loadOrgMembers(); }
    else showToast(t('toast.error'), 'error');
  };

  setTimeout(() => input.focus(), 50);
}

async function orgMemberResendInvite(userId) {
  const res = await fetch(`/org/members/${userId}/resend-invite`, { method: 'POST', credentials: 'include' });
  if(res.ok) showToast(t('invite.resent_toast'), 'success');
  else       showToast(t('toast.error'), 'error');
}

function openInviteUserModal() {
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
  overlay.innerHTML = `
    <div style="background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:28px;max-width:380px;width:100%">
      <div style="font-size:15px;font-weight:600;color:var(--text1);margin-bottom:20px">${t('invite.modal_title')}</div>
      <div style="margin-bottom:10px">
        <div style="font-size:12px;color:var(--text3);margin-bottom:4px">${t('invite.email_label')} *</div>
        <input id="_inv_email" type="email" placeholder="email@example.com"
          style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg3);color:var(--text1);font-size:13px;box-sizing:border-box">
      </div>
      <div style="margin-bottom:10px">
        <div style="font-size:12px;color:var(--text3);margin-bottom:4px">${t('invite.name_label')}</div>
        <input id="_inv_name" type="text" placeholder="${t('invite.name_placeholder')}"
          style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg3);color:var(--text1);font-size:13px;box-sizing:border-box">
      </div>
      <div style="margin-bottom:20px">
        <div style="font-size:12px;color:var(--text3);margin-bottom:4px">${t('invite.role_label')}</div>
        <select id="_inv_role"
          style="width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg3);color:var(--text1);font-size:13px">
          <option value="user">${t('org.role_user')}</option>
          <option value="manager">${t('org.role_manager')}</option>
        </select>
      </div>
      <div id="_inv_error" style="display:none;color:var(--red);font-size:12px;margin-bottom:10px"></div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button id="_inv_cancel" class="btn btn-ghost">${t('org.delete_permanent_cancel')}</button>
        <button id="_inv_submit" class="btn btn-primary">${t('invite.send_btn')}</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);

  const emailInput = overlay.querySelector('#_inv_email');
  const nameInput  = overlay.querySelector('#_inv_name');
  const roleSelect = overlay.querySelector('#_inv_role');
  const errEl      = overlay.querySelector('#_inv_error');
  const submitBtn  = overlay.querySelector('#_inv_submit');
  const cancelBtn  = overlay.querySelector('#_inv_cancel');

  cancelBtn.onclick = () => overlay.remove();
  overlay.addEventListener('click', e => { if(e.target === overlay) overlay.remove(); });

  submitBtn.onclick = async () => {
    const email     = emailInput.value.trim();
    const full_name = nameInput.value.trim();
    const role      = roleSelect.value;
    if(!email) { errEl.textContent = t('invite.err_email_required'); errEl.style.display=''; return; }
    submitBtn.disabled = true;
    try {
      const res  = await fetch('/org/members/invite', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, full_name, role }),
      });
      const data = await res.json();
      if(data.ok) {
        overlay.remove();
        showToast(data.existing_user ? t('invite.added_existing_toast') : t('invite.sent_toast'), 'success');
        loadOrgMembers();
      } else {
        const msgs = { already_in_org: t('onboarding.err_already_in_org'), email_required: t('invite.err_email_required') };
        errEl.textContent = msgs[data.error] || t('toast.error');
        errEl.style.display = '';
      }
    } catch { errEl.textContent = t('auth.err_connection'); errEl.style.display=''; }
    finally  { submitBtn.disabled = false; }
  };

  setTimeout(() => emailInput.focus(), 50);
}

function _renderInviteToken(data) {
  const el = document.getElementById('invite-token-block');
  if(!el) return;
  if(!data || !data.token) {
    el.innerHTML = `<span style="font-size:12px;color:var(--text3)">${t('org.invite_no_token')}</span>`;
    return;
  }
  const expires = new Date(data.expires_at + 'Z');
  const diff    = Math.max(0, Math.round((expires - Date.now()) / 60000));
  el.innerHTML = `
    <div style="background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius-sm);padding:10px 12px">
      <div style="font-family:monospace;font-size:13px;font-weight:600;word-break:break-all;margin-bottom:4px">${data.token}</div>
      <div style="font-size:11px;color:var(--text3)">${t('org.invite_expires').replace('{m}', diff)}</div>
    </div>`;
}

async function generateInvite() {
  const res  = await fetch('/org/invite/generate', { method: 'POST', credentials: 'include' });
  const data = await res.json();
  if(data.ok) _renderInviteToken(data);
  else showToast('Помилка генерації токену', 'error');
}

async function _loadCurrentInvite() {
  const res = await fetch('/org/invite/current', { credentials: 'include' });
  if(res.ok) _renderInviteToken(await res.json());
}

async function leaveOrg() {
  if(!confirm(t('org.leave_confirm'))) return;
  try {
    const res = await fetch('/org/leave', { method: 'POST', credentials: 'include' });
    if(!res.ok) {
      const d = await res.json();
      showToast(d.error === 'admin_cannot_leave' ? t('toast.forbidden') : t('toast.error'), 'error');
      return;
    }
    showToast(t('org.leave_success'), 'success');
    setTimeout(() => window.location.reload(), 800);
  } catch {
    showToast(t('toast.error'), 'error');
  }
}

function restoreSettingsTab() {
  const saved = localStorage.getItem('settingsTab') || 'companies';
  const el = document.querySelector(`.settings-nav-item[onclick*="'${saved}'"]`);
  if(el) showSettingsTab(saved, el);
  else showSettingsTab('companies', document.querySelector('.settings-nav-item'));
}

// ── SCROLL LOCK ──
let _scrollLockCount = 0;
function lockScroll()   { if (++_scrollLockCount === 1) document.body.style.overflow = 'hidden'; }
function unlockScroll() { if (--_scrollLockCount <= 0) { _scrollLockCount = 0; document.body.style.overflow = ''; } }

// ── MODAL ──
let editingId = null;
let pendingFiles = [];
let pendingDriveFiles = [];

function openModal() {
  editingId = null;
  resetModalForm();
  document.getElementById('modal-title').textContent = t('form.new_record');
  document.getElementById('modal-save-btn').textContent = t('btn.save_record');
  document.getElementById('modal-edit-badge').style.display = 'none';
  document.getElementById('modal-overlay').classList.add('open');
  lockScroll();
}

function setVal(id, val) {
  const el = document.getElementById(id);
  if(!el) return;
  if(val === null || val === undefined) {
    if('innerHTML' in el) el.innerHTML = '';
  } else if('style' in el && typeof val === 'object') {
    Object.assign(el.style, val);
  } else {
    el.value = val;
  }
}

function setDisplay(id, display) {
  const el = document.getElementById(id);
  if(el) el.style.display = display;
}

function resetModalForm() {
  setVal('field-date', new Date().toISOString().split('T')[0]);
  setVal('field-amount', '');
  setVal('field-title', '');
  setVal('field-note', '');
  setVal('field-payment-type', '');
  setVal('field-payment-method', '');
  setVal('field-card', '');
  setVal('field-company', '');
  setVal('field-status', 'waiting');
  setVal('field-to-return', '');
  setVal('field-returned', '');
  setVal('field-remainder', '');
  setDisplay('return-block', 'none');
  setDisplay('return-fields', 'none');
  setDisplay('card-select-group', 'none');
  pendingFiles = [];
  pendingDriveFiles = [];
  const fp = document.getElementById('files-preview');
  if(fp) fp.innerHTML = '';
  const ep = document.getElementById('existing-attachments-preview');
  if(ep) ep.innerHTML = '';
}

function openEditModal(id) {
  const doc = sampleDocs.find(d => d.id === id) || archivedDocs.find(d => d.id === id);
  if(!doc) return;
  editingId = id;

  document.getElementById('modal-title').textContent = t('form.edit_record');
  document.getElementById('modal-save-btn').textContent = t('form.update');
  document.getElementById('modal-edit-badge').style.display = '';

  // Fill all fields
  document.getElementById('field-date').value = doc.date;
  document.getElementById('field-amount').value = doc.amount;
  document.getElementById('field-title').value = doc.title;
  document.getElementById('field-note').value = doc.note || '';
  document.getElementById('field-payment-type').value = doc.payType;
  document.getElementById('field-payment-method').value = doc.payMethod;
  document.getElementById('field-company').value = doc.companyId || '';
  document.getElementById('field-status').value = doc.status;

  // Card
  if(doc.payMethod === 'card') {
    document.getElementById('card-select-group').style.display = '';
    document.getElementById('field-card').value = doc.cardId || '';
  } else {
    document.getElementById('card-select-group').style.display = 'none';
  }

  // Return block
  if(doc.payType === 'private') {
    document.getElementById('return-block').style.display = '';
    document.getElementById('return-fields').style.display = '';
    document.getElementById('field-to-return').value = doc.toReturn || doc.amount;
    document.getElementById('field-returned').value = doc.returned || 0;
    document.getElementById('field-remainder').value = doc.remainder || 0;
  } else {
    document.getElementById('return-block').style.display = 'none';
    document.getElementById('return-fields').style.display = 'none';
  }

  pendingFiles = [];
  pendingDriveFiles = [];
  document.getElementById('files-preview').innerHTML = '';
  renderExistingAttachments(doc);
  document.getElementById('modal-overlay').classList.add('open');
  lockScroll();
}

function closeModal() {
  document.getElementById('modal-overlay').classList.remove('open');
  unlockScroll();
}

function closeModalOutside(e) {
  if(e.target === document.getElementById('modal-overlay')) closeModal();
}

// ── PAYMENT LOGIC ──
function onPaymentTypeChange() {
  const type = document.getElementById('field-payment-type').value;
  const returnBlock = document.getElementById('return-block');
  const returnFields = document.getElementById('return-fields');

  if(type === 'private') {
    returnBlock.style.display = '';
    returnFields.style.display = '';
    document.getElementById('field-status').value = 'waiting';
  } else {
    returnBlock.style.display = 'none';
    returnFields.style.display = 'none';
  }
  recalcRemainder();
}

function onPaymentMethodChange() {
  const method = document.getElementById('field-payment-method').value;
  const cardGroup = document.getElementById('card-select-group');
  cardGroup.style.display = method === 'card' ? '' : 'none';
}

function recalcRemainder() {
  const amount = parseFloat(document.getElementById('field-amount').value) || 0;
  const returned = parseFloat(document.getElementById('field-returned')?.value) || 0;
  const toReturnEl = document.getElementById('field-to-return');
  const remainderEl = document.getElementById('field-remainder');
  const statusEl = document.getElementById('field-status');

  if(toReturnEl) toReturnEl.value = amount > 0 ? amount.toFixed(2) : '';
  if(remainderEl) {
    const rem = Math.max(0, amount - returned);
    remainderEl.value = amount > 0 ? rem.toFixed(2) : '';
  }

  // auto status
  const type = document.getElementById('field-payment-type').value;
  if(type === 'private' && amount > 0) {
    if(returned <= 0) statusEl.value = 'waiting';
    else if(returned < amount) statusEl.value = 'partial';
    else statusEl.value = 'done';
  }
}

// ── FILE HANDLING ──
function handleFiles(input) {
  const files = Array.from(input.files);
  pendingFiles = [...pendingFiles, ...files];
  if(pendingFiles.length > 5) {
    pendingFiles = pendingFiles.slice(-5);
    showToast(t('toast.max_files'), 'error');
  }
  renderFilesPreview();
  input.value = '';
}

function removePendingFile(index) {
  pendingFiles.splice(index, 1);
  renderFilesPreview();
}

function renderFilesPreview() {
  const preview = document.getElementById('files-preview');
  if(!preview) return;
  const localHtml = pendingFiles.map((f, i) => `
    <div style="background:var(--bg4);border:1px solid var(--border);border-radius:6px;padding:4px 10px;font-size:12px;color:var(--text2);display:flex;align-items:center;gap:6px;">
      ${f.type.includes('pdf') ? '📄' : '🖼️'} ${f.name.substring(0,20)}${f.name.length>20?'...':''}
      <span style="cursor:pointer;color:var(--text3)" onclick="removePendingFile(${i})">✕</span>
    </div>
  `).join('');
  const driveHtml = pendingDriveFiles.map((f, i) => `
    <div style="background:var(--bg4);border:1px solid var(--accent,#4f8ef7);border-radius:6px;padding:4px 10px;font-size:12px;color:var(--text2);display:flex;align-items:center;gap:6px;">
      ☁️ ${f.file_name.substring(0,20)}${f.file_name.length>20?'...':''}
      <span style="cursor:pointer;color:var(--text3)" onclick="removePendingDriveFile(${i})">✕</span>
    </div>
  `).join('');
  preview.innerHTML = localHtml + driveHtml;
}

function removePendingDriveFile(index) {
  pendingDriveFiles.splice(index, 1);
  renderFilesPreview();
}

function renderExistingAttachments(doc) {
  const container = document.getElementById('existing-attachments-preview');
  if(!container) return;
  const atts = doc.attachments || [];
  if(atts.length === 0) { container.innerHTML = ''; return; }
  container.innerHTML = atts.map(f => {
    const isPdf = f.type === 'application/pdf';
    const shortName = f.name.length > 20 ? f.name.substring(0,18) + '…' : f.name;
    return `
      <div style="background:var(--bg4);border:1px solid var(--green,#34c759);border-radius:6px;padding:4px 10px;font-size:12px;color:var(--text2);display:flex;align-items:center;gap:6px;">
        ${isPdf ? '📄' : '🖼️'} ${shortName}
        <span style="cursor:pointer;color:var(--text3)" onclick="removeExistingAttachment('${f.id}')">✕</span>
      </div>
    `;
  }).join('');
}

async function removeExistingAttachment(id) {
  try {
    await deleteAttachmentDB(id);
    const doc = sampleDocs.find(d => d.id === editingId) || archivedDocs.find(d => d.id === editingId);
    if(doc) {
      doc.attachments = doc.attachments.filter(a => a.id !== id);
      doc.files = doc.attachments.length;
      renderExistingAttachments(doc);
    }
  } catch(e) {
    showToast(t('toast.file_delete_error'), 'error');
  }
}

// ── SAVE RECORD (create + edit) ──
async function saveRecord() {
  const required = ['field-date','field-amount','field-title','field-payment-type','field-payment-method'];
  let valid = true;

  required.forEach(id => {
    const el = document.getElementById(id);
    if(!el) { console.warn('Missing field:', id); valid = false; return; }
    if(!el.value) {
      el.style.borderColor = 'var(--red)';
      valid = false;
      setTimeout(() => el.style.borderColor = '', 2000);
    }
  });

  if(!valid) {
    showToast(t('toast.fill_required'), 'error');
    return;
  }

  const payType = document.getElementById('field-payment-type').value;
  const amount = parseFloat(document.getElementById('field-amount').value);
  const returned = parseFloat(document.getElementById('field-returned')?.value) || 0;

  // Use user-selected status
  const autoStatus = document.getElementById('field-status').value;

  const btn = document.getElementById('modal-save-btn');
  btn.disabled = true;
  const origText = btn.textContent;
  btn.textContent = t('btn.saving');

  try {
    const payMethod = document.getElementById('field-payment-method').value;
    const companySelect = document.getElementById('field-company');
    const cardSelect = document.getElementById('field-card');
    const companyId = companySelect.value || null;
    const cardId = payMethod === 'card' ? (cardSelect.value || null) : null;
    const companyName = companySelect.options[companySelect.selectedIndex]?.text || '—';
    const cardName = cardId ? (cardSelect.options[cardSelect.selectedIndex]?.text || '') : '';

    const recordData = {
      title: document.getElementById('field-title').value,
      note: document.getElementById('field-note').value,
      date: document.getElementById('field-date').value,
      amount,
      payType,
      payMethod,
      companyId,
      cardId,
      status: autoStatus,
      toReturn: payType === 'private' ? amount : 0,
      returned,
      remainder: payType === 'private' ? Math.max(0, amount - returned) : 0,
      is_archived: autoStatus === 'archived' ? 1 : 0,
    };

    if(editingId !== null) {
      await updateRecord(editingId, recordData);

      const _editDoc = sampleDocs.find(d => d.id === editingId) || archivedDocs.find(d => d.id === editingId);
      if(pendingFiles.length > 0) {
        setBusy(true, 'busy.uploading');
        try {
          for(const file of pendingFiles) {
            const att = await uploadAttachment(editingId, file);
            if(_editDoc) {
              if(!_editDoc.attachments) _editDoc.attachments = [];
              _editDoc.attachments.push({ id: att.id, name: att.file_name, type: att.file_type, storageType: 'local' });
              _editDoc.files = _editDoc.attachments.length;
            }
          }
          if(_editDoc && currentDetailId === editingId) renderAttachments(_editDoc);
        } finally {
          setBusy(false);
        }
        pendingFiles = [];
      }
      if(pendingDriveFiles.length > 0) {
        setBusy(true, 'busy.drive_download');
        try {
          for(const df of pendingDriveFiles) {
            const resp = await fetch(`/records/${editingId}/attach-from-drive`, {
              method: 'POST', credentials: 'include',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(df),
            });
            if(resp.ok) {
              const att = await resp.json();
              if(_editDoc) {
                if(!_editDoc.attachments) _editDoc.attachments = [];
                _editDoc.attachments.push({ id: att.id, name: att.file_name, type: att.file_type, storageType: att.storage_type });
                _editDoc.files = _editDoc.attachments.length;
              }
            }
          }
          if(_editDoc && currentDetailId === editingId) renderAttachments(_editDoc);
        } finally {
          setBusy(false);
        }
        pendingDriveFiles = [];
      }

      const sIdx = sampleDocs.findIndex(d => d.id === editingId);
      const aIdx = archivedDocs.findIndex(d => d.id === editingId);
      if(sIdx !== -1) {
        if(recordData.is_archived) {
          const doc = { ...sampleDocs[sIdx], ...recordData, isArchived: true, company: companyName, card: cardName };
          sampleDocs.splice(sIdx, 1);
          archivedDocs.unshift(doc);
        } else {
          sampleDocs[sIdx] = { ...sampleDocs[sIdx], ...recordData, isArchived: false, company: companyName, card: cardName };
        }
      } else if(aIdx !== -1) {
        if(!recordData.is_archived) {
          const doc = { ...archivedDocs[aIdx], ...recordData, isArchived: false, company: companyName, card: cardName };
          archivedDocs.splice(aIdx, 1);
          sampleDocs.unshift(doc);
        } else {
          archivedDocs[aIdx] = { ...archivedDocs[aIdx], ...recordData, isArchived: true, company: companyName, card: cardName };
        }
      }
      filteredArchived = archivedDocs.filter(d => !d.isDeleted);
      showToast(t('toast.updated'), 'success');
    } else {
      const newDoc = await createRecord(recordData);
      newDoc.company = companyName;
      newDoc.card = cardName;

      if(pendingFiles.length > 0) {
        setBusy(true, 'busy.uploading');
        try {
          for(const file of pendingFiles) {
            const att = await uploadAttachment(newDoc.id, file);
            newDoc.attachments.push({ id: att.id, name: att.file_name, type: att.file_type, storageType: 'local' });
            newDoc.files = newDoc.attachments.length;
          }
        } finally {
          setBusy(false);
        }
        pendingFiles = [];
      }
      if(pendingDriveFiles.length > 0) {
        setBusy(true, 'busy.drive_download');
        try {
          for(const df of pendingDriveFiles) {
            const resp = await fetch(`/records/${newDoc.id}/attach-from-drive`, {
              method: 'POST', credentials: 'include',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(df),
            });
            if(resp.ok) {
              const att = await resp.json();
              newDoc.attachments.push({ id: att.id, name: att.file_name, type: att.file_type, storageType: att.storage_type });
              newDoc.files = newDoc.attachments.length;
            }
          }
        } finally {
          setBusy(false);
        }
        pendingDriveFiles = [];
      }

      sampleDocs.unshift(newDoc);
      showToast(t('toast.saved'), 'success');
    }

    filteredDocs = sampleDocs.filter(d => !d.isArchived && !d.isDeleted);
    renderDocs();
    updateDashboard();
    updateBadges();
    closeModal();
  } catch(e) {
    console.error('saveRecord error', e);
    showToast(_errMsg(e), 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = origText;
  }
}

// ── RENDER DOCS ──
function renderDocs() {
  renderTable();
  renderCards();
  renderArchiveSection();
}

function renderArchiveSection() {
  const section = document.getElementById('archive-section');
  if(!section) return;
  if(!filteredArchived.length) { section.style.display = 'none'; return; }
  section.style.display = '';
  document.getElementById('archive-section-count').textContent = `${filteredArchived.length} ${t('dash.checks')}`;
  renderArchiveTable();
  renderArchiveCards();
  const archiveView = window.innerWidth <= 768 ? 'cards' : currentView;
  document.getElementById('table-view-archive').style.display = archiveView === 'table' ? '' : 'none';
  document.getElementById('cards-view-archive').style.display = archiveView === 'cards' ? 'grid' : 'none';
}

function renderArchiveTable() {
  const tbody = document.getElementById('archive-table-body');
  if(!tbody) return;
  tbody.innerHTML = filteredArchived.map(d => `
    <tr onclick="openDetail('${d.id}')" style="opacity:0.7">
      <td class="td-date">${formatDate(d.date)}</td>
      <td class="td-title"><strong style="font-weight:500">${d.title}</strong></td>
      <td style="color:var(--text2)">${d.company}</td>
      <td class="td-amount">${d.currency}${d.amount.toFixed(2)}</td>
      <td><span style="font-size:12px;color:var(--text2)">${d.payType === 'private' ? t('detail.private') : t('detail.company_pay')}</span></td>
      <td>${statusBadge(d.status)}</td>
      <td class="td-remainder">${d.remainder > 0 ? d.currency + d.remainder.toFixed(2) : '<span style="color:var(--text3)">—</span>'}</td>
      <td class="attachment-icon ${d.files > 0 ? 'has' : ''}">${d.files > 0 ? '📎' + (d.files > 1 ? d.files : '') : '—'}</td>
      <td onclick="event.stopPropagation()">
        ${canWrite() ? `<div style="display:flex;gap:4px;align-items:center">
          <button class="btn btn-ghost" style="font-size:11px;padding:3px 8px" title="${t('archive.restore')}" onclick="unarchiveRecord('${d.id}')">↩</button>
          <button class="icon-btn danger" title="${t('btn.to_trash')}" onclick="deleteFromArchive('${d.id}')">🗑️</button>
        </div>` : ''}
      </td>
    </tr>
  `).join('');
}

function renderArchiveCards() {
  const grid = document.getElementById('cards-view-archive');
  if(!grid) return;
  grid.innerHTML = filteredArchived.map(d => `
    <div class="doc-card" onclick="openDetail('${d.id}')" style="opacity:0.7">
      <div class="doc-card-top">
        <div class="doc-card-title">${d.title}</div>
        <div style="display:flex;align-items:center;gap:4px">
          ${d.files > 0 ? '<span class="attachment-icon has" style="font-size:15px">📎</span>' : ''}
          ${canWrite() ? `<button class="btn btn-ghost" style="font-size:11px;padding:2px 6px" onclick="event.stopPropagation();unarchiveRecord('${d.id}')">↩</button>
          <button class="icon-btn danger" title="${t('btn.to_trash')}" onclick="event.stopPropagation();deleteFromArchive('${d.id}')" style="width:24px;height:24px;font-size:11px">🗑️</button>` : ''}
        </div>
      </div>
      <div class="doc-card-meta">
        <span class="meta-chip">📅 ${formatDate(d.date)}</span>
        <span class="meta-chip">🏢 ${d.company}</span>
      </div>
      <div class="doc-card-footer">
        <div><div class="doc-card-amount">${d.currency}${d.amount.toFixed(2)}</div></div>
        ${statusBadge(d.status)}
      </div>
    </div>
  `).join('');
}

function statusBadge(status) {
  const map = {
    waiting: () => `<span class="badge badge-waiting">${t('status.waiting')}</span>`,
    partial: () => `<span class="badge badge-partial">${t('status.partial')}</span>`,
    done: () => `<span class="badge badge-done">${t('status.done')}</span>`,
    'no-return': () => `<span class="badge badge-no-return">${t('status.no_return')}</span>`,
    ready: () => `<span class="badge badge-done">${t('status.ready')}</span>`,
    archived: () => `<span class="badge badge-archived">${t('status.archived')}</span>`,
  };
  return map[status] ? map[status]() : status;
}

function formatDate(d) {
  if(!d) return '';
  const [y,m,day] = d.split('-');
  return `${day}.${m}.${y}`;
}

function formatDateTime(d) {
  if(!d) return '';
  const [datePart, timePart] = d.split(' ');
  const [y,m,day] = datePart.split('-');
  const time = timePart ? timePart.slice(0,5) : '';
  return time ? `${day}.${m}.${y} ${time}` : `${day}.${m}.${y}`;
}

function renderTable() {
  const tbody = document.getElementById('docs-table-body');
  if(!tbody) return;
  if(!filteredDocs.length) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:40px;color:var(--text3)">${t('docs.not_found')}</td></tr>`;
    return;
  }
  tbody.innerHTML = filteredDocs.map(d => `
    <tr onclick="openDetail('${d.id}')">
      <td class="td-date">${formatDate(d.date)}</td>
      <td class="td-title"><strong style="font-weight:500">${d.title}</strong></td>
      <td style="color:var(--text2)">${d.company}</td>
      <td class="td-amount">${d.currency}${d.amount.toFixed(2)}</td>
      <td><span style="font-size:12px;color:var(--text2)">${d.payType === 'private' ? t('detail.private') : t('detail.company_pay')}</span></td>
      <td>${statusBadge(d.status)}</td>
      <td class="td-remainder">${d.remainder > 0 ? d.currency + d.remainder.toFixed(2) : '<span style="color:var(--text3)">—</span>'}</td>
      <td class="attachment-icon ${d.files > 0 ? 'has' : ''}">${d.files > 0 ? '📎' + (d.files > 1 ? d.files : '') : '—'}</td>
      <td onclick="event.stopPropagation()">
        ${canWrite() ? `<div style="display:flex;flex-direction:row;gap:4px;align-items:center">
          <button class="icon-btn" title="${t('detail.edit')}" onclick="openEditModal('${d.id}')" style="opacity:0.5" onmouseenter="this.style.opacity=1" onmouseleave="this.style.opacity=0.5">✏️</button>
          <button class="icon-btn" title="${t('detail.archive')}" onclick="archiveRecordById('${d.id}')" style="opacity:0.5" onmouseenter="this.style.opacity=1" onmouseleave="this.style.opacity=0.5">🗄️</button>
          <button class="icon-btn danger" title="${t('btn.to_trash')}" onclick="trashRecordById('${d.id}')">🗑️</button>
        </div>` : ''}
      </td>
    </tr>
  `).join('');
}

function renderCards() {
  const grid = document.getElementById('cards-view');
  if(!grid) return;
  if(!filteredDocs.length) {
    grid.innerHTML = `<div class="empty-state"><div class="empty-icon">📄</div><div class="empty-title">${t('docs.not_found')}</div></div>`;
    return;
  }
  grid.innerHTML = filteredDocs.map(d => `
    <div class="doc-card" onclick="openDetail('${d.id}')">
      <div class="doc-card-top">
        <div class="doc-card-title">${d.title}</div>
        <div style="display:flex;align-items:center;gap:4px">
          ${d.files > 0 ? '<span class="attachment-icon has" style="font-size:15px">📎</span>' : ''}
          ${canWrite() ? `<button class="icon-btn" title="${t('detail.edit')}" onclick="event.stopPropagation();openEditModal('${d.id}')" style="width:24px;height:24px;font-size:11px">✏️</button>
          <button class="icon-btn" title="${t('detail.archive')}" onclick="event.stopPropagation();archiveRecordById('${d.id}')" style="width:24px;height:24px;font-size:11px">🗄️</button>
          <button class="icon-btn danger" title="${t('btn.to_trash')}" onclick="event.stopPropagation();trashRecordById('${d.id}')" style="width:24px;height:24px;font-size:11px">🗑️</button>` : ''}
        </div>
      </div>
      <div class="doc-card-meta">
        <span class="meta-chip">📅 ${formatDate(d.date)}</span>
        <span class="meta-chip">🏢 ${d.company}</span>
        <span class="meta-chip">${d.payType === 'private' ? '💼' : '🏢'} ${d.payMethod === 'card' ? d.card : t('instrument.cash')}</span>
      </div>
      <div class="doc-card-footer">
        <div>
          <div class="doc-card-amount">${d.currency}${d.amount.toFixed(2)}</div>
          ${d.remainder > 0 ? `<div class="doc-card-remainder">${t('detail.remainder')}: ${d.currency}${d.remainder.toFixed(2)}</div>` : ''}
        </div>
        ${statusBadge(d.status)}
      </div>
    </div>
  `).join('');
}

// ── VIEW TOGGLE ──
function setView(type) {
  if (window.innerWidth <= 768) type = 'cards';
  currentView = type;
  localStorage.setItem('docView', type);
  document.getElementById('table-view').style.display = type === 'table' ? '' : 'none';
  document.getElementById('cards-view').style.display = type === 'cards' ? 'grid' : 'none';
  document.getElementById('table-view-archive').style.display = type === 'table' ? '' : 'none';
  document.getElementById('cards-view-archive').style.display = type === 'cards' ? 'grid' : 'none';
  document.getElementById('view-table-btn').classList.toggle('active', type === 'table');
  document.getElementById('view-cards-btn').classList.toggle('active', type === 'cards');
}

// ── FILTER / SORT ──
function filterDocs(q) {
  applyFilters();
}

function filterByStatus(val) {
  applyFilters();
}

function filterByCompany(val) {
  applyFilters();
}

function filterByPayType(val) {
  applyFilters();
}

function applyFilters() {
  const search = (document.getElementById('docs-search')?.value || '').toLowerCase();
  const status = document.getElementById('docs-filter-status')?.value || '';
  const company = document.getElementById('docs-filter-company')?.value || '';
  const payType = document.getElementById('docs-filter-paytype')?.value || '';

  // Якщо вибрано "Архівовано" — ховаємо основну таблицю, показуємо тільки архів
  if(status === 'archived') {
    document.getElementById('table-view').style.display = 'none';
    document.getElementById('cards-view').style.display = 'none';
    filteredDocs = [];
    filteredArchived = archivedDocs.filter(d => !d.isDeleted).filter(d => {
      if(!search) return true;
      return d.title.toLowerCase().includes(search) ||
        d.company.toLowerCase().includes(search) ||
        (d.note || '').toLowerCase().includes(search);
    });
    renderArchiveSection();
    return;
  }

  // Повертаємо основну таблицю якщо вона була захована
  document.getElementById('table-view').style.display = currentView === 'table' ? '' : 'none';
  document.getElementById('cards-view').style.display = currentView === 'cards' ? 'grid' : 'none';

  let base = sampleDocs.filter(d => !d.isArchived && !d.isDeleted);

  if(search) {
    base = base.filter(d =>
      d.title.toLowerCase().includes(search) ||
      d.company.toLowerCase().includes(search) ||
      (d.note || '').toLowerCase().includes(search)
    );
  }
  if(status) base = base.filter(d => d.status === status);
  if(company) base = base.filter(d => d.company === company);
  if(payType) base = base.filter(d => d.payType === payType);

  filteredDocs = base;

  // Архівну секцію показуємо тільки при "Всі статуси"
  if(!status) {
    filteredArchived = archivedDocs.filter(d => !d.isDeleted).filter(d => {
      if(!search) return true;
      return d.title.toLowerCase().includes(search) ||
        d.company.toLowerCase().includes(search) ||
        (d.note || '').toLowerCase().includes(search);
    });
  } else {
    filteredArchived = [];
  }

  const sortVal = document.getElementById('sort-select')?.value || 'date-desc';
  sortDocs(sortVal);
}

function sortDocs(val) {
  const map = {
    'date-desc': (a,b) => b.date.localeCompare(a.date),
    'date-asc':  (a,b) => a.date.localeCompare(b.date),
    'amount-desc': (a,b) => b.amount - a.amount,
    'amount-asc':  (a,b) => a.amount - b.amount,
    'company': (a,b) => a.company.localeCompare(b.company),
    'status': (a,b) => a.status.localeCompare(b.status),
  };
  if(map[val]) filteredDocs.sort(map[val]);
  renderDocs();
}

// ── LANG — see js/i18n.js ──

// ── MOBILE SIDEBAR ──
function toggleMobSidebar() {
  const sidebar = document.querySelector('.sidebar');
  const overlay = document.getElementById('mob-sidebar-overlay');
  sidebar.classList.toggle('mob-expanded');
  overlay.classList.toggle('open');
}

function initSidebarSwipe() {
  let startX = 0, startY = 0, active = false;

  document.addEventListener('touchstart', e => {
    startX = e.touches[0].clientX;
    startY = e.touches[0].clientY;
    active = true;
  }, { passive: true });

  document.addEventListener('touchmove', e => {
    if (!active) return;
    const dx = e.touches[0].clientX - startX;
    const dy = e.touches[0].clientY - startY;
    if (Math.abs(dy) > Math.abs(dx)) active = false;
  }, { passive: true });

  document.addEventListener('touchend', e => {
    if (!active) return;
    active = false;
    const dx = e.changedTouches[0].clientX - startX;
    const sidebar = document.querySelector('.sidebar');
    if (!sidebar) return;
    const isExpanded = sidebar.classList.contains('mob-expanded');
    if (dx > 60 && startX < 80 && !isExpanded) toggleMobSidebar();
    else if (dx < -60 && isExpanded) toggleMobSidebar();
  }, { passive: true });
}

initSidebarSwipe();

function userCardClick() {
  if (window.innerWidth <= 768) {
    toggleMobSidebar();
  } else {
    showLogoutMenu();
  }
}

// ── SYNC ──
function syncNow() {
  if(!DRIVE_ENABLED) return;
  confirmSync();
}

function closeSyncPreview() {
  document.getElementById('sync-preview-overlay').classList.remove('open');
}

async function confirmSync() {
  if(!DRIVE_ENABLED) return;
  setBusy(true, 'sync.busy');
  try {
    const res  = await fetch('/sync', { method: 'POST', credentials: 'include' });
    const data = await res.json();
    if(!res.ok || !data.ok) {
      showToast(t('toast.sync_error'), 'error');
      return;
    }
    const uploaded = data.uploaded || 0;
    if(uploaded === 0) {
      showToast(t('toast.sync_nothing'), 'info');
    } else {
      showToast(t('toast.sync_done').replace('{n}', uploaded), 'success');
    }
  } catch {
    showToast(t('toast.sync_error'), 'error');
  } finally {
    setBusy(false);
  }
}

async function runDriveCleanup() {
  if(!DRIVE_ENABLED) return;
  setBusy(true, 'sync.drive_cleanup_busy');
  try {
    const res  = await fetch('/drive-cleanup', { method: 'POST', credentials: 'include' });
    const data = await res.json();
    if(!res.ok || !data.ok) {
      showToast(t(data.message === 'no_drive_token' ? 'toast.sync_no_drive' : 'toast.sync_error'), 'error');
      return;
    }
    const f = data.deleted_files   || 0;
    const d = data.deleted_folders || 0;
    if(f === 0 && d === 0) {
      showToast(t('sync.drive_cleanup_nothing'), 'info');
    } else {
      showToast(t('sync.drive_cleanup_done').replace('{f}', f).replace('{d}', d), 'success');
    }
  } catch {
    showToast(t('toast.sync_error'), 'error');
  } finally {
    setBusy(false);
  }
}

async function importFromDrive() {
  if(!DRIVE_ENABLED) return;
  setBusy(true, 'sync.importing');
  try {
    const res  = await fetch('/import-from-drive', { method: 'POST', credentials: 'include' });
    const data = await res.json();
    if(!res.ok || !data.ok) {
      showToast(t(data.message === 'no_drive_token' ? 'toast.sync_no_drive' : 'toast.sync_error'), 'error');
      return;
    }
    const imported = data.imported || 0;
    const cleaned  = data.cleaned  || 0;
    if(imported === 0 && cleaned === 0) {
      showToast(t('sync.import_nothing'), 'info');
    } else {
      if(imported > 0) showToast(t('toast.sync_imported').replace('{n}', imported), 'success');
      if(cleaned  > 0) showToast(t('sync.import_cleaned').replace('{n}', cleaned), 'info');
      loadUnprocessed();
      updateUnprocessedBadge();
    }
  } catch {
    showToast(t('toast.sync_error'), 'error');
  } finally {
    setBusy(false);
  }
}

// ══════════════════════════════════════════
// EXPORT
// ══════════════════════════════════════════
function openExportModal() {
  document.getElementById('export-modal-overlay').classList.add('open');
  lockScroll();
  updateExportCount();
}

function closeExportModal() {
  document.getElementById('export-modal-overlay').classList.remove('open');
  unlockScroll();
}

function onExportPeriodChange() {
  const period = document.getElementById('export-period').value;
  const isCustom = period === 'custom';
  document.getElementById('export-date-from-group').style.display = isCustom ? '' : 'none';
  document.getElementById('export-date-to-group').style.display = isCustom ? '' : 'none';
  updateExportCount();
}

function getExportDocs() {
  const period = document.getElementById('export-period').value;
  const status = document.getElementById('export-status').value;
  const inclArchived = document.getElementById('export-include-archived').checked;

  let docs = inclArchived
    ? [...sampleDocs, ...archivedDocs].filter(d => !d.isDeleted)
    : sampleDocs.filter(d => !d.isDeleted && !d.isArchived);

  // Period filter
  const now = new Date();
  if(period === 'this_month') {
    const y = now.getFullYear(), m = now.getMonth();
    docs = docs.filter(d => {
      const dt = new Date(d.date);
      return dt.getFullYear() === y && dt.getMonth() === m;
    });
  } else if(period === 'last_month') {
    const dt = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    const y = dt.getFullYear(), m = dt.getMonth();
    docs = docs.filter(d => {
      const dt2 = new Date(d.date);
      return dt2.getFullYear() === y && dt2.getMonth() === m;
    });
  } else if(period === 'this_year') {
    docs = docs.filter(d => new Date(d.date).getFullYear() === now.getFullYear());
  } else if(period === 'custom') {
    const from = document.getElementById('export-date-from').value;
    const to = document.getElementById('export-date-to').value;
    if(from) docs = docs.filter(d => d.date >= from);
    if(to)   docs = docs.filter(d => d.date <= to);
  }

  // Status filter
  if(status !== 'all') docs = docs.filter(d => d.status === status);

  return docs;
}

function updateExportCount() {
  const status = document.getElementById('export-status').value;
  if(status === 'archived') {
    document.getElementById('export-include-archived').checked = true;
  }
  const docs = getExportDocs();
  const el = document.getElementById('export-count-info');
  if(el) el.textContent = `${t('export.count')} ${docs.length} ${t('export.records')}`;
}


function getStatusLabel(status) {
  const key = status === 'no-return' ? 'status.no_return_full'
    : status === 'waiting' ? 'status.waiting_full'
    : status === 'partial' ? 'status.partial_full'
    : status === 'done' ? 'status.done_full'
    : status === 'ready' ? 'status.ready_full'
    : status === 'archived' ? 'status.archived_full'
    : null;
  return key ? t(key).replace(/^[^\s]+\s/, '') : status;
}

function buildExportRows(docs) {
  const headers = [
    t('export.col.date'), t('export.col.created'), t('export.col.title'), t('export.col.note'),
    t('export.col.company'), t('export.col.pay_type'), t('export.col.pay_method'), t('export.col.card'),
    t('export.col.amount'), t('export.col.currency'), t('export.col.status'),
    t('export.col.to_return'), t('export.col.returned'), t('export.col.remainder'),
    t('export.col.files')
  ];

  const rows = docs.map(d => [
    d.date,
    d.created,
    d.title,
    d.note || '',
    d.company,
    t('export.pay_type.' + d.payType) || d.payType,
    t('export.pay_method.' + d.payMethod) || d.payMethod,
    d.card || '',
    d.amount,
    'EUR',
    getStatusLabel(d.status),
    d.toReturn || 0,
    d.returned || 0,
    d.remainder || 0,
    d.files || 0,
  ]);

  return [headers, ...rows];
}

async function doExport(format) {
  const docs = getExportDocs();
  if(!docs.length) {
    showToast(t('toast.no_data'), 'error');
    return;
  }

  const rows = buildExportRows(docs);
  const now = new Date();
  const dateStr = now.toISOString().split('T')[0];
  const filename = `reimbursement-${dateStr}`;

  if(format === 'csv') {
    exportCSV(rows, filename);
  } else if(format === 'pdf') {
    await exportPDF(rows, filename);
  } else {
    exportXLSX(rows, filename);
  }

  closeExportModal();
  showToast(`${t('toast.exported')} ${docs.length} ${t('export.records')} ✓`, 'success');
}

function exportCSV(rows, filename) {
  const csv = rows.map(row =>
    row.map(cell => {
      const s = String(cell ?? '');
      return s.includes(',') || s.includes('"') || s.includes('\n')
        ? '"' + s.replace(/"/g, '""') + '"'
        : s;
    }).join(',')
  ).join('\n');

  const bom = '\uFEFF'; // UTF-8 BOM for Excel
  const blob = new Blob([bom + csv], { type: 'text/csv;charset=utf-8;' });
  downloadBlob(blob, filename + '.csv');
}

function exportXLSX(rows, filename) {
  if(typeof XLSX === 'undefined') {
    showToast(t('toast.xlsx_missing'), 'error');
    return;
  }

  const wb = XLSX.utils.book_new();
  const ws = XLSX.utils.aoa_to_sheet(rows);

  // Column widths
  ws['!cols'] = [
    {wch:12},{wch:12},{wch:30},{wch:30},
    {wch:18},{wch:14},{wch:14},{wch:18},
    {wch:10},{wch:8},{wch:22},
    {wch:14},{wch:12},{wch:12},{wch:10}
  ];

  // Style header row (bold)
  const range = XLSX.utils.decode_range(ws['!ref']);
  for(let c = range.s.c; c <= range.e.c; c++) {
    const cell = ws[XLSX.utils.encode_cell({r:0, c})];
    if(cell) {
      cell.s = { font: { bold: true }, fill: { fgColor: { rgb: 'E8EAF0' } } };
    }
  }

  XLSX.utils.book_append_sheet(wb, ws, t('export.sheet_name'));
  XLSX.writeFile(wb, filename + '.xlsx');
}

let _pdfFontBase64 = null;

async function loadPdfFont() {
  if(_pdfFontBase64) return _pdfFontBase64;
  const ttfRes = await fetch('/fonts/Roboto-Regular.ttf');
  const buf = await ttfRes.arrayBuffer();
  const bytes = new Uint8Array(buf);
  let binary = '';
  for(let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  _pdfFontBase64 = btoa(binary);
  return _pdfFontBase64;
}

async function exportPDF(rows, filename) {
  if(typeof window.jspdf === 'undefined') {
    showToast(t('toast.pdf_missing'), 'error');
    return;
  }

  showToast(t('toast.pdf_generating'), 'info');

  let fontBase64;
  try {
    fontBase64 = await loadPdfFont();
  } catch(e) {
    showToast(t('toast.font_error'), 'error');
    return;
  }

  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' });

  doc.addFileToVFS('Roboto-Regular.ttf', fontBase64);
  doc.addFont('Roboto-Regular.ttf', 'Roboto', 'normal');
  doc.setFont('Roboto', 'normal');

  const now = new Date();
  const locale = currentLang === 'de' ? 'de-DE' : currentLang === 'en' ? 'en-GB' : 'uk-UA';
  const dateStr = now.toLocaleDateString(locale);

  doc.setFontSize(12);
  doc.text(t('export.title'), 14, 14);
  doc.setFontSize(8);
  doc.text(dateStr, 14, 20);

  const head = [rows[0]];
  const body = rows.slice(1);

  doc.autoTable({
    head,
    body,
    startY: 25,
    styles: { fontSize: 7, cellPadding: 2, overflow: 'linebreak', font: 'Roboto' },
    headStyles: { fillColor: [60, 80, 160], textColor: 255, fontStyle: 'normal', font: 'Roboto' },
    alternateRowStyles: { fillColor: [245, 246, 250] },
    columnStyles: {
      0: { cellWidth: 18 },
      1: { cellWidth: 18 },
      2: { cellWidth: 30 },
      3: { cellWidth: 25 },
      4: { cellWidth: 20 },
      5: { cellWidth: 18 },
      6: { cellWidth: 18 },
      7: { cellWidth: 18 },
      8: { cellWidth: 14 },
      9: { cellWidth: 10 },
      10: { cellWidth: 22 },
      11: { cellWidth: 16 },
      12: { cellWidth: 16 },
      13: { cellWidth: 14 },
      14: { cellWidth: 14 },
    },
    margin: { left: 7, right: 7 },
    didDrawPage: (data) => {
      const pageCount = doc.internal.getNumberOfPages();
      doc.setFontSize(7);
      doc.setFont('Roboto', 'normal');
      doc.text(`${data.pageNumber} / ${pageCount}`, doc.internal.pageSize.getWidth() - 15, doc.internal.pageSize.getHeight() - 5);
    }
  });

  doc.save(filename + '.pdf');
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// legacy alias
function exportData() { openExportModal(); }

// ── BADGES ──
async function updateBadges() {
  const active = sampleDocs.filter(d => !d.isArchived && !d.isDeleted).length;
  const [deletedRecords, deletedInstruments, deletedCompanies] = await Promise.all([
    loadDeletedRecords(), loadDeletedInstruments(), loadDeletedCompanies()
  ]);
  const deleted = deletedRecords.length + deletedInstruments.length + deletedCompanies.length;
  document.getElementById('docs-count').textContent = active || '';
  document.getElementById('trash-count').textContent = deleted || '';
}

// ── TOAST ──
function setBusy(on, msgKey = 'busy.uploading') {
  const el = document.getElementById('busy-overlay');
  if (!el) return;
  if (on) {
    document.getElementById('busy-text').textContent = t(msgKey);
    el.classList.remove('hidden');
  } else {
    el.classList.add('hidden');
  }
}

function showToast(msg, type='success') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = 'toast ' + type;
  toast.innerHTML = (type === 'success' ? '✓' : '✕') + ' ' + msg;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}


// ── DETAIL VIEW ──
let currentDetailId = null;

const docIcons = {
  private: '💼', company: '🏢'
};

function openDetail(id) {
  const doc = sampleDocs.find(d => d.id === id) || archivedDocs.find(d => d.id === id);
  if(!doc) return;
  currentDetailId = id;

  // Header
  document.getElementById('detail-icon').textContent = doc.payType === 'private' ? '💼' : '🏢';
  document.getElementById('detail-title').textContent = doc.title;
  document.getElementById('detail-status-badge').innerHTML = statusBadge(doc.status);
  document.getElementById('detail-company-meta').textContent = '· ' + doc.company;
  document.getElementById('detail-date-meta').textContent = '· ' + formatDate(doc.date);

  // Finance grid
  const finGrid = document.getElementById('detail-finance-grid');
  finGrid.innerHTML = `
    <div class="detail-field">
      <div class="detail-field-label">${t('detail.amount')}</div>
      <div class="detail-field-value mono" style="font-size:22px;font-weight:300">${doc.currency}${doc.amount.toFixed(2)}</div>
    </div>
    <div class="detail-field">
      <div class="detail-field-label">${t('detail.date')}</div>
      <div class="detail-field-value">${formatDate(doc.date)}</div>
    </div>
    <div class="detail-field">
      <div class="detail-field-label">${t('detail.created')}</div>
      <div class="detail-field-value" style="color:var(--text2)">${formatDateTime(doc.created)}</div>
    </div>
  `;

  // Return section
  const returnSection = document.getElementById('detail-return-section');
  if(doc.payType === 'private') {
    returnSection.style.display = '';
    renderReturnSection(doc);
  } else {
    returnSection.style.display = 'none';
  }

  // Payment grid
  const payGrid = document.getElementById('detail-payment-grid');
  payGrid.innerHTML = `
    <div class="detail-field">
      <div class="detail-field-label">${t('detail.pay_type')}</div>
      <div class="detail-field-value">${doc.payType === 'private' ? t('detail.private') : t('detail.company_pay')}</div>
    </div>
    <div class="detail-field">
      <div class="detail-field-label">${t('detail.pay_method')}</div>
      <div class="detail-field-value">${doc.payMethod === 'card' ? t('detail.by_card') : t('detail.by_cash')}</div>
    </div>
    <div class="detail-field">
      <div class="detail-field-label">${t('detail.card')}</div>
      <div class="detail-field-value ${doc.card ? '' : 'muted'}">${doc.card || t('detail.no_card')}</div>
    </div>
    <div class="detail-field">
      <div class="detail-field-label">${t('detail.company')}</div>
      <div class="detail-field-value">🏢 ${doc.company}</div>
    </div>
    <div class="detail-field">
      <div class="detail-field-label">${t('detail.currency')}</div>
      <div class="detail-field-value mono">${t('detail.currency_eur')}</div>
    </div>
    <div class="detail-field">
      <div class="detail-field-label">${t('detail.files_count')}</div>
      <div class="detail-field-value">${doc.files > 0 ? '📎 ' + doc.files + ' ' + t('detail.files_unit') : '<span style="color:var(--text3);font-weight:400">' + t('detail.files_none') + '</span>'}</div>
    </div>
  `;

  // Note
  const noteEl = document.getElementById('detail-note-text');
  noteEl.textContent = doc.note || '—';
  if(!doc.note) noteEl.style.color = 'var(--text3)';
  else noteEl.style.color = '';

  // Attachments
  renderAttachments(doc);

  // Reset add-return form
  document.getElementById('add-return-form').classList.remove('open');
  document.getElementById('ret-date').value = new Date().toISOString().split('T')[0];

  document.getElementById('detail-overlay').classList.add('open');
  lockScroll();
}

function renderReturnSection(doc) {
  const pct = doc.amount > 0 ? Math.min(100, (doc.returned / doc.amount) * 100) : 0;

  document.getElementById('detail-return-summary').innerHTML = `
    <div class="return-box highlight">
      <div class="return-box-label">${t('detail.to_return')}</div>
      <div class="return-box-value">${doc.currency}${doc.toReturn.toFixed(2)}</div>
    </div>
    <div class="return-box success">
      <div class="return-box-label">${t('detail.returned')}</div>
      <div class="return-box-value">${doc.currency}${doc.returned.toFixed(2)}</div>
    </div>
    <div class="return-box ${doc.remainder > 0 ? 'highlight' : ''}">
      <div class="return-box-label">${t('detail.remainder')}</div>
      <div class="return-box-value" style="${doc.remainder === 0 ? 'color:var(--green)' : ''}">${doc.currency}${doc.remainder.toFixed(2)}</div>
    </div>
  `;

  document.getElementById('detail-progress-bar').style.width = pct + '%';

  // Return events
  const eventsEl = document.getElementById('detail-return-events');
  if(!doc.returnEvents || doc.returnEvents.length === 0) {
    eventsEl.innerHTML = `<div style="text-align:center;padding:16px 0;color:var(--text3);font-size:12px">${t('detail.no_returns')}</div>`;
  } else {
    eventsEl.innerHTML = doc.returnEvents.map((ev, i) => `
      <div class="return-event-row">
        <div class="return-event-num">${i+1}</div>
        <div class="return-event-info">
          <div class="return-event-amount">${doc.currency}${ev.amount.toFixed(2)}</div>
          <div class="return-event-meta">${ev.method || t('detail.no_method')}</div>
        </div>
        <div class="return-event-date">${formatDate(ev.date)}</div>
        <button class="icon-btn danger" title="${t('detail.delete')}" onclick="deleteReturnEvent('${ev.id}')" style="margin-left:4px">✕</button>
      </div>
    `).join('');
  }
}

function renderAttachments(doc) {
  const grid = document.getElementById('detail-attachments');
  if(!doc.attachments || doc.attachments.length === 0) {
    grid.innerHTML = `<div style="color:var(--text3);font-size:12px;padding:8px 0">${t('detail.no_attachments')}</div>`;
    return;
  }
  grid.innerHTML = doc.attachments.map(f => {
    const isPdf = f.type === 'application/pdf';
    const shortName = f.name.length > 15 ? f.name.substring(0,13) + '…' : f.name;
    return `
      <div class="attachment-thumb" onclick="viewAttachment('${f.id}')">
        <button class="attachment-delete" onclick="event.stopPropagation();deleteAttachment('${f.id}')" title="${t('detail.delete')}">✕</button>
        <div class="attachment-thumb-icon">${isPdf ? '📄' : '🖼️'}</div>
        <div class="attachment-thumb-name">${shortName}</div>
      </div>
    `;
  }).join('');
}

function viewAttachment(id) {
  window.open(API_URL + '/attachments/' + id + '/file', '_blank');
}

async function deleteAttachment(id) {
  try {
    const res = await deleteAttachmentDB(id);
    const doc = sampleDocs.find(d => d.id === currentDetailId) || archivedDocs.find(d => d.id === currentDetailId);
    if(doc) {
      doc.attachments = doc.attachments.filter(a => a.id !== id);
      doc.files = doc.attachments.length;
      renderAttachments(doc);
    }
    renderDocs();
    updateDashboard();
    if(res.drive_warning) showToast('Файл видалено локально, але не з Drive: ' + res.drive_warning, 'warning');
  } catch(e) {
    showToast(t('toast.file_delete_error'), 'error');
  }
}

async function addFilesToRecord(input) {
  const files = Array.from(input.files);
  if(!files.length) return;
  const doc = sampleDocs.find(d => d.id === currentDetailId) || archivedDocs.find(d => d.id === currentDetailId);
  if(!doc) return;
  input.value = '';
  setBusy(true, 'busy.uploading');
  try {
    for(const file of files) {
      const att = await uploadAttachment(currentDetailId, file);
      if(!doc.attachments) doc.attachments = [];
      doc.attachments.push({ id: att.id, name: att.file_name, type: att.file_type, storageType: 'local' });
      doc.files = doc.attachments.length;
    }
    renderAttachments(doc);
    renderDocs();
    showToast(t('toast.files_added'), 'success');
  } catch(e) {
    showToast(t('toast.file_upload_error'), 'error');
  } finally {
    setBusy(false);
  }
}

function closeDetail() {
  document.getElementById('detail-overlay').classList.remove('open');
  unlockScroll();
  currentDetailId = null;
}

function closeDetailOutside(e) {
  if(e.target === document.getElementById('detail-overlay')) closeDetail();
}

function editRecord() {
  const id = currentDetailId;
  closeDetail();
  openEditModal(id);
}

async function archiveRecord() {
  try {
    const idx = sampleDocs.findIndex(d => d.id === currentDetailId);
    const previousStatus = idx !== -1 ? sampleDocs[idx].status : 'waiting';
    await archiveRecordDB(currentDetailId, previousStatus);
    if(idx !== -1) {
      const doc = { ...sampleDocs[idx], previousStatus, status: 'archived', isArchived: true };
      sampleDocs.splice(idx, 1);
      archivedDocs.unshift(doc);
    }
    filteredDocs = sampleDocs.filter(d => !d.isArchived && !d.isDeleted);
    filteredArchived = archivedDocs.filter(d => !d.isDeleted);
    renderDocs();
    updateDashboard();
    updateBadges();
    closeDetail();
    showToast(t('toast.archived'), 'success');
  } catch(e) {
    showToast(_errMsg(e), 'error');
  }
}

async function deleteRecord() {
  try {
    await deleteRecordDB(currentDetailId);
    const doc = sampleDocs.find(d => d.id === currentDetailId);
    if(doc) { doc.isDeleted = true; }
    filteredDocs = sampleDocs.filter(d => !d.isArchived && !d.isDeleted);
    renderDocs();
    updateDashboard();
    updateBadges();
    closeDetail();
    showToast(t('toast.deleted'), 'success');
  } catch(e) {
    showToast(_errMsg(e), 'error');
  }
}

async function archiveRecordById(id) {
  try {
    const idx = sampleDocs.findIndex(d => d.id === id);
    const previousStatus = idx !== -1 ? sampleDocs[idx].status : 'waiting';
    await archiveRecordDB(id, previousStatus);
    if(idx !== -1) {
      const doc = { ...sampleDocs[idx], previousStatus, status: 'archived', isArchived: true };
      sampleDocs.splice(idx, 1);
      archivedDocs.unshift(doc);
    }
    filteredDocs = sampleDocs.filter(d => !d.isArchived && !d.isDeleted);
    filteredArchived = archivedDocs.filter(d => !d.isDeleted);
    renderDocs();
    updateDashboard();
    updateBadges();
    showToast(t('toast.archived'), 'success');
  } catch(e) {
    showToast(_errMsg(e), 'error');
  }
}

async function trashRecordById(id) {
  try {
    await deleteRecordDB(id);
    const doc = sampleDocs.find(d => d.id === id);
    if(doc) { doc.isDeleted = true; }
    filteredDocs = sampleDocs.filter(d => !d.isArchived && !d.isDeleted);
    renderDocs();
    updateDashboard();
    updateBadges();
    showToast(t('toast.deleted'), 'success');
  } catch(e) {
    showToast(_errMsg(e), 'error');
  }
}

// ── ADD RETURN EVENT ──
function toggleAddReturn() {
  const form = document.getElementById('add-return-form');
  form.classList.toggle('open');
  if(form.classList.contains('open')) {
    document.getElementById('ret-amount').focus();
  }
}

async function saveReturn() {
  const amount = parseFloat(document.getElementById('ret-amount').value);
  const date = document.getElementById('ret-date').value;
  const method = document.getElementById('ret-method').value;

  if(!amount || amount <= 0 || !date) {
    showToast(t('toast.return_required'), 'error');
    return;
  }

  const doc = sampleDocs.find(d => d.id === currentDetailId);
  if(!doc) return;

  try {
    await addReturnEvent(currentDetailId, amount, date, method);
    const updated = sampleDocs.find(d => d.id === currentDetailId);
    renderReturnSection(updated);
    renderDocs();
    updateDashboard();
    document.getElementById('ret-amount').value = '';
    document.getElementById('ret-method').value = '';
    document.getElementById('add-return-form').classList.remove('open');
    showToast(t('toast.return_saved'), 'success');
  } catch(e) {
    showToast(_errMsg(e), 'error');
  }
}

async function deleteReturnEvent(eventId) {
  const doc = sampleDocs.find(d => d.id === currentDetailId);
  if(!doc) return;
  try {
    await deleteReturnEventDB(eventId, currentDetailId);
    const updated = sampleDocs.find(d => d.id === currentDetailId);
    renderReturnSection(updated);
    renderDocs();
    updateDashboard();
    showToast(t('toast.return_deleted'), 'success');
  } catch(e) {
    showToast(_errMsg(e), 'error');
  }
}




async function unarchiveRecord(id) {
  try {
    const idx = archivedDocs.findIndex(d => d.id === id);
    const restoredStatus = (idx !== -1 && archivedDocs[idx].previousStatus) ? archivedDocs[idx].previousStatus : 'waiting';
    await apiPut('/records/' + id, { is_archived: 0, status: restoredStatus, previous_status: null });
    if(idx !== -1) {
      const doc = { ...archivedDocs[idx], isArchived: false, status: restoredStatus, previousStatus: null };
      archivedDocs.splice(idx, 1);
      sampleDocs.unshift(doc);
    }
    filteredDocs = sampleDocs.filter(d => !d.isArchived && !d.isDeleted);
    filteredArchived = archivedDocs.filter(d => !d.isDeleted);
    renderDocs();
    updateDashboard();
    updateBadges();
    showToast(t('toast.unarchived'), 'success');
  } catch(e) {
    const msg = e.message || '';
    if(msg.includes('forbidden') || msg.includes('no_org')) showToast('Недостатньо прав для цієї дії', 'error');
    else showToast(t('toast.error'), 'error');
  }
}

async function deleteFromArchive(id) {
  try {
    await apiPut('/records/' + id, { is_deleted: 1, is_archived: 0, deleted_at: new Date().toISOString() });
    const idx = archivedDocs.findIndex(d => d.id === id);
    if(idx !== -1) archivedDocs.splice(idx, 1);
    filteredArchived = archivedDocs.filter(d => !d.isDeleted);
    renderArchiveSection();
    updateBadges();
    showToast(t('toast.deleted'), 'success');
  } catch(e) { showToast(_errMsg(e), 'error'); }
}

// ── TRASH PAGE ──
async function loadAndRenderTrash() {
  const list = document.getElementById('trash-list');
  list.innerHTML = '<div class="empty-state"><div class="spinner" style="margin:0 auto"></div></div>';
  const [records, instruments, companies] = await Promise.all([
    loadDeletedRecords(), loadDeletedInstruments(), loadDeletedCompanies()
  ]);
  if(!records.length && !instruments.length && !companies.length) {
    list.innerHTML = `<div class="empty-state"><div class="empty-icon">🗑️</div><div class="empty-title">${t('trash.empty')}</div><div class="empty-sub">${t('trash.empty_sub')}</div></div>`;
    return;
  }
  const typeIcon = { private_card: '💳', company_card: '🏢', cash: '💵' };
  let html = '';
  if(companies.length) {
    html += '<div class="card" style="margin-bottom:12px">' + companies.map(c => `
      <div class="settings-item">
        <div class="settings-item-icon" style="opacity:0.5">🏢</div>
        <div class="settings-item-info">
          <div class="settings-item-name" style="opacity:0.6">${c.name}</div>
          <div class="settings-item-sub">${t('table.company')}</div>
        </div>
        <div class="settings-item-actions">
          <button class="btn btn-ghost" style="font-size:12px" onclick="restoreCompany('${c.id}')">${t('trash.restore')}</button>
          <button class="icon-btn danger" title="${t('trash.delete_perm')}" onclick="permanentDeleteCompany('${c.id}')">✕</button>
        </div>
      </div>
    `).join('') + '</div>';
  }
  if(instruments.length) {
    html += '<div class="card" style="margin-bottom:12px">' + instruments.map(i => `
      <div class="settings-item">
        <div class="settings-item-icon" style="opacity:0.5">${typeIcon[i.type] || '💳'}</div>
        <div class="settings-item-info">
          <div class="settings-item-name" style="opacity:0.6">${i.name}</div>
          <div class="settings-item-sub">${t('settings.instrument_single')}</div>
        </div>
        <div class="settings-item-actions">
          <button class="btn btn-ghost" style="font-size:12px" onclick="restoreInstrument('${i.id}')">${t('trash.restore')}</button>
          <button class="icon-btn danger" title="${t('trash.delete_perm')}" onclick="permanentDeleteInstrument('${i.id}')">✕</button>
        </div>
      </div>
    `).join('') + '</div>';
  }
  if(records.length) {
    html += '<div class="card">' + records.map(r => `
      <div class="settings-item">
        <div class="settings-item-icon" style="opacity:0.5">📄</div>
        <div class="settings-item-info">
          <div class="settings-item-name" style="opacity:0.6">${r.title}</div>
          <div class="settings-item-sub">${formatDate(r.date)} · €${r.amount.toFixed(2)} · ${r.company}</div>
        </div>
        <div class="settings-item-actions">
          <button class="btn btn-ghost" style="font-size:12px" onclick="restoreRecord('${r.id}', '${r.status}')">${t('trash.restore')}</button>
          <button class="icon-btn danger" title="${t('trash.delete_perm')}" onclick="permanentDelete('${r.id}')">✕</button>
        </div>
      </div>
    `).join('') + '</div>';
  }
  list.innerHTML = html;
}

async function restoreRecord(id, status) {
  try {
    const isArchived = status === 'archived';
    await apiPut('/records/' + id, { is_deleted: 0, deleted_at: null, ...(isArchived ? { is_archived: 1 } : {}) });
    showToast(t('toast.restored'), 'success');
    loadAndRenderTrash();
    const [records, archived] = await Promise.all([loadRecords(), loadArchivedRecords()]);
    sampleDocs.length = 0;
    records.forEach(r => sampleDocs.push(r));
    archivedDocs.length = 0;
    archived.forEach(r => archivedDocs.push(r));
    filteredDocs = sampleDocs.filter(d => !d.isArchived && !d.isDeleted);
    filteredArchived = archivedDocs.filter(d => !d.isDeleted);
    renderDocs();
    updateDashboard();
    updateBadges();
  } catch(e) {
    const msg = e.message || '';
    if(msg.includes('forbidden') || msg.includes('no_org')) showToast('Недостатньо прав для цієї дії', 'error');
    else showToast(t('toast.error'), 'error');
  }
}

async function permanentDelete(id) {
  try {
    await permanentDeleteDB(id);
    const idx = sampleDocs.findIndex(d => d.id === id);
    if(idx !== -1) sampleDocs.splice(idx, 1);
    showToast(t('toast.perm_deleted'), 'success');
    loadAndRenderTrash();
    updateBadges();
  } catch(e) { showToast(_errMsg(e), 'error'); }
}

async function emptyTrash() {
  const [records, instruments, companies] = await Promise.all([
    loadDeletedRecords(), loadDeletedInstruments(), loadDeletedCompanies()
  ]);
  for(const r of records) { await permanentDeleteDB(r.id); }
  for(const i of instruments) { await permanentDeleteInstrumentDB(i.id); }
  for(const c of companies) { await permanentDeleteCompanyDB(c.id); }
  records.forEach(r => { const idx = sampleDocs.findIndex(d => d.id === r.id); if(idx !== -1) sampleDocs.splice(idx, 1); });
  showToast(t('toast.trash_cleared'), 'success');
  loadAndRenderTrash();
  updateBadges();
}

// ── THEMES ──
const themes = {
  'dark': {
    '--bg':'#0f1117','--bg2':'#161b27','--bg3':'#1e2535','--bg4':'#252d40',
    '--border':'#2a3348','--border2':'#334060',
    '--text':'#e8eaf0','--text2':'#8892a4','--text3':'#5a6478',
  },
  'dark-blue': {
    '--bg':'#0a0f1e','--bg2':'#0d1528','--bg3':'#162038','--bg4':'#1a2540',
    '--border':'#1e2d4a','--border2':'#263860',
    '--text':'#dde8ff','--text2':'#6e86b8','--text3':'#3d5280',
  },
  'dark-green': {
    '--bg':'#0a1210','--bg2':'#0d1a16','--bg3':'#152620','--bg4':'#1a2e26',
    '--border':'#1e3028','--border2':'#254036',
    '--text':'#d8ede6','--text2':'#6a9982','--text3':'#3a6050',
  },
  'light': {
    '--bg':'#d8dce6','--bg2':'#e8ecf4','--bg3':'#ccd2de','--bg4':'#c0c8d4',
    '--border':'#adb8c8','--border2':'#96a4b8',
    '--text':'#1a1f2e','--text2':'#4a5568','--text3':'#8896aa',
  },
  'mocha': {
    '--bg':'#1a1310','--bg2':'#211916','--bg3':'#26201c','--bg4':'#2e2520',
    '--border':'#382e28','--border2':'#463b34',
    '--text':'#ede0d8','--text2':'#9a8278','--text3':'#5e4e48',
  },
  'slate': {
    '--bg':'#13161f','--bg2':'#191d28','--bg3':'#1f2330','--bg4':'#252a38',
    '--border':'#2c3244','--border2':'#363d52',
    '--text':'#e2e6f0','--text2':'#808aa0','--text3':'#4a5268',
  },
  'lavender': {
    '--bg':'#cfc8e8','--bg2':'#dfdaf0','--bg3':'#c4bcdc','--bg4':'#b8b0d0',
    '--border':'#a49cc2','--border2':'#9088b2',
    '--text':'#2a2640','--text2':'#645e88','--text3':'#9890b4',
  },
  'frost': {
    '--bg':'#ccd4e4','--bg2':'#dce4f0','--bg3':'#bec8d8','--bg4':'#b2bece',
    '--border':'#9aaec0','--border2':'#88a0b4',
    '--text':'#1a2434','--text2':'#4a607a','--text3':'#849ab0',
  },
  'sage': {
    '--bg':'#c8d8ca','--bg2':'#d8e8da','--bg3':'#bccebe','--bg4':'#b0c4b2',
    '--border':'#9cb8a0','--border2':'#8aaa8e',
    '--text':'#1e2c22','--text2':'#4c6452','--text3':'#88a08e',
  },
  'mist': {
    '--bg':'#ccd0d8','--bg2':'#dcdfe8','--bg3':'#bec4cc','--bg4':'#b2b8c2',
    '--border':'#9ea6b4','--border2':'#8c96a8',
    '--text':'#1c2030','--text2':'#4a5068','--text3':'#828898',
  },
};

function setTheme(name, el, silent = false) {
  const t = themes[name];
  if(!t) return;
  const root = document.documentElement;
  Object.entries(t).forEach(([k,v]) => root.style.setProperty(k, v));
  localStorage.setItem('theme', name);

  document.querySelectorAll('.theme-card').forEach(c => c.classList.remove('active'));
  if(el) el.classList.add('active');
  if(!silent) showToast(t('toast.theme_changed'), 'success');
}

function setAccent(color, color2, el, silent = false) {
  const root = document.documentElement;
  root.style.setProperty('--accent', color);
  root.style.setProperty('--accent2', color2);
  root.style.setProperty('--accent-glow', hexToRgba(color, 0.15));
  localStorage.setItem('accent', color);
  localStorage.setItem('accent2', color2);

  document.querySelectorAll('.accent-swatch').forEach(s => s.classList.remove('active'));
  if(el) el.classList.add('active');
  if(!silent) showToast(t('toast.accent_changed'), 'success');
}

function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1,3),16);
  const g = parseInt(hex.slice(3,5),16);
  const b = parseInt(hex.slice(5,7),16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function loadSavedTheme() {
  const saved = localStorage.getItem('theme');
  const savedAccent = localStorage.getItem('accent');
  const savedAccent2 = localStorage.getItem('accent2');
  if(saved && themes[saved]) {
    const el = document.getElementById('theme-' + saved);
    setTheme(saved, el, true);
  }
  if(savedAccent) {
    const el = Array.from(document.querySelectorAll('.accent-swatch'))
      .find(s => s.style.getPropertyValue('--sw') === savedAccent);
    setAccent(savedAccent, savedAccent2 || savedAccent, el, true);
  }
}

// init card select visibility
document.getElementById('card-select-group').style.display = 'none';
// ══════════════════════════════════════════
// SETTINGS — COMPANIES
// ══════════════════════════════════════════
let companiesCache = [];
let editingCompanyId = null;

async function loadAndRenderCompanies() {
  const list = document.getElementById('companies-list');
  if(!list) return;
  companiesCache = await loadCompanies();
  renderCompaniesList();
}

function renderCompaniesList() {
  const list = document.getElementById('companies-list');
  if(!list) return;
  if(!companiesCache.length) {
    list.innerHTML = `<div style="text-align:center;padding:24px;color:var(--text3);font-size:13px">${t('settings.no_companies')}</div>`;
    return;
  }
  list.innerHTML = companiesCache.slice().reverse().map(c => `
    <div class="settings-item ${!c.is_active ? 'deactivated' : ''}">
      <div class="settings-item-icon">🏢</div>
      <div class="settings-item-info">
        <div class="settings-item-name">${c.name}</div>
      </div>
      <div class="settings-item-actions">
        ${canWrite() ? `<button class="icon-btn" title="${t('detail.edit')}" onclick="openCompanyModal('${c.id}')">✏️</button>
        <button class="icon-btn" title="${c.is_active ? t('btn.deactivate') : t('btn.activate')}"
          onclick="toggleCompanyActive('${c.id}', ${c.is_active})">
          ${c.is_active ? '⏸' : '▶'}
        </button>
        <button class="icon-btn danger" title="${t('detail.delete')}" onclick="deleteCompany('${c.id}', '${c.name.replace(/'/g, "\\'")}')">🗑️</button>` : ''}
      </div>
    </div>
  `).join('');
}

function openCompanyModal(id = null) {
  editingCompanyId = id;
  const title = document.getElementById('company-modal-title');
  const nameInput = document.getElementById('company-name-input');

  if(id) {
    const c = companiesCache.find(c => c.id === id);
    title.textContent = t('company.edit');
    nameInput.value = c.name;
  } else {
    title.textContent = t('company.new');
    nameInput.value = '';
  }

  document.getElementById('company-modal-overlay').classList.add('open');
  lockScroll();
  setTimeout(() => nameInput.focus(), 100);
}

function closeCompanyModal() {
  document.getElementById('company-modal-overlay').classList.remove('open');
  unlockScroll();
  editingCompanyId = null;
}

async function saveCompanyModal() {
  const name = document.getElementById('company-name-input').value.trim();

  if(!name) {
    document.getElementById('company-name-input').style.borderColor = 'var(--red)';
    setTimeout(() => document.getElementById('company-name-input').style.borderColor = '', 2000);
    showToast(t('toast.company_name_required'), 'error');
    return;
  }

  try {
    if(editingCompanyId) {
      await apiPut('/companies/' + editingCompanyId, { name });
      showToast(t('toast.company_updated'), 'success');
    } else {
      await apiPost('/companies', {
        name,
        sort_order: companiesCache.length
      });
      showToast(t('toast.company_saved'), 'success');
    }
    closeCompanyModal();
    await loadAndRenderCompanies();
    // Refresh dropdowns
    const companies = await loadCompanies();
    populateCompanyDropdowns(companies);
  } catch(e) {
    showToast(_errMsg(e), 'error');
  }
}

async function toggleCompanyActive(id, isActive) {
  try {
    await apiPut('/companies/' + id, { is_active: !isActive });
    await loadAndRenderCompanies();
    showToast(isActive ? t('toast.company_deactivated') : t('toast.company_activated'), 'success');
  } catch(e) {
    showToast(t('toast.error'), 'error');
  }
}

async function deleteCompany(id, name) {
  if(!confirm(t('confirm.to_trash').replace('{name}', name))) return;
  try {
    await apiDelete('/companies/' + id);
    await loadAndRenderCompanies();
    const companies = await loadCompanies();
    populateCompanyDropdowns(companies);
    showToast(t('toast.deleted'), 'success');
    updateBadges();
  } catch(e) {
    showToast(_errMsg(e), 'error');
  }
}

async function restoreCompany(id) {
  try {
    await restoreCompanyDB(id);
    await loadAndRenderCompanies();
    const companies = await loadCompanies();
    populateCompanyDropdowns(companies);
    showToast(t('toast.company_restored'), 'success');
    loadAndRenderTrash();
    updateBadges();
  } catch(e) { showToast(_errMsg(e), 'error'); }
}

async function permanentDeleteCompany(id) {
  try {
    await permanentDeleteCompanyDB(id);
    showToast(t('toast.company_perm_deleted'), 'success');
    loadAndRenderTrash();
    updateBadges();
  } catch(e) { showToast(_errMsg(e), 'error'); }
}

// ══════════════════════════════════════════
// SETTINGS — INSTRUMENTS
// ══════════════════════════════════════════
let instrumentsCache = [];
let editingInstrumentId = null;

async function loadAndRenderInstruments() {
  const list = document.getElementById('instruments-list');
  if(!list) return;
  instrumentsCache = await loadInstruments();
  renderInstrumentsList();
}

function renderInstrumentsList() {
  const list = document.getElementById('instruments-list');
  if(!list) return;
  if(!instrumentsCache.length) {
    list.innerHTML = `<div style="text-align:center;padding:24px;color:var(--text3);font-size:13px">${t('settings.no_instruments')}</div>`;
    return;
  }

  const typeLabel = { private_card: t('instrument.private_card'), company_card: t('instrument.company_card'), cash: t('instrument.cash') };
  const typeClass = { private_card: 'type-private', company_card: 'type-company', cash: 'type-cash' };
  const typeIcon  = { private_card: '💳', company_card: '🏢', cash: '💵' };

  list.innerHTML = instrumentsCache.slice().reverse().map(i => `
    <div class="settings-item ${!i.is_active ? 'deactivated' : ''}">
      <div class="settings-item-icon">${typeIcon[i.type] || '💳'}</div>
      <div class="settings-item-info">
        <div class="settings-item-name">${i.name}</div>
        <div class="settings-item-sub">
          <span class="type-chip ${typeClass[i.type] || ''}">${typeLabel[i.type] || i.type}</span>
        </div>
      </div>
      <div class="settings-item-actions">
        ${canWrite() ? `<button class="icon-btn" title="${t('detail.edit')}" onclick="openInstrumentModal('${i.id}')">✏️</button>
        <button class="icon-btn" title="${i.is_active ? t('btn.deactivate') : t('btn.activate')}"
          onclick="toggleInstrumentActive('${i.id}', ${i.is_active})">
          ${i.is_active ? '⏸' : '▶'}
        </button>
        <button class="icon-btn danger" title="${t('detail.delete')}" onclick="deleteInstrument('${i.id}', '${i.name.replace(/'/g, "\\'")}')">🗑️</button>` : ''}
      </div>
    </div>
  `).join('');
}

function openInstrumentModal(id = null) {
  editingInstrumentId = id;
  const title = document.getElementById('instrument-modal-title');
  const nameInput = document.getElementById('instrument-name-input');
  const typeInput = document.getElementById('instrument-type-input');

  if(id) {
    const i = instrumentsCache.find(i => i.id === id);
    title.textContent = t('instrument.edit');
    nameInput.value = i.name;
    typeInput.value = i.type;
  } else {
    title.textContent = t('instrument.new');
    nameInput.value = '';
    typeInput.value = '';
  }

  document.getElementById('instrument-modal-overlay').classList.add('open');
  lockScroll();
  setTimeout(() => nameInput.focus(), 100);
}

function closeInstrumentModal() {
  document.getElementById('instrument-modal-overlay').classList.remove('open');
  unlockScroll();
  editingInstrumentId = null;
}

async function saveInstrumentModal() {
  const name = document.getElementById('instrument-name-input').value.trim();
  const type = document.getElementById('instrument-type-input').value;

  if(!name || !type) {
    showToast(t('toast.fill_required'), 'error');
    return;
  }

  try {
    if(editingInstrumentId) {
      await apiPut('/instruments/' + editingInstrumentId, { name, type });
      showToast(t('toast.instrument_updated'), 'success');
    } else {
      await apiPost('/instruments', {
        name,
        type,
        sort_order: instrumentsCache.length
      });
      showToast(t('toast.instrument_saved'), 'success');
    }
    closeInstrumentModal();
    await loadAndRenderInstruments();
    // Refresh dropdowns
    const instruments = await loadInstruments();
    populateInstrumentDropdowns(instruments);
  } catch(e) {
    showToast(_errMsg(e), 'error');
  }
}

async function toggleInstrumentActive(id, isActive) {
  try {
    await apiPut('/instruments/' + id, { is_active: !isActive });
    await loadAndRenderInstruments();
    showToast(isActive ? t('toast.deactivated') : t('toast.activated'), 'success');
  } catch(e) {
    showToast(t('toast.error'), 'error');
  }
}

async function deleteInstrument(id, name) {
  if(!confirm(t('confirm.to_trash').replace('{name}', name))) return;
  try {
    await apiDelete('/instruments/' + id);
    await loadAndRenderInstruments();
    const instruments = await loadInstruments();
    populateInstrumentDropdowns(instruments);
    showToast(t('toast.deleted'), 'success');
    updateBadges();
  } catch(e) {
    showToast(_errMsg(e), 'error');
  }
}

async function restoreInstrument(id) {
  try {
    await restoreInstrumentDB(id);
    await loadAndRenderInstruments();
    const instruments = await loadInstruments();
    populateInstrumentDropdowns(instruments);
    showToast(t('toast.instrument_restored'), 'success');
    loadAndRenderTrash();
    updateBadges();
  } catch(e) { showToast(_errMsg(e), 'error'); }
}

async function permanentDeleteInstrument(id) {
  try {
    await permanentDeleteInstrumentDB(id);
    showToast(t('toast.instrument_perm_deleted'), 'success');
    loadAndRenderTrash();
    updateBadges();
  } catch(e) { showToast(_errMsg(e), 'error'); }
}

// ══════════════════════════════════════════
// UNPROCESSED IMPORTS
// ══════════════════════════════════════════
// ══════════════════════════════════════════
// GALLERY
// ══════════════════════════════════════════
let _galleryItems = [];

async function loadGallery() {
  try {
    const res = await fetch('/gallery', { credentials: 'include' });
    _galleryItems = await res.json();
    renderGallery(_galleryItems);
  } catch(e) {
    renderGallery([]);
  }
}

function _gesc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function renderGallery(items) {
  const grid  = document.getElementById('gallery-grid');
  const empty = document.getElementById('gallery-empty');
  if (!grid) return;

  if (!items.length) {
    empty.style.display = '';
    grid.innerHTML = '';
    return;
  }
  empty.style.display = 'none';

  const locale = currentLang === 'de' ? 'de-DE' : currentLang === 'en' ? 'en-GB' : 'uk-UA';

  // Group: year → month → day → record_id → { title, meta, files[] }
  const tree = {};
  items.forEach((item, idx) => {
    const date = (item.record_date || '').slice(0, 10) || '0000-00-00';
    const [year, month, day] = date.split('-');
    const recId = item.record_id || '_';
    if (!tree[year]) tree[year] = {};
    if (!tree[year][month]) tree[year][month] = {};
    if (!tree[year][month][day]) tree[year][month][day] = {};
    if (!tree[year][month][day][recId]) tree[year][month][day][recId] = {
      title: item.record_title || '—',
      meta: [item.company_name, item.card_name].filter(Boolean).join(' · '),
      files: []
    };
    tree[year][month][day][recId].files.push({ item, idx });
  });

  const years = Object.keys(tree).sort().reverse();
  let html = '<div class="gallery-tree">';

  years.forEach((year, yi) => {
    const months = Object.keys(tree[year]).sort().reverse();
    html += `<details class="gt-year" open><summary class="gt-node gt-year-node"><span class="gt-arrow"></span><span class="gt-year-label gt-lbl">${_gesc(year)}</span></summary>`;

    months.forEach((month) => {
      const monthName = new Date(+year, parseInt(month) - 1).toLocaleString(locale, { month: 'long' });
      const monthLabel = monthName.charAt(0).toUpperCase() + monthName.slice(1);
      const days = Object.keys(tree[year][month]).sort().reverse();
      html += `<details class="gt-month" open><summary class="gt-node gt-month-node"><span class="gt-arrow"></span><span class="gt-lbl">${_gesc(monthLabel)}</span></summary>`;

      days.forEach(day => {
        const d = new Date(+year, parseInt(month) - 1, +day);
        const dayLabel = d.toLocaleString(locale, { day: 'numeric', month: 'long' });
        const records = Object.keys(tree[year][month][day]);
        html += `<details class="gt-day"><summary class="gt-node gt-day-node"><span class="gt-arrow"></span><span class="gt-lbl">${_gesc(dayLabel)}</span></summary>`;

        records.forEach(recId => {
          const rec = tree[year][month][day][recId];
          html += `<details class="gt-record"><summary class="gt-node gt-record-node"><span class="gt-arrow"></span><div class="gt-record-info"><div class="gt-record-title">${_gesc(rec.title)}</div>${rec.meta ? `<div class="gt-record-meta">${_gesc(rec.meta)}</div>` : ''}</div></summary>`;
          rec.files.forEach(({ item, idx }) => {
            html += `<div class="gt-file" onclick="openGalleryPreview(${idx})"><span class="gt-file-icon">${fileIcon(item.file_name)}</span><span class="gt-file-name">${_gesc(item.file_name)}</span></div>`;
          });
          html += '</details>';
        });

        html += '</details>';
      });

      html += '</details>';
    });

    html += '</details>';
  });

  html += '</div>';
  grid.innerHTML = html;
}

function fileIcon(name) {
  const ext = (name || '').split('.').pop().toLowerCase();
  if (['jpg','jpeg','png','gif','webp','svg'].includes(ext)) return '🖼️';
  if (ext === 'pdf') return '📄';
  if (ext === 'heic') return '📷';
  if (['xlsx','xls','csv'].includes(ext)) return '📊';
  if (['docx','doc'].includes(ext)) return '📝';
  return '📎';
}

function openGalleryPreview(idx) {
  const item = _galleryItems[idx];
  if (!item) return;

  const modal   = document.getElementById('gallery-modal');
  const content = document.getElementById('gallery-preview-content');
  const meta    = document.getElementById('gallery-preview-meta');

  const isPdf   = /pdf/i.test(item.file_type || '') || /\.pdf$/i.test(item.file_name);
  const isImage = /^image\//i.test(item.file_type || '') && !/heic/i.test(item.file_type || '');
  const isHeic  = /heic/i.test(item.file_type || '') || /\.heic$/i.test(item.file_name);

  if (isPdf || isHeic || (!isImage && item.source !== 'unprocessed')) {
    const url = item.file_path ? `/attachments/${item.id}/file` : null;
    if (url) { window.open(url, '_blank'); return; }
    if (item.drive_id) { window.open(`https://drive.google.com/file/d/${item.drive_id}/view`, '_blank'); return; }
    return;
  }

  if (item.source === 'unprocessed') {
    content.innerHTML = `<div class="gallery-preview-placeholder"><div class="icon">📂</div><div>${t('gallery.unprocessed_badge')}</div></div>`;
  } else if (isImage && item.file_path) {
    content.innerHTML = `<img src="/attachments/${item.id}/file" alt="${item.file_name}">`;
  } else {
    content.innerHTML = `<div class="gallery-preview-placeholder"><div class="icon">${fileIcon(item.file_name)}</div></div>`;
  }

  const details = [item.record_date, item.company_name, item.card_name].filter(Boolean).join(' · ');
  meta.innerHTML = `
    <div class="meta-name">${item.file_name}</div>
    ${details ? `<div class="meta-detail">${details}</div>` : ''}
    <div class="meta-detail">${item.created_at ? item.created_at.slice(0,10) : ''}</div>
  `;

  modal.classList.add('open');
}

function closeGalleryModal() {
  document.getElementById('gallery-modal').classList.remove('open');
}

let _unprocessedItems = [];
let _currentImportId = null;

async function loadUnprocessed() {
  if(!DRIVE_ENABLED) return;
  try {
    const res = await fetch('/unprocessed', { credentials: 'include' });
    _unprocessedItems = await res.json();
    renderUnprocessed(_unprocessedItems);
    updateUnprocessedBadge();
  } catch { }
}

function updateUnprocessedBadge() {
  const badge = document.getElementById('unprocessed-count');
  if (!badge) return;
  const count = _unprocessedItems.length;
  badge.textContent = count;
  badge.style.display = count > 0 ? '' : 'none';
}

function _unprocessedItemHtml(item) {
  const ext = (item.file_name.split('.').pop() || '').toLowerCase();
  const icon = ['jpg','jpeg','png','gif','webp'].includes(ext) ? '🖼️'
              : ext === 'pdf' ? '📄'
              : ['doc','docx'].includes(ext) ? '📝' : '📎';
  const date   = item.synced_at ? item.synced_at.slice(0, 10) : '';
  const folder = item.drive_folder || '';
  const pathHtml = folder
    ? `<div class="unprocessed-item-path">📁 ${folder}</div>`
    : '';
  return `<div class="unprocessed-item" onclick="openAssignModal('${item.id}','${item.file_name.replace(/'/g,"\\'")}')">
    <div class="unprocessed-item-icon">${icon}</div>
    <div class="unprocessed-item-info">
      <div class="unprocessed-item-name">${item.file_name}</div>
      ${pathHtml}
    </div>
    <div class="unprocessed-item-date">${date}</div>
  </div>`;
}

function renderUnprocessed(items) {
  const list = document.getElementById('unprocessed-list');
  const empty = document.getElementById('unprocessed-empty');
  if (!list) return;
  if (!items.length) {
    list.innerHTML = '';
    if (empty) empty.style.display = '';
    return;
  }
  if (empty) empty.style.display = 'none';

  const fromFolder = items.filter(i => i.drive_folder === 'Unprocessed Imports');
  const others     = items.filter(i => i.drive_folder !== 'Unprocessed Imports');

  let html = '';
  if (fromFolder.length) {
    html += `<div class="unprocessed-group-title" data-i18n="unprocessed.from_folder">${t('unprocessed.from_folder')}</div>`;
    html += fromFolder.map(_unprocessedItemHtml).join('');
  }
  if (others.length) {
    html += `<div class="unprocessed-group-title" data-i18n="unprocessed.from_other">${t('unprocessed.from_other')}</div>`;
    html += others.map(_unprocessedItemHtml).join('');
  }
  list.innerHTML = html;
}

function openAssignModal(impId, fileName) {
  _currentImportId = impId;
  document.getElementById('assign-file-name').textContent = fileName;
  document.getElementById('assign-search').value = '';
  renderAssignRecords(sampleDocs || []);
  document.getElementById('assign-modal').classList.add('open');
}

function closeAssignModal() {
  document.getElementById('assign-modal').classList.remove('open');
  _currentImportId = null;
}

function filterAssignRecords(query) {
  const all = sampleDocs || [];
  const q = query.toLowerCase();
  const filtered = q ? all.filter(r =>
    r.title.toLowerCase().includes(q) ||
    (r.company_name || '').toLowerCase().includes(q)
  ) : all;
  renderAssignRecords(filtered);
}

function renderAssignRecords(records) {
  const el = document.getElementById('assign-records-list');
  if (!el) return;
  const sorted = [...records].filter(r => !r.is_deleted && !r.is_archived)
    .sort((a,b) => b.date.localeCompare(a.date));
  el.innerHTML = sorted.map(r => `
    <div class="assign-record-item" onclick="assignToRecord('${r.id}')">
      <div class="assign-record-title">${r.title}</div>
      <div class="assign-record-meta">${r.date}${r.company_name ? ' · ' + r.company_name : ''} · ${r.amount} ${r.currency}</div>
    </div>
  `).join('');
}

async function assignToRecord(recordId) {
  if (!_currentImportId) return;
  const impId = _currentImportId;
  closeAssignModal();
  setBusy(true, 'busy.assigning');
  try {
    const res = await fetch(`/unprocessed/${impId}/assign`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ record_id: recordId })
    });
    const data = await res.json();
    if (data.ok) {
      _unprocessedItems = _unprocessedItems.filter(i => i.id !== impId);
      showToast(t(data.drive_ok === false ? 'toast.assign_no_drive' : 'toast.unprocessed_assigned'), data.drive_ok === false ? 'warning' : 'success');
      const records = await loadRecords();
      sampleDocs.length = 0;
      records.forEach(r => sampleDocs.push(r));
      filteredDocs = sampleDocs.filter(d => !d.isArchived && !d.isDeleted);
      renderDocs();
      loadUnprocessed();
    } else {
      showToast(t('toast.error'), 'error');
    }
  } catch(e) { showToast(_errMsg(e), 'error'); }
  finally { setBusy(false); }
}

async function createNewRecordFromImport() {
  if (!_currentImportId) return;
  const impId = _currentImportId;
  const imp = _unprocessedItems.find(i => i.id === impId);
  if (!imp) return;
  closeAssignModal();
  setBusy(true, 'busy.assigning');
  try {
    const res = await fetch(`/unprocessed/${impId}/new-record`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: imp.file_name.replace(/\.[^.]+$/, '') })
    });
    const data = await res.json();
    if (data.ok) {
      _unprocessedItems = _unprocessedItems.filter(i => i.id !== impId);
      showToast(t(data.drive_ok === false ? 'toast.assign_no_drive' : 'toast.unprocessed_created'), data.drive_ok === false ? 'warning' : 'success');
      const records = await loadRecords();
      sampleDocs.length = 0;
      records.forEach(r => sampleDocs.push(r));
      filteredDocs = sampleDocs.filter(d => !d.isArchived && !d.isDeleted);
      renderDocs();
      loadUnprocessed();
    } else {
      showToast(t('toast.error'), 'error');
    }
  } catch(e) { showToast(_errMsg(e), 'error'); }
  finally { setBusy(false); }
}

// ══════════════════════════════════════════
// STORAGE INFO
// ══════════════════════════════════════════
function _formatBytes(bytes) {
  if(bytes === 0) return '0 B';
  if(bytes < 1024) return bytes + ' B';
  if(bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  if(bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
  return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
}

async function loadBackupList() {
  if(!DRIVE_ENABLED) return;
  const btn  = document.getElementById('backup-list-btn');
  const list = document.getElementById('backup-drive-list');
  if(btn) { btn.disabled = true; btn.textContent = t('loading.text'); }
  try {
    const res  = await fetch('/backup/list', { credentials: 'include' });
    const data = await res.json();
    if(!res.ok || !data.ok) {
      showToast(t(data.message === 'no_drive_token' ? 'toast.sync_no_drive' : 'toast.error'), 'error');
      return;
    }
    list.style.display = 'flex';
    if(!data.files.length) {
      list.innerHTML = `<div style="font-size:12px;color:var(--text3)">${t('settings.restore_drive_empty')}</div>`;
      return;
    }
    list.innerHTML = data.files.map(f => {
      const date = f.modifiedTime ? f.modifiedTime.slice(0, 10) : '';
      const size = f.size ? Math.round(f.size / 1024) + ' KB' : '';
      return `<div style="display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 10px;background:var(--bg3);border-radius:var(--radius-sm);border:1px solid var(--border)">
        <div>
          <div style="font-size:12px;font-weight:500;color:var(--text1)">${f.name}</div>
          <div style="font-size:11px;color:var(--text3)">${date}${size ? ' · ' + size : ''}</div>
        </div>
        <button class="btn btn-danger" style="font-size:12px;padding:4px 10px" onclick="restoreFromDrive('${f.id}','${f.name}')">${t('settings.restore_btn_short')}</button>
      </div>`;
    }).join('');
  } catch {
    showToast(t('toast.error'), 'error');
  } finally {
    if(btn) { btn.disabled = false; btn.textContent = t('settings.restore_drive_btn'); }
  }
}

async function restoreFromDrive(driveId, name) {
  if(!DRIVE_ENABLED) return;
  if(!confirm(t('settings.restore_confirm').replace('{f}', name))) return;
  setBusy(true, 'loading.text');
  try {
    const res  = await fetch('/backup/restore-from-drive', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ drive_id: driveId }),
    });
    const data = await res.json();
    if(!res.ok || !data.ok) { showToast(t('toast.error'), 'error'); return; }
    showToast(t('settings.restore_done'), 'success');
    setTimeout(() => location.reload(), 1500);
  } catch {
    showToast(t('toast.error'), 'error');
  } finally {
    setBusy(false);
  }
}

async function restoreBackup(input) {
  const file = input.files[0];
  if(!file) return;
  input.value = '';
  if(!confirm(t('settings.restore_confirm'))) return;
  const status = document.getElementById('restore-status');
  if(status) status.textContent = t('loading.text');
  const form = new FormData();
  form.append('file', file);
  try {
    const res  = await fetch('/backup/restore', { method: 'POST', credentials: 'include', body: form });
    const data = await res.json();
    if(!res.ok || !data.ok) {
      showToast(t('toast.error'), 'error');
      if(status) status.textContent = '';
      return;
    }
    showToast(t('settings.restore_done'), 'success');
    if(status) status.textContent = '';
    setTimeout(() => location.reload(), 1500);
  } catch {
    showToast(t('toast.error'), 'error');
    if(status) status.textContent = '';
  }
}

async function downloadBackupPC() {
  const res  = await fetch('/backup/download', { credentials: 'include' });
  if(!res.ok) { showToast(t('toast.error'), 'error'); return; }
  const blob = await res.blob();
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = `backup_${new Date().toISOString().slice(0,10)}.zip`;
  a.click();
  URL.revokeObjectURL(url);
}

async function downloadBackup() {
  const btn = document.getElementById('backup-btn');
  if(btn) { btn.disabled = true; btn.textContent = t('loading.text'); }
  try {
    const res  = await fetch('/backup', { method: 'POST', credentials: 'include' });
    const data = await res.json();
    if(!res.ok || !data.ok) {
      showToast(t(data.message === 'no_drive_token' ? 'toast.sync_no_drive' : 'toast.error'), 'error');
      return;
    }
    showToast(t('settings.backup_done').replace('{f}', data.filename), 'success');
  } catch {
    showToast(t('toast.error'), 'error');
  } finally {
    if(btn) { btn.disabled = false; btn.textContent = t('settings.backup_btn'); }
  }
}

async function loadStorageInfo() {
  const container = document.getElementById('storage-info-content');
  container.innerHTML = `<div style="text-align:center;padding:20px;color:var(--text3);font-size:13px">${t('loading.text')}</div>`;
  try {
    const resp = await fetch('/storage-info', { credentials: 'include' });
    if(!resp.ok) throw new Error();
    const d = await resp.json();
    container.innerHTML = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
        <div style="grid-column:1/-1;background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius);padding:18px 20px;display:flex;align-items:center;gap:16px">
          <div style="font-size:28px">💾</div>
          <div>
            <div style="font-size:11px;color:var(--text3);font-weight:600;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:2px">${t('storage.total')}</div>
            <div style="font-size:24px;font-weight:600;color:var(--text1)">${_formatBytes(d.total_size)}</div>
          </div>
        </div>
        <div style="background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px">
          <div style="font-size:11px;color:var(--text3);font-weight:600;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px">${t('storage.files')}</div>
          <div style="font-size:20px;font-weight:600;color:var(--text1)">${_formatBytes(d.uploads_size)}</div>
          <div style="font-size:12px;color:var(--text3);margin-top:4px">${d.file_count} ${t('storage.files_unit')}</div>
        </div>
        <div style="background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px">
          <div style="font-size:11px;color:var(--text3);font-weight:600;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px">${t('storage.db')}</div>
          <div style="font-size:20px;font-weight:600;color:var(--text1)">${_formatBytes(d.db_size)}</div>
          <div style="font-size:12px;color:var(--text3);margin-top:4px">${t('storage.db_hint')}</div>
        </div>
      </div>
    `;
  } catch(e) {
    container.innerHTML = `<div style="text-align:center;padding:20px;color:var(--red);font-size:13px">${t('toast.error')}</div>`;
  }
}

async function checkRecordsStats() {
  const overlay = document.getElementById('stats-overlay');
  const body = document.getElementById('stats-modal-body');

  setBusy(true, 'busy.uploading');
  try {
    const resp = await fetch('/records-stats', { credentials: 'include' });
    const data = await resp.json();
    setBusy(false);
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
    const r = data.records;
    const a = data.attachments;
    body.innerHTML = `
      <div>
        <div class="stats-section-title">Записи</div>
        <div class="stats-row"><span class="stats-row-label">Всього</span><span class="stats-row-value">${r.total}</span></div>
        <div class="stats-row"><span class="stats-row-label">Активних</span><span class="stats-row-value">${r.active}</span></div>
        <div class="stats-row"><span class="stats-row-label">Архів</span><span class="stats-row-value">${r.archived}</span></div>
        <div class="stats-row"><span class="stats-row-label">Корзина</span><span class="stats-row-value">${r.deleted}</span></div>
      </div>
      <div>
        <div class="stats-section-title">Чеки</div>
        <div class="stats-row"><span class="stats-row-label">БД</span><span class="stats-row-value">${a.total}</span></div>
        <div class="stats-row"><span class="stats-row-label">Локально</span><span class="stats-row-value">${a.local}</span></div>
        <div class="stats-row"><span class="stats-row-label">Drive</span><span class="stats-row-value">${a.drive !== null && a.drive !== undefined ? a.drive : (a.drive_error || '?')}</span></div>
        ${a.unprocessed ? `<div class="stats-row"><span class="stats-row-label">Необроблені</span><span class="stats-row-value">${a.unprocessed}</span></div>` : ''}
      </div>
    `;
  } catch(e) {
    setBusy(false);
    body.innerHTML = '<div style="text-align:center;padding:24px;color:var(--red)">Помилка завантаження</div>';
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
  }
}

function closeStatsModal() {
  document.getElementById('stats-overlay').classList.remove('open');
  document.body.style.overflow = '';
}

async function runVerifyDrive() {
  if(!DRIVE_ENABLED) return;
  const btn = document.getElementById('verify-drive-btn');
  if(btn) { btn.disabled = true; btn.textContent = 'Перевірка...'; }
  try {
    const res = await fetch('/sync/verify-drive', { method: 'POST', credentials: 'include' });
    const d = await res.json();
    if(!d.ok) { showToast(d.message || 'Помилка', 'error'); return; }
    if(d.fixed > 0) showToast(`Виправлено ${d.fixed} файл(ів) — тепер синхронізуйте`, 'success');
    else showToast('Розбіжностей не знайдено', 'success');
  } catch(e) {
    showToast('Помилка', 'error');
  } finally {
    if(btn) { btn.disabled = false; btn.textContent = '🔍 Перевірити Drive і виправити розбіжності'; }
  }
}

async function runStorageCleanup() {
  const btn = document.getElementById('cleanup-btn');
  if(btn) { btn.disabled = true; btn.textContent = t('btn.saving'); }
  try {
    const resp = await fetch('/storage-cleanup', { method: 'POST', credentials: 'include' });
    if(!resp.ok) throw new Error();
    const d = await resp.json();
    const msg = t('storage.cleanup_done')
      .replace('{f}', d.deleted_files)
      .replace('{d}', d.deleted_folders);
    showToast(msg, 'success');
    loadStorageInfo();
  } catch(e) {
    showToast(t('toast.error'), 'error');
  } finally {
    if(btn) { btn.disabled = false; btn.textContent = t('storage.cleanup_btn'); }
  }
}

// ══════════════════════════════════════════
// DRIVE PICKER
// ══════════════════════════════════════════
let _drivePickerContext = null;
let _drivePickerTimer   = null;

function openDrivePicker(context) {
  if(!DRIVE_ENABLED) return;
  _drivePickerContext = context;
  document.getElementById('drive-picker-search').value = '';
  document.getElementById('drive-picker-overlay').classList.add('open');
  _loadDriveFiles('');
}

function closeDrivePicker() {
  document.getElementById('drive-picker-overlay').classList.remove('open');
  _drivePickerContext = null;
}

function onDrivePickerSearch(val) {
  clearTimeout(_drivePickerTimer);
  _drivePickerTimer = setTimeout(() => _loadDriveFiles(val.trim()), 400);
}

async function _loadDriveFiles(query) {
  const list = document.getElementById('drive-picker-list');
  list.innerHTML = `<div style="text-align:center;padding:24px;color:var(--text3);font-size:13px">${t('drive.loading')}</div>`;
  try {
    const url = query ? `/drive/files?q=${encodeURIComponent(query)}` : '/drive/files';
    const resp = await fetch(url, { credentials: 'include' });
    if(!resp.ok) {
      list.innerHTML = `<div style="text-align:center;padding:24px;color:var(--text3);font-size:13px">${t('drive.no_drive')}</div>`;
      return;
    }
    const files = await resp.json();
    if(!files.length) {
      list.innerHTML = `<div style="text-align:center;padding:24px;color:var(--text3);font-size:13px">${t('drive.empty')}</div>`;
      return;
    }
    list.innerHTML = files.map(f => {
      const icon = f.mimeType && f.mimeType.includes('pdf') ? '📄' :
                   f.mimeType && f.mimeType.startsWith('image/') ? '🖼️' : '📎';
      const name = f.name || '';
      const shortName = name.length > 48 ? name.substring(0, 46) + '…' : name;
      const safeId   = f.id.replace(/'/g, '');
      const safeMime = (f.mimeType || '').replace(/'/g, '');
      const safeName = name.replace(/\\/g, '\\\\').replace(/`/g, '\\`').replace(/\$/g, '\\$');
      return `<div onclick="selectDriveFile('${safeId}',\`${safeName}\`,'${safeMime}')"
                style="display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:var(--radius-sm);cursor:pointer;transition:background 0.12s"
                onmouseover="this.style.background='var(--bg3)'"
                onmouseout="this.style.background=''">
        <span style="font-size:16px;flex-shrink:0">${icon}</span>
        <span style="font-size:13px;color:var(--text1);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${shortName}</span>
      </div>`;
    }).join('');
  } catch(e) {
    list.innerHTML = `<div style="text-align:center;padding:24px;color:var(--red);font-size:13px">${t('toast.error')}</div>`;
  }
}

async function selectDriveFile(driveId, fileName, mimeType) {
  const ctx = _drivePickerContext;
  closeDrivePicker();

  if(ctx === 'form') {
    pendingDriveFiles.push({ drive_id: driveId, file_name: fileName, mime_type: mimeType });
    renderFilesPreview();
    return;
  }

  // context is a record_id — attach directly
  setBusy(true, 'busy.drive_download');
  try {
    const resp = await fetch(`/records/${ctx}/attach-from-drive`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ drive_id: driveId, file_name: fileName, mime_type: mimeType }),
    });
    if(!resp.ok) throw new Error();
    const att  = await resp.json();
    const doc  = sampleDocs.find(d => d.id === ctx) || archivedDocs.find(d => d.id === ctx);
    if(doc) {
      if(!doc.attachments) doc.attachments = [];
      doc.attachments.push({ id: att.id, name: att.file_name, type: att.file_type, storageType: att.storage_type });
      doc.files = doc.attachments.length;
      renderAttachments(doc);
      renderDocs();
    }
    showToast(t('toast.drive_attached'), 'success');
  } catch(e) {
    showToast(t('toast.drive_error'), 'error');
  } finally {
    setBusy(false);
  }
}
