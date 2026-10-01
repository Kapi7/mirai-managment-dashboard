/* ---------- tabs ---------- */
const TABS = [
  { k: 'sites', label: 'Overview', icon: 'grid' },
  { k: 'ecosystem', label: 'Traffic to sales', short: 'Sales', icon: 'out' },
  { k: 'searches', label: 'Google searches', short: 'Searches', icon: 'search' },
  { k: 'visits', label: 'Visits', icon: 'users' },
  { k: 'authority', label: 'Authority & content', short: 'Authority', icon: 'shield' },
  { k: 'connections', label: 'Connections', short: 'Connect', icon: 'plug' },
];
const VHEX = { Main: 'var(--v-main)', Satellites: 'var(--v-satellite)' };
const vhex = v => VHEX[v] || 'var(--v-other)';
const siteChip = s => `<span class="sitechip" style="--vc:${vcol(s.vertical)}">${esc(s.name)}</span>`;
const findTxt = () => state.find.trim().toLowerCase();
const noMatch = what => `<div class="empty">Nothing in ${what} matches “${esc(state.find.trim())}”. <button type="button" class="reset" data-clearfind>Clear the search</button></div>`;
const more = (key, total, shown) => total > shown ? `<div class="showall"><button type="button" class="chipbtn" data-more="${key}">Show all ${fmt(total)}</button></div>` : '';
const MORE = {};

