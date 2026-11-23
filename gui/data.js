// Lab data page: equipment, test methods, parts directory, gaps, and a request-vs-equipment check.
// Reads and writes through gui/serve.py. Equipment records are the source of truth for which equipment
// runs which test; each test's equipment list is rebuilt from them before every save.
'use strict';

const BRANDING_URL = '../data/private/branding/branding.json';
const AREAS = ['mechanical', 'electrical', 'environmental', 'analytical', 'solderability', 'metrology', 'process'];
const LIMIT_HINTS = ['temp_min_c', 'temp_max_c', 'cold_zone_c', 'hot_zone_c', 'rh_min_pct', 'rh_max_pct', 'ramp_max_c_per_min', 'load_cell_capacity_max_n',
  'current_max_a', 'voltage_max_kv', 'frequency_max_hz', 'sine_accel_max_gpk', 'random_accel_max_grms', 'channels', 'working_volume_ft3', 'sample_max_mm'];

let USER = null, ADMIN = false, SETS = {}, which = { equipment: null, parts: null }, EQ = null, PARTS = null, view = 'equipment';
const filt = { q: '', area: '', status: '' };

const $ = id => document.getElementById(id);
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v; else if (k === 'text') e.textContent = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v); else if (v !== undefined && v !== false && v !== null) e.setAttribute(k, v);
  }
  kids.flat().forEach(c => c != null && e.append(c));
  return e;
};
const getJSON = async url => { try { const r = await fetch(url, { credentials: 'same-origin' }); return r.ok ? await r.json() : null; } catch (_) { return null; } };
const norm = s => String(s ?? '').toLowerCase();
const lines = s => String(s || '').split('\n').map(x => x.trim()).filter(Boolean);
const setLabel = s => s === 'private' ? 'Real lab data (private)' : 'Synthetic demo data';

// ---------- formatting ----------
function limitText(k, v) {
  const unit = k.endsWith('_c') ? ' °C' : k.endsWith('_n') ? ' N' : k.endsWith('_a') ? ' A' : k.endsWith('_kv') ? ' kV' : k.endsWith('_hz') ? ' Hz'
    : k.endsWith('_gpk') ? ' gpk' : k.endsWith('_grms') ? ' grms' : k.endsWith('_ft3') ? ' ft³' : k.endsWith('_mm') ? ' mm' : k.endsWith('_pct') ? ' %'
    : k.endsWith('_mv') ? ' mV' : k.endsWith('_ma') ? ' mA' : k.endsWith('_um') ? ' µm' : '';
  const name = k.replace(/_(c|n|a|kv|hz|gpk|grms|ft3|mm|pct|mv|ma|um|in|in_s)$/, '').replace(/_/g, ' ');
  const val = Array.isArray(v) ? v.join(' to ') : (v && typeof v === 'object') ? Object.entries(v).map(([a, b]) => `${a} ${b}`).join(', ') : v;
  return val === null || val === undefined ? null : `${name}: ${val}${Array.isArray(v) || typeof v !== 'object' ? unit : ''}`;
}

// ---------- shell ----------
function drawLogos(brand) {
  const w = $('logoWrap'); w.replaceChildren();
  if (!brand) return;
  const base = BRANDING_URL.replace(/[^/]+$/, '');
  if (brand.company) w.append(el('img', { src: base + brand.company.logo, alt: brand.company.name }));
  if (brand.department) w.append(el('span', { class: 'sep' }), el('img', { class: 'dept', src: base + brand.department.logo, alt: brand.department.name }),
    el('span', { class: 'dept-name' }, ...brand.department.name.split(' ').flatMap((x, i) => i ? [el('br'), x] : [x])));
}
function drawNav() {
  const gapsN = EQ ? EQ.equipment.reduce((a, e) => a + (e.unknown?.length || 0), 0) : 0;
  const items = [['equipment', 'Equipment', EQ?.equipment.length], ['tests', 'Test methods', EQ?.test_methods.length],
    ['parts', 'Parts directory', PARTS?.parts.length], ['gaps', 'Gaps to fill', gapsN], ['check', 'Check a request', '']];
  $('nav').replaceChildren(...items.map(([k, label, n]) => el('li', {}, el('button', { type: 'button', 'aria-current': String(view === k),
    onclick: () => { view = k; draw(); } }, el('span', { text: label }), el('span', { class: 'count', text: n ?? '' })))));
  const sel = $('dataset');
  const opts = ['private', 'synthetic'].filter(s => SETS.equipment?.[s] || SETS.parts?.[s]);
  sel.replaceChildren(...opts.map(s => el('option', { value: s, text: setLabel(s) })));
  sel.value = which.equipment || opts[0];
  $('who').replaceChildren(...(ADMIN ? [`Signed in as ${USER} (admin): you can edit.`]
    : USER ? [`Signed in as ${USER}: read only. Editing lab data needs an admin account.`]
    : ['Read only. ', el('a', { href: 'request_form.html' }, 'Sign in on the Request forms page'), ' to edit (admins only).']));
}
function draw() {
  drawNav();
  const m = $('main'); m.replaceChildren();
  if (!EQ && view !== 'parts') { m.append(el('p', { text: 'No equipment database found. Start the page with python gui/serve.py.' })); return; }
  ({ equipment: drawEquipment, tests: drawTests, parts: drawParts, gaps: drawGaps, check: drawCheck })[view](m);
}

