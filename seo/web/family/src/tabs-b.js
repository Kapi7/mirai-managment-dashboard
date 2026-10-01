/* ----- Visits ----- */
const SGCN = new Set();
function vVisits(L, w) {
  const f = findTxt(), nd = state.traffic === 'nodirect', T = totals(L, w.s, w.e);
  const eng = engineAgg(L, w.s, w.e), etot = eng.reduce((a, e) => a + e.n, 0), emax = Math.max(1, ...eng.map(e => e.n));
  const V = L.map(s => siteView(s, w));
  const bots = V.filter(v => v.flags.some(x => x.k === 'bots'));
  const banner = bots.length && !nd ? `<div class="banner warn"><span class="bi" aria-hidden="true">!</span><div class="bn"><b class="t">Direct traffic needs context</b>${bots.map(v => `<span class="chip warn">${esc(v.site.name)} ${pct(v.a.direct / v.a.sessAll)}</span>`).join('')}${info('Share of visits that arrived as Direct traffic, with unusually low engagement.')}<button type="button" class="chipbtn" data-traffic="nodirect">Hide Direct</button></div></div>` : '';
  const engPanel = `<div class="panel"><div class="ph"><h2>Search engines</h2><span class="meta">${fmt(etot)} visits</span>${info(`Search Console counts ${fmt(T.clicks)} Google clicks for these days; GA4 counts ${fmt((eng.find(e => e.name === 'Google') || { n: 0 }).n)} Google visits. Search Console never sees Bing, DuckDuckGo or Yahoo.`)}</div>${eng.length ? `<div class="engines">${eng.map(e => `<div class="eng" style="--c:${ENG_COL[e.name] || 'var(--other)'};grid-template-columns:96px minmax(0,1fr) 44px 50px"><span>${esc(e.name)}</span><span class="bt"><span style="width:${e.n / emax * 100}%"></span></span><span class="n">${fmt(e.n)}</span><span class="dim small" style="text-align:right">${pct(e.n / etot)}</span></div>`).join('')}</div>
` : '<div class="empty">No search visits in this period.</div>'}</div>`;
  const other = T.sessAll - T.direct - T.org, engOther = T.engAll - T.engDir - T.engOrg;
  const eRows = [['From search engines', T.engOrg, T.org, 'var(--ga4)'], ['Direct', T.engDir, T.direct, 'var(--direct)'], ['Everything else', engOther, other, 'var(--other)']].filter(r => r[2] > 0);
  const ratio = T.org && T.direct && T.engDir ? (T.engOrg / T.org) / (T.engDir / T.direct) : null;
  const engage = `<div class="panel"><div class="ph"><h2>Who actually reads</h2><span class="meta">engaged share</span>${info('GA4 counts a visit as engaged when it lasts over 10 seconds, views 2+ pages or converts.')}${ratio && ratio > 1.2 ? `<div class="right"><span class="chip good">search ${ratio.toFixed(1)}× more engaged</span></div>` : ''}</div>${eRows.length ? `<div class="bars">${eRows.map(([l, e, n, c]) => `<div class="bar-r" style="--c:${c}"><span class="nm">${l} <span class="dim small">${fmt(n)} visits</span></span><span class="n">${pct(e / n)}</span><span class="bt"><span style="width:${e / n * 100}%"></span></span></div>`).join('')}</div>` : '<div class="empty">No visits in this period.</div>'}</div>`;
  let rows = [...V].filter(v => v.a.sessAll > 0).sort((a, b) => b.a.sessAll - a.a.sessAll);
  if (f) rows = rows.filter(v => v.site.name.includes(f));
  const mix = `<section class="panel"><div class="ph"><h2>How visitors arrive</h2><span class="meta">each bar is one site’s visits${nd ? ' without Direct' : ''}, split by source</span><div class="right legend"><span><i style="background:var(--ga4)"></i>Search engines</span>${nd ? '' : '<span><i style="background:var(--direct)"></i>Direct</span>'}<span><i style="background:var(--other)"></i>Other</span></div></div>
    <div class="vrow h"><span>Site</span><span style="text-align:right">Visits</span><span>Mix</span><span class="vx" style="text-align:right">From search</span></div>
    ${rows.length ? rows.map(v => { const a = v.a, o = a.org, d = nd ? 0 : a.direct, ot = Math.max(0, a.sess - o - d);
      return `<div class="vrow"><span style="display:flex;gap:8px;align-items:center;min-width:0">${avatar(v.site, 'sm')}<button type="button" class="link" data-site="${v.site.slug}">${hl(v.site.name, f)}</button></span><span class="num" style="text-align:right;font-weight:800">${fmt(a.sess)} ${delta(a.sess, v.p.sess)}</span>
      <span class="stk"><span class="stack" role="img" aria-label="Search ${fmt(o)}, Direct ${fmt(d)}, other ${fmt(ot)}">${a.sess ? `<span style="width:${o / a.sess * 100}%;background:var(--ga4)"></span><span style="width:${d / a.sess * 100}%;background:var(--direct)"></span><span style="width:${ot / a.sess * 100}%;background:var(--other)"></span>` : ''}</span></span>
      <span class="vx num" style="text-align:right"><b>${fmt(o)}</b> <span class="dim small">${a.sess ? pct(o / a.sess) : ''}</span></span></div>`; }).join('') : (f ? noMatch('sites') : '<div class="empty">No visits in this period.</div>')}</section>`;
  const allGeo = geoAgg(L, w.s, w.e), gtot = allGeo.reduce((a, g) => a + g.n, 0);
  const geo = allGeo.filter(g => countryMatches(g, f)), gmax = Math.max(1, ...geo.map(g => g.n));
  const geoPanel = `<div class="panel" id="countriesPanel"><div class="ph"><h2>Countries</h2><span class="meta">${selectedCountry() ? esc(countryLabel(selectedCountry())) : 'All countries'} · all visits</span><button type="button" class="reset" data-editfilters>Filter countries</button></div><p class="small muted">Includes Direct. Country selection applies here and in site country breakdowns; other dashboard totals stay across all countries.</p>${geo.length ? `<div class="bars">${geo.slice(0, MORE.geo ? undefined : 10).map(g => `<div class="bar-r" style="--c:${SGCN.has(g.name) ? 'var(--warn)' : 'var(--ga4)'}"><span class="nm"><span class="cc" aria-hidden="true">${countryFlag(g.iso)}</span>${hl(g.name === '(not set)' ? 'Unknown country' : g.name, f)}${SGCN.has(g.name) ? ' <span class="chip warn">review engagement</span>' : ''}</span><span class="n">${fmt(g.n)} <span class="dim small">${gtot ? pct(g.n / gtot) : '—'}</span></span><span class="bt"><span style="width:${g.n / gmax * 100}%"></span></span></div>`).join('')}</div><p class="small dim">Percentages are a share of all country visits for the selected sites and dates.</p>${more('geo', geo.length, 10)}` : `<div class="empty">${state.country ? 'No country data for this selection and date range.' : f ? 'No countries match the search.' : 'No country data in this period.'}</div>`}</div>`;
  let links = linkAgg(L, w.s, w.e); if (f) links = links.filter(l => l.host.includes(f));
  const lmax = Math.max(1, ...links.map(l => l.n));
  const partners = `<div class="panel"><div class="ph"><h2>Where partner clicks go</h2></div>${links.length ? `<div class="bars">${links.slice(0, 10).map(l => `<div class="bar-r" style="--c:var(--partner)"><span class="nm" title="${esc([...l.urls][0])}">${hl(l.host, f)} <span class="dim small">${[...l.sites].map(x => esc(siteBy(x).name)).join(', ')}</span></span><span class="n">${fmt(l.n)}</span><span class="bt"><span style="width:${l.n / lmax * 100}%"></span></span></div>`).join('')}</div>` : (f ? noMatch('partner links') : '<div class="empty">No partner clicks with a link recorded in this period.</div>')}</div>`;
  const track = `<section class="panel"><div class="ph"><h2>Partner click tracking</h2>${info('Whether each site sends affiliate_click or outbound_click events to GA4.')}</div><div class="tw"><table><thead><tr><th>Site</th><th class="n">Partner clicks</th><th class="n">Per 100 search visits</th><th>Tracking</th></tr></thead><tbody>
    ${[...V].filter(v => !f || v.site.name.includes(f)).sort((a, b) => b.a.aff - a.a.aff || b.a.sessAll - a.a.sessAll).map(v => `<tr><td><button type="button" class="link" data-site="${v.site.slug}">${esc(v.site.name)}</button></td><td class="n"><b>${fmt(v.a.aff)}</b> ${delta(v.a.aff, v.p.aff)}</td><td class="n">${v.a.org ? Math.round(v.a.aff / v.a.org * 100) : '—'}</td>
      <td>${v.a.aff || v.p.aff ? '<span class="chip good">Events arriving</span>' : v.a.sessAll ? '<span class="chip warn">No events in two periods</span>' : '<span class="chip mute">No visits</span>'}</td></tr>`).join('')}</tbody></table></div></section>`;
  return `<div class="explain"><span class="src s-ga4">Analytics 4</span><span>to <b>${dm(Math.min(w.e, D.ga4End))}</b></span>${info('Visits, sources, countries and partner clicks. GA4 finalises each day within 48 hours.')}</div>
  ${banner}<section class="grid2">${engPanel}${engage}</section>${mix}<section class="grid2">${geoPanel}${partners}</section>${track}`;
}

