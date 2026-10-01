/* ---------- icons ---------- */
const IC = {
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
  click: '<path d="M4 3l7 17 2.5-7.5L21 10z"/>',
  ladder: '<path d="M4 20V10M10 20V4M16 20v-7M21 20H3"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
  out: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14.5a6 6 0 0 1 3.5 5.5"/>',
  bot: '<rect x="4" y="8" width="16" height="11" rx="3"/><path d="M12 4v4M9 13h.01M15 13h.01M2 13v2M22 13v2"/>',
  pulse: '<path d="M3 12h4l2.5-6 5 12 2.5-6H21"/>',
  pen: '<path d="M4 20h4L19 9l-4-4L4 16v4ZM14 6l4 4"/>',
  shield: '<path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/>',
  rise: '<path d="M3 17l6-6 4 4 8-8M15 7h6v6"/>',
  target: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
  alert: '<path d="M12 3 2 21h20L12 3Z"/><path d="M12 10v5M12 18h.01"/>',
  plug: '<path d="M9 7V3M15 7V3M7 7h10v4a5 5 0 0 1-10 0V7ZM12 16v5"/>',
  cal: '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/>',
  grid: '<path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"/>',
  dice: '<rect x="3.5" y="3.5" width="17" height="17" rx="4"/><path d="M8.5 8.5h.01M15.5 15.5h.01M12 12h.01M15.5 8.5h.01M8.5 15.5h.01" stroke-width="3"/>',
  spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 15l.7 1.8 1.8.7-1.8.7L19 20l-.7-1.8-1.8-.7 1.8-.7z"/>',
  bars: '<path d="M3 20h18l-1.6-5H4.6zM6.5 15l1.3-4.5h8.4L17.5 15M9 10.5 10.2 6h3.6l1.2 4.5"/>',
  tag: '<path d="M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9z"/><circle cx="7.5" cy="7.5" r="1.3"/>',
  site: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M3 9h18M7 6.5h.01M10 6.5h.01"/>',
};
const icon = (k, sz = 14) => `<svg width="${sz}" height="${sz}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${IC[k]}</svg>`;
const TONE = { good: 'var(--good)', bad: 'var(--bad)', warn: 'var(--warn)', info: 'var(--info)', mute: 'var(--muted)' };
const vsShort = (w, prevVal) => state.compare && prevVal != null ? `<span class="vs" title="Previous period: ${rangeTxt(w.ps, w.pe)}">vs ${prevVal}</span>` : '';
function changeWords(cur, prev, n) {
  if (!state.compare || !prev) return '';
  const r = cur / prev;
  if (r >= 2) return `, ${r >= 10 ? Math.round(r) : r.toFixed(1)}× the ${n} days before`;
  if (r > 1.05) return `, up ${Math.round((r - 1) * 100)}% on the ${n} days before`;
  if (r < 0.95) return `, down ${Math.round((1 - r) * 100)}% on the ${n} days before`;
  return ', about the same as the period before';
}
function ratioTxt(cur, prev) {
  if (!prev) return cur ? 'New' : '—';
  const r = cur / prev;
  return r >= 9.5 ? '×' + Math.round(r) : r >= 1.95 ? '×' + r.toFixed(1) : (r >= 1 ? '+' : '−') + Math.round(Math.abs(r - 1) * 100) + '%';
}
function firstSeenMarks(L, w) {
  const m = new Map();
  L.forEach(s => { if (s.firstImpr != null && s.firstImpr >= w.s && s.firstImpr <= w.e) m.set(s.firstImpr, [...(m.get(s.firstImpr) || []), s.name]); });
  return [...m.entries()].map(([d, names]) => ({ d, label: `First seen on Google: ${names.join(', ')}` }));
}

