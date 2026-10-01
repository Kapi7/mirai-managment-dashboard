/**
 * Fetch orchestrator — pulls GSC + GA4 into SQLite.
 *
 *   npm run seo:fetch               incremental (backfills on first run)
 *   npm run seo:fetch -- --full      full configured backfill
 *   npm run seo:fetch -- --ahrefs    explicit Ahrefs profiles
 *
 * Each source resolves its own request window from its own lag, and each GA4 property
 * resolves its own incremental anchor. Every attempt is logged with the connection it
 * describes and the newest date it actually delivered.
 */
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig, googleCredentials, credentialStatusFor, CREDENTIAL_ENV_VAR } from './config.js';
import * as db from './db.js';
import * as gsc from './gsc.js';
import * as ga4 from './ga4.js';
import * as wordpress from './wordpress.js';
import * as ahrefs from './ahrefs.js';
import { fetchCommerce } from './commerce.js';
import { SOURCE, latestCompleteDate, shiftDate, primaryGa4Scope, sourceAsOf } from './reporting.js';

// Page/query dimensions return huge row counts. Backfilling those in one
// request would blow past row limits and time out, so history is chunked.
const GSC_CHUNK_DAYS = 30;
const GA4_CHUNK_DAYS = 90;

const log = (msg) =>
  console.log(`[${new Date().toTimeString().slice(0, 8)}] ${msg}`);

/** Inclusive [start, end] chunks of at most `size` days, over ISO date strings. */
function* dateChunks(start, end, size) {
  let cur = start;
  while (cur <= end) {
    const stop = shiftDate(cur, size - 1);
    yield [cur, stop > end ? end : stop];
    cur = shiftDate(stop, 1);
  }
}

/**
 * Decide which dates to request: full backfill, or an incremental refresh.
 *
 * The end date comes from the requested source's *own* lag — applying the Search
 * Console delay to GA4 would discard two days of GA4 data that exist and are complete.
 *
 * The anchor comes from `(table, site, propertyId)`. Scoping it to the property is what
 * lets a newly added GA4 property backfill instead of inheriting its sibling's anchor.
 *
 * @returns {{startDate: string, endDate: string}|null} null when already current
 */
function resolveWindow({ database, table, source, slug, propertyId = null, settings, full, now = new Date() }) {
  const endDate = latestCompleteDate(source, settings.sourceLagDays, now);
  const backfillStart = shiftDate(endDate, -settings.backfillMonths * 30);
  if (full) return { startDate: backfillStart, endDate };

  const last = db.latestDate(database, table, slug, propertyId);
  if (!last) return { startDate: backfillStart, endDate };

  // Re-fetch a trailing window so Google's late data corrections land.
  let startDate = shiftDate(last, -settings.refreshWindowDays);
  if (startDate < backfillStart) startDate = backfillStart;
  if (startDate > endDate) return null;
  return { startDate, endDate };
}

const failureStatus = (err, DeniedClass) =>
  err instanceof DeniedClass ? 'no_access' : 'error';
const failureMessage = (err, DeniedClass) =>
  err instanceof DeniedClass ? err.message : `${err.name}: ${err.message}`;

