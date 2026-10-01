/* ---------- connection health ----------
   Two readings of the same question. "Stored" is what the last fetch wrote to
   fetch_log for every site and source; it is always "now" (the 28 days to the
   newest data), not the chosen period. "Live" runs the server's connection
   checker (api/connections) on demand, with the production credentials. */
const W0 = { s: END - 27, e: END, n: 28, ps: END - 55, pe: END - 28 };
const SRCDEF = [
  { k: 'gsc', name: 'Search Console', logo: 'G', c: 'var(--gsc)', cls: 's-gsc', what: 'Google views, clicks and position' },
  { k: 'ga4', name: 'Google Analytics 4', logo: 'GA', c: 'var(--ga4)', cls: 's-ga4', what: 'Visits, engines, countries, partner clicks' },
  { k: 'ahrefs', name: 'Ahrefs', logo: 'A', c: 'var(--ahr)', cls: 's-ahr', what: 'Domain rating and backlinks' },
];
const shortMsg = m => (m ? String(m).replace(/\s+/g, ' ').slice(0, 160) : '');
const ahrefsFetch = () => ACTIVE.map(s => s.fetch.ahrefs).find(Boolean) || null;
const ahrefsOut = () => { const f = ahrefsFetch(); return !!(f && f.status === 'no_access' && /unit/i.test(f.message || '')); };
const lastAhrefs = () => SITES.map(s => (s.ah.length ? s.ah[s.ah.length - 1][0] : null)).filter(Boolean).sort().pop() || null;
const credOfSite = (s, k) => (D.credentials || []).find(c => (k === 'gsc' ? c.gscSites : c.ga4Sites).includes(s.slug)) || null;

/* ----- live check (api/connections) ----- */
let LIVE = { state: 'idle', at: null, sites: null, error: null };
const liveFor = s => (LIVE.sites ? LIVE.sites.find(x => x.slug === s.slug) : null);
const LIVE_MAP = {
  connected: ['ok', 'Connected'], enabled: ['ok', 'Events arriving'], connected_no_data: ['stale', 'Connected, no data'],
  not_detected: ['stale', 'No partner events'], property_mismatch: ['stale', 'Wrong property'], maintenance: ['stale', 'Maintenance page'],
  not_installed: ['unset', 'Plugin not installed'], no_key_on_site: ['stale', 'Plugin has no key'], no_key_stored: ['stale', 'Key not stored'],
  access_denied: ['denied', 'Access denied'], not_found: ['denied', 'Not found'], key_rejected: ['denied', 'Key rejected'], insecure: ['denied', 'Not HTTPS'],
  not_configured: ['unset', 'Not set up'], timed_out: ['stale', 'Timed out'], invalid_response: ['denied', 'Bad response'], error: ['denied', 'Error'],
};
const liveState = r => { if (!r) return { st: 'unset', label: '—' }; const [st, label] = LIVE_MAP[r.status] || ['denied', r.status.replace(/_/g, ' ')]; return { st, label, msg: r.message || '', suggestion: r.suggestion || null }; };
async function runLiveCheck() {
  if (LIVE.state === 'running') return;
  LIVE = { ...LIVE, state: 'running', error: null };
  refreshLive();
  try {
    const res = await fetch(`${BASE}/api/connections`, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.message || `The server answered ${res.status}.`);
    LIVE = { state: 'done', at: body.checkedAt, sites: body.sites || [], googleConfigured: body.googleConfigured, error: null };
  } catch (err) {
    LIVE = { ...LIVE, state: 'error', error: err.message || 'The live check failed.' };
  }
  refreshLive();
}
/** Re-render whatever shows live results: the Connections tab and the status menu. */
function refreshLive() {
  syncChrome();
  if (state.tab === 'connections') renderTab();
  if (openSlug && $('.drawer')) { const y = $('.drawer').scrollTop; openSite(openSlug); $('.drawer').scrollTop = y; }
}
function liveNote(s, k) {
  const r = liveFor(s); if (!r) return '';
  const src = k === 'gsc' ? r.gsc : k === 'ga4' ? r.ga4 : k === 'wordpress' ? r.wordpress : null; if (!src) return '';
  const x = liveState(src);
  return `<span class="live ${x.st === 'ok' ? '' : 'w'}" title="${esc(x.msg)}">Live: ${esc(x.label)}${x.suggestion ? ` → ${esc(x.suggestion)}` : ''}</span>`;
}

