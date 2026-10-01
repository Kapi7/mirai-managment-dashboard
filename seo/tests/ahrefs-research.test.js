import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { tempDb, makeSite } from './helpers.js';
import { migrate, upsert } from '../server/db.js';
import { batchMetrics, limitsAndUsage, requireAllowance, BudgetExceeded } from '../server/ahrefs.js';
import { validateResearch, runResearch, savedResearch, budgetStatus, safeUrl } from '../server/ahrefs-research.js';
const now = new Date('2026-10-01T12:00:00Z');
const site = makeSite(), cfg = { sites: [site] };
const params = (kind = 'gap') => validateResearch({ site: 'alpha', country: 'us', kind, competitors: ['rival.test'] }, cfg);
const usage = async () => ({ remaining: 50000 });
const row = (keyword, best_position = 3) => ({ keyword, best_position, best_position_url: `https://rival.test/${keyword}`, volume: 0, keyword_difficulty: 0 });

test('extended authority preserves measured zero and nullable metrics', async () => {
  const rows = await batchMetrics([site], { apiKey: 'test', extended: true, now,
    fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({ targets: [{ index: 0, backlinks: 0, backlinks_dofollow: 0, backlinks_nofollow: 0, domain_rating: null, refdomains: 0, org_keywords: 0, org_traffic: null }] }) }) });
  assert.deepEqual(rows, [['alpha', '2026-10-01', 0, 0, 0, null, 0, 0, null]]);
  await assert.rejects(batchMetrics([site], { apiKey: 'test', fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({ targets: [{ index: 0, domain_rating: 4 }] }) }) }), /incomplete backlink/);
});
test('allowance is the lower of key and workspace remaining; missing workspace is unverified', async () => {
  const get = limits => limitsAndUsage({ apiKey: 'test', fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({ limits_and_usage: limits }) }) });
  assert.equal((await get({ units_usage_api_key: 30, units_limit_api_key: 100, units_usage_workspace: 50, units_limit_workspace: 500 })).remaining, 70);
  assert.equal((await get({ units_usage_api_key: 30, units_limit_api_key: null, units_usage_workspace: 50, units_limit_workspace: 500 })).remaining, 450);
  const missing = await get({ units_usage_api_key: 0 });
  assert.equal(missing.remaining, null); assert.throws(() => requireAllowance(missing, 50), BudgetExceeded);
  assert.throws(() => requireAllowance({}, 50), BudgetExceeded);
});
test('research validates configured sites, markets and at most three public domain inputs', () => {
  for (const input of [{ site: 'other' }, { site: 'alpha', country: 'xx' }, { site: 'alpha', kind: 'gap', competitors: ['localhost'] }, { site: 'alpha', kind: 'gap', competitors: ['alpha.test'] }, { site: 'alpha', kind: 'gap', competitors: ['a.test', 'b.test', 'c.test', 'd.test'] }]) assert.throws(() => validateResearch(input, cfg));
  assert.equal(safeUrl('javascript:alert(1)'), null);
  assert.throws(() => validateResearch({ site: 'alpha', kind: 'gap', competitors: ['www.alpha.test'] }, cfg));
});
test('gap checks every sampled keyword on target, excludes existing top ten, preserves zero estimates', async () => {
  const t = tempDb(), calls = [];
  try {
    const result = await runResearch(t.database, params(), { now, usage, client: async (path, options) => {
      calls.push(options.params); options.onCost(50);
      return options.params.target === 'rival.test' ? { keywords: [row('missing'), row('weak'), row('strong')] } : { keywords: [row('weak', 17), row('strong', 4)] };
    } });
    assert.deepEqual(result.rows.map(r => [r.keyword, r.kind, r.targetPosition]), [['missing', 'missing', null], ['weak', 'weak', 17]]);
    assert.equal(result.rows[0].volume, 0); assert.equal(result.rows[0].difficulty, 0);
    assert.equal(result.sampledKeywords, 3); assert.equal(result.units, 100);
    assert.equal(calls[0].date, calls[1].date); assert.equal(calls[1].country, 'us');
    assert.deepEqual(JSON.parse(calls[1].where).or.map(x => x.is[1]), ['missing', 'weak', 'strong']);
    assert.equal(calls[1].limit, 3);
    const cached = await runResearch(t.database, params(), { now, usage: () => { throw Error('must not query allowance on cache hit'); } });
    assert.equal(cached.cached, true); assert.equal(budgetStatus(t.database, now).used, 100);
    assert.equal(savedResearch(t.database, 'alpha', 'gb', now).gap, null);
  } finally { t.cleanup(); }
});
test('quota and local research budget block paid calls', async () => {
  const t = tempDb(); let calls = 0;
  try {
    const client = async () => { calls++; throw Error('should not run'); };
    await assert.rejects(runResearch(t.database, params(), { now, usage: async () => ({ remaining: 0 }), client }), BudgetExceeded);
    t.database.prepare('INSERT INTO ahrefs_research_spend(created_at,units) VALUES (?,?)').run(now.toISOString(), 10000);
    await assert.rejects(runResearch(t.database, params(), { now, usage, client }), BudgetExceeded);
    assert.equal(calls, 0);
  } finally { t.cleanup(); }
});
test('failed target verification never saves false missing-keyword conclusions and retains spend', async () => {
  const t = tempDb(); let n = 0;
  try {
    await assert.rejects(runResearch(t.database, params(), { now, usage, client: async () => ++n === 1 ? { keywords: [row('one')] } : { error: 'broken' } }), /invalid keyword/);
    assert.equal(savedResearch(t.database, 'alpha', 'us', now).gap, null);
    assert.equal(budgetStatus(t.database, now).used, 770, 'unknown cost is conservatively accounted');
  } finally { t.cleanup(); }
});
test('discovery cache expires after seven days and returns only validated domains', async () => {
  const t = tempDb(); let calls = 0;
  try {
    const client = async (_, o) => { calls++; o.onCost(50); return { competitors: [{ competitor_domain: 'rival.test', domain_rating: 0, keywords_common: 0, keywords_competitor: 12 }, { competitor_domain: '<script>' }] }; };
    const first = await runResearch(t.database, params('discover'), { now, usage, client });
    assert.equal(first.competitors.length, 1); assert.equal(first.competitors[0].dr, 0);
    await runResearch(t.database, params('discover'), { now: new Date('2026-10-09'), usage, client }); assert.equal(calls, 2);
  } finally { t.cleanup(); }
});
test('additive migration preserves historical snapshots and null extended readings', () => {
  const t = tempDb();
  try {
    upsert(t.database, 'ahrefs_snapshot', [['alpha', '2026-09-01', 9, 8, 1, 2.2]]);
    t.database.prepare("DELETE FROM schema_migrations WHERE id='007_ahrefs_research'").run();
    migrate(t.database); migrate(t.database);
    const r = t.database.prepare('SELECT * FROM ahrefs_snapshot').get();
    assert.equal(r.domain_rating, 2.2); assert.equal(r.backlinks, 9); assert.equal(r.refdomains, null);
  } finally { t.cleanup(); }
});
test('current authority includes snapshots newer than the delayed Google window, with zero DR intact', () => {
  const ctx = vm.createContext({ D: { epoch: '2026-01-01', end: 270, minDay: 0, channels: [], sources: [], sites: [] }, URL, localStorage: { getItem: () => '{}' }, document: { addEventListener() {} } });
  vm.runInContext(readFileSync(new URL('../web/family/src/core.js', import.meta.url), 'utf8') + readFileSync(new URL('../web/family/src/authority.js', import.meta.url), 'utf8'), ctx);
  assert.equal(vm.runInContext("currentAh({ah:[['2026-10-01',0,2,1,1,0,0]]})[1]", ctx), 0);
  assert.equal(vm.runInContext("drText(null)", ctx), '—');
  assert.equal(vm.runInContext("drText(0)", ctx), '0.0');
  assert.equal(vm.runInContext("externalLink('javascript:alert(1)', '<script>')", ctx), '&lt;script&gt;');
});
test('search-result discovery sends only explicitly supplied terms and labels the evidence', async () => {
  const t = tempDb(); const requests = [];
  try {
    assert.throws(() => validateResearch({ site: 'alpha', kind: 'serp' }, cfg), /Enter one to three/);
    const p = validateResearch({ site: 'alpha', kind: 'serp', seedKeywords: ['public topic', 'second topic'] }, cfg);
    const r = await runResearch(t.database, p, { now, usage, client: async (path, options) => {
      requests.push({ path, ...options.params }); options.onCost(50);
      return { positions: [{ url: 'https://rival.test/page', position: 3, domain_rating: 0 }, { url: 'https://alpha.test/page', position: 1, domain_rating: 4 }, { url: 'javascript:alert(1)', position: 2 }] };
    } });
    assert.deepEqual(requests.map(x => x.keyword), ['public topic', 'second topic']);
    assert.equal(r.units, 100); assert.equal(r.competitors.length, 1);
    assert.deepEqual(r.competitors[0].seeds, ['public topic', 'second topic']);
    assert.equal(r.competitors[0].common, null, 'sampled results never masquerade as organic-overlap counts');
  } finally { t.cleanup(); }
});

