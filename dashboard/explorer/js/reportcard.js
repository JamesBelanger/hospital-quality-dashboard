// reportcard.js — "Report card": look up any U.S. hospital and see every key measure against the peer group and the nation.
import { D, seriesFor, sortedIn, median, betterThan, fmtVal, fmtPct, scopeLabel, stateName } from './data.js';
import { T, el, tooltip, hospitalSearch, sqlButton, downloadCSV, bins, badge } from './ui.js';
import { onPeersChange, go, setQuery, setScopeValue, setFilters, scopeValue } from './main.js';

const tip = tooltip();
let root, ctx, current = null, body, search;

const EXAMPLES = ['Houston Methodist Hospital', 'Mayo Clinic Hospital Rochester', 'Cleveland Clinic', 'Massachusetts General Hospital', 'Cedars-Sinai Medical Center', 'UCLA Health Ronald Reagan Medical Center'];

function mount(r, c) {
  root = r; ctx = c;
  root.append(el('p', { class: 'kicker', text: 'Report card' }));
  root.append(el('h1', { text: 'How does one hospital compare?' }));
  root.append(el('p', { class: 'dek', text: `Search any of ${D.H.length.toLocaleString()} U.S. hospitals. Every measure is placed against the peer group you choose in the bar above and against the whole country.` }));
  const sw = el('div', { class: 'searchwrap' });
  search = hospitalSearch(sw, (h) => select(h));
  const ex = el('div', { class: 'row', style: 'margin-top:10px;font-size:12.5px;color:var(--muted)' }, [el('span', { text: 'Try:' })]);
  for (const name of EXAMPLES) {
    const h = D.H.find(x => x.name === name); if (!h) continue;
    ex.append(el('span', { class: 'chip', text: h.name, onclick: () => select(h) }));
  }
  root.append(el('div', { class: 'card' }, [sw, ex]));
  body = el('div'); root.append(body);
  onPeersChange(() => current && render());
  renderEmpty();
}

function show(q) {
  if (q.h && D.byId.has(q.h)) { if (!current || current.id !== q.h) select(D.byId.get(q.h), true); }
  else if (!q.h && current) { current = null; search.set(null); renderEmpty(); }
}

function select(h, fromUrl = false) {
  current = h; search.set(h);
  if (!fromUrl) setQuery({ h: h.id });
  render();
}

function renderEmpty() {
  body.innerHTML = '';
  body.append(el('div', { class: 'card' }, [
    el('h2', { text: 'How to read a report card' }),
    el('p', { class: 'sub', html: 'Each row places the hospital’s score (blue dot) on the distribution of its peers (gray bars). The tick marks the peer median; the badge says what share of peers the hospital beats after accounting for whether higher or lower is better. Empty rows mean CMS did not publish a score — usually a small denominator.' }),
    el('p', { class: 'sub', html: 'Change the peer group in the bar above: the whole country, one state, the Houston area, or only hospitals with the same ownership or type.' })
  ]));
}

function peerChips(h) {
  const row = el('div', { class: 'row', style: 'gap:6px' });
  const mk = (label, on, act) => el('span', { class: 'chip' + (on ? ' on' : ''), text: label, onclick: act });
  const sv = scopeValue(), f = ctx.filters;
  row.append(mk('All U.S. hospitals', sv === 'us' && !f.own && !f.type, () => { setFilters({ own: undefined, type: undefined, er: undefined }); setScopeValue('us'); }));
  row.append(mk(stateName(h.state), sv === 'state:' + h.state && !f.own && !f.type, () => { setFilters({ own: undefined, type: undefined, er: undefined }); setScopeValue('state:' + h.state); }));
  row.append(mk(`Same ownership in ${h.state}`, sv === 'state:' + h.state && f.own === h.own, () => { setFilters({ own: h.own, type: undefined }); setScopeValue('state:' + h.state); }));
  row.append(mk(`Same type, U.S.`, sv === 'us' && f.type === h.type && !f.own, () => { setFilters({ type: h.type, own: undefined }); setScopeValue('us'); }));
  if (h.hou) row.append(mk('Houston area', sv === 'houston', () => { setFilters({ own: undefined, type: undefined, er: undefined }); setScopeValue('houston'); }));
  return row;
}

