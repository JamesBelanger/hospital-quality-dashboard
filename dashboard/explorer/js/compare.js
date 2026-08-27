// compare.js — "Compare": linked views over the peer group. Brush a distribution → the table and heatmap follow; hover a row → the dot lights up.
import { D, seriesFor, sortedIn, median, mean, betterThan, fmtVal, scopeLabel } from './data.js';
import { T, el, tooltip, hospTip, sqlButton, downloadCSV, svgIn, axisStyle, bins, seqScale } from './ui.js';
import { onPeersChange, goHospital, setQuery } from './main.js';

const tip = tooltip();
const DEFAULT_COLS = ['READM_30_PN', 'MORT_30_HF', 'HAI_1_SIR', 'SEP_1', 'H_RECMND_DY', 'H_STAR_RATING'];
const EXP = ['H_RECMND_DY', 'H_HSP_RATING_9_10', 'H_COMP_1_A_P', 'H_COMP_2_A_P', 'H_COMP_5_A_P', 'H_COMP_6_Y_P', 'H_CLEAN_HSP_A_P', 'H_QUIET_HSP_A_P'];
let root, ctx, state = { m: 'READM_30_PN', cols: DEFAULT_COLS.slice(), range: null, sort: 'READM_30_PN', asc: true, pinned: null, hover: null };
let stripEl, tableEl, heatEl, countEl, colsEl, brushG, xScale, dotSel = null;

function mount(r, c) {
  root = r; ctx = c;
  root.append(el('p', { class: 'kicker', text: 'Compare' }));
  root.append(el('h1', { text: 'The peer group, side by side' }));
  root.append(el('p', { class: 'dek', text: 'Pick a measure and brush a range of its distribution. The scorecard and the patient-experience heatmap below show only the hospitals you selected. Hover a row to find it in the distribution.' }));

  // strip card
  const c1 = el('div', { class: 'card' });
  const ctl = el('div', { class: 'controls' });
  const sel = el('select', { id: 'cmp-m' });
  for (const g of Object.keys(D.groups)) {
    const og = el('optgroup', { label: D.groups[g] });
    og.append(...D.key.filter(m => m.group === g).map(m => el('option', { value: m.id, text: m.short })));
    sel.append(og);
  }
  sel.value = state.m;
  sel.addEventListener('change', () => { state.m = sel.value; state.range = null; state.sort = state.m; state.asc = !!D.keyById.get(state.m).hib === false; if (!state.cols.includes(state.m)) { state.cols = [state.m, ...state.cols].slice(0, 8); } setQuery({ m: state.m, r: undefined }); renderAll(); });
  ctl.append(el('label', {}, ['Measure ', sel]));
  ctl.append(el('button', { class: 'btn-ghost small', text: 'Clear selection', onclick: () => { state.range = null; setQuery({ r: undefined }); if (brushG) brushG.call(d3.brushX().clear); renderAll(); } }));
  countEl = el('span', { class: 'caption', style: 'margin:0 0 0 auto' }); ctl.append(countEl);
  c1.append(ctl);
  stripEl = el('div'); c1.append(stripEl);
  c1.append(el('p', { class: 'caption', text: 'Each dot is a hospital in the peer group (a histogram when the group is large). Solid line: peer median. Lighter line: U.S. median. Drag across the chart to select.' }));
  c1.append(sqlButton({ file: '05_vs_state_average' }));
  root.append(c1);

  // table card
  const c2 = el('div', { class: 'card' });
  const hdr = el('div', { class: 'row', style: 'justify-content:space-between;margin-bottom:8px' });
  hdr.append(el('h2', { text: 'Scorecard' }));
  hdr.append(el('button', { class: 'btn-ghost small', text: 'Download selection (CSV)', onclick: exportCSV }));
  c2.append(hdr);
  colsEl = el('div', { class: 'row', style: 'gap:6px;margin-bottom:10px' }); c2.append(colsEl);
  tableEl = el('div', { class: 'tablewrap' }); c2.append(tableEl);
  c2.append(el('p', { class: 'caption', html: '<span class="key emph"></span> at or better than the peer median &nbsp; <span class="key ctx"></span> worse &nbsp;·&nbsp; bar length = position within the peer range, oriented so longer is always better &nbsp;·&nbsp; click a column header to sort, a hospital to open its report card' }));
  c2.append(sqlButton({ file: '11_scorecard_pivot' }));
  root.append(c2);

  // heatmap card
  const c3 = el('div', { class: 'card' });
  c3.append(el('h2', { text: 'What patients said' }));
  c3.append(el('p', { class: 'sub', text: 'HCAHPS survey answers for the selected hospitals. Each cell is coloured by the share of peers the hospital beats on that question, so darker is always better.' }));
  heatEl = el('div'); c3.append(heatEl);
  c3.append(sqlButton({ file: 'views', view: 'v_hcahps' }));
  root.append(c3);

  onPeersChange(() => { state.range = null; renderAll(); });
}

