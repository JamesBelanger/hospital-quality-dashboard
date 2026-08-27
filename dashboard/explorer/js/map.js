// map.js — Map view: national state choropleth (median, oriented so darker = better) that zooms
// into a county-level dot map of hospitals colored by percentile within the current peer group.
import { D, seriesFor, sortedIn, median, betterThan, fmtVal, fmtPct, stateName, STATE_FIPS, dataUrl } from './data.js';
import { T, el, tooltip, hospTip, sqlButton, svgIn, seqScale } from './ui.js';
import { onPeersChange, goHospital, setQuery } from './main.js';

const WIDTH = 960, HEIGHT = 600;
const NA_FILL = '#eeede8';

// FIPS -> state abbreviation (inverse of STATE_FIPS), built once.
const FIPS_STATE = {};
for (const [ab, fips] of Object.entries(STATE_FIPS)) FIPS_STATE[fips] = ab;

let root_, ctx_;
let svg, gStates, gCounties, gDots, zoomG;
let statesFC, countiesTopo, statesTopo, path, projection;
let sel = { m: 'MORT_30_HF', st: null };
let tip;
let level = 'us'; // 'us' | 'state'

export default {
  name: 'map',
  mount(root, ctx) {
    root_ = root; ctx_ = ctx;
    tip = tooltip();
    root.innerHTML = '';

    const controls = el('div', { class: 'controls' });
    const measureSel = el('select', { 'aria-label': 'Measure' });
    for (const [gid, glabel] of Object.entries(D.groups)) {
      const og = el('optgroup', { label: glabel });
      og.append(...D.key.filter(m => m.group === gid).map(m => el('option', { value: m.id, text: m.short })));
      measureSel.append(og);
    }
    measureSel.addEventListener('change', () => { sel.m = measureSel.value; setQuery({ m: sel.m }); recolorAll(); });

    const houBtn = el('button', { class: 'btn-ghost', type: 'button', text: 'Houston area' });
    houBtn.addEventListener('click', () => { zoomHouston(); });
    const resetBtn = el('button', { class: 'btn-ghost', type: 'button', text: 'Reset to U.S.' });
    resetBtn.addEventListener('click', () => { sel.st = null; setQuery({ st: undefined }); zoomToUS(); });

    controls.append(el('label', {}, ['Measure ', measureSel]), houBtn, resetBtn);

    const panel = el('div', { class: 'card flush' });
    const mapWrap = el('div');
    panel.append(mapWrap);

    const legend = el('div', { class: 'maplegend' });
    const ramp = el('div', { class: 'ramp' });
    ramp.append(...T.seq.map(c => el('span', { style: `background:${c}` })));
    legend.append(el('span', { text: 'worse' }), ramp, el('span', { text: 'better (percentile within peers)' }),
      el('span', { style: 'margin-left:14px' }, [
        el('span', { class: 'key', style: 'border-radius:50%;background:#fff;border:1px solid ' + T.deemph, html: '' }),
        ' not reported'
      ]));

    const caption = el('div', { class: 'caption', id: 'map-caption' },
      'Locations are ZIP-code centroids, so hospitals sharing a ZIP overlap.');

    root.append(controls, panel, legend, caption, sqlButton({ file: '10_county_rollup' }));

    mapWrap.innerHTML = '<div class="loading">Loading map…</div>';

    Promise.all([
      fetch(dataUrl('geo/states-10m.json')).then(r => r.json()),
      fetch(dataUrl('geo/counties-10m.json')).then(r => r.json())
    ]).then(([statesTopoJ, countiesTopoJ]) => {
      statesTopo = statesTopoJ; countiesTopo = countiesTopoJ;
      statesFC = topojson.feature(statesTopo, statesTopo.objects.states);

      mapWrap.innerHTML = '';
      svg = svgIn(mapWrap, WIDTH, HEIGHT);
      projection = d3.geoAlbersUsa().fitSize([WIDTH, HEIGHT], statesFC);
      path = d3.geoPath(projection);

      zoomG = svg.append('g');
      gStates = zoomG.append('g').attr('class', 'g-states');
      gCounties = zoomG.append('g').attr('class', 'g-counties').style('display', 'none');
      gDots = zoomG.append('g').attr('class', 'g-dots').style('display', 'none');

      drawStates();
      measureSel.value = sel.m;
      if (sel.st) zoomToState(sel.st, false); else zoomToUS(false);
    }).catch(err => { mapWrap.innerHTML = '<div class="loading">Could not load map data.</div>'; console.error(err); });

    onPeersChange(() => { if (level === 'state') recolorDots(); });
  },

  show(q, ctx) {
    ctx_ = ctx;
    sel.m = D.keyById.has(q.m) ? q.m : 'MORT_30_HF';
    sel.st = q.st || null;
    const measureSel = root_.querySelector('select');
    if (measureSel) measureSel.value = sel.m;
    if (!svg) return; // still loading; mount()'s .then() will pick up sel
    if (sel.st) { if (level !== 'state' || currentStateAb() !== sel.st) zoomToState(sel.st); else recolorDots(); }
    else if (level !== 'us') zoomToUS();
    else recolorAll();
  }
};

