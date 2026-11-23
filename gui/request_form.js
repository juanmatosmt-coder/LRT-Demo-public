// Request form drafts for the local test suite. Builds the forms from data/templates/lab_request_forms.json,
// autosaves every change, and never submits anything.
//   Signed in: drafts are saved by the local server (gui/serve.py) under data/private/drafts/<user>/.
//   Guest:     drafts are saved in this browser (localStorage). A copy is also kept here when the server
//              cannot be reached, and pushed to the account the next time it can.
// Attached files are not stored: a draft keeps only their names and sizes.
'use strict';

const SCHEMA_URL = '../data/templates/lab_request_forms.json';
const PRIVATE_LISTS_URL = '../data/private/lab_request_forms_schema.json';   // real org lists, gitignored
const BRANDING_URL = '../data/private/branding/branding.json';               // logos, gitignored
const LS_DRAFTS = 'lrt.drafts.v1', LS_LAST = 'lrt.last.v1';

let S = null, BRAND = null, PARTS = [], USER = null, CAN_REGISTER = false, HAVE_API = false;
let formKey = 'lab_test_request', state = {}, draft = null, dirty = false, saveTimer = null;

// ---------- small helpers ----------
const $ = id => document.getElementById(id);
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v; else if (k === 'text') e.textContent = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v); else if (v !== undefined && v !== false) e.setAttribute(k, v);
  }
  kids.flat().forEach(c => c != null && e.append(c));
  return e;
};
const getJSON = async url => { try { const r = await fetch(url, { credentials: 'same-origin' }); return r.ok ? await r.json() : null; } catch (_) { return null; } };
const newId = () => (crypto.randomUUID ? crypto.randomUUID() : Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('')).replace(/-/g, '');
const nowIso = () => new Date().toISOString();
const when = t => { if (!t) return ''; const d = new Date(t); return isNaN(d) ? t : d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); };
const money = n => (isFinite(n) ? n : 0).toLocaleString(undefined, { style: 'currency', currency: 'USD' });
const num = v => { const n = parseFloat(v); return isFinite(n) ? n : 0; };

// ---------- schema helpers ----------
const expandFields = fields => (fields || []).flatMap(f => typeof f === 'string' && f.startsWith('@') ? S.common_steps[f.slice(1)] : [f]);
const tableOf = step => typeof step.table === 'string' ? S.common_steps[step.table.slice(1)] : step.table;
const optionsOf = f => Array.isArray(f.options) ? f.options : (S.shared_lists[f.options] || []);
const F = () => S.forms[formKey];
function titleOf() {
  const firstRow = Object.keys(state).filter(k => k.endsWith('_rows')).map(k => state[k]?.[0]).find(Boolean) || {};
  const t = state.projectJobName || state.projectNumber || (state.supplierName && `${state.supplierName}${state.project ? ' · ' + state.project : ''}`)
    || firstRow.productName || firstRow.partNumber || firstRow.description;
  return (t ? String(t) : 'Untitled').slice(0, 80);
}

// ---------- draft storage ----------
const lsAll = () => { try { return JSON.parse(localStorage.getItem(LS_DRAFTS)) || {}; } catch (_) { return {}; } };
const lsWrite = all => { try { localStorage.setItem(LS_DRAFTS, JSON.stringify(all)); return true; } catch (_) { return false; } };
const lsLast = v => { try { if (v === undefined) return JSON.parse(localStorage.getItem(LS_LAST)); localStorage.setItem(LS_LAST, JSON.stringify(v)); } catch (_) { return null; } };
const summary = d => ({ id: d.id, form: d.form, title: d.title, created: d.created, updated: d.updated, unsynced: d.unsynced });

const Store = {
  async list() {
    const local = Object.values(lsAll()).filter(d => (d.owner || null) === USER);
    if (!USER) return local.map(summary).sort((a, b) => (b.updated || '').localeCompare(a.updated || ''));
    const r = await fetch('/api/drafts', { credentials: 'same-origin' }).catch(() => null);
    const remote = r && r.ok ? await r.json() : [];
    const byId = Object.fromEntries(remote.map(d => [d.id, d]));
    local.filter(d => d.unsynced).forEach(d => { byId[d.id] = summary(d); });    // not yet on the server
    return Object.values(byId).sort((a, b) => (b.updated || '').localeCompare(a.updated || ''));
  },
  async get(id) {
    const local = lsAll()[id];
    if (!USER || local?.unsynced) return local && (local.owner || null) === USER ? local : null;
    return getJSON('/api/drafts/' + id);
  },
  async put(d) {
    if (!USER) {
      const all = lsAll(); d.updated = nowIso(); all[d.id] = { ...d, owner: null };
      if (!lsWrite(all)) throw new Error('This browser has no room left for drafts.');
      return { where: 'this browser', updated: d.updated };
    }
    const r = await fetch('/api/drafts/' + d.id, { method: 'PUT', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(d) });
    if (!r.ok) throw new Error('server ' + r.status);
    const all = lsAll(); if (all[d.id]) { delete all[d.id]; lsWrite(all); }       // server copy is now the good one
    return { where: 'your account', updated: (await r.json()).updated };
  },
  async del(id) {
    const all = lsAll(); if (all[id]) { delete all[id]; lsWrite(all); }
    if (USER) await fetch('/api/drafts/' + id, { method: 'DELETE', credentials: 'same-origin' }).catch(() => null);
  },
};

// Keep a local copy (marked unsynced) when the account cannot be reached, or when the page is closing.
function localBackup() {
  const all = lsAll();
  all[draft.id] = { ...currentDraft(), updated: nowIso(), owner: USER, unsynced: !!USER };
  return lsWrite(all);
}
async function pushUnsynced() {
  if (!USER) return;
  for (const d of Object.values(lsAll()).filter(d => d.unsynced && d.owner === USER)) {
    try { await Store.put({ ...d, unsynced: undefined }); } catch (_) { return; }
  }
}

// ---------- autosave ----------
// A draft with nothing typed in it is not worth keeping (tables start with one empty item).
const hasContent = v => Array.isArray(v) ? v.some(hasContent) : (v && typeof v === 'object') ? Object.entries(v).some(([k, x]) => k !== '_part' && hasContent(x)) : String(v ?? '').trim() !== '';
const currentDraft = () => ({ id: draft.id, form: formKey, title: titleOf(), created: draft.created, submitted: false, fields: state });
function setSave(text, cls = '') { const e = $('saveState'); e.textContent = text; e.className = 'save-state ' + cls; }
function markDirty() { dirty = true; setSave('Saving…'); clearTimeout(saveTimer); saveTimer = setTimeout(saveNow, 600); }
async function saveNow() {
  clearTimeout(saveTimer);
  if (!dirty || !draft) return;
  dirty = false;
  if (!hasContent(state) && !draft.saved) { setSave('New draft · saves as you type'); return; }
  draft.saved = true;
  try {
    const r = await Store.put(currentDraft());
    setSave(`Saved ${when(r.updated)} · ${r.where}`, 'ok');
  } catch (e) {
    const ok = localBackup();
    setSave(ok ? 'Saved in this browser only: the server could not be reached. It will sync later.' : 'Not saved: ' + e.message, 'bad');
  }
  lsLast({ id: draft.id, user: USER });
}
addEventListener('pagehide', () => { if (dirty) localBackup(); });
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') saveNow(); });

// ---------- logos ----------
function drawLogos() {
  const w = $('logoWrap'), r = $('divisionRow');
  w.replaceChildren(); r.replaceChildren(); r.hidden = true;
  if (!BRAND) return;
  const base = BRANDING_URL.replace(/[^/]+$/, '');
  const img = (b, cls) => el('img', { src: base + b.logo, alt: b.name, title: b.name, class: cls });
  if (BRAND.company) w.append(img(BRAND.company));
  if (BRAND.department) w.append(el('span', { class: 'sep' }), img(BRAND.department, 'dept'),
    el('span', { class: 'dept-name' }, ...BRAND.department.name.split(' ').flatMap((x, i) => i ? [el('br'), x] : [x])));
  const div = BRAND.by_business_unit?.[state.businessUnit];
  if (div) { r.append('Requesting BU', img(div)); r.hidden = false; }
}