function show(q) {
  if (q.m && D.keyById.has(q.m)) { state.m = q.m; document.getElementById('cmp-m').value = q.m; }
  if (q.cols) state.cols = q.cols.split(',').filter(c => D.keyById.has(c)).slice(0, 8);
  if (q.r) { const [a, b] = q.r.split(',').map(Number); if (!Number.isNaN(a) && !Number.isNaN(b)) state.range = [a, b]; }
  state.pinned = q.h && D.byId.has(q.h) ? D.byId.get(q.h).i : null;
  if (!state.cols.includes(state.m)) state.cols = [state.m, ...state.cols].slice(0, 8);
  renderAll();
}

function selected() {
  const s = seriesFor(state.m), out = [];
  for (const i of ctx.peers) {
    const v = s[i];
    if (state.range) { if (Number.isNaN(v) || v < state.range[0] || v > state.range[1]) continue; }
    out.push(i);
  }
  return out;
}

function renderAll() { renderStrip(); renderCols(); renderTable(); renderHeat(); }

// ---------------- strip with brush ----------------
function renderStrip() {
  const m = D.keyById.get(state.m), s = seriesFor(state.m);
  const ps = sortedIn(state.m, ctx.peers), us = sortedIn(state.m, null);
  const W = 1100, H = 190, ml = 16, mr = 16, mt = 26, mb = 34;
  const svg = svgIn(stripEl, W, H);
  if (!ps.length) { svg.append('text').attr('x', ml).attr('y', 40).attr('fill', T.muted).text('No hospitals in this peer group report this measure.'); countEl.textContent = ''; return; }
  const lo = ps[Math.floor(ps.length * 0.005)], hi = ps[Math.min(ps.length - 1, Math.ceil(ps.length * 0.995))];
  xScale = d3.scaleLinear().domain([lo, hi]).nice().range([ml, W - mr]);
  const x = xScale, pmed = median(ps), umed = median(us);
  const ax = axisStyle(svg.append('g').attr('transform', `translate(0,${H - mb})`).call(d3.axisBottom(x).ticks(10).tickFormat(v => fmtVal(m, v).replace('.0', ''))));
  ax.select('.domain').attr('stroke', T.axis);
  svg.append('text').attr('x', ml).attr('y', 14).attr('fill', T.ink).style('font-weight', 600).style('font-size', '13px').text(`${m.short} · ${m.hib ? 'higher is better' : 'lower is better'} · ${ps.length.toLocaleString()} hospitals in ${scopeLabel(ctx.scope)}`);
  // reference lines
  for (const [v, col, lbl, anchor, ty] of [[umed, T.axis, `U.S. median ${fmtVal(m, umed)}`, 'end', mt + 22], [pmed, T.ink2, `peer median ${fmtVal(m, pmed)}`, 'start', mt + 10]]) {
    if (Number.isNaN(v) || v < lo || v > hi) continue;
    svg.append('line').attr('x1', x(v)).attr('x2', x(v)).attr('y1', mt).attr('y2', H - mb).attr('stroke', col).attr('stroke-width', 1);
    svg.append('text').attr('x', x(v) + (anchor === 'start' ? 4 : -4)).attr('y', ty).attr('text-anchor', anchor).attr('fill', col === T.axis ? T.muted : T.ink2).style('font-size', '11px').text(lbl);
  }
  const inRange = (v) => !state.range || (v >= state.range[0] && v <= state.range[1]);
  dotSel = null;
  if (ps.length <= 450) {
    // dot strip: stack dots per pixel-bin
    const r = ps.length > 250 ? 3 : 4, step = r * 2 + 1, nb = Math.floor((W - ml - mr) / step);
    const cols = new Map(); const pts = [];
    for (const i of ctx.peers) { const v = s[i]; if (Number.isNaN(v)) continue; const k = Math.max(0, Math.min(nb - 1, Math.floor((x(Math.max(lo, Math.min(hi, v))) - ml) / step))); const n = cols.get(k) || 0; cols.set(k, n + 1); pts.push({ i, v, k, n }); }
    const maxN = d3.max(pts, d => d.n) + 1, avail = H - mb - mt - 16, dy = Math.min(step, avail / maxN);
    dotSel = svg.append('g').selectAll('circle').data(pts, d => d.i).join('circle')
      .attr('cx', d => ml + d.k * step + r).attr('cy', d => H - mb - 6 - r - d.n * dy).attr('r', r)
      .attr('fill', d => d.i === state.pinned ? T.ink : inRange(d.v) ? T.blue : T.deemph).attr('stroke', T.surface).attr('stroke-width', 1)
      .style('cursor', 'pointer')
      .on('mousemove', (ev, d) => tip.show(hospTip(D.H[d.i], `<div>${m.short}: <b>${fmtVal(m, d.v)}</b> · beats ${Math.round(betterThan(m.id, d.v, ps) * 100)}% of peers</div>`), ev))
      .on('mouseleave', () => tip.hide()).on('click', (ev, d) => goHospital(D.H[d.i]));
  } else {
    const b = bins(ps.filter(v => v >= lo && v <= hi), 60, lo, hi), max = d3.max(b, d => d.n);
    const y = d3.scaleLinear().domain([0, max]).range([H - mb, mt + 14]);
    svg.append('g').selectAll('rect').data(b).join('rect')
      .attr('x', d => x(d.x0) + 0.5).attr('width', d => Math.max(0, x(d.x1) - x(d.x0) - 1)).attr('y', d => y(d.n)).attr('height', d => H - mb - y(d.n))
      .attr('fill', d => inRange((d.x0 + d.x1) / 2) ? T.blue : T.deemph)
      .on('mousemove', (ev, d) => tip.show(`${fmtVal(m, d.x0)} – ${fmtVal(m, d.x1)}<br><b>${d.n}</b> hospitals`, ev)).on('mouseleave', () => tip.hide());
    if (state.pinned != null && !Number.isNaN(s[state.pinned])) {
      const v = s[state.pinned];
      svg.append('line').attr('x1', x(v)).attr('x2', x(v)).attr('y1', mt + 14).attr('y2', H - mb).attr('stroke', T.ink).attr('stroke-width', 2);
      svg.append('text').attr('x', x(v) + 4).attr('y', mt + 26).attr('fill', T.ink).style('font-size', '11px').text(D.H[state.pinned].name);
    }
  }
  // brush
  const brush = d3.brushX().extent([[ml, mt + 12], [W - mr, H - mb]]).on('brush end', (ev) => {
    if (!ev.sourceEvent && !ev.selection) return;
    if (ev.selection) { state.range = ev.selection.map(x.invert); }
    else state.range = null;
    if (ev.type === 'end') setQuery({ r: state.range ? state.range.map(v => +v.toFixed(3)).join(',') : undefined });
    if (dotSel) dotSel.attr('fill', d => d.i === state.pinned ? T.ink : inRange(d.v) ? T.blue : T.deemph);
    else svg.selectAll('rect').filter(function () { return this.parentNode.classList?.contains('brush') !== true && d3.select(this).datum()?.x0 !== undefined; }).attr('fill', d => inRange((d.x0 + d.x1) / 2) ? T.blue : T.deemph);
    updateCount(); if (ev.type === 'end') { renderTable(); renderHeat(); }
  });
  brushG = svg.append('g').attr('class', 'brush').call(brush);
  brushG.selectAll('.selection').attr('fill', T.blue).attr('fill-opacity', .08).attr('stroke', T.ink2).attr('stroke-width', 1);
  if (state.range) brushG.call(brush.move, [x(state.range[0]), x(state.range[1])]);
  updateCount();
}
function updateCount() {
  const n = selected().length, rep = sortedIn(state.m, ctx.peers).length;
  countEl.textContent = state.range ? `${n.toLocaleString()} of ${rep.toLocaleString()} reporting hospitals selected` : `${rep.toLocaleString()} of ${ctx.peers.length.toLocaleString()} hospitals report this measure · drag to select`;
}
export function highlight(i) {
  state.hover = i;
  if (dotSel) dotSel.attr('r', d => d.i === i ? 6 : (ctx.peers.length > 250 ? 3 : 4)).attr('fill', d => d.i === i ? T.ink : d.i === state.pinned ? T.ink : (!state.range || (d.v >= state.range[0] && d.v <= state.range[1])) ? T.blue : T.deemph).filter(d => d.i === i).raise();
}