function currentStateAb() { return zoomG.attr('data-st') || null; }

// ---------------- national choropleth ----------------
function nationalStateStats(mid) {
  const s = seriesFor(mid);
  const m = D.keyById.get(mid);
  const allSorted = sortedIn(mid, null, s);
  const byState = new Map();
  for (const h of D.H) {
    if (!byState.has(h.state)) byState.set(h.state, []);
    if (!Number.isNaN(s[h.i])) byState.get(h.state).push(s[h.i]);
  }
  const stats = new Map();
  for (const [ab, vals] of byState) {
    if (vals.length < 3) { stats.set(ab, { n: vals.length, med: NaN, pct: NaN }); continue; }
    vals.sort((a, b) => a - b);
    const med = median(vals);
    const pct = betterThan(mid, med, allSorted, m.hib);
    stats.set(ab, { n: vals.length, med, pct });
  }
  return stats;
}

function drawStates() {
  const scale = seqScale([0, 1]);
  const stats = nationalStateStats(sel.m);
  const m = D.keyById.get(sel.m);

  const sel_ = gStates.selectAll('path.state').data(statesFC.features, d => d.id);
  sel_.enter().append('path')
    .attr('class', 'state')
    .attr('d', path)
    .attr('stroke', '#fff')
    .attr('stroke-width', 0.75)
    .style('cursor', 'pointer')
    .on('mousemove', (ev, d) => {
      const ab = FIPS_STATE[d.id]; const st = stats.get(ab);
      if (!st || st.n < 3) { tip.show(`<b>${d.properties.name}</b><div class="tip-sub">n < 3 hospitals reporting</div>`, ev); return; }
      tip.show(`<b>${d.properties.name}</b><div class="tip-sub">${fmtVal(m, st.med)} median · ${st.n.toLocaleString()} hospitals reporting</div><div class="tip-sub">beats ${fmtPct(st.pct)} of U.S. hospitals</div>`, ev);
    })
    .on('mousemove.move', (ev) => tip.move(ev))
    .on('mouseleave', () => tip.hide())
    .on('click', (ev, d) => { const ab = FIPS_STATE[d.id]; if (ab) { sel.st = ab; setQuery({ st: ab }); zoomToState(ab); } })
    .merge(sel_)
    .attr('fill', d => {
      const ab = FIPS_STATE[d.id]; const st = stats.get(ab);
      return (!st || st.n < 3 || Number.isNaN(st.pct)) ? NA_FILL : scale(st.pct);
    });
}

