/* Current authority readings and explicit, cached competitor research. */
const AUTH = { site: 'mirai-skin', country: 'us', key: '', data: null, selected: [], busy: false, error: '', allowance: null, filter: 'all', custom: '', seeds: '' };
const MARKETS = [['us', '🇺🇸 United States'], ['gb', '🇬🇧 United Kingdom'], ['ca', '🇨🇦 Canada'], ['au', '🇦🇺 Australia'], ['de', '🇩🇪 Germany'], ['fr', '🇫🇷 France'], ['es', '🇪🇸 Spain'], ['it', '🇮🇹 Italy'], ['in', '🇮🇳 India']];
const drText = n => n == null || !Number.isFinite(n) ? '—' : n.toFixed(1);
const currentAh = s => s.ah.at(-1) || null;
const currentWp = s => s.wp.at(-1) || null;
const authorityKey = () => AUTH.site + ':' + AUTH.country;
const externalLink = (url, label) => {
  try { const u = new URL(url); if (!['https:', 'http:'].includes(u.protocol) || u.username || u.password) return esc(label); return `<a href="${esc(u.href)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`; } catch { return esc(label); }
};
const drChange = (s, ah) => {
  if (!ah || ah[1] == null) return '';
  const before = [...s.ah].reverse().find(r => r[0] <= isoOf(dayOf(ah[0]) - 30) && r[1] != null);
  if (!before) return '<span class="dim small">Building history</span>';
  const d = ah[1] - before[1];
  return `<span class="small ${d > 0 ? 'up-a' : d < 0 ? 'dn-a' : 'dim'}">${d > 0 ? '+' : ''}${d.toFixed(1)} since ${dm(before[0])}</span>`;
};
function authorityStatus(s) {
  const ah = currentAh(s), f = s.fetch.ahrefs;
  if (!D.ahrefs.configured) return '<span class="chip warn">Key not configured</span>';
  if (f?.status === 'not_configured') return '<span class="chip warn">Key added · refresh needed</span>';
  if (f && f.status !== 'ok') return `<span class="chip bad">${f.status === 'no_access' ? 'Access / quota issue' : 'Last fetch failed'}</span><small>${esc(shortMsg(f.message))}</small>`;
  if (!ah) return '<span class="chip warn">Not fetched yet</span>';
  return `<span class="chip ${TODAY - dayOf(ah[0]) > 7 ? 'warn' : 'good'}">Snapshot ${dm(ah[0])}</span>`;
}
function authorityProfile(L) {
  const chosen = L.find(s => s.slug === AUTH.site) || L[0], ah = chosen && currentAh(chosen);
  const card = (label, value, note) => `<div class="authority-metric"><span>${label}</span><b>${value}</b><small>${note}</small></div>`;
  const shared = chosen?.slug === 'slots-us-com';
  const isShared = chosen?.name === 'slots.us.com' || shared;
  return `<section class="panel authority-profile"><div class="ph"><h2>${esc(chosen?.name || 'Authority')}</h2><span class="src s-ahr">Ahrefs</span><span class="meta">Latest available snapshot${ah ? ' · ' + dm(ah[0]) : ''}</span></div>
    <p class="small muted">Current authority is shown independently of the Google date filter. DR measures backlink strength on a logarithmic 0–100 scale; it is not a Google rank.</p>
    <div class="authority-metrics">${card(isShared ? 'Parent-domain DR' : 'Domain Rating (DR)', drText(ah?.[1]), isShared ? 'Ahrefs rates us.com, not this site' : chosen ? drChange(chosen, ah) : '')}${card('Referring domains', fmt(ah?.[4]), 'Unique websites linking here')}${card('Backlinks', fmt(ah?.[2]), ah && ah[2] ? pct(ah[3] / ah[2]) + ' followed' : 'Links pointing to this site')}${card('Organic keywords', fmt(ah?.[5]), 'Ahrefs top 100 · all countries')}${card('Estimated search visits', fmt(ah?.[6]), 'Ahrefs monthly estimate · not GA4')}</div>
    ${ah?.[5] === 0 ? '<p class="small muted">Ahrefs currently reports no organic keywords for this site. Its index differs from Search Console; this does not mean Google sends no visits. Use explicit search terms or competitor domains below to research opportunities.</p>' : ''}
    <div class="authority-actions">${chosen ? authorityStatus(chosen) : ''}<button class="btn" data-ah="refresh" ${AUTH.busy || !D.ahrefs.configured ? 'disabled' : ''}>Refresh this site’s Ahrefs</button><span class="small dim">Up to 50 units · complete snapshots reused today</span></div></section>`;
}
function authorityPortfolio(L) {
  const f = findTxt(), sites = L.filter(s => !f || s.name.includes(f));
  return `<section class="panel"><div class="ph"><h2>Authority across selected sites</h2><span class="meta">Latest snapshots · click a site for research</span></div><div class="tw"><table><thead><tr><th>Site</th><th class="n">DR</th><th>Change</th><th class="n">Referring domains</th><th class="n">Backlinks</th><th class="n">Organic keywords</th><th>Data status</th></tr></thead><tbody>${sites.map(s => { const a = currentAh(s); return `<tr><td><button class="link" data-ahsite="${esc(s.slug)}">${esc(s.name)}</button>${s.name === 'slots.us.com' ? '<small>DR belongs to us.com</small>' : ''}</td><td class="n"><b class="c-pos">${drText(a?.[1])}</b></td><td>${drChange(s, a)}</td><td class="n">${fmt(a?.[4])}</td><td class="n">${fmt(a?.[2])}</td><td class="n">${fmt(a?.[5])}</td><td>${authorityStatus(s)}</td></tr>`; }).join('') || '<tr><td colspan="7">No sites match.</td></tr>'}</tbody></table></div></section>`;
}
function contentHealth(L, w) {
  const qs = queryAgg(L,w.s,w.e).filter(q=>q.i>0 && q.pos>10 && q.pos<=20).sort((a,b)=>b.i-a.i).slice(0,8);
  return `<section class="grid2"><div class="panel"><div class="ph"><h2>Pages within reach of the top 10</h2><span class="src s-gsc">Search Console</span></div><p class="small muted">Top reported query sample · ${rangeTxt(w.s,w.e)}. Review relevance before changing a page.</p><div class="tw"><table><thead><tr><th>Search term</th><th>Site</th><th>Views</th><th>Avg rank</th></tr></thead><tbody>${qs.map(q=>`<tr><td>${esc(q.text)}</td><td>${esc(q.site.name)}</td><td>${fmt(q.i)}</td><td>${rankText(q.pos)}</td></tr>`).join('') || '<tr><td colspan="4">No sampled queries average rank 11–20 in this period.</td></tr>'}</tbody></table></div></div><div class="panel"><div class="ph"><h2>Sitemap health</h2></div><p class="small muted">Submitted URLs are not indexed-page counts. Content is managed in Shopify and the satellite repositories.</p><div class="tw"><table><thead><tr><th>Site</th><th>Platform</th><th>Submitted URLs</th><th>Last Google read</th></tr></thead><tbody>${L.map(s=>`<tr><td>${esc(s.name)}</td><td>${esc(s.platform)}</td><td>${fmt(s.sm?.sub)}</td><td>${s.sm?.last ? dm(s.sm.last) : 'Not recorded'}</td></tr>`).join('')}</tbody></table></div></div></section>`;
}