/* ----- Sites ----- */
const SORTS = [{ k: 'impr', l: 'Views' }, { k: 'clicks', l: 'Clicks' }, { k: 'org', l: 'Search visits' }, { k: 'aff', l: 'Partner clicks' }, { k: 'pos', l: 'Best rank' }, { k: 'growth', l: 'Growth' }];
function sortVal(v, k) {
  switch (k) {
    case 'name': return v.site.name; case 'impr': return v.a.impr; case 'clicks': return v.a.clicks;
    case 'ctr': return v.a.impr ? v.a.clicks / v.a.impr : -1; case 'pos': return v.a.pos ?? 999;
    case 'org': return v.a.org; case 'sess': return v.a.sess; case 'direct': return v.a.sessAll ? v.a.direct / v.a.sessAll : -1;
    case 'aff': return v.a.aff; case 'posts': return v.wp.total ?? -1; case 'dr': return v.ah?.[1] ?? -1;
    default: return v.a.impr - v.p.impr;
  }
}
function sortViews(V) {
  const k = state.sort, dir = state.sortDir;
  return V.sort((a, b) => { const x = sortVal(a, k), y = sortVal(b, k); return (typeof x === 'string' ? x.localeCompare(y) : x - y) * dir || b.a.impr - a.a.impr || b.a.sessAll - a.a.sessAll; });
}
const tv = (l, v, c) => `<div class="tv" style="--c:${c}"><b>${v}</b><span>${l}</span></div>`;
function ecosystemTrend(L, w) {
  if (L.length < 2) return '';
  const colors = {'mirai-skin':'var(--v-main)','glow-coded':'var(--pos)','rooted-glow':'var(--good)'};
  const chart = (key,label) => timeChart({s:w.s,e:w.e,h:225,series:L.map(site=>({label:site.name,color:colors[site.slug]||vhex(site.vertical),vals:series([site],w.s,w.e)[key],kind:'line'})),aria:`Daily ${label.toLowerCase()} by site`});
  const legend = `<div class="legend">${L.map(site=>`<span><i style="background:${colors[site.slug]||vhex(site.vertical)}"></i>${esc(site.name)}</span>`).join('')}</div>`;
  return `<section class="grid2 ecosystem-trends"><div class="panel glow-chart" style="--c:var(--v-main)"><div class="ph"><h2>Google clicks by site</h2><span class="src s-gsc">GSC</span></div>${chart('clicks','Google clicks')}${legend}</div><div class="panel glow-chart" style="--c:var(--good)"><div class="ph"><h2>Search visits by site</h2><span class="src s-ga4">GA4</span></div>${chart('org','search visits')}${legend}</div></section>`;
}
function vSites(L, w) {
  const f = findTxt(), nd = state.traffic === 'nodirect', T = totals(L, w.s, w.e);
  const V = sortViews(L.map(s => siteView(s, w)).filter(v => !f || v.site.name.includes(f)));
  const tool = `<div class="stool"><div class="seg" role="radiogroup" aria-label="Layout">${[['cards', 'Cards'], ['table', 'Table']].map(([k, l]) => `<button type="button" role="radio" data-view="${k}" aria-checked="${state.view === k}">${l}</button>`).join('')}</div>
    ${state.view === 'cards' ? `<span class="flabel">Sort</span><div class="seg" role="radiogroup" aria-label="Sort sites">${SORTS.map(s => `<button type="button" role="radio" data-sort="${s.k}" aria-checked="${state.sort === s.k}">${s.l}</button>`).join('')}</div>` : ''}</div>`;
  const tbar = `<div class="tbar"><div class="who"><span class="av" style="--vc:var(--gold)">${icon('grid', 15)}</span><div><b>Portfolio total</b><span>${L.length} ${plural(L.length, 'site')} · ${rangeTxt(w.s, w.e)}</span></div></div>
    ${tv('Views', fmt(T.impr), 'var(--gsc)')}${tv('Google clicks', fmt(T.clicks), 'var(--gsc)')}${tv('Avg rank', rankText(T.pos), 'var(--pos)')}${tv('Search visits', fmt(T.org), 'var(--ga4)')}${tv(nd ? 'Visits w/o Direct' : 'All visits', fmt(T.sess), 'var(--visits)')}${tv('Partner clicks', fmt(T.aff), 'var(--partner)')}</div>`;
  if (!V.length) return tool + tbar + `<div class="panel">${noMatch('the site list')}</div>`;
  return tool + ecosystemTrend(L,w) + tbar + (state.view === 'table' ? sitesTable(V, nd) : `<section class="cards" aria-label="Sites">${V.map(v => siteCard(v, f)).join('')}</section>`);
}
function siteCard(v, f) {
  const { site: s, a, p, wp } = v, ah = v.ah?.[1] != null ? v.ah : null;
  const arrow = state.compare && p.impr && a.impr !== p.impr ? `<span class="a ${a.impr > p.impr ? 'up-a' : 'dn-a'}">${a.impr > p.impr ? '▲' : '▼'}</span>` : '';
  const sub = v.trend.k === 'new' ? `in Google since ${dm(v.trend.since)}` : a.pos ? `avg rank ${rankText(a.pos)}` : s.gsc_property ? 'no Google observations for this period' : 'GA4 only';
  const drTxt = ah ? (v.flags.some(x => x.k === 'drshared') ? `${ah[1].toFixed(0)}*` : ah[1].toFixed(1)) : '—';
  const z = n => !n ? ' class="zero"' : '';
  return `<button type="button" class="scard ${v.tint}" data-site="${s.slug}" aria-label="${esc(s.name)}: ${fmt(a.impr)} views, ${fmt(a.clicks)} clicks, ${fmt(a.org)} search visits. Open site view">
    <div class="sc-h">${avatar(s)}<div class="nm"><b>${hl(s.name, f)}</b><span class="meta">${statusChip(v, true)}<span>${VNAME[s.vertical] || s.vertical} · ${sub}</span></span></div></div>
    <div class="sc-m"><div><b${z(a.impr)}>${fmt(a.impr)}${arrow}</b><span>Views</span></div><div><b${z(a.clicks)}>${fmt(a.clicks)}</b><span>Clicks</span></div><div><b style="color:${a.pos ? PAGE_COL[bucketOf(a.pos)] : ''}"${z(a.pos)}>${rankText(a.pos)}</b><span>Avg rank</span></div></div>
    <div class="sc-f"><div><b${z(a.org)}>${fmt(a.org)}</b><span>Search visits</span></div><div><b${z(a.aff)}>${fmt(a.aff)}</b><span>Partner</span></div><div><b style="font-size:.8rem">${esc(s.platform)}</b><span>Platform</span></div><div><b${z(ah && ah[1])}>${drTxt}</b><span>DR</span></div></div></button>`;
}
function sitesTable(V, nd) {
  const cols = [['name', 'Site', 0], ['impr', 'Views', 1], ['growth', 'vs before', 1], ['clicks', 'Clicks', 1], ['ctr', 'Click rate', 1], ['pos', 'Avg rank', 1], ['org', 'Search visits', 1], ['sess', nd ? 'Visits w/o Direct' : 'All visits', 1], ['direct', 'Direct', 1], ['aff', 'Partner', 1], ['name', 'Platform', 0], ['dr', 'DR', 1]];
  const th = cols.map(([k, l, n]) => { const on = state.sort === k; return `<th class="${n ? 'n' : ''}"${on ? ` aria-sort="${state.sortDir > 0 ? 'ascending' : 'descending'}"` : ''}><button type="button" data-tsort="${k}">${l}${on ? (state.sortDir > 0 ? ' ▲' : ' ▼') : ''}</button></th>`; }).join('');
  const rows = V.map(v => { const { site: s, a, p, wp } = v, ah = v.ah?.[1] != null ? v.ah : null; const ci = oneIn(a.clicks, a.impr);
    return `<tr><td><span style="display:flex;gap:8px;align-items:center">${avatar(s, 'sm')}<span><button type="button" class="link" data-site="${s.slug}">${esc(s.name)}</button><br>${statusChip(v)}</span></span></td>
      <td class="n"><b>${fmt(a.impr)}</b></td><td class="n">${delta(a.impr, p.impr) || '<span class="dim">—</span>'}</td><td class="n">${fmt(a.clicks)}</td><td class="n">${ci ? '1 in ' + fmt(ci) : '<span class="dim">—</span>'}</td><td class="n">${rankTag(a.pos)}</td>
      <td class="n">${fmt(a.org)}</td><td class="n">${fmt(a.sess)}</td><td class="n">${a.sessAll ? pct(a.direct / a.sessAll) : '—'}</td><td class="n">${fmt(a.aff)}</td><td>${esc(s.platform)}</td><td class="n">${ah ? ah[1].toFixed(1) : '—'}</td></tr>`; }).join('');
  return `<section class="panel"><div class="tw"><table><thead><tr>${th}</tr></thead><tbody>${rows}</tbody></table></div></section>`;
}

