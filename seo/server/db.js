/**
 * SQLite schema, migrations and write helpers.
 *
 * All writes are idempotent upserts on natural keys, so re-fetching an
 * overlapping date range corrects existing rows instead of duplicating them.
 * This matters because Google revises Search Console data for several days
 * after the fact.
 */
import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import Database from 'better-sqlite3';
import { initCommerce } from './commerce.js';

const SCHEMA = `
CREATE TABLE IF NOT EXISTS gsc_daily (
  site TEXT NOT NULL, date TEXT NOT NULL,
  clicks INTEGER NOT NULL DEFAULT 0, impressions INTEGER NOT NULL DEFAULT 0,
  ctr REAL NOT NULL DEFAULT 0, position REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (site, date)
);

CREATE TABLE IF NOT EXISTS gsc_page (
  site TEXT NOT NULL, date TEXT NOT NULL, page TEXT NOT NULL,
  clicks INTEGER NOT NULL DEFAULT 0, impressions INTEGER NOT NULL DEFAULT 0,
  ctr REAL NOT NULL DEFAULT 0, position REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (site, date, page)
);
CREATE INDEX IF NOT EXISTS idx_gsc_page_site_date ON gsc_page (site, date);

CREATE TABLE IF NOT EXISTS gsc_query (
  site TEXT NOT NULL, date TEXT NOT NULL, query TEXT NOT NULL,
  clicks INTEGER NOT NULL DEFAULT 0, impressions INTEGER NOT NULL DEFAULT 0,
  ctr REAL NOT NULL DEFAULT 0, position REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (site, date, query)
);
CREATE INDEX IF NOT EXISTS idx_gsc_query_site_date ON gsc_query (site, date);

-- property_id is part of the key so a site's two GA4 properties can be stored side
-- by side and compared. Reads MUST scope to one property per site: summing both
-- double-counts every metric. See reporting.primaryGa4Scope.
CREATE TABLE IF NOT EXISTS ga4_daily (
  site TEXT NOT NULL, property_id TEXT NOT NULL, date TEXT NOT NULL,
  channel TEXT NOT NULL,
  sessions INTEGER NOT NULL DEFAULT 0, active_users INTEGER NOT NULL DEFAULT 0,
  engaged_sessions INTEGER NOT NULL DEFAULT 0, page_views INTEGER NOT NULL DEFAULT 0,
  key_events REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (site, property_id, date, channel)
);
CREATE INDEX IF NOT EXISTS idx_ga4_daily_site_date ON ga4_daily (site, date);
CREATE INDEX IF NOT EXISTS idx_ga4_daily_prop_date ON ga4_daily (site, property_id, date);

-- Sessions by country. Same property-scoping rule as ga4_daily: reads MUST pin one
-- property per site or every session is counted twice.
--
-- country is GA4's display name and country_id its ISO 3166-1 alpha-2 code. The
-- code is stored beside the name rather than derived from it, because the name is
-- localised and a lookup built from it would be a guess. GA4's '(not set)' rows —
-- sessions it could not place — are stored as measured, so this table sums back to
-- the session total in ga4_daily.
CREATE TABLE IF NOT EXISTS ga4_geo (
  site TEXT NOT NULL, property_id TEXT NOT NULL, date TEXT NOT NULL,
  country TEXT NOT NULL, country_id TEXT NOT NULL DEFAULT '',
  sessions INTEGER NOT NULL DEFAULT 0, active_users INTEGER NOT NULL DEFAULT 0,
  engaged_sessions INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (site, property_id, date, country)
);
CREATE INDEX IF NOT EXISTS idx_ga4_geo_site_date ON ga4_geo (site, date);

-- Sessions by session source and session medium — the grain under ga4_daily.channel.
-- Both dimensions are session-scoped, so they describe the same unit the sessions
-- metric counts. GA4's placeholders ('(direct)', '(none)', '(not set)') are stored
-- verbatim: they are what was measured, and rewriting one invents an attribution.
CREATE TABLE IF NOT EXISTS ga4_source (
  site TEXT NOT NULL, property_id TEXT NOT NULL, date TEXT NOT NULL,
  source TEXT NOT NULL, medium TEXT NOT NULL,
  sessions INTEGER NOT NULL DEFAULT 0, active_users INTEGER NOT NULL DEFAULT 0,
  engaged_sessions INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (site, property_id, date, source, medium)
);
CREATE INDEX IF NOT EXISTS idx_ga4_source_site_date ON ga4_source (site, date);

CREATE TABLE IF NOT EXISTS ga4_event (
  site TEXT NOT NULL, property_id TEXT NOT NULL, date TEXT NOT NULL,
  event_name TEXT NOT NULL, event_count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (site, property_id, date, event_name)
);
CREATE INDEX IF NOT EXISTS idx_ga4_event_site_date ON ga4_event (site, date);
CREATE INDEX IF NOT EXISTS idx_ga4_event_prop_date ON ga4_event (site, property_id, date);

-- Affiliate/outbound clicks broken down by destination link. Only the configured
-- affiliate events are fetched at this grain — every event name at every URL
-- would be mostly page_view noise at ~100x the rows.
--
-- link_url is the raw destination as GA4 recorded it. Brand and geo are PARSED
-- AT READ TIME (server/brands.js), never stored: parsing rules improve over time
-- and a stored brand would freeze yesterday's rule errors into the data.
-- GA4 reports '(not set)' when the click had no link_url; that is stored as-is,
-- because it is what was measured.
CREATE TABLE IF NOT EXISTS ga4_event_link (
  site TEXT NOT NULL, property_id TEXT NOT NULL, date TEXT NOT NULL,
  event_name TEXT NOT NULL, link_url TEXT NOT NULL,
  event_count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (site, property_id, date, event_name, link_url)
);
CREATE INDEX IF NOT EXISTS idx_ga4_event_link_site_date ON ga4_event_link (site, date);

-- Content and indexing counts stored as one dated snapshot per fetch run.
-- (site, date) key means re-running a day corrects the row; keeping history
-- costs almost nothing and leaves room for a content-growth trend later.
CREATE TABLE IF NOT EXISTS wp_content (
  site TEXT NOT NULL, date TEXT NOT NULL,
  post_count INTEGER NOT NULL DEFAULT 0,
  last_post_date TEXT,
  PRIMARY KEY (site, date)
);

-- Ahrefs Batch Analysis snapshot. These are provider readings, never estimates.
CREATE TABLE IF NOT EXISTS ahrefs_snapshot (
  site TEXT NOT NULL, date TEXT NOT NULL,
  backlinks INTEGER NOT NULL DEFAULT 0,
  backlinks_dofollow INTEGER NOT NULL DEFAULT 0,
  backlinks_nofollow INTEGER NOT NULL DEFAULT 0,
  domain_rating REAL,
  PRIMARY KEY (site, date)
);

-- Sitemap status snapshot.
--
-- DEPRECATED COLUMN: indexed. Google has deprecated the sitemaps API's indexed
-- field and it now reports 0 for most properties. It is retained only so existing
-- databases keep their history and older builds still open. Nothing reads it: no
-- calculation, no API response, no UI label. Real index coverage needs the URL
-- Inspection API. Report "submitted" as "Submitted sitemap URLs" instead.
CREATE TABLE IF NOT EXISTS gsc_sitemap (
  site TEXT NOT NULL, date TEXT NOT NULL,
  submitted INTEGER NOT NULL DEFAULT 0,
  indexed INTEGER NOT NULL DEFAULT 0,
  sitemap_count INTEGER NOT NULL DEFAULT 0,
  errors INTEGER NOT NULL DEFAULT 0,
  warnings INTEGER NOT NULL DEFAULT 0,
  pending INTEGER NOT NULL DEFAULT 0,
  last_downloaded TEXT,
  PRIMARY KEY (site, date)
);

-- One row per source+site+connection per run.
--
-- "connection" disambiguates a site's multiple endpoints for one source — a GA4
-- property id, a GSC property URL, a WordPress origin. Without it, a site's two GA4
-- properties log two rows with an identical (source, site, run_at) and the health
-- query cannot tell them apart.
--
-- "data_through" records the newest date the attempt actually delivered, which is how
-- the dashboard knows what "current" means for each source.
CREATE TABLE IF NOT EXISTS fetch_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_at TEXT NOT NULL, source TEXT NOT NULL, site TEXT NOT NULL,
  connection TEXT NOT NULL DEFAULT '',
  start_date TEXT, end_date TEXT, data_through TEXT,
  rows INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL, message TEXT
);
CREATE INDEX IF NOT EXISTS idx_fetch_log_site ON fetch_log (site, source, run_at);
-- NOTE: the index on (source, site, connection, run_at) is created by migration 001,
-- not here. On an existing database CREATE TABLE IF NOT EXISTS is a no-op, so the
-- connection column does not exist yet at this point and indexing it would fail.

CREATE TABLE IF NOT EXISTS schema_migrations (
  id TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL
);
`;

