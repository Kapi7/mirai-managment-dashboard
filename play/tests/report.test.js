import test from 'node:test';
import assert from 'node:assert/strict';
import express from 'express';
import { readFileSync } from 'node:fs';
import { readPlayConfig, redact, WEBSITE_GA4_PROPERTY_IDS } from '../server/config.js';
import { aggregateGa4, aggregateInstallCsv, aggregateVitals, monthsInRange, reportRange } from '../server/normalize.js';
import { createPlayReport, createPlayRouter } from '../server/report.js';
import { SourceFailure } from '../server/sources.js';
import { formatCount, formatRate } from '../../src/features/play/model.js';

const NOW = () => new Date('2026-10-26T12:00:00Z');
const RANGE = { start: '2026-10-19', end: '2026-10-20' };
const CSV = `Date,Package Name,Country,Daily Device Installs,Daily Device Uninstalls,Daily User Installs,Daily User Uninstalls
2026-10-20,com.miraiskin.mobile,US,3,1,9,4
2026-10-20,com.miraiskin.mobile,US,3,1,9,4
2026-10-20,com.miraiskin.mobile,AU,2,0,8,0
2026-10-20,com.miraiskin.mobile,GB,0,0,7,0
2026-10-20,com.miraiskin.mobile,DE,4,2,4,2
2026-10-19,com.miraiskin.mobile,US,1,0,1,0
2026-09-01,com.miraiskin.mobile,US,100,0,100,0
2026-10-20,com.other.app,US,50,50,50,50
`;

function statPath(path) {
  if (path === '/keys/play.json' || path === '/keys/ga4.json') return 'file';
  if (path === '/exports') return 'dir';
  return null;
}

function keysOf(value, found = []) {
  if (value && typeof value === 'object') {
    for (const [key, child] of Object.entries(value)) {
      found.push(key);
      keysOf(child, found);
    }
  }
  return found;
}

test('website GA4 ids in this report match SEO config', () => {
  const yaml = readFileSync(new URL('../../seo/config/sites.yaml', import.meta.url), 'utf8');
  const ids = [...yaml.matchAll(/ga4_property_id:\s*'(\d+)'/g)].map(match => match[1]);
  assert.deepEqual(ids.sort(), [...WEBSITE_GA4_PROPERTY_IDS].sort());
});

test('missing credentials name the exact env vars and do not call a source', async () => {
  let called = false;
  const report = createPlayReport({
    env: {}, now: NOW, statPath, fetchImpl: () => { called = true; },
    ga4RunReport: () => { called = true; },
  });
  const body = await report({});
  assert.equal(called, false);
  assert.equal(body.status, 'not_configured');
  assert.equal(body.packageName, 'com.miraiskin.mobile');
  assert.equal(body.range.start, '2026-10-19');
  assert.equal(body.range.end, '2026-10-25');
  assert.match(body.sources.playInstalls.blocker, /PLAY_STATS_BUCKET/);
  assert.match(body.sources.playInstalls.blocker, /PLAY_STATS_DIR/);
  assert.match(body.sources.playVitals.blocker, /PLAY_GOOGLE_CREDENTIALS_PATH/);
  assert.match(body.sources.playVitals.blocker, /does not reuse the SEO OAuth token/);
  assert.match(body.sources.ga4App.blocker, /PLAY_GA4_PROPERTY_ID/);
  assert.match(body.sources.ga4App.blocker, /475812683/);
  assert.equal(body.totals.installs, null);
  assert.equal(body.totals.sessions, null);
  assert.equal(body.byCountry.find(row => row.code === 'IL').installs, null);
  assert.equal(keysOf(body).includes('credentialsPath'), false);
  assert.equal(keysOf(body).includes('statsDir'), false);
  assert.equal(keysOf(body).includes('bucket'), false);
});

test('a website GA4 property is rejected and not queried', async () => {
  let called = false;
  const report = createPlayReport({
    env: { PLAY_GA4_PROPERTY_ID: '475812683', GOOGLE_APPLICATION_CREDENTIALS: '/keys/ga4.json' },
    now: NOW, statPath, ga4RunReport: () => { called = true; },
  });
  const body = await report(RANGE);
  assert.equal(called, false);
  assert.equal(body.sources.ga4App.state, 'misconfigured');
  assert.match(body.sources.ga4App.blocker, /website GA4 property/);
  assert.equal(body.totals.sessions, null);
  assert.equal(body.status, 'misconfigured');
});