// ---------- saving ----------
function syncTests(db = EQ) {   // rebuild test -> equipment links from the equipment records
  for (const t of db.test_methods) t.equipment = db.equipment.filter(e => (e.tests || []).includes(t.id)).map(e => e.id);
}
async function save(name, data, msgEl) {
  if (!ADMIN) { msgEl.className = 'msg bad'; msgEl.textContent = USER ? 'Only admins edit lab data.' : 'Sign in on the Request forms page to edit.'; return false; }
  if (name === 'equipment') syncTests(data);
  const r = await fetch(`/api/data/${name}?set=${which[name]}`, { method: 'PUT', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }).catch(() => null);
  const j = r ? await r.json().catch(() => ({})) : { error: 'The local server is not running.' };
  if (!r || !r.ok) { msgEl.className = 'msg bad'; msgEl.textContent = [j.error, ...(j.problems || [])].filter(Boolean).join(' · '); return false; }
  return true;
}
let PARTS_SEEDED = false;
async function reload() {
  const e = await getJSON(`/api/data/equipment?set=${which.equipment}`); EQ = e?.data || null;
  which.parts = which.equipment;
  const p = await getJSON(`/api/data/parts?set=${which.parts}`);
  PARTS_SEEDED = !p && which.parts === 'private';
  // No private parts directory yet: start from the synthetic sample; the first save creates the private one.
  PARTS = p?.data || (await getJSON('/api/data/parts?set=synthetic'))?.data || { parts: [], fields: [] };
  if (PARTS_SEEDED) PARTS = { ...PARTS, _about: 'PRIVATE (gitignored) parts directory. Started from the synthetic sample; replace the sample parts with real ones.' };
}