/* ---------- signals: five verdict tiles, each with a visual dropdown ---------- */
function signalList(ctx) {
  const { L, T, TP, qs, eng } = ctx, S = [];
  const r = TP.impr ? T.impr / TP.impr : null;
  S.push({ k: 'views', icon: 'eye', v: state.compare ? ratioTxt(T.impr, TP.impr) : fmt(T.impr), l: state.compare ? 'Google views vs before' : 'Google views',
    tone: !state.compare || r == null ? 'info' : r >= 1.1 ? 'good' : r <= 0.9 ? 'bad' : 'mute' });
  const b = buckets(qs), bt = b.reduce((a, x) => a + x.impr, 0);
  if (bt) { const deep = b[4].impr / bt; S.push({ k: 'rank', icon: 'ladder', v: pct(deep), l: 'Keyword views · avg rank >50', tone: deep > .5 ? 'warn' : deep > .25 ? 'mute' : 'good' }); }
  if (eng.length) S.push({ k: 'engine', icon: 'globe', v: eng[0].name, l: 'Top search engine', tone: eng[0].name === 'Google' ? 'good' : 'info' });
  if (T.sessAll) { const ds = T.direct / T.sessAll; S.push({ k: 'bots', icon: 'bot', v: pct(ds), l: 'Direct share', tone: 'info' }); }
  const u = fixItems(L).filter(a => a.sev === 'bad').length;
  S.push({ k: 'fixes', icon: 'alert', v: String(u), l: u === 1 ? 'Urgent fix' : 'Urgent fixes', tone: u ? 'bad' : 'good' });
  return S;
}
function signalsHTML(ctx) {
  const S = signalList(ctx), open = S.find(s => s.k === state.sig), idx = open ? S.indexOf(open) : -1;
  return `<section class="signals" id="signals" aria-label="Key signals" style="--n:${S.length}">
    ${S.map(s => `<button type="button" class="sig" data-sig="${s.k}" aria-expanded="${state.sig === s.k}" ${state.sig === s.k ? 'aria-controls="sigDetail"' : ''} style="--c:${TONE[s.tone]}"><span class="sv">${esc(s.v)}</span><span class="sl">${icon(s.icon, 12)}${s.l}</span><span class="chev"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg></span></button>`).join('')}
    ${open ? `<div class="sig-detail" id="sigDetail" role="region" aria-label="${esc(open.l)}" style="--c:${TONE[open.tone]};--px:${((idx + .5) / S.length * 100).toFixed(2)}%">${sigDetail(open.k, ctx)}</div>` : ''}
  </section>`;
}
const hbar = (label, val, max, color, right) => `<div class="hb"><span class="hl">${label}</span><span class="ht"><span style="width:${max && val ? Math.max(2, val / max * 100) : 0}%;background:${color}"></span></span><span class="hv">${right ?? fmt(val)}</span></div>`;
const sdRow = (attr, left, right, dot) => `<button type="button" class="sd-row" ${attr}>${dot ? `<span class="dot" style="--c:${dot}"></span>` : ''}<span class="sn">${left}</span><span class="rv">${right}</span></button>`;
const shortRange = (s, e) => `${dm(s)}–${dm(e)}`;
function sigDetail(k, ctx) {
  const { L, w, T, TP, qs, eng } = ctx;
  if (k === 'views') {
    const V = L.map(s => siteView(s, w)), gains = V.map(v => ({ v, g: v.a.impr - v.p.impr })).filter(x => x.g > 0).sort((a, b) => b.g - a.g);
    const gross = gains.reduce((a, x) => a + x.g, 0), newGain = gains.filter(x => x.v.trend.k === 'new').reduce((a, x) => a + x.g, 0), max = Math.max(1, T.impr, TP.impr);
    const main = state.compare ? hbar(`<b>Before</b><small>${shortRange(w.ps, w.pe)}</small>`, TP.impr, max, 'var(--line2)') + hbar(`<b>Now</b><small>${shortRange(w.s, w.e)}</small>`, T.impr, max, 'var(--gsc)')
      : [...V].sort((a, b) => b.a.impr - a.a.impr).slice(0, 4).map(v => hbar(esc(v.site.name), v.a.impr, Math.max(1, ...V.map(x => x.a.impr)), 'var(--gsc)')).join('');
    return `<div class="sd-main">${main}</div><div class="sd-side"><div class="sd-h">Biggest gains</div>${gains.slice(0, 3).map(x => sdRow(`data-site="${x.v.site.slug}"`, esc(x.v.site.name), `<b class="up-a">+${fmt(x.g)}</b>`)).join('') || '<div class="empty">No site grew.</div>'}
      ${gross > 0 && newGain / gross > .5 ? `<div class="sd-note"><b>${pct(newGain / gross)}</b> of the growth is from sites new to Google</div>` : ''}<button type="button" class="more" data-go="sites">All sites ›</button></div>`;
  }
  if (k === 'rank') {
    const b = buckets(qs), bt = b.reduce((a, x) => a + x.impr, 0), near = qs.filter(q => q.pos >= 7.5 && q.pos <= 20.5).length;
    return `<div class="sd-main"><div class="bseg" role="img" aria-label="${b.map(x => `${x.l} ${pct(x.impr / bt)}`).join(', ')}">${b.map(x => x.impr ? `<span style="flex:${x.impr};background:${x.c}" title="${x.l}: ${fmt(x.impr)} views"></span>` : '').join('')}</div>
      <div class="blg">${b.map(x => `<div><i style="background:${x.c}"></i>${x.l}<b>${pct(x.impr / bt, x.impr && x.impr / bt < .01 ? 1 : 0)}</b></div>`).join('')}</div></div>
      <div class="sd-side"><div class="sd-h">Close to page 1</div><div class="sd-big">${fmt(near)}</div><div class="sd-note">search terms at positions 8–20</div><button type="button" class="more" data-go="searches">Search terms ›</button></div>`;
  }
  if (k === 'engine') {
    const emax = Math.max(1, ...eng.map(e => e.n)), etot = eng.reduce((a, e) => a + e.n, 0), g = eng.find(e => e.name === 'Google');
    return `<div class="sd-main">${eng.slice(0, 5).map(e => hbar(esc(e.name), e.n, emax, ENG_COL[e.name] || 'var(--other)', `${fmt(e.n)} <span class="dim">${pct(e.n / etot)}</span>`)).join('')}</div>
      <div class="sd-side"><div class="sd-h">Google, two ways</div><div class="sd-pair"><div><b>${fmt(T.clicks)}</b><span>clicks in Search Console</span></div><div><b>${fmt(g ? g.n : 0)}</b><span>visits in GA4</span></div></div><div class="sd-note">Search Console never sees Bing, DuckDuckGo or Yahoo.</div><button type="button" class="more" data-go="visits">Visits ›</button></div>`;
  }
  if (k === 'bots') {
    const other = Math.max(0, T.sessAll - T.direct - T.org), geo = geoAgg(L, w.s, w.e).slice(0, 4), gt = geoAgg(L, w.s, w.e).reduce((a, x) => a + x.n, 0);
    return `<div class="sd-main">${hbar('Direct', T.direct, T.sessAll, 'var(--direct)', `${fmt(T.direct)} <span class="dim">${pct(T.direct / T.sessAll)}</span>`)}${hbar('Search engines', T.org, T.sessAll, 'var(--ga4)', `${fmt(T.org)} <span class="dim">${pct(T.org / T.sessAll)}</span>`)}${hbar('Everything else', other, T.sessAll, 'var(--other)', `${fmt(other)} <span class="dim">${pct(other / T.sessAll)}</span>`)}
      <div class="sd-geo">${geo.map(g => `<span class="${SGCN.has(g.name) ? 'warnc' : ''}"><span class="cc" title="${esc(g.name)}" aria-label="${esc(g.name)}">${countryFlag(g.iso)}</span>${pct(g.n / gt)}</span>`).join('')}</div></div>
      <div class="sd-side"><div class="sd-h">Engaged visits</div><div class="sd-pair"><div><b>${T.org ? pct(T.engOrg / T.org) : '—'}</b><span>from search</span></div><div><b>${T.direct ? pct(T.engDir / T.direct) : '—'}</b><span>Direct</span></div></div>
      <button type="button" class="btn" data-traffic="${state.traffic === 'nodirect' ? 'all' : 'nodirect'}">${state.traffic === 'nodirect' ? 'Show Direct again' : 'Hide Direct visits'}</button></div>`;
  }
  const F = fixItems(L), n = s => F.filter(a => a.sev === s).length;
  return `<div class="sd-main">${F.filter(a => a.sev !== 'info').slice(0, 5).map(a => sdRow(`data-go="${a.tab}"`, a.t.replace(/<[^>]+>/g, ''), a.sites ? `<span class="dim">${a.sites.slice(0, 2).map(s => esc(s.name)).join(', ')}${a.sites.length > 2 ? ` +${a.sites.length - 2}` : ''}</span>` : '', a.sev === 'bad' ? 'var(--bad)' : 'var(--warn)')).join('')}</div>
    <div class="sd-side"><div class="sd-pair"><div><b class="dn-a">${n('bad')}</b><span>urgent</span></div><div><b style="color:var(--warn)">${n('warn')}</b><span>to check</span></div><div><b style="color:var(--info)">${n('info')}</b><span>notes</span></div></div><button type="button" class="more" data-go="connections">All fixes ›</button></div>`;
}

