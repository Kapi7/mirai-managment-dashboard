/**
 * The dataset behind the AIO dashboard page (web/family).
 *
 * One payload carries every site's daily history, so the page can change the
 * period, the site set and the traffic filter without another round trip.
 * Numbers are copied from the tables the fetcher wrote, never recomputed here:
 * the page sums what was stored, which keeps "zero", "nothing stored" and
 * "no access" as distinguishable as they are in SQLite.
 *
 * Size is kept down two ways: dates travel as day offsets from EPOCH, and
 * repeated strings (queries, pages, countries, sources, links, channels) are
 * interned into lookup tables that rows reference by index. History is capped
 * at HISTORY_DAYS — a 12-month window plus the 12 months it is compared with.
 *
 * Nothing in the result carries a credential or a filesystem path: messages go
 * through redactPaths(), and credentials are reported by name and status only —
 * the key files are never opened here (CLAUDE.md §1).
 */
import { credentialStatusFor, redactPaths } from './config.js';
import * as ahrefs from './ahrefs.js';

export const EPOCH = '2025-01-01';
export const HISTORY_DAYS = 730;
const DAY_MS = 86_400_000;
const EPOCH_MS = Date.parse(`${EPOCH}T00:00:00Z`);

/** Whole days between EPOCH and an ISO date (or datetime). */
export const dayIndex = (iso) => Math.round((Date.parse(`${String(iso).slice(0, 10)}T00:00:00Z`) - EPOCH_MS) / DAY_MS);
/** The ISO date `d` days after EPOCH. */
export const isoOfDay = (d) => new Date(EPOCH_MS + d * DAY_MS).toISOString().slice(0, 10);

const round1 = (x) => Math.round(x * 10) / 10;

/** Assigns each distinct key a stable index; `list` is what ships. */
class Interner {
  constructor() { this.list = []; this.index = new Map(); }
  id(key, value = key) {
    let i = this.index.get(key);
    if (i === undefined) {
      i = this.list.length;
      this.index.set(key, i);
      this.list.push(value);
    }
    return i;
  }
}

/** Which credential reaches which sites, and whether it is set up. No paths, no secrets. */
export function credentialSummary(cfg) {
  return Object.entries(cfg.credentials || {}).map(([name, cred]) => {
    const status = credentialStatusFor(cred);
    return {
      name,
      kind: cred.kind,
      envVar: cred.envVar,
      configured: status.configured,
      gscSites: cfg.sites.filter((s) => s.gscProperty && s.gscAuth === name).map((s) => s.slug),
      ga4Sites: cfg.sites.filter((s) => s.ga4PropertyId && s.ga4Auth === name).map((s) => s.slug),
    };
  });
}

/**
 * @param {import('better-sqlite3').Database} database opened read-only
 * @param {object} cfg loadConfig() result
 * @returns {object} the page's dataset; `empty: true` when nothing has been fetched
 */
