import test from 'node:test';
import assert from 'node:assert/strict';
import express from 'express';
import { registerAuthorityRoutes } from '../server/authority-routes.js';
import { tempDb, makeSite } from './helpers.js';

test('authority routes load saved reports without API calls, validate requests and serialize refreshes', async () => {
  const t = tempDb(), oldKey = process.env.MIRAI_SEO_AHREFS_API_KEY;
  process.env.MIRAI_SEO_AHREFS_API_KEY = 'test';
  const app = express(); app.use(express.json());
  let finish, received;
  const ops = registerAuthorityRoutes(app, { sites: [makeSite()], settings: { database: t.path } }, {
    refreshRunning: () => false,
    refresh: async input => { received = input; return new Promise(resolve => { finish = () => resolve({ failed: [], sourceAsOf: { ahrefs: '2026-10-01' } }); }); },
  });
  const server = app.listen(0, '127.0.0.1');
  await new Promise(resolve => server.on('listening', resolve));
  const base = 'http://127.0.0.1:' + server.address().port;
  const post = (input, headers = {}) => fetch(base + '/api/authority/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify(input) });
  try {
    const saved = await (await fetch(base + '/api/authority/research?site=alpha&country=us')).json();
    assert.equal(saved.discover, null); assert.equal(saved.configured, true);
    assert.equal((await post({ site: 'alpha' })).status, 403, 'cross-origin forms cannot trigger paid work');
    assert.equal((await post({ site: 'missing' }, { 'X-SEO-Request': '1' })).status, 400);
    const first = post({ site: 'alpha' }, { 'X-SEO-Request': '1' });
    while (!finish) await new Promise(resolve => setImmediate(resolve));
    assert.equal(ops.running(), true);
    assert.equal((await post({ site: 'alpha' }, { 'X-SEO-Request': '1' })).status, 409);
    finish(); assert.equal((await first).status, 200);
    assert.deepEqual(received, { site: 'alpha', source: 'ahrefs' });
    assert.equal(ops.running(), false);
  } finally {
    if (oldKey === undefined) delete process.env.MIRAI_SEO_AHREFS_API_KEY; else process.env.MIRAI_SEO_AHREFS_API_KEY = oldKey;
    server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); t.cleanup();
  }
});