/* ---------- KPI cards ---------- */
function kcard(o) {
  return `<div class="kcard" style="--c:${o.c}">${o.src ? `<span class="src ${o.srcCls}">${o.src}</span>` : ''}
    <div class="kl">${icon(o.icon)}${o.label}${o.tip ? info(o.tip) : ''}</div>
    <div class="kv">${o.value}</div>${o.delta ? `<div class="kd">${o.delta}</div>` : ''}${o.extra || ''}
    ${o.spark ? `<div class="kchart">${o.spark}</div>` : ''}${o.legend || ''}</div>`;
}
const legendHTML = (color, marks) => `<div class="klegend"><span><i style="--c:${color}"></i>Daily</span>${state.compare ? '<span><i class="dash"></i>Before</span>' : ''}${marks ? '<span><i class="dm"></i>New site</span>' : ''}</div>`;
function kpiHTML(ctx) {
  const { L, w, T, TP, S, SP, qs, qsPrev } = ctx, R = rangeTxt(w.s, w.e);
  const b = buckets(qs), bt = b.reduce((a, x) => a + x.impr, 0), p1 = bt ? (b[0].impr + b[1].impr) / bt : 0;
  const nd = state.traffic === 'nodirect', ctr = oneIn(T.clicks, T.impr), marks = firstSeenMarks(L, w);
  const heroA = kcard({ c: 'var(--gsc)', src: 'GSC', srcCls: 's-gsc', icon: 'eye', label: 'Seen on Google', tip: 'Times a page from these sites appeared in Google results, once per search.',
    value: fmt(T.impr), delta: `${delta(T.impr, TP.impr)}${vsShort(w, fmt(TP.impr))}`,
    extra: `<div class="inset"><div><div class="il">Click rate</div><div class="iv">${ctr ? '1 in ' + fmt(ctr) : 'No clicks'}</div></div></div>`,
    spark: timeChart({ s: w.s, e: w.e, h: 230, series: [{ label: 'Views', color: 'var(--gsc)', vals: S.impr, prev: SP.impr, kind: 'area' }], marks, aria: `Daily Google views, ${R}` }), legend: legendHTML('var(--gsc)', marks.length) });
  const heroB = kcard({ c: 'var(--pos)', src: 'GSC', srcCls: 's-gsc', icon: 'ladder', label: 'Average Google rank', tip: 'Search Console average rank, weighted by Google views (impressions). Lower is better; #1 is first. It combines the selected sites and searches, so a change in search mix can move this average even without a ranking change for the same keyword.',
    value: rankText(T.pos), delta: `${posDelta(T.pos, TP.pos)}${vsShort(w, TP.pos ? rankText(TP.pos) : null)}`,
    extra: `<div class="rank-note">Lower is better · #1 is first<br><span>Average across searches, not a fixed site rank.</span></div><div class="inset">${ring(p1, 'var(--gold)')}<div><div class="il">Views from keywords averaging top 10</div><div class="iv">${bt ? pct(p1, p1 && p1 < .01 ? 1 : 0) : '—'}</div></div></div><div class="rank-coverage">Reported keywords cover ${T.impr ? pct(bt / T.impr) : '—'} of Google views. The percentage above uses only those keywords.</div>`,
    spark: timeChart({ s: w.s, e: w.e, h: 230, invert: true, series: [{ label: 'Avg rank', color: 'var(--pos)', vals: S.pos, prev: SP.pos, kind: 'line', fmt: v => `${rankText(v)} · lower is better` }], aria: `Daily average Google position, ${R}` }), legend: legendHTML('var(--pos)', 0) });
  const withClicks = L.filter(s => agg(s, w.s, w.e).clicks > 0).length;
  const top3 = ctx.eng.slice(0, 3).map(e => `<span class="eg"><i style="background:${ENG_COL[e.name] || 'var(--muted)'}"></i>${esc(e.name)} <b>${fmt(e.n)}</b></span>`).join('');
  const r3 = [
    kcard({ c: 'var(--gsc)', src: 'GSC', srcCls: 's-gsc', icon: 'click', label: 'Google clicks', tip: 'Clicks from Google results, as counted by Search Console.', value: fmt(T.clicks), delta: `${delta(T.clicks, TP.clicks)}${vsShort(w, fmt(TP.clicks))}`,
      extra: `<div class="kx">${withClicks} of ${L.length} ${plural(L.length, 'site')} got a click</div>`, spark: sparkBars(S.clicks, 'var(--gsc)', w.s, 'Google clicks') }),
    kcard({ c: 'var(--ga4)', src: 'GA4', srcCls: 's-ga4', icon: 'search', label: 'Search visits', tip: 'Visits GA4 credits to any search engine. Search Console only sees Google; sessions and clicks use different definitions.', value: fmt(T.org), delta: `${delta(T.org, TP.org)}${vsShort(w, fmt(TP.org))}`,
      extra: `<div class="kx eng3">${top3 || 'None'}</div>`, spark: sparkBars(S.org, 'var(--ga4)', w.s, 'Search visits') }),
    kcard({ c: 'var(--partner)', src: 'GA4', srcCls: 's-ga4', icon: 'out', label: 'Partner clicks', tip: 'Configured affiliate_click, outbound_click and mirai_click events. Click intent is not a purchase.', value: fmt(T.aff), delta: `${delta(T.aff, TP.aff)}${vsShort(w, fmt(TP.aff))}`,
      extra: `<div class="kx">${T.aff && T.org ? `<b>${Math.round(T.aff / T.org * 100)}</b> per 100 search visits` : T.aff ? 'from all traffic' : 'none recorded'}</div>`, spark: sparkBars(S.aff, 'var(--good)', w.s, 'Partner clicks') }),
  ].join('');
  const terms = qs.filter(q => q.i > 0).length, termsP = qsPrev.filter(q => q.i > 0).length;
  const prevKeys = new Set(qsPrev.filter(q => q.i > 0).map(q => q.site.idx + ':' + q.key)), fresh = state.compare ? qs.filter(q => q.i > 0 && !prevKeys.has(q.site.idx + ':' + q.key)).length : 0;
  const posts = L.reduce((a, s) => { const x = wpInfo(s, w.s, w.e); return { added: a.added + Math.max(0, x.added || 0), removed: a.removed + Math.max(0, -(x.added || 0)), total: a.total + (x.total || 0), last: Math.max(a.last, x.last ?? -1e9) }; }, { added: 0, removed: 0, total: 0, last: -1e9 });
  const drVals = L.map(s => [s, s.ah.at(-1)]).filter(([s, a]) => a && a[1] != null && s.name !== 'slots.us.com').map(([, a]) => a[1]).sort((a, b) => a - b);
  const drMed = drVals.length ? drVals[Math.floor(drVals.length / 2)] : null, bl = L.reduce((a, s) => { const x = s.ah.at(-1); return a + (x ? x[2] : 0); }, 0);
  const lastSnap = L.map(s => s.ah.at(-1)?.[0]).filter(Boolean).sort().at(-1);
  const r5 = [
    kcard({ c: 'var(--ga4)', src: 'GA4', srcCls: 's-ga4', icon: 'users', label: nd ? 'Visits, no Direct' : 'All visits', tip: nd ? 'Every GA4 visit except Direct traffic.' : 'Every GA4 visit, Direct included.', value: fmt(T.sess), delta: delta(T.sess, TP.sess),
      extra: `<div class="kx">${nd ? `${fmt(T.direct)} Direct hidden` : `${pct(T.sessAll ? T.org / T.sessAll : 0, 1)} from search`}</div>`, spark: sparkBars(S.sess, 'var(--ga4)', w.s, 'Visits') }),
    kcard({ c: 'var(--good)', src: 'GA4', srcCls: 's-ga4', icon: 'pulse', label: 'Engaged', tip: 'GA4 counts a visit as engaged when it lasts over 10 seconds, views 2+ pages or converts.', value: T.sess ? pct(T.eng / T.sess) : '—',
      extra: `<div class="kx">search <b>${T.org ? pct(T.engOrg / T.org) : '—'}</b> · direct <b>${T.direct ? pct(T.engDir / T.direct) : '—'}</b></div>` }),
    kcard({ c: 'var(--gsc)', src: 'GSC', srcCls: 's-gsc', icon: 'tag', label: 'Search terms', tip: 'Distinct search terms that showed these sites at least once, as Google reports them by name.', value: fmt(terms), delta: delta(terms, termsP),
      extra: `<div class="kx">${state.compare ? `<b>${fmt(fresh)}</b> new` : 'with 1+ view'}</div>` }),
    kcard({ c: 'var(--v-main)', src: 'GA4', srcCls: 's-ga4', icon: 'out', label: 'Analytics purchases', tip: 'GA4 ecommerce purchase events across all traffic. Not reconciled Shopify paid orders. See Traffic to sales for source attribution.', value: commerceTotals(L, w).known ? fmt(commerceTotals(L, w).purchases) : '—', extra: '<div class="kx">All channels · GA4 attribution</div>' }),
    kcard({ c: 'var(--ahr)', src: 'Ahrefs', srcCls: 's-ahr', icon: 'shield', label: 'Authority', tip: 'Current median Ahrefs Domain Rating (0–100), independent of the Google date filter. Available sites only; missing snapshots are excluded.', value: drMed == null ? '—' : `DR ${drMed.toFixed(1)}`,
      extra: `<div class="kx">${drVals.length ? `${fmt(bl)} backlinks · snapshot ${dm(lastSnap)}` : 'no snapshot yet'}${ahrefsOut() && lastSnap && isoOf(w.e) > lastSnap ? `<br><span class="chip bad">frozen ${dm(lastSnap)}</span>` : ''}</div>` }),
  ].join('');
  return `<section class="krow hero" aria-label="Google visibility">${heroA}${heroB}</section><section class="krow r3" aria-label="Clicks and visits">${r3}</section><section class="krow r5" aria-label="Quality and content">${r5}</section>`;
}

