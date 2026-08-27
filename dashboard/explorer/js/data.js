// data.js — data layer for the explorer. Loads the static bundle and exposes indexed, peer-aware statistics.
// Everything is computed client-side from hospital-level rows (no precomputed benchmarks), mirroring the SQL views.

export const D = {
  H: [],            // hospitals: {i, id, name, city, state, zip, county, type, own, er, stars, tx, hou, lat, lon}
  byId: new Map(),  // facility_id -> hospital
  cat: null,        // catalog.json
  key: [],          // key measures (catalog.key) with .group, .hib, .unit, .dec, .short
  keyById: new Map(),
  groups: {},       // group id -> label
  vals: {},         // measure id -> {i: idx[], v: score[], d: denom[]}
  series: new Map() // measure id -> Float64Array by hospital index (NaN = missing)
};

const base = new URL('./data/', import.meta.url.replace(/js\/[^/]*$/, ''));
export const dataUrl = (p) => new URL(p, base).href;

export async function load() {
  const [hosp, cat, vals] = await Promise.all(['hospitals.json', 'catalog.json', 'values.json'].map(f => fetch(dataUrl(f)).then(r => r.json())));
  const cols = hosp.cols;
  D.H = hosp.rows.map((r, i) => { const o = { i }; cols.forEach((c, k) => o[c] = r[k]); return o; });
  D.H.forEach(h => D.byId.set(h.id, h));
  D.cat = cat; D.key = cat.key; D.groups = cat.groups;
  D.key.forEach(m => D.keyById.set(m.id, m));
  D.vals = vals;
  for (const m of D.key) seriesFor(m.id);
  return D;
}

/** Dense series (Float64Array indexed by hospital idx, NaN = missing) for a key measure or a lazily loaded one. */
export function seriesFor(mid) {
  if (D.series.has(mid)) return D.series.get(mid);
  const src = D.vals[mid]; if (!src) return null;
  const s = new Float64Array(D.H.length).fill(NaN);
  src.i.forEach((idx, k) => { s[idx] = src.v[k]; });
  D.series.set(mid, s);
  return s;
}

/** Lazily fetch any of the 161 measures (measure explorer). Returns the dense series. */
export async function loadMeasure(meta) {
  const mid = meta.id;
  if (D.series.has(mid)) return D.series.get(mid);
  const j = await fetch(dataUrl('measures/' + (meta.file || mid + '.json'))).then(r => r.json());
  D.vals[mid] = j;
  return seriesFor(mid);
}

// ---------------- peer sets ----------------
/** Build a peer set (array of hospital idx) from a scope + filters.
 *  scope: {kind:'us'} | {kind:'state', state:'TX'} | {kind:'houston'} | {kind:'county', state, county}
 *  filters: {own?: string, type?: string, er?: true}
 */
export function peerSet(scope = { kind: 'us' }, filters = {}) {
  const out = [];
  for (const h of D.H) {
    if (scope.kind === 'state' && h.state !== scope.state) continue;
    if (scope.kind === 'houston' && !h.hou) continue;
    if (scope.kind === 'county' && (h.state !== scope.state || h.county !== scope.county)) continue;
    if (filters.own && h.own !== filters.own) continue;
    if (filters.type && h.type !== filters.type) continue;
    if (filters.er && !h.er) continue;
    out.push(h.i);
  }
  return out;
}

export function scopeLabel(scope) {
  if (scope.kind === 'state') return stateName(scope.state);
  if (scope.kind === 'houston') return 'Houston area';
  if (scope.kind === 'county') return `${scope.county} County, ${scope.state}`;
  return 'United States';
}

// ---------------- statistics ----------------
const statCache = new Map();
/** Sorted values of a measure within a peer set. peers = array of idx or null (all). */
export function sortedIn(mid, peers, series) {
  const s = series || seriesFor(mid); if (!s) return [];
  const k = mid + '|' + (peers ? peers.length + ':' + peers[0] + ':' + peers[peers.length - 1] : 'all');
  if (statCache.has(k)) return statCache.get(k);
  const arr = [];
  if (peers) { for (const i of peers) if (!Number.isNaN(s[i])) arr.push(s[i]); }
  else { for (let i = 0; i < s.length; i++) if (!Number.isNaN(s[i])) arr.push(s[i]); }
  arr.sort((a, b) => a - b);
  if (statCache.size > 400) statCache.clear();
  statCache.set(k, arr);
  return arr;
}

export function quantile(sorted, q) {
  const n = sorted.length; if (!n) return NaN;
  const pos = (n - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}
export const median = s => quantile(s, 0.5);
export const mean = s => s.length ? s.reduce((a, b) => a + b, 0) / s.length : NaN;

/** Fraction of `sorted` strictly below x (percent_rank style, 0..1). */
export function rankBelow(sorted, x) {
  let lo = 0, hi = sorted.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (sorted[m] < x) lo = m + 1; else hi = m; }
  return sorted.length ? lo / sorted.length : NaN;
}