// ---------- equipment ----------
function drawEquipment(m) {
  m.append(el('h2', { text: 'Equipment' }),
    el('p', { class: 'lead', text: `${EQ.lab?.name || 'Lab'}${EQ.lab?.accreditation ? ' · ' + EQ.lab.accreditation : ''}. ${EQ.equipment.length} records, ${EQ.equipment.reduce((a, e) => a + (e.count || 0), 0)} units.` }));
  const q = el('input', { type: 'search', placeholder: 'Search name, model, capability or standard', value: filt.q, 'aria-label': 'Search equipment' });
  const area = el('select', { 'aria-label': 'Area' }, el('option', { value: '', text: 'All areas' }), AREAS.map(a => el('option', { value: a, text: a })));
  const status = el('select', { 'aria-label': 'Status' }, el('option', { value: '', text: 'Any status' }), el('option', { value: 'available', text: 'Available' }), el('option', { value: 'other', text: 'Planned or not available' }));
  area.value = filt.area; status.value = filt.status;
  const list = el('div', { class: 'cards' });
  const redraw = () => {
    filt.q = q.value; filt.area = area.value; filt.status = status.value;
    const words = norm(q.value).split(/\s+/).filter(Boolean);
    const rows = EQ.equipment.filter(e => (!filt.area || e.area === filt.area) && (!filt.status || (filt.status === 'available') === (e.status === 'available'))
      && words.every(w => norm([e.id, e.name, e.model, ...(e.capabilities || []), ...(e.standards || [])].join(' ')).includes(w)));
    list.replaceChildren(...rows.map(equipmentCard));
    if (!rows.length) list.append(el('p', { class: 'meta', text: 'Nothing matches.' }));
  };
  q.addEventListener('input', redraw); area.addEventListener('change', redraw); status.addEventListener('change', redraw);
  m.append(el('div', { class: 'toolbar' }, q, area, status, el('button', { class: 'btn btn-primary', type: 'button', onclick: () => editEquipment(null) }, '+ Add')), list);
  redraw();
}
function equipmentCard(e) {
  const lim = Object.entries(e.limits || {}).map(([k, v]) => limitText(k, v)).filter(Boolean);
  const tests = (e.tests || []).map(t => EQ.test_methods.find(x => x.id === t)?.name || t);
  return el('div', { class: 'card' },
    el('h3', { text: e.name }),
    el('div', { class: 'meta', text: `${e.id} · ${e.area} · ${e.count ?? '?'} unit${e.count === 1 ? '' : 's'}${e.model ? ' · ' + e.model : ''}` }),
    el('div', { class: 'chips' }, e.status !== 'available' ? el('span', { class: 'chip plan', text: e.status }) : null,
      tests.map(t => el('span', { class: 'chip', text: t }))),
    lim.length ? el('div', { class: 'meta', text: lim.join(' · ') }) : null,
    e.unknown?.length ? el('div', { class: 'chips' }, el('span', { class: 'chip warn', text: `${e.unknown.length} unknown: ${e.unknown.join(', ')}` })) : null,
    el('div', { class: 'actions' }, el('button', { class: 'btn btn-quiet', type: 'button', onclick: () => editEquipment(e) }, 'Edit'),
      el('button', { class: 'btn btn-quiet', type: 'button', onclick: () => { view = 'check'; checkPick = e.id; draw(); } }, 'Check')));
}
function field(label, ctl, wide) { return el('div', { class: 'field' + (wide ? ' wide' : '') }, el('label', { text: label }), ctl); }
function editEquipment(e) {
  const isNew = !e;
  const r = e ? structuredClone(e) : { id: '', name: '', area: 'mechanical', count: 1, model: null, status: 'available', tests: [], standards: [], capabilities: [], limits: {}, unknown: [], source: '' };
  const id = el('input', { value: r.id, placeholder: 'AREA-SHORT-NAME' }), name = el('input', { value: r.name });
  const area = el('select', {}, AREAS.map(a => el('option', { value: a, text: a }))); area.value = r.area;
  const count = el('input', { type: 'number', min: 0, value: r.count ?? '' }), model = el('input', { value: r.model || '' });
  const status = el('input', { value: r.status, list: 'statusList' });
  const stds = el('textarea', {}), caps = el('textarea', {}), unk = el('textarea', {}), notes = el('textarea', {}), source = el('input', { value: r.source || '' });
  stds.value = (r.standards || []).join('\n'); caps.value = (r.capabilities || []).join('\n'); unk.value = (r.unknown || []).join('\n'); notes.value = r.notes || '';
  const checks = el('div', { class: 'checks' }, EQ.test_methods.map(t => el('label', {}, el('input', { type: 'checkbox', value: t.id, checked: (r.tests || []).includes(t.id) }), `${t.id} ${t.name}`)));
  const kv = el('div', { class: 'kv' });
  const kvRow = (k = '', v = '') => {
    const kk = el('input', { value: k, list: 'limitKeys', placeholder: 'limit name, e.g. temp_max_c' });
    const vv = el('input', { value: typeof v === 'object' ? JSON.stringify(v) : v, placeholder: 'number, [min, max] or text' });
    const rm = el('button', { type: 'button', class: 'btn btn-danger', text: '×', 'aria-label': 'Remove limit' });
    rm.addEventListener('click', () => { kk.remove(); vv.remove(); rm.remove(); });
    kv.append(kk, vv, rm);
  };
  Object.entries(r.limits || {}).forEach(([k, v]) => kvRow(k, v));
  const msg = el('div', { class: 'msg' });
  const parseVal = v => { const t = v.trim(); if (t === '') return null; try { return JSON.parse(t); } catch (_) { return t; } };
  const body = el('div', { class: 'form' },
    el('h3', { text: isNew ? 'Add equipment' : `Edit ${r.id}` }),
    el('datalist', { id: 'statusList' }, ['available', 'out of service', 'calibration due', 'planned 2026'].map(s => el('option', { value: s }))),
    el('datalist', { id: 'limitKeys' }, LIMIT_HINTS.map(s => el('option', { value: s }))),
    el('div', { class: 'grid2' }, field('ID', id), field('Name', name), field('Area', area), field('Count', count), field('Model', model), field('Status', status),
      field('Tests it runs', checks, true), field('Standards (one per line)', stds), field('Capabilities (one per line)', caps),
      field('Limits', el('div', {}, kv, el('button', { type: 'button', class: 'btn btn-quiet', style: 'margin-top:6px', onclick: () => kvRow() }, '+ Limit')), true),
      field('Still unknown (one per line)', unk), field('Notes', notes), field('Source', source, true)),
    msg,
    el('div', { class: 'dlg-actions' },
      el('button', { type: 'button', class: 'btn btn-primary', onclick: async () => {
        const limits = {}; const ins = [...kv.querySelectorAll('input')];
        for (let i = 0; i < ins.length; i += 2) if (ins[i].value.trim()) limits[ins[i].value.trim()] = parseVal(ins[i + 1].value);
        const rec = { ...r, id: id.value.trim(), name: name.value.trim(), area: area.value, count: count.value === '' ? null : Number(count.value),
          model: model.value.trim() || null, status: status.value.trim() || 'available', tests: [...checks.querySelectorAll('input:checked')].map(x => x.value),
          standards: lines(stds.value), capabilities: lines(caps.value), limits, unknown: lines(unk.value), source: source.value.trim() };
        if (notes.value.trim()) rec.notes = notes.value.trim(); else delete rec.notes;
        if (!rec.id || !rec.name) { msg.className = 'msg bad'; msg.textContent = 'ID and name are required.'; return; }
        const next = structuredClone(EQ);
        const i = isNew ? -1 : next.equipment.findIndex(x => x.id === r.id);
        if (isNew) next.equipment.push(rec); else next.equipment[i] = rec;
        if (!isNew && rec.id !== r.id) next.test_methods.forEach(t => { t.equipment = t.equipment.map(x => x === r.id ? rec.id : x); });
        if (await save('equipment', next, msg)) { EQ = next; syncTests(); $('editor').close(); draw(); }
      } }, 'Save'),
      !isNew ? el('button', { type: 'button', class: 'btn btn-danger', onclick: async ev => {
        if (!ev.target.dataset.armed) { ev.target.dataset.armed = 1; ev.target.textContent = 'Delete? Click again'; return; }
        const next = structuredClone(EQ); next.equipment = next.equipment.filter(x => x.id !== r.id);
        if (await save('equipment', next, msg)) { EQ = next; syncTests(); $('editor').close(); draw(); }
      } }, 'Delete') : null,
      el('button', { type: 'button', class: 'btn btn-quiet', onclick: () => $('editor').close() }, 'Cancel')));
  $('editorBody').replaceChildren(body); $('editor').showModal();
}

