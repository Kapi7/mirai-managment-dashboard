/* ---------- site view (drawer) ---------- */
let lastFocus = null, openSlug = null;
const CH_LABEL = { 'Organic Search': 'Search engines', Direct: 'Direct', Unassigned: 'Unassigned', Referral: 'Other websites', 'AI Assistant': 'AI assistants', 'Organic Social': 'Social', 'Paid Search': 'Paid search', 'Cross-network': 'Cross-network', 'Paid Other': 'Paid other', 'Organic Video': 'Video' };
function chanAgg(site, s, e) {
  const m = new Map();
  for (const r of site.a) { if (r[0] < s) continue; if (r[0] > e) break; m.set(r[1], (m.get(r[1]) || 0) + r[2]); }
  return [...m.entries()].map(([c, n]) => ({ name: CH[c], n })).sort((a, b) => b.n - a.n);
}
function siteVerdict(v, w, eng) {
  const { site: s, a, p } = v, out = [];
  if (!s.gsc_property) out.push('This site is not in Search Console, so its Google visibility is unknown.');
  else if (v.flags.some(f => f.k === 'httpprop')) out.push('Search Console is connected to the <b>http://</b> version of this site, which shows no views. Google sends its traffic to the https:// site.');
  else if (!a.impr) out.push('Google did not show this site in this period.');
  else out.push(`Google showed it <b class="c-gsc">${fmt(a.impr)}</b> ${plural(a.impr, 'time')}${changeWords(a.impr, p.impr, w.n)}, with an average Google rank of <b class="c-pos">${rankText(a.pos)}</b> (weighted by views; lower is better), for <b class="c-gsc">${fmt(a.clicks)}</b> ${plural(a.clicks, 'click')}.`);
  if (a.sessAll) out.push(`It had ${fmt(a.sessAll)} ${plural(a.sessAll, 'visit')}; <b class="c-ga4">${fmt(a.org)}</b> came from search engines${eng[0] ? `, most of them from ${esc(eng[0].name)}` : ''}.`);
  else if (s.ga4) out.push('GA4 recorded no visits in this period.');
  if (v.flags.some(f => f.k === 'bots')) out.push(`<b class="c-warn">${pct(a.direct / a.sessAll)}</b> of visits were Direct, with no recorded referrer; this alone does not identify bots.`);
  if (a.aff) out.push(`Visitors clicked to partners <b class="c-part">${fmt(a.aff)}</b> ${plural(a.aff, 'time')}.`);
  else if (a.sessAll) out.push('No partner clicks were recorded.');
  if (v.wp.last != null) out.push(`Latest post: ${dm(v.wp.last)}.`);
  return out.join(' ');
}
function liveLine(s) {
  if (liveFor(s)) return `<div class="small dim" style="margin-top:10px">Lines marked “Live” come from the check at ${liveTime()}.</div>`;
  return `<div class="small dim" style="margin-top:10px">Stored status from the last fetch. <button type="button" class="reset" data-livecheck>${LIVE.state === 'running' ? 'Checking…' : 'Run a live check'}</button></div>`;
}
const mf = (l, v, sub, c) => `<div class="mf" style="--c:${c}"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${sub}</div></div>`;
function openSite(slug) {
  const s = siteBy(slug); if (!s) return;
  openSlug = slug;
  if (!$('.drawer')) lastFocus = document.activeElement;
  const w = win(), v = siteView(s, w), a = v.a, p = v.p;
  const S = series([s], w.s, w.e), SP = state.compare ? series([s], w.ps, w.pe) : {};
  const eng = engineAgg([s], w.s, w.e), geo = geoAgg([s], w.s, w.e).filter(g => countryMatches(g)), links = linkAgg([s], w.s, w.e), chans = chanAgg(s, w.s, w.e);
  const qs = queryAgg([s], w.s, w.e).filter(q => q.i > 0 || q.c > 0).sort((x, y) => y.c - x.c || y.i - x.i).slice(0, 10);
  const pages = pageAgg([s], w.s, w.e).filter(q => q.i > 0).sort((x, y) => y.c - x.c || y.i - x.i).slice(0, 8);
  const ci = oneIn(a.clicks, a.impr), R = rangeTxt(w.s, w.e);
  const chMax = Math.max(1, ...chans.map(c => c.n)), gMax = Math.max(1, ...geo.map(g => g.n)), lMax = Math.max(1, ...links.map(l => l.n));
  const extra = v.flags.slice(1).map(f => `<span class="chip ${f.sev}">${esc(f.short)}</span>`).join('');
  const bars = (list, max, color, label) => list.length ? `<div class="bars">${list.map(x => `<div class="bar-r" style="--c:${color(x)}"><span class="nm">${label(x)}</span><span class="n">${fmt(x.n)}</span><span class="bt"><span style="width:${x.n / max * 100}%"></span></span></div>`).join('')}</div>` : '<div class="empty">Nothing recorded in this period.</div>';
  $('#dwRoot').innerHTML = `<div class="scrim" data-close></div>
  <aside class="drawer" role="dialog" aria-modal="true" aria-labelledby="dw-title">
    <div class="dw-h">${avatar(s, 'lg')}<div style="min-width:0"><h2 id="dw-title">${esc(s.name)}</h2><div class="small muted">${VNAME[s.vertical] || s.vertical} · <a href="https://${esc(s.name)}" target="_blank" rel="noopener">Open site ↗</a> · ${R}</div></div>
      <button type="button" class="x" data-close aria-label="Close site view">✕</button></div>
    <div style="display:flex;gap:6px;flex-wrap:wrap">${statusChip(v)}${extra}</div>
    <details class="sumd"><summary>${icon('pulse')}In plain words<span class="cv" aria-hidden="true">&#9662;</span></summary><p>${siteVerdict(v, w, eng)}</p></details>
    <div class="mf4">${mf('Seen on Google', fmt(a.impr), `${delta(a.impr, p.impr)} ${a.pos ? 'avg rank ' + rankText(a.pos) : ''}`, 'var(--gsc)')}${mf('Google clicks', fmt(a.clicks), ci ? `1 in ${fmt(ci)} views` : 'no clicks', 'var(--gsc)')}${mf('Search visits', fmt(a.org), eng.slice(0, 2).map(e => `${esc(e.name)} ${fmt(e.n)}`).join(' · ') || 'none', 'var(--ga4)')}${mf('Partner clicks', fmt(a.aff), delta(a.aff, p.aff) || '&nbsp;', 'var(--partner)')}</div>
    <section class="grid2"><div class="panel"><div class="ph"><h2>Seen on Google</h2><span class="src s-gsc">GSC</span></div>${timeChart({ s: w.s, e: w.e, site: s.slug, h: 140, series: [{ label: 'Views', color: 'var(--gsc)', vals: S.impr, prev: SP.impr, kind: 'area' }, { label: 'Clicks', color: 'var(--clicks)', vals: S.clicks, kind: 'bars' }], aria: `Daily Google views for ${s.name}` })}</div>
      <div class="panel"><div class="ph"><h2>Visits from search</h2><span class="src s-ga4">GA4</span></div>${timeChart({ s: w.s, e: w.e, site: s.slug, h: 140, series: [{ label: 'Search visits', color: 'var(--ga4)', vals: S.org, prev: SP.org, kind: 'area' }], aria: `Daily search visits for ${s.name}` })}</div></section>
    <section class="panel"><div class="ph"><h2>Top search terms</h2><span class="src s-gsc">GSC</span></div>${qs.length ? `<div class="tw"><table><thead><tr><th>Search term</th><th class="n">Views</th><th class="n">Clicks</th><th class="n">Avg rank</th></tr></thead><tbody>${qs.map(q => `<tr><td class="q">${esc(qsplit(q.text).q)}</td><td class="n">${fmt(q.i)}</td><td class="n">${fmt(q.c)}</td><td class="n">${rankTag(q.pos)}</td></tr>`).join('')}</tbody></table></div>` : `<div class="empty">${s.gsc_property ? 'Google reported no search terms for this site in this period.' : 'This site is not in Search Console.'}</div>`}</section>
    ${pages.length ? `<section class="panel"><div class="ph"><h2>Top pages on Google</h2></div><div class="tw"><table><thead><tr><th>Page</th><th class="n">Views</th><th class="n">Avg rank</th></tr></thead><tbody>${pages.map(q => `<tr><td class="q" style="overflow-wrap:anywhere">${esc(q.text)}</td><td class="n">${fmt(q.i)}</td><td class="n">${rankTag(q.pos)}</td></tr>`).join('')}</tbody></table></div></section>` : ''}
    <section class="grid2"><div class="panel"><div class="ph"><h2>How visitors arrive</h2><span class="src s-ga4">GA4</span></div>${bars(chans, chMax, x => x.name === 'Organic Search' ? 'var(--ga4)' : x.name === 'Direct' ? 'var(--direct)' : 'var(--other)', x => esc(CH_LABEL[x.name] || x.name))}</div>
      <div class="panel"><div class="ph"><h2>Countries</h2><span class="src s-ga4">GA4</span><span class="meta">${selectedCountry() ? esc(countryLabel(selectedCountry())) : "All countries"} · includes Direct</span></div>${bars(geo.slice(0, 8), gMax, x => SGCN.has(x.name) ? 'var(--warn)' : 'var(--ga4)', x => `<span class="cc" aria-hidden="true">${countryFlag(x.iso)}</span>${esc(x.name === "(not set)" ? "Unknown country" : x.name)}`)}</div></section>
    ${links.length ? `<section class="panel"><div class="ph"><h2>Where partner clicks go</h2></div>${bars(links.slice(0, 8), lMax, () => 'var(--partner)', x => esc(x.host))}</section>` : ''}
    <section class="grid2"><div class="panel"><div class="ph"><h2>Authority &amp; content</h2></div><div class="mf4" style="grid-template-columns:repeat(2,minmax(0,1fr))">
      ${mf('Current DR', v.ah?.[1] != null ? v.ah[1].toFixed(1) : '—', v.flags.some(f => f.k === 'drshared') ? 'rating of us.com' : v.ah ? `Ahrefs, ${dm(v.ah[0])}` : 'no snapshot', 'var(--ahr)')}${mf('Backlinks', v.ah ? fmt(v.ah[2]) : '—', v.ah ? `${pct(v.ah[3] / Math.max(1, v.ah[2]))} follow` : '&nbsp;', 'var(--ahr)')}
      ${mf('Posts', v.wp.total == null ? '—' : fmt(v.wp.total), v.wp.added ? `+${v.wp.added} in period` : 'none added', 'var(--wp)')}${mf('Sitemap pages', s.sm ? fmt(s.sm.sub) : '—', s.sm && s.sm.last ? `Google read it ${dm(s.sm.last)}` : 'never read', 'var(--wp)')}</div></div>
      <div class="panel"><div class="ph"><h2>Connections</h2></div><div class="tw"><table><tbody>${SRCDEF.map(src => `<tr><td class="small muted">${src.name}</td><td>${cellHTML(s, src.k)}</td></tr>`).join('')}</tbody></table></div>${liveLine(s)}</div></section>
  </aside>`;
  document.body.style.overflow = 'hidden';
  mountCharts($('#dwRoot'));
  $('.drawer .x').focus();
}
function closeSite() { openSlug = null; $('#dwRoot').innerHTML = ''; document.body.style.overflow = ''; if (lastFocus && lastFocus.isConnected) lastFocus.focus(); }