export function buildDashboard(database, cfg, { now = new Date() } = {}) {
  const one = (sql, ...args) => database.prepare(sql).get(...args);
  const gscEndIso = one('SELECT MAX(date) AS d FROM gsc_daily')?.d || null;
  const ga4EndIso = one('SELECT MAX(date) AS d FROM ga4_daily')?.d || null;
  const lastFetch = one('SELECT MAX(run_at) AS r FROM fetch_log')?.r || null;
  const base = {
    epoch: EPOCH,
    generatedAt: now.toISOString(),
    lastFetch,
    credentials: credentialSummary(cfg),
    ahrefs: { configured: ahrefs.credentialStatus().configured },
  };
  if (!gscEndIso && !ga4EndIso) return { ...base, empty: true, sites: [] };

  const gscEnd = gscEndIso ? dayIndex(gscEndIso) : null;
  const ga4End = ga4EndIso ? dayIndex(ga4EndIso) : null;
  // Periods end on the last day every source has delivered, so a Search Console
  // number is never compared with a GA4 number that has two more days in it.
  const end = gscEnd != null && ga4End != null ? Math.min(gscEnd, ga4End) : (gscEnd ?? ga4End);
  const floor = isoOfDay(end - HISTORY_DAYS);

  const tables = {
    channels: new Interner(), countries: new Interner(), queries: new Interner(),
    pages: new Interner(), sources: new Interner(), links: new Interner(),
  };
  const affiliate = (cfg.settings.affiliateEvents || []).map(String);
  const q = (sql) => database.prepare(sql);
  const stmt = {
    gsc: q('SELECT date, clicks, impressions, position FROM gsc_daily WHERE site = ? AND date >= ? ORDER BY date'),
    ga4: q(`SELECT date, channel, sessions, engaged_sessions FROM ga4_daily
            WHERE site = ? AND property_id = ? AND date >= ? ORDER BY date`),
    events: affiliate.length ? q(`SELECT date, SUM(event_count) AS n FROM ga4_event
            WHERE site = ? AND property_id = ? AND date >= ? AND event_name IN (${affiliate.map(() => '?').join(',')})
            GROUP BY date ORDER BY date`) : null,
    geo: q(`SELECT date, country, country_id, sessions FROM ga4_geo
            WHERE site = ? AND property_id = ? AND date >= ? ORDER BY date`),
    src: q(`SELECT date, source, medium, sessions, engaged_sessions FROM ga4_source
            WHERE site = ? AND property_id = ? AND date >= ? ORDER BY date`),
    links: q(`SELECT date, link_url, SUM(event_count) AS n FROM ga4_event_link
            WHERE site = ? AND property_id = ? AND date >= ? GROUP BY date, link_url ORDER BY date`),
    // Mirai's multilingual storefront has hundreds of thousands of page rows.
    // Keep all daily headline totals, but bound detailed series in the browser.
    // The coverage label makes this sample explicit for every date selection.
    queries: q(`SELECT date, query, clicks, impressions, position FROM gsc_query WHERE site = @site AND date >= @floor
      AND query IN (SELECT query FROM gsc_query WHERE site=@site AND date>=@floor GROUP BY query ORDER BY SUM(impressions) DESC LIMIT 500) ORDER BY date`),
    pages: q(`SELECT date, page, clicks, impressions, position FROM gsc_page WHERE site = @site AND date >= @floor
      AND page IN (SELECT page FROM gsc_page WHERE site=@site AND date>=@floor GROUP BY page ORDER BY SUM(impressions) DESC LIMIT 250) ORDER BY date`),
    commerce: q('SELECT date,source,medium,sessions,purchases,revenue FROM mirai_commerce WHERE site=? AND property_id=? AND date>=? ORDER BY date'),
    wp: q('SELECT date, post_count, last_post_date FROM wp_content WHERE site = ? AND date >= ? ORDER BY date'),
    sitemap: q(`SELECT date, submitted, sitemap_count, errors, warnings, last_downloaded FROM gsc_sitemap
            WHERE site = ? ORDER BY date DESC LIMIT 1`),
    ahrefs: q(`SELECT date, domain_rating, backlinks, backlinks_dofollow, refdomains, organic_keywords, organic_traffic FROM ahrefs_snapshot
            WHERE site = ? AND date >= ? ORDER BY date`),
    fetch: q(`SELECT source, status, data_through, message, run_at FROM fetch_log
            WHERE id IN (SELECT MAX(id) FROM fetch_log WHERE site = ? GROUP BY source)`),
  };
  const hostPrefix = /^https?:\/\/[^/]+/;

  const sites = cfg.sites.map((site) => {
    const pid = site.ga4PropertyId;
    const out = {
      slug: site.slug,
      name: site.name,
      vertical: site.vertical,
      platform: site.platform,
      gsc_property: site.gscProperty,
      ga4: pid,
      g: stmt.gsc.all(site.slug, floor).map((r) => [dayIndex(r.date), r.clicks, r.impressions, round1(r.position * r.impressions)]),
      q: stmt.queries.all({site:site.slug, floor}).map((r) =>
        [dayIndex(r.date), tables.queries.id(r.query), r.clicks, r.impressions, round1(r.position * r.impressions)]),
      p: stmt.pages.all({site:site.slug, floor}).map((r) =>
        [dayIndex(r.date), tables.pages.id(r.page.replace(hostPrefix, '') || '/'), r.clicks, r.impressions, round1(r.position * r.impressions)]),
      wp: stmt.wp.all(site.slug, floor).map((r) => [dayIndex(r.date), r.post_count, r.last_post_date ? dayIndex(r.last_post_date) : -1]),
      ah: stmt.ahrefs.all(site.slug, floor).map((r) => [r.date, r.domain_rating, r.backlinks, r.backlinks_dofollow, r.refdomains, r.organic_keywords, r.organic_traffic]),
      a: [], ev: [], geo: [], src: [], lk: [],
      sales: pid ? stmt.commerce.all(site.slug,pid,floor).map(r => [dayIndex(r.date),r.source,r.medium,r.sessions,r.purchases,r.revenue]) : [],
    };
    if (pid) {
      // The primary property only — summing a site's two properties double-counts.
      out.a = stmt.ga4.all(site.slug, pid, floor).map((r) => [dayIndex(r.date), tables.channels.id(r.channel), r.sessions, r.engaged_sessions]);
      out.ev = stmt.events ? stmt.events.all(site.slug, pid, floor, ...affiliate).map((r) => [dayIndex(r.date), r.n]) : [];
      out.geo = stmt.geo.all(site.slug, pid, floor).map((r) =>
        [dayIndex(r.date), tables.countries.id(r.country, [r.country, r.country_id || '']), r.sessions]);
      out.src = stmt.src.all(site.slug, pid, floor).map((r) =>
        [dayIndex(r.date), tables.sources.id(`${r.source}|${r.medium}`), r.sessions, r.engaged_sessions]);
      out.lk = stmt.links.all(site.slug, pid, floor).map((r) => [dayIndex(r.date), tables.links.id(r.link_url), r.n]);
    }
    const sm = stmt.sitemap.get(site.slug);
    out.sm = sm ? { sub: sm.submitted, cnt: sm.sitemap_count, err: sm.errors, warn: sm.warnings, last: sm.last_downloaded, asof: sm.date } : null;
    out.fetch = Object.fromEntries(stmt.fetch.all(site.slug).map((r) => [r.source, {
      status: r.status, through: r.data_through, runAt: r.run_at, message: redactPaths(r.message) || null,
    }]));
    return out;
  });

  const firstDays = sites.flatMap((s) => [s.g[0]?.[0], s.a[0]?.[0]]).filter((d) => d != null);
  return {
    ...base,
    empty: false,
    end,
    gscEnd,
    ga4End,
    minDay: firstDays.length ? Math.min(...firstDays) : end,
    channels: tables.channels.list,
    countries: tables.countries.list,
    queries: tables.queries.list,
    pages: tables.pages.list,
    sources: tables.sources.list,
    links: tables.links.list,
    sites,
  };
}