// ---------- test methods ----------
function drawTests(m) {
  m.append(el('h2', { text: 'Test methods' }), el('p', { class: 'lead', text: 'The tests the lab offers, their standards, and the equipment that runs each one. Which equipment runs a test is set on the equipment record.' }));
  const q = el('input', { type: 'search', placeholder: 'Search test or standard', 'aria-label': 'Search tests' });
  const list = el('div', { class: 'cards' });
  const redraw = () => {
    const words = norm(q.value).split(/\s+/).filter(Boolean);
    const rows = EQ.test_methods.filter(t => words.every(w => norm([t.id, t.name, t.group, ...t.standards].join(' ')).includes(w)));
    list.replaceChildren(...rows.map(t => el('div', { class: 'card' },
      el('h3', { text: t.name }), el('div', { class: 'meta', text: `${t.id} · ${t.group}${t.accredited ? ' · accredited' : ''}` }),
      el('div', { class: 'meta', text: t.standards.join('; ') }),
      t.check ? el('div', { class: 'chips' }, el('span', { class: 'chip warn', text: t.check })) : null,
      el('div', { class: 'chips' }, t.equipment.length ? t.equipment.map(id => el('button', { type: 'button', class: 'chip', text: EQ.equipment.find(e => e.id === id)?.name || id,
        onclick: () => editEquipment(EQ.equipment.find(e => e.id === id)) })) : el('span', { class: 'chip warn', text: 'No equipment linked' })),
      el('div', { class: 'actions' }, el('button', { class: 'btn btn-quiet', type: 'button', onclick: () => editTest(t) }, 'Edit')))));
  };
  q.addEventListener('input', redraw);
  m.append(el('div', { class: 'toolbar' }, q, el('button', { class: 'btn btn-primary', type: 'button', onclick: () => editTest(null) }, '+ Add')), list);
  redraw();
}
function editTest(t) {
  const isNew = !t;
  const r = t ? structuredClone(t) : { id: 'T' + String(EQ.test_methods.length + 1).padStart(2, '0'), name: '', group: '', standards: [], accredited: false, equipment: [] };
  const id = el('input', { value: r.id }), name = el('input', { value: r.name }), group = el('input', { value: r.group });
  const acc = el('input', { type: 'checkbox', checked: r.accredited }), stds = el('textarea', {}); stds.value = r.standards.join('\n');
  const checks = el('div', { class: 'checks' }, EQ.equipment.map(e => el('label', {}, el('input', { type: 'checkbox', value: e.id, checked: r.equipment.includes(e.id) }), `${e.id} ${e.name}`)));
  const msg = el('div', { class: 'msg' });
  $('editorBody').replaceChildren(el('div', { class: 'form' }, el('h3', { text: isNew ? 'Add test method' : `Edit ${r.id}` }),
    el('div', { class: 'grid2' }, field('ID', id), field('Name', name), field('Group', group), field('Accredited', el('label', {}, acc, ' on the lab scope')),
      field('Standards (one per line)', stds, true), field('Equipment that runs it', checks, true)), msg,
    el('div', { class: 'dlg-actions' }, el('button', { type: 'button', class: 'btn btn-primary', onclick: async () => {
      const rec = { ...r, id: id.value.trim(), name: name.value.trim(), group: group.value.trim(), accredited: acc.checked, standards: lines(stds.value) };
      if (!rec.id || !rec.name) { msg.className = 'msg bad'; msg.textContent = 'ID and name are required.'; return; }
      const chosen = new Set([...checks.querySelectorAll('input:checked')].map(x => x.value));
      const next = structuredClone(EQ);
      if (isNew) next.test_methods.push(rec); else next.test_methods[next.test_methods.findIndex(x => x.id === r.id)] = rec;
      next.equipment.forEach(e => {     // write the links onto the equipment records
        const has = new Set((e.tests || []).filter(x => x !== r.id));
        if (chosen.has(e.id)) has.add(rec.id);
        e.tests = [...has];
      });
      if (await save('equipment', next, msg)) { EQ = next; $('editor').close(); draw(); }
    } }, 'Save'), el('button', { type: 'button', class: 'btn btn-quiet', onclick: () => $('editor').close() }, 'Cancel'))));
  $('editor').showModal();
}