/* ----- Google searches ----- */
function vSearches(L, w) {
  const f = findTxt(), T = totals(L, w.s, w.e), qs = queryAgg(L, w.s, w.e);
  const prevKeys = state.compare ? new Set(queryAgg(L, w.ps, w.pe).filter(q => q.i > 0).map(q => q.site.idx + ':' + q.key)) : null;
  const isNew = q => prevKeys && !prevKeys.has(q.site.idx + ':' + q.key);
  const b = buckets(qs), bt = b.reduce((a, x) => a + x.impr, 0), bmax = Math.max(1, ...b.map(x => x.impr));
  const ladder = bt ? `<div class="ladder">${b.map(x => `<div class="lrow" style="--pc:${x.c}"><span class="lb"><i></i>${x.l}</span><span class="bt" role="img" aria-label="${x.l}: ${fmt(x.impr)} views"><span style="width:${x.impr / bmax * 100}%"></span></span><span class="ln"><b>${pct(x.impr / bt, x.impr && x.impr / bt < .01 ? 1 : 0)}</b> · ${fmt(x.clicks)} ${plural(x.clicks, 'click')}</span></div>`).join('')}</div>
` : '<div class="empty">No named search terms in this period.</div>';
  const pts = qs.filter(q => q.i > 0 && q.pos).map(q => ({ x: q.pos, y: q.i, c: q.c, color: vhex(q.site.vertical), label: qsplit(q.text).q, site: q.site }));
  const legend = `<div class="legend">${[...new Set(L.map(s => s.vertical))].map(v => `<span><i style="background:${vhex(v)}"></i>${VNAME[v] || v}</span>`).join('')}<span><i style="background:var(--point-stroke);border-radius:50%"></i>got a click</span></div>`;
  let top = qs.filter(q => q.i > 0 || q.c > 0);
  if (f) top = top.filter(q => q.text.toLowerCase().includes(f) || q.site.name.includes(f));
  top.sort((a, b) => b.c - a.c || b.i - a.i);
  const shown = MORE.q ? top : top.slice(0, 15);
  const qTable = top.length ? `<div class="tw"><table><thead><tr><th>Search term</th><th>Site</th><th class="n">Views</th><th class="n">Clicks</th><th class="n">Avg rank</th></tr></thead><tbody>${shown.map(q => { const x = qsplit(q.text); return `<tr><td class="q">${hl(x.q, f)}${isNew(q) ? ' <span class="chip info">new</span>' : ''}${x.g ? `<small>group: ${esc(x.g)}</small>` : ''}</td><td>${siteChip(q.site)}</td><td class="n">${fmt(q.i)}</td><td class="n">${fmt(q.c)}</td><td class="n">${rankTag(q.pos)}</td></tr>`; }).join('')}</tbody></table></div>${more('q', top.length, shown.length)}` : (f ? noMatch('search terms') : '<div class="empty">No search terms in this period.</div>');
  let pages = pageAgg(L, w.s, w.e).filter(p => p.i > 0);
  if (f) pages = pages.filter(p => p.text.toLowerCase().includes(f) || p.site.name.includes(f));
  pages.sort((a, b) => b.c - a.c || b.i - a.i);
  const pShown = MORE.p ? pages : pages.slice(0, 10);
  const pTable = pages.length ? `<div class="tw"><table><thead><tr><th>Page</th><th class="n">Views</th><th class="n">Clicks</th><th class="n">Avg rank</th></tr></thead><tbody>${pShown.map(p => `<tr><td class="q" style="overflow-wrap:anywhere">${hl(p.text, f)}<small>${esc(p.site.name)}</small></td><td class="n">${fmt(p.i)}</td><td class="n">${fmt(p.c)}</td><td class="n">${rankTag(p.pos)}</td></tr>`).join('')}</tbody></table></div>${more('p', pages.length, pShown.length)}` : (f ? noMatch('pages') : '<div class="empty">No pages with views in this period.</div>');
  const fresh = prevKeys ? qs.filter(q => q.i > 0 && isNew(q)).sort((a, b) => b.i - a.i) : [];
  const newPanel = prevKeys ? `<div class="panel"><div class="ph"><h2>New search terms</h2><span class="meta">${fmt(fresh.length)} new</span>${info(`Terms that showed our sites this period but not in ${rangeTxt(w.ps, w.pe)}.`)}</div>
    ${fresh.length ? `<div class="bars">${fresh.slice(0, 8).map(q => `<div class="bar-r" style="--c:${vhex(q.site.vertical)}"><span class="nm">${esc(qsplit(q.text).q)} <span class="dim small">${esc(q.site.name)}</span></span><span class="n">${fmt(q.i)} views</span><span class="bt"><span style="width:${q.i / fresh[0].i * 100}%"></span></span></div>`).join('')}</div>` : '<div class="empty">No new search terms compared with the previous period.</div>'}</div>` : '';
  return `<div class="explain"><span class="src s-gsc">Search Console</span><span>to <b>${dm(Math.min(w.e, D.gscEnd))}</b></span>${info('What Google shows and what searchers click. Google finalises each day after 2–3 days.')}</div>
  <section class="grid2 wide"><div class="panel"><div class="ph"><h2>Opportunity map</h2>${info('Each dot is a search term. Right = lower on Google, up = more views. The green band holds positions 8–20, one push from page 1. Click a dot to open its site.')}<div class="right">${legend}</div></div>${pts.length ? scatterChart(pts, `Search terms by Google position and views, ${pts.length} terms`) : '<div class="empty">No search terms to plot in this period.</div>'}</div>
    <div class="panel"><div class="ph"><h2>Where we rank</h2><span class="meta">${fmt(qs.length)} terms · ${pct(T.impr ? bt / T.impr : 0)} of views</span>${info('Reported keyword views grouped by each keyword’s average rank for this period. This is not a count of individual rankings. Google omits some search terms; the coverage beside this title shows the share of total Google views represented.')}</div>${ladder}</div></section>
  <section class="panel"><div class="ph"><h2>Top search terms</h2><span class="meta">sorted by clicks, then views</span></div>${qTable}</section>
  <section class="${prevKeys ? 'grid2' : ''}"><div class="panel"><div class="ph"><h2>Top pages on Google</h2></div>${pTable}</div>${newPanel}</section>`;
}
