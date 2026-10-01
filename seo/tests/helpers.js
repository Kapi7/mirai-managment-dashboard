/** Shared fixtures for the data-correctness tests. No Google API, no real DB. */
import { rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import * as db from '../server/db.js';
import { shiftDate } from '../server/reporting.js';

let counter = 0;

/** A throwaway on-disk SQLite database with the current schema applied. */
export function tempDb() {
  const path = join(tmpdir(), `mirai-test-${process.pid}-${Date.now()}-${counter++}.db`);
  const database = db.initDb(path);
  return {
    database,
    path,
    cleanup() {
      try { database.close(); } catch { /* already closed */ }
      for (const suffix of ['', '-wal', '-shm']) rmSync(path + suffix, { force: true });
    },
  };
}

/** A config-shaped site. Override only what a test cares about. */
export const makeSite = (over = {}) => {
  const primary = 'ga4PropertyId' in over ? over.ga4PropertyId : '100';
  const alt = over.ga4PropertyIdAlt ?? null;
  const ids = [primary, alt].filter(Boolean);
  return {
    slug: 'alpha',
    name: 'Alpha',
    vertical: 'Test',
    gscProperty: 'https://alpha.test/',
    wpOrigin: 'https://alpha.test',
    ...over,
    ga4PropertyId: primary,
    ga4PropertyIdAlt: alt,
    ga4PropertyIds: ids,
    ga4Properties: ids,
  };
};

/** Default per-source lag used by the tests, matching config defaults. */
export const LAG = { gsc: 3, ga4: 1, wordpress: 0, gsc_sitemap: 0, ahrefs: 0 };

/**
 * Seed `count` consecutive days of gsc_daily ending on `end` (inclusive).
 * `valueFor(dateIndexFromEnd, date)` returns { clicks, impressions, position }.
 */
export function seedGscDaily(database, site, end, count, valueFor = () => ({})) {
  for (let i = 0; i < count; i++) {
    const date = shiftDate(end, -i);
    const { clicks = 10, impressions = 100, position = 10 } = valueFor(i, date) || {};
    db.upsert(database, 'gsc_daily',
      [[site, date, clicks, impressions, impressions ? clicks / impressions : 0, position]]);
  }
}

/** Seed `count` days of ga4_daily for one property, ending on `end` (inclusive). */
export function seedGa4Daily(database, site, propertyId, end, count, valueFor = () => ({})) {
  for (let i = 0; i < count; i++) {
    const date = shiftDate(end, -i);
    const {
      channel = 'Organic Search', sessions = 10, activeUsers = 8,
      engagedSessions = 6, pageViews = 20, keyEvents = 1,
    } = valueFor(i, date) || {};
    db.upsert(database, 'ga4_daily',
      [[site, propertyId, date, channel, sessions, activeUsers, engagedSessions, pageViews, keyEvents]]);
  }
}

/** Seed `count` days of ga4_geo for one property and one country, ending on `end`. */
export function seedGa4Geo(database, site, propertyId, end, count, valueFor = () => ({})) {
  for (let i = 0; i < count; i++) {
    const date = shiftDate(end, -i);
    const {
      country = 'United States', countryId = 'US',
      sessions = 10, activeUsers = 8, engagedSessions = 6,
    } = valueFor(i, date) || {};
    db.upsert(database, 'ga4_geo',
      [[site, propertyId, date, country, countryId, sessions, activeUsers, engagedSessions]]);
  }
}

/** Seed `count` days of ga4_source for one property and one source/medium pair. */
export function seedGa4Source(database, site, propertyId, end, count, valueFor = () => ({})) {
  for (let i = 0; i < count; i++) {
    const date = shiftDate(end, -i);
    const {
      source = 'google', medium = 'organic',
      sessions = 10, activeUsers = 8, engagedSessions = 6,
    } = valueFor(i, date) || {};
    db.upsert(database, 'ga4_source',
      [[site, propertyId, date, source, medium, sessions, activeUsers, engagedSessions]]);
  }
}

export function seedGa4Event(database, site, propertyId, end, count, name, countFor = () => 1) {
  for (let i = 0; i < count; i++) {
    db.upsert(database, 'ga4_event',
      [[site, propertyId, shiftDate(end, -i), name, countFor(i)]]);
  }
}

/** A successful fetch_log row, so state resolution does not report `no_data`. */
export function logOk(database, source, site, connection, dataThrough) {
  db.logFetch(database, {
    runAt: new Date().toISOString(), source, site, connection,
    rows: 1, status: 'ok', dataThrough,
  });
}