function recolorAll() {
  if (!svg) return;
  const stats = nationalStateStats(sel.m);
  const scale = seqScale([0, 1]);
  gStates.selectAll('path.state').attr('fill', d => {
    const ab = FIPS_STATE[d.id]; const st = stats.get(ab);
    return (!st || st.n < 3 || Number.isNaN(st.pct)) ? NA_FILL : scale(st.pct);
  });
  const m = D.keyById.get(sel.m);
  gStates.selectAll('path.state').on('mousemove', (ev, d) => {
    const ab = FIPS_STATE[d.id]; const st = stats.get(ab);
    if (!st || st.n < 3) { tip.show(`<b>${d.properties.name}</b><div class="tip-sub">n < 3 hospitals reporting</div>`, ev); return; }
    tip.show(`<b>${d.properties.name}</b><div class="tip-sub">${fmtVal(m, st.med)} median · ${st.n.toLocaleString()} hospitals reporting</div><div class="tip-sub">beats ${fmtPct(st.pct)} of U.S. hospitals</div>`, ev);
  });
  if (level === 'state') recolorDots();
}

// ---------------- state-level: counties + hospital dots ----------------
function stateHospitals(ab) {
  return D.H.filter(h => h.state === ab && h.lat != null && h.lon != null);
}
function stateHospitalsAll(ab) { return D.H.filter(h => h.state === ab); }

function drawCounties(ab) {
  const fips = STATE_FIPS[ab];
  const countiesFC = topojson.feature(countiesTopo, countiesTopo.objects.counties);
  const feats = countiesFC.features.filter(f => f.id.slice(0, 2) === fips);
  const s = gCounties.selectAll('path.county').data(feats, d => d.id);
  s.exit().remove();
  s.enter().append('path')
    .attr('class', 'county')
    .attr('fill', '#f3f3ef')
    .attr('stroke', '#d9d8d0')
    .attr('stroke-width', 0.75)
    .merge(s)
    .attr('d', path);
}

function drawDots(ab, animate) {
  const hs = stateHospitals(ab);
  const k = currentZoomK();
  const scale = seqScale([0, 1]);
  const s = gDots.selectAll('circle.hosp').data(hs, d => d.id);
  s.exit().remove();
  const enter = s.enter().append('circle')
    .attr('class', 'hosp')
    .attr('stroke', '#fff')
    .attr('stroke-width', 1)
    .style('cursor', 'pointer')
    .attr('cx', d => projection([d.lon, d.lat])[0])
    .attr('cy', d => projection([d.lon, d.lat])[1])
    .on('mousemove', (ev, d) => { tip.show(hospTip(d, dotExtra(d)), ev); })
    .on('mouseleave', () => tip.hide())
    .on('click', (ev, d) => goHospital(d));
  enter.merge(s)
    .attr('cx', d => projection([d.lon, d.lat])[0])
    .attr('cy', d => projection([d.lon, d.lat])[1])
    .attr('r', d => (d.hou ? 5.5 : 4.5) / k);
  recolorDots(scale);
}

function dotExtra(h) {
  const m = D.keyById.get(sel.m);
  const s = seriesFor(sel.m);
  const x = s[h.i];
  if (Number.isNaN(x)) return '<div class="tip-sub">not reported</div>';
  const sorted = sortedIn(sel.m, ctx_.peers);
  const b = betterThan(sel.m, x, sorted, m.hib);
  return `<div class="tip-sub">${m.short}: ${fmtVal(m, x)}</div><div class="tip-sub">beats ${fmtPct(b)} of peer group</div>`;
}

function recolorDots(scale) {
  if (!gDots) return;
  scale = scale || seqScale([0, 1]);
  const s = seriesFor(sel.m);
  const m = D.keyById.get(sel.m);
  const sorted = sortedIn(sel.m, ctx_.peers);
  gDots.selectAll('circle.hosp')
    .attr('fill', d => {
      const x = s[d.i];
      if (Number.isNaN(x)) return '#fff';
      const b = betterThan(sel.m, x, sorted, m.hib);
      return Number.isNaN(b) ? '#fff' : scale(b);
    })
    .attr('stroke', d => Number.isNaN(s[d.i]) ? T.deemph : '#fff');
  gDots.selectAll('circle.hosp').on('mousemove', (ev, d) => tip.show(hospTip(d, dotExtra(d)), ev));
  updateCaption();
}

