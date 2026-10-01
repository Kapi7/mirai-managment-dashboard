/* Site/date links and daily chart navigation. No data is fetched or changed. */
const defaultSites = () => ACTIVE.some(s => s.slug === 'mirai-skin') ? new Set(['mirai-skin']) : null;
let dayTrail = [];
function readRoute() {
  const q = new URLSearchParams(location.search);
  // A fresh dashboard always starts on Mirai Skin; explicit links select their scope.
  state.lens = ['All', 'Main', 'Satellites'].includes(q.get('lens')) ? q.get('lens') : 'All';
  state.sites = defaultSites();
  const selection = q.get('sites') ?? q.get('site');
  if (selection === 'all' || (selection == null && q.has('lens'))) state.sites = null;
  else if (selection === 'none') state.sites = new Set();
  else if (selection != null) {
    const slugs = selection.split(',').filter(slug => ACTIVE.some(s => s.slug === slug));
    if (slugs.length) {
      state.sites = new Set(slugs);
    } else state.lens = 'All';
  }
  if (state.sites) selectSites(state.sites);
  const preset = q.get('period');
  if (PRESETS.some(p => p.k === preset)) { state.preset = preset; state.offset = 0; }
  const days = Number(q.get('days'));
  if (Number.isInteger(days) && days > 0 && days <= 730) {
    Object.assign(state, { preset: 'custom', from: Math.max(MIN, END - days + 1), to: END, offset: 0 });
  }
  const parseDate = value => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return null;
    const day = dayOf(value);
    return Number.isFinite(day) && isoOf(day) === value ? day : null;
  };
  const from = parseDate(q.get('from')), to = parseDate(q.get('to'));
  if (from != null && to != null && from <= to && from >= MIN && to <= END) {
    Object.assign(state, { preset: 'custom', from, to, offset: 0 });
  }
  if (['all', 'nodirect'].includes(q.get('traffic'))) state.traffic = q.get('traffic');
  if (q.has('compare')) state.compare = q.get('compare') !== '0';
  state.country = q.get('country') || '';
  if (!selectedCountry()) state.country = '';
  const tab = location.hash.slice(1);
  if (['sites', 'ecosystem', 'searches', 'visits', 'authority', 'connections'].includes(tab)) state.tab = tab;
}
function syncUrl(push = false) {
  const url = new URL(location.href), q = url.searchParams;
  for (const key of ['view', 'days', 'site', 'sites', 'period', 'from', 'to']) q.delete(key);
  const sites = state.sites ? [...state.sites] : null;
  q.set(sites?.length === 1 ? 'site' : 'sites', sites == null ? 'all' : sites.length ? sites.join(',') : 'none');
  q.set('lens', state.lens);
  const w = win();
  if (state.preset === 'custom' || state.offset) { q.set('from', isoOf(w.s)); q.set('to', isoOf(w.e)); }
  else q.set('period', state.preset);
  q.set('traffic', state.traffic); q.set('compare', state.compare ? '1' : '0');
  if (state.country) q.set('country', state.country); else q.delete('country');
  url.hash = state.tab;
  try { history[push ? 'pushState' : 'replaceState'](null, '', url); } catch (e) { /* embedded navigation can be restricted */ }
  if (window.parent && window.parent !== window) {
    window.parent.postMessage({ type: 'mirai-seo-route', search: url.search, hash: url.hash }, location.origin);
  }
}
function stepPeriod(direction) {
  const w = win(), from = w.s + direction * w.n, to = w.e + direction * w.n;
  if (from < MIN || to > END) return false;
  Object.assign(state, { preset: 'custom', from, to, offset: 0 });
  return true;
}
function openChartRange(from, to, slug) {
  if (!Number.isInteger(from) || !Number.isInteger(to) || from < MIN || to > END || from > to) return;
  const w = win();
  if (from === w.s && to === w.e && !slug) return;
  dayTrail.push({ state: { ...state, sites: state.sites ? new Set(state.sites) : null }, slug: openSlug });
  closeSite(); closePops();
  if (slug && ACTIVE.some(s => s.slug === slug)) selectSites(new Set([slug]));
  Object.assign(state, { preset: 'custom', from, to, offset: 0, sig: null });
  syncUrl(true); persist(); renderAll();
  $('#dayPill').focus();
}
function backToPeriod() {
  const previous = dayTrail.pop(); if (!previous) return;
  closeSite(); Object.assign(state, previous.state);
  syncUrl(true); persist(); renderAll();
  if (previous.slug) openSite(previous.slug); else $('#dayPill').focus();
}
function chartTarget(from, to, index, label, slug) {
  return `role="button" tabindex="${index === 0 ? 0 : -1}" data-chart-from="${from}" data-chart-to="${to}"${slug ? ` data-chart-site="${esc(slug)}"` : ''} aria-label="${esc(`Open ${rangeTxt(from, to)}. ${label}`)}"`;
}
function handleChartKey(e) {
  const target = e.target.closest?.('[data-chart-from]'); if (!target) return false;
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault(); openChartRange(Number(target.dataset.chartFrom), Number(target.dataset.chartTo), target.dataset.chartSite); return true;
  }
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return false;
  e.preventDefault();
  const items = [...target.closest('svg').querySelectorAll('[data-chart-from]')], at = items.indexOf(target);
  const next = e.key === 'Home' ? 0 : e.key === 'End' ? items.length - 1 : Math.max(0, Math.min(items.length - 1, at + (e.key === 'ArrowLeft' ? -1 : 1)));
  items.forEach((item, i) => item.setAttribute('tabindex', i === next ? '0' : '-1')); items[next].focus(); return true;
}
window.addEventListener('popstate', () => {
  closeSite(); closePops(); dayTrail = [];
  Object.assign(state, DEFAULTS); readRoute(); renderAll();
});
readRoute();