test('CSV export retains numeric values and neutralizes spreadsheet formulas including leading whitespace', async () => {
  let blob, download, clicked = false;
  const url = { createObjectURL: value => { blob = value; return 'blob:test'; }, revokeObjectURL() {} };
  const context = vm.createContext({ URL: url, Blob, setTimeout() {}, document: { addEventListener() {}, createElement: () => ({ set download(v) { download = v; }, click() { clicked = true; } }) } });
  vm.runInContext(readFileSync(new URL('../web/family/src/authority.js', import.meta.url), 'utf8'), context);
  const report = { site: 'alpha', country: 'us', date: '2026-09-29', rows: [{ keyword: ' \t=1+1', volume: 0, difficulty: null, targetPosition: null, targetUrl: null, competitors: [{ domain: 'rival.test', position: 3 }], action: 'Check page coverage' }] };
  context.report = report;
  vm.runInContext('AUTH.data = {gap:report}; exportGap();', context);
  assert.equal(clicked, true); assert.equal(download, 'alpha-us-content-gaps-2026-09-29.csv');
  const csv = await blob.text();
  assert.ok(csv.includes('"\' \t=1+1","0",""'), 'formulas get a leading apostrophe; zero and unknown remain distinct');
  assert.equal(csv.split('\r\n').length, 2);
});

test('partial parallel failure waits for outstanding costs and preserves the previous report', async () => {
  const t = tempDb(); let completed = false;
  try {
    const p = validateResearch({ site: 'alpha', kind: 'gap', competitors: ['a.test', 'b.test'] }, cfg);
    await assert.rejects(runResearch(t.database, p, { now, usage, client: async (_, o) => {
      if (o.params.target === 'a.test') throw Error('provider failed');
      await new Promise(resolve => setImmediate(resolve));
      o.onCost(50); completed = true;
      return { keywords: [row('one')] };
    } }), /provider failed/);
    assert.equal(completed, true, 'the operation stays active until all in-flight requests settle');
    assert.equal(budgetStatus(t.database, now).used, 770);
    assert.equal(savedResearch(t.database, 'alpha', 'us', now).gap, null);
  } finally { t.cleanup(); }
});
