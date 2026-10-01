/* ---------- data + helpers ---------- */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const EPOCH = Date.parse(D.epoch + 'T00:00:00Z');
const isoOf = d => new Date(EPOCH + d * 864e5).toISOString().slice(0, 10);
const dayOf = s => Math.round((Date.parse(String(s).slice(0, 10) + 'T00:00:00Z') - EPOCH) / 864e5);
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const dm = d => { if (d == null || d === '') return '—'; const s = typeof d === 'number' ? isoOf(d) : String(d); const [, m, dd] = s.slice(0, 10).split('-'); return `${+dd} ${MON[+m - 1]}`; };
const yr = d => d == null ? '' : isoOf(d).slice(0, 4);
function rangeTxt(s, e) {
  const a = isoOf(s), b = isoOf(e);
  if (a === b) return `${dm(s)} ${yr(s)}`;
  if (a.slice(0, 7) === b.slice(0, 7)) return `${+a.slice(8)}–${dm(e)} ${yr(e)}`;
  return a.slice(0, 4) === b.slice(0, 4) ? `${dm(s)} – ${dm(e)} ${yr(e)}` : `${dm(s)} ${yr(s)} – ${dm(e)} ${yr(e)}`;
}
const nf = new Intl.NumberFormat('en-US');
function fmt(n) {
  if (n == null || !isFinite(n)) return '—';
  const a = Math.abs(n);
  if (a >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
  if (a >= 1e4) return (n / 1e3).toFixed(a >= 1e5 ? 0 : 1).replace(/\.0$/, '') + 'k';
  return nf.format(Math.round(n));
}
const pct = (x, dg = 0) => x == null || !isFinite(x) ? '—' : (x * 100).toFixed(dg) + '%';
const plural = (n, w, ws) => `${w}${n === 1 ? '' : (ws || 's')}`;
const END = D.end, MIN = D.minDay;
const TODAY = dayOf(new Date().toISOString());
const CH = D.channels, CH_DIRECT = CH.indexOf('Direct'), CH_ORG = CH.indexOf('Organic Search');
const VNAME = { Main: 'Main', Satellites: 'Satellite', Unclassified: 'Other' };
const VCOL = { Main: 'var(--v-main)', Satellites: 'var(--v-satellite)' };
const vcol = v => VCOL[v] || 'var(--v-other)';
function mono(name) { const p = name.replace(/\.(us\.com|com)$/, '').split(/[-.]/).filter(Boolean); return (p.length > 1 ? p[0][0] + p[1][0] : p[0].slice(0, 2)).toUpperCase(); }
const avatar = (s, cls = '') => `<span class="av ${cls}" style="--vc:${vcol(s.vertical)}" aria-hidden="true">${mono(s.name)}</span>`;
const ENGINE = { google: 'Google', bing: 'Bing', duckduckgo: 'DuckDuckGo', yahoo: 'Yahoo', yandex: 'Yandex', 'yandex.ru': 'Yandex', 'ecosia.org': 'Ecosia', baidu: 'Baidu', naver: 'Naver', seznam: 'Seznam', qwant: 'Qwant', 'search.brave.com': 'Brave', startpage: 'Startpage', sogou: 'Sogou' };
const ENG_COL = { Google: 'var(--gsc)', Bing: 'var(--bing)', DuckDuckGo: 'var(--ga4)', Yahoo: 'var(--pos)', Yandex: 'var(--yandex)', Ecosia: 'var(--ecosia)' };
const SRCS = D.sources.map(x => { const i = x.lastIndexOf('|'); const src = x.slice(0, i), med = x.slice(i + 1); return { src, med, engine: med === 'organic' ? ENGINE[src.toLowerCase()] || null : null }; });
const PAGE_COL = ['var(--good)', 'var(--lime)', 'var(--gold)', 'var(--ga4)', 'var(--direct)'];
const BUCKETS = ['Avg rank 1–3', 'Avg rank >3–10', 'Avg rank >10–20', 'Avg rank >20–50', 'Avg rank >50'];
const bucketOf = p => p <= 3 ? 0 : p <= 10 ? 1 : p <= 20 ? 2 : p <= 50 ? 3 : 4;
const rankText = pos => Number.isFinite(pos) && pos > 0 ? '#' + pos.toFixed(1) : '—';
function rankTag(pos) {
  if (!Number.isFinite(pos) || pos <= 0) return '<span class="dim">—</span>';
  return `<span class="pg" title="Average Google rank · lower is better"><span class="pb" style="--pc:${PAGE_COL[bucketOf(pos)]}">${rankText(pos)}</span></span>`;
}
const regionNames = new Intl.DisplayNames(['en'], { type: 'region' });
function countryFlag(iso) {
  const code = String(iso || '').toUpperCase();
  if (!/^[A-Z]{2}$/.test(code) || ['ZZ', 'XX'].includes(code) || regionNames.of(code) === code) return '🌐';
  return String.fromCodePoint(...[...code].map(c => 127397 + c.charCodeAt(0)));
}
const countryKey = g => /^[A-Z]{2}$/i.test(g.iso || '') ? g.iso.toUpperCase() : 'name:' + g.name;
const countryLabel = g => `${countryFlag(g.iso)} ${g.name === '(not set)' ? 'Unknown country' : g.name}`;
const selectedCountry = () => (D.countries || []).map(([name, iso]) => ({ name, iso })).find(g => countryKey(g) === state.country);
const countryMatches = (g, needle = '') => (!state.country || countryKey(g) === state.country)
  && `${g.name} ${g.iso} ${countryLabel(g)}`.toLowerCase().includes(needle.toLowerCase());
const oneIn = (part, whole) => part > 0 ? Math.max(1, Math.round(whole / part)) : null;
function qsplit(q) { const p = q.split(';'); return { q: p[0], g: p.length > 1 ? p.slice(1).join(' · ') : '' }; }
function hostOf(u) { try { return new URL(u).hostname.replace(/^www\./, ''); } catch (e) { return u; } }
function hl(text, needle) {
  const t = esc(text); if (!needle) return t;
  const i = text.toLowerCase().indexOf(needle.toLowerCase()); if (i < 0) return t;
  return esc(text.slice(0, i)) + '<mark>' + esc(text.slice(i, i + needle.length)) + '</mark>' + esc(text.slice(i + needle.length));
}

/* ---------- sites (static facts) ---------- */
const SITES = D.sites.map((s, idx) => {
  const fi = s.g.find(r => r[2] > 0);
  return { ...s, idx, firstImpr: fi ? fi[0] : null, lastSess: s.a.length ? s.a[s.a.length - 1][0] : null, gscFirst: s.g.length ? s.g[0][0] : null };
});
const ACTIVE = SITES.filter(s => !s.excluded);
const siteBy = slug => SITES.find(s => s.slug === slug);

/* ---------- state ---------- */
const PRESETS = [{ k: '7d', n: 7, l: '7 days' }, { k: '28d', n: 28, l: '28 days' }, { k: '3m', n: 91, l: '3 months' }, { k: '6m', n: 182, l: '6 months' }, { k: '12m', n: 364, l: '12 months' }];
const DEFAULTS = { lens: 'All', preset: '28d', from: null, to: null, offset: 0, compare: true, traffic: 'all', sites: null, country: '', find: '', tab: 'sites', view: 'cards', sort: 'impr', sortDir: -1, sig: null };
const state = { ...DEFAULTS };
try {
  const saved = JSON.parse(localStorage.getItem('mirai-seo-v1') || '{}');
  for (const k of ['lens', 'preset', 'from', 'to', 'compare', 'traffic', 'view', 'sort', 'sortDir']) if (saved[k] !== undefined) state[k] = saved[k];
  if (Array.isArray(saved.sites)) state.sites = new Set(saved.sites);
  if (state.preset === 'custom' && (state.from == null || state.to == null)) state.preset = '28d';
} catch (e) { /* storage unavailable: defaults */ }
function persist() {
  syncUrl();
  try { localStorage.setItem('mirai-seo-v1', JSON.stringify({ lens: state.lens, preset: state.preset, from: state.from, to: state.to, compare: state.compare, traffic: state.traffic, view: state.view, sort: state.sort, sortDir: state.sortDir, sites: state.sites ? [...state.sites] : null })); } catch (e) { /* ignore */ }
}

function win() {
  let s, e;
  if (state.preset === 'custom') { s = state.from; e = state.to; }
  else { const n = PRESETS.find(p => p.k === state.preset).n; e = END; s = END - n + 1; }
  const n = e - s + 1; s -= state.offset * n; e -= state.offset * n;
  return { s, e, n, ps: s - n, pe: s - 1 };
}
const lensSites = () => ACTIVE.filter(s => state.lens === 'All' || s.vertical === state.lens);
function scope() { let L = lensSites(); if (state.sites) L = L.filter(s => state.sites.has(s.slug)); return L; }
// Explicit site choices determine the category; category buttons select that
// whole category. Mixed/empty choices never highlight All as if it were active.
function selectSites(slugs) {
  const selected = ACTIVE.filter(s => slugs.has(s.slug));
  const verticals = [...new Set(selected.map(s => s.vertical))];
  state.lens = verticals.length === 1 && ['Main', 'Satellites'].includes(verticals[0]) ? verticals[0] : 'All';
  state.sites = new Set(selected.map(s => s.slug));
  if (selected.length === ACTIVE.length && ACTIVE.length) selectLens('All');
}
function selectLens(lens) {
  state.lens = ['All', 'Main', 'Satellites'].includes(lens) ? lens : 'All';
  state.sites = null;
}
const checkedLens = () => state.lens === 'All' && state.sites ? null : state.lens;
function scopeLabel(L = scope()) {
  if (!L.length) return 'No sites selected';
  if (L.length === 1) return L[0].name;
  if (state.sites) return `${L.length} selected sites`;
  return `All ${L.length} ${state.lens === 'All' ? '' : VNAME[state.lens].toLowerCase() + ' '}${plural(L.length, 'site')}`;
}
function scopeWords(L) {
  if (L.length === 1) return L[0].name;
  const all = lensSites();
  if (state.sites && L.length < all.length) return `${L.length} selected sites`;
  return state.lens === 'All' ? `all ${L.length} sites` : `the ${L.length} ${VNAME[state.lens].toLowerCase()} ${plural(L.length, 'site')}`;
}

/* ---------- aggregation ---------- */
let MEMO = new Map();
function agg(site, s, e) {
  const key = `${site.idx}:${s}:${e}:${state.traffic}`;
  if (MEMO.has(key)) return MEMO.get(key);
  const o = { clicks: 0, impr: 0, pw: 0, gRows: 0, sessAll: 0, direct: 0, org: 0, engAll: 0, engDir: 0, engOrg: 0, aff: 0, aRows: 0 };
  for (const r of site.g) { if (r[0] < s) continue; if (r[0] > e) break; o.clicks += r[1]; o.impr += r[2]; o.pw += r[3]; o.gRows++; }
  for (const r of site.a) {
    if (r[0] < s) continue; if (r[0] > e) break;
    o.sessAll += r[2]; o.engAll += r[3]; o.aRows++;
    if (r[1] === CH_DIRECT) { o.direct += r[2]; o.engDir += r[3]; }
    if (r[1] === CH_ORG) { o.org += r[2]; o.engOrg += r[3]; }
  }
  for (const r of site.ev) { if (r[0] < s) continue; if (r[0] > e) break; o.aff += r[1]; }
  const nd = state.traffic === 'nodirect';
  o.sess = nd ? o.sessAll - o.direct : o.sessAll;
  o.eng = nd ? o.engAll - o.engDir : o.engAll;
  o.pos = o.impr ? o.pw / o.impr : null;
  MEMO.set(key, o);
  return o;
}
function totals(L, s, e) {
  const t = { clicks: 0, impr: 0, pw: 0, sessAll: 0, sess: 0, direct: 0, org: 0, engAll: 0, eng: 0, engDir: 0, engOrg: 0, aff: 0 };
  for (const site of L) { const a = agg(site, s, e); for (const k in t) t[k] += a[k]; }
  t.pos = t.impr ? t.pw / t.impr : null;
  return t;
}
function series(L, s, e) {
  const n = e - s + 1, z = () => new Array(n).fill(0);
  const o = { impr: z(), clicks: z(), pw: z(), sess: z(), org: z(), aff: z(), direct: z() };
  const nd = state.traffic === 'nodirect';
  for (const site of L) {
    for (const r of site.g) { if (r[0] < s) continue; if (r[0] > e) break; const i = r[0] - s; o.clicks[i] += r[1]; o.impr[i] += r[2]; o.pw[i] += r[3]; }
    for (const r of site.a) {
      if (r[0] < s) continue; if (r[0] > e) break; const i = r[0] - s;
      if (r[1] === CH_DIRECT) { o.direct[i] += r[2]; if (nd) continue; }
      o.sess[i] += r[2]; if (r[1] === CH_ORG) o.org[i] += r[2];
    }
    for (const r of site.ev) { if (r[0] < s) continue; if (r[0] > e) break; o.aff[r[0] - s] += r[1]; }
  }
  o.pos = o.pw.map((w, i) => o.impr[i] ? w / o.impr[i] : null);
  return o;
}
function rowsAgg(L, s, e, field, keyIdx) {
  const m = new Map();
  for (const site of L) for (const r of site[field]) {
    if (r[0] < s) continue; if (r[0] > e) break;
    const k = site.idx * 1e6 + r[keyIdx]; let a = m.get(k);
    if (!a) m.set(k, a = { site, key: r[keyIdx], c: 0, i: 0, pw: 0 });
    a.c += r[2]; a.i += r[3]; a.pw += r[4];
  }
  return [...m.values()].map(a => (a.pos = a.i ? a.pw / a.i : null, a));
}
const queryAgg = (L, s, e) => rowsAgg(L, s, e, 'q', 1).map(a => ({ ...a, text: D.queries[a.key] }));
const pageAgg = (L, s, e) => rowsAgg(L, s, e, 'p', 1).map(a => ({ ...a, text: D.pages[a.key] }));
function buckets(qs) {
  const b = BUCKETS.map((l, i) => ({ l, i, n: 0, impr: 0, clicks: 0, c: PAGE_COL[i] }));
  for (const q of qs) if (q.pos != null) { const x = b[bucketOf(q.pos)]; x.n++; x.impr += q.i; x.clicks += q.c; }
  return b;
}
function geoAgg(L, s, e) {
  const m = new Map();
  for (const site of L) for (const r of site.geo) { if (r[0] < s) continue; if (r[0] > e) break; m.set(r[1], (m.get(r[1]) || 0) + r[2]); }
  return [...m.entries()].map(([ci, n]) => ({ name: D.countries[ci][0], iso: D.countries[ci][1], n })).sort((a, b) => b.n - a.n);
}
function engineAgg(L, s, e) {
  const m = new Map();
  for (const site of L) for (const r of site.src) {
    if (r[0] < s) continue; if (r[0] > e) break;
    const en = SRCS[r[1]].engine; if (!en) continue;
    const a = m.get(en) || { name: en, n: 0, eng: 0, sites: new Set() }; a.n += r[2]; a.eng += r[3]; a.sites.add(site.slug); m.set(en, a);
  }
  return [...m.values()].sort((a, b) => b.n - a.n);
}
function linkAgg(L, s, e) {
  const m = new Map();
  for (const site of L) for (const r of site.lk) {
    if (r[0] < s) continue; if (r[0] > e) break;
    const host = hostOf(D.links[r[1]]); const a = m.get(host) || { host, n: 0, sites: new Set(), urls: new Set() };
    a.n += r[2]; a.sites.add(site.slug); a.urls.add(D.links[r[1]]); m.set(host, a);
  }
  return [...m.values()].sort((a, b) => b.n - a.n);
}
function wpAt(site, day) { let best = null; for (const r of site.wp) { if (r[0] <= day) best = r; else break; } return best; }
function wpInfo(site, s, e) {
  const end = wpAt(site, e), start = wpAt(site, s - 1), first = site.wp[0];
  if (!end) return { total: null, added: null, last: null, since: first ? first[0] : null };
  const base = start || first;
  return { total: end[1], added: end[1] - base[1], partial: !start, since: first[0], last: end[2] >= 0 ? end[2] : null };
}
function postsLost(site) {
  const now = wpAt(site, END); if (!now) return null;
  let peak = null; for (const r of site.wp) if (r[0] <= END && (!peak || r[1] > peak[1])) peak = r;
  if (!peak || peak[1] < 5 || now[1] > peak[1] * 0.5) return null;
  const drop = site.wp.find(r => r[0] > peak[0] && r[1] <= peak[1] * 0.5);
  return { from: peak[1], to: now[1], on: drop ? drop[0] : now[0] };
}
function ahAt(site, e) { const iso = isoOf(e); let best = null; for (const r of site.ah) if (r[0] <= iso) best = r; return best; }

/* ---------- per-site verdicts ---------- */
function flagsFor(site, a) {
  const F = [];
  if (site.excluded) return F;
  if (!site.gsc_property) F.push({ k: 'nogsc', sev: 'warn', short: 'Not in Search Console' });
  else if (site.gsc_property.startsWith('http://') && a.impr === 0 && a.gRows > 0) F.push({ k: 'httpprop', sev: 'bad', short: 'Zero Google views' });
  if (site.ga4 && site.lastSess != null && END - site.lastSess > 7) F.push({ k: 'ga4stale', sev: 'bad', short: `No visits since ${dm(site.lastSess)}` });
  if (a.sessAll >= 100 && a.direct / a.sessAll >= 0.8) F.push({ k: 'bots', sev: 'warn', short: 'High Direct share' });
  const lost = postsLost(site); if (lost) F.push({ k: 'postslost', sev: 'bad', short: 'Posts disappeared' });
  const ah = site.ah.at(-1);
  if (ah && site.name === 'slots.us.com') F.push({ k: 'drshared', sev: 'warn', short: 'DR belongs to us.com' });
  return F;
}
function trendOf(site, a, p, w) {
  if (!a.impr && !p.impr) return { k: 'none' };
  if (site.firstImpr != null && site.firstImpr > w.ps) return { k: 'new', since: site.firstImpr };
  if (!p.impr) return { k: 'new', since: site.firstImpr };
  const r = a.impr / p.impr;
  return { k: r >= 1.2 ? 'up' : r <= 0.8 ? 'down' : 'flat', r };
}
function siteView(site, w) {
  const a = agg(site, w.s, w.e), p = agg(site, w.ps, w.pe);
  const flags = flagsFor(site, a), trend = trendOf(site, a, p, w);
  const bad = flags.some(f => f.sev === 'bad');
  const tint = bad || trend.k === 'down' ? 't-bad' : (trend.k === 'up' || (trend.k === 'new' && a.impr > 0)) ? 't-good' : '';
  return { site, a, p, flags, trend, tint, wp: wpInfo(site, w.s, w.e), ah: site.ah.at(-1) || null };
}
function statusChip(v, compact) {
  const f = v.flags.find(x => x.sev === 'bad') || v.flags.find(x => x.sev === 'warn');
  if (f) return `<span class="chip ${f.sev}">${esc(f.short)}</span>`;
  const t = v.trend;
  if (t.k === 'none') return '<span class="chip mute">Not in Google yet</span>';
  if (t.k === 'new') return compact ? '<span class="chip info">New in Google</span>' : `<span class="chip info">In Google since ${dm(t.since)}</span>`;
  if (t.k === 'up') return '<span class="chip good">Growing</span>';
  if (t.k === 'down') return '<span class="chip bad">Dropping</span>';
  return '<span class="chip mute">Steady</span>';
}
function delta(cur, prev, { invert = false } = {}) {
  if (!state.compare || cur == null || prev == null) return '';
  if (!prev && !cur) return '<span class="delta flat">no change</span>';
  if (!prev) return '<span class="delta new">new</span>';
  const ch = (cur - prev) / prev;
  if (Math.abs(ch) < 0.005) return '<span class="delta flat">±0%</span>';
  const good = invert ? ch < 0 : ch > 0;
  const txt = cur / prev >= 10 ? '×' + Math.round(cur / prev) : Math.round(Math.abs(ch) * 100) + '%';
  return `<span class="delta ${good ? 'up' : 'down'}"><span aria-hidden="true">${ch > 0 ? '▲' : '▼'}</span>${txt}<span class="sr">${ch > 0 ? ' up' : ' down'}</span></span>`;
}
function posDelta(cur, prev) {
  if (!state.compare || !cur || !prev) return '';
  const d = cur - prev; if (Math.abs(d) < 0.05) return '<span class="delta flat">No rank change</span>';
  return `<span class="delta ${d < 0 ? 'up' : 'down'}">${Math.abs(d).toFixed(1)} places ${d < 0 ? 'better' : 'worse'}</span>`;
}
const vsTxt = (w, prevVal) => state.compare ? `vs ${rangeTxt(w.ps, w.pe)}${prevVal != null ? ' · ' + prevVal : ''}` : '';
const info = t => `<button type="button" class="ib" data-tip="${esc(t)}" aria-label="${esc(t)}">i</button>`;