test('bucket and directory together are not read', async () => {
  let called = false;
  const config = readPlayConfig({
    PLAY_STATS_BUCKET: 'mirai-play', PLAY_STATS_DIR: '/exports', PLAY_GOOGLE_CREDENTIALS_PATH: '/keys/play.json',
  }, { statPath });
  assert.equal(config.sources.playInstalls.state, 'misconfigured');
  assert.match(config.sources.playInstalls.blocker, /only one/);
  const report = createPlayReport({
    env: { PLAY_STATS_BUCKET: 'mirai-play', PLAY_STATS_DIR: '/exports', PLAY_GOOGLE_CREDENTIALS_PATH: '/keys/play.json' },
    now: NOW, statPath, readDir: () => { called = true; return []; },
  });
  const body = await report(RANGE);
  assert.equal(called, false);
  assert.equal(body.totals.installs, null);
});

test('install export, vitals and GA4 stay in their own fields', async () => {
  const calls = [];
  const report = createPlayReport({
    env: {
      PLAY_STATS_DIR: '/exports',
      PLAY_GOOGLE_CREDENTIALS_PATH: '/keys/play.json',
      PLAY_GA4_PROPERTY_ID: '123456789',
    },
    now: NOW,
    statPath,
    readDir: async () => ['installs_com.miraiskin.mobile_202610_country.csv', 'installs_com.miraiskin.mobile_202609_country.csv', 'notes.txt'],
    readFile: async file => {
      assert.match(file, /202610_country\.csv$/);
      return CSV;
    },
    tokenProvider: async () => 'test-token',
    fetchImpl: async (url, init) => {
      calls.push({ url: String(url), body: init.body, authorization: init.headers.Authorization });
      const href = String(url);
      const json = payload => ({ ok: true, status: 200, text: async () => JSON.stringify(payload), json: async () => payload });
      if (href.includes('errorCountMetricSet')) {
        return json({ rows: [
          errorRow(20, 'US', 'CRASH', 2),
          errorRow(20, 'IL', 'ANR', 1),
          errorRow(20, 'DE', 'CRASH', 5),
          errorRow(20, 'US', 'NON_FATAL', 8),
          errorRow(21, 'US', 'CRASH', 9),
        ] });
      }
      if (href.includes('crashRateMetricSet')) {
        return json({ rows: [rateRow(19, 'userPerceivedCrashRate', '0.5'), rateRow(20, 'userPerceivedCrashRate', '0.25'), rateRow(21, 'userPerceivedCrashRate', '0.9')] });
      }
      if (href.includes('anrRateMetricSet')) return json({ rows: [rateRow(20, 'userPerceivedAnrRate', '0.01')] });
      throw new Error(`unexpected ${href}`);
    },
    ga4RunReport: async ({ propertyId, request }) => {
      assert.equal(propertyId, '123456789');
      const dims = (request.dimensions || []).map(item => item.name).join(',');
      if (!dims) return ga4Table([], ['sessions', 'activeUsers'], [{ sessions: '10', activeUsers: '4' }]);
      if (dims === 'date') return ga4Table(['date'], ['activeUsers'], [{ date: '20261019', activeUsers: '2' }, { date: '20261020', activeUsers: '3' }]);
      if (dims === 'countryId') return ga4Table(['countryId'], ['sessions', 'activeUsers'], [
        { countryId: 'US', sessions: '6', activeUsers: '4' },
        { countryId: 'AU', sessions: '1', activeUsers: '1' },
        { countryId: 'FR', sessions: '3', activeUsers: '2' },
      ]);
      if (dims === 'countryId,eventName') return ga4Table(['countryId', 'eventName'], ['eventCount'], [
        { countryId: 'US', eventName: 'first_open', eventCount: '6' },
        { countryId: 'FR', eventName: 'first_open', eventCount: '1' },
        { countryId: 'US', eventName: 'app_remove', eventCount: '1' },
      ]);
      throw new Error(dims);
    },
  });
  const body = await report(RANGE);
  assert.equal(body.status, 'ready');
  assert.equal(body.totals.installs, 10);
  assert.equal(body.totals.uninstalls, 3);
  assert.equal(body.byCountry.find(row => row.code === 'US').installs, 4);
  assert.equal(body.byCountry.find(row => row.code === 'GB').installs, 0);
  assert.equal(body.byCountry.find(row => row.code === 'IL').installs, null);
  assert.equal(body.byCountry.find(row => row.code === 'OTHER').installs, 4);
  assert.equal(body.totals.crashes, 7);
  assert.equal(body.totals.anrs, 1);
  assert.equal(body.byCountry.find(row => row.code === 'IL').anrs, 1);
  assert.equal(body.totals.crashRate, 0.25);
  assert.equal(body.totals.crashRateDate, '2026-10-20');
  assert.equal(body.totals.sessions, 10);
  assert.equal(body.totals.activeUsers, 4);
  assert.equal(body.totals.latestDayActiveUsers, 3);
  assert.notEqual(body.totals.latestDayActiveUsers, 5);
  assert.equal(body.totals.firstOpen, 7);
  assert.equal(body.totals.appRemove, 1);
  assert.equal(body.totals.installs === body.totals.firstOpen, false);
  assert.equal(body.byCountry.find(row => row.code === 'US').firstOpen, 6);
  assert.equal(body.byCountry.find(row => row.code === 'OTHER').sessions, 3);
  assert.equal(body.byCountry.find(row => row.code === 'OTHER').activeUsers, null);
  assert.equal(JSON.stringify(body).includes('test-token'), false);
  assert.equal(JSON.stringify(body).includes('/keys/play.json'), false);
  assert.equal(JSON.stringify(body).includes('/exports'), false);
  const crashCall = calls.find(call => call.url.includes('crashRateMetricSet'));
  const sent = JSON.parse(crashCall.body);
  assert.equal(sent.timelineSpec.endTime.day, 21);
  assert.equal(sent.timelineSpec.startTime.day, 19);
});

