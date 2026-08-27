// console.js — "SQL": an in-browser SQL console. DuckDB compiled to WebAssembly runs the project's own
// tables (shipped as Parquet) and the same views/exercises that run against the PostgreSQL warehouse.
import { dataUrl } from './data.js';
import { T, el, sqlSnippets, downloadCSV } from './ui.js';
import { setQuery } from './main.js';

const DUCK = 'https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.32.0/+esm';
let root, editor, status, results, presetsEl, runBtn, db, conn, ready = false, initPromise = null, running = false, last = null, presets = [];

/** PostgreSQL → DuckDB: the dialects overlap almost entirely for this project; only the schema plumbing differs. */
export function toDuck(sql) {
  return sql.replace(/^\s*SET\s+search_path[^;]*;\s*$/gim, '').replace(/\bhq\./g, '').trim();
}
const statements = (sql) => sql.split(/;\s*\n/).map(s => s.trim()).filter(s => s && s.replace(/--[^\n]*/g, '').trim());

function mount(r) {
  root = r;
  root.append(el('p', { class: 'kicker', text: 'SQL' }));
  root.append(el('h1', { text: 'Run the queries yourself' }));
  root.append(el('p', { class: 'dek', text: 'The twelve analyses behind this project, runnable in your browser against the full 799,104-row fact table. Edit anything and press Ctrl+Enter.' }));
  const grid = el('div', { class: 'console' });
  presetsEl = el('div', { class: 'presets' }); grid.append(presetsEl);
  const right = el('div');
  editor = el('textarea', { class: 'editor', spellcheck: 'false', placeholder: 'SELECT … FROM measure_values …' });
  editor.addEventListener('keydown', (e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); run(); } });
  right.append(editor);
  const bar = el('div', { class: 'row', style: 'margin-top:8px' });
  runBtn = el('button', { class: 'btn primary', text: 'Run (Ctrl+Enter)', onclick: run });
  bar.append(runBtn, el('button', { class: 'btn-ghost', text: 'Download result (CSV)', onclick: () => last && downloadCSV('query_result.csv', last.rows, last.cols.map(c => ({ key: c }))) }));
  status = el('span', { class: 'status', style: 'margin-left:auto' }); bar.append(status);
  right.append(bar);
  results = el('div', { class: 'results', style: 'margin-top:10px;min-height:80px' }); right.append(results);
  right.append(el('p', { class: 'note', text: 'Runs entirely in your browser: DuckDB compiled to WebAssembly over the project’s Parquet tables (hospitals, measures, measure_values) plus the five views from the repository. The same SQL runs against the PostgreSQL warehouse; only the schema prefix differs.' }));
  grid.append(right); root.append(grid);
  buildPresets();
}

async function buildPresets() {
  const all = await sqlSnippets();
  const ex = Object.keys(all).filter(k => /^\d\d_/.test(k)).sort();
  const kinds = { '01': 'join + filter', '02': 'aggregate', '03': 'group by', '04': 'window: rank', '05': 'window: avg over', '06': 'window: percent_rank', '07': 'window: lag', '08': 'CTE composite', '09': 'CTE + cross join', '10': 'rollup', '11': 'conditional pivot', '12': 'share beating national' };
  presets = ex.map(k => { const raw = all[k]; const q = (raw.match(/--\s*Q:\s*([^\n]*)/) || [])[1] || k; return { key: k, title: q, sub: `${k.slice(0, 2)} · ${kinds[k.slice(0, 2)] || 'exercise'}`, sql: toDuck(raw) }; });
  presets.push(
    { key: 'schema_describe', group: 'Schema', title: 'Describe the fact table', sub: 'DESCRIBE', sql: 'DESCRIBE measure_values;' },
    { key: 'schema_domains', group: 'Schema', title: 'Rows per CMS domain', sub: 'GROUP BY', sql: 'SELECT domain, count(*) AS rows, count(DISTINCT measure_id) AS measures, count(DISTINCT facility_id) AS hospitals\nFROM measure_values GROUP BY 1 ORDER BY 2 DESC;' },
    { key: 'schema_houston', group: 'Schema', title: 'Houston-area hospitals', sub: 'WHERE', sql: 'SELECT facility_id, facility_name, city, county, hospital_ownership, overall_rating\nFROM hospitals WHERE is_houston_area ORDER BY facility_name LIMIT 20;' },
    ...['v_tx_latest', 'v_scorecard', 'v_benchmarks', 'v_hcahps', 'v_tx_vs_national'].map(v => ({ key: 'view_' + v, group: 'Views', title: v, sub: 'SELECT * … LIMIT 50', sql: `SELECT * FROM ${v} LIMIT 50;` })));
  presetsEl.innerHTML = '';
  let grp = 'Exercises';
  presetsEl.append(el('div', { style: 'font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);cursor:default', text: grp }));
  for (const p of presets) {
    if (p.group && p.group !== grp) { grp = p.group; presetsEl.append(el('div', { style: 'font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);cursor:default', text: grp })); }
    const d = el('div', { html: `${p.title}<small>${p.sub}</small>`, onclick: () => pick(p) }); p.el = d; presetsEl.append(d);
  }
}

