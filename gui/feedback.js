// Feedback page: summary, filters, status changes and export of the feedback log (assistant/feedback.py).
// All text is set with textContent (never innerHTML): feedback is untrusted text from people.
'use strict';
const $ = id => document.getElementById(id);
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'text') n.textContent = v; else if (k.startsWith('on')) n.addEventListener(k.slice(2), v); else n.setAttribute(k, v);
  }
  kids.flat().forEach(k => k != null && n.append(k));
  return n;
};
const D = { items: [], summary: null, manage: false, meta: null };
const testLabel = k => (D.meta?.tests || []).find(t => t.key === k)?.label || k;
const BY = { ai: '✦ AI', rule: 'Rule', procedure: 'Procedure', parts: 'Parts list' };

async function load() {
  const [r, m] = await Promise.all([fetch('/api/feedback', { credentials: 'same-origin' }), fetch('/api/feedback/meta', { credentials: 'same-origin' })]).catch(() => [null, null]);
  if (!r || !r.ok) { $('list').replaceChildren(el('p', { class: 'empty', text: r && r.status === 401 ? 'Sign in on the Request forms page to see feedback from another device.' : 'Could not reach the local server (start.bat).' })); return; }
  const j = await r.json(); D.meta = m && m.ok ? await m.json() : null;
  Object.assign(D, { items: j.items, summary: j.summary, manage: j.can_manage });
  $('who').textContent = j.synthetic ? '' : D.manage ? 'You see all entries and can set their status.' : 'You see your own entries.';
  $('synBanner').hidden = !j.synthetic;
  if ($('fStatus').options.length === 1) {
    (D.meta?.statuses || []).forEach(s => $('fStatus').append(el('option', { value: s, text: s[0].toUpperCase() + s.slice(1) })));
    (D.meta?.tests || []).forEach(t => $('fTest').append(el('option', { value: t.key, text: t.label })));
  }
  draw();
}

function draw() {
  const s = D.summary;
  const stat = (n, label) => el('div', { class: 'stat' }, el('b', { text: String(n) }), el('span', { text: label }));
  $('stats').replaceChildren(stat(s.total, 'entries'), stat(D.items.filter(e => e.type === 'suggestion').length, 'suggestions'),
    stat(D.items.filter(e => e.type === 'rating').length, 'ratings'), ...Object.entries(s.by_status).map(([k, v]) => stat(v, k)),
    ...Object.entries(s.by_role).filter(([, v]) => v).map(([k, v]) => stat(v, 'from ' + k + (v === 1 ? '' : 's'))));
  const tests = Object.entries(s.by_test);
  $('byTest').replaceChildren(tests.length ? el('table', {}, el('thead', {}, el('tr', {}, ['Test', 'Suggestions', 'Useful', 'Not needed', 'Wrong'].map(h => el('th', { text: h })))),
    el('tbody', {}, tests.map(([t, c]) => el('tr', {}, el('td', { text: testLabel(t) }), ...['suggestions', 'useful', 'not_needed', 'wrong'].map(k => el('td', { class: 'n', text: String(c[k]) })))))) :
    el('p', { class: 'empty', text: 'No feedback yet.' }));
  $('wanted').replaceChildren(s.suggestions.length ? el('table', {}, el('thead', {}, el('tr', {}, ['Importance', 'Test', 'Ask or check', 'Status', 'From'].map(h => el('th', { text: h })))),
    el('tbody', {}, s.suggestions.map(w => el('tr', {}, el('td', {}, el('span', { class: 'tag ' + w.importance, text: w.importance })), el('td', { text: testLabel(w.test) }),
      el('td', { text: w.text }), el('td', { text: w.status }), el('td', { text: w.role })))) ) : el('p', { class: 'empty', text: 'No open suggestions.' }));
  $('worst').replaceChildren(s.worst_rated.length ? el('table', {}, el('thead', {}, el('tr', {}, ['What was rated', 'Kind', 'Useful', 'Not needed', 'Wrong'].map(h => el('th', { text: h })))),
    el('tbody', {}, s.worst_rated.map(w => el('tr', {}, el('td', {}, w.by ? el('span', { class: 'tag ' + w.by, text: BY[w.by] || w.by }) : null, w.text), el('td', { text: w.kind.replace('_', ' ') }),
      ...['useful', 'not_needed', 'wrong'].map(k => el('td', { class: 'n', text: String(w[k]) })))))) : el('p', { class: 'empty', text: 'Nothing rated Not needed or Wrong yet.' }));
  drawList();
}