test('a Play stats bucket download does not echo the token or bucket', async () => {
  const seen = [];
  const report = createPlayReport({
    env: { PLAY_STATS_BUCKET: 'mirai-play-stats', PLAY_GOOGLE_CREDENTIALS_PATH: '/keys/play.json' },
    now: NOW,
    statPath,
    tokenProvider: async ({ scopes }) => {
      assert.ok(scopes.includes('https://www.googleapis.com/auth/devstorage.read_only'));
      return 'bucket-token';
    },
    fetchImpl: async (url, init) => {
      seen.push(String(url));
      assert.equal(init.headers.Authorization, 'Bearer bucket-token');
      if (String(url).includes('prefix=')) {
        return { ok: true, status: 200, text: async () => JSON.stringify({ items: [
          { name: 'stats/installs/installs_com.miraiskin.mobile_202610_country.csv' },
          { name: 'stats/installs/installs_com.miraiskin.mobile_202610_overview.csv' },
        ] }) };
      }
      assert.match(String(url), /alt=media/);
      return { ok: true, status: 200, text: async () => 'Date,Country,Daily Device Installs,Daily Device Uninstalls\n2026-10-20,CA,2,1\n' };
    },
  });
  const body = await report(RANGE);
  assert.equal(body.sources.playInstalls.state, 'ok');
  assert.equal(body.totals.installs, 2);
  assert.equal(body.byCountry.find(row => row.code === 'CA').uninstalls, 1);
  assert.equal(body.byCountry.find(row => row.code === 'US').installs, null);
  assert.equal(JSON.stringify(body).includes('bucket-token'), false);
  assert.equal(JSON.stringify(body).includes('mirai-play-stats'), false);
  assert.equal(seen.some(url => url.includes('overview')), false);
});

test('conflicting install rows and non-code countries hide totals', () => {
  const conflict = aggregateInstallCsv([
    'Date,Country,Daily Device Installs,Daily Device Uninstalls\n2026-10-20,US,1,0\n2026-10-20,US,2,0\n',
  ], { ...RANGE, packageName: 'com.miraiskin.mobile' });
  assert.match(conflict.error, /conflicting rows/);
  const named = aggregateInstallCsv([
    'Date,Country,Daily Device Installs,Daily Device Uninstalls\n2026-10-20,United States,1,0\n',
  ], { ...RANGE, packageName: 'com.miraiskin.mobile' });
  assert.match(named.error, /2-letter codes/);
});