// ---------- fields ----------
function input(f, value, onChange) {
  const id = 'f_' + Math.random().toString(36).slice(2, 9);
  const wrap = el('div', { class: 'field', 'data-key': f.key });
  const lab = el('label', { for: id }, f.label, f.required ? el('span', { class: 'star', text: '*' }) : null);
  let ctl;
  if (f.type === 'select') {
    ctl = el('select', { id }, el('option', { value: '', text: '-- Select --' }), optionsOf(f).map(o => el('option', { value: o, text: o })));
    ctl.value = value ?? '';
  } else if (f.type === 'combo') {
    const lid = id + '_list';
    ctl = el('input', { id, type: 'text', list: lid, placeholder: 'Pick or type', autocomplete: 'off' });
    ctl.value = value ?? '';
    wrap.append(el('datalist', { id: lid }, optionsOf(f).map(o => el('option', { value: o }))));
  } else if (f.lookup) {
    // Part number from the parts directory: suggestions as you type, any value can still be typed.
    const lid = id + '_list';
    ctl = el('input', { id, type: 'text', list: lid, placeholder: 'Type or pick from the parts directory', autocomplete: 'off' });
    ctl.value = value ?? '';
    wrap.append(el('datalist', { id: lid }, PARTS.filter(p => p.status !== 'obsolete').map(p => el('option', { value: partKey(p, f.lookup.format), label: p.product_name || p.description || '' }))));
  } else if (f.type === 'textarea') {
    ctl = el('textarea', { id, placeholder: 'Enter ' + f.label.toLowerCase() }); ctl.value = value ?? '';
  } else if (f.type === 'radio') {
    ctl = el('div', { class: 'radios', role: 'radiogroup', 'aria-label': f.label },
      optionsOf(f).map(o => el('label', {}, el('input', { type: 'radio', name: id, value: o, checked: value === o, onchange: () => onChange(o) }), o[0].toUpperCase() + o.slice(1))));
    wrap.append(el('div', { class: 'label' }, f.label, f.required ? el('span', { class: 'star', text: '*' }) : null), ctl);
    if (f.note) wrap.append(el('div', { class: 'help', text: f.note }));
    return wrap;
  } else if (f.type === 'file') {
    // Only the file names are kept (nothing is uploaded from here), so the assistant, Check quality and the lab
    // reviewer can see what will be attached. The files themselves are attached on the lab's online form.
    const list = Array.isArray(value) ? value : [];
    const set = v => { onChange(v); markDirty(); wrap.replaceWith(input(f, v, onChange)); };
    const ok = x => (f.accept || []).some(ext => x.name.toLowerCase().endsWith(ext)) && x.bytes <= (f.max_mb || 2) * 1048576;
    const chips = el('div', { class: 'chips' }, list.map(x => el('span', { class: 'chip' + (x.ok ? '' : ' warn'),
      title: x.ok ? 'Attach this file on the lab\'s online form.' : `Not accepted there (${(f.accept || []).join(', ')}, max ${f.max_mb} MB): share it by link in Additional Information.`,
      text: x.name + (x.ok ? '' : ' · link') })));
    const pick = el('input', { id, type: 'file', multiple: true, 'aria-label': 'Choose the files you will attach' });
    pick.addEventListener('change', () => set([...list, ...[...pick.files].map(x => ({ name: x.name, bytes: x.size, ok: ok({ name: x.name, bytes: x.size }) }))]));
    const clear = list.length ? el('button', { type: 'button', class: 'btn-link', onclick: () => set([]) }, 'Clear list') : null;
    ctl = el('div', { class: 'drop' }, pick, chips, clear,
      el('div', { class: 'help', text: `Only the file names are kept here, so the assistant and Check quality know what you will attach. Attach the files on ${F().target} (${(f.accept || []).join(', ')}, max ${f.max_mb} MB each). For test boards, attach the schematic and layout as PDF and share the full Gerber/ODB++ package by link.` }));
    wrap.append(el('div', { class: 'label' }, f.label), ctl);
    return wrap;
  } else if (f.type === 'money') {
    ctl = el('input', { id, type: 'number', step: '0.01', min: '0', inputmode: 'decimal', placeholder: '0.00' }); ctl.value = value ?? '';
  } else {
    ctl = el('input', { id, type: f.type === 'number' ? 'number' : f.type, placeholder: f.type === 'email' ? 'you@example.com' : (f.type === 'date' ? undefined : 'Enter ' + f.label.toLowerCase()) });
    ctl.value = value ?? '';
  }
  ctl.addEventListener('input', () => onChange(ctl.value));
  if (f.key === 'businessUnit') ctl.addEventListener('input', drawLogos);
  wrap.append(lab, ctl);
  if (f.note) wrap.append(el('div', { class: 'help', text: f.note }));
  return wrap;
}

// ---------- parts directory ----------
const partKey = (p, fmt) => fmt === 'pn_rev' ? `${p.part_number} Rev ${p.rev}` : p.part_number;
const findPart = (v, fmt) => {
  const x = String(v || '').trim().toLowerCase(), pn = x.split(/\s+rev\b/)[0].trim();
  return x && (PARTS.find(p => partKey(p, fmt).toLowerCase() === x) || PARTS.find(p => p.part_number.toLowerCase() === pn));
};
// When a part number matches the directory, fill the empty fields of that item from it.
function applyPart(row, col) {
  const p = findPart(row[col.key], col.lookup.format);
  if (!p) return false;
  if (col.lookup.format === 'pn_rev') row[col.key] = partKey(p, 'pn_rev');
  let changed = false;
  for (const [k, src] of Object.entries(col.lookup.fill || {})) if (!String(row[k] ?? '').trim() && p[src]) { row[k] = p[src]; changed = true; }
  row._part = { part_number: p.part_number, rev: p.rev, status: p.status };
  return changed;
}

// Per-item files: slots per item, checked against the form's upload_rule. Only names and sizes are kept.
const FILE_KINDS = [
  { key: 'drawing', label: 'Drawing (PDF)', accept: '.pdf' },
  { key: 'cad', label: 'CAD model (STEP)', accept: '.step,.stp' },
  { key: 'quote', label: 'Quote or spec sheet', accept: '.pdf,.xlsx,.docx' },
  { key: 'photos', label: 'Photos', accept: 'image/*' },
];
const okFor = (f, rule) => !rule || (rule.accept.some(ext => f.name.toLowerCase().endsWith(ext)) && f.bytes <= rule.max_mb * 1024 * 1024);
function itemFiles(row, cfg) {
  row._files = row._files || {};
  const rule = F().upload_rule;
  const box = el('div', { class: 'files' }, el('div', { class: 'label', style: 'margin-top:10px', text: 'Files for this item' }));
  const grid = el('div', { class: 'grid2' });
  FILE_KINDS.filter(k => cfg.kinds.includes(k.key)).forEach(k => {
    const req = cfg.required.includes(k.key);
    const chips = el('div', { class: 'chips' });
    const tip = rule ? `Accepted: ${rule.accept.join(', ')} up to ${rule.max_mb} MB (${rule.where})` : '';
    const draw = () => chips.replaceChildren(...(row._files[k.key] || []).map(f => el('span', { class: 'chip' + (f.ok ? '' : ' warn'), title: f.ok ? tip : 'Not accepted by the upload: share by link. ' + tip, text: f.name + (f.ok ? '' : ' · link') })));
    const inp = el('input', { type: 'file', multiple: k.key === 'photos', accept: k.accept, 'aria-label': k.label });
    inp.addEventListener('change', () => { row._files[k.key] = [...inp.files].map(f => ({ name: f.name, bytes: f.size, ok: okFor({ name: f.name, bytes: f.size }, rule) })); draw(); });
    draw();
    grid.append(el('div', { class: 'field', 'data-key': '_file_' + k.key }, el('label', {}, k.label, req ? el('span', { class: 'star', text: '*' }) : null), inp, chips));
  });
  if (!cfg.required.length) grid.append(input({ key: 'fileLink', label: 'Link to files', type: 'text' }, row.fileLink, v => { row.fileLink = v; }));
  box.append(grid, el('div', { class: 'help', text: 'Files stay on this computer; the draft keeps their names. Pick them again when you enter the request.' }));
  if (cfg.match) box.append(el('div', { class: 'help', text: cfg.match }));
  return box;
}