// ---------------- column chips ----------------
function renderCols() {
  colsEl.innerHTML = '';
  colsEl.append(el('span', { class: 'caption', style: 'margin:0 6px 0 0', text: 'Columns:' }));
  for (const id of state.cols) {
    const m = D.keyById.get(id);
    colsEl.append(el('span', { class: 'chip on', html: `${m.short} <span style="opacity:.7">×</span>`, title: 'remove column', onclick: () => {
      if (state.cols.length > 1) { state.cols = state.cols.filter(c => c !== id); setQuery({ cols: state.cols.join(',') }); renderCols(); renderTable(); }
    } }));
  }
  if (state.cols.length < 8) {
    const add = el('select', { style: 'font-size:12px;padding:3px 6px' });
    add.append(el('option', { value: '', text: '+ add a column' }));
    for (const g of Object.keys(D.groups)) {
      const og = el('optgroup', { label: D.groups[g] });
      og.append(...D.key.filter(m => m.group === g && !state.cols.includes(m.id)).map(m => el('option', { value: m.id, text: m.short })));
      if (og.children.length) add.append(og);
    }
    add.addEventListener('change', () => { if (add.value) { state.cols.push(add.value); setQuery({ cols: state.cols.join(',') }); renderCols(); renderTable(); } });
    colsEl.append(add);
  } else colsEl.append(el('span', { class: 'caption', style: 'margin:0', text: 'eight columns is the maximum' }));
  colsEl.append(el('button', { class: 'btn-ghost small', text: 'Reset', onclick: () => { state.cols = DEFAULT_COLS.slice(); if (!state.cols.includes(state.m)) state.cols.unshift(state.m); setQuery({ cols: undefined }); renderCols(); renderTable(); } }));
}

