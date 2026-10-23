import test from 'node:test';
import assert from 'node:assert/strict';
import express from 'express';
import { createAttributionRouter, createReportService, channelFor, normalizeReport, reconcileRows, parseTable, reportRange, SourceError } from '../server/report.js';
import { buildView, csvCell, exportCsv, trend } from '../../src/features/attribution/model.js';

const range = reportRange({ start: '2026-10-01', end: '2026-10-02' }, new Date('2026-10-23'));
const session = (day, country, count, converted) => ({ day, referring_channel: 'google', traffic_type: 'organic', session_country: country, session_country_code: country, sessions: String(count), sessions_that_completed_checkout: String(converted) });
const sale = (day, country, count, amount, type = 'New') => ({ day, referring_channel: 'google', traffic_type: 'organic', shipping_country: country, shipping_country_code: country, orders: String(count), net_sales: String(amount), new_or_returning_customer: type, sales_channel: 'Online Store' });
const report = { range, currency: 'USD', timezone: 'Asia/Jerusalem', rows: normalizeReport([
  session('2026-10-01', 'US', 100, 10), session('2026-10-02', 'CA', 900, 9), session('2026-09-29', 'US', 20, 1), session('2026-09-30', 'GB', 10, 1),
], [sale('2026-10-01', 'US', 9, 900), sale('2026-10-02', 'CA', 3, 450, 'Returning'), sale('2026-10-02', 'US', 0, -40), sale('2026-09-30', 'GB', 1, 100)], range) };

test('inclusive comparisons cross months and reject invalid, future and oversized ranges', () => {
  assert.equal(range.days, 2); assert.equal(range.previousStart, '2026-09-29'); assert.equal(range.previousEnd, '2026-09-30');
  for (const query of [{ start: '2026-02-30', end: '2026-03-01' }, { start: '2026-10-02', end: '2026-10-01' }, { start: '2026-10-01', end: '2027-01-01' }, { start: '2026-01-01', end: '2026-10-01' }, { start: ['2026-10-01'], end: '2026-10-02' }, { comparison: 'arbitrary' }]) assert.throws(() => reportRange(query, new Date('2026-10-23')));
  assert.equal(reportRange({ start: '2024-02-29', end: '2024-03-01' }, new Date('2026-10-23')).days, 2);
});

test('weighted conversion uses converted sessions; sales reversals and repeat orders remain additive', () => {
  const view = buildView(report);
  assert.equal(view.current.sessions, 1000);
  assert.equal(view.current.orders, 12);
  assert.equal(view.current.conversion, 19 / 1000);
  assert.equal(view.current.amount, 1310);
  assert.equal(view.current.returningOrders, 3);
  assert.equal(view.daily[0].previous.sessions, 20);
  assert.equal(view.daily[1].previous.orders, 1);
  const priorOnly = view.children[0].children.find(row => row.countryCode === 'GB');
  assert.equal(priorOnly.current.orders, 0); assert.equal(priorOnly.previous.orders, 1);
});

test('both drilldown directions and simultaneous filters reconcile to their totals', () => {
  for (const group of ['channel', 'country']) {
    const view = buildView(report, { group, country: 'US', channel: 'Google · Organic' });
    assert.equal(view.current.orders, 9); assert.equal(view.current.amount, 860);
    assert.equal(view.previous.sessions, 20);
    assert.equal(view.children.reduce((total, row) => total + row.current.amount, 0), view.current.amount);
    assert.equal(view.children.flatMap(row => row.children).reduce((total, row) => total + row.current.sessions, 0), view.current.sessions);
  }
  assert.equal(buildView(report, { country: 'ZZ' }).children.length, 0);
});

test('Shop sales stay separate and missing attribution is not guessed', () => {
  assert.equal(channelFor({ referring_channel: null }), 'Unattributed');
  assert.equal(channelFor({ sales_channel: 'Shop', referring_channel: 'google', traffic_type: 'paid' }, true), 'Shop');
  assert.equal(channelFor({ referring_channel: 'direct' }), 'Direct');
  const rows = normalizeReport([], [{ ...sale('2026-10-01', 'US', 1, 50), sales_channel: 'Shop' }], range);
  const view = buildView({ ...report, rows });
  assert.equal(view.current.conversion, null);
  assert.equal(view.current.orders, 1);
});

test('zero baselines, zero sessions, flat trends and percentage point changes are honest', () => {
  assert.deepEqual(trend(2, 0), { direction: 'up', text: 'New' });
  assert.deepEqual(trend(0, 0), { direction: 'neutral', text: '0%' });
  assert.deepEqual(trend(null, 0.1, true), { direction: 'neutral', text: '—' });
  assert.deepEqual(trend(0.02, 0.01, true), { direction: 'up', text: '+1.00 pp' });
  assert.deepEqual(trend(0, 5), { direction: 'down', text: '-100.0%' });
});

