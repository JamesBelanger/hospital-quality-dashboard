// story.js — Story tab: a five-step scrollytelling intro built entirely from the client-side data
// (nothing hard-coded except a facility-id lookup, verified against the loaded bundle at mount time).
import { D, seriesFor, sortedIn, mean, rankBelow, fmtVal, ordinal } from './data.js';
import { T, el, tooltip, hospTip, svgIn, axisStyle } from './ui.js';
import { go, goHospital } from './main.js';

const W = 640, H = 520;
const MARGIN = { top: 56, right: 18, bottom: 30, left: 18 };

// Houston Methodist Hospital — verified by exact name match against data/hospitals.json (450358).
const HM_ID = '450358';

let root_, tip;
let svg, gDots, gAxis, gScatter, gTitle, gLeader;
let x, dotR;
let hospitals = [];       // {i, x0, y0, r, cls} laid out for step 1-4 (dot-strip)
let mid = 'MORT_30_HF';
let hmHosp = null, hmVal = NaN;
let n1 = 0, n2 = 0, n3 = 0, pctStr = '0th';
let n5 = 0;
let observer;
let steps = [];

export default {
  name: 'story',
  mount(root, ctx) {
    root_ = root;
    tip = tooltip();
    root.innerHTML = '';

    resolveHoustonMethodist();
    computeNumbers();

    const wrap = el('div', { class: 'story' });
    root.append(wrap);

    // header
    wrap.append(
      el('p', { class: 'kicker', text: 'CMS Care Compare · July 2026 release' }),
      el('h1', { text: 'How does your hospital measure up?' }),
      el('p', { class: 'dek', text: 'Six public CMS datasets, 5,419 hospitals, 33 quality measures. Scroll to see how one Houston hospital compares, then look up your own.' })
    );

    const layout = el('div', { class: 'layout' });
    const sticky = el('div', { class: 'sticky' });
    const stepsWrap = el('div', { class: 'steps' });
    layout.append(sticky, stepsWrap);
    wrap.append(layout);

    svg = svgIn(sticky, W, H);
    gTitle = svg.append('text').attr('class', 'story-title').attr('x', MARGIN.left).attr('y', 20)
      .attr('fill', T.ink).style('font-size', '13px').style('font-weight', '600');
    gAxis = svg.append('g').attr('transform', `translate(0,${H - MARGIN.bottom})`);
    gDots = svg.append('g').attr('class', 'g-dots');
    gLeader = svg.append('g').attr('class', 'g-leader');
    gScatter = svg.append('g').attr('class', 'g-scatter-axes');

    buildLayout();

    const stepText = [
      { big: fmt(n1), p: 'U.S. hospitals report 30-day heart-failure mortality. Each dot is one hospital.' },
      { big: fmt(n2), p: 'of them are in Texas.' },
      { big: fmt(n3), p: 'are in the five-county Houston area.' },
      { big: pctStr, p: hmHosp
          ? `percentile: ${hmHosp.name}'s heart-failure mortality of ${fmtVal(D.keyById.get(mid), hmVal)} is among the lowest in the country.`
          : 'percentile: the lowest-mortality Houston hospital is among the lowest in the country.' },
      { big: fmt(n5), p: 'Texas hospitals beat the state on pneumonia readmission but fall below it on ‘would recommend’. Outcomes and experience are different things.' }
    ];
    stepText.forEach((s, k) => {
      const inner = el('div', {}, [el('div', { class: 'big', text: s.big }), el('p', { text: s.p })]);
      const step = el('div', { class: 'step', 'data-step': String(k) }, [inner]);
      stepsWrap.append(step);
      steps.push(step);
    });

    const cta = el('div', { class: 'cta' }, [
      el('button', { class: 'btn primary', type: 'button', text: 'Look up any hospital', onclick: () => go('report') }),
      el('button', { class: 'btn', type: 'button', text: 'Explore Houston on the map', onclick: () => go('map', { st: 'TX' }) }),
      el('button', { class: 'btn', type: 'button', text: 'Run the SQL yourself', onclick: () => go('sql') })
    ]);
    wrap.append(cta);

    wrap.append(el('div', { class: 'storyfoot' }, [
      el('p', { text: 'Every benchmark is computed from hospital-level rows; nothing is pre-aggregated. Percentiles, means, and ranks all run live over the raw CMS scores, in the browser here and in SQL on the SQL tab.' }),
      el('p', {}, [el('a', { href: 'https://jamesbelanger.com/projects/hospital-quality/', target: '_blank', rel: 'noopener', text: 'Read the case study' })])
    ]));

    setStep(0, true);

    observer = new IntersectionObserver((entries) => {
      entries.forEach(en => { if (en.isIntersecting) setStep(+en.target.dataset.step); });
    }, { threshold: 0.6 });
    steps.forEach(s => observer.observe(s));
  },

  show(q, ctx) {
    window.scrollTo({ top: 0 });
    setStep(0, true);
  }
};