function render() {
  const h = current; body.innerHTML = '';
  const peers = ctx.peers, inPeers = peers.includes(h.i);
  const label = scopeLabel(ctx.scope) + (ctx.filters.own ? ', ' + ctx.filters.own.toLowerCase() : '') + (ctx.filters.type ? ', ' + ctx.filters.type.toLowerCase() : '');
  // ---- per-measure stats
  const rows = D.key.map(m => {
    const s = seriesFor(m.id), x = s[h.i];
    const ps = sortedIn(m.id, peers), us = sortedIn(m.id, null);
    return { m, x, ps, us, pmed: median(ps), umed: median(us), beat: betterThan(m.id, x, ps), beatUS: betterThan(m.id, x, us) };
  });
  const scored = rows.filter(r => !Number.isNaN(r.x) && !Number.isNaN(r.beat));
  const avgBeat = scored.length ? scored.reduce((a, r) => a + r.beat, 0) / scored.length : NaN;
  const nBetter = scored.filter(r => r.beat >= 0.5).length;
  const best = scored.slice().sort((a, b) => b.beat - a.beat)[0], worst = scored.slice().sort((a, b) => a.beat - b.beat)[0];

  // ---- header card
  const head = el('div', { class: 'card' });
  const left = el('div', {}, [
    el('div', { class: 'name', text: h.name }),
    el('div', { class: 'meta', html: `${h.city ? h.city + ', ' : ''}${stateName(h.state)}${h.county ? ' · ' + h.county + ' County' : ''} · CMS ID ${h.id}<br>${h.type} · ${h.own} · ${h.er ? 'Emergency department' : 'No emergency department'}${h.stars ? ` · CMS overall rating ${h.stars} of 5` : ' · no CMS overall rating'}` })
  ]);
  const right = el('div', {}, [el('div', { class: 'kicker', text: 'Compared against' }), peerChips(h),
    el('p', { class: 'caption', text: `${peers.length.toLocaleString()} hospitals in ${label}${inPeers ? '' : ' (this hospital is outside the peer group; it is still placed on the peer distribution)'}` })]);
  head.append(el('div', { class: 'rc-head' }, [left, right]));
  const kp = el('div', { class: 'rc-kpis' });
  kp.append(el('div', { class: 'rc-kpi' }, [el('div', { class: 'v', text: Number.isNaN(avgBeat) ? '–' : Math.round(avgBeat * 100) + '%' }), el('div', { class: 'l', text: `of peers beaten on average across ${scored.length} reported measures` })]));
  kp.append(el('div', { class: 'rc-kpi' }, [el('div', { class: 'v', text: scored.length ? `${nBetter} of ${scored.length}` : '–' }), el('div', { class: 'l', text: 'measures at or better than the peer median' })]));
  kp.append(el('div', { class: 'rc-kpi' }, [el('div', { class: 'v', style: 'font-size:18px', text: best ? best.m.short : '–' }), el('div', { class: 'l', html: best ? `strongest (beats ${Math.round(best.beat * 100)}%) · weakest: <b>${worst.m.short}</b> (beats ${Math.round(worst.beat * 100)}%)` : 'no reported measures' })]));
  head.append(kp);
  const actions = el('div', { class: 'row', style: 'margin-top:14px' }, [
    el('button', { class: 'btn', text: 'Compare in the table', onclick: () => go('compare', { h: h.id }) }),
    el('button', { class: 'btn', text: 'See on the map', onclick: () => go('map', { st: h.state, m: 'MORT_30_HF' }) }),
    el('button', { class: 'btn-ghost', text: 'Download this card (CSV)', onclick: () => downloadCSV(`${h.id}_report_card.csv`, rows, [
      { key: 'measure', get: r => r.m.id }, { key: 'label', get: r => r.m.short }, { key: 'group', get: r => D.groups[r.m.group] }, { key: 'direction', get: r => r.m.hib ? 'higher is better' : 'lower is better' },
      { key: 'value', get: r => Number.isNaN(r.x) ? '' : r.x }, { key: 'peer_median', get: r => Number.isNaN(r.pmed) ? '' : +r.pmed.toFixed(3) }, { key: 'us_median', get: r => Number.isNaN(r.umed) ? '' : +r.umed.toFixed(3) },
      { key: 'share_of_peers_beaten', get: r => Number.isNaN(r.beat) ? '' : +r.beat.toFixed(3) }, { key: 'share_of_us_beaten', get: r => Number.isNaN(r.beatUS) ? '' : +r.beatUS.toFixed(3) }, { key: 'n_peers_reporting', get: r => r.ps.length }]) })
  ]);
  head.append(actions);
  body.append(head);

  // ---- groups
  const card = el('div', { class: 'card' });
  card.append(el('div', { class: 'row', style: 'justify-content:space-between' }, [el('h2', { text: 'Every key measure' }), el('span', { class: 'caption', style: 'margin:0', html: `<span class="key" style="background:${T.deemph}"></span> peers &nbsp; <span class="key" style="background:${T.blue};border-radius:50%;width:9px"></span> this hospital &nbsp; | peer median &nbsp; <span style="color:${T.axis}">|</span> U.S. median` })]));
  const pending = [];
  for (const g of Object.keys(D.groups)) {
    const grp = rows.filter(r => r.m.group === g);
    const sec = el('div', { class: 'rc-group' });
    const nrep = grp.filter(r => !Number.isNaN(r.x)).length;
    sec.append(el('h3', {}, [document.createTextNode(D.groups[g]), el('span', { text: `${nrep} of ${grp.length} reported` })]));
    for (const r of grp) sec.append(rowEl(r, label, pending));
    card.append(sec);
  }
  card.append(el('p', { class: 'caption', text: 'Bars: distribution of the peer group between its 1st and 99th percentiles. Badge: share of peers this hospital beats, oriented by each measure’s direction. Sources: CMS Care Compare, July 2026.' }));
  card.append(sqlButton({ file: '06_national_percentile' }));
  body.append(card);
  // strips need their real pixel width, so draw them once the card is in the document
  const draw = () => pending.forEach(([c, r]) => drawStrip(c, r, label));
  draw();
  if (!render.resizeBound) { render.resizeBound = true; let t; addEventListener('resize', () => { clearTimeout(t); t = setTimeout(() => current && render(), 200); }); }
}