test('CSV is filtered, excludes duplicate totals and escapes malicious channel values', () => {
  const view = buildView(report, { country: 'US' });
  const csv = exportCsv(view, report, 'channel');
  assert.equal(csv.split('\r\n').length, 2);
  assert.ok(csv.includes('"860"')); assert.ok(csv.includes('"Asia/Jerusalem"'));
  assert.equal(csvCell('=HYPERLINK("bad")'), '"\'=HYPERLINK(""bad"")"');
  assert.equal(csvCell('a,"b"'), '"a,""b"""');
  assert.equal(csvCell('  =1+1'), '"\'  =1+1"');
  assert.equal(csvCell(-40), '"-40"');
});

test('upstream errors, missing columns, row limits and malformed metrics fail closed', () => {
  const body = { data: { shopifyqlQuery: { tableData: { columns: [{ name: 'orders' }], rows: [{ orders: '1' }] }, parseErrors: [] } } };
  assert.equal(parseTable(body, ['orders']).rows.length, 1);
  assert.throws(() => parseTable({ errors: [{ message: 'private error' }] }, []), SourceError);
  assert.throws(() => parseTable({ data: { shopifyqlQuery: { parseErrors: ['bad'] } } }, []), SourceError);
  assert.throws(() => parseTable(body, ['sessions']), SourceError);
  assert.throws(() => parseTable({ data: { shopifyqlQuery: { tableData: { columns: [], rows: Array(100000).fill({}) } } } }, []), SourceError);
  assert.throws(() => normalizeReport([{ ...session('2026-10-01', 'US', 1, 0), sessions: null }], [], range), SourceError);
});

test('concurrent requests deduplicate and expired cache refreshes without retaining failed data', async () => {
  let calls = 0;
  let time = new Date('2026-10-23T10:00:00Z');
  const service = createReportService({ now: () => time, client: async () => { calls++; return { rows: [], shop: { currencyCode: 'USD', ianaTimezone: 'Asia/Jerusalem' } }; } });
  const query = { start: range.start, end: range.end };
  const [a, b] = await Promise.all([service(query), service(query)]);
  assert.equal(calls, 4); assert.equal(a, b);
  await service(query); assert.equal(calls, 4);
  time = new Date('2026-10-23T10:06:00Z'); await service(query); assert.equal(calls, 8);
  const failure = createReportService({ client: async () => { throw new Error('secret token'); } });
  await assert.rejects(failure(query)); await assert.rejects(failure(query));
});

test('missing detail is explicit and reconciles to daily source totals without guessing attribution', () => {
  const details = normalizeReport([session('2026-10-01', 'US', 99, 3)], [sale('2026-10-01', 'US', 3, 100)], range);
  const rows = reconcileRows(details, [{ day: '2026-10-01', sessions: '100', sessions_that_completed_checkout: '3' }], [{ day: '2026-10-01', orders: '3', net_sales: '100', new_or_returning_customer: 'New' }], range);
  const residual = rows.find(row => row.unallocated);
  assert.equal(residual.sessions, 1); assert.equal(residual.countryCode, ''); assert.equal(residual.channel, 'Unallocated detail');
  assert.equal(buildView({ ...report, rows }).current.sessions, 100);
  assert.throws(() => reconcileRows(details, [{ day: '2026-10-01', sessions: '98', sessions_that_completed_checkout: '3' }], [], range), /revising/);
});

test('the production router requires authentication and suppresses private upstream errors', async t => {
  let reads = 0;
  const app = express();
  app.use('/private', createAttributionRouter({ report: async () => { reads++; return {}; } }));
  app.use('/failure', createAttributionRouter({ authorize: (_req, _res, next) => next(), report: async () => { throw new Error('secret access token'); } }));
  const server = app.listen(0, '127.0.0.1');
  await new Promise(resolve => server.once('listening', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const base = `http://127.0.0.1:${server.address().port}`;
  const denied = await fetch(`${base}/private`); assert.equal(denied.status, 401); assert.equal(reads, 0); assert.equal(denied.headers.get('cache-control'), 'no-store');
  const invalid = await fetch(`${base}/failure?start=invalid`); assert.equal(invalid.status, 400);
  const failure = await fetch(`${base}/failure`); assert.equal(failure.status, 502); assert.ok(!(await failure.text()).includes('secret'));
});