// ---------------- table ----------------
function renderTable() {
  const rows = selected();
  const cols = state.cols.map(id => D.keyById.get(id));
  const stats = {}; for (const m of cols) { const ps = sortedIn(m.id, ctx.peers); stats[m.id] = { ps, med: median(ps), lo: ps[0], hi: ps[ps.length - 1] }; }
  const sm = D.keyById.get(state.sort) || cols[0];
  const ss = seriesFor(sm.id);
  const ordered = rows.slice().sort((a, b) => {
    const va = ss[a], vb = ss[b];
    if (Number.isNaN(va) && Number.isNaN(vb)) return 0; if (Number.isNaN(va)) return 1; if (Number.isNaN(vb)) return -1;
    return state.asc ? va - vb : vb - va;
  });
  const CAP = 200, shown = ordered.slice(0, CAP);
  tableEl.innerHTML = '';
  const table = el('table', { class: 'data' });
  const thead = el('thead'); const tr = el('tr');
  tr.append(el('th', { html: 'Hospital<span class="dir">click a name for its report card</span>' }));
  for (const m of cols) {
    const th = el('th', { html: `${m.short}${state.sort === m.id ? (state.asc ? ' ↑' : ' ↓') : ''}<span class="dir">${m.hib ? 'higher is better' : 'lower is better'}${m.unit && m.unit !== '%' ? ' · ' + m.unit : ''}</span>` });
    th.addEventListener('click', () => { if (state.sort === m.id) state.asc = !state.asc; else { state.sort = m.id; state.asc = !m.hib; } renderTable(); });
    tr.append(th);
  }
  thead.append(tr); table.append(thead);
  const tb = el('tbody');
  for (const i of shown) {
    const h = D.H[i];
    const r = el('tr', { class: i === state.pinned ? 'hl' : '' });
    r.addEventListener('mouseenter', () => highlight(i)); r.addEventListener('mouseleave', () => highlight(null));
    const nm = el('td', { class: 'name', html: `<a style="cursor:pointer;color:inherit;text-decoration:none">${h.name}</a><span class="meta">${h.city ? h.city + ', ' : ''}${h.state} · ${h.own}</span>` });
    nm.addEventListener('click', () => goHospital(h)); r.append(nm);
    for (const m of cols) {
      const v = seriesFor(m.id)[i], st = stats[m.id];
      if (Number.isNaN(v)) { r.append(el('td', { class: 'na', text: '–', style: 'color:var(--muted);text-align:center' })); continue; }
      let w = st.hi === st.lo ? 50 : 100 * (v - st.lo) / (st.hi - st.lo); if (!m.hib) w = 100 - w;
      const better = m.hib ? v >= st.med : v <= st.med;
      r.append(el('td', { html: `<div class="cell"><span class="track"><span class="bar${better ? ' emph' : ''}" style="width:${Math.max(2, w).toFixed(0)}%"></span></span><span class="v">${fmtVal(m, v)}</span></div>` }));
    }
    tb.append(r);
  }
  table.append(tb); tableEl.append(table);
  if (ordered.length > CAP) tableEl.append(el('p', { class: 'caption', text: `Showing ${CAP} of ${ordered.length.toLocaleString()} hospitals. Brush the distribution or narrow the peer group to see the rest; the CSV export includes everything.` }));
  if (!ordered.length) tableEl.append(el('p', { class: 'caption', text: 'No hospitals in the selection.' }));
}