// ---------- parts ----------
function drawParts(m) {
  const fields = PARTS.fields?.length ? PARTS.fields : ['part_number', 'rev', 'product_name', 'description', 'status'];
  m.append(el('h2', { text: 'Parts directory' }), el('p', { class: 'lead', text: `${PARTS.parts.length} parts. The request forms suggest these when you type a part number, and fill the item's other fields.` }));
  if (PARTS_SEEDED) m.append(el('div', { class: 'readonly-note', text: 'There is no real parts directory yet, so this shows the synthetic sample. Your first save creates the private one (data/private/parts/parts.json); the sample is not changed.' }));
  const q = el('input', { type: 'search', placeholder: 'Search part number, name or material', 'aria-label': 'Search parts' });
  const list = el('div', { class: 'cards' });
  const redraw = () => {
    const words = norm(q.value).split(/\s+/).filter(Boolean);
    const rows = PARTS.parts.filter(p => words.every(w => norm(Object.values(p).join(' ')).includes(w)));
    list.replaceChildren(...rows.map(p => el('div', { class: 'card' },
      el('h3', { text: `${p.part_number} Rev ${p.rev ?? ''}` }), el('div', { text: p.product_name || p.description || '' }),
      el('div', { class: 'meta', text: fields.filter(f => !['part_number', 'rev', 'product_name', 'status'].includes(f) && p[f]).map(f => `${f.replace(/_/g, ' ')}: ${p[f]}`).join(' · ') }),
      p.status && p.status !== 'active' ? el('div', { class: 'chips' }, el('span', { class: 'chip warn', text: p.status })) : null,
      el('div', { class: 'actions' }, el('button', { class: 'btn btn-quiet', type: 'button', onclick: () => editPart(p, fields) }, 'Edit')))));
    if (!rows.length) list.append(el('p', { class: 'meta', text: 'Nothing matches.' }));
  };
  q.addEventListener('input', redraw);
  m.append(el('div', { class: 'toolbar' }, q, el('button', { class: 'btn btn-primary', type: 'button', onclick: () => editPart(null, fields) }, '+ Add')), list);
  redraw();
}
function editPart(p, fields) {
  const isNew = !p;
  const r = p ? { ...p } : { status: 'active' };
  const ins = Object.fromEntries(fields.map(f => [f, f === 'status' ? el('select', {}, ['active', 'obsolete', 'prototype'].map(s => el('option', { value: s, text: s }))) : el('input', { value: r[f] ?? '' })]));
  if (ins.status) ins.status.value = r.status || 'active';
  const msg = el('div', { class: 'msg' });
  $('editorBody').replaceChildren(el('div', { class: 'form' }, el('h3', { text: isNew ? 'Add part' : `Edit ${r.part_number}` }),
    el('div', { class: 'grid2' }, fields.map(f => field(f.replace(/_/g, ' '), ins[f]))), msg,
    el('div', { class: 'dlg-actions' },
      el('button', { type: 'button', class: 'btn btn-primary', onclick: async () => {
        const rec = Object.fromEntries(fields.map(f => [f, ins[f].value.trim()]));
        const next = structuredClone(PARTS);
        if (isNew) next.parts.push(rec); else next.parts[PARTS.parts.indexOf(p)] = rec;
        if (await save('parts', next, msg)) { PARTS = next; $('editor').close(); draw(); }
      } }, 'Save'),
      !isNew ? el('button', { type: 'button', class: 'btn btn-danger', onclick: async ev => {
        if (!ev.target.dataset.armed) { ev.target.dataset.armed = 1; ev.target.textContent = 'Delete? Click again'; return; }
        const next = structuredClone(PARTS); next.parts.splice(PARTS.parts.indexOf(p), 1);
        if (await save('parts', next, msg)) { PARTS = next; $('editor').close(); draw(); }
      } }, 'Delete') : null,
      el('button', { type: 'button', class: 'btn btn-quiet', onclick: () => $('editor').close() }, 'Cancel'))));
  $('editor').showModal();
}