const UPSERTS = {
  gsc_daily: `INSERT INTO gsc_daily (site,date,clicks,impressions,ctr,position)
    VALUES (?,?,?,?,?,?) ON CONFLICT(site,date) DO UPDATE SET
    clicks=excluded.clicks, impressions=excluded.impressions,
    ctr=excluded.ctr, position=excluded.position`,
  gsc_page: `INSERT INTO gsc_page (site,date,page,clicks,impressions,ctr,position)
    VALUES (?,?,?,?,?,?,?) ON CONFLICT(site,date,page) DO UPDATE SET
    clicks=excluded.clicks, impressions=excluded.impressions,
    ctr=excluded.ctr, position=excluded.position`,
  gsc_query: `INSERT INTO gsc_query (site,date,query,clicks,impressions,ctr,position)
    VALUES (?,?,?,?,?,?,?) ON CONFLICT(site,date,query) DO UPDATE SET
    clicks=excluded.clicks, impressions=excluded.impressions,
    ctr=excluded.ctr, position=excluded.position`,
  ga4_daily: `INSERT INTO ga4_daily (site,property_id,date,channel,sessions,
    active_users,engaged_sessions,page_views,key_events)
    VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(site,property_id,date,channel) DO UPDATE SET
    sessions=excluded.sessions, active_users=excluded.active_users,
    engaged_sessions=excluded.engaged_sessions, page_views=excluded.page_views,
    key_events=excluded.key_events`,
  ga4_geo: `INSERT INTO ga4_geo (site,property_id,date,country,country_id,
    sessions,active_users,engaged_sessions)
    VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(site,property_id,date,country) DO UPDATE SET
    country_id=excluded.country_id, sessions=excluded.sessions,
    active_users=excluded.active_users, engaged_sessions=excluded.engaged_sessions`,
  ga4_source: `INSERT INTO ga4_source (site,property_id,date,source,medium,
    sessions,active_users,engaged_sessions)
    VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(site,property_id,date,source,medium) DO UPDATE SET
    sessions=excluded.sessions, active_users=excluded.active_users,
    engaged_sessions=excluded.engaged_sessions`,
  ga4_event: `INSERT INTO ga4_event (site,property_id,date,event_name,event_count)
    VALUES (?,?,?,?,?) ON CONFLICT(site,property_id,date,event_name) DO UPDATE SET
    event_count=excluded.event_count`,
  ga4_event_link: `INSERT INTO ga4_event_link
    (site,property_id,date,event_name,link_url,event_count)
    VALUES (?,?,?,?,?,?) ON CONFLICT(site,property_id,date,event_name,link_url)
    DO UPDATE SET event_count=excluded.event_count`,
  wp_content: `INSERT INTO wp_content (site,date,post_count,last_post_date)
    VALUES (?,?,?,?) ON CONFLICT(site,date) DO UPDATE SET
    post_count=excluded.post_count, last_post_date=excluded.last_post_date`,
  ahrefs_snapshot: `INSERT INTO ahrefs_snapshot
    (site,date,backlinks,backlinks_dofollow,backlinks_nofollow,domain_rating)
    VALUES (?,?,?,?,?,?) ON CONFLICT(site,date) DO UPDATE SET
    backlinks=excluded.backlinks,
    backlinks_dofollow=excluded.backlinks_dofollow,
    backlinks_nofollow=excluded.backlinks_nofollow,
    domain_rating=excluded.domain_rating`,
  ahrefs_profile: `INSERT INTO ahrefs_snapshot
    (site,date,backlinks,backlinks_dofollow,backlinks_nofollow,domain_rating,refdomains,organic_keywords,organic_traffic)
    VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(site,date) DO UPDATE SET
    backlinks=excluded.backlinks, backlinks_dofollow=excluded.backlinks_dofollow,
    backlinks_nofollow=excluded.backlinks_nofollow, domain_rating=excluded.domain_rating,
    refdomains=excluded.refdomains, organic_keywords=excluded.organic_keywords, organic_traffic=excluded.organic_traffic`,
  // Named parameters (not positional) because the column list is wide and semantic —
  // a nine-slot tuple here would be a silent-misalignment waiting to happen.
  gsc_sitemap: `INSERT INTO gsc_sitemap
    (site,date,submitted,indexed,sitemap_count,errors,warnings,pending,last_downloaded)
    VALUES (@site,@date,@submitted,@indexed,@sitemapCount,@errors,@warnings,@pending,@lastDownloaded)
    ON CONFLICT(site,date) DO UPDATE SET
    submitted=excluded.submitted, indexed=excluded.indexed,
    sitemap_count=excluded.sitemap_count, errors=excluded.errors,
    warnings=excluded.warnings, pending=excluded.pending,
    last_downloaded=excluded.last_downloaded`,
};

