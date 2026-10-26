import express from 'express';
import { authorizeMirai } from '../../seo/server/router.js';
import { publicSources, readPlayConfig, redact } from './config.js';
import { DEFINITIONS, countryRows, emptyMetrics, reportRange } from './normalize.js';
import { applyGa4, applyInstalls, applyVitals, loadGa4, loadVitals, readInstalls, SourceFailure } from './sources.js';

function overall(sources) {
  const states = Object.values(sources).map(source => source.state);
  const answered = states.some(state => state === 'ok' || state === 'empty');
  const incomplete = states.some(state => state === 'error' || state === 'misconfigured' || state === 'not_configured');
  if (answered && incomplete) return 'partial';
  if (answered) return 'ready';
  if (states.some(state => state === 'error')) return 'error';
  if (states.some(state => state === 'misconfigured')) return 'misconfigured';
  return 'not_configured';
}

export function createPlayReport(options = {}) {
  const env = options.env || process.env;
  return async function playReport(query) {
    const now = options.now ? options.now() : new Date();
    const range = reportRange(query, now);
    const config = readPlayConfig(env, options);
    const sources = publicSources(config.sources);
    const totals = emptyMetrics();
    const byCountry = countryRows(config.countries);
    const secrets = [config.credentialsPath, config.ga4CredentialsPath, config.statsDir, config.bucket].filter(Boolean);

    async function run(key, loader, apply) {
      if (config.sources[key].state !== 'ready') return;
      try {
        const result = await loader();
        sources[key].state = result.observed ? 'ok' : 'empty';
        sources[key].note = result.note;
        if (result.observed) apply(totals, byCountry, result);
      } catch (error) {
        sources[key].state = 'error';
        sources[key].note = null;
        const message = error instanceof SourceFailure ? error.message : 'The source could not be read.';
        sources[key].blocker = redact(message, secrets);
      }
    }

    await Promise.all([
      run('playInstalls', () => readInstalls({
        config, range, readDir: options.readDir, readFile: options.readFile,
        fetchImpl: options.fetchImpl || fetch, tokenProvider: options.tokenProvider,
      }), applyInstalls),
      run('playVitals', () => loadVitals({
        config, range, fetchImpl: options.fetchImpl || fetch, tokenProvider: options.tokenProvider,
      }), applyVitals),
      run('ga4App', () => loadGa4({
        config, range, ga4RunReport: options.ga4RunReport,
      }), applyGa4),
    ]);

    return {
      status: overall(sources),
      packageName: config.packageName,
      storeBuild: {
        name: 'Play 1.0.0',
        note: 'Reported live by Mirai Skin. This dashboard does not read the Play listing and does not confirm that status.',
      },
      range,
      totals,
      byCountry,
      sources,
      definitions: DEFINITIONS,
      generatedAt: now.toISOString(),
    };
  };
}

export function createPlayRouter({ authorize = authorizeMirai, report = createPlayReport() } = {}) {
  const router = express.Router();
  router.use((_req, res, next) => { res.set('Cache-Control', 'no-store'); next(); });
  router.use(authorize);
  router.get('/', async (req, res) => {
    try {
      reportRange(req.query);
    } catch (error) {
      return res.status(400).json({ message: error.message });
    }
    try {
      res.json(await report(req.query));
    } catch {
      res.status(502).json({ message: 'App performance could not be loaded. Please retry.' });
    }
  });
  return router;
}
