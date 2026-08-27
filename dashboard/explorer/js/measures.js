// measures.js — the measure explorer: browse all 161 CMS measures, see the national + peer distribution
// for the selected one, and pull the best/worst hospitals in the current peer group.
import { D, loadMeasure, sortedIn, quantile, median, fmtVal, fmtPct, scopeLabel } from './data.js';
import { T, el, tooltip, sqlButton, downloadCSV, svgIn, axisStyle, bins, debounce } from './ui.js';
import { onPeersChange, goHospital, setQuery } from './main.js';

const DEFAULT_ID = 'MORT_30_HF';
const VT_LABEL = { score: 'Score', answer_percent: 'Percent answering', linear_mean: 'Linear mean score', star_rating: 'Star rating (1–5)' };

let refs = null;
let curCtx = null;
let selected = DEFAULT_ID;
let showHidden = false;
let filterText = '';

function truncate(s, n) { return s.length > n ? s.slice(0, n - 1) + '…' : s; }
function prettifyDomain(s) { return (s || '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()); }

function fmtMeasureVal(meta, keyMeta, x) {
  if (x === null || x === undefined || Number.isNaN(x)) return '–';
  if (keyMeta) return fmtVal(keyMeta, x);
  const dec = Math.abs(x) >= 10 ? 1 : 2;
  let s = Number(x).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
  if (meta.vt === 'answer_percent') s += '%';
  return s;
}

function measureList() {
  const q = filterText;
  return D.cat.all
    .filter(m => showHidden || !m.hidden)
    .filter(m => !q || m.id.toLowerCase().includes(q) || m.name.toLowerCase().includes(q))
    .slice()
    .sort((a, b) => b.n - a.n);
}

function renderList() {
  if (!refs) return;
  refs.listEl.innerHTML = '';
  const rows = measureList();
  for (const m of rows) {
    const row = el('div', { class: m.id === selected ? 'cur' : '', role: 'option', onclick: () => selectMeasure(m.id) });
    const nameSpan = el('span', {}, [truncate(m.name, 70)]);
    if (m.key) nameSpan.append(' ', el('span', { class: 'chip', text: 'key', style: 'padding:0 6px;font-size:10px;cursor:default' }));
    row.append(nameSpan, el('span', { class: 'n', text: m.n.toLocaleString() }));
    refs.listEl.append(row);
  }
  if (!rows.length) refs.listEl.append(el('div', { text: 'No measures match.', style: 'cursor:default' }));
}

function selectMeasure(id) {
  if (id === selected) return;
  selected = id;
  setQuery({ m: id });
  renderList();
  renderDetail();
}

function peerPairs(series, peers) {
  const out = [];
  const idxs = peers || D.H.map(h => h.i);
  for (const i of idxs) { const v = series[i]; if (!Number.isNaN(v)) out.push({ i, v }); }
  return out;
}

function buildHeader(meta, keyMeta, peerN) {
  const card = el('div', { class: 'card' });
  const title = keyMeta ? keyMeta.short : meta.name;
  card.append(el('div', { class: 'kicker', text: keyMeta ? D.groups[keyMeta.group] : prettifyDomain(meta.domain) }));
  card.append(el('h2', { text: title }));
  if (keyMeta) card.append(el('p', { class: 'sub', text: keyMeta.desc }));
  const vtLabel = VT_LABEL[meta.vt] || meta.vt;
  const dirLabel = meta.hib === true ? 'Higher is better' : meta.hib === false ? 'Lower is better' : 'Direction not defined';
  const periodTxt = keyMeta?.period ? `reporting period ${keyMeta.period[0]} to ${keyMeta.period[1]}` : null;
  card.append(el('p', { class: 'sub', text: [vtLabel, dirLabel, periodTxt].filter(Boolean).join(' · ') }));
  card.append(el('p', { class: 'sub', text: `reported by ${meta.n.toLocaleString()} of ${D.cat.n_hospitals.toLocaleString()} hospitals (${fmtPct(meta.n / D.cat.n_hospitals)}) nationally · ${peerN.toLocaleString()} in current peer group` }));
  const bar = el('div', { class: 'missbar' });
  bar.append(el('span', { style: `width:${Math.min(100, 100 * meta.n / D.cat.n_hospitals).toFixed(1)}%` }));
  card.append(bar);
  return card;
}

function drawHistogram(container, meta, keyMeta, natSorted, peerSorted, natMedian, peerMedian) {
  const width = 760, height = 260, m = { top: 22, right: 16, bottom: 26, left: 16 };
  const svg = svgIn(container, width, height);
  if (!natSorted.length) {
    svg.append('text').attr('x', width / 2).attr('y', height / 2).attr('text-anchor', 'middle').attr('fill', T.muted).text('no data reported for this measure');
    return;
  }
  const lo = quantile(natSorted, 0.005), hi = quantile(natSorted, 0.995);
  const nb = 40;
  const natBins = bins(natSorted, nb, lo, hi);
  const peerBins = peerSorted.length ? bins(peerSorted, nb, lo, hi) : null;
  const natTotal = natSorted.length, peerTotal = peerSorted.length;
  const natDensity = natBins.map(b => b.n / natTotal);
  const peerDensity = peerBins ? peerBins.map(b => b.n / peerTotal) : null;
  const yMax = Math.max(0.0001, ...natDensity, ...(peerDensity || [0])) * 1.15;

  const x = d3.scaleLinear().domain([lo, hi]).range([m.left, width - m.right]);
  const y = d3.scaleLinear().domain([0, yMax]).range([height - m.bottom, m.top]);

  const gx = svg.append('g').attr('transform', `translate(0,${height - m.bottom})`)
    .call(d3.axisBottom(x).ticks(6).tickFormat(v => fmtMeasureVal(meta, keyMeta, v)).tickSizeOuter(0));
  axisStyle(gx);

  svg.append('g').selectAll('rect.bar').data(natBins).join('rect')
    .attr('class', 'bar')
    .attr('x', d => x(d.x0) + 0.5)
    .attr('width', d => Math.max(0, x(d.x1) - x(d.x0) - 1))
    .attr('y', (d, i) => y(natDensity[i]))
    .attr('height', (d, i) => Math.max(0, y(0) - y(natDensity[i])))
    .attr('fill', T.deemph);

  if (peerBins) {
    const stepPoints = [];
    peerBins.forEach((b, i) => { stepPoints.push([b.x0, peerDensity[i]], [b.x1, peerDensity[i]]); });
    const line = d3.line().x(p => x(p[0])).y(p => y(p[1]));
    svg.append('path').datum(stepPoints).attr('fill', 'none').attr('stroke', T.blue).attr('stroke-width', 2).attr('d', line);
  }

  function hairline(v, color, label, ty) {
    if (Number.isNaN(v) || v < lo || v > hi) return;
    svg.append('line').attr('x1', x(v)).attr('x2', x(v)).attr('y1', m.top).attr('y2', height - m.bottom).attr('stroke', color).attr('stroke-width', 1);
    svg.append('text').attr('x', x(v) + 4).attr('y', ty).attr('fill', color).style('font-size', '11px').text(label);
  }
  hairline(natMedian, T.ink2, `US median ${fmtMeasureVal(meta, keyMeta, natMedian)}`, m.top + 2);
  hairline(peerMedian, T.blue, `Peer median ${fmtMeasureVal(meta, keyMeta, peerMedian)}`, m.top + 14);

  // transparent full-height hover targets, one per bin
  const tt = tooltip();
  svg.append('g').selectAll('rect.hit').data(natBins).join('rect')
    .attr('class', 'hit')
    .attr('x', d => x(d.x0)).attr('width', d => Math.max(1, x(d.x1) - x(d.x0)))
    .attr('y', m.top).attr('height', height - m.bottom - m.top)
    .attr('fill', 'transparent')
    .on('mousemove', (ev, d) => {
      const i = natBins.indexOf(d);
      const peerN = peerBins ? peerBins[i].n : 0;
      tt.show(`${fmtMeasureVal(meta, keyMeta, d.x0)}–${fmtMeasureVal(meta, keyMeta, d.x1)}<div class="tip-sub">${d.n.toLocaleString()} nationally${peerSorted.length ? ' · ' + peerN.toLocaleString() + ' in peer group' : ''}</div>`, ev);
    })
    .on('mouseleave', () => tt.hide());
}

function buildList(title, pairs, meta, keyMeta) {
  const wrap = el('div', {});
  wrap.append(el('h3', { text: title }));
  const ul = el('ul', { class: 'toplist' });
  for (const p of pairs) {
    const h = D.H[p.i];
    const li = el('li', {});
    const nameCell = el('span', {}, [
      el('a', { text: h.name, onclick: () => goHospital(h) }),
      el('span', { class: 'search-meta', text: ` ${h.city ? h.city + ', ' : ''}${h.state}` })
    ]);
    li.append(nameCell, el('span', { text: fmtMeasureVal(meta, keyMeta, p.v) }));
    ul.append(li);
  }
  wrap.append(ul);
  return wrap;
}

function buildLists(meta, keyMeta, pairsAsc, ctx) {
  const card = el('div', { class: 'card' });
  if (!pairsAsc.length) {
    card.append(el('p', { class: 'sub', text: 'No hospitals in this peer group report this measure.' }));
    return card;
  }
  const peerLabel = scopeLabel(ctx.scope);
  const undecided = meta.hib === null || meta.hib === undefined;
  const higherIsBest = meta.hib !== false; // true or undecided -> top of range shown first
  const best = higherIsBest ? pairsAsc.slice(-10).reverse() : pairsAsc.slice(0, 10);
  const worst = higherIsBest ? pairsAsc.slice(0, 10) : pairsAsc.slice(-10).reverse();
  const t1 = (undecided ? 'Highest 10 in ' : 'Best 10 in ') + peerLabel;
  const t2 = (undecided ? 'Lowest 10 in ' : 'Worst 10 in ') + peerLabel;
  const grid = el('div', { class: 'grid2' });
  grid.append(buildList(t1, best, meta, keyMeta), buildList(t2, worst, meta, keyMeta));
  card.append(grid);
  return card;
}

function buildActions(meta, pairsAsc) {
  const card = el('div', { class: 'card', style: 'display:flex;gap:10px;flex-wrap:wrap;align-items:flex-start' });
  card.append(sqlButton({ file: '02_sparse_measures_tx' }));
  const dl = el('button', {
    class: 'btn-ghost', type: 'button', text: 'Download CSV (peer group)',
    onclick: () => {
      const rows = pairsAsc.slice().reverse().map(p => ({ h: D.H[p.i], v: p.v }));
      downloadCSV(`${meta.id}_peer_group.csv`, rows, [
        { key: 'facility_id', get: r => r.h.id },
        { key: 'name', get: r => r.h.name },
        { key: 'city', get: r => r.h.city },
        { key: 'state', get: r => r.h.state },
        { key: 'value', get: r => r.v }
      ]);
    }
  });
  card.append(dl);
  return card;
}

async function renderDetail() {
  if (!refs || !curCtx) return;
  const meta = D.cat.all.find(m => m.id === selected);
  if (!meta) return;
  const keyMeta = D.keyById.get(selected);
  const mySel = selected;
  refs.detailEl.innerHTML = '';
  refs.detailEl.append(el('div', { class: 'loading', text: 'Loading measure…' }));
  const series = await loadMeasure(meta);
  if (mySel !== selected || !refs) return; // stale: selection or view changed while fetching

  const natSorted = sortedIn(selected, null, series);
  const peerSorted = sortedIn(selected, curCtx.peers, series);
  const pairsAsc = peerPairs(series, curCtx.peers).sort((a, b) => a.v - b.v);

  refs.detailEl.innerHTML = '';
  refs.detailEl.append(buildHeader(meta, keyMeta, peerSorted.length));

  const chartCard = el('div', { class: 'card' });
  chartCard.append(el('h3', { text: 'Distribution' }),
    el('p', { class: 'caption', text: 'Gray bars: national distribution. Blue line: current peer group (same axis, scaled by share of group).' }));
  const chartHost = el('div', {});
  chartCard.append(chartHost);
  refs.detailEl.append(chartCard);
  drawHistogram(chartHost, meta, keyMeta, natSorted, peerSorted, median(natSorted), median(peerSorted));

  refs.detailEl.append(buildLists(meta, keyMeta, pairsAsc, curCtx));
  refs.detailEl.append(buildActions(meta, pairsAsc));
}

export default {
  name: 'measures',
  mount(root, ctx) {
    curCtx = ctx;
    root.innerHTML = '';
    const wrap = el('div', { style: 'display:grid;grid-template-columns:300px 1fr;gap:20px;align-items:start' });

    const left = el('div', {});
    const search = el('input', { class: 'search', type: 'search', placeholder: 'Filter by name or ID', 'aria-label': 'Filter measures', style: 'width:100%;margin-bottom:8px' });
    const compLabel = el('label', { class: 'controls', style: 'margin-bottom:8px' });
    const compCb = el('input', { type: 'checkbox' });
    compLabel.append(compCb, document.createTextNode(' show component rows'));
    const listEl = el('div', { class: 'mlist' });
    left.append(search, compLabel, listEl);

    const right = el('div', {});
    wrap.append(left, right);
    root.append(wrap);

    refs = { root, search, compCb, listEl, detailEl: right };

    search.addEventListener('input', debounce(() => { filterText = search.value.trim().toLowerCase(); renderList(); }));
    compCb.addEventListener('change', () => { showHidden = compCb.checked; renderList(); });
    onPeersChange((c) => { curCtx = c; renderDetail(); });
  },
  show(q, ctx) {
    curCtx = ctx;
    const valid = q.m && D.cat.all.some(m => m.id === q.m);
    selected = valid ? q.m : DEFAULT_ID;
    if (refs) { refs.search.value = ''; filterText = ''; }
    renderList();
    renderDetail();
  }
};