function researchHTML() {
  const d = AUTH.data, discovery = d?.discover?.competitors?.length ? d.discover : (d?.serp || d?.discover), gap = d?.gap;
  const budget = d?.budget;
  const competitors = discovery?.competitors || [];
  const rows = (gap?.rows || []).filter(r => AUTH.filter === 'all' || r.kind === AUTH.filter);
  const status = AUTH.busy ? 'Working with Ahrefs…' : AUTH.error;
  const allowance = AUTH.allowance;
  const fromSearch = discovery?.kind === 'serp';
  const discoveryTable = competitors.length ? `<div class="tw"><table><thead><tr><th>Compare</th><th>Suggested competitor</th><th class="n">DR</th><th class="n">${fromSearch ? 'Sampled searches' : 'Shared keywords'}</th><th class="n">${fromSearch ? 'Matched search terms' : 'Competitor-only keywords'}</th></tr></thead><tbody>${competitors.map(c => `<tr><td><input type="checkbox" data-ahcompetitor="${esc(c.domain)}" aria-label="Compare ${esc(c.domain)}" ${AUTH.selected.includes(c.domain) ? 'checked' : ''} ${AUTH.busy ? 'disabled' : ''}></td><td>${externalLink('https://' + c.domain, c.domain)}</td><td class="n">${drText(c.dr)}</td><td class="n">${fmt(fromSearch ? c.seeds.length : c.common)}</td><td class="n">${fromSearch ? c.seeds.map(esc).join(', ') : fmt(c.missing)}</td></tr>`).join('')}</tbody></table></div>` : `<div class="empty">${discovery ? 'Ahrefs found no competitors in this report. You can enter relevant domains below.' : 'Find competitors to see domains that overlap with this site’s search keywords.'}</div>`;
  const gapTable = gap ? `<div class="ph"><h2>Content-gap opportunities</h2><select class="ctl-btn" id="ahGapFilter" aria-label="Content-gap type"><option value="all" ${AUTH.filter === 'all' ? 'selected' : ''}>All opportunities</option><option value="missing" ${AUTH.filter === 'missing' ? 'selected' : ''}>No ranking found</option><option value="weak" ${AUTH.filter === 'weak' ? 'selected' : ''}>Existing weak rankings</option></select><button class="reset" data-ah="export">Export CSV</button></div>
    <p class="small muted">${esc(gap.country.toUpperCase())} · Ahrefs data for ${esc(gap.date)} · ${fmt(gap.sampledKeywords)} unique keywords sampled from ${gap.competitors.map(esc).join(', ')}. ${gap.stale ? 'Saved report is older than 7 days; run again to refresh.' : ''}</p>
    <p class="small dim">Up to 30 non-branded top-10 keywords per competitor, ordered by estimated search volume. Target rankings are checked for every sampled keyword on the same date and market. “No ranking found” means Ahrefs did not return a ranking; it does not prove you lack a page. Volume and difficulty are Ahrefs estimates. This is a bounded sample, not a complete content audit.</p>
    ${rows.length ? `<div class="tw"><table class="gap-table"><thead><tr><th>Keyword / action</th><th class="n">Monthly volume</th><th class="n">Difficulty /100</th><th>Your ranking</th><th>Competitors in top 10</th></tr></thead><tbody>${rows.map(r => `<tr><td><b>${esc(r.keyword)}</b><small>${esc(r.action)}</small></td><td class="n">${fmt(r.volume)}</td><td class="n">${fmt(r.difficulty)}</td><td>${r.targetPosition == null ? '<span class="chip warn">No ranking found</span>' : externalLink(r.targetUrl, '#' + r.targetPosition + ' · existing page')}</td><td>${r.competitors.map(c => `<div>${externalLink(c.url, c.domain + ' · #' + c.position)}</div>`).join('')}</td></tr>`).join('')}</tbody></table></div>` : '<div class="empty">No opportunities match this report and filter. This does not mean there are no content gaps outside the sample.</div>'}` : '';
  return `<section class="panel research-panel" aria-busy="${AUTH.busy}"><div class="ph"><h2>Competitors & content gaps</h2><span class="src s-ahr">Ahrefs</span></div>
    <p class="small muted">Start with suggested competitors, review their relevance, then compare up to three. Results are saved for 7 days; opening this tab spends no Ahrefs units.</p>
    <div class="authority-actions"><button class="btn" data-ah="discover" ${AUTH.busy || !D.ahrefs.configured ? 'disabled' : ''}>Find competitors</button><span class="small dim">Up to 50 units</span><button class="ctl-btn" data-ah="allowance" ${AUTH.busy ? 'disabled' : ''}>Check API allowance</button></div>
    ${budget ? `<p class="small dim">Research budget: ${fmt(budget.remaining)} of ${fmt(budget.limit)} units left this calendar month. Refreshes use your separate account allowance.</p>` : ''}
    ${allowance ? `<p class="small muted">${esc(allowance.subscription || 'Ahrefs')} · ${allowance.remaining == null ? 'Allowance unverified' : fmt(allowance.remaining) + ' included API units remaining'}${allowance.resetDate ? ' · resets ' + esc(allowance.resetDate) : ''}</p>` : ''}
    <p class="authority-status ${AUTH.error ? 'c-bad' : 'muted'}" role="status">${esc(status)}</p>
    <div class="authority-actions"><label class="small" for="ahSeeds">Search terms to send to Ahrefs</label><input class="ctl-btn" id="ahSeeds" value="${esc(AUTH.seeds)}" aria-label="Search terms to send to Ahrefs" placeholder="e.g. AI writing tools, AI design tools" ${AUTH.busy ? 'disabled' : ''}><button class="ctl-btn" data-ah="serp" ${AUTH.busy || !D.ahrefs.configured ? 'disabled' : ''}>Send terms & suggest competitors</button><span class="small dim">1–3 comma-separated terms · up to 50 units each</span></div>
    ${discovery ? `<p class="small dim">Suggestions as of ${esc(discovery.date)}${discovery.stale ? ' · saved more than 7 days ago' : ''}. ${fromSearch ? 'Suggested from Ahrefs top-10 results for: ' + discovery.seedKeywords.map(esc).join(', ') + '. This is a small SERP sample, not a measured organic-overlap report.' : 'Shared keywords indicate search overlap, not necessarily business relevance.'}</p>` : ''}${discoveryTable}
    <div class="authority-actions"><label class="small" for="ahCustom">Or enter competitor domains</label><input class="ctl-btn" id="ahCustom" value="${esc(AUTH.custom)}" placeholder="example.com, another.com" aria-label="Competitor domains" ${AUTH.busy ? 'disabled' : ''}><button class="btn" data-ah="gap" ${AUTH.busy || !D.ahrefs.configured ? 'disabled' : ''}>Find content gaps</button><span class="small dim">Up to 810 units per competitor · maximum 2,430 per run</span></div>
    ${gapTable}</section>`;
}
function vAuthority(L, w) {
  if (!L.some(s => s.slug === AUTH.site)) AUTH.site = (L.find(s => s.slug === 'mirai-skin') || L[0])?.slug || '';
  if (AUTH.key !== authorityKey()) { AUTH.data = null; AUTH.selected = []; AUTH.custom = ''; AUTH.seeds = ''; }
  return `<div class="authority-controls"><label for="ahSite">Research site</label><select class="ctl-btn" id="ahSite" ${AUTH.busy ? 'disabled' : ''}>${L.map(s => `<option value="${esc(s.slug)}" ${AUTH.site === s.slug ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select><label for="ahCountry">Research market</label><select class="ctl-btn" id="ahCountry" ${AUTH.busy ? 'disabled' : ''}>${MARKETS.map(([k,n]) => `<option value="${k}" ${AUTH.country === k ? 'selected' : ''}>${n}</option>`).join('')}</select><span class="small dim">Market applies to competitor research</span></div>${authorityProfile(L)}${authorityPortfolio(L)}${researchHTML()}${contentHealth(L, w)}`;
}
async function authorityRequest(path, body) {
  const res = await fetch(`${BASE}/api/authority/${path}`, { credentials: 'same-origin', headers: { Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json', 'X-SEO-Request': '1' } : {}) }, ...(body ? { method: 'POST', body: JSON.stringify(body) } : {}) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.message || 'Ahrefs could not complete this request.');
  return data;
}
async function ensureAuthorityData(force = false) {
  const key = authorityKey();
  if (AUTH.key === key && !force) return;
  AUTH.key = key; AUTH.data = null; AUTH.selected = []; AUTH.error = '';
  try {
    const data = await authorityRequest(`research?site=${encodeURIComponent(AUTH.site)}&country=${AUTH.country}`);
    if (key !== authorityKey()) return;
    AUTH.data = data;
    AUTH.selected = data.gap?.competitors || [];
  } catch (e) { if (key === authorityKey()) AUTH.error = e.message; }
  if (key === authorityKey() && state.tab === 'authority') renderTab();
}
async function runAuthority(action) {
  if (AUTH.busy) return;
  if (action === 'export') return exportGap();
  const key = authorityKey(), site = AUTH.site, country = AUTH.country;
  const custom = $('#ahCustom')?.value.trim();
  const competitors = custom ? custom.split(/[\s,]+/).filter(Boolean) : AUTH.selected;
  const seedKeywords = ($('#ahSeeds')?.value || '').split(',').map(x => x.trim()).filter(Boolean);
  if (action === 'serp' && (!seedKeywords.length || seedKeywords.length > 3)) { AUTH.error = 'Enter one to three search terms to send to Ahrefs.'; return renderTab(); }
  if (action === 'gap' && (!competitors.length || competitors.length > 3)) { AUTH.error = 'Choose one to three competitors, or enter their domains.'; return renderTab(); }
  AUTH.busy = true; AUTH.error = ''; renderTab();
  try {
    const data = action === 'allowance' ? await authorityRequest('allowance') : await authorityRequest(action === 'refresh' ? 'refresh' : 'research', { site, country, kind: action, competitors, seedKeywords });
    if (action === 'refresh') { location.reload(); return; }
    if (key !== authorityKey()) return;
    if (action === 'allowance') { AUTH.allowance = data; if (!data.configured) AUTH.error = 'Ahrefs is not configured on the server.'; }
    else {
      await ensureAuthorityData(true);
      if (action === 'gap' && AUTH.data) AUTH.data.gap = data;
    }
  } catch (e) { if (key === authorityKey()) AUTH.error = e.message; }
  finally { AUTH.busy = false; if (state.tab === 'authority') renderTab(); }
}
function exportGap() {
  const report = AUTH.data?.gap; if (!report) return;
  const cell = v => '"' + String(v ?? '').replace(/^[\s]*[=+@-]/, x => "'" + x).replace(/"/g, '""') + '"';
  const rows = [['Site', 'Country', 'Date', 'Keyword', 'Monthly volume', 'Difficulty', 'Target position', 'Target URL', 'Competitors', 'Suggested action'], ...report.rows.map(r => [report.site, report.country, report.date, r.keyword, r.volume, r.difficulty, r.targetPosition, r.targetUrl, r.competitors.map(c => c.domain + ' #' + c.position).join('; '), r.action])];
  const url = URL.createObjectURL(new Blob([rows.map(r => r.map(cell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a'); a.href = url; a.download = `${report.site}-${report.country}-content-gaps-${report.date}.csv`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
document.addEventListener('click', e => {
  const b = e.target.closest('[data-ah],[data-ahsite]'); if (!b) return;
  if (b.dataset.ahsite) { AUTH.site = b.dataset.ahsite; renderTab(); return; }
  runAuthority(b.dataset.ah);
});
document.addEventListener('input', e => {
  if (e.target.id === 'ahCustom') AUTH.custom = e.target.value;
  if (e.target.id === 'ahSeeds') AUTH.seeds = e.target.value;
});
document.addEventListener('change', e => {
  if (e.target.id === 'ahSite' || e.target.id === 'ahCountry') { AUTH[e.target.id === 'ahSite' ? 'site' : 'country'] = e.target.value; AUTH.data = null; renderTab(); }
  if (e.target.id === 'ahGapFilter') { AUTH.filter = e.target.value; renderTab(); }
  if (e.target.dataset.ahcompetitor) {
    const domain = e.target.dataset.ahcompetitor;
    AUTH.selected = e.target.checked ? [...new Set([...AUTH.selected, domain])] : AUTH.selected.filter(c => c !== domain);
    if (AUTH.selected.length > 3) { AUTH.selected = AUTH.selected.filter(c => c !== domain); e.target.checked = false; AUTH.error = 'Choose up to three competitors.'; renderTab(); }
  }
});