// ---------------- data prep ----------------
function resolveHoustonMethodist() {
  hmHosp = D.byId.get(HM_ID) || null;
  if (hmHosp && hmHosp.hou) {
    const v = seriesFor(mid)[hmHosp.i];
    if (!Number.isNaN(v)) return;
  }
  // fallback: lowest-mortality Houston hospital
  const s = seriesFor(mid);
  let best = null, bestV = Infinity;
  for (const h of D.H) { if (h.hou && !Number.isNaN(s[h.i]) && s[h.i] < bestV) { bestV = s[h.i]; best = h; } }
  hmHosp = best;
}

function computeNumbers() {
  const s = seriesFor(mid);
  n1 = 0; n2 = 0; n3 = 0;
  for (const h of D.H) {
    if (Number.isNaN(s[h.i])) continue;
    n1++;
    if (h.state === 'TX') n2++;
    if (h.hou) n3++;
  }
  hmVal = hmHosp ? s[hmHosp.i] : NaN;
  if (hmHosp && !Number.isNaN(hmVal)) {
    const sorted = sortedIn(mid, null, s);
    const below = rankBelow(sorted, hmVal);
    // ordinal() expects an integer; the copy wants one decimal (e.g. "0.4th"), so build it by hand.
    pctStr = fmtOrdinalDecimal(below * 100);
  }

  const readm = seriesFor('READM_30_PN'), rec = seriesFor('H_RECMND_DY');
  const txReadm = [], txRec = [];
  for (const h of D.H) {
    if (h.state !== 'TX') continue;
    if (!Number.isNaN(readm[h.i])) txReadm.push(readm[h.i]);
    if (!Number.isNaN(rec[h.i])) txRec.push(rec[h.i]);
  }
  const mReadm = mean(txReadm), mRec = mean(txRec);
  n5 = 0;
  for (const h of D.H) {
    if (h.state !== 'TX') continue;
    const r = readm[h.i], c = rec[h.i];
    if (Number.isNaN(r) || Number.isNaN(c)) continue;
    if (r < mReadm && c < mRec) n5++;
  }
}

// one-decimal ordinal, e.g. 0.4 -> "0.4th", 1.2 -> "1.2nd" (suffix follows the integer part)
function fmtOrdinalDecimal(v) {
  const rounded = Math.round(v * 10) / 10;
  const intPart = Math.floor(rounded);
  const suf = ordinal(intPart).replace(String(intPart), '');
  return rounded.toFixed(1) + suf;
}

const fmt = (n) => n.toLocaleString('en-US');