// --- Migrations -------------------------------------------------------------

/** Column names present on a table right now. Empty when the table does not exist. */
function columnsOf(db, table) {
  try {
    return new Set(db.prepare(`PRAGMA table_info(${table})`).all().map((c) => c.name));
  } catch {
    return new Set();
  }
}

/**
 * Add a column only when it is missing.
 *
 * Additive by design: no table is rebuilt, no row is rewritten, no data is dropped.
 * Existing rows take the column default, so historical fetch_log entries survive
 * with an empty `connection` and are still uniquely identifiable.
 */
function addColumn(db, table, column, definition) {
  const cols = columnsOf(db, table);
  if (cols.size === 0 || cols.has(column)) return false;
  db.exec(`ALTER TABLE ${table} ADD COLUMN ${column} ${definition}`);
  return true;
}

/**
 * Ordered, idempotent migrations.
 *
 * Each step re-checks the live schema, so it is safe to run on a fresh database
 * (where SCHEMA already created the columns), on a partially migrated one, and
 * repeatedly.
 */
const MIGRATIONS = [
  {
    id: '001_fetch_log_connection',
    up(db) {
      addColumn(db, 'fetch_log', 'connection', "TEXT NOT NULL DEFAULT ''");
      db.exec(`CREATE INDEX IF NOT EXISTS idx_fetch_log_identity
               ON fetch_log (source, site, connection, run_at)`);
    },
  },
  {
    id: '002_fetch_log_data_through',
    up(db) {
      addColumn(db, 'fetch_log', 'data_through', 'TEXT');
    },
  },
  {
    id: '003_sitemap_status_fields',
    up(db) {
      addColumn(db, 'gsc_sitemap', 'sitemap_count', 'INTEGER NOT NULL DEFAULT 0');
      addColumn(db, 'gsc_sitemap', 'errors', 'INTEGER NOT NULL DEFAULT 0');
      addColumn(db, 'gsc_sitemap', 'warnings', 'INTEGER NOT NULL DEFAULT 0');
      addColumn(db, 'gsc_sitemap', 'pending', 'INTEGER NOT NULL DEFAULT 0');
      addColumn(db, 'gsc_sitemap', 'last_downloaded', 'TEXT');
    },
  },
  {
    // Per-link affiliate clicks. On a database created before this table existed
    // the CREATE in SCHEMA already ran by the time migrations do — this records
    // that the schema step is done so future conditional steps can rely on it.
    id: '004_ga4_event_link',
    up(db) {
      db.exec(`CREATE TABLE IF NOT EXISTS ga4_event_link (
        site TEXT NOT NULL, property_id TEXT NOT NULL, date TEXT NOT NULL,
        event_name TEXT NOT NULL, link_url TEXT NOT NULL,
        event_count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (site, property_id, date, event_name, link_url)
      )`);
      db.exec(`CREATE INDEX IF NOT EXISTS idx_ga4_event_link_site_date
               ON ga4_event_link (site, date)`);
    },
  },
  {
    id: '005_ahrefs_snapshot',
    up(db) {
      db.exec(`CREATE TABLE IF NOT EXISTS ahrefs_snapshot (
        site TEXT NOT NULL, date TEXT NOT NULL,
        backlinks INTEGER NOT NULL DEFAULT 0,
        backlinks_dofollow INTEGER NOT NULL DEFAULT 0,
        backlinks_nofollow INTEGER NOT NULL DEFAULT 0,
        domain_rating REAL,
        PRIMARY KEY (site, date)
      )`);
    },
  },
  {
    // Geo and source/medium breakdowns of GA4 sessions. Additive: no existing table
    // is touched, and an older database gains two empty tables which the next fetch
    // backfills from their own anchor (see fetch.js — they must NOT inherit
    // ga4_daily's, or a site already current would never fetch a single day).
    id: '006_ga4_geo_source',
    up(db) {
      db.exec(`CREATE TABLE IF NOT EXISTS ga4_geo (
        site TEXT NOT NULL, property_id TEXT NOT NULL, date TEXT NOT NULL,
        country TEXT NOT NULL, country_id TEXT NOT NULL DEFAULT '',
        sessions INTEGER NOT NULL DEFAULT 0, active_users INTEGER NOT NULL DEFAULT 0,
        engaged_sessions INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (site, property_id, date, country)
      )`);
      db.exec(`CREATE INDEX IF NOT EXISTS idx_ga4_geo_site_date ON ga4_geo (site, date)`);
      db.exec(`CREATE TABLE IF NOT EXISTS ga4_source (
        site TEXT NOT NULL, property_id TEXT NOT NULL, date TEXT NOT NULL,
        source TEXT NOT NULL, medium TEXT NOT NULL,
        sessions INTEGER NOT NULL DEFAULT 0, active_users INTEGER NOT NULL DEFAULT 0,
        engaged_sessions INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (site, property_id, date, source, medium)
      )`);
      db.exec(`CREATE INDEX IF NOT EXISTS idx_ga4_source_site_date ON ga4_source (site, date)`);
    },
  },
  {
    id: '007_ahrefs_research',
    up(db) {
      addColumn(db, 'ahrefs_snapshot', 'refdomains', 'INTEGER');
      addColumn(db, 'ahrefs_snapshot', 'organic_keywords', 'INTEGER');
      addColumn(db, 'ahrefs_snapshot', 'organic_traffic', 'INTEGER');
      db.exec(`CREATE TABLE IF NOT EXISTS ahrefs_research_cache (
        cache_key TEXT PRIMARY KEY, site TEXT NOT NULL, kind TEXT NOT NULL,
        created_at TEXT NOT NULL, payload TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS ahrefs_research_spend (
        id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, units INTEGER NOT NULL
      );`);
    },
  },
];

