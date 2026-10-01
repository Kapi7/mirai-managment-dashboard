import { initDb, openDb } from './db.js';
import { loadConfig } from './config.js';
import { runFetch } from './fetch.js';
import { createStorage } from './storage.js';
import { AccessDenied, BudgetExceeded, AhrefsUnavailable } from './ahrefs.js';

export function createRuntime({ cfg = loadConfig(), fetcher = runFetch, storage = createStorage(cfg.settings.database) } = {}) {
  const state = { running: false, startedAt: null, finishedAt: null, error: null, failed: [], durable: storage.durable };
  let readyError = null;
  const ready = storage.restore().then(() => { initDb(cfg.settings.database).close(); })
    .catch(() => { readyError = 'SEO history could not be restored. Retry after checking the database connection.'; });
  let task = null;
  async function mutate(operation) {
    await ready;
    if (readyError) throw new Error(readyError);
    if (task) throw new Error('A refresh is already running.');
    state.running = true; state.startedAt = new Date().toISOString(); state.error = null;
    task = (async () => {
      try {
        const result = await storage.exclusive(operation);
        state.failed = (result.failed || []).map(f => ({ site: f.site, source: f.source, status: f.status }));
        return result;
      } catch (error) {
        state.error = 'The update could not complete or be saved. Another instance may be refreshing; try again shortly.';
        if (error instanceof AccessDenied || error instanceof BudgetExceeded || error instanceof AhrefsUnavailable) throw error;
        throw new Error(state.error);
      } finally { state.running = false; state.finishedAt = new Date().toISOString(); task = null; }
    })();
    return task;
  }
  async function refresh(options = {}) {
    return mutate(async () => {
      // Google daily refreshes do not consume Ahrefs units. Ahrefs is explicit.
      if (options.source) return fetcher(options);
      const gsc = await fetcher({ ...options, source: 'gsc' });
      const ga4 = await fetcher({ ...options, source: 'ga4' });
      return { failed: [...gsc.failed, ...ga4.failed], sourceAsOf: ga4.sourceAsOf };
    });
  }
  let timer;
  if (process.env.MIRAI_SEO_AUTO_REFRESH === '1') {
    const tick = async () => {
      await ready;
      if (readyError || state.running) return;
      const database = openDb(cfg.settings.database, { readonly: true });
      let latest;
      try { latest = database.prepare("SELECT MAX(run_at) AS d FROM fetch_log WHERE source='ga4' AND status='ok'").get()?.d; } finally { database.close(); }
      if (!latest || Date.now() - Date.parse(latest) > 864e5) await refresh().catch(() => {});
    };
    ready.then(() => tick());
    timer = setInterval(tick, 3600e3); timer.unref();
  }
  return { cfg, state, ready, refresh, mutate, storage, error: () => readyError,
    async close() { clearInterval(timer); await task?.catch(() => {}); await storage.close(); } };
}