function rowEl(r, label, pending) {
  const na = Number.isNaN(r.x);
  const row = el('div', { class: 'rc-row' + (na ? ' na' : '') });
  row.append(el('div', { class: 'lbl', html: `${r.m.short}<small>${r.m.hib ? 'higher is better' : 'lower is better'}${r.m.unit && r.m.unit !== '%' ? ' · ' + r.m.unit : ''}</small>` }));
  const strip = el('div', { class: 'strip' }); row.append(strip);
  row.append(el('div', { class: 'val', text: na ? 'not reported' : fmtVal(r.m, r.x) }));
  row.append(el('div', { class: 'bdg' }, badge(r.beat)));
  pending.push([strip, r]);
  return row;
}

function drawStrip(container, r, label) {
  const W = Math.max(160, container.clientWidth || 320), H = 34, pad = 6;
  container.innerHTML = '';
  const svg = d3.select(container).append('svg').attr('viewBox', `0 0 ${W} ${H}`).attr('width', W).attr('height', H);
  const ps = r.ps; if (!ps.length && Number.isNaN(r.x)) return;
  let lo = ps.length ? ps[Math.floor(ps.length * 0.01)] : r.x, hi = ps.length ? ps[Math.min(ps.length - 1, Math.ceil(ps.length * 0.99))] : r.x;
  if (!Number.isNaN(r.x)) { lo = Math.min(lo, r.x); hi = Math.max(hi, r.x); }
  if (!Number.isNaN(r.umed)) { lo = Math.min(lo, r.umed); hi = Math.max(hi, r.umed); }
  if (hi === lo) { lo -= 1; hi += 1; }
  const x = d3.scaleLinear().domain([lo, hi]).range([pad, W - pad]);
  if (ps.length) {
    const b = bins(ps.filter(v => v >= lo && v <= hi), 36, lo, hi), max = d3.max(b, d => d.n) || 1;
    svg.append('g').selectAll('rect').data(b).join('rect')
      .attr('x', d => x(d.x0) + 0.5).attr('width', d => Math.max(0, x(d.x1) - x(d.x0) - 1)).attr('y', d => H - 4 - 22 * d.n / max).attr('height', d => 22 * d.n / max)
      .attr('fill', T.deemph).attr('opacity', .8);
  }
  if (!Number.isNaN(r.umed)) svg.append('line').attr('x1', x(r.umed)).attr('x2', x(r.umed)).attr('y1', 5).attr('y2', H - 4).attr('stroke', T.axis).attr('stroke-width', 1.5);
  if (!Number.isNaN(r.pmed)) svg.append('line').attr('x1', x(r.pmed)).attr('x2', x(r.pmed)).attr('y1', 3).attr('y2', H - 2).attr('stroke', T.ink2).attr('stroke-width', 1.5);
  if (!Number.isNaN(r.x)) svg.append('circle').attr('cx', x(r.x)).attr('cy', H / 2).attr('r', 5.5).attr('fill', T.blue).attr('stroke', T.surface).attr('stroke-width', 2);
  svg.append('rect').attr('x', 0).attr('y', 0).attr('width', W).attr('height', H).attr('fill', 'transparent')
    .on('mousemove', (ev) => tip.show(`<b>${r.m.short}</b><div class="tip-sub">${r.m.desc}</div>` +
      `<div>This hospital: <b>${fmtVal(r.m, r.x)}</b>${Number.isNaN(r.beat) ? '' : ` · beats ${Math.round(r.beat * 100)}% of ${label}`}</div>` +
      `<div class="tip-sub">Peer median ${fmtVal(r.m, r.pmed)} (n = ${ps.length.toLocaleString()}) · U.S. median ${fmtVal(r.m, r.umed)} (n = ${r.us.length.toLocaleString()})${Number.isNaN(r.beatUS) ? '' : ` · beats ${Math.round(r.beatUS * 100)}% nationally`}</div>`, ev))
    .on('mouseleave', () => tip.hide());
}

export default { name: 'report', mount, show };