function updateCaption() {
  const cap = root_.querySelector('#map-caption');
  if (!cap || level !== 'state' || !sel.st) {
    if (cap) cap.textContent = 'Locations are ZIP-code centroids, so hospitals sharing a ZIP overlap.';
    return;
  }
  const all = stateHospitalsAll(sel.st);
  const shown = all.filter(h => h.lat != null && h.lon != null).length;
  cap.textContent = `Locations are ZIP-code centroids, so hospitals sharing a ZIP overlap. ${shown.toLocaleString()} hospitals shown / ${(all.length - shown).toLocaleString()} without a location.`;
}

// ---------------- zoom / navigation ----------------
let currentTransform = d3.zoomIdentity;
function currentZoomK() { return currentTransform.k || 1; }

function applyTransform(t, animate) {
  currentTransform = t;
  const sel_ = animate ? zoomG.transition().duration(600) : zoomG;
  sel_.attr('transform', t);
  if (animate) {
    zoomG.transition().duration(600).on('end', () => {
      gDots.selectAll('circle.hosp').attr('r', d => (d.hou ? 5.5 : 4.5) / currentZoomK());
    });
  } else {
    gDots.selectAll('circle.hosp').attr('r', d => (d.hou ? 5.5 : 4.5) / currentZoomK());
  }
}

function boundsTransform(feature) {
  const [[x0, y0], [x1, y1]] = path.bounds(feature);
  const dx = x1 - x0, dy = y1 - y0, cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  const k = Math.max(1, Math.min(8, 0.85 / Math.max(dx / WIDTH, dy / HEIGHT)));
  const tx = WIDTH / 2 - k * cx, ty = HEIGHT / 2 - k * cy;
  return d3.zoomIdentity.translate(tx, ty).scale(k);
}

function zoomToUS(animate = true) {
  level = 'us';
  zoomG.attr('data-st', '');
  gCounties.style('display', 'none');
  gDots.style('display', 'none');
  gStates.style('display', null);
  applyTransform(d3.zoomIdentity, animate);
  recolorAll();
  updateCaption();
}

function zoomToState(ab, animate = true) {
  const fips = STATE_FIPS[ab];
  const feature = statesFC.features.find(f => f.id === fips);
  if (!feature) return;
  level = 'state';
  sel.st = ab;
  zoomG.attr('data-st', ab);
  drawCounties(ab);
  gCounties.style('display', null);
  gStates.style('display', 'none');
  gDots.style('display', null);
  applyTransform(boundsTransform(feature), animate);
  drawDots(ab, animate);
  updateCaption();
}

function zoomHouston() {
  const hs = D.H.filter(h => h.hou && h.lat != null && h.lon != null);
  if (!hs.length) return;
  sel.st = 'TX';
  setQuery({ st: 'TX' });
  level = 'state';
  zoomG.attr('data-st', 'TX');
  drawCounties('TX');
  gCounties.style('display', null);
  gStates.style('display', 'none');
  gDots.style('display', null);
  drawDots('TX', false);
  const pts = hs.map(h => projection([h.lon, h.lat]));
  const x0 = Math.min(...pts.map(p => p[0])), x1 = Math.max(...pts.map(p => p[0]));
  const y0 = Math.min(...pts.map(p => p[1])), y1 = Math.max(...pts.map(p => p[1]));
  const dx = x1 - x0, dy = y1 - y0, cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  const k = Math.max(1, Math.min(10, 0.75 / Math.max(dx / WIDTH, dy / HEIGHT, 0.02)));
  const tx = WIDTH / 2 - k * cx, ty = HEIGHT / 2 - k * cy;
  applyTransform(d3.zoomIdentity.translate(tx, ty).scale(k), true);
  updateCaption();
}