function pick(p, auto = true) {
  presets.forEach(x => x.el?.classList.toggle('cur', x === p));
  editor.value = p.sql; setQuery({ p: p.key });
  if (auto) run();
}

function show(q) {
  if (!initPromise) initPromise = init();
  initPromise.then(() => { if (q.p) { const p = presets.find(x => x.key === q.p); if (p) pick(p); } else if (!editor.value && presets.length) pick(presets[5] || presets[0]); });
}

function setStatus(msg, err = false) { status.textContent = msg; status.className = 'status' + (err ? ' err' : ''); }

async function init() {
  const t0 = performance.now();
  try {
    setStatus('Loading DuckDB (≈ 6 MB WebAssembly)…');
    const duckdb = await import(DUCK);
    const bundle = await duckdb.selectBundle(duckdb.getJsDelivrBundles());
    const workerUrl = URL.createObjectURL(new Blob([`importScripts("${bundle.mainWorker}");`], { type: 'text/javascript' }));
    const worker = new Worker(workerUrl);
    db = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), worker);
    await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
    URL.revokeObjectURL(workerUrl);
    setStatus('Loading tables (2 MB Parquet)…');
    const names = ['hospitals', 'measures', 'measure_values'];
    const bufs = await Promise.all(names.map(n => fetch(dataUrl(`hq/${n}.parquet`)).then(r => { if (!r.ok) throw new Error(`${n}.parquet ${r.status}`); return r.arrayBuffer(); })));
    for (let k = 0; k < names.length; k++) await db.registerFileBuffer(`${names[k]}.parquet`, new Uint8Array(bufs[k]));
    conn = await db.connect();
    for (const n of names) await conn.query(`CREATE VIEW ${n} AS SELECT * FROM parquet_scan('${n}.parquet')`);
    const all = await sqlSnippets();
    const vt = all.schema.match(/CREATE OR REPLACE VIEW v_tx_latest[\s\S]*?;/);
    const views = [vt ? vt[0] : ''].concat(statements(toDuck(all.views)).filter(s => /CREATE/i.test(s)));
    for (const v of views) if (v.trim()) await conn.query(toDuck(v));
    const n = (await conn.query('SELECT count(*)::INTEGER AS n FROM measure_values')).toArray()[0].n;
    ready = true;
    setStatus(`Ready · ${Number(n).toLocaleString()} rows · hospitals, measures, measure_values + 5 views · ${((performance.now() - t0) / 1000).toFixed(1)} s`);
  } catch (e) {
    console.error(e);
    setStatus(`DuckDB could not start (${e.message}). The queries are still readable on the left; they run against PostgreSQL in the repository.`, true);
  }
}