/* ----- stored status (fetch_log) ----- */
function cellState(s, k) {
  if (k === 'gsc' && !s.gsc_property) return { st: 'unset', label: 'Not set up', note: 'No Search Console property' };
  if (k === 'ga4' && !s.ga4) return { st: 'unset', label: 'Not set up', note: 'No GA4 property' };
  const f = s.fetch[k];
  if (!f) return { st: 'unset', label: 'Not fetched yet', note: '' };
  if (k === 'ahrefs' && f.status === 'no_access') return ahrefsOut() ? { st: 'denied', label: 'Out of API units', note: `Nothing new since ${dm(lastAhrefs())}`, msg: f.message } : { st: 'denied', label: 'Refused', note: shortMsg(f.message), msg: f.message };
  if (f.status === 'no_access') return { st: 'denied', label: 'Access refused', note: shortMsg(f.message), msg: f.message };
  if (k === 'ahrefs' && f.status === 'not_configured' && D.ahrefs.configured) return { st: 'stale', label: 'Refresh needed', note: 'Key is configured now; the last fetch ran before setup.' };
  if (f.status === 'not_configured') return { st: 'unset', label: 'Not set up', note: shortMsg(f.message), msg: f.message };
  if (f.status !== 'ok') return { st: 'denied', label: 'Error', note: shortMsg(f.message), msg: f.message };
  if (k === 'ga4' && s.lastSess != null && END - s.lastSess > 7) return { st: 'stale', label: 'Silent', note: `No visits since ${dm(s.lastSess)}` };
  if (k === 'gsc' && s.gsc_property.startsWith('http://') && agg(s, W0.s, W0.e).impr === 0) return { st: 'stale', label: 'Connected, empty', note: 'http:// property reads zero' };
  if (k === 'wordpress') { const x = postsLost(s); if (x) return { st: 'stale', label: `Connected, ${x.to} posts`, note: `had ${x.from} until ${dm(x.on)}` }; }
  return { st: 'ok', label: 'Connected', note: f.through ? `to ${dm(f.through)}` : '' };
}
const ICON = { ok: '✓', stale: '!', denied: '✕', unset: '–', paused: '‖' };
function cellHTML(s, k) {
  const c = cellState(s, k);
  return `<span class="cell" ${c.msg ? `title="${esc(c.msg)}"` : ''}><span class="st ${c.st}"><i aria-hidden="true">${ICON[c.st]}</i>${esc(c.label)}</span>${c.note ? `<small>${esc(c.note)}</small>` : ''}${liveNote(s, k)}</span>`;
}