async function fetchGsc(database, client, site, settings, full, runAt) {
  const connection = site.gscProperty;
  const window = resolveWindow({
    database, table: 'gsc_daily', source: SOURCE.GSC, slug: site.slug, settings, full,
  });

  if (!window) {
    log(`  ${site.slug}: GSC already current`);
  } else {
    const { startDate, endDate } = window;
    log(`  ${site.slug}: GSC ${startDate} → ${endDate}`);
    let rows = 0;
    try {
      for (const [cs, ce] of dateChunks(startDate, endDate, GSC_CHUNK_DAYS)) {
        rows += db.upsert(database, 'gsc_daily',
          await gsc.daily(client, site.slug, site.gscProperty, cs, ce));
        rows += db.upsert(database, 'gsc_page',
          await gsc.pages(client, site.slug, site.gscProperty, cs, ce));
        rows += db.upsert(database, 'gsc_query',
          await gsc.queries(client, site.slug, site.gscProperty, cs, ce));
      }
      // What was actually delivered, which is not necessarily `endDate`.
      const dataThrough = db.latestDate(database, 'gsc_daily', site.slug);
      db.logFetch(database, { runAt, source: SOURCE.GSC, site: site.slug, connection,
        startDate, endDate, dataThrough, rows, status: 'ok' });
      log(`  ${site.slug}: GSC ${rows.toLocaleString()} rows through ${dataThrough ?? 'n/a'}`);
    } catch (err) {
      const status = failureStatus(err, gsc.AccessDenied);
      const message = failureMessage(err, gsc.AccessDenied);
      db.logFetch(database, { runAt, source: SOURCE.GSC, site: site.slug, connection,
        startDate, endDate, rows, status, message });
      log(`  ${site.slug}: GSC ${status === 'no_access' ? 'SKIPPED' : 'ERROR'} — ${message}`);
    }
  }

  // Sitemap status is a point-in-time snapshot — no date window — and logged
  // separately so a sitemap failure never masks a successful analytics pull.
  try {
    const snapshot = await gsc.sitemaps(client, site.slug, site.gscProperty);
    const rows = db.upsert(database, 'gsc_sitemap', [snapshot]);
    db.logFetch(database, { runAt, source: SOURCE.SITEMAP, site: site.slug, connection,
      rows, dataThrough: snapshot.date, status: 'ok' });
  } catch (err) {
    const status = failureStatus(err, gsc.AccessDenied);
    const message = failureMessage(err, gsc.AccessDenied);
    db.logFetch(database, { runAt, source: SOURCE.SITEMAP, site: site.slug, connection,
      rows: 0, status, message });
    log(`  ${site.slug}: sitemap ${status === 'no_access' ? 'SKIPPED' : 'ERROR'} — ${message}`);
  }
}

/** Content snapshot from the WordPress REST API. Point-in-time, no date window. */
async function fetchWordpress(database, site, runAt) {
  const connection = site.wpOrigin;
  try {
    const row = await wordpress.content(site.slug, site.wpOrigin);
    const rows = db.upsert(database, 'wp_content', [row]);
    db.logFetch(database, { runAt, source: SOURCE.WORDPRESS, site: site.slug, connection,
      rows, dataThrough: row[1], status: 'ok' });
    log(`  ${site.slug}: WordPress ok`);
  } catch (err) {
    const status = failureStatus(err, wordpress.WpUnavailable);
    const message = failureMessage(err, wordpress.WpUnavailable);
    db.logFetch(database, { runAt, source: SOURCE.WORDPRESS, site: site.slug, connection,
      rows: 0, status, message });
    log(`  ${site.slug}: WordPress ${status === 'no_access' ? 'SKIPPED' : 'ERROR'} — ${message}`);
  }
}

