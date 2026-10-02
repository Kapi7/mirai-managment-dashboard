import { latestCompleteDate } from './reporting.js';

export const GOOGLE_REFRESH_INTERVAL_MS = 6 * 3600e3;
export const GOOGLE_CHECK_INTERVAL_MS = 3600e3;

// Check every connection, including commerce. A healthy GA4 property must not
// conceal a failed satellite, Search Console import, or purchase report.
export function googleFreshness(database, cfg, now = new Date()) {
  const latest = database.prepare(`SELECT run_at, status, end_date, data_through
    FROM fetch_log WHERE site = ? AND source = ? AND connection = ?
    ORDER BY id DESC LIMIT 1`);
  const sources = [];
  for (const site of cfg.sites) {
    const connections = [];
    if (site.gscProperty) connections.push(['gsc', site.gscProperty]);
    if (site.ga4PropertyId) connections.push(['ga4', site.ga4PropertyId], ['ga4_commerce', site.ga4PropertyId]);
    for (const [source, connection] of connections) {
      const row = latest.get(site.slug, source, connection);
      const expectedThrough = latestCompleteDate(source === 'gsc' ? 'gsc' : 'ga4', cfg.settings.sourceLagDays, now);
      const elapsed = now.getTime() - Date.parse(row?.run_at);
      const reason = !row ? 'not_fetched' : row.status !== 'ok' ? 'retry'
        : !row.end_date || row.end_date < expectedThrough ? 'new_reporting_day'
        : !Number.isFinite(elapsed) || elapsed >= GOOGLE_REFRESH_INTERVAL_MS ? 'scheduled' : null;
      sources.push({ site: site.slug, source, status: row?.status || 'not_fetched',
        checkedAt: row?.run_at || null, dataThrough: row?.data_through || null,
        requestedThrough: row?.end_date || null, expectedThrough, reason });
    }
  }
  return {
    lastFetch: sources.map(s => s.checkedAt).filter(Boolean).sort().at(-1) || null,
    due: sources.some(s => s.reason),
    failures: sources.filter(s => s.status !== 'ok').length,
    refreshIntervalHours: GOOGLE_REFRESH_INTERVAL_MS / 3600e3,
    checkIntervalMinutes: GOOGLE_CHECK_INTERVAL_MS / 60000,
    sources,
  };
}