// ---------- gaps ----------
function drawGaps(m) {
  const rows = EQ.equipment.filter(e => e.unknown?.length);
  m.append(el('h2', { text: 'Gaps to fill' }), el('p', { class: 'lead', text: `${rows.reduce((a, e) => a + e.unknown.length, 0)} values on ${rows.length} records are not known yet. Until they are filled, a check that needs them answers "unknown" and the assistant asks the lab.` }));
  AREAS.forEach(a => {
    const g = rows.filter(e => e.area === a);
    if (!g.length) return;
    m.append(el('div', { class: 'gap-group' }, el('h3', { text: a[0].toUpperCase() + a.slice(1) }),
      el('ul', {}, g.map(e => el('li', {}, el('button', { type: 'button', class: 'chip', onclick: () => editEquipment(e) }, e.id), ' ', e.name, ': ', el('span', { class: 'meta', text: e.unknown.join(', ') }))))));
  });
}

// ---------- check a request ----------
let checkPick = '';
function drawCheck(m) {
  m.append(el('h2', { text: 'Check a request' }), el('p', { class: 'lead', text: 'Find the equipment for a test, then check the conditions you want against its limits. The assistant runs the same check.' }));
  const q = el('input', { type: 'search', placeholder: 'Test name or standard, e.g. thermal shock or EIA 364-70', 'aria-label': 'Find equipment' });
  const found = el('div', { class: 'chips', style: 'margin:8px 0 16px' });
  const pick = el('select', { 'aria-label': 'Equipment' }, el('option', { value: '', text: '-- Choose equipment --' }), EQ.equipment.map(e => el('option', { value: e.id, text: `${e.id} · ${e.name}` })));
  pick.value = checkPick;
  const num = (lbl, key) => { const i = el('input', { type: 'number', step: 'any', 'data-key': key, placeholder: lbl }); return field(lbl, i); };
  const form = el('div', { class: 'grid2 form' }, num('Temperature min (°C)', 'temp_min_c'), num('Temperature max (°C)', 'temp_max_c'), num('Force (N)', 'force_n'),
    num('Current (A)', 'current_a'), num('Voltage (kV)', 'voltage_kv'), num('Frequency (Hz)', 'frequency_hz'));
  const out = el('div');
  q.addEventListener('change', async () => {
    const r = await getJSON(`/api/equipment/find?set=${which.equipment}&q=${encodeURIComponent(q.value)}`);
    found.replaceChildren(...(r?.equipment || []).map(e => el('button', { type: 'button', class: 'chip' + (e.status !== 'available' ? ' plan' : ''), text: `${e.name}${e.status !== 'available' ? ' (' + e.status + ')' : ''}`, onclick: () => { pick.value = e.id; checkPick = e.id; } })),
      ...(r?.test_methods || []).map(t => el('span', { class: 'chip', text: `${t.id} ${t.name}: ${t.standards.join('; ')}` })));
    if (r && !r.equipment.length && !r.test_methods.length) found.replaceChildren(el('span', { class: 'chip warn', text: r.note || 'No match' }));
  });
  const run = el('button', { type: 'button', class: 'btn btn-primary', onclick: async () => {
    if (!pick.value) { out.replaceChildren(el('p', { class: 'msg bad', text: 'Choose the equipment first.' })); return; }
    checkPick = pick.value;
    const qs = new URLSearchParams({ set: which.equipment, id: pick.value });
    form.querySelectorAll('input').forEach(i => { if (i.value !== '') qs.set(i.dataset.key, i.value); });
    const r = await getJSON('/api/equipment/check?' + qs);
    if (!r || r.error) { out.replaceChildren(el('p', { class: 'msg bad', text: r?.error || 'Check failed.' })); return; }
    out.replaceChildren(el('div', { class: 'result ' + (r.fits ? 'fit' : 'nofit') },
      el('h3', { text: r.fits ? `Fits: ${r.name}` : (r.problems.length ? `Does not fit: ${r.name}` : `Cannot confirm: ${r.name}`) }),
      el('div', { class: 'meta', text: `Status ${r.status} · ${r.count ?? '?'} unit(s)` }),
      r.problems.length ? el('ul', {}, r.problems.map(x => el('li', { text: x }))) : null,
      r.unknown.length ? el('div', {}, el('div', { class: 'label', text: 'Not in the database (ask the lab):' }), el('ul', {}, r.unknown.map(x => el('li', { text: x })))) : null,
      r.ok.length ? el('div', { class: 'meta', text: r.ok.join(' · ') }) : null,
      !r.problems.length && !r.unknown.length && !r.ok.length ? el('p', { class: 'meta', text: 'Enter at least one condition to check.' }) : null));
  } }, 'Check');
  m.append(el('div', { class: 'toolbar' }, q), found, el('div', { class: 'toolbar' }, pick), form, el('div', { class: 'dlg-actions' }, run), out);
}

// ---------- start ----------
$('dataset').addEventListener('change', async e => { which.equipment = e.target.value; await reload(); draw(); });
(async () => {
  drawLogos(await getJSON(BRANDING_URL));
  const me = await (await fetch('/api/me', { credentials: 'same-origin' }).catch(() => null))?.json().catch(() => null);
  USER = me?.user || null; ADMIN = !!me?.admin;
  SETS = (await getJSON('/api/data')) || {};
  which.equipment = SETS.equipment?.default || 'synthetic';
  await reload();
  draw();
})();
