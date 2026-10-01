// Observed session sources are separate from outbound intent. A satellite click
// is never labelled a sale without an order-level attribution join.
const isAiSource = source => /(^|\.)(chatgpt\.com|chat\.openai\.com|perplexity\.ai|claude\.ai|gemini\.google\.com|copilot\.microsoft\.com)$/.test(String(source).toLowerCase());
const isSatelliteSource = source => /(^|\.)(glow-coded\.com|rooted-glow\.com)$/.test(String(source).toLowerCase());
function commerceRows(L, w) {
  return L.flatMap(site => (site.sales || []).filter(r => r[0] >= w.s && r[0] <= w.e).map(r => ({ site, date: r[0], source: r[1], medium: r[2], sessions: r[3], purchases: r[4], revenue: r[5] })));
}
function commerceTotals(L, w) {
  const rows = commerceRows(L, w);
  const known = L.length > 0 && L.every(s => s.fetch.ga4_commerce?.status === 'ok');
  return { known, purchases: rows.reduce((n, r) => n + r.purchases, 0), revenue: rows.reduce((n, r) => n + r.revenue, 0) };
}
function vEcosystem(L, w) {
  const selected = commerceRows(L, w), groups = new Map();
  for (const r of selected) {
    const key = `${r.site.slug}|${r.source}|${r.medium}`;
    if (!groups.has(key)) groups.set(key, { ...r, sessions: 0, purchases: 0, revenue: 0 });
    const g = groups.get(key); g.sessions += r.sessions; g.purchases += r.purchases; g.revenue += r.revenue;
  }
  const rows = [...groups.values()].filter(r => `${r.site.name} ${r.source} ${r.medium}`.toLowerCase().includes(findTxt())).sort((a,b) => b.purchases-a.purchases || b.sessions-a.sessions);
  const lanes = [
    ['Organic search', r => r.medium === 'organic', 'var(--gsc)'],
    ['AI referrals', r => isAiSource(r.source), 'var(--pos)'],
    ['Satellite referrals', r => isSatelliteSource(r.source), 'var(--good)'],
  ];
  const known = commerceTotals(L, w).known;
  const money = n => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD',maximumFractionDigits:2}).format(n);
  const cards = lanes.map(([name, filter, color]) => {
    const all = selected.filter(filter), sums = all.reduce((t,r) => ({ sessions:t.sessions+r.sessions, purchases:t.purchases+r.purchases,revenue:t.revenue+r.revenue }), {sessions:0,purchases:0,revenue:0});
    return `<div class="panel commerce-lane" style="--c:${color}"><h2>${name}</h2><b>${known ? fmt(sums.sessions) : '—'}</b><span>observed sessions</span><p>${known ? fmt(sums.purchases) : '—'} analytics purchases · ${known ? money(sums.revenue) : '—'} purchase revenue</p></div>`;
  }).join('');
  const outbound = linkAgg(L.filter(s => s.vertical === 'Satellites'), w.s, w.e).filter(r => /(^|\.)mirai-skin\.com$/.test(r.host));
  return `<div class="explain"><b>From discovery to Mirai</b><span>${rangeTxt(w.s,w.e)} · selected sites · all traffic</span></div>
    <p class="small muted">Source and medium are GA4 session attribution. Analytics purchases and USD purchase revenue are not reconciled paid Shopify orders. Satellite referrals only include a recorded satellite source; missing referrers stay unattributed. The Direct and country controls do not filter this view.</p>
    <section class="commerce-lanes">${cards}</section>
    <section class="panel"><div class="ph"><h2>Traffic and purchases by source</h2><span class="src s-ga4">GA4</span><a class="right" href="/Reports" target="_top">Open Mirai sales reports ↗</a></div>
    <div class="tw"><table><thead><tr><th>Site</th><th>Source / medium</th><th class="n">Sessions</th><th class="n">Purchases</th><th class="n">Revenue · USD</th></tr></thead><tbody>${rows.slice(0, MORE.commerce ? undefined : 25).map(r => `<tr><td>${esc(r.site.name)}</td><td>${esc(r.source)} / ${esc(r.medium)}</td><td class="n">${fmt(r.sessions)}</td><td class="n">${fmt(r.purchases)}</td><td class="n">${money(r.revenue)}</td></tr>`).join('') || `<tr><td colspan="5">${known ? 'No matching observations in this period.' : 'Commerce data has not been collected. Refresh Google data to check this source.'}</td></tr>`}</tbody></table></div>${more('commerce',rows.length,25)}</section>
    <section class="panel"><div class="ph"><h2>Satellite clicks toward Mirai</h2><span class="meta">Tracked outbound intent</span></div><p class="small muted">Clicks are separate from sessions and purchases. They are not a cross-site customer journey or proof of sales.</p><div class="tw"><table><thead><tr><th>Destination</th><th class="n">Clicks</th></tr></thead><tbody>${outbound.map(r => `<tr><td>${esc(r.host)}</td><td class="n">${fmt(r.n)}</td></tr>`).join('') || `<tr><td colspan="2">${L.some(s => s.vertical === 'Satellites') ? 'No Mirai destination was present in the selected satellites’ recorded outbound events. This does not establish zero referrals.' : 'Choose Ecosystem or Satellites to inspect their tracked outbound clicks toward Mirai.'}</td></tr>`}</tbody></table></div></section>`;
}
