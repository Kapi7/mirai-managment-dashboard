import test from 'node:test';
import assert from 'node:assert/strict';
import * as db from '../server/db.js';
import { ROOT } from '../server/config.js';
import {
  buildDashboard, credentialSummary, dayIndex, isoOfDay, HISTORY_DAYS,
} from '../server/dashboard.js';
import {
  tempDb, makeSite, seedGscDaily, seedGa4Daily, seedGa4Event, logOk,
} from './helpers.js';

const cfgFor = (sites) => ({
  settings: { affiliateEvents: ['affiliate_click', 'outbound_click'] },
  credentials: { seogrid: { name: 'seogrid', kind: 'service_account', envVar: 'MIRAI_TEST_UNSET_KEY_PATH' } },
  sites,
});

test('day offsets round-trip through ISO dates', () => {
  assert.equal(dayIndex('2025-01-01'), 0);
  assert.equal(isoOfDay(dayIndex('2026-08-31')), '2026-08-31');
  assert.equal(dayIndex('2026-08-31T08:20:37.431Z'), dayIndex('2026-08-31'));
});

test('an empty database is reported as empty, not as zeros', () => {
  const t = tempDb();
  try {
    const out = buildDashboard(t.database, cfgFor([makeSite()]));
    assert.equal(out.empty, true);
    assert.deepEqual(out.sites, []);
  } finally { t.cleanup(); }
});

test('periods end on the last day every source delivered', () => {
  const t = tempDb();
  try {
    const site = makeSite();
    seedGscDaily(t.database, 'alpha', '2026-08-31', 10);
    seedGa4Daily(t.database, 'alpha', '100', '2026-09-02', 10);
    const out = buildDashboard(t.database, cfgFor([site]));
    assert.equal(out.empty, false);
    assert.equal(out.gscEnd, dayIndex('2026-08-31'));
    assert.equal(out.ga4End, dayIndex('2026-09-02'));
    assert.equal(out.end, dayIndex('2026-08-31'));
    assert.equal(out.minDay, dayIndex('2026-08-22'));
  } finally { t.cleanup(); }
});

test('GA4 rows come from the primary property only', () => {
  const t = tempDb();
  try {
    const site = makeSite({ ga4PropertyId: '100', ga4PropertyIdAlt: '200' });
    seedGscDaily(t.database, 'alpha', '2026-08-31', 3);
    seedGa4Daily(t.database, 'alpha', '100', '2026-08-31', 3, () => ({ sessions: 7 }));
    seedGa4Daily(t.database, 'alpha', '200', '2026-08-31', 3, () => ({ sessions: 1000 }));
    const [s] = buildDashboard(t.database, cfgFor([site])).sites;
    assert.equal(s.ga4, '100');
    assert.equal(s.a.length, 3);
    assert.equal(s.a.reduce((sum, r) => sum + r[2], 0), 21);
  } finally { t.cleanup(); }
});

test('only the configured affiliate events count as partner clicks', () => {
  const t = tempDb();
  try {
    seedGscDaily(t.database, 'alpha', '2026-08-31', 2);
    seedGa4Daily(t.database, 'alpha', '100', '2026-08-31', 2);
    seedGa4Event(t.database, 'alpha', '100', '2026-08-31', 2, 'affiliate_click', () => 2);
    seedGa4Event(t.database, 'alpha', '100', '2026-08-31', 2, 'outbound_click', () => 1);
    seedGa4Event(t.database, 'alpha', '100', '2026-08-31', 2, 'page_view', () => 50);
    const [s] = buildDashboard(t.database, cfgFor([makeSite()])).sites;
    assert.deepEqual(s.ev.map((r) => r[1]), [3, 3]);
  } finally { t.cleanup(); }
});

test('repeated strings are interned and page hosts are dropped', () => {
  const t = tempDb();
  try {
    seedGscDaily(t.database, 'alpha', '2026-08-31', 2);
    db.upsert(t.database, 'gsc_query', [
      ['alpha', '2026-08-30', 'sphinx slot', 1, 20, 0.05, 30],
      ['alpha', '2026-08-31', 'sphinx slot', 0, 17, 0, 34],
    ]);
    db.upsert(t.database, 'gsc_page', [['alpha', '2026-08-31', 'https://alpha.test/reviews/x/', 0, 5, 0, 12]]);
    const out = buildDashboard(t.database, cfgFor([makeSite()]));
    assert.deepEqual(out.queries, ['sphinx slot']);
    assert.deepEqual(out.sites[0].q.map((r) => r[1]), [0, 0]);
    // position × impressions travels so the page can weight averages exactly
    assert.equal(out.sites[0].q[0][4], 600);
    assert.deepEqual(out.pages, ['/reviews/x/']);
  } finally { t.cleanup(); }
});

test('history older than two years is left out of the payload', () => {
  const t = tempDb();
  try {
    seedGscDaily(t.database, 'alpha', '2026-08-31', 1);
    seedGscDaily(t.database, 'alpha', isoOfDay(dayIndex('2026-08-31') - HISTORY_DAYS - 5), 1);
    seedGa4Daily(t.database, 'alpha', '100', '2026-08-31', 1);
    const [s] = buildDashboard(t.database, cfgFor([makeSite()])).sites;
    assert.deepEqual(s.g.map((r) => r[0]), [dayIndex('2026-08-31')]);
  } finally { t.cleanup(); }
});

test('fetch status is the latest per source, with paths scrubbed', () => {
  const t = tempDb();
  try {
    seedGscDaily(t.database, 'alpha', '2026-08-31', 1);
    seedGa4Daily(t.database, 'alpha', '100', '2026-08-31', 1);
    logOk(t.database, 'ga4', 'alpha', '100', '2026-08-30');
    db.logFetch(t.database, { runAt: '2026-09-03T08:20:00.000Z', source: 'ga4', site: 'alpha', connection: '100',
      rows: 0, status: 'error', message: `Could not read ${ROOT}/data/cache.json` });
    const out = buildDashboard(t.database, cfgFor([makeSite()]));
    const ga4 = out.sites[0].fetch.ga4;
    assert.equal(ga4.status, 'error');
    assert.ok(!ga4.message.includes(ROOT), 'the project path must not leave the server');
  } finally { t.cleanup(); }
});

test('credentials are reported by name and status, never by path', () => {
  const sites = [makeSite({ slug: 'a', gscAuth: 'seogrid', ga4Auth: 'seogrid' }),
    makeSite({ slug: 'b', gscProperty: null, ga4Auth: 'seogrid' })];
  const [c] = credentialSummary(cfgFor(sites));
  assert.deepEqual(Object.keys(c).sort(), ['configured', 'envVar', 'ga4Sites', 'gscSites', 'kind', 'name']);
  assert.equal(c.configured, false);
  assert.deepEqual(c.gscSites, ['a']);
  assert.deepEqual(c.ga4Sites, ['a', 'b']);
});
