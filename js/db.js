// ══════════════════════════════════════════
// DB — LOCAL API (Flask + SQLite)
// ══════════════════════════════════════════
const API_URL = '';

async function apiGet(path) {
  const token = localStorage.getItem('auth_token');
  const res = await fetch(API_URL + path, {
    headers: { 'Authorization': 'Bearer ' + token }
  });
  if(!res.ok) {
    const err = new Error(await res.text());
    err.status = res.status;
    throw err;
  }
  return res.json();
}

async function apiPost(path, body) {
  const token = localStorage.getItem('auth_token');
  const res = await fetch(API_URL + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
    body: JSON.stringify(body)
  });
  if(!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    const e = new Error(err.error || res.statusText);
    e.data = err;
    throw e;
  }
  return res.json();
}

async function apiPut(path, body) {
  const token = localStorage.getItem('auth_token');
  const res = await fetch(API_URL + path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
    body: JSON.stringify(body)
  });
  if(!res.ok) throw new Error(await res.text());
  return res.json();
}

async function apiDelete(path) {
  const token = localStorage.getItem('auth_token');
  const res = await fetch(API_URL + path, {
    method: 'DELETE',
    headers: { 'Authorization': 'Bearer ' + token }
  });
  if(!res.ok) throw new Error(await res.text());
  return res.json();
}

// ── AUTH ──
async function authLogin(email, password) {
  const data = await apiPost('/auth/login', { email, password });
  localStorage.setItem('auth_token', data.token);
  return data.user;
}

async function authRegister(email, password, fullName) {
  const data = await apiPost('/auth/register', { email, password, full_name: fullName });
  localStorage.setItem('auth_token', data.token);
  return data.user;
}

async function authGetCurrentUser() {
  const token = localStorage.getItem('auth_token');
  if(!token) return null;
  try { return await apiGet('/auth/me'); }
  catch(e) { localStorage.removeItem('auth_token'); return null; }
}

function authSignOut() {
  localStorage.removeItem('auth_token');
}

// ── COMPANIES ──
async function loadCompanies() { return await apiGet('/companies'); }

async function saveCompany(name, isShared = false) {
  return await apiPost('/companies', { name, is_shared: isShared });
}

async function updateCompanyDB(id, data) { return await apiPut('/companies/' + id, data); }
async function loadDeletedCompanies() { return await apiGet('/companies/trash'); }
async function restoreCompanyDB(id) { return await apiPost('/companies/' + id + '/restore', {}); }
async function permanentDeleteCompanyDB(id) { return await apiDelete('/companies/' + id + '/permanent'); }

// ── INSTRUMENTS ──
async function loadInstruments() { return await apiGet('/instruments'); }

async function saveInstrumentAPI(name, type) {
  return await apiPost('/instruments', { name, type });
}

async function updateInstrumentDB(id, data) { return await apiPut('/instruments/' + id, data); }
async function loadDeletedInstruments() { return await apiGet('/instruments/trash'); }
async function restoreInstrumentDB(id) { return await apiPost('/instruments/' + id + '/restore', {}); }
async function permanentDeleteInstrumentDB(id) { return await apiDelete('/instruments/' + id + '/permanent'); }

// ── RECORDS ──
const CURRENCY_SYMBOLS = { EUR: '€', UAH: '₴', USD: '$' };

function mapRecord(r) {
  return {
    id: r.id,
    date: r.date,
    created: (r.created_at || '').split('T')[0] || '',
    title: r.title,
    note: r.note || '',
    company: r.company_name || '—',
    companyId: r.company_id,
    amount: parseFloat(r.amount) || 0,
    currency: CURRENCY_SYMBOLS[r.currency] || '€',
    currencyCode: r.currency || 'EUR',
    payType: r.pay_type,
    payMethod: r.pay_method,
    card: r.card_name || '',
    cardId: r.card_id,
    status: r.status,
    toReturn: parseFloat(r.to_return) || 0,
    returned: parseFloat(r.returned) || 0,
    remainder: parseFloat(r.remainder) || 0,
    files: (r.attachments || []).length,
    attachments: (r.attachments || []).map(a => ({
      id: a.id,
      name: a.file_name,
      type: a.file_type || '',
      storageType: a.storage_type || 'local'
    })),
    returnEvents: (r.return_events || []).map(e => ({
      id: e.id, amount: parseFloat(e.amount), date: e.date, method: e.method || ''
    })),
    isArchived: !!r.is_archived,
    isDeleted: !!r.is_deleted,
    previousStatus: r.previous_status || null,
  };
}