function tableSection(step, t) {
  const key = 'step' + step.n + '_rows';
  state[key] = state[key] || (t.min_rows ? [{}] : []);
  const box = el('div');
  const draw = () => {
    box.replaceChildren();
    state[key].forEach((row, i) => {
      box.append(el('div', { class: 'row', 'data-row': i },
        el('div', { class: 'row-head' }, el('strong', { text: `Item ${i + 1}` }),
          el('button', { type: 'button', class: 'btn-link', text: 'Remove', onclick: () => { state[key].splice(i, 1); draw(); markDirty(); updateTotals(); } })),
        el('div', { class: 'grid2' }, t.columns.map(c => {
          const w = input(c, row[c.key], v => { row[c.key] = v; });
          if (c.lookup) {
            w.querySelector('input').addEventListener('change', () => { if (applyPart(row, c)) { draw(); markDirty(); } });
            const p = findPart(row[c.key], c.lookup.format);
            const revTyped = (String(row[c.key] || '').match(/rev\.?\s*([a-z0-9]+)/i) || [])[1] || row.rev;
            const revNote = p && revTyped && p.rev && String(revTyped).toUpperCase() !== String(p.rev).toUpperCase() ? ` (directory has Rev ${p.rev})` : '';
            w.append(el('div', { class: 'help', text: p ? `In the parts directory: ${p.product_name || p.description}${p.status === 'obsolete' ? ' (OBSOLETE)' : ''}${revNote}` : (row[c.key] ? 'Not in the parts directory' : '') }));
          }
          return w;
        })),
        t.totals ? el('div', { class: 'calc', 'data-calc': `ext-${step.n}-${i}` }) : null,
        t.item_files ? itemFiles(row, t.item_files) : null));
    });
    if (state[key].length < t.max_rows)
      box.append(el('button', { type: 'button', class: 'btn btn-quiet', text: '+ Add item', onclick: () => { state[key].push({}); draw(); markDirty(); updateTotals(); } }));
  };
  draw();
  const note = t.optional ? `Optional. Up to ${t.max_rows} items.` : `At least ${t.min_rows} item, at most ${t.max_rows}.`;
  return [el('p', { class: 'note', text: note }), box];
}

// Line totals and estimated cost (purchase requisition).
function updateTotals() {
  F().steps.forEach(step => {
    const t = tableOf(step);
    if (t?.totals) (state['step' + step.n + '_rows'] || []).forEach((r, i) => {
      const e = document.querySelector(`[data-calc="ext-${step.n}-${i}"]`);
      if (e) e.textContent = 'Extended: ' + money(num(r[t.totals.qty]) * num(r[t.totals.price]));
    });
    if (step.summary) {
      const ts = F().steps.find(s => s.n === step.summary.table_step), tt = tableOf(ts);
      const sub = (state['step' + ts.n + '_rows'] || []).reduce((a, r) => a + num(r[tt.totals.qty]) * num(r[tt.totals.price]), 0);
      const lines = [['Subtotal', sub]].concat(step.summary.adders.map(a => [a.label, a.sign * num(state[a.key])]));
      const total = lines.reduce((a, [, v]) => a + v, 0);
      const box = document.querySelector(`[data-calc="summary-${step.n}"]`);
      if (box) box.replaceChildren(...lines.map(([k, v]) => el('div', {}, el('span', { text: k }), el('span', { text: money(v) }))),
        el('div', { class: 'total' }, el('span', { text: 'Estimated cost' }), el('span', { text: money(total) })));
    }
  });
}

// ---------- page ----------
function render() {
  document.getElementById('title').textContent = F().title;
  if (typeof CHAT !== 'undefined' && !$('chat').hidden && CHAT.form !== formKey) openChat();   // chat follows the form
  $('draftOnly').textContent = formKey === 'lab_test_request'
    ? 'Draft only. The assistant fills what it can from the request and the cited procedures; you check every field.'
    : 'Draft only. You fill in the fields; Check quality reviews them before you enter them in the real form.';
  $('target').textContent = `Nothing is submitted from here. Your draft saves as you type; enter it in ${F().target} when it is ready.` + (F().note ? ' ' + F().note : '');
  $('switch').replaceChildren(...Object.entries(S.forms).map(([k, f]) => el('button', { type: 'button', 'aria-pressed': String(k === formKey), onclick: () => newDraft(k) }, f.short || f.title)));
  const nav = $('nav'), host = $('sections');
  nav.replaceChildren(); host.replaceChildren();
  F().steps.forEach(step => {
    const sid = 'sec' + step.n;
    nav.append(el('li', { 'data-step': step.n }, el('a', { href: '#' + sid }, el('span', { class: 'dot', text: step.n }), step.title)));
    const sec = el('section', { id: sid }, el('div', { class: 'step', text: `Step ${step.n} of ${F().steps.length}` }), el('h2', { text: step.title }));
    expandFields(step.fields).forEach(f => sec.append(input(f, state[f.key], v => {
      state[f.key] = v;
      // The requester always gets the report: an empty "Send copies to" takes their own email.
      if (f.key === 'email' && v && !String(state.sendCopiesTo ?? '').trim()) {
        state.sendCopiesTo = v; const c = document.querySelector('.field[data-key="sendCopiesTo"] input'); if (c) c.value = v;
      }
    })));
    const t = tableOf(step);
    if (t) sec.append(...tableSection(step, t));
    if (step.summary) sec.append(el('div', { class: 'summary', 'data-calc': `summary-${step.n}` }));
    if (step.footer) sec.append(el('p', { class: 'note', text: step.footer }));
    host.append(sec);
  });
  drawLogos();
  updateTotals();
}

function drawAccount() {
  const a = $('account');
  a.replaceChildren(
    el('span', { class: 'who', text: USER ? `Signed in as ${USER}` : (HAVE_API ? 'Guest · drafts stay in this browser' : 'Offline · drafts stay in this browser') }),
    el('button', { type: 'button', onclick: openDrafts }, 'My drafts'),
    el('button', { type: 'button', onclick: () => newDraft(formKey) }, 'New'),
    HAVE_API ? (USER ? el('button', { type: 'button', onclick: signOut }, 'Sign out') : el('button', { type: 'button', onclick: openSignIn }, 'Sign in')) : null);
}

async function newDraft(k) {
  await saveNow();
  formKey = k; state = {}; draft = { id: newId(), created: nowIso() };
  $('banner').hidden = true; $('status').textContent = '';
  render();
  setSave('New draft · saves as you type');
}
function openDraft(d) {
  formKey = S.forms[d.form] ? d.form : formKey;
  state = d.fields || {}; draft = { id: d.id, created: d.created || nowIso(), saved: true };
  render();
  setSave(`Opened · last saved ${when(d.updated)}`, 'ok');
  lsLast({ id: d.id, user: USER });
}

// ---------- check required ----------
function check() {
  const missing = [];
  document.querySelectorAll('.invalid').forEach(e => e.classList.remove('invalid'));
  document.querySelectorAll('.err').forEach(e => e.id !== 'siErr' && e.remove());
  F().steps.forEach(step => {
    let stepOk = true;
    expandFields(step.fields).forEach(f => {
      if (f.required && f.type !== 'file' && !String(state[f.key] ?? '').trim()) { missing.push(`${step.title}: ${f.label}`); stepOk = false; mark('#sec' + step.n, f.key); }
    });
    const t = tableOf(step);
    if (t) {
      const rows = state['step' + step.n + '_rows'] || [];
      if (rows.length < t.min_rows) { missing.push(`${step.title}: add at least ${t.min_rows} item`); stepOk = false; }
      rows.forEach((r, i) => {
        t.columns.forEach(c => { if (c.required && !String(r[c.key] ?? '').trim()) { missing.push(`${step.title}, item ${i + 1}: ${c.label}`); stepOk = false; } });
        (t.item_files?.required || []).forEach(k => { if (!(r._files?.[k] || []).length) { missing.push(`${step.title}, item ${i + 1}: ${FILE_KINDS.find(x => x.key === k).label}`); stepOk = false; } });
        const d = r._files?.drawing?.[0]?.name, c = r._files?.cad?.[0]?.name, stem = n => n.replace(/\.[^.]+$/, '').toLowerCase();
        if (t.item_files?.match && d && c && stem(d) !== stem(c)) { missing.push(`${step.title}, item ${i + 1}: drawing and STEP file names differ (${d} / ${c})`); stepOk = false; }
      });
    }
    document.querySelector(`#nav li[data-step="${step.n}"]`)?.classList.toggle('done', stepOk);
  });
  const s = $('status');
  s.className = 'status ' + (missing.length ? 'bad' : 'ok');
  s.textContent = missing.length ? `${missing.length} required field(s) empty: ${missing.slice(0, 3).join('; ')}${missing.length > 3 ? '; …' : ''}` : 'All required fields are filled. Ready for your review.';
  return missing;
}
function mark(sec, key) {
  const w = document.querySelector(`${sec} .field[data-key="${key}"]`);
  if (!w) return;
  w.querySelector('input,select,textarea')?.classList.add('invalid');
  w.append(el('div', { class: 'err', text: 'Required' }));
}