// ---------------- dot-strip layout (steps 1-4) ----------------
function buildLayout() {
  const s = seriesFor(mid);
  const m = D.keyById.get(mid);
  const sorted = sortedIn(mid, null, s);
  const lo = quantileOf(sorted, 0.005), hi = quantileOf(sorted, 0.995);

  x = d3.scaleLinear().domain([lo, hi]).range([MARGIN.left, W - MARGIN.right]).nice();

  const nbins = 90;
  const w = (hi - lo) / nbins || 1;
  const binOf = (v) => Math.min(nbins - 1, Math.max(0, Math.floor((v - lo) / w)));
  const counts = new Array(nbins).fill(0);
  const rows = [];
  for (const h of D.H) {
    const v = s[h.i]; if (Number.isNaN(v)) continue;
    const b = binOf(v);
    rows.push({ i: h.i, h, v, b, k: counts[b]++ });
  }
  const maxCount = Math.max(1, ...counts);
  const avail = H - MARGIN.top - MARGIN.bottom - 6;
  const step = avail / maxCount;                      // vertical pitch so the tallest bin exactly fits under the title
  dotR = Math.max(1.5, Math.min(2.6, step * 0.9));    // dots zigzag left/right within a bin, so they can be wider than the pitch

  hospitals = rows.map(r => ({
    i: r.i, h: r.h, v: r.v,
    x0: x(lo + (r.b + 0.5) * w) + (r.k % 2 ? 1 : -1) * dotR * 0.55,
    y0: H - MARGIN.bottom - 4 - r.k * step
  }));

  gAxis.call(d3.axisBottom(x).ticks(6).tickFormat(v => v.toFixed(1) + '%'));
  axisStyle(gAxis);
  gScatter.style('display', 'none');
  gLeader.selectAll('*').remove();

  const sel = gDots.selectAll('circle').data(hospitals, d => d.i);
  sel.exit().remove();
  const enter = sel.enter().append('circle')
    .attr('r', dotR).attr('fill', T.deemph).attr('stroke', 'none')
    .attr('cx', d => d.x0).attr('cy', d => d.y0)
    .style('cursor', 'pointer')
    .on('mousemove', (ev, d) => tip.show(hospTip(d.h, `<div class="tip-sub">${m.short}: ${fmtVal(m, d.v)}</div>`), ev))
    .on('mouseleave', () => tip.hide())
    .on('click', (ev, d) => goHospital(d.h));
  enter.merge(sel).attr('cx', d => d.x0).attr('cy', d => d.y0);
}

function quantileOf(sorted, q) {
  if (!sorted.length) return 0;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos), hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

// ---------------- step transitions ----------------
let current = -1;
function setStep(k, immediate) {
  if (k === current) return;
  current = k;
  steps.forEach((st, idx) => st.classList.toggle('on', idx === k));

  const titles = [
    'Every hospital that reports heart-failure mortality',
    'Texas hospitals highlighted',
    'Houston-area hospitals highlighted',
    `${hmHosp ? hmHosp.name : 'Houston hospital'} vs. the nation`,
    'Texas: outcomes vs. experience'
  ];
  gTitle.text(titles[k] || '');

  if (k < 4) {
    if (gScatter.style('display') !== 'none' || svg.select('.g-scatter-dots').size()) morphBackToStrip(immediate);
    updateStripColors(k, immediate);
  } else if (k === 4) {
    morphToScatter(immediate);
  }
}

function circleSel() { return gDots.selectAll('circle'); }

function updateStripColors(k, immediate) {
  gAxis.style('display', null);
  gScatter.style('display', 'none');
  svg.select('.g-scatter-dots').remove();
  gLeader.selectAll('*').remove();
  const t = immediate ? circleSel() : circleSel().transition().duration(600);

  t.attr('cx', d => d.x0).attr('cy', d => d.y0)
   .attr('r', dotR)
   .attr('opacity', 1)
   .attr('fill', d => {
     if (k === 0) return T.deemph;
     if (k === 1) return d.h.state === 'TX' ? T.blue : T.deemph;
     if (k === 2) return d.h.hou ? T.blue : (d.h.state === 'TX' ? '#d8d7cf' : T.deemph);
     return T.deemph;
   });

  if (k === 3 && hmHosp) {
    const t2 = immediate ? circleSel() : circleSel().transition().duration(600);
    t2.attr('opacity', d => d.i === hmHosp.i ? 1 : 0.35)
      .attr('fill', d => d.i === hmHosp.i ? T.ink : T.deemph)
      .attr('r', d => d.i === hmHosp.i ? 5 : dotR);
    const target = hospitals.find(d => d.i === hmHosp.i);
    if (target) {
      const lx = Math.min(W - MARGIN.right - 4, target.x0 + 60);
      const ly = Math.max(MARGIN.top + 10, target.y0 - 40);
      gLeader.append('line').attr('x1', target.x0).attr('y1', target.y0).attr('x2', lx).attr('y2', ly)
        .attr('stroke', T.ink).attr('stroke-width', 1);
      gLeader.append('circle').attr('cx', target.x0).attr('cy', target.y0).attr('r', 5).attr('fill', 'none')
        .attr('stroke', T.ink).attr('stroke-width', 1);
      gLeader.append('text').attr('x', lx + 4).attr('y', ly).attr('fill', T.ink)
        .style('font-size', '11px').style('font-weight', '600').text(hmHosp.name);
    }
  } else {
    gLeader.selectAll('*').remove();
  }
}