/* ----- Connections ----- */
const liveTime = () => (LIVE.at ? new Date(LIVE.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '');
const LIVE_COLS = [['gsc', 'Search Console'], ['ga4', 'Analytics'], ['ga4Outbound', 'Partner events'], ['robots', 'Robots'], ['llms', 'AI discovery'], ['sitemap', 'Sitemap'], ['statusCode', 'Site answers']];
function livePanel(act) {
  const btn = `<button type="button" class="btn" data-livecheck ${LIVE.state === 'running' ? 'disabled' : ''}>${LIVE.state === 'running' ? 'Checking…' : LIVE.state === 'done' ? 'Run again' : 'Run live check'}</button>`;
  const fails = LIVE.sites ? LIVE.sites.reduce((n, r) => n + LIVE_COLS.filter(([k]) => r[k] && liveState(r[k]).st === 'denied').length, 0) : 0;
  const head = `<div class="ph"><h2>Live check</h2>${info('Runs the server’s connection checker now, with the production credentials: Search Console access, GA4, partner-click events, robots, AI discovery, sitemap and whether the site answers.')}${LIVE.state === 'done' ? `<span class="meta">${liveTime()} · ${fails} ${plural(fails, 'failure')}</span>` : ''}<div class="right">${btn}</div></div>`;
  let body;
  if (LIVE.state === 'error') body = `<div class="banner bad"><span class="bi" aria-hidden="true">!</span><div class="bn"><b class="t">The live check failed</b><span class="small muted">${esc(LIVE.error)}</span></div></div>`;
  else if (!LIVE.sites) body = `<div class="empty">${LIVE.state === 'running' ? `Checking ${act.length} sites…` : 'Tests every site against Google and the live sites. Takes about 10 seconds.'}</div>`;
  else body = `<div class="tw"><table class="matrix"><thead><tr><th>Site</th>${LIVE_COLS.map(([, l]) => `<th>${l}</th>`).join('')}</tr></thead><tbody>${act.map(s => { const r = liveFor(s); if (!r) return ''; return `<tr><td><button type="button" class="link" data-site="${s.slug}">${esc(s.name)}</button></td>${LIVE_COLS.map(([k]) => { const x = liveState(r[k]); return `<td><span class="cell" title="${esc(x.msg)}"><span class="st ${x.st}"><i aria-hidden="true">${ICON[x.st]}</i>${esc(x.label)}</span>${x.suggestion ? `<small>try ${esc(x.suggestion)}</small>` : ''}</span></td>`; }).join('')}</tr>`; }).join('')}</tbody></table></div>`;
  return `<section class="panel" aria-live="polite">${head}${body}</section>`;
}
function vConnections(L, w) {
  const all = SITES.filter(s => (state.lens === 'All' || s.vertical === state.lens) && (!state.sites || s.excluded || state.sites.has(s.slug)));
  const act = all.filter(s => !s.excluded);
  const cards = SRCDEF.map(src => { const cs = act.map(s => cellState(s, src.k)), ok = cs.filter(c => c.st === 'ok').length;
    return `<div class="scn" style="--c:${src.c}"><div class="top"><span class="logo">${src.logo}</span><div><div class="name">${src.name}</div><div class="what">${src.what}</div></div></div><div class="ratio">${ok}<small> of ${act.length} healthy</small></div><div class="segs" aria-hidden="true">${cs.map(c => `<i style="--c:${{ ok: 'var(--good)', stale: 'var(--warn)', denied: 'var(--bad)' }[c.st] || 'var(--line)'}"></i>`).join('')}</div></div>`; }).join('');
  const n = w.e - w.s + 1, hrows = [];
  [...act].sort((a, b) => a.name.localeCompare(b.name)).forEach(s => {
    const g = new Array(n).fill(null), a = new Array(n).fill(null);
    for (const r of s.g) { if (r[0] < w.s) continue; if (r[0] > w.e) break; g[r[0] - w.s] = r[2]; }
    for (const r of s.a) { if (r[0] < w.s) continue; if (r[0] > w.e) break; a[r[0] - w.s] = (a[r[0] - w.s] || 0) + r[2]; }
    hrows.push({ site: s.name, label: s.name, src: 'GSC', color: 'var(--gsc)', unit: 'views', vals: g, first: true }, { site: s.name, label: s.name, src: 'GA4', color: 'var(--ga4)', unit: 'visits', vals: a });
  });
  const F = fixItems(act);
  return `<div class="explain"><span>Stored <b>${dm(D.lastFetch)}</b></span>${LIVE.state === 'done' ? `<span style="color:var(--info)">Live check <b>${liveTime()}</b></span>` : ''}${info(`Stored status comes from the last fetch (${dm(D.lastFetch)}, ${String(D.lastFetch || '').slice(11, 16)} UTC). The live check tests every site now, with the server’s credentials.`)}</div>
  <section class="srccards">${cards}</section>${livePanel(act)}
  <section class="panel"><div class="ph"><h2>Is data arriving?</h2>${info(`One cell per ${n > 91 ? 'week' : 'day'}. A strip that goes dark means that source stopped sending data for the site; brighter cells mean more views or visits.`)}<div class="right legend"><span><i style="background:var(--gsc)"></i>Google views</span><span><i style="background:var(--ga4)"></i>Visits</span><span><i style="background:rgba(148,163,184,.3)"></i>recorded zero</span><span><i style="background:var(--inset);border:1px solid var(--line)"></i>nothing recorded</span></div></div>
    ${hrows.length ? heatmap(hrows, w.s, w.e, `Data arrival for ${act.length} sites`) : '<div class="empty">No sites selected.</div>'}
</section>
  <section class="panel"><div class="ph"><h2>Every site, every source</h2><span class="meta">${all.length} sites</span></div><div class="tw"><table class="matrix"><thead><tr><th>Site</th>${SRCDEF.map(s => `<th><span class="src ${s.cls}">${s.name}</span></th>`).join('')}</tr></thead><tbody>
    ${all.map(s => `<tr><td><button type="button" class="link" data-site="${s.slug}">${esc(s.name)}</button></td>${SRCDEF.map(src => `<td>${cellHTML(s, src.k)}</td>`).join('')}</tr>`).join('')}</tbody></table></div></section>
  <section class="grid2"><div class="panel"><div class="ph"><h2>Who signs in</h2><span class="meta">Google and Ahrefs credentials</span></div><div class="ids">${identities()}</div></div>
    <div class="panel"><div class="ph"><h2>What to fix</h2><span class="meta">${F.length} items</span></div><div class="fix">${F.map(fxHTML).join('')}</div></div></section>
  <section class="panel"><div class="ph"><h2>Mirai ecosystem</h2><span class="meta">Mirai Skin and its two satellites</span></div><div class="flow">
    <div class="fnode"><b>Mirai Skin</b><span>Shopify · main store</span></div><span class="farrow" aria-hidden="true"></span>
    <div class="fnode"><b>Glow Coded + Rooted Glow</b><span>Cloudflare Pages · satellite discovery</span></div><span class="farrow" aria-hidden="true"></span>
    <div class="fnode"><b>Measured sources</b><span>Google visibility, analytics traffic and purchases, Ahrefs authority</span></div><span class="farrow" aria-hidden="true"></span>
    <div class="fnode"><b>Marketing → SEO</b><span>Protected by your Mirai Management login</span></div></div><p class="small muted">${D.refresh?.automatic ? 'Google data refreshes daily while the service is running.' : 'Google data refresh is manual on this server.'} ${D.refresh?.durable ? 'History is preserved across deployments.' : 'This preview uses local history.'} Ahrefs research runs only when requested.</p></section>`;
}