// ---------- export / import ----------
function exportJson() {
  const d = { ...currentDraft(), exported: nowIso(), missing_required: check() };
  const a = el('a', { href: URL.createObjectURL(new Blob([JSON.stringify(d, null, 2)], { type: 'application/json' })), download: `${formKey}_${d.title.replace(/[^\w.-]+/g, '_')}.json` });
  document.body.append(a); a.click(); a.remove();
}
function importDraft(d, banner) {
  openDraft({ ...d, id: newId(), created: nowIso() });     // an imported draft becomes a new draft of yours
  dirty = true; saveNow();
  $('banner').hidden = false; $('banner').textContent = banner;
}

// ---------- quality check (AI flags) ----------
// The server runs assistant/quality.py on the draft: every flag points at a field, says why (with its source)
// and how to fix it. Without the server, only the required-field check runs.
function clearFlags() {
  document.querySelectorAll('.flag-error, .flag-warn, .flag-info').forEach(e => e.classList.remove('flag-error', 'flag-warn', 'flag-info'));
  document.querySelectorAll('.flag-note, .err').forEach(e => e.id !== 'siErr' && e.remove());
}
function flagTarget(f) {
  const scope = f.step ? document.querySelector('#sec' + f.step) : document;
  if (!scope || !f.field) return f.step ? document.querySelector('#sec' + f.step + ' h2') : null;
  if (f.row !== null && f.row !== undefined) {
    const r = scope.querySelector(`.row[data-row="${f.row}"] .field[data-key="${f.field}"]`);
    if (r) return r;
  }
  return scope.querySelector(`.field[data-key="${f.field}"]`) || document.querySelector(`.field[data-key="${f.field}"]`);
}
function showFlag(f) {
  const t = flagTarget(f);
  if (!t) return;
  t.scrollIntoView({ behavior: 'smooth', block: 'center' });
  t.classList.add('flag-pulse'); setTimeout(() => t.classList.remove('flag-pulse'), 1600);
}
async function checkQuality() {
  await saveNow();
  clearFlags();
  const r = await fetch('/api/quality', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ form: formKey, fields: state }) }).catch(() => null);
  const q = r && r.ok ? await r.json() : null;
  const panel = $('flagsPanel');
  if (!q) { panel.hidden = true; check(); return; }
  const order = { error: 0, warn: 1, info: 2 };
  const flags = q.flags.slice().sort((a, b) => order[a.severity] - order[b.severity]);
  const byField = new Map();
  flags.forEach(f => { const t = flagTarget(f); if (t && f.field) { if (!byField.has(t)) byField.set(t, []); byField.get(t).push(f); } });
  byField.forEach((fs, t) => {
    const worst = fs[0].severity;
    t.classList.add('flag-' + worst);
    t.append(el('div', { class: 'flag-note ' + worst }, ...fs.map(f => el('div', { text: (f.severity === 'error' ? '✖ ' : f.severity === 'warn' ? '▲ ' : 'ℹ ') + f.message }))));
  });
  F().steps.forEach(step => document.querySelector(`#nav li[data-step="${step.n}"]`)?.classList.toggle('done', !flags.some(f => f.step === step.n && f.severity === 'error')));
  const label = { error: 'Must fix', warn: 'Should fix', info: 'Good practice' };
  // One line per step for empty required fields (the fields themselves are still outlined on the form).
  const listed = [], groups = new Map();
  flags.forEach(f => {
    if (f.severity === 'error' && /^.+ is empty\.$/.test(f.message) && f.step) {
      const key = f.step + '|' + (f.row ?? '');
      if (!groups.has(key)) { groups.set(key, { ...f, names: [] }); listed.push(groups.get(key)); }
      groups.get(key).names.push(f.message.replace(/^Item \d+: /, '').replace(/ is empty\.$/, ''));
    } else listed.push(f);
  });
  groups.forEach(g => {
    if (g.names.length < 2) return;
    const where = g.row == null ? `Step ${g.step}` : `Step ${g.step}, item ${g.row + 1}`;
    g.message = `${where}: ${g.names.length} required fields are empty: ${g.names.join(', ')}.`; g.why = 'Required by the request form.'; g.fix = null;
  });
  panel.hidden = false;
  panel.className = 'flags-panel ' + (q.errors ? 'bad' : q.warnings ? 'warn' : 'ok');
  panel.replaceChildren(...[
    el('div', { class: 'flags-head' }, byBadge('rule'), el('strong', { text: q.readiness }),
      el('span', { class: 'meta', text: ` ${q.errors} must fix · ${q.warnings} should fix · ${q.info} good practice` }),
      el('button', { type: 'button', class: 'btn-link', style: 'margin-left:auto;color:var(--ink-quiet)', onclick: () => { panel.hidden = true; clearFlags(); } }, 'Hide')),
    el('div', { class: 'meta', text: 'Rule check, no AI: the form\'s required fields and the cited procedures\' requirements. The same draft always gets the same result.' }),
    q.tests_detected.length ? el('div', { class: 'meta', text: 'Tests recognised: ' + q.tests_detected.map(t => t.replace(/_/g, ' ')).join(', ') }) : null,
    el('ol', { class: 'flag-list' }, listed.map(f => el('li', { class: 'flag-item ' + f.severity },
      el('button', { type: 'button', class: 'flag-msg', onclick: () => showFlag(f) }, el('span', { class: 'sev ' + f.severity, text: label[f.severity] }), ' ', f.message),
      el('div', { class: 'meta', text: f.why }),
      f.fix ? el('div', { class: 'fix', text: 'Fix: ' + f.fix }) : null,
      f.source ? el('span', { class: 'src', text: f.source }) : null,
      rateRow({ kind: 'flag', key: f.field || '', text: f.message, by: 'rule' }, { tests: q.tests_detected })))),
    feedbackBar(panel, { tests: q.tests_detected })].filter(Boolean));
  panel.classList.remove('fb-on');
  panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  return q;
}