/** Share of peers this value beats, oriented so higher = better regardless of measure direction. */
export function betterThan(mid, x, sorted, hib) {
  if (Number.isNaN(x) || !sorted.length) return NaN;
  const below = rankBelow(sorted, x);
  const h = hib === undefined ? D.keyById.get(mid)?.hib : hib;
  if (h === null || h === undefined) return below;      // undecided direction: raw percentile
  return h ? below : 1 - rankBelow(sorted, x + 1e-9);   // lower is better -> share above
}

/** Per-hospital composite score (0..100) over a peer set from group weights {outcomes, readmissions, safety, timely, experience}. */
export function composite(peers, weights) {
  const groups = Object.keys(D.groups);
  const byGroup = {}; groups.forEach(g => byGroup[g] = D.key.filter(m => m.group === g));
  const sortedByM = {}; D.key.forEach(m => sortedByM[m.id] = sortedIn(m.id, peers));
  const res = [];
  for (const i of peers) {
    const gscore = {}; let wsum = 0, total = 0, ng = 0;
    for (const g of groups) {
      const w = weights[g] ?? 0; if (!w) continue;
      let acc = 0, n = 0;
      for (const m of byGroup[g]) {
        const x = seriesFor(m.id)[i]; if (Number.isNaN(x)) continue;
        const b = betterThan(m.id, x, sortedByM[m.id]); if (Number.isNaN(b)) continue;
        acc += b; n++;
      }
      if (n) { gscore[g] = acc / n; total += w * gscore[g]; wsum += w; ng++; }
    }
    if (wsum > 0 && ng >= 2) res.push({ i, score: 100 * total / wsum, groups: gscore, ng });
  }
  res.sort((a, b) => b.score - a.score);
  res.forEach((r, k) => r.rank = k + 1);
  return res;
}

// ---------------- formatting ----------------
export function fmtVal(m, x) {
  if (x === null || x === undefined || Number.isNaN(x)) return '–';
  const dec = m?.dec ?? 1;
  const s = Number(x).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
  const u = m?.unit || '';
  return u === '%' ? s + '%' : u === 'min' ? s + ' min' : u === 'stars' ? s + ' ★' : s;
}
export const fmtPct = (f) => Number.isNaN(f) ? '–' : Math.round(f * 100) + '%';
export const ordinal = (n) => { const s = ['th', 'st', 'nd', 'rd'], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); };

const STATES = { AL: 'Alabama', AK: 'Alaska', AZ: 'Arizona', AR: 'Arkansas', CA: 'California', CO: 'Colorado', CT: 'Connecticut', DE: 'Delaware', DC: 'District of Columbia', FL: 'Florida', GA: 'Georgia', HI: 'Hawaii', ID: 'Idaho', IL: 'Illinois', IN: 'Indiana', IA: 'Iowa', KS: 'Kansas', KY: 'Kentucky', LA: 'Louisiana', ME: 'Maine', MD: 'Maryland', MA: 'Massachusetts', MI: 'Michigan', MN: 'Minnesota', MS: 'Mississippi', MO: 'Missouri', MT: 'Montana', NE: 'Nebraska', NV: 'Nevada', NH: 'New Hampshire', NJ: 'New Jersey', NM: 'New Mexico', NY: 'New York', NC: 'North Carolina', ND: 'North Dakota', OH: 'Ohio', OK: 'Oklahoma', OR: 'Oregon', PA: 'Pennsylvania', RI: 'Rhode Island', SC: 'South Carolina', SD: 'South Dakota', TN: 'Tennessee', TX: 'Texas', UT: 'Utah', VT: 'Vermont', VA: 'Virginia', WA: 'Washington', WV: 'West Virginia', WI: 'Wisconsin', WY: 'Wyoming', PR: 'Puerto Rico', GU: 'Guam', VI: 'U.S. Virgin Islands', AS: 'American Samoa', MP: 'Northern Mariana Islands' };
export const stateName = (ab) => STATES[ab] || ab;
export const STATE_FIPS = { AL: '01', AK: '02', AZ: '04', AR: '05', CA: '06', CO: '08', CT: '09', DE: '10', DC: '11', FL: '12', GA: '13', HI: '15', ID: '16', IL: '17', IN: '18', IA: '19', KS: '20', KY: '21', LA: '22', ME: '23', MD: '24', MA: '25', MI: '26', MN: '27', MS: '28', MO: '29', MT: '30', NE: '31', NV: '32', NH: '33', NJ: '34', NM: '35', NY: '36', NC: '37', ND: '38', OH: '39', OK: '40', OR: '41', PA: '42', RI: '44', SC: '45', SD: '46', TN: '47', TX: '48', UT: '49', VT: '50', VA: '51', WA: '53', WV: '54', WI: '55', WY: '56', PR: '72' };

/** Distinct values for filter dropdowns. */
export function distinct(field) {
  const c = new Map();
  for (const h of D.H) if (h[field]) c.set(h[field], (c.get(h[field]) || 0) + 1);
  return [...c.entries()].sort((a, b) => b[1] - a[1]).map(([v, n]) => ({ v, n }));
}
