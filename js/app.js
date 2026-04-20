// ══════════════════════════════════════════
// INIT APP
// ══════════════════════════════════════════
async function initApp(user) {
  currentUser = user;

  // Update sidebar
  const email = user.email || '';
  const sidebarEmail = document.getElementById('sidebar-email');
  const sidebarAvatar = document.getElementById('sidebar-avatar');
  if(sidebarEmail) sidebarEmail.textContent = email;
  if(sidebarAvatar) sidebarAvatar.textContent = email[0].toUpperCase();

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
    showApp();
  } catch(e) {
    console.error('initApp error', e);
    showApp();
    showToast(t('toast.load_error'), 'error');
  }
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
  if(statEls[4]) statEls[4].textContent = 0; // Google Drive — майбутнє

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

let currentView = 'table';
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

  if(name === 'documents') renderDocs();
  if(name === 'trash') loadAndRenderTrash();
  if(name === 'settings') loadAndRenderInstruments();
  if(name === 'inbox' || name === 'unprocessed') applyTranslations();
}

// ── INIT ──
document.addEventListener('DOMContentLoaded', async () => {
  const dateEl = document.getElementById('field-date');
  if(dateEl) dateEl.value = new Date().toISOString().split('T')[0];
  loadSavedTheme();
  loadSavedLang();

  const user = await authGetCurrentUser();
  if(user) {
    document.getElementById('page-dashboard').style.display = '';
    document.getElementById('page-dashboard').classList.add('active');
    await initApp(user);
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
  if(name === 'payments') loadAndRenderInstruments();
  if(name === 'companies') loadAndRenderCompanies();
}

// ── MODAL ──
let editingId = null;
let pendingFiles = [];

function openModal() {
  editingId = null;
  resetModalForm();
  document.getElementById('modal-title').textContent = t('form.new_record');
  document.getElementById('modal-save-btn').textContent = t('btn.save_record');
  document.getElementById('modal-edit-badge').style.display = 'none';
  document.getElementById('modal-overlay').classList.add('open');
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
  document.getElementById('files-preview').innerHTML = '';
  renderExistingAttachments(doc);
  document.getElementById('modal-overlay').classList.add('open');
}

function closeModal() {
  document.getElementById('modal-overlay').classList.remove('open');
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
  preview.innerHTML = pendingFiles.map((f, i) => `
    <div style="background:var(--bg4);border:1px solid var(--border);border-radius:6px;padding:4px 10px;font-size:12px;color:var(--text2);display:flex;align-items:center;gap:6px;">
      ${f.type.includes('pdf') ? '📄' : '🖼️'} ${f.name.substring(0,20)}${f.name.length>20?'...':''}
      <span style="cursor:pointer;color:var(--text3)" onclick="removePendingFile(${i})">✕</span>
    </div>
  `).join('');
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

      if(pendingFiles.length > 0) {
        const doc = sampleDocs.find(d => d.id === editingId) || archivedDocs.find(d => d.id === editingId);
        for(const file of pendingFiles) {
          const att = await uploadAttachment(editingId, file);
          if(doc) {
            if(!doc.attachments) doc.attachments = [];
            doc.attachments.push({ id: att.id, name: att.file_name, type: att.file_type, storageType: 'local' });
            doc.files = doc.attachments.length;
          }
        }
        pendingFiles = [];
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
        for(const file of pendingFiles) {
          const att = await uploadAttachment(newDoc.id, file);
          newDoc.attachments.push({ id: att.id, name: att.file_name, type: att.file_type, storageType: 'local' });
          newDoc.files = newDoc.attachments.length;
        }
        pendingFiles = [];
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
    showToast(t('toast.save_error') + ': ' + e.message, 'error');
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
}

function renderArchiveTable() {
  const tbody = document.getElementById('archive-table-body');
  if(!tbody) return;
  tbody.innerHTML = filteredArchived.map(d => `
    <tr onclick="openDetail('${d.id}')" style="opacity:0.7">
      <td class="td-date">${formatDate(d.date)}</td>
      <td><strong style="font-weight:500">${d.title}</strong></td>
      <td style="color:var(--text2)">${d.company}</td>
      <td class="td-amount">${d.currency}${d.amount.toFixed(2)}</td>
      <td><span style="font-size:12px;color:var(--text2)">${d.payType === 'private' ? t('detail.private') : t('detail.company_pay')}</span></td>
      <td>${statusBadge(d.status)}</td>
      <td class="td-remainder">${d.remainder > 0 ? d.currency + d.remainder.toFixed(2) : '<span style="color:var(--text3)">—</span>'}</td>
      <td class="attachment-icon ${d.files > 0 ? 'has' : ''}">${d.files > 0 ? '📎' + (d.files > 1 ? d.files : '') : '—'}</td>
      <td onclick="event.stopPropagation()">
        <div style="display:flex;gap:4px;align-items:center">
          <button class="btn btn-ghost" style="font-size:11px;padding:3px 8px" title="${t('archive.restore')}" onclick="unarchiveRecord('${d.id}')">↩</button>
          <button class="icon-btn danger" title="${t('btn.to_trash')}" onclick="deleteFromArchive('${d.id}')">🗑️</button>
        </div>
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
          <button class="btn btn-ghost" style="font-size:11px;padding:2px 6px" onclick="event.stopPropagation();unarchiveRecord('${d.id}')">↩</button>
          <button class="icon-btn danger" title="${t('btn.to_trash')}" onclick="event.stopPropagation();deleteFromArchive('${d.id}')" style="width:24px;height:24px;font-size:11px">🗑️</button>
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
      <td><strong style="font-weight:500">${d.title}</strong></td>
      <td style="color:var(--text2)">${d.company}</td>
      <td class="td-amount">${d.currency}${d.amount.toFixed(2)}</td>
      <td><span style="font-size:12px;color:var(--text2)">${d.payType === 'private' ? t('detail.private') : t('detail.company_pay')}</span></td>
      <td>${statusBadge(d.status)}</td>
      <td class="td-remainder">${d.remainder > 0 ? d.currency + d.remainder.toFixed(2) : '<span style="color:var(--text3)">—</span>'}</td>
      <td class="attachment-icon ${d.files > 0 ? 'has' : ''}">${d.files > 0 ? '📎' + (d.files > 1 ? d.files : '') : '—'}</td>
      <td onclick="event.stopPropagation()">
        <div style="display:flex;flex-direction:row;gap:4px;align-items:center">
          <button class="icon-btn" title="${t('detail.edit')}" onclick="openEditModal('${d.id}')" style="opacity:0.5" onmouseenter="this.style.opacity=1" onmouseleave="this.style.opacity=0.5">✏️</button>
          <button class="icon-btn" title="${t('detail.archive')}" onclick="archiveRecordById('${d.id}')" style="opacity:0.5" onmouseenter="this.style.opacity=1" onmouseleave="this.style.opacity=0.5">🗄️</button>
          <button class="icon-btn danger" title="${t('btn.to_trash')}" onclick="trashRecordById('${d.id}')">🗑️</button>
        </div>
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
          <button class="icon-btn" title="${t('detail.edit')}" onclick="event.stopPropagation();openEditModal('${d.id}')" style="width:24px;height:24px;font-size:11px">✏️</button>
          <button class="icon-btn" title="${t('detail.archive')}" onclick="event.stopPropagation();archiveRecordById('${d.id}')" style="width:24px;height:24px;font-size:11px">🗄️</button>
          <button class="icon-btn danger" title="${t('btn.to_trash')}" onclick="event.stopPropagation();trashRecordById('${d.id}')" style="width:24px;height:24px;font-size:11px">🗑️</button>
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
  currentView = type;
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

  renderDocs();
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

// ── SYNC ──
function syncNow() {
  showToast(t('toast.sync_unavailable'), 'error');
}

// ══════════════════════════════════════════
// EXPORT
// ══════════════════════════════════════════
function openExportModal() {
  document.getElementById('export-modal-overlay').classList.add('open');
  updateExportCount();
}

function closeExportModal() {
  document.getElementById('export-modal-overlay').classList.remove('open');
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
      <div class="detail-field-value" style="color:var(--text2)">${formatDate(doc.created)}</div>
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
    await deleteAttachmentDB(id);
    const doc = sampleDocs.find(d => d.id === currentDetailId) || archivedDocs.find(d => d.id === currentDetailId);
    if(doc) {
      doc.attachments = doc.attachments.filter(a => a.id !== id);
      doc.files = doc.attachments.length;
      renderAttachments(doc);
    }
    renderDocs();
    updateDashboard();
  } catch(e) {
    showToast(t('toast.file_delete_error'), 'error');
  }
}

async function addFilesToRecord(input) {
  const files = Array.from(input.files);
  if(!files.length) return;
  const doc = sampleDocs.find(d => d.id === currentDetailId) || archivedDocs.find(d => d.id === currentDetailId);
  if(!doc) return;
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
  }
  input.value = '';
}

function closeDetail() {
  document.getElementById('detail-overlay').classList.remove('open');
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
    showToast(t('toast.error') + ': ' + e.message, 'error');
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
    showToast(t('toast.error') + ': ' + e.message, 'error');
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
    showToast(t('toast.error') + ': ' + e.message, 'error');
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
    showToast(t('toast.error') + ': ' + e.message, 'error');
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
    showToast(t('toast.error') + ': ' + e.message, 'error');
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
    showToast(t('toast.error') + ': ' + e.message, 'error');
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
  } catch(e) { showToast(t('toast.error'), 'error'); }
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
  } catch(e) { showToast(t('toast.error'), 'error'); }
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
  } catch(e) { showToast(t('toast.error'), 'error'); }
}

async function permanentDelete(id) {
  try {
    await permanentDeleteDB(id);
    const idx = sampleDocs.findIndex(d => d.id === id);
    if(idx !== -1) sampleDocs.splice(idx, 1);
    showToast(t('toast.perm_deleted'), 'success');
    loadAndRenderTrash();
    updateBadges();
  } catch(e) { showToast(t('toast.error'), 'error'); }
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
    '--bg':'#f4f5f7','--bg2':'#ffffff','--bg3':'#ebeef2','--bg4':'#e2e5eb',
    '--border':'#d0d5de','--border2':'#b8bfcc',
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
  list.innerHTML = companiesCache.map(c => `
    <div class="settings-item ${!c.is_active ? 'deactivated' : ''}">
      <div class="settings-item-icon">🏢</div>
      <div class="settings-item-info">
        <div class="settings-item-name">${c.name}</div>
      </div>
      <div class="settings-item-actions">
        <button class="icon-btn" title="${t('detail.edit')}" onclick="openCompanyModal('${c.id}')">✏️</button>
        <button class="icon-btn" title="${c.is_active ? t('btn.deactivate') : t('btn.activate')}"
          onclick="toggleCompanyActive('${c.id}', ${c.is_active})">
          ${c.is_active ? '⏸' : '▶'}
        </button>
        <button class="icon-btn danger" title="${t('detail.delete')}" onclick="deleteCompany('${c.id}', '${c.name.replace(/'/g, "\\'")}')">🗑️</button>
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
  setTimeout(() => nameInput.focus(), 100);
}

function closeCompanyModal() {
  document.getElementById('company-modal-overlay').classList.remove('open');
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
    showToast(t('toast.error') + ': ' + e.message, 'error');
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
    showToast(t('toast.error') + ': ' + e.message, 'error');
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
  } catch(e) { showToast(t('toast.error'), 'error'); }
}

async function permanentDeleteCompany(id) {
  try {
    await permanentDeleteCompanyDB(id);
    showToast(t('toast.company_perm_deleted'), 'success');
    loadAndRenderTrash();
    updateBadges();
  } catch(e) { showToast(t('toast.error'), 'error'); }
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

  list.innerHTML = instrumentsCache.map(i => `
    <div class="settings-item ${!i.is_active ? 'deactivated' : ''}">
      <div class="settings-item-icon">${typeIcon[i.type] || '💳'}</div>
      <div class="settings-item-info">
        <div class="settings-item-name">${i.name}</div>
        <div class="settings-item-sub">
          <span class="type-chip ${typeClass[i.type] || ''}">${typeLabel[i.type] || i.type}</span>
        </div>
      </div>
      <div class="settings-item-actions">
        <button class="icon-btn" title="${t('detail.edit')}" onclick="openInstrumentModal('${i.id}')">✏️</button>
        <button class="icon-btn" title="${i.is_active ? t('btn.deactivate') : t('btn.activate')}"
          onclick="toggleInstrumentActive('${i.id}', ${i.is_active})">
          ${i.is_active ? '⏸' : '▶'}
        </button>
        <button class="icon-btn danger" title="${t('detail.delete')}" onclick="deleteInstrument('${i.id}', '${i.name.replace(/'/g, "\\'")}')">🗑️</button>
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
  setTimeout(() => nameInput.focus(), 100);
}

function closeInstrumentModal() {
  document.getElementById('instrument-modal-overlay').classList.remove('open');
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
    showToast(t('toast.error') + ': ' + e.message, 'error');
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
    showToast(t('toast.error') + ': ' + e.message, 'error');
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
  } catch(e) { showToast(t('toast.error'), 'error'); }
}

async function permanentDeleteInstrument(id) {
  try {
    await permanentDeleteInstrumentDB(id);
    showToast(t('toast.instrument_perm_deleted'), 'success');
    loadAndRenderTrash();
    updateBadges();
  } catch(e) { showToast(t('toast.error'), 'error'); }
}