function drawList() {
  const q = $('q').value.trim().toLowerCase(), ft = $('fType').value, fs = $('fStatus').value, fx = $('fTest').value;
  const items = D.items.filter(e => (!ft || e.type === ft) && (!fs || e.status === fs) && (!fx || (e.tests || []).includes(fx)) &&
    (!q || JSON.stringify(e).toLowerCase().includes(q))).slice().reverse();
  $('list').replaceChildren(...(items.length ? items.map(card) : [el('p', { class: 'empty', text: 'No entries match.' })]));
}

function card(e) {
  const c = el('div', { class: 'card' });
  c.append(el('span', { class: 'st ' + e.status, text: e.status }));
  const sg = e.suggestion, t = e.target;
  if (e.type === 'suggestion') {
    c.append(el('span', { class: 'tag suggestion', text: 'Suggestion' }), el('span', { class: 'tag ' + sg.importance, text: (D.meta?.importance || {})[sg.importance] || sg.importance }),
      el('h3', { text: `${sg.ask_or_check === 'check' ? 'Check' : sg.ask_or_check === 'both' ? 'Ask and check' : 'Ask'}: ${sg.text}` }),
      el('dl', { class: 'kv' }, ...[['Test', sg.test === 'other' ? (sg.test_other || 'other') : testLabel(sg.test)], ['Why', sg.why], ['Good answer', sg.example],
        ['Source', [sg.source, sg.source_ref].filter(Boolean).join(': ')], ['Comment', e.comment]].filter(([, v]) => v).flatMap(([k, v]) => [el('dt', { text: k }), el('dd', { text: v })])));
  } else {
    c.append(el('span', { class: 'tag ' + e.rating, text: (D.meta?.ratings || {})[e.rating] || e.rating }),
      t.by ? el('span', { class: 'tag ' + t.by, text: BY[t.by] || t.by }) : null, el('span', { class: 'meta', text: t.kind.replace('_', ' ') + (t.key ? ` (${t.key})` : '') }),
      el('h3', { text: t.text }), e.comment ? el('dl', { class: 'kv' }, el('dt', { text: 'Comment' }), el('dd', { text: e.comment })) : null);
  }
  if (e.screen?.length) c.append(el('div', { class: 'screen', text: 'Screened: ' + e.screen.join('; ') + '. Stored as text only; it is never given to the AI as an instruction.' }));
  const ctx = e.context || {};
  c.append(el('div', { class: 'meta', text: [e.time.replace('T', ' '), e.role, 'by ' + e.by, (e.tests || []).map(testLabel).join(', '), ctx.model && 'model: ' + ctx.model,
    ctx.version && 'tool ' + ctx.version, ctx.run_id && 'run ' + ctx.run_id].filter(Boolean).join(' · ') }));
  (e.history || []).forEach(h => c.append(el('div', { class: 'meta', text: `${h.time.replace('T', ' ')}: ${h.status} by ${h.by}${h.note ? ' (' + h.note + ')' : ''}` })));
  if (D.manage) {
    const sel = el('select', { 'aria-label': 'Status' }, (D.meta?.statuses || []).map(s => el('option', { value: s, text: s[0].toUpperCase() + s.slice(1) })));
    sel.value = e.status;
    const note = el('input', { type: 'text', maxlength: 500, placeholder: e.status === 'accepted' ? 'Where it went (e.g. SYN-TM-120, quality.py)' : 'Note (optional)', 'aria-label': 'Note' });
    const msg = el('span', { class: 'msg' });
    const save = el('button', { type: 'button', class: 'btn btn-quiet', onclick: async () => {
      const r = await fetch('/api/feedback/status', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: e.id, status: sel.value, note: note.value }) }).catch(() => null);
      const j = r ? await r.json().catch(() => ({})) : {};
      if (r && r.ok) { msg.className = 'msg ok'; msg.textContent = 'Saved'; setTimeout(load, 500); } else { msg.className = 'msg bad'; msg.textContent = j.error || 'Not saved'; }
    } }, 'Save status');
    c.append(el('div', { class: 'manage' }, sel, note, save, msg));
  }
  return c;
}

['q', 'fType', 'fStatus', 'fTest'].forEach(id => $(id).addEventListener('input', drawList));
$('json').addEventListener('click', () => {
  const a = el('a', { href: URL.createObjectURL(new Blob([JSON.stringify(D.items, null, 2)], { type: 'application/json' })),
    download: `lab_request_feedback_${new Date().toISOString().slice(0, 10)}.json` });
  a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});
load();