/** One Ahrefs Batch Analysis call for every selected site. */
async function fetchAhrefs(database, sites, runAt) {
  const targets = sites.filter((site) => ahrefs.targetForSite(site));
  if (targets.length === 0) return;
  const credential = ahrefs.credentialStatus();
  if (!credential.configured) {
    logNotConfigured(database, SOURCE.AHREFS, targets, runAt, credential.reason,
      (site) => [ahrefs.targetForSite(site)]);
    return;
  }
  let pending = targets;
  try {
    // Snapshots are current readings, not historical backfills. Reuse today's
    // complete profile so dashboard refreshes do not repeatedly spend units.
    const today = new Date().toISOString().slice(0, 10);
    pending = targets.filter(s => !database.prepare('SELECT 1 FROM ahrefs_snapshot WHERE site=? AND date=? AND refdomains IS NOT NULL').get(s.slug, today));
    if (!pending.length) { log('  Ahrefs profiles already refreshed today'); return; }
    ahrefs.requireAllowance(await ahrefs.limitsAndUsage(), Math.max(50, pending.length * ahrefs.PROFILE_UNITS_PER_SITE));
    const snapshots = await ahrefs.batchMetrics(pending, { extended: true });
    db.upsert(database, 'ahrefs_profile', snapshots);
    for (let i = 0; i < pending.length; i++) {
      const row = snapshots[i];
      db.logFetch(database, {
        runAt, source: SOURCE.AHREFS, site: pending[i].slug,
        connection: ahrefs.targetForSite(pending[i]), rows: 1,
        dataThrough: row[1], status: 'ok',
      });
    }
    log(`  Ahrefs ${snapshots.length} site snapshots`);
  } catch (err) {
    const status = err instanceof ahrefs.AccessDenied ? 'no_access' : 'error';
    for (const site of pending) {
      db.logFetch(database, {
        runAt, source: SOURCE.AHREFS, site: site.slug,
        connection: ahrefs.targetForSite(site), rows: 0, status, message: err.message,
      });
    }
    log(`  Ahrefs ${status === 'no_access' ? 'SKIPPED' : 'ERROR'} — ${err.message}`);
  }
}

/**
 * GA4 traffic, events and session breakdowns, per property.
 *
 * The window is resolved *inside* the property loop. Resolving it once per site would
 * anchor a brand-new property on its sibling's latest date, giving it a 7-day refresh
 * window instead of a backfill — and then the property-comparison panel would be
 * deciding between 16 months of history and one week of it.
 *
 * Two anchors, not one. `ga4_geo` / `ga4_source` were added after `ga4_daily`, so on
 * every existing database they start empty while the traffic table is already current.
 * Anchoring them on `ga4_daily` would hand them its "already current" answer and they
 * would never fetch a day. Given their own anchor they backfill exactly like a newly
 * added property, then fall in step with the rest.
 */
async function fetchGa4(database, client, site, settings, full, runAt) {
  for (const propertyId of site.ga4PropertyIds) {
    const label = `${site.slug}[${propertyId}]`;
    const anchor = (table) => resolveWindow({
      database, table, source: SOURCE.GA4, slug: site.slug, propertyId, settings, full,
    });
    const core = anchor('ga4_daily');
    const breakdown = anchor('ga4_geo');
    if (!core && !breakdown) {
      log(`  ${label}: GA4 already current`);
      continue;
    }
    // The union of both windows, for the log: it must describe what was actually
    // requested, not one half of it.
    const startDate = [core, breakdown].filter(Boolean)
      .map((w) => w.startDate).sort()[0];
    const endDate = [core, breakdown].filter(Boolean)
      .map((w) => w.endDate).sort().reverse()[0];
    log(`  ${label}: GA4 ${startDate} → ${endDate}`);
    let rows = 0;
    try {
      if (core) {
        for (const [cs, ce] of dateChunks(core.startDate, core.endDate, GA4_CHUNK_DAYS)) {
          rows += db.upsert(database, 'ga4_daily',
            await ga4.traffic(client, site.slug, propertyId, cs, ce));
          rows += db.upsert(database, 'ga4_event',
            await ga4.events(client, site.slug, propertyId, cs, ce));
          rows += db.upsert(database, 'ga4_event_link',
            await ga4.eventLinks(client, site.slug, propertyId, cs, ce,
              settings.affiliateEvents));
        }
      }
      if (breakdown) {
        for (const [cs, ce] of dateChunks(breakdown.startDate, breakdown.endDate, GA4_CHUNK_DAYS)) {
          rows += db.upsert(database, 'ga4_geo',
            await ga4.geography(client, site.slug, propertyId, cs, ce));
          rows += db.upsert(database, 'ga4_source',
            await ga4.acquisition(client, site.slug, propertyId, cs, ce));
        }
      }
      const dataThrough = db.latestDate(database, 'ga4_daily', site.slug, propertyId);
      db.logFetch(database, { runAt, source: SOURCE.GA4, site: site.slug, connection: propertyId,
        startDate, endDate, dataThrough, rows, status: 'ok',
        message: propertyId === site.ga4PropertyId ? 'primary property' : 'alternate property' });
      log(`  ${label}: GA4 ${rows.toLocaleString()} rows through ${dataThrough ?? 'n/a'}`);
    } catch (err) {
      const status = failureStatus(err, ga4.AccessDenied);
      const message = failureMessage(err, ga4.AccessDenied);
      db.logFetch(database, { runAt, source: SOURCE.GA4, site: site.slug, connection: propertyId,
        startDate, endDate, rows, status, message });
      log(`  ${label}: GA4 ${status === 'no_access' ? 'SKIPPED' : 'ERROR'} — ${message}`);
    }
    if (propertyId === site.ga4PropertyId) {
      const commerce = anchor('mirai_commerce');
      if (commerce) {
        try {
          const count = await fetchCommerce(database, client, site, commerce.startDate, commerce.endDate);
          db.logFetch(database, { runAt, source: 'ga4_commerce', site: site.slug, connection: propertyId,
            startDate: commerce.startDate, endDate: commerce.endDate, dataThrough: commerce.endDate, rows: count, status: 'ok' });
        } catch {
          db.logFetch(database, { runAt, source: 'ga4_commerce', site: site.slug, connection: propertyId,
            status: 'error', message: 'GA4 commerce report could not be read. Other analytics history is preserved.' });
        }
      }
    }
  }
}

