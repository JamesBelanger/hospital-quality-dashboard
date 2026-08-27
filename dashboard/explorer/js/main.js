// main.js — bootstrap, hash router, and the shared peer-group bar.
// Views register with `register(name, {mount(el, ctx), update(ctx), show(q)})` and receive ctx = {peers, scope, filters, q, go}.
import { D, load, peerSet, scopeLabel, distinct, stateName } from './data.js';
import { readHash, writeHash, el } from './ui.js';

const views = {};
export const ctx = { peers: null, scope: { kind: 'us' }, filters: {}, q: {}, hospital: null, go };
const listeners = new Set();
export const onPeersChange = (fn) => listeners.add(fn);

export function register(name, api) { views[name] = api; }
export function go(view, q = {}, replace = false) { writeHash(view, q, replace); route(); }
export function goHospital(h) { go('report', { h: h.id }); }
/** Merge view-specific params into the URL without re-routing (views call this to make their state shareable). */
export function setQuery(patch) { Object.assign(ctx.q, patch); syncHash(); }

function recomputePeers() {
  ctx.peers = peerSet(ctx.scope, ctx.filters);
  document.getElementById('peercount').textContent = `${ctx.peers.length.toLocaleString()} hospitals in ${scopeLabel(ctx.scope)}` +
    (ctx.filters.own ? ` · ${ctx.filters.own}` : '') + (ctx.filters.type ? ` · ${ctx.filters.type}` : '') + (ctx.filters.er ? ' · with ED' : '');
  for (const fn of listeners) fn(ctx);
}

function buildPeerBar() {
  const scope = document.getElementById('scope');
  const opts = [['us', 'United States (all hospitals)'], ['houston', 'Houston area (5 counties)']];
  const states = [...new Set(D.H.map(h => h.state))].filter(Boolean).sort();
  scope.append(...opts.map(([v, t]) => el('option', { value: v, text: t })));
  const og = el('optgroup', { label: 'One state' });
  og.append(...states.map(s => el('option', { value: 'state:' + s, text: stateName(s) })));
  scope.append(og);
  scope.addEventListener('change', () => { setScope(scope.value); recomputePeers(); syncHash(); });
  const own = document.getElementById('f-own'), type = document.getElementById('f-type'), er = document.getElementById('f-er');
  own.append(...distinct('own').map(o => el('option', { value: o.v, text: `${o.v} (${o.n})` })));
  type.append(...distinct('type').map(o => el('option', { value: o.v, text: `${o.v} (${o.n})` })));
  own.addEventListener('change', () => { ctx.filters.own = own.value || undefined; recomputePeers(); syncHash(); });
  type.addEventListener('change', () => { ctx.filters.type = type.value || undefined; recomputePeers(); syncHash(); });
  er.addEventListener('change', () => { ctx.filters.er = er.checked || undefined; recomputePeers(); syncHash(); });
}
function setScope(v) {
  if (v.startsWith('state:')) ctx.scope = { kind: 'state', state: v.slice(6) };
  else ctx.scope = { kind: v };
}
export function setScopeValue(v) { setScope(v); document.getElementById('scope').value = v; recomputePeers(); syncHash(); }
/** Set peer-bar filters programmatically (e.g. "same ownership" chips on the report card). */
export function setFilters(patch) {
  ctx.filters = { ...ctx.filters, ...patch };
  document.getElementById('f-own').value = ctx.filters.own || ''; document.getElementById('f-type').value = ctx.filters.type || ''; document.getElementById('f-er').checked = !!ctx.filters.er;
  recomputePeers(); syncHash();
}
export const scopeValue = () => ctx.scope.kind === 'state' ? 'state:' + ctx.scope.state : ctx.scope.kind;

let current = null;
function syncHash() {
  const q = { ...ctx.q, scope: scopeValue() === 'us' ? undefined : scopeValue(), own: ctx.filters.own, type: ctx.filters.type, er: ctx.filters.er ? 1 : undefined };
  writeHash(current, q, true);
}
function applyHashFilters(q) {
  if (q.scope) { setScope(q.scope); document.getElementById('scope').value = q.scope; }
  ctx.filters = { own: q.own || undefined, type: q.type || undefined, er: q.er ? true : undefined };
  document.getElementById('f-own').value = q.own || ''; document.getElementById('f-type').value = q.type || ''; document.getElementById('f-er').checked = !!q.er;
}

const PEERBAR_VIEWS = new Set(['report', 'compare', 'rankings', 'measures', 'map']);
function route() {
  const { view, q } = readHash();
  const name = views[view] ? view : 'story';
  ctx.q = q;
  if (q.scope !== undefined || q.own || q.type || q.er) { applyHashFilters(q); recomputePeers(); }
  document.querySelectorAll('#tabs a').forEach(a => a.classList.toggle('active', a.dataset.view === name));
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === 'view-' + name));
  document.getElementById('peerbar').style.display = PEERBAR_VIEWS.has(name) ? '' : 'none';
  current = name;
  const api = views[name];
  if (!api.mounted) { api.mount(document.getElementById('view-' + name), ctx); api.mounted = true; }
  api.show?.(q, ctx);
  window.scrollTo({ top: 0 });
}

async function boot() {
  await load();
  buildPeerBar();
  const { q } = readHash();
  if (q.scope) { setScope(q.scope); document.getElementById('scope').value = q.scope; }
  applyHashFilters(q);
  recomputePeers();
  document.getElementById('loading').remove();
  const mods = await Promise.all(['./story.js', './reportcard.js', './compare.js', './measures.js', './map.js', './rankings.js', './console.js'].map(m => import(m).catch(e => { console.error(m, e); return null; })));
  mods.forEach(m => m && m.default && register(m.default.name, m.default));
  addEventListener('hashchange', route);
  addEventListener('popstate', route);
  route();
}
boot();