function u32ToBig(a) { let b = 0n; for (let i = a.length - 1; i >= 0; i--) b = (b << 32n) + BigInt(a[i] >>> 0); if (b >= (1n << 127n)) b -= (1n << 128n); return b; }
function cell(v, f) {
  if (v === null || v === undefined) return { t: '∅', num: false, null: true, raw: null };
  const tn = String(f.type);
  if (typeof v === 'bigint') return { t: v.toLocaleString(), num: true, raw: Number(v) };
  if (v instanceof Uint32Array || v instanceof Int32Array) { const s = f.type.scale ?? 0; const n = Number(u32ToBig(v)) / 10 ** s; return { t: n.toLocaleString('en-US', { maximumFractionDigits: s }), num: true, raw: n }; }
  if (v instanceof Date) { const iso = v.toISOString(); return { t: /Date/.test(tn) ? iso.slice(0, 10) : iso.replace('T', ' ').slice(0, 19), num: false, raw: iso.slice(0, 10) }; }
  if (typeof v === 'number') {
    if (/Date/.test(tn)) { const iso = new Date(v).toISOString().slice(0, 10); return { t: iso, num: false, raw: iso }; }
    if (/Timestamp/.test(tn)) { const iso = new Date(v).toISOString().replace('T', ' ').slice(0, 19); return { t: iso, num: false, raw: iso }; }
    return { t: Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString('en-US', { maximumFractionDigits: 4 }), num: true, raw: v };
  }
  if (typeof v === 'boolean') return { t: v ? 'true' : 'false', num: false, raw: v };
  return { t: String(v), num: false, raw: String(v) };
}

async function run() {
  if (running) return;
  const sql = toDuck(editor.value); if (!sql) return;
  if (!ready) { if (!initPromise) initPromise = init(); await initPromise; if (!ready) return; }
  running = true; runBtn.disabled = true; setStatus('Running…');
  const t0 = performance.now();
  try {
    const sts = statements(sql);
    for (const s of sts.slice(0, -1)) await conn.query(s);
    const table = await conn.query(sts[sts.length - 1]);
    const fields = table.schema.fields, cols = fields.map(f => f.name);
    const rowsAll = table.toArray().map(r => { const o = r.toJSON(); return cols.map((c, k) => cell(o[c], fields[k])); });
    last = { cols, rows: rowsAll.map(r => Object.fromEntries(cols.map((c, k) => [c, r[k].raw]))) };
    renderResults(cols, rowsAll, fields);
    setStatus(`${rowsAll.length.toLocaleString()} row${rowsAll.length === 1 ? '' : 's'} · ${Math.round(performance.now() - t0)} ms`);
  } catch (e) {
    results.innerHTML = ''; setStatus(String(e.message || e).split('\n').slice(0, 3).join(' '), true);
  } finally { running = false; runBtn.disabled = false; }
}

function renderResults(cols, rows, fields) {
  results.innerHTML = '';
  const CAP = 500;
  const table = el('table');
  const thead = el('thead'); const tr = el('tr');
  cols.forEach((c, k) => tr.append(el('th', { html: `${c}<div style="font-weight:400;color:var(--muted);font-size:10.5px">${String(fields[k].type).replace(/<.*>/, '').toLowerCase()}</div>` })));
  thead.append(tr); table.append(thead);
  const tb = el('tbody');
  for (const r of rows.slice(0, CAP)) { const row = el('tr'); r.forEach(c => row.append(el('td', { class: c.num ? 'num' : '', text: c.t, style: c.null ? 'color:var(--muted)' : '' }))); tb.append(row); }
  table.append(tb); results.append(table);
  if (rows.length > CAP) results.append(el('p', { class: 'caption', style: 'padding:6px 10px', text: `Showing ${CAP} of ${rows.length.toLocaleString()} rows; the CSV download has all of them.` }));
  if (!rows.length) results.append(el('p', { class: 'caption', style: 'padding:10px', text: 'No rows returned.' }));
}

export default { name: 'sql', mount, show };