/**
 * Record a source as unconfigured rather than failed.
 *
 * A missing credential is a setup gap, not an API error, and the two must not
 * look alike in Data health. `reason` is written verbatim and is path-free.
 *
 * `connectionsOf` yields one log row per connection, so an unconfigured site with two
 * GA4 properties reports both rather than collapsing into one ambiguous row.
 */
function logNotConfigured(database, source, targets, runAt, reason, connectionsOf) {
  let written = 0;
  for (const s of targets) {
    for (const connection of connectionsOf(s)) {
      db.logFetch(database, { runAt, source, site: s.slug, connection, rows: 0,
        status: 'not_configured', message: reason });
      written++;
    }
  }
  log(`  SKIPPED ${written} connection(s) across ${targets.length} site(s) — ${reason}`);
}

export async function runFetch({ full = false, site = null, source = null } = {}) {
  const cfg = loadConfig();
  const { settings } = cfg;

  // Resolved once per run. Google sources degrade to 'not_configured' without
  // it; WordPress needs no credential and always runs.
  const credentials = googleCredentials();
  if (credentials.insideRepo) {
    console.warn(
      `Warning: ${CREDENTIAL_ENV_VAR} points inside the project folder. Move the ` +
      `key somewhere outside it so it can never be zipped or committed by accident.`,
    );
  }

  const database = db.initDb(settings.database);
  const runAt = new Date().toISOString();
  const sites = cfg.sites.filter((s) => !site || s.slug === site);
  if (sites.length === 0) throw new Error(`No site matching '${site}'`);

  try {
    if (!source || source === SOURCE.GSC || source === SOURCE.SITEMAP) {
      const targets = sites.filter((s) => s.gscProperty);
      if (targets.length) {
        log('=== Search Console ===');
        // Sites route to named credentials (config.credentials). Each credential
        // authenticates once; an unconfigured one degrades only ITS sites to
        // not_configured — the rest of the portfolio still fetches.
        const byCred = new Map();
        for (const s of targets) {
          if (!byCred.has(s.gscAuth)) byCred.set(s.gscAuth, []);
          byCred.get(s.gscAuth).push(s);
        }
        for (const [credName, credSites] of byCred) {
          const status = credentialStatusFor(cfg.credentials[credName]);
          if (status.insideRepo) {
            console.warn(`Warning: ${cfg.credentials[credName].envVar} points inside the ` +
              `project folder. Move the file outside it.`);
          }
          if (!status.configured) {
            for (const src of [SOURCE.GSC, SOURCE.SITEMAP]) {
              logNotConfigured(database, src, credSites, runAt, status.reason,
                (s) => [s.gscProperty]);
            }
            continue;
          }
          const client = await gsc.createClient(status.keyFile);
          for (const s of credSites) await fetchGsc(database, client, s, settings, full, runAt);
        }
      }
    }
    if (!source || source === SOURCE.GA4) {
      const targets = sites.filter((s) => s.ga4PropertyIds.length > 0);
      if (targets.length) {
        log('=== Google Analytics 4 ===');
        // Routed per credential exactly like Search Console above.
        const byCred = new Map();
        for (const s of targets) {
          if (!byCred.has(s.ga4Auth)) byCred.set(s.ga4Auth, []);
          byCred.get(s.ga4Auth).push(s);
        }
        for (const [credName, credSites] of byCred) {
          const status = credentialStatusFor(cfg.credentials[credName]);
          if (!status.configured) {
            logNotConfigured(database, SOURCE.GA4, credSites, runAt, status.reason,
              (s) => s.ga4PropertyIds);
            continue;
          }
          const client = ga4.createClient(status.keyFile);
          for (const s of credSites) await fetchGa4(database, client, s, settings, full, runAt);
        }
      }
    }
    if (!source || source === SOURCE.WORDPRESS) {
      const targets = sites.filter((s) => s.wpOrigin);
      if (targets.length) {
        log('=== WordPress ===');
        for (const s of targets) await fetchWordpress(database, s, runAt);
      }
    }
    if (!source || source === SOURCE.AHREFS) {
      log('=== Ahrefs ===');
      await fetchAhrefs(database, sites, runAt);
    }

    const failed = database.prepare(
      `SELECT source, site, connection, status, message FROM fetch_log
       WHERE run_at = ? AND status != 'ok' ORDER BY source, site, connection`,
    ).all(runAt);

    // The latest date each source actually delivered, portfolio-wide. GA4 is scoped to
    // primary properties because that is what the dashboard reports on.
    const asOf = {
      [SOURCE.GSC]: sourceAsOf(database, SOURCE.GSC),
      [SOURCE.GA4]: sourceAsOf(database, SOURCE.GA4, { scope: primaryGa4Scope(cfg.sites) }),
      [SOURCE.WORDPRESS]: sourceAsOf(database, SOURCE.WORDPRESS),
      [SOURCE.SITEMAP]: sourceAsOf(database, SOURCE.SITEMAP),
      [SOURCE.AHREFS]: sourceAsOf(database, SOURCE.AHREFS),
    };

    log('=== Done ===');
    log(`Data through — GSC ${asOf.gsc ?? 'n/a'}, GA4 ${asOf.ga4 ?? 'n/a'}, ` +
      `WordPress ${asOf.wordpress ?? 'n/a'}, sitemap ${asOf.gsc_sitemap ?? 'n/a'}, `
      + `Ahrefs ${asOf.ahrefs ?? 'n/a'}`);
    if (failed.length) {
      log(`${failed.length} source/site/connection triples need attention:`);
      for (const f of failed) {
        log(`  [${f.status}] ${f.source} ${f.site}${f.connection ? ` (${f.connection})` : ''}: ${f.message}`);
      }
    }
    return { runAt, failed, sourceAsOf: asOf };
  } finally {
    database.close();
  }
}

// CLI entry point — only when run directly, not when imported by the server.
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const argv = process.argv.slice(2);
  const flag = (name) => {
    const i = argv.indexOf(`--${name}`);
    return i >= 0 ? argv[i + 1] : null;
  };
  runFetch({
    full: argv.includes('--full'),
    site: flag('site'),
    source: flag('source'),
  }).catch((err) => {
    console.error(`FATAL: ${err.message}`);
    process.exit(1);
  });
}

// Exported for tests: window resolution is the highest-risk arithmetic in this file.
export { resolveWindow, dateChunks };