// ---------- examples of good requests ----------
async function loadExamples() {
  // Real past requests (private, personal details removed) first, then the synthetic examples.
  // Without the private library (e.g. a reviewer's copy of the repository), the SYNTHETIC past requests are shown instead.
  const priv = await getJSON('../data/private/lab_requests/index.json');
  const past = priv?.examples?.length ? null : await getJSON('../data/synthetic/past_requests/index.json');
  const syn = await getJSON('../data/synthetic/lab_requests/index.json');
  const items = [...(priv?.examples || []).map(x => ({ ...x, private: true, url: '../data/private/lab_requests/' + x.file })),
                 ...(past?.examples || []).map(x => ({ ...x, synthetic: true, url: '../data/synthetic/past_requests/' + x.file })),
                 ...(syn?.examples || []).map(x => ({ ...x, synthetic: true, url: '../data/synthetic/lab_requests/' + x.file }))];
  const demos = await getJSON('../data/synthetic/drafts/index.json');
  (demos?.demos || []).forEach(x => items.push({ ...x, id: 'DEMO', why_good: [], url: '../data/synthetic/drafts/' + x.file }));
  // Search: the words of each example (title, form, notes, tests and fields), filtered as you type.
  const words = x => [x.title, x.form, x.id, ...(x.why_good || []), ...(x.gaps || []), ...(x.tests || [])].join(' ').toLowerCase();
  const draw = () => {
    const q = $('exSearch').value.trim().toLowerCase().split(/\s+/).filter(Boolean), kind = $('exKind').value;
    const res = q.map(w => new RegExp('(^|[^a-z0-9])' + w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));   // from the start of a word: 'sem' is not 'assembly'
    const shown = items.filter(x => (!kind || (kind === 'private' ? x.private : x.synthetic)) && res.every(r => r.test(words(x))));
    $('exCount').textContent = `${shown.length} of ${items.length}`;
    $('exampleList').replaceChildren(...shown.map(row));
  };
  $('exSearch').oninput = draw; $('exKind').onchange = draw;
  const row = x => el('li', { class: 'ex-row' },
    el('div', {}, el('div', { text: x.title }), el('div', { class: 'meta', text: `${x.private ? 'Real past request (private) · ' : x.synthetic ? 'SYNTHETIC · ' + (x.kind === 'contrast example (what to avoid)' ? 'what to avoid · ' : '') : ''}${S.forms[x.form]?.short || x.form}${x.why_good?.length ? ' · ' + x.why_good[0] : ''}` })),
    el('div', { class: 'ex-btns' },
      el('button', { type: 'button', class: 'btn-sm btn-sm-primary', onclick: () => previewExample(x) }, 'View'),
      el('button', { type: 'button', class: 'btn-sm', title: 'Open an editable copy as a new draft', onclick: async () => {
        const d = await getJSON(x.url); if (!d) return;
        $('draftsDlg').close();
        importDraft({ ...d, title: (x.id === 'DEMO' ? '' : 'Copy of ') + x.title },
          x.why_good?.length ? `${x.synthetic ? 'SYNTHETIC example (invented for the course, not a real request). ' : ''}Example notes (fixed text, not AI). Copy of ${x.private ? 'past request' : 'example'} ${x.id}. Why it is a good request: ${x.why_good.join(' ')}${d.gaps?.length ? ' What it missed: ' + d.gaps.join(' ') : ''}`
            : 'Demo draft with typical mistakes. Press Check quality to see the flags.');
      } }, 'Use as start')));
  draw();
}

// ---------- read-only preview of a past request or example (nothing is saved) ----------
async function previewExample(x) {
  const d = await getJSON(x.url);
  if (!d) return;
  const form = S.forms[d.form || x.form] || F(), f = d.fields || {};
  const has = v => Array.isArray(v) ? v.some(has) : (v && typeof v === 'object') ? Object.entries(v).some(([k, y]) => !k.startsWith('_') && has(y)) : String(v ?? '').trim() !== '';
  const body = el('div', { class: 'pv-body' });
  form.steps.forEach(step => {
    const parts = [];
    const kv = expandFields(step.fields).filter(fd => fd.type !== 'file' && has(f[fd.key]));
    if (kv.length) parts.push(el('dl', { class: 'pv-kv' }, kv.flatMap(fd => [el('dt', { text: fd.label }), el('dd', { text: String(f[fd.key]) })])));
    const t = tableOf(step), rows = (f[`step${step.n}_rows`] || []).filter(has);
    if (t && rows.length) {
      const cols = (t.columns || []).filter(c => rows.some(r => has(r[c.key])));
      parts.push(el('table', { class: 'pv-table' }, el('thead', {}, el('tr', {}, cols.map(c => el('th', { text: c.label })))),
        el('tbody', {}, rows.map(r => el('tr', {}, cols.map(c => el('td', { text: String(r[c.key] ?? '') })))))));
      const files = rows.flatMap(r => Object.values(r._files || {}).flat().map(z => z.name)).filter(Boolean);
      if (files.length) parts.push(el('div', { class: 'pv-meta', text: 'Files: ' + files.join(', ') }));
    }
    if (parts.length) body.append(el('h4', { text: step.title }), ...parts);
  });
  const notes = [];
  if (x.why_good?.length) notes.push(el('div', {}, el('b', { text: 'Why it is a good request: ' }), x.why_good.join(' ')));
  if (d.gaps?.length) notes.push(el('div', {}, el('b', { text: 'What it missed: ' }), d.gaps.join(' ')));
  $('pvTitle').textContent = x.title;
  $('pvMeta').textContent = [x.private ? 'Real past request (private, details removed)' : x.synthetic ? 'SYNTHETIC (invented for the course)' : 'Demo draft',
    form.short || form.title, x.id !== 'DEMO' ? x.id : ''].filter(Boolean).join(' · ');
  $('pvNotes').replaceChildren(...notes); $('pvNotes').hidden = !notes.length;
  $('pvBody').replaceWith(body); body.id = 'pvBody';
  $('pvUse').onclick = () => { $('previewDlg').close(); $('draftsDlg').close();
    importDraft({ ...d, title: 'Copy of ' + x.title }, `${x.synthetic ? 'SYNTHETIC example. ' : ''}Copy of ${x.id}.`); };
  $('previewDlg').showModal();
}
$('pvClose').addEventListener('click', () => $('previewDlg').close());
$('pvPrint').addEventListener('click', () => { document.body.classList.add('printing-preview'); window.print(); document.body.classList.remove('printing-preview'); });

// ---------- drafts dialog ----------
async function openDrafts() {
  await saveNow();
  $('draftsWhere').textContent = USER ? `Saved to your account (${USER}) on the local server.` : 'Saved in this browser only. Sign in to keep them on the local server.';
  const list = $('draftList'); list.replaceChildren(el('li', { text: 'Loading…' }));
  $('draftsDlg').showModal();
  const items = await Store.list();
  list.replaceChildren(...(items.length ? items : []).map(d => {
    const del = el('button', { type: 'button', class: 'btn-quiet' }, 'Delete');
    del.addEventListener('click', async () => {
      if (del.dataset.armed) { await Store.del(d.id); if (d.id === draft.id) await newDraft(formKey); openDrafts(); }
      else { del.dataset.armed = 1; del.textContent = 'Delete?'; }
    });
    return el('li', {},
      el('div', {}, el('div', { text: (d.id === draft.id ? '● ' : '') + (d.title || 'Untitled') }),
        el('div', { class: 'meta', text: `${S.forms[d.form]?.short || d.form} · ${when(d.updated)}${d.unsynced ? ' · not synced yet' : ''}` })),
      el('div', {}, el('button', { type: 'button', class: 'btn-primary', onclick: async () => { const full = await Store.get(d.id); if (full) openDraft(full); $('draftsDlg').close(); } }, 'Open'), ' ', del));
  }));
  if (!items.length) list.replaceChildren(el('li', { class: 'meta', text: 'No drafts yet.' }));
  loadExamples();
}

// ---------- sign in ----------
function openSignIn() {
  $('siErr').textContent = ''; $('siRegister').hidden = !CAN_REGISTER;
  const n = Object.values(lsAll()).filter(d => !d.owner).length;
  $('siMoveWrap').hidden = !n; $('siMoveText').textContent = `Move my ${n} guest draft${n === 1 ? '' : 's'} from this browser into my account`;
  $('signin').showModal();
}
$('signinForm').addEventListener('submit', async e => {
  const how = e.submitter?.value;
  if (how === 'guest') return;                               // dialog closes, stay a guest
  e.preventDefault();
  const r = await fetch('/api/' + (how === 'register' ? 'register' : 'login'), { method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user: $('siUser').value, password: $('siPass').value }) }).catch(() => null);
  const j = r ? await r.json().catch(() => ({})) : { error: 'The local server is not running.' };
  if (!r || !r.ok) { $('siErr').textContent = j.error || 'Could not sign in.'; return; }
  $('siPass').value = '';
  await saveNow();
  const move = !$('siMoveWrap').hidden && $('siMove').checked;
  USER = j.user;
  if (move) {                                                // guest drafts become this user's, then upload
    const all = lsAll();
    Object.values(all).filter(d => !d.owner).forEach(d => { all[d.id] = { ...d, owner: USER, unsynced: true }; });
    lsWrite(all);
  }
  await pushUnsynced();
  $('signin').close();
  drawAccount();
  if (hasContent(state)) { dirty = true; await saveNow(); }   // the open draft now belongs to the account
});
async function signOut() {
  await saveNow();
  await fetch('/api/logout', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: '{}' }).catch(() => null);
  USER = null; lsLast(null);
  drawAccount();
  await newDraft(formKey);
}