function exportCSV() {
  const rows = selected(); const cols = state.cols.map(id => D.keyById.get(id));
  downloadCSV('scorecard_selection.csv', rows.map(i => D.H[i]), [
    { key: 'facility_id', get: h => h.id }, { key: 'name', get: h => h.name }, { key: 'city', get: h => h.city }, { key: 'state', get: h => h.state }, { key: 'county', get: h => h.county }, { key: 'ownership', get: h => h.own }, { key: 'type', get: h => h.type }, { key: 'cms_overall_rating', get: h => h.stars },
    ...cols.map(m => ({ key: m.id, get: h => { const v = seriesFor(m.id)[h.i]; return Number.isNaN(v) ? '' : v; } }))]);
}

// ---------------- heatmap ----------------
function renderHeat() {
  const rows = selected();
  const ms = EXP.map(id => D.keyById.get(id)).filter(Boolean);
  const stats = {}; for (const m of ms) stats[m.id] = sortedIn(m.id, ctx.peers);
  const rec = seriesFor('H_RECMND_DY');
  let list = rows.filter(i => ms.some(m => !Number.isNaN(seriesFor(m.id)[i]))).sort((a, b) => (Number.isNaN(rec[b]) ? -1 : rec[b]) - (Number.isNaN(rec[a]) ? -1 : rec[a]));
  const CAP = 60, total = list.length; list = list.slice(0, CAP);
  heatEl.innerHTML = '';
  if (!list.length) { heatEl.append(el('p', { class: 'caption', text: 'None of the selected hospitals report HCAHPS results.' })); return; }
  const rowH = 18, ml = 250, mt = 112, cw = 92, W = ml + cw * ms.length + 90, H = mt + rowH * list.length + 12;
  const svg = svgIn(heatEl, W, H);
  const color = seqScale([0, 1]);
  ms.forEach((m, k) => svg.append('text').attr('x', ml + k * cw + cw / 2 + 4).attr('y', mt - 8).attr('text-anchor', 'start').attr('transform', `rotate(-45 ${ml + k * cw + cw / 2 + 4} ${mt - 8})`).attr('fill', T.ink2).style('font-size', '11px').text(m.short));
  list.forEach((i, r) => {
    const h = D.H[i];
    svg.append('text').attr('x', ml - 8).attr('y', mt + r * rowH + rowH / 2 + 4).attr('text-anchor', 'end').attr('fill', i === state.pinned ? T.ink : T.ink2).style('font-size', '11px').style('cursor', 'pointer').text(h.name.length > 38 ? h.name.slice(0, 37) + '…' : h.name).on('click', () => goHospital(h));
    ms.forEach((m, k) => {
      const v = seriesFor(m.id)[i];
      const b = Number.isNaN(v) ? NaN : betterThan(m.id, v, stats[m.id]);
      svg.append('rect').attr('x', ml + k * cw + 1).attr('y', mt + r * rowH + 1).attr('width', cw - 2).attr('height', rowH - 2)
        .attr('fill', Number.isNaN(b) ? '#f0efe9' : color(b))
        .on('mousemove', (ev) => tip.show(hospTip(h, `<div>${m.short}: <b>${fmtVal(m, v)}</b>${Number.isNaN(b) ? ' (not reported)' : ` · beats ${Math.round(b * 100)}% of peers`}</div>`), ev)).on('mouseleave', () => tip.hide());
    });
  });
  // legend
  const lg = svg.append('g').attr('transform', `translate(${ml + cw * ms.length + 14},${mt})`);
  T.seq.forEach((c, k) => lg.append('rect').attr('x', 0).attr('y', k * 12).attr('width', 12).attr('height', 12).attr('fill', c));
  lg.append('text').attr('x', 16).attr('y', 9).attr('fill', T.muted).style('font-size', '10px').text('worse');
  lg.append('text').attr('x', 16).attr('y', 12 * T.seq.length - 2).attr('fill', T.muted).style('font-size', '10px').text('better');
  if (total > CAP) heatEl.append(el('p', { class: 'caption', text: `Showing the ${CAP} hospitals with the highest "would recommend" score of ${total.toLocaleString()} selected. Brush a narrower range to see others.` }));
}

export default { name: 'compare', mount, show };