/** Apply pending migrations. Returns the ids applied by this call. */
export function migrate(db) {
  db.exec(`CREATE TABLE IF NOT EXISTS schema_migrations (
    id TEXT PRIMARY KEY, applied_at TEXT NOT NULL)`);
  const done = new Set(db.prepare('SELECT id FROM schema_migrations').all().map((r) => r.id));
  const record = db.prepare('INSERT OR IGNORE INTO schema_migrations (id,applied_at) VALUES (?,?)');
  const applied = [];
  for (const m of MIGRATIONS) {
    if (done.has(m.id)) continue;
    db.transaction(() => {
      m.up(db);
      record.run(m.id, new Date().toISOString());
    })();
    applied.push(m.id);
  }
  return applied;
}

// --- Open / init -----------------------------------------------------------

export function openDb(path, { readonly = false } = {}) {
  mkdirSync(dirname(path), { recursive: true });
  const db = new Database(path, { readonly, fileMustExist: readonly });
  db.pragma('journal_mode = WAL');
  return db;
}

export function initDb(path) {
  const db = openDb(path);
  db.exec(SCHEMA);
  initCommerce(db);
  migrate(db);
  return db;
}

/** Insert rows in a single transaction. Returns the number of rows written. */
export function upsert(db, table, rows) {
  if (!rows || rows.length === 0) return 0;
  const stmt = db.prepare(UPSERTS[table]);
  const run = db.transaction((batch) => {
    for (const row of batch) stmt.run(row);
  });
  run(rows);
  return rows.length;
}

