export function formatCount(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(value);
}

export function formatRate(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  return `${(value * 100).toFixed(2)}%`;
}

export function formatDay(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return '';
  return value;
}

export const SOURCE_LABELS = Object.freeze({
  playInstalls: 'Play installs',
  playVitals: 'Play crashes and ANRs',
  ga4App: 'GA4 app sessions',
});

export function sourceStateLabel(state) {
  return {
    not_configured: 'Not connected',
    misconfigured: 'Needs a fix',
    ready: 'Connected',
    ok: 'Reporting',
    empty: 'No rows',
    error: 'Unavailable',
    partial: 'Partial',
  }[state] || 'Unavailable';
}