// ---------- assistant chat ----------
// The engineer describes the test; the server (assistant/chat.py) asks for missing inputs, cites procedures and proposes
// field values. Nothing changes in the draft until the engineer presses Apply, and nothing is ever submitted.
const CHAT = { history: [], status: null, busy: false, form: null };
// Who wrote each value or remark, shown as a small label so AI text is never mistaken for a fixed rule.
const BY = { ai: '✦ AI', rule: 'Rule', procedure: 'Procedure', parts: 'Parts list' };
const BY_TIP = { ai: 'Written by the local AI model, then checked: numbers and procedure IDs must appear in your draft or the cited procedures.',
                 rule: 'Fixed rule: the same answer every time, no AI.', procedure: 'Copied from the cited procedure (no AI).',
                 parts: 'From the parts directory (no AI).' };
const byBadge = kind => el('span', { class: 'by ' + kind, title: BY_TIP[kind] || '', text: BY[kind] || kind });
// What the assistant can do on each form. Only the General lab form is drafted so far; on the others it says so plainly.
const CHAT_FORMS = {
  lab_test_request: {
    intro: 'Describe the test you need in your own words: the part, how many samples, the test and its conditions, and what decision the results support. I\'ll ask for anything the procedure requires, cite the procedure, and propose field values for you to apply. Already filled in the form? Ask me to review it.',
    examples: ['Measure warpage on 10 SYN-10001 housings through reflow, peak 260 C, to confirm the new mold before release.',
               'Thermal cycling -40 C to 125 C, 500 cycles, readouts every 100 cycles, 20 SYN-20001 parts.',
               'Room-temperature flatness on 5 SYN-10002 housings, limit 0.10 mm over the seating plane.',
               'What do you think of the request on the form? What is missing?'] },
  smt_lab_test_request: { off: 'On the SMT lab form the assistant does not fill fields yet. Fill it in by hand, then press Check quality. To have a test request drafted, switch to the General lab form.' },
  machine_shop_request: { off: 'On the Machine shop form the assistant does not fill fields yet. Fill it in by hand, then press Check quality. To have a test request drafted, switch to the General lab form.' },
  purchase_requisition: { off: 'On the Purchase req form the assistant does not fill fields yet. Fill in the supplier, shipping, line items and account by hand, then press Check quality: it checks the requisition against the purchasing rules. To have a test request drafted, switch to the General lab form.' },
};
const STATE_TEXT = { 'incomplete': 'Incomplete', 'ready for review': 'Ready for your review', 'refused': 'Not done' };
function labelOf(key) {
  for (const step of F().steps) {
    for (const f of expandFields(step.fields)) if (f.key === key) return f.label;
    const t = tableOf(step);
    if (t) { if (key === `step${step.n}_rows`) return step.title; const c = (t.columns || []).find(c => c.key === key); if (c) return c.label; }
  }
  return key;
}
function chatAdd(node) { $('chatLog').append(node); node.scrollIntoView({ block: 'end' }); return node; }
function chatSay(cls, text) { return chatAdd(el('div', { class: 'msg ' + cls, text })); }
// Which AI model is serving, asked from the server (the model server reports its own name, quantization and GPU).
async function refreshAIStatus() {
  if (!HAVE_API) return;
  const r = await fetch('/api/assistant/status', { credentials: 'same-origin' }).catch(() => null);
  CHAT.status = r && r.ok ? await r.json() : { mode: 'offline', label: 'Sign in to use the assistant from another device.', model_label: 'unknown (not signed in)' };
  const st = CHAT.status, badge = { model: 'AI on', demo: 'Demo: no AI', offline: 'No AI' }[st.mode] || st.mode;
  $('chatMode').textContent = badge; $('chatMode').className = 'chat-mode ' + st.mode;
  $('chatMode').title = st.label + (st.version ? ' · ' + st.version : '');
  // Several allowed models (LRT_AI_MODELS): a picker; the choice is remembered in this browser.
  if (st.models?.length) {
    try { CHAT.model = localStorage.getItem('lrt_model'); } catch (_) {}
    if (!st.models.includes(CHAT.model)) CHAT.model = st.model;
    const pick = el('select', { class: 'fb-role', 'aria-label': 'AI model' }, st.models.map(m => el('option', { value: m, text: m })));
    pick.value = CHAT.model;
    pick.addEventListener('change', () => { CHAT.model = pick.value; try { localStorage.setItem('lrt_model', pick.value); } catch (_) {} refreshAIStatus(); });
    $('chatModel').replaceChildren(el('span', { class: 'k', text: 'AI model: ' }), pick, el('span', { class: 'k', text: ' · ' + st.where }));
  } else {
    CHAT.model = null;
    $('chatModel').replaceChildren(el('span', { class: 'k', text: 'AI model: ' }),
      el('strong', { text: st.mode === 'model' ? st.model_label : st.model_label || 'none' }),
      st.mode === 'model' ? '' : el('span', { class: 'k', text: ' · drafts by fixed rules' }));
  }
  $('chatModel').title = (st.model || '') + (st.version ? ' · tool ' + st.version : '');
  // Show the tool version, and warn when the server still runs older code than what is on disk (git pull without restart).
  $('chatModel').append(el('span', { class: 'k', text: ' · tool ' + (st.version || '?').split(' ')[0] }));
  $('chatStale').hidden = !st.stale; $('chatStale').textContent = st.stale || '';
  $('staleBanner').hidden = !st.stale; $('staleBanner').textContent = st.stale ? '⚠ ' + st.stale : '';
  const chip = $('aiChip');
  chip.hidden = false; chip.className = 'ai-chip ' + st.mode;
  chip.textContent = st.mode === 'model' ? '✦ ' + (CHAT.model || st.model_label.split(' · ')[0]) : st.mode === 'demo' ? 'Demo: no AI' : 'No AI';
  chip.title = st.label;
}
async function openChat() {
  $('chat').hidden = false; document.body.classList.add('chat-open');
  fitChatInput(); $('chatInput').focus();
  if (!HAVE_API) {
    $('chatMode').textContent = 'off'; $('chatMode').className = 'chat-mode offline';
    if (!$('chatLog').children.length) chatSay('err', 'The assistant needs the local server. Start the tool with start.bat (or python gui\\serve.py) and open the page it shows.');
    return;
  }
  await refreshAIStatus();                // every time: the model may have been started or stopped since
  if (CHAT.form !== formKey) {           // a different form: start the conversation over for it
    CHAT.form = formKey; CHAT.history = [];
    $('chatLog').replaceChildren();
  }
  const cf = CHAT_FORMS[formKey] || { off: 'The assistant does not fill this form yet. Fill it in by hand, then press Check quality.' };
  $('chatForm').hidden = !!cf.off;
  if (!$('chatLog').children.length) {
    if (cf.off) {
      chatSay('bot', cf.off);
      chatAdd(el('div', { class: 'row-btns' },
        el('button', { type: 'button', class: 'btn btn-primary', onclick: () => newDraft('lab_test_request') }, 'Switch to General lab'),
        el('button', { type: 'button', class: 'btn btn-quiet', onclick: () => { closeChat(); checkQuality(); } }, 'Check quality')));
      return;
    }
    chatSay('bot', `${cf.intro}\n\n${CHAT.status.label}`);
    chatAdd(el('div', { class: 'chips' }, cf.examples.map(t => el('button', { type: 'button', class: 'chip', onclick: () => { $('chatInput').value = t; fitChatInput(); $('chatInput').focus(); } }, t))));
  }
}
function proposalCard(r) {
  const card = el('div', { class: 'card' });
  const st = r.state === 'ready for review' ? 'ready' : r.state;
  card.append(el('span', { class: 'state ' + st, text: STATE_TEXT[r.state] || r.state }));
  if (r.changes.length) {
    const items = [];
    r.changes.forEach(c => {
      const [k, col] = c.split('.');
      const v = r.proposed[k];
      if (Array.isArray(v)) {
        const row = v[0] || {};
        Object.entries(row).filter(([ck, cv]) => cv && (!col || ck === col)).forEach(([ck, cv]) => items.push([labelOf(ck), cv, (r.field_sources || {})[`${k}.${ck}`]]));
      } else items.push([labelOf(k), v, (r.field_sources || {})[k]]);
    });
    card.append(el('h3', { text: 'Proposed for your draft' }), el('ul', { class: 'by-list' }, items.map(([k, v, by]) => el('li', {}, by ? byBadge(by) : null, el('span', { class: 'k', text: k + ': ' }), String(v),
      rateRow({ kind: 'proposal', key: k, text: `${k}: ${v}`, by: by || '' }, { j: r, tests: r.tests })))));
    card.append(el('div', { class: 'row-btns' },
      el('button', { type: 'button', class: 'btn btn-primary', onclick: e => { applyProposal(r); e.target.disabled = true; e.target.textContent = 'Applied'; } }, 'Apply to form'),
      el('button', { type: 'button', class: 'btn btn-quiet', onclick: e => { card.remove(); } }, 'Dismiss')));
  }
  if (r.citations.length) {
    card.append(el('details', {}, el('summary', { text: `Procedures cited (${r.citations.length})` }),
      el('ul', {}, r.citations.map(c => el('li', {}, el('strong', { text: `${c.doc_id} Rev ${c.revision}` }), ` · ${c.section.split(' - ').pop()}`,
        el('div', { class: 'k', text: c.snippet + '…' }))))));
  }
  if (r.flags.length) {
    card.append(el('h3', { style: 'margin-top:10px' }, byBadge('rule'), `Still to fix (${r.flags.filter(f => f.severity === 'error').length} must, ${r.flags.filter(f => f.severity === 'warn').length} should)`),
      el('ul', {}, r.flags.slice(0, 6).map(f => el('li', {}, f.message, rateRow({ kind: 'flag', key: f.field || '', text: f.message, by: 'rule' }, { j: r, tests: r.tests })))));
  }
  card.append(el('div', { class: 'k', style: 'margin-top:8px;font-size:11px', text: `${r.review ? 'Reviewed' : 'Drafted'} by: ${r.mode}. Only you approve; nothing is submitted.` }));
  return card;
}
function applyProposal(r) {
  r.changes.forEach(c => {
    const [k, col] = c.split('.');
    const v = r.proposed[k];
    if (Array.isArray(v)) {
      if (!col) { if (!hasContent(state[k])) state[k] = JSON.parse(JSON.stringify(v)); return; }
      state[k] = state[k] && state[k].length ? state[k] : [{}];
      if (!String(state[k][0][col] ?? '').trim()) state[k][0][col] = v[0][col];
    } else if (!String(state[k] ?? '').trim()) state[k] = v;
  });
  render(); markDirty();
  chatSay('note', 'Applied to the draft. Check the highlighted fields, fill your details, then use Check quality.');
  if (window.matchMedia('(max-width: 860px)').matches) closeChat();     // on a phone, show the form and its flags
  checkQuality();
}
// ---------- feedback: engineers, technicians and lab reviewers tell the assistant what to ask and check ----------
// Stored on the local server (data/private/feedback/, append-only). It never changes the assistant by itself:
// a person reviews it on the Feedback page and turns accepted items into rules or procedure text.
const FB = { meta: null, role: null };
try { FB.role = localStorage.getItem('lrt_role'); } catch (_) { /* private window: ask each time */ }
async function fbMeta() {
  if (!FB.meta && HAVE_API) {
    const r = await fetch('/api/feedback/meta', { credentials: 'same-origin' }).catch(() => null);
    FB.meta = r && r.ok ? await r.json() : null;
  }
  return FB.meta;
}
const fbContext = j => ({ run_id: j?.run_id || '', version: CHAT.status?.version || '', model: CHAT.status?.model_label || '', mode: j?.mode || '' });
async function sendFeedback(body) {
  const r = await fetch('/api/feedback', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role: FB.role || 'other', form: formKey, ...body }) }).catch(() => null);
  const j = r ? await r.json().catch(() => ({})) : {};
  return r && r.ok ? { ok: true, ...j } : { ok: false, error: j.error || 'Could not reach the local server.' };
}
function rolePicker() {
  const sel = el('select', { class: 'fb-role', 'aria-label': 'Your role' }, el('option', { value: '', text: 'I am…' }),
    ['engineer', 'technician', 'lab reviewer', 'other'].map(r => el('option', { value: r, text: r[0].toUpperCase() + r.slice(1) })));
  sel.value = FB.role || '';
  sel.addEventListener('change', () => { FB.role = sel.value || null; try { localStorage.setItem('lrt_role', sel.value); } catch (_) {} });
  return sel;
}
// Useful / Not needed / Wrong on one item, with an optional comment. Shown only in feedback mode.
function rateRow(target, ctx) {
  const row = el('div', { class: 'rate' });
  const draw = () => row.replaceChildren(...Object.entries({ useful: 'Useful', not_needed: 'Not needed', wrong: 'Wrong' }).map(([k, label]) =>
    el('button', { type: 'button', onclick: () => pick(k, label) }, label)));
  const pick = (rating, label) => {
    if (!FB.role) { row.replaceChildren(el('span', { class: 'fb-hint', text: 'Pick your role first (I am…), then rate.' })); setTimeout(draw, 2200); return; }
    const note = el('input', { type: 'text', maxlength: 1000, placeholder: rating === 'useful' ? 'Comment (optional)' : 'Why? What should it say? (optional)' });
    const send = async () => {
      const r = await sendFeedback({ type: 'rating', rating, tests: ctx.tests || [], target, comment: note.value, context: fbContext(ctx.j) });
      row.replaceChildren(el('span', { class: r.ok ? 'fb-saved' : 'fb-hint', text: r.ok ? `✓ Saved: ${label}` + (r.screen?.length ? ' (stored as text only)' : '') : r.error }));
    };
    note.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); send(); } if (e.key === 'Escape') draw(); });
    row.replaceChildren(el('span', { class: 'fb-pick', text: label }), note,
      el('button', { type: 'button', class: 'fb-send', onclick: send }, 'Send'), el('button', { type: 'button', onclick: draw }, 'Cancel'));
    note.focus();
  };
  draw();
  return row;
}
// The bar under an answer (or the rule check): turns feedback mode on for that block.
function feedbackBar(group, ctx) {
  const extra = el('span', { class: 'fb-extra' }, rolePicker(),
    el('button', { type: 'button', class: 'btn-link', onclick: () => openSuggest(ctx) }, '+ Suggest a missing question or check'));
  const toggle = el('button', { type: 'button', class: 'btn-link fb-toggle', 'aria-expanded': 'false', onclick: () => {
    const on = group.classList.toggle('fb-on'); toggle.setAttribute('aria-expanded', String(on));
    toggle.textContent = on ? 'Done giving feedback' : 'Give feedback on this';
  } }, 'Give feedback on this');
  return el('div', { class: 'fb-bar' }, toggle, extra);
}
async function openSuggest(ctx) {
  const m = await fbMeta();
  if (!m) { chatSay('err', 'Feedback needs the local server (start.bat).'); return; }
  const d = $('suggestDlg'), f = $('suggestForm');
  f.reset(); $('sgMsg').textContent = '';
  $('sgRole').replaceChildren(...[['', 'Choose…'], ...m.roles.map(r => [r, r[0].toUpperCase() + r.slice(1)])].map(([v, t]) => el('option', { value: v, text: t })));
  $('sgRole').value = FB.role || '';
  $('sgTest').replaceChildren(...m.tests.map(t => el('option', { value: t.key, text: t.label[0].toUpperCase() + t.label.slice(1) })));
  $('sgTest').value = (ctx.tests || [])[0] || 'other';
  $('sgSource').replaceChildren(...m.sources.map(x => el('option', { value: x, text: x[0].toUpperCase() + x.slice(1) })));
  $('sgSource').value = 'lab experience';
  const other = () => { $('sgTestOtherWrap').hidden = $('sgTest').value !== 'other'; };
  $('sgTest').onchange = other; other();
  f.onsubmit = async e => {
    e.preventDefault();
    if (!$('sgRole').value) { $('sgMsg').textContent = 'Choose your role.'; return; }
    FB.role = $('sgRole').value; try { localStorage.setItem('lrt_role', FB.role); } catch (_) {}
    const r = await sendFeedback({ type: 'suggestion', role: FB.role, tests: ctx.tests || [], context: fbContext(ctx.j), comment: '',
      suggestion: { ask_or_check: f.querySelector('input[name=sgKind]:checked')?.value || 'ask', test: $('sgTest').value, test_other: $('sgTestOther').value,
        text: $('sgText').value, why: $('sgWhy').value, importance: f.querySelector('input[name=sgImp]:checked')?.value || 'should',
        example: $('sgExample').value, source: $('sgSource').value, source_ref: $('sgRef').value } });
    if (!r.ok) { $('sgMsg').textContent = r.error; return; }
    d.close();
    const note = 'Thanks: your suggestion was saved for review. It does not change the assistant until a person adds it to the rules or the procedure.';
    if (!$('chat').hidden) chatSay('note', note); else { $('status').textContent = 'Suggestion saved for review.'; }
  };
  d.showModal();
  $('sgText').focus();
}
// The assistant's answer, with each question and review point as its own item (so each can be rated).
function botMessage(j) {
  const ctx = { j, tests: j.tests };
  const rp = j.reply_parts, m = el('div', { class: 'msg bot' });
  const before = rp ? rp.before.slice() : j.reply.split('\n');
  const after = rp ? rp.after : [];
  if (j.review_points?.length) {
    m.append(el('div', { text: before.shift() }),
      el('ul', { class: 'by-list' }, j.review_points.map(p => el('li', {}, byBadge(p.by), p.text,
        rateRow({ kind: 'review_point', key: '', text: p.text, by: p.by }, ctx)))));
  }
  if (before.length) m.append(el('div', { text: before.join('\n') }));
  if (rp && j.questions?.length) {
    const must = j.questions.filter(q => q.blocking), nice = j.questions.filter(q => !q.blocking);
    const li = q => el('li', { title: 'From ' + q.source }, q.question, rateRow({ kind: 'question', key: q.key, text: q.question, by: 'rule' }, ctx));
    const head = t => el('div', { class: 'qhead' }, t, ' ', byBadge('rule'));
    if (must.length) m.append(head(rp.questions_head), el('ol', { class: 'qlist' }, must.map(li)));
    // Optional questions fold away when there are must-answer ones, so the reply is not a wall of questions.
    if (nice.length && must.length) m.append(el('details', { class: 'qmore' }, el('summary', { text: `Also useful (${nice.length})` }),
      el('ol', { class: 'qlist', start: must.length + 1 }, nice.map(li))));
    else if (nice.length) m.append(head(rp.questions_head), el('ol', { class: 'qlist' }, nice.map(li)));
  }
  if (after.length) m.append(el('div', { text: after.join('\n') }));
  if (j.choices?.length) {                      // one tap answers: which test, or add vs separate request
    const buttons = el('div', { class: 'choices' }, j.choices.map(c => el('button', { type: 'button', class: 'chip', onclick: async e => {
        e.target.closest('.choices').querySelectorAll('button').forEach(b => { b.disabled = true; });
        if (c.action === 'new_draft') {          // a separate request: save this draft, open a blank one, forget the earlier chat
          await newDraft(formKey); CHAT.history = [];
          chatSay('note', 'Started a new draft. The previous one is saved under My drafts.');
        }
        $('chatInput').value = c.send; fitChatInput(); sendChat({ preventDefault() {} });
      } }, c.label)));
    if (rp) m.append(buttons);                  // a full answer: the buttons go under it
    else m.replaceChildren(el('div', { text: j.reply.split('\n').filter(l => !/^\d+\. /.test(l)).join('\n') }), buttons);
  }
  return m;
}
async function sendChat(e) {
  e.preventDefault();
  const text = $('chatInput').value.trim();
  if (!text || CHAT.busy) return;
  CHAT.busy = true; $('chatSend').disabled = true; $('chatInput').value = ''; fitChatInput();
  chatSay('user', text);
  const t0 = Date.now();
  const wait = chatAdd(el('div', { class: 'thinking', text: 'Thinking…' }));
  const tick = setInterval(() => { wait.textContent = `Thinking… ${Math.round((Date.now() - t0) / 1000)} s (the local model can take a minute)`; }, 1000);
  try {
    const r = await fetch('/api/assistant', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, history: CHAT.history, form: formKey, fields: state, model: CHAT.model || undefined }) });
    const j = await r.json().catch(() => ({}));
    wait.remove();
    if (!r.ok) { chatSay('err', j.error || `The assistant did not answer (HTTP ${r.status}).`); return; }
    (j.warnings || []).forEach(w => chatSay('note', w));
    const group = el('div', { class: 'fb-group' });
    // The proposal card only when there is something to apply, cite or review (not when the test is still unclear).
    const useful = j.changes?.length || j.citations?.length || j.review_points?.length;
    group.append(...[botMessage(j), useful ? proposalCard(j) : null, feedbackBar(group, { j, tests: j.tests })].filter(Boolean));
    chatAdd(group);
    refreshAIStatus();
    CHAT.history.push({ role: 'user', content: text }, { role: 'assistant', content: [j.reply, ...(j.review_points || []).map(p => '- ' + p.text)].join('\n') });
  } catch (_) {
    wait.remove(); chatSay('err', 'Could not reach the local server. Is start.bat still running?');
  } finally {
    clearInterval(tick); CHAT.busy = false; fitChatInput(); $('chatInput').focus();
  }
}
$('askBtn').addEventListener('click', openChat);
$('sgCancel').addEventListener('click', () => $('suggestDlg').close());
// The message box grows with the text (up to its max-height), so there is no inner scrollbar for short messages.
function fitChatInput() { const t = $('chatInput'); t.style.height = 'auto'; t.style.height = Math.max(44, t.scrollHeight) + 'px';
  $('chatSend').disabled = CHAT.busy || !t.value.trim(); }