test('vitals truncation and GA4 partial pages are not summed', () => {
  const truncated = aggregateVitals({ errorRows: [errorRow(20, 'US', 'CRASH', 2)], start: RANGE.start, end: RANGE.end, complete: false });
  assert.match(truncated.error, /partial page/);
  assert.throws(() => aggregateGa4({
    rangeResponse: ga4Table([], ['sessions', 'activeUsers'], [{ sessions: '1', activeUsers: '1' }]),
    dailyResponse: { ...ga4Table(['date'], ['activeUsers'], [{ date: '20261020', activeUsers: '1' }]), rowCount: 9 },
    countryResponse: ga4Table(['countryId'], ['sessions', 'activeUsers'], []),
    eventResponse: ga4Table(['countryId', 'eventName'], ['eventCount'], []),
    ...RANGE,
  }), /partial result/);
});

test('date windows reject the future and cross months', () => {
  assert.throws(() => reportRange({ start: '2026-10-27', end: '2026-10-27' }, NOW()), RangeError);
  assert.throws(() => reportRange({ start: '2026-10-20', end: '2026-10-19' }, NOW()), RangeError);
  assert.deepEqual(monthsInRange('2026-12-30', '2027-01-02'), ['202612', '202701']);
});

test('upstream secrets do not reach the client', async () => {
  const report = createPlayReport({
    env: { PLAY_GOOGLE_CREDENTIALS_PATH: '/keys/play.json' },
    now: NOW,
    statPath,
    tokenProvider: async () => { throw new SourceFailure('denied ya29.abcDEF-123 for /keys/play.json'); },
    fetchImpl: async () => { throw new Error('should not matter'); },
  });
  const body = await report(RANGE);
  assert.equal(body.sources.playVitals.state, 'error');
  assert.match(body.sources.playVitals.blocker, /\[redacted\]/);
  assert.equal(body.sources.playVitals.blocker.includes('ya29'), false);
  assert.equal(body.sources.playVitals.blocker.includes('/keys/play.json'), false);
  assert.equal(body.totals.crashes, null);
  assert.equal(redact('ya29.abc'), '[redacted]');
});

test('the production router requires authentication and hides private failures', async t => {
  let reads = 0;
  const app = express();
  app.use('/private', createPlayRouter({ report: async () => { reads += 1; return { ok: true }; } }));
  app.use('/failure', createPlayRouter({ authorize: (_req, _res, next) => next(), report: async () => { throw new Error('ya29.secretTOKEN'); } }));
  app.use('/dates', createPlayRouter({ authorize: (_req, _res, next) => next(), report: async () => ({}) }));
  const server = app.listen(0, '127.0.0.1');
  await new Promise(resolve => server.once('listening', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const base = `http://127.0.0.1:${server.address().port}`;
  const denied = await fetch(`${base}/private`);
  assert.equal(denied.status, 401);
  assert.equal(reads, 0);
  assert.equal(denied.headers.get('cache-control'), 'no-store');
  const failure = await fetch(`${base}/failure`);
  assert.equal(failure.status, 502);
  assert.equal((await failure.text()).includes('ya29'), false);
  const invalid = await fetch(`${base}/dates?start=nope&end=2026-10-20`);
  assert.equal(invalid.status, 400);
});

test('counts stay blank until a real number exists', () => {
  assert.equal(formatCount(null), '—');
  assert.equal(formatCount(undefined), '—');
  assert.equal(formatCount(0), '0');
  assert.equal(formatCount(1000), '1,000');
  assert.equal(formatRate(0.25), '25.00%');
  assert.equal(formatRate(null), null);
});

function errorRow(day, country, type, count) {
  return {
    startTime: { year: 2026, month: 10, day },
    dimensions: [
      { dimension: 'countryCode', stringValue: country },
      { dimension: 'reportType', stringValue: type },
    ],
    metrics: [{ metric: 'errorReportCount', decimalValue: { value: String(count) } }],
  };
}

function rateRow(day, metric, value) {
  return {
    startTime: { year: 2026, month: 10, day },
    metrics: [{ metric, decimalValue: { value } }],
  };
}

function ga4Table(dimensions, metrics, rows) {
  return {
    dimensionHeaders: dimensions.map(name => ({ name })),
    metricHeaders: metrics.map(name => ({ name })),
    rowCount: rows.length,
    rows: rows.map(row => ({
      dimensionValues: dimensions.map(name => ({ value: row[name] })),
      metricValues: metrics.map(name => ({ value: String(row[name]) })),
    })),
  };
}