/* ----- what to fix, most severe first ----- */
function fixItems(list) {
  const A = [], V = list.map(s => siteView(s, W0));
  const has = k => V.filter(v => v.flags.some(f => f.k === k)).map(v => v.site);
  const names = arr => arr.map(s => esc(s.name)).join(', ');
  const ahDenied = list.filter(s => s.fetch.ahrefs && s.fetch.ahrefs.status === 'no_access');
  if (ahDenied.length) A.push(ahrefsOut()
    ? { sev: 'bad', src: 'ahr', t: 'Ahrefs has run out of API units', d: `The key works, but the plan’s API units are used up, so authority numbers are frozen at ${dm(lastAhrefs())}.`, f: 'Top up units on the Ahrefs plan. Fetching Ahrefs weekly instead of daily cuts use about seven-fold; ratings barely move day to day.', tab: 'authority' }
    : { sev: 'bad', src: 'ahr', t: 'Ahrefs refused the API key', d: shortMsg(ahDenied[0].fetch.ahrefs.message), f: 'Put a key with API access into <code>MIRAI_SEO_AHREFS_API_KEY</code> in the server env file.', tab: 'authority' });
  for (const [k, label] of [['gsc', 'Search Console'], ['ga4', 'Analytics']]) {
    const denied = list.filter(s => s.fetch[k] && s.fetch[k].status === 'no_access');
    if (denied.length) {
      const cred = credOfSite(denied[0], k);
      A.push({ sev: 'bad', src: k === 'gsc' ? 'gsc' : 'ga4', t: `${label} refused access for ${denied.length} ${plural(denied.length, 'site')}`, sites: denied, d: names(denied),
        f: `Grant the ${cred ? `<code>${esc(cred.name)}</code> credential (<code>${esc(cred.envVar)}</code>)` : 'credential in use'} access to these properties, or route them to one that has it (<code>${k}_auth</code> in <code>config/sites.yaml</code>).`, tab: 'connections' });
    }
    const unset = list.filter(s => s.fetch[k] && s.fetch[k].status === 'not_configured');
    if (unset.length) A.push({ sev: 'warn', src: k, t: `${label} has no credential for ${unset.length} ${plural(unset.length, 'site')}`, sites: unset, d: shortMsg(unset[0].fetch[k].message), f: 'Set the credential’s env var in the server env file, then restart the service.', tab: 'connections' });
  }
  const hp = has('httpprop');
  if (hp.length) A.push({ sev: 'bad', src: 'gsc', t: `${hp.length === 1 ? 'One site shows' : hp.length + ' sites show'} zero Google views`, sites: hp,
    d: hp.map(s => { const r = liveFor(s); const sug = r && r.gsc && r.gsc.suggestion; return `<b>${esc(s.name)}</b> reads <code>${esc(s.gsc_property)}</code>, which is empty${sug ? `; the live check suggests <code>${esc(sug)}</code>` : ''}`; }).join('. ') + '.',
    f: 'Verify the https:// property, add the service account to it, and change <code>gsc_property</code> in <code>config/sites.yaml</code>.', tab: 'connections' });
  const lost = list.filter(s => postsLost(s));
  if (lost.length) A.push({ sev: 'bad', src: 'wp', t: `${lost.length === 1 ? esc(lost[0].name) + ' lost its posts' : lost.length + ' sites lost their posts'}`, sites: lost,
    d: lost.map(s => { const x = postsLost(s); return `WordPress reports ${x.to} posts since ${dm(x.on)} (it had ${x.from})${s.lastSess != null && END - s.lastSess > 7 ? `; GA4 also went silent on ${dm(s.lastSess)}` : ''}`; }).join('. ') + '. The site may be down, reset or blocking its API.',
    f: 'Open the site and its /wp-json endpoint. If the posts are gone, restore them from the host’s backup.', tab: 'authority' });
  const st = has('ga4stale');
  if (st.length) A.push({ sev: 'bad', src: 'ga4', t: `Analytics stopped recording on ${st.length === 1 ? 'one site' : st.length + ' sites'}`, sites: st, d: st.map(s => `${esc(s.name)}: last visit ${dm(s.lastSess)}`).join(' · '), f: 'Check the GA4 tag is still in the site header; plugin or theme updates often remove it.', tab: 'connections' });
  const bots = has('bots');
  if (bots.length) { const tot = V.filter(v => bots.includes(v.site)).reduce((a, v) => a + v.a.direct, 0); A.push({ sev: 'warn', src: 'ga4', t: 'Direct visits have limited attribution', sites: bots, d: `${fmt(tot)} Direct visits on ${names(bots)} in the last 28 days, with no recorded referrer.`, f: 'Switch Visits to “Without Direct” above, and review engagement before drawing conclusions about traffic quality.', tab: 'visits' }); }
  const drs = has('drshared');
  if (drs.length) A.push({ sev: 'warn', src: 'ahr', t: `${names(drs)} shows the rating of its parent domain`, sites: drs, d: 'Ahrefs rates the registrable domain (for slots.us.com that is us.com), not this site.', f: 'Treat its authority as unknown, or query Ahrefs in subdomain mode for it.', tab: 'authority' });
  const quiet = list.filter(s => { const w = wpAt(s, END); return w && w[2] >= 0 && END - w[2] > 21 && !postsLost(s); });
  if (quiet.length) { const common = quiet.every(s => wpAt(s, END)[2] === wpAt(quiet[0], END)[2]); A.push({ sev: 'info', src: 'wp', t: `${quiet.length} ${plural(quiet.length, 'site')} stopped publishing`, sites: quiet, d: common ? `No new posts since ${dm(wpAt(quiet[0], END)[2])}.` : quiet.map(s => `${esc(s.name)}: ${dm(wpAt(s, END)[2])}`).join(' · '), f: 'Schedule new articles for these sites in the Operations Sheet.', tab: 'authority' }); }
  const nog = has('nogsc');
  if (nog.length) A.push({ sev: 'info', src: 'gsc', t: `${names(nog)} ${nog.length === 1 ? 'is' : 'are'} not in Search Console`, sites: nog, d: 'Only visits are measured.', f: 'Create and verify the property, or remove the site from the registry.', tab: 'connections' });
  const smErr = list.filter(s => s.sm && s.sm.err > 0);
  if (smErr.length) A.push({ sev: 'info', src: 'gsc', t: `Sitemap errors on ${names(smErr)}`, sites: smErr, d: smErr.map(s => `${s.sm.err} ${plural(s.sm.err, 'error')}, ${s.sm.warn} ${plural(s.sm.warn, 'warning')}`).join(' · '), f: 'Open the sitemap report in Search Console and fix the listed URLs.', tab: 'authority' });
  const noAff = V.filter(v => v.site.vertical === 'Satellites' && v.a.sessAll > 0 && !v.a.aff && !v.p.aff).map(v => v.site);
  if (noAff.length) A.push({ sev: 'info', src: 'ga4', t: `${noAff.length} ${plural(noAff.length, 'site')} have no tracked outbound clicks`, sites: noAff, d: 'No configured outbound event was observed in 56 days. Missing events do not establish zero referrals or sales.', f: 'Check mirai_click, affiliate_click or outbound_click tracking on the satellites.', tab: 'visits' });
  const order = { bad: 0, warn: 1, info: 2 };
  return A.sort((a, b) => order[a.sev] - order[b.sev]);
}
function fxHTML(a) {
  return `<details class="fx sev-${a.sev}"><summary><span class="bi" aria-hidden="true">${a.sev === 'info' ? 'i' : '!'}</span><span class="t">${a.t}</span><span class="cv" aria-hidden="true">&#9662;</span></summary><div class="fb"><div class="d">${a.d}</div>${a.f ? `<div class="f"><b>Fix:</b> ${a.f}</div>` : ''}</div></details>`;
}
function identities() {
  const card = (title, sub, uses, chip) => `<div class="idc"><div class="h"><b>${title}</b>${chip}</div><div class="e">${sub}</div><div class="u">${uses}</div></div>`;
  const cards = (D.credentials || []).map(c => card(
    c.kind === 'service_account' ? 'Google service account' : 'Google OAuth token',
    `${esc(c.envVar)}${c.kind === 'oauth_token' ? ' · stored user token' : ''}`,
    `<span class="dim">${esc(c.name)} ·</span> Search Console on ${c.gscSites.length} · GA4 on ${c.ga4Sites.length} ${plural(c.ga4Sites.length, 'site')}`,
    c.configured ? '<span class="chip good">Configured</span>' : '<span class="chip bad">Missing</span>'));
  const af = ahrefsFetch();
  const ahChip = !D.ahrefs.configured ? '<span class="chip bad">Missing</span>' : ahrefsOut() ? '<span class="chip bad">No units left</span>' : af && af.status === 'no_access' ? '<span class="chip bad">Refused</span>' : '<span class="chip good">Configured</span>';
  cards.push(card('Ahrefs API key', 'MIRAI_SEO_AHREFS_API_KEY', af ? `Last fetch: ${esc(shortMsg(af.message) || af.status)}` : 'Domain rating and backlinks', ahChip));
  return cards.join('');
}