async function loadRecords() {
  const data = await apiGet('/records');
  return data.map(mapRecord);
}

async function loadArchivedRecords() {
  const data = await apiGet('/records?archived=1');
  return data.filter(r => r.is_archived).map(mapRecord);
}

async function loadDeletedRecords() {
  const data = await apiGet('/records?deleted=1');
  return data.filter(r => r.is_deleted).map(mapRecord);
}

async function createRecord(data) {
  const rec = await apiPost('/records', {
    title: data.title, note: data.note || '', date: data.date,
    amount: data.amount,
    pay_type: data.payType, pay_method: data.payMethod,
    card_id: data.cardId || null, company_id: data.companyId || null,
    status: data.status,
    to_return: data.toReturn || 0, returned: data.returned || 0, remainder: data.remainder || 0,
  });
  return mapRecord(rec);
}

async function updateRecord(id, data) {
  await apiPut('/records/' + id, {
    title: data.title, note: data.note || '', date: data.date,
    amount: data.amount, pay_type: data.payType, pay_method: data.payMethod,
    card_id: data.cardId || null, company_id: data.companyId || null,
    status: data.status,
    to_return: data.toReturn || 0, returned: data.returned || 0, remainder: data.remainder || 0,
    is_archived: data.is_archived ?? 0,
  });
}

async function archiveRecordDB(id, previousStatus) {
  await apiPut('/records/' + id, { is_archived: 1, status: 'archived', previous_status: previousStatus });
}

async function deleteRecordDB(id) {
  await apiPut('/records/' + id, { is_deleted: 1, deleted_at: new Date().toISOString() });
}

async function restoreRecordDB(id) {
  await apiPut('/records/' + id, { is_deleted: 0, deleted_at: null });
}

async function permanentDeleteDB(id) {
  await apiDelete('/records/' + id);
}

// ── RETURN EVENTS ──
async function addReturnEvent(recordId, amount, date, method) {
  const event = await apiPost('/records/' + recordId + '/returns', {
    amount, date, method: method || null
  });
  const doc = sampleDocs.find(d => d.id === recordId);
  if(doc) {
    if(!doc.returnEvents) doc.returnEvents = [];
    doc.returnEvents.push({ id: event.id, amount, date, method: method || '' });
    doc.returned = doc.returnEvents.reduce((s, e) => s + e.amount, 0);
    doc.remainder = Math.max(0, doc.amount - doc.returned);
    doc.status = doc.returned <= 0 ? 'waiting' : doc.returned < doc.amount ? 'partial' : 'done';
  }
  return event;
}

// ── ATTACHMENTS ──
async function uploadAttachment(recordId, file) {
  const token = localStorage.getItem('auth_token');
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(API_URL + '/attachments/' + recordId, {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + token },
    body: formData
  });
  if(!res.ok) throw new Error(await res.text());
  return res.json();
}

async function deleteAttachmentDB(id) {
  return await apiDelete('/attachments/' + id);
}

async function deleteReturnEventDB(eventId, recordId) {
  await apiDelete('/returns/' + eventId);
  const doc = sampleDocs.find(d => d.id === recordId);
  if(doc) {
    doc.returnEvents = (doc.returnEvents || []).filter(e => e.id !== eventId);
    doc.returned = doc.returnEvents.reduce((s, e) => s + e.amount, 0);
    doc.remainder = Math.max(0, doc.amount - doc.returned);
    doc.status = doc.returned <= 0 ? 'waiting' : doc.returned < doc.amount ? 'partial' : 'done';
  }
}