/* ---------- insight arena ---------- */
function acard(o) {
  return `<div class="acard" style="--c:${o.c}"><div class="ah"><span class="it">${icon(o.icon, 18)}</span><div><b>${o.title}</b><span>${o.sub}</span></div></div>${o.body}<button type="button" class="more" data-go="${o.go}">${o.more} ›</button></div>`;
}
function arenaHTML(ctx) {
  const { L, w, qs, qsPrev } = ctx, V = L.map(s => siteView(s, w));
  const item = (attr, t, s, r) => `<button type="button" class="aitem" ${attr}><span class="t">${t}</span><span class="s">${s}</span><span class="r">${r}</span></button>`;
  const risers = V.filter(v => v.a.impr > v.p.impr).sort((a, b) => (b.a.impr - b.p.impr) - (a.a.impr - a.p.impr)).slice(0, 3);
  const fall = V.filter(v => v.p.impr > v.a.impr).sort((a, b) => (a.a.impr - a.p.impr) - (b.a.impr - b.p.impr))[0];
  const siteItem = (v, r) => item(`data-site="${v.site.slug}"`, esc(v.site.name), `${v.a.pos ? `avg rank ${rankText(v.a.pos)} · ` : ''}${fmt(v.a.impr)} views`, r);
  const rising = acard({ c: 'var(--good)', icon: 'rise', title: 'Rising on Google', sub: 'change in views', go: 'sites', more: 'All sites',
    body: `<div class="alist">${state.compare ? (risers.map(v => siteItem(v, `<span class="up-a">+${fmt(v.a.impr - v.p.impr)}</span>`)).join('') + (fall ? siteItem(fall, `<span class="dn-a">−${fmt(fall.p.impr - fall.a.impr)}</span>`) : '')) || '<div class="empty">No change in this period.</div>' : '<div class="empty">Turn on Compare to see movers.</div>'}</div>` });
  const near = qs.filter(q => q.pos >= 7.5 && q.pos <= 20.5).sort((a, b) => b.i - a.i).slice(0, 3);
  const close = acard({ c: 'var(--lime)', icon: 'target', title: 'Close to page 1', sub: 'positions 8–20', go: 'searches', more: 'All terms',
    body: `<div class="alist">${near.map(q => item(`data-site="${q.site.slug}"`, esc(qsplit(q.text).q), `${esc(q.site.name)} · ${fmt(q.i)} views`, rankTag(q.pos))).join('') || '<div class="empty">None in this period.</div>'}</div>` });
  const prevKeys = new Set(qsPrev.filter(q => q.i > 0).map(q => q.site.idx + ':' + q.key));
  const fresh = state.compare ? qs.filter(q => q.i > 0 && !prevKeys.has(q.site.idx + ':' + q.key)).sort((a, b) => b.i - a.i) : [];
  const newT = acard({ c: 'var(--gsc)', icon: 'tag', title: 'New search terms', sub: state.compare ? `${fmt(fresh.length)} found us this period` : 'turn on Compare', go: 'searches', more: 'All terms',
    body: `<div class="alist">${fresh.slice(0, 3).map(q => item(`data-site="${q.site.slug}"`, esc(qsplit(q.text).q), `${esc(q.site.name)} · ${fmt(q.i)} views`, rankTag(q.pos))).join('') || '<div class="empty">No new terms.</div>'}</div>` });
  const links = linkAgg(L, w.s, w.e);
  const partners = acard({ c: 'var(--partner)', icon: 'out', title: 'Partner clicks go to', sub: `${fmt(links.reduce((a, l) => a + l.n, 0))} tracked clicks`, go: 'visits', more: 'All visits',
    body: `<div class="alist">${links.slice(0, 3).map(l => item(`data-go="visits"`, esc(l.host), [...l.sites].map(x => esc(siteBy(x).name)).join(', '), `<b>${fmt(l.n)}</b>`)).join('') || '<div class="empty">No tracked outbound links in this period.</div>'}</div>` });
  return `<section class="arena" aria-label="Highlights">${rising}${close}${newT}${partners}</section>`;
}
