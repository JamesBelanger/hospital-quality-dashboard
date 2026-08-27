// ui.js — shared UI primitives: tokens, tooltip, search box, SQL drawer, CSV export, URL state, small chart helpers.
import { D, fmtVal } from './data.js';

export const T = {
  surface: '#fcfcfb', page: '#f9f9f7', ink: '#0b0b0b', ink2: '#52514e', muted: '#898781', grid: '#e1e0d9', axis: '#c3c2b7',
  blue: '#2a78d6', deemph: '#c3c2b7', blueSoft: '#cde2fb',
  seq: ['#86b6ef', '#6da7ec', '#5598e7', '#3987e5', '#2a78d6', '#256abf', '#1c5cab', '#184f95', '#104281', '#0d366b'],
  font: 'system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'
};
export const seqScale = (domain) => d3.scaleQuantize().domain(domain).range(T.seq);
export const el = (tag, attrs = {}, children = []) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v; else if (k === 'html') e.innerHTML = v; else if (k === 'text') e.textContent = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v);
  }
  for (const c of [].concat(children)) if (c != null) e.append(c);
  return e;
};

// ---------------- tooltip ----------------
let tip;
export function tooltip() {
  if (!tip) { tip = el('div', { class: 'tip', role: 'tooltip' }); document.body.append(tip); }
  return {
    show(html, ev) { tip.innerHTML = html; tip.style.display = 'block'; this.move(ev); },
    move(ev) {
      const x = ev.clientX + 14, y = ev.clientY + 14, w = tip.offsetWidth, h = tip.offsetHeight;
      tip.style.left = (x + w > innerWidth - 8 ? ev.clientX - w - 10 : x) + 'px';
      tip.style.top = (y + h > innerHeight - 8 ? ev.clientY - h - 10 : y) + 'px';
    },
    hide() { tip.style.display = 'none'; }
  };
}
export const hospTip = (h, extra = '') => `<b>${h.name}</b><div class="tip-sub">${h.city ? h.city + ', ' : ''}${h.state}${h.county ? ' · ' + h.county + ' County' : ''}</div><div class="tip-sub">${h.type} · ${h.own}${h.stars ? ' · ' + h.stars + '★ overall' : ''}</div>${extra}`;

