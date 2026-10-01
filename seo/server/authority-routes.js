import { existsSync } from 'node:fs';
import { openDb } from './db.js';
import { redactPaths } from './config.js';
import { credentialStatus, limitsAndUsage, AccessDenied, BudgetExceeded, AhrefsUnavailable, PROFILE_UNITS_PER_SITE } from './ahrefs.js';
import { validateResearch, savedResearch, runResearch, DISCOVERY_UNITS, GAP_UNITS_PER_COMPETITOR, CACHE_DAYS } from './ahrefs-research.js';

export function registerAuthorityRoutes(app, cfg, { refresh, refreshRunning, mutate = operation => operation() }) {
  let running = false;
  const failure = (res, error) => {
    const known = error instanceof AccessDenied || error instanceof BudgetExceeded || error instanceof AhrefsUnavailable;
    return res.status(error instanceof BudgetExceeded ? 409 : error instanceof AccessDenied ? 403 : 502).json({
      error: error instanceof BudgetExceeded ? 'budget_limit' : error instanceof AccessDenied ? 'no_access' : 'error',
      message: known ? redactPaths(error.message) : 'The Ahrefs operation could not complete. Existing data was preserved.',
    });
  };
  app.get('/api/authority/research', (req, res) => {
    let params;
    try { params = validateResearch({ ...req.query, kind: 'discover' }, cfg); } catch (e) { return res.status(400).json({ error: 'invalid_input', message: e.message }); }
    if (!existsSync(cfg.settings.database)) return res.status(503).json({ error: 'no_database', message: 'Run the first data fetch before research.' });
    const db = openDb(cfg.settings.database, { readonly: true });
    try { res.set('Cache-Control', 'no-store').json({ configured: credentialStatus().configured,
      ...savedResearch(db, params.site.slug, params.country), costs: { discover: DISCOVERY_UNITS, gapPerCompetitor: GAP_UNITS_PER_COMPETITOR, cacheDays: CACHE_DAYS, refresh: Math.max(50, PROFILE_UNITS_PER_SITE) } });
    } finally { db.close(); }
  });
  app.get('/api/authority/allowance', async (_req, res) => {
    if (!credentialStatus().configured) return res.json({ configured: false });
    try { res.set('Cache-Control', 'no-store').json({ configured: true, ...await limitsAndUsage() }); } catch (e) { failure(res, e); }
  });
  app.post('/api/authority/:action', async (req, res) => {
    // A custom header requires same-origin JS (no CORS grant); ordinary forms
    // cannot trigger paid requests against an authenticated portal session.
    if (req.get('X-SEO-Request') !== '1' || !req.is('application/json')) return res.status(403).json({ error: 'invalid_request', message: 'Use the dashboard controls to run Ahrefs.' });
    if (!['research', 'refresh'].includes(req.params.action)) return res.status(404).end();
    let params;
    try { params = validateResearch({ ...req.body, ...(req.params.action === 'refresh' ? { kind: 'discover' } : {}) }, cfg); } catch (e) { return res.status(400).json({ error: 'invalid_input', message: e.message }); }
    if (!credentialStatus().configured) return res.status(409).json({ error: 'not_configured', message: 'Ahrefs is not configured on the server.' });
    if (running || refreshRunning()) return res.status(409).json({ error: 'already_running', message: 'A data refresh or Ahrefs operation is already running. Try again when it finishes.' });
    if (!existsSync(cfg.settings.database)) return res.status(503).json({ error: 'no_database', message: 'Run the first data fetch before research.' });
    running = true;
    let db;
    try {
      if (req.params.action === 'refresh') {
        const result = await refresh({ site: params.site.slug, source: 'ahrefs' });
        const failed = result.failed.filter(f => f.source === 'ahrefs');
        if (failed.length) return res.status(502).json({ error: failed[0].status, message: redactPaths(failed[0].message) });
        return res.json({ status: 'ok', asOf: result.sourceAsOf.ahrefs });
      }
      const result = await mutate(async () => {
        db = openDb(cfg.settings.database);
        try { return await runResearch(db, params); }
        finally { db.close(); db = null; }
      });
      return res.json(result);
    } catch (e) { return failure(res, e); } finally { db?.close(); running = false; }
  });
  return { running: () => running };
}
