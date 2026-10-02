import express from 'express';
import { resolve } from 'node:path';
import { openDb } from './db.js';
import { buildDashboard } from './dashboard.js';
import { checkConnections } from './connections.js';
import { credentialStatusFor } from './config.js';
import { createRuntime } from './runtime.js';
import { registerAuthorityRoutes } from './authority-routes.js';
import { familyHtml, familyScript, familyCss, FAMILY_DIR } from './family-page.js';

export async function authorizeMirai(req, res, next) {
  if (!/^Bearer \S+$/.test(req.get('Authorization') || '')) {
    return res.status(401).json({ error: 'unauthorized', message: 'Sign in to Mirai Management to view SEO.' });
  }
  try {
    const response = await fetch(`${process.env.PYTHON_BACKEND_URL || 'http://127.0.0.1:8080'}/auth/me`, {
      headers: { Authorization: req.get('Authorization') }, signal: AbortSignal.timeout(10000), redirect: 'error',
    });
    if (!response.ok) return res.status(response.status === 401 || response.status === 403 ? response.status : 503)
      .json({ error: 'auth_unavailable', message: 'Your Mirai session could not be verified.' });
    const body = await response.json();
    if (!body.user?.email) return res.status(401).json({ error: 'unauthorized', message: 'Sign in to Mirai Management.' });
    req.seoUser = body.user;
    next();
  } catch { res.status(503).json({ error: 'auth_unavailable', message: 'Mirai sign-in is temporarily unavailable.' }); }
}

export function createSeoRouter({ runtime = createRuntime(), authorize = authorizeMirai } = {}) {
  const router = express.Router();
  const { cfg } = runtime;
  router.use(express.json({ limit: '16kb' }));
  router.use('/api', authorize, async (req, res, next) => {
    res.set('Cache-Control', 'no-store');
    await runtime.ready;
    if (runtime.error()) return res.status(503).json({ error: 'storage_unavailable', message: runtime.error() });
    if (!['GET', 'HEAD'].includes(req.method) && !req.seoUser?.is_admin) return res.status(403).json({ error: 'admin_required', message: 'A Mirai administrator can refresh sources and run research.' });
    next();
  });
  router.get('/api/status', (_req, res) => res.json({ ...runtime.state,
    freshness: runtime.freshness(),
    automaticRefresh: process.env.MIRAI_SEO_AUTO_REFRESH === '1',
    googleConfigured: credentialStatusFor(cfg.credentials.mirai).configured,
    sites: cfg.sites.map(s => ({ slug: s.slug, name: s.name, role: s.vertical, platform: s.platform })),
  }));
  router.get('/api/dashboard', (_req, res) => {
    const database = openDb(cfg.settings.database, { readonly: true });
    try { res.json({ ...buildDashboard(database, cfg), refresh: { ...runtime.state,
      freshness: runtime.freshness(), automatic: process.env.MIRAI_SEO_AUTO_REFRESH === '1' } }); } finally { database.close(); }
  });
  router.get('/api/fetch/status', (_req, res) => res.json(runtime.state));
  let authority;
  router.post('/api/fetch', (req, res) => {
    if (req.get('X-SEO-Request') !== '1' || !req.is('application/json')) return res.status(403).json({ error: 'invalid_request' });
    if (runtime.state.running || authority.running()) return res.status(409).json({ error: 'already_running', message: 'A refresh is already running.' });
    if (!credentialStatusFor(cfg.credentials.mirai).configured) return res.status(409).json({ error: 'not_configured', message: 'Connect the Mirai Google credential before refreshing.' });
    runtime.refresh().catch(() => {});
    res.status(202).json({ status: 'started' });
  });
  let connectionCheck = null;
  router.get('/api/connections', async (_req, res) => {
    if (!connectionCheck) connectionCheck = checkConnections(cfg.sites, {
      registry: cfg.credentials, affiliateEvents: cfg.settings.affiliateEvents,
    }).then(sites => ({ checkedAt: new Date().toISOString(), sites }))
      .finally(() => { connectionCheck = null; });
    try { res.json(await connectionCheck); }
    catch { res.status(502).json({ error: 'connection_check_failed', message: 'Some sources could not be checked. Try again.' }); }
  });
  authority = registerAuthorityRoutes(router, cfg, {
    refresh: options => runtime.refresh(options), refreshRunning: () => runtime.state.running,
    mutate: operation => runtime.mutate(operation),
  });
  router.use('/api', (_req, res) => res.status(404).json({ error: 'not_found' }));
  router.get('/family/app.js', (_req, res) => res.set('Cache-Control', 'no-cache').type('application/javascript').send(familyScript()));
  router.get('/family/style.css', (_req, res) => res.set('Cache-Control', 'no-cache').type('text/css').send(familyCss()));
  router.use('/family/fonts', express.static(resolve(FAMILY_DIR, 'fonts'), { maxAge: '365d', immutable: true }));
  router.get('/', (_req, res) => res.set({ 'Cache-Control': 'no-store', 'X-Frame-Options': 'SAMEORIGIN',
    'Content-Security-Policy': "frame-ancestors 'self'", 'Referrer-Policy': 'same-origin' }).type('html').send(familyHtml('/seo-dashboard')));
  router.use((err, _req, res, _next) => res.status(500).json({ error: 'seo_error', message: 'SEO could not complete this request.' }));
  return router;
}