// ---------------- hospital search (combobox) ----------------
export function hospitalSearch(container, onPick, placeholder = 'Search any U.S. hospital, city, or CMS ID') {
  const input = el('input', { class: 'search', type: 'search', placeholder, autocomplete: 'off', 'aria-label': placeholder });
  const list = el('div', { class: 'search-list', role: 'listbox' });
  container.append(input, list);
  let items = [], cur = -1;
  const norm = s => (s || '').toLowerCase();
  const render = () => {
    list.innerHTML = '';
    items.forEach((h, k) => {
      const row = el('div', { class: 'search-item' + (k === cur ? ' cur' : ''), role: 'option',
        html: `<span>${h.name}</span><span class="search-meta">${h.city}, ${h.state} · ${h.id}</span>`, onmousedown: (e) => { e.preventDefault(); pick(h); } });
      list.append(row);
    });
    list.style.display = items.length ? 'block' : 'none';
  };
  const pick = (h) => { input.value = h.name; items = []; render(); onPick(h); };
  input.addEventListener('input', () => {
    const q = norm(input.value).trim(); cur = -1;
    if (q.length < 2) { items = []; render(); return; }
    const words = q.split(/\s+/);
    const scored = [];
    for (const h of D.H) {
      const hay = norm(h.name) + ' ' + norm(h.city) + ' ' + norm(h.state) + ' ' + h.id;
      if (words.every(w => hay.includes(w))) scored.push([norm(h.name).startsWith(q) ? 0 : norm(h.name).includes(q) ? 1 : 2, h]);
      if (scored.length > 400) break;
    }
    scored.sort((a, b) => a[0] - b[0] || a[1].name.localeCompare(b[1].name));
    items = scored.slice(0, 12).map(x => x[1]); render();
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { cur = Math.min(cur + 1, items.length - 1); render(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { cur = Math.max(cur - 1, 0); render(); e.preventDefault(); }
    else if (e.key === 'Enter' && items.length) { pick(items[Math.max(cur, 0)]); }
    else if (e.key === 'Escape') { items = []; render(); }
  });
  input.addEventListener('blur', () => setTimeout(() => { items = []; render(); }, 150));
  return { input, set: (h) => { input.value = h ? h.name : ''; } };
}

// ---------------- "show the SQL" drawer ----------------
let sqlCache;
export async function sqlSnippets() {
  if (!sqlCache) sqlCache = await fetch(new URL('../data/sql.json', import.meta.url)).then(r => r.json());
  return sqlCache;
}
/** Extract one statement (view or query) by a marker: {file:'views', view:'v_benchmarks'} or {file:'06_national_percentile'} */
export async function sqlFor(ref) {
  const all = await sqlSnippets();
  let txt = all[ref.file] || '';
  if (ref.view) {
    const m = txt.match(new RegExp(`(--[^\\n]*\\n)*CREATE OR REPLACE VIEW ${ref.view}[\\s\\S]*?;`));
    txt = m ? m[0] : txt;
  }
  return txt.trim();
}
export function sqlButton(ref, label = 'Show the SQL') {
  const wrap = el('div', { class: 'sqlwrap' });
  const btn = el('button', { class: 'btn-ghost', type: 'button', text: label });
  const drawer = el('div', { class: 'sqldrawer', style: 'display:none' });
  btn.addEventListener('click', async () => {
    if (drawer.style.display === 'none') {
      if (!drawer.hasChildNodes()) {
        const code = await sqlFor(ref);
        const pre = el('pre', { class: 'code' }, el('code', { text: code }));
        const copy = el('button', { class: 'btn-ghost small', type: 'button', text: 'Copy' , onclick: () => { navigator.clipboard?.writeText(code); copy.textContent = 'Copied'; setTimeout(() => copy.textContent = 'Copy', 1200); } });
        const meta = el('div', { class: 'sqlmeta' }, [el('span', { text: `PostgreSQL · ${ref.file}.sql${ref.view ? ' · ' + ref.view : ''}` }), copy]);
        drawer.append(meta, pre);
      }
      drawer.style.display = 'block'; btn.textContent = 'Hide the SQL';
    } else { drawer.style.display = 'none'; btn.textContent = label; }
  });
  wrap.append(btn, drawer);
  return wrap;
}

// ---------------- CSV export ----------------
export function downloadCSV(name, rows, cols) {
  const esc = v => v == null ? '' : /[",\n]/.test(String(v)) ? '"' + String(v).replace(/"/g, '""') + '"' : String(v);
  const lines = [cols.map(c => esc(c.label || c.key)).join(',')];
  for (const r of rows) lines.push(cols.map(c => esc(typeof c.get === 'function' ? c.get(r) : r[c.key])).join(','));
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
  const a = el('a', { href: URL.createObjectURL(blob), download: name }); document.body.append(a); a.click(); a.remove();
}

// ---------------- URL state (hash router) ----------------
export function readHash() {
  const h = location.hash.replace(/^#\/?/, '');
  const [path, qs] = h.split('?');
  const q = Object.fromEntries(new URLSearchParams(qs || ''));
  return { view: path || 'story', q };
}
export function writeHash(view, q = {}, replace = false) {
  const qs = new URLSearchParams(Object.entries(q).filter(([, v]) => v !== undefined && v !== null && v !== '')).toString();
  const h = '#/' + view + (qs ? '?' + qs : '');
  if (replace) history.replaceState(null, '', h); else if (location.hash !== h) history.pushState(null, '', h);
}

// ---------------- chart helpers ----------------
export function svgIn(container, width, height) {
  d3.select(container).selectAll('svg').remove();
  return d3.select(container).append('svg').attr('viewBox', `0 0 ${width} ${height}`).attr('width', '100%').attr('height', height)
    .style('font-family', T.font).style('font-size', '12px');
}
export function axisStyle(g) {
  g.selectAll('path,line').attr('stroke', T.axis); g.selectAll('text').attr('fill', T.muted).style('font-size', '11px');
  return g;
}
/** Histogram bins for a sorted array within [lo, hi]. */
export function bins(sorted, n = 40, lo, hi) {
  lo = lo ?? sorted[0]; hi = hi ?? sorted[sorted.length - 1];
  const w = (hi - lo) / n || 1, out = Array.from({ length: n }, (_, k) => ({ x0: lo + k * w, x1: lo + (k + 1) * w, n: 0 }));
  for (const v of sorted) { let k = Math.floor((v - lo) / w); if (k >= n) k = n - 1; if (k < 0) k = 0; out[k].n++; }
  return out;
}
export const nice = { valueOf: (m, x) => fmtVal(m, x) };
export function badge(frac) {
  if (Number.isNaN(frac)) return el('span', { class: 'badge na', text: 'n/a' });
  const p = frac * 100;
  const cls = p >= 75 ? 'good' : p >= 50 ? 'ok' : p >= 25 ? 'low' : 'poor';
  const txt = p > 99 || (p < 1 && p > 0) ? p.toFixed(1) : Math.round(p);
  return el('span', { class: 'badge ' + cls, text: `beats ${txt}%` });
}
export const debounce = (fn, ms = 120) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