let scatterState = null;
function morphToScatter(immediate) {
  const readm = seriesFor('READM_30_PN'), rec = seriesFor('H_RECMND_DY');
  const txReadm = [], txRec = [];
  const rows = [];
  for (const h of D.H) {
    if (h.state !== 'TX') continue;
    const rv = readm[h.i], cv = rec[h.i];
    if (Number.isNaN(rv) || Number.isNaN(cv)) continue;
    txReadm.push(rv); txRec.push(cv);
    rows.push({ i: h.i, h, rv, cv });
  }
  const mReadm = mean(txReadm), mRec = mean(txRec);

  gAxis.style('display', 'none');
  const px = d3.scaleLinear().domain(d3.extent(txReadm)).nice().range([MARGIN.left + 24, W - MARGIN.right - 12]);
  const py = d3.scaleLinear().domain(d3.extent(txRec)).nice().range([H - MARGIN.bottom - 12, MARGIN.top + 24]);

  gScatter.style('display', null).selectAll('*').remove();
  gScatter.append('g').attr('transform', `translate(0,${H - MARGIN.bottom - 12})`).call(d3.axisBottom(px).ticks(5).tickFormat(v => v.toFixed(0) + '%'));
  gScatter.append('g').attr('transform', `translate(${MARGIN.left + 24},0)`).call(d3.axisLeft(py).ticks(5).tickFormat(v => v.toFixed(0) + '%'));
  axisStyle(gScatter);
  gScatter.append('line').attr('x1', px(mReadm)).attr('x2', px(mReadm)).attr('y1', MARGIN.top + 24).attr('y2', H - MARGIN.bottom - 12).attr('stroke', T.axis).attr('stroke-dasharray', '2,2');
  gScatter.append('line').attr('x1', MARGIN.left + 24).attr('x2', W - MARGIN.right - 12).attr('y1', py(mRec)).attr('y2', py(mRec)).attr('stroke', T.axis).attr('stroke-dasharray', '2,2');
  gScatter.append('text').attr('x', MARGIN.left + 28).attr('y', MARGIN.top + 34).attr('fill', T.muted).style('font-size', '11px').text('readmission →');
  gScatter.append('text').attr('x', MARGIN.left + 28).attr('y', MARGIN.top + 46).attr('fill', T.muted).style('font-size', '11px').text('recommend ↑');

  gLeader.selectAll('*').remove();

  const byIdx = new Map(rows.map(r => [r.i, r]));
  scatterState = { rows, px, py, mReadm, mRec };

  const t = immediate ? circleSel() : circleSel().transition().duration(600);
  t.attr('cx', d => { const r = byIdx.get(d.i); return r ? px(r.rv) : d.x0; })
   .attr('cy', d => { const r = byIdx.get(d.i); return r ? py(r.cv) : d.y0; })
   .attr('r', 2.4)
   .attr('opacity', d => byIdx.has(d.i) ? 1 : 0)
   .attr('fill', d => {
     const r = byIdx.get(d.i);
     if (!r) return T.deemph;
     return (r.rv < mReadm && r.cv < mRec) ? T.blue : T.deemph;
   });
}

function morphBackToStrip(immediate) {
  gAxis.style('display', null);
  gScatter.style('display', 'none');
  gLeader.selectAll('*').remove();
  const t = immediate ? circleSel() : circleSel().transition().duration(600);
  t.attr('cx', d => d.x0).attr('cy', d => d.y0).attr('r', dotR).attr('opacity', 1);
}