/**
 * Append a fetch attempt to the log.
 *
 * `connection` identifies which endpoint of a source this row describes (GA4 property
 * id, GSC property URL, WordPress origin). It defaults to '' for single-connection
 * sources and for legacy rows, and is part of the identity the health query groups on
 * — so two GA4 properties for one site stay two distinguishable rows.
 */
export function logFetch(db, entry) {
  db.prepare(
    `INSERT INTO fetch_log
       (run_at,source,site,connection,start_date,end_date,data_through,rows,status,message)
     VALUES (?,?,?,?,?,?,?,?,?,?)`,
  ).run(
    entry.runAt, entry.source, entry.site, entry.connection ?? '',
    entry.startDate ?? null, entry.endDate ?? null, entry.dataThrough ?? null,
    entry.rows ?? 0, entry.status, entry.message ?? null,
  );
}

/**
 * Most recent stored date — the incremental fetch anchor.
 *
 * `propertyId` scopes the anchor to one GA4 property. Without it, `MAX(date)` spans
 * every property for the site, so adding a second GA4 property to a site with
 * existing history would inherit the incumbent's anchor and never backfill.
 *
 * @param {string} table
 * @param {string} site
 * @param {string|null} propertyId only for tables with a property_id column
 */
export function latestDate(db, table, site, propertyId = null) {
  const where = ['site = ?'];
  const params = [site];
  if (propertyId != null) {
    where.push('property_id = ?');
    params.push(String(propertyId));
  }
  const row = db
    .prepare(`SELECT MAX(date) AS d FROM ${table} WHERE ${where.join(' AND ')}`)
    .get(...params);
  return row?.d || null;
}

export function hasAnyData(db) {
  try {
    const gsc = db.prepare('SELECT COUNT(*) AS n FROM gsc_daily').get().n;
    const ga4 = db.prepare('SELECT COUNT(*) AS n FROM ga4_daily').get().n;
    return gsc > 0 || ga4 > 0;
  } catch {
    return false;
  }
}