$('chatInput').addEventListener('input', fitChatInput);
function closeChat() { $('chat').hidden = true; document.body.classList.remove('chat-open'); }
$('chatClose').addEventListener('click', closeChat);
$('chatForm').addEventListener('submit', sendChat);
// Enter sends (like most chat apps); Shift+Enter adds a line. Not while an IME is composing text.
$('chatInput').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) sendChat(e); });

// ---------- wiring ----------
$('form').addEventListener('input', () => { markDirty(); updateTotals(); });
$('form').addEventListener('change', markDirty);
$('check').addEventListener('click', checkQuality);
$('export').addEventListener('click', exportJson);
$('openDrafts').addEventListener('click', openDrafts);
$('newDraft').addEventListener('click', async () => { $('draftsDlg').close(); await newDraft(formKey); });
$('closeDrafts').addEventListener('click', () => $('draftsDlg').close());
$('load').addEventListener('change', async e => {
  const f = e.target.files[0]; if (!f) return;
  try { importDraft(JSON.parse(await f.text()), `Imported ${f.name}. Check every field before you use it.`); $('draftsDlg').close(); }
  catch (_) { alert('That file is not a draft.'); }
});

(async () => {
  S = await getJSON(SCHEMA_URL);
  if (!S) { $('sections').textContent = 'Could not load the form schema. Start the page with  python gui/serve.py  and open it through that.'; return; }
  const priv = await getJSON(PRIVATE_LISTS_URL);               // real lists, only on the engineer's laptop
  if (priv?.shared_lists) {
    const L = priv.shared_lists;
    Object.assign(S.shared_lists, { bPCNumber: L.bpc_number, businessUnit: L.business_unit, mFGSite: L.mfg_site });
  }
  BRAND = await getJSON(BRANDING_URL);
  const dir = (await getJSON(S.parts_directory?.private)) || (await getJSON(S.parts_directory?.synthetic));
  PARTS = dir?.parts || [];
  const me = await fetch('/api/me', { credentials: 'same-origin' }).catch(() => null);
  if (me && (me.status === 200 || me.status === 401)) {
    HAVE_API = true; const j = await me.json().catch(() => ({})); USER = j.user || null; CAN_REGISTER = !!j.register;
  }
  await pushUnsynced();
  drawAccount();
  refreshAIStatus();                                            // show which AI model is serving, next to Ask the assistant
  setInterval(() => { if (document.visibilityState === 'visible') refreshAIStatus(); }, 60000);
  // ?draft=<relative path>: open a draft the assistant wrote (local paths only).
  const p = new URLSearchParams(location.search).get('draft');
  if (p && !/^[a-z]+:|^\/\//i.test(p)) { const d = await getJSON(p); if (d) return importDraft(d, 'Prefilled draft from the assistant. Check every field before you use it.'); }
  // Otherwise reopen the last draft (survives reloads, crashes and shutdowns).
  const last = lsLast();
  if (last && (last.user || null) === USER) { const d = await Store.get(last.id); if (d) return openDraft(d); }
  newDraft('lab_test_request');
})();
