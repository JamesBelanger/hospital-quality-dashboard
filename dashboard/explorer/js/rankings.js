// rankings.js — "Rank hospitals your way" (weighted composite) + "Outcomes versus experience" (mismatch quadrant).
import { D, seriesFor, sortedIn, mean, betterThan, composite, fmtVal, fmtPct, scopeLabel } from './data.js';
import { T, el, tooltip, hospTip, sqlButton, downloadCSV, svgIn, axisStyle } from './ui.js';
import { onPeersChange, goHospital, setQuery } from './main.js';

const GKEYS = ['outcomes', 'readmissions', 'safety', 'timely', 'experience'];
const DEFAULT_W = { outcomes: 30, readmissions: 20, safety: 20, timely: 10, experience: 20 };
const ROW_H = 26, ROW_W = 900, MAX_ROWS = 25;
const PN_ID = 'READM_30_PN', RECMND_ID = 'H_RECMND_DY';

function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

function truncateName(s, n = 34) { return s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s; }

/** Path for a bar with a rounded RIGHT end only (left edge square). */
function roundedBarPath(x0, w, y, h, r) {
  if (w <= 0) return `M${x0},${y}h0v${h}h0Z`;
  const rr = Math.min(r, w);
  const x1 = x0 + w;
  return `M${x0},${y}H${x1 - rr}A${rr},${rr} 0 0 1 ${x1},${y + rr}V${y + h - rr}A${rr},${rr} 0 0 1 ${x1 - rr},${y + h}H${x0}Z`;
}

