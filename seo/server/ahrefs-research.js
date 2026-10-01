/** Bounded, on-demand competitor research. No research runs on page load. */
import { createHash } from 'node:crypto';
import { apiRequest, limitsAndUsage, requireAllowance, BudgetExceeded, AhrefsUnavailable, nullableNumber, targetForSite } from './ahrefs.js';
export const KEYWORDS_PER_COMPETITOR = 30;
export const MAX_COMPETITORS = 3;
export const DISCOVERY_UNITS = 50;
// keyword + position + URL + volume(10) + difficulty(10) + branded = 24.
// Target verification needs only keyword + position + URL = 3.
export const GAP_UNITS_PER_COMPETITOR = KEYWORDS_PER_COMPETITOR * (24 + 3);
export const CACHE_DAYS = 7;
export const monthlyLimit = () => {
  const n = Number(process.env.MIRAI_SEO_AHREFS_RESEARCH_MONTHLY_UNITS ?? 10000);
  return Number.isSafeInteger(n) && n >= 0 ? n : 10000;
};
const numeric = nullableNumber;
export const safeUrl = value => {
  try { const u = new URL(value); return ['https:', 'http:'].includes(u.protocol) && !u.username && !u.password ? u.href : null; } catch { return null; }
};
export function domainName(value) {
  if (typeof value !== 'string' || value.length > 253 || !/^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}$/i.test(value)) return null;
  return value.toLowerCase();
}
export function validateResearch(input, cfg) {
  const site = cfg.sites.find(s => s.slug === input.site);
  const country = String(input.country || 'us').toLowerCase();
  if (!site || !targetForSite(site)) throw new Error('Select a configured site.');
  if (!/^[a-z]{2}$/.test(country) || new Intl.DisplayNames(['en'], { type: 'region' }).of(country.toUpperCase()) === country.toUpperCase()) throw new Error('Select a valid country.');
  const kind = input.kind || 'discover';
  if (!['discover', 'serp', 'gap'].includes(kind)) throw new Error('Unknown research action.');
  const competitors = [...new Set((Array.isArray(input.competitors) ? input.competitors : []).map(domainName))];
  const host = new URL(targetForSite(site)).hostname.replace(/^www\./, '');
  if (kind === 'gap' && (!competitors.length || competitors.length > MAX_COMPETITORS || competitors.some(c => !c || c.replace(/^www\./, '') === host))) throw new Error('Choose one to three competitor domains, excluding the target.');
  const seedKeywords = kind === 'serp' && Array.isArray(input.seedKeywords) ? [...new Set(input.seedKeywords.map(k => String(k).trim()))] : [];
  if (kind === 'serp' && (!seedKeywords.length || seedKeywords.length > 3 || seedKeywords.some(k => k.length < 2 || k.length > 80))) throw new Error('Enter one to three search terms, each 2–80 characters, to send to Ahrefs.');
  return { site, country, kind, seedKeywords, competitors: kind === 'gap' ? competitors.sort() : [] };
}
const keyFor = p => createHash('sha256').update(JSON.stringify([p.site.slug, targetForSite(p.site), p.country, p.kind, p.competitors, p.seedKeywords])).digest('hex');
export function budgetStatus(db, now = new Date()) {
  const month = now.toISOString().slice(0, 7), used = db.prepare('SELECT COALESCE(SUM(units),0) AS n FROM ahrefs_research_spend WHERE created_at LIKE ?').get(month + '%').n;
  return { limit: monthlyLimit(), used, remaining: Math.max(0, monthlyLimit() - used), month };
}
export function savedResearch(db, site, country, now = new Date()) {
  const rows = db.prepare('SELECT kind, created_at, payload FROM ahrefs_research_cache WHERE site=? ORDER BY created_at DESC').all(site);
  const result = { discover: null, serp: null, gap: null, budget: budgetStatus(db, now) };
  for (const row of rows) {
    const data = JSON.parse(row.payload);
    if (data.country === country && !result[row.kind]) result[row.kind] = { ...data, cached: true, stale: now - new Date(row.created_at) >= CACHE_DAYS * 864e5 };
  }
  return result;
}
function reserve(db, units, now) {
  return db.transaction(() => {
    if (budgetStatus(db, now).remaining < units) throw new BudgetExceeded(`The dashboard research budget cannot cover this run of up to ${units} units. Existing results remain available.`);
    return db.prepare('INSERT INTO ahrefs_research_spend(created_at,units) VALUES (?,?)').run(now.toISOString(), units).lastInsertRowid;
  }).immediate();
}
function keywordRows(body) {
  if (!Array.isArray(body.keywords)) throw new AhrefsUnavailable('Ahrefs returned an invalid keyword response. No gap conclusions were saved.');
  const seen = new Set();
  return body.keywords.map(row => {
    if (typeof row.keyword !== 'string' || !row.keyword.trim() || seen.has(row.keyword.toLowerCase())) throw new AhrefsUnavailable('Ahrefs returned ambiguous keyword rows. No gap conclusions were saved.');
    seen.add(row.keyword.toLowerCase());
    const position = numeric(row.best_position);
    if (position === null || position < 1 || position > 100) throw new AhrefsUnavailable('Ahrefs returned a keyword without a usable ranking. No gap conclusions were saved.');
    return { keyword: row.keyword, position, url: safeUrl(row.best_position_url), volume: numeric(row.volume), difficulty: numeric(row.keyword_difficulty) };
  });
}
export function gapRows(competitorRows, ownRows) {
  const own = new Map(ownRows.map(r => [r.keyword.toLowerCase(), r])), groups = new Map();
  for (const { domain, rows } of competitorRows) for (const row of rows) {
    const k = row.keyword.toLowerCase();
    if (!groups.has(k)) groups.set(k, { keyword: row.keyword, volume: row.volume, difficulty: row.difficulty, competitors: [] });
    groups.get(k).competitors.push({ domain, position: row.position, url: row.url });
  }
  return [...groups].flatMap(([k, row]) => {
    const target = own.get(k);
    if (target && target.position <= 10) return [];
    return [{ ...row, targetPosition: target?.position ?? null, targetUrl: target?.url ?? null,
      kind: target ? 'weak' : 'missing', action: target ? 'Improve existing page' : 'Check page coverage' }];
  }).sort((a, b) => b.competitors.length - a.competitors.length || (b.volume ?? -1) - (a.volume ?? -1) || (a.difficulty ?? 101) - (b.difficulty ?? 101));
}
// Wait for every in-flight response before releasing a budget reservation or
// reporting failure. Two parallel request phases stay within the portal timeout.
async function settledResults(tasks) {
  const results = await Promise.allSettled(tasks);
  const failed = results.find(r => r.status === 'rejected');
  if (failed) throw failed.reason;
  return results.map(r => r.value);
}
export async function runResearch(db, params, { now = new Date(), client = apiRequest, usage = limitsAndUsage } = {}) {
  const cacheKey = keyFor(params), cached = db.prepare('SELECT created_at,payload FROM ahrefs_research_cache WHERE cache_key=?').get(cacheKey);
  if (cached && now - new Date(cached.created_at) < CACHE_DAYS * 864e5) return { ...JSON.parse(cached.payload), cached: true };
  const maxUnits = params.kind === 'discover' ? DISCOVERY_UNITS : params.kind === 'serp' ? params.seedKeywords.length * 50 : params.competitors.length * GAP_UNITS_PER_COMPETITOR;
  const allowance = await usage();
  requireAllowance(allowance, maxUnits);
  const reservation = reserve(db, maxUnits, now);
  let charged = 0;
  const call = async (path, query, bound) => {
    // Reserve the bound before sending; a timeout or missing cost header stays
    // conservatively charged rather than allowing retries to exceed the budget.
    charged += bound;
    return client(path, { params: query, onCost: n => { if (n !== null) charged += n - bound; } });
  };
  try {
    const date = new Date(now.getTime() - 2 * 864e5).toISOString().slice(0, 10);
    const base = { country: params.country, date, mode: 'subdomains', protocol: 'both', output: 'json', timeout: 25 };
    const target = targetForSite(params.site);
    const result = { kind: params.kind, site: params.site.slug, country: params.country, date, fetchedAt: now.toISOString(), maxUnits };
    if (params.kind === 'discover') {
      const body = await call('site-explorer/organic-competitors', { ...base, target,
        select: 'competitor_domain,domain_rating,keywords_common,keywords_competitor,share', order_by: 'keywords_common:desc', limit: 5 }, DISCOVERY_UNITS);
      if (!Array.isArray(body.competitors)) throw new AhrefsUnavailable('Ahrefs returned an invalid competitor response.');
      result.competitors = body.competitors.filter(r => domainName(r.competitor_domain) && r.competitor_domain !== new URL(target).hostname).map(r => ({
        domain: domainName(r.competitor_domain), dr: numeric(r.domain_rating), common: numeric(r.keywords_common), missing: numeric(r.keywords_competitor), share: numeric(r.share),
      }));
    } else if (params.kind === 'serp') {
      const seeds = params.seedKeywords.map(query => ({ query }));
      const peers = new Map(), ownHost = new URL(target).hostname.replace(/^www\./, '');
      await settledResults(seeds.map(async seed => {
        const body = await call('serp-overview/serp-overview', { keyword: seed.query, country: params.country, date,
          select: 'url,position,domain_rating', top_positions: 10, type: 'organic', output: 'json' }, 50);
        if (!Array.isArray(body.positions)) throw new AhrefsUnavailable('Ahrefs returned an invalid search-results response.');
        for (const r of body.positions) {
          const url = safeUrl(r.url); if (!url || numeric(r.position) === null || r.position < 1 || r.position > 10) continue;
          const domain = new URL(url).hostname.replace(/^www\./, '');
          if (!domainName(domain) || domain === ownHost) continue;
          if (!peers.has(domain)) peers.set(domain, { domain, dr: numeric(r.domain_rating), common: null, missing: null, seeds: [] });
          const peer = peers.get(domain);
          if (!peer.seeds.includes(seed.query)) peer.seeds.push(seed.query);
        }
      }));
      result.seedKeywords = seeds.map(s => s.query);
      result.competitors = [...peers.values()].sort((a, b) => b.seeds.length - a.seeds.length || a.domain.localeCompare(b.domain)).slice(0, 8);
    } else {
      const competitorRows = await settledResults(params.competitors.map(async domain => {
        const body = await call('site-explorer/organic-keywords', { ...base, target: domain,
          select: 'keyword,volume,keyword_difficulty,best_position,best_position_url,is_branded',
          where: JSON.stringify({ and: [{ field: 'best_position', is: ['lte', 10] }, { field: 'is_branded', is: ['eq', false] }] }),
          order_by: 'volume:desc', limit: KEYWORDS_PER_COMPETITOR }, 24 * KEYWORDS_PER_COMPETITOR);
        const rows = keywordRows(body);
        if (rows.length > KEYWORDS_PER_COMPETITOR || rows.some(r => r.position > 10)) throw new AhrefsUnavailable('Ahrefs did not honor the bounded keyword request.');
        return { domain, rows };
      }));
      const keywords = [...new Set(competitorRows.flatMap(c => c.rows.map(r => r.keyword)))], batches = [];
      for (let i = 0; i < keywords.length; i += KEYWORDS_PER_COMPETITOR) batches.push(keywords.slice(i, i + KEYWORDS_PER_COMPETITOR));
      const own = (await settledResults(batches.map(async batch => {
        const rows = keywordRows(await call('site-explorer/organic-keywords', { ...base, target,
          select: 'keyword,best_position,best_position_url', limit: batch.length,
          where: JSON.stringify({ or: batch.map(keyword => ({ field: 'keyword', is: ['eq', keyword] })) }),
        }, Math.max(50, batch.length * 3)));
        if (rows.some(r => !batch.some(k => k.toLowerCase() === r.keyword.toLowerCase()))) throw new AhrefsUnavailable('Ahrefs did not honor the target keyword filter.');
        return rows;
      }))).flat();
      result.competitors = params.competitors;
      result.sampledKeywords = keywords.length;
      result.rows = gapRows(competitorRows, own);
    }
    result.units = charged;
    db.prepare('INSERT INTO ahrefs_research_cache(cache_key,site,kind,created_at,payload) VALUES (?,?,?,?,?) ON CONFLICT(cache_key) DO UPDATE SET created_at=excluded.created_at,payload=excluded.payload').run(cacheKey, params.site.slug, params.kind, now.toISOString(), JSON.stringify(result));
    return result;
  } finally {
    db.prepare('UPDATE ahrefs_research_spend SET units=? WHERE id=?').run(Math.max(0, Math.ceil(charged)), reservation);
  }
}