export default {
  name: 'rankings',
  mount(root, ctx) {
    const tip = tooltip();
    const weights = { ...DEFAULT_W };
    let mode = 'top'; // 'top' | 'bottom'

    root.append(
      el('div', { class: 'kicker', text: 'Custom scoring & outliers' }),
      el('h1', { text: 'Rankings' }),
      el('p', { class: 'dek', text: `Build a weighted composite ranking of ${scopeLabel(ctx.scope)}, or find hospitals whose outcomes and patient experience tell different stories.` })
    );

    // ---------------- Section 1: weighted composite ----------------
    const card1 = el('div', { class: 'card' });
    card1.append(el('h2', { text: 'Rank hospitals your way' }));
    card1.append(el('p', { class: 'sub', text: 'Set how much each of the five CMS measure groups counts, and the peer group re-ranks live.' }));

    const sliderWrap = el('div', { class: 'sliders' });
    const sliderEls = {};
    for (const g of GKEYS) {
      const pct = el('small', { text: '' });
      const labelText = el('span', { text: D.groups[g] + ' ' });
      const input = el('input', { type: 'range', min: '0', max: '100', step: '1', value: String(weights[g]), 'aria-label': D.groups[g] });
      input.addEventListener('input', () => { weights[g] = +input.value; renderWeightLabels(); scheduleRank(); });
      const s = el('div', { class: 'slider' }, [el('label', {}, [labelText, pct]), input]);
      sliderEls[g] = { input, pct };
      sliderWrap.append(s);
    }
    card1.append(sliderWrap);

    const chips1 = el('div', { class: 'controls' });
    const chipTop = el('button', { class: 'chip on', type: 'button', text: 'Top 25' });
    const chipBottom = el('button', { class: 'chip', type: 'button', text: 'Bottom 25' });
    chipTop.addEventListener('click', () => { mode = 'top'; chipTop.classList.add('on'); chipBottom.classList.remove('on'); renderList(); });
    chipBottom.addEventListener('click', () => { mode = 'bottom'; chipBottom.classList.add('on'); chipTop.classList.remove('on'); renderList(); });
    chips1.append(chipTop, chipBottom);
    card1.append(chips1);

    const listHost = el('div', {});
    card1.append(listHost);
    const caption1 = el('p', { class: 'caption' });
    card1.append(caption1);

    card1.append(el('p', { class: 'note', text: 'Illustrative composite: each measure is scored as the share of peers the hospital beats, averaged within group, then weighted. This is not the CMS Overall Star Rating methodology, and a hospital needs scores in at least two groups to be ranked.' }));

    const btnRow1 = el('div', { class: 'controls' });
    const csvBtn = el('button', { class: 'btn', type: 'button', text: 'Download ranking (CSV)' });
    csvBtn.addEventListener('click', () => downloadCurrentCSV());
    btnRow1.append(csvBtn, sqlButton({ file: '08_quality_composite' }));
    card1.append(btnRow1);
    root.append(card1);

    // ---------------- Section 2: mismatch quadrant ----------------
    const card2 = el('div', { class: 'card' });
    card2.append(el('h2', { text: 'Outcomes versus experience' }));
    card2.append(el('p', { class: 'sub', text: 'Pneumonia readmission rate against the share of patients who would definitely recommend the hospital. The lower-right quadrant is the mismatch: better outcomes, weaker experience.' }));
    const scatterHost = el('div', {});
    card2.append(scatterHost);
    const selControls = el('div', { class: 'controls', style: 'display:none' });
    const clearChip = el('button', { class: 'chip', type: 'button', text: 'Clear selection' });
    selControls.append(clearChip);
    card2.append(selControls);
    const selList = el('ul', { class: 'toplist' });
    card2.append(selList);
    card2.append(sqlButton({ file: '09_mismatch_finder' }));
    root.append(card2);

    let lastResults = [];
    let brush, brushG, xScale, yScale, points = [];

    function renderWeightLabels() {
      const total = GKEYS.reduce((a, g) => a + weights[g], 0) || 1;
      for (const g of GKEYS) sliderEls[g].pct.textContent = Math.round(100 * weights[g] / total) + '%';
    }
    renderWeightLabels();

    function computeRanking() { return composite(ctx.peers, weights); }

    function renderList() {
      const res = lastResults;
      const total = res.length;
      const n = Math.min(MAX_ROWS, total);
      const rows = total <= MAX_ROWS ? res : (mode === 'top' ? res.slice(0, n) : res.slice(-n).reverse());
      caption1.textContent = total === 0 ? 'no hospitals in this peer group have enough scored measures to rank'
        : total <= MAX_ROWS ? `showing all ${total} hospitals` : `showing the ${mode} 25 of ${total}`;

      const svg = svgIn(listHost, ROW_W, Math.max(rows.length * ROW_H, 1));
      const rankX = 0, rankW = 28, nameX = 34, nameW = 250, trackX = 300, trackW = 260, scoreX = 572, sqStart = 636, sq = 8, sqGap = 6;
      const barScale = d3.scaleLinear().domain([0, 100]).range([0, trackW]);
      const sqColor = d3.scaleQuantize().domain([0, 1]).range(T.seq);

      const g = svg.selectAll('g.row').data(rows, d => D.H[d.i].id);
      g.exit().transition().duration(300).style('opacity', 0).remove();

      const enter = g.enter().append('g').attr('class', 'row')
        .attr('transform', (d, i) => `translate(0,${i * ROW_H})`)
        .style('opacity', 0);

      enter.append('text').attr('class', 'rk').attr('x', rankX + rankW).attr('y', ROW_H / 2 + 4).attr('text-anchor', 'end')
        .attr('fill', T.muted).style('font-size', '12px').style('font-variant-numeric', 'tabular-nums');
      enter.append('text').attr('class', 'nm').attr('x', nameX).attr('y', ROW_H / 2 + 4)
        .attr('fill', T.ink).style('font-size', '13px').style('cursor', 'pointer')
        .on('click', (ev, d) => goHospital(D.H[d.i]))
        .on('mouseenter', (ev, d) => { tip.show(hospTip(D.H[d.i], groupExtra(d)), ev); })
        .on('mousemove', ev => tip.move(ev)).on('mouseleave', () => tip.hide());
      enter.append('path').attr('class', 'bar').attr('fill', T.blue);
      enter.append('text').attr('class', 'sc').attr('y', ROW_H / 2 + 4)
        .attr('fill', T.ink2).style('font-size', '12px').style('font-variant-numeric', 'tabular-nums');
      const sqG = enter.append('g').attr('class', 'sqs');
      GKEYS.forEach((gg, k) => sqG.append('rect').attr('class', 'g' + k)
        .attr('x', sqStart + k * (sq + sqGap)).attr('y', (ROW_H - sq) / 2).attr('width', sq).attr('height', sq));

      const merged = enter.merge(g);
      merged.select('text.rk').text(d => d.rank);
      merged.select('text.nm').text(d => truncateName(D.H[d.i].name));
      merged.select('text.sc').attr('x', d => trackX + barScale(d.score) + 8).text(d => d.score.toFixed(1));
      GKEYS.forEach((gg, k) => merged.select('g.sqs rect.g' + k)
        .attr('fill', d => d.groups[gg] !== undefined ? sqColor(d.groups[gg]) : 'none')
        .attr('stroke', d => d.groups[gg] !== undefined ? 'none' : T.deemph));
      merged.on('mouseenter', (ev, d) => tip.show(hospTip(D.H[d.i], groupExtra(d)), ev))
        .on('mousemove', ev => tip.move(ev)).on('mouseleave', () => tip.hide());

      merged.transition().duration(500)
        .attr('transform', (d, i) => `translate(0,${i * ROW_H})`)
        .style('opacity', 1)
        .select('path.bar').attr('d', d => roundedBarPath(trackX, barScale(d.score), (ROW_H - 10) / 2, 10, 3));
    }

    function groupExtra(d) {
      const parts = GKEYS.map(g => `${D.groups[g]}: ${d.groups[g] !== undefined ? Math.round(d.groups[g] * 100) + '%' : '–'}`).join(' · ');
      return `<div class="tip-sub">${parts}</div><div class="tip-sub">Composite score: ${d.score.toFixed(1)}</div>`;
    }

    function downloadCurrentCSV() {
      const rows = computeRanking();
      downloadCSV('hospital_rankings.csv', rows, [
        { key: 'rank', label: 'rank' },
        { key: 'facility_id', label: 'facility_id', get: r => D.H[r.i].id },
        { key: 'name', label: 'name', get: r => D.H[r.i].name },
        { key: 'city', label: 'city', get: r => D.H[r.i].city },
        { key: 'state', label: 'state', get: r => D.H[r.i].state },
        { key: 'score', label: 'score', get: r => r.score.toFixed(1) },
        ...GKEYS.map(g => ({ key: g, label: g, get: r => r.groups[g] !== undefined ? Math.round(r.groups[g] * 100) + '%' : '' }))
      ]);
    }

    const scheduleRank = debounce(() => {
      setQuery({ w: GKEYS.map(g => weights[g]).join(',') });
      lastResults = computeRanking();
      renderList();
    }, 80);

    function renderRank1() {
      lastResults = computeRanking();
      renderList();
    }

    // ---------------- section 2 render ----------------
    function renderScatter() {
      const xs = seriesFor(PN_ID), ys = seriesFor(RECMND_ID);
      const pnMeta = D.keyById.get(PN_ID), rcMeta = D.keyById.get(RECMND_ID);
      const data = [];
      for (const i of ctx.peers) {
        const xv = xs ? xs[i] : NaN, yv = ys ? ys[i] : NaN;
        if (!Number.isNaN(xv) && !Number.isNaN(yv)) data.push({ i, x: xv, y: yv });
      }
      selControls.style.display = 'none'; selList.innerHTML = '';
      if (data.length < 5) {
        d3.select(scatterHost).selectAll('svg').remove();
        scatterHost.innerHTML = '';
        scatterHost.append(el('p', { class: 'caption', text: 'not enough hospitals in this peer group report both measures' }));
        points = [];
        return;
      }
      scatterHost.innerHTML = '';
      const W = 900, H = 460, L = 60, R = 20, TOP = 20, BOT = 42;
      const xVals = data.map(d => d.x), yVals = data.map(d => d.y);
      const xMin = d3.min(xVals), xMax = d3.max(xVals), yMin = d3.min(yVals), yMax = d3.max(yVals);
      xScale = d3.scaleLinear().domain([xMin, xMax]).nice().range([W - R, L]); // reversed: right = lower value = better
      yScale = d3.scaleLinear().domain([yMin, yMax]).nice().range([H - BOT, TOP]);
      const meanX = mean(xVals), meanY = mean(yVals);

      const svg = svgIn(scatterHost, W, H);
      const xAxis = svg.append('g').attr('transform', `translate(0,${H - BOT})`).call(d3.axisBottom(xScale).ticks(6).tickFormat(v => v.toFixed(1) + '%'));
      const yAxis = svg.append('g').attr('transform', `translate(${L},0)`).call(d3.axisLeft(yScale).ticks(6).tickFormat(v => v.toFixed(0) + '%'));
      axisStyle(xAxis); axisStyle(yAxis);
      svg.append('text').attr('x', (L + W - R) / 2).attr('y', H - 6).attr('text-anchor', 'middle').attr('fill', T.muted).style('font-size', '11px')
        .text(`${pnMeta ? pnMeta.short : 'Pneumonia readmission rate'} — lower is better, right = better →`);
      svg.append('text').attr('transform', `translate(16,${(TOP + H - BOT) / 2}) rotate(-90)`).attr('text-anchor', 'middle').attr('fill', T.muted).style('font-size', '11px')
        .text(`${rcMeta ? rcMeta.short : 'Would definitely recommend'} — higher is better ↑`);

      // quadrant hairlines
      svg.append('line').attr('x1', xScale(meanX)).attr('x2', xScale(meanX)).attr('y1', TOP).attr('y2', H - BOT).attr('stroke', T.ink2).attr('stroke-width', 1);
      svg.append('line').attr('x1', L).attr('x2', W - R).attr('y1', yScale(meanY)).attr('y2', yScale(meanY)).attr('stroke', T.ink2).attr('stroke-width', 1);
      svg.append('text').attr('x', xScale(meanX)).attr('y', TOP - 6).attr('text-anchor', 'middle').attr('fill', T.muted).style('font-size', '11px')
        .text(`peer mean ${fmtVal(pnMeta, meanX)}`);
      svg.append('text').attr('x', W - R).attr('y', yScale(meanY) - 4).attr('text-anchor', 'end').attr('fill', T.muted).style('font-size', '11px')
        .text(`peer mean ${fmtVal(rcMeta, meanY)}`);

      // quadrant counts
      let cTL = 0, cTR = 0, cBL = 0, cBR = 0;
      for (const d of data) {
        const outcomeBetter = d.x < meanX, expBetter = d.y > meanY;
        if (outcomeBetter && expBetter) cTR++; else if (outcomeBetter && !expBetter) cBR++;
        else if (!outcomeBetter && expBetter) cTL++; else cBL++;
      }
      const corner = (x, y, anchor, text) => svg.append('text').attr('x', x).attr('y', y).attr('text-anchor', anchor).attr('fill', T.muted).style('font-size', '11px').text(text);
      corner(L + 6, TOP + 14, 'start', `${cTL} hospitals: weaker outcomes, stronger experience`);
      corner(W - R - 6, TOP + 14, 'end', `${cTR} hospitals: better outcomes, stronger experience`);
      corner(L + 6, H - BOT - 8, 'start', `${cBL} hospitals: weaker outcomes, weaker experience`);
      corner(W - R - 6, H - BOT - 8, 'end', `${cBR} hospitals: better outcomes, weaker experience`);

      points = data.map(d => ({ ...d, h: D.H[d.i], px: xScale(d.x), py: yScale(d.y) }));
      const dots = svg.append('g').selectAll('circle').data(points, d => d.h.id).join('circle')
        .attr('cx', d => d.px).attr('cy', d => d.py).attr('r', 4)
        .attr('fill', d => d.h.hou && ctx.scope.kind !== 'houston' ? T.blue : T.deemph)
        .attr('stroke', '#fff').attr('stroke-width', 1.5)
        .style('cursor', 'pointer')
        .on('click', (ev, d) => goHospital(d.h))
        .on('mouseenter', (ev, d) => tip.show(hospTip(d.h, `<div class="tip-sub">${pnMeta ? pnMeta.short : 'Readmission'}: ${fmtVal(pnMeta, d.x)} · ${rcMeta ? rcMeta.short : 'Recommend'}: ${fmtVal(rcMeta, d.y)}</div>`), ev))
        .on('mousemove', ev => tip.move(ev)).on('mouseleave', () => tip.hide());

      brushG = svg.append('g').attr('class', 'brush');
      brush = d3.brush().extent([[L, TOP], [W - R, H - BOT]]).on('end', brushed);
      brushG.call(brush);

      function brushed(ev) {
        const sel = ev.selection;
        if (!sel) { selControls.style.display = 'none'; selList.innerHTML = ''; return; }
        const [[x0, y0], [x1, y1]] = sel;
        const picked = points.filter(d => d.px >= x0 && d.px <= x1 && d.py >= y0 && d.py <= y1);
        selControls.style.display = picked.length ? 'flex' : 'none';
        selList.innerHTML = '';
        const shown = picked.slice(0, 40);
        for (const d of shown) {
          selList.append(el('li', {}, [
            el('a', { text: d.h.name, onclick: () => goHospital(d.h) }),
            el('span', { text: `${fmtVal(pnMeta, d.x)} · ${fmtVal(rcMeta, d.y)}` })
          ]));
        }
        if (picked.length > 40) selList.append(el('li', {}, [el('span', { class: 'caption', text: `…and ${picked.length - 40} more` })]));
      }
      clearChip.onclick = () => brushG.call(brush.move, null);
    }

    function renderAll() { renderRank1(); renderScatter(); }
    onPeersChange(renderAll);

    // expose for show()
    this._applyWeights = (w) => {
      if (!w) return;
      const parts = String(w).split(',').map(Number);
      GKEYS.forEach((g, k) => { if (Number.isFinite(parts[k])) { weights[g] = Math.max(0, Math.min(100, parts[k])); sliderEls[g].input.value = String(weights[g]); } });
      renderWeightLabels();
    };
    this._renderAll = renderAll;
  },
  show(q, ctx) {
    this._applyWeights(q.w);
    this._renderAll();
  }
};
