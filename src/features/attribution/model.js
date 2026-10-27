const DAY = 86400000;
const fields = ['sessions', 'convertedSessions', 'orders', 'amount', 'returningOrders', 'unknownCustomerOrders'];
export const METRICS = [
  { key: 'sessions', label: 'Sessions', color: '#818cf8', description: 'Shopify Online Store sessions, including traffic Shopify identifies as bots. Shop app / Shop Cash and other non–Online Store sales channels with orders and no Online Store sessions show n/a.' },
  { key: 'orders', label: 'Orders', color: '#fb7185', description: 'Shopify orders by recorded referring channel; Shop and other sales channels are separate.' },
  { key: 'conversion', label: 'Conversion', color: '#2dd4bf', description: 'Sessions that completed checkout ÷ sessions. Totals are weighted, not averaged across rows.' },
  { key: 'amount', label: 'Net sales', color: '#22d3ee', description: 'Sales after discounts and sales reversals; excludes shipping and taxes. Reversals follow their posting date.' },
  { key: 'returningOrders', label: 'Returning orders', color: '#a78bfa', description: 'Orders classified by Shopify as Returning at purchase time, rather than the customer’s current lifetime order count.' },
];
export const countryKey = row => row.countryCode || row.country;
const blank = () => Object.fromEntries(fields.map(key => [key, 0]));
const pair = (id, label, extra = {}) => ({ id, label, current: blank(), previous: blank(), children: new Map(), ...extra });
function add(target, row) { for (const field of fields) target[field] += row[field] || 0; }
function finish(value) { return { ...value, conversion: value.sessions > 0 ? value.convertedSessions / value.sessions : null }; }
function finalize(node) { return { ...node, current: finish(node.current), previous: finish(node.previous), children: [...node.children.values()].map(finalize) }; }

export function buildView(report, { channel = 'all', country = 'all', group = 'channel' } = {}) {
  const root = pair('total', 'Total');
  const daily = new Map();
  for (let i = 0; i < report.range.days; i++) {
    const date = new Date(Date.parse(report.range.start) + i * DAY).toISOString().slice(0, 10);
    daily.set(date, pair(date, date));
  }
  for (const row of report.rows) {
    if (channel !== 'all' && row.channel !== channel || country !== 'all' && countryKey(row) !== country) continue;
    const previous = row.date < report.range.start;
    const side = previous ? 'previous' : 'current';
    const dayIndex = Math.round((Date.parse(row.date) - Date.parse(previous ? report.range.previousStart : report.range.start)) / DAY);
    const date = new Date(Date.parse(report.range.start) + dayIndex * DAY).toISOString().slice(0, 10);
    if (!daily.has(date)) continue;
    add(root[side], row);
    add(daily.get(date)[side], row);
    const geo = { label: row.country, countryCode: row.countryCode, isCountry: true };
    const topId = group === 'channel' ? row.channel : countryKey(row);
    const subId = group === 'channel' ? countryKey(row) : row.channel;
    if (!root.children.has(topId)) root.children.set(topId, pair(topId, group === 'channel' ? row.channel : row.country, group === 'channel' ? {} : geo));
    const top = root.children.get(topId);
    if (!top.children.has(subId)) top.children.set(subId, pair(`${topId}/${subId}`, group === 'channel' ? row.country : row.channel, group === 'channel' ? geo : {}));
    const sub = top.children.get(subId);
    if (!sub.children.has(date)) sub.children.set(date, pair(`${topId}/${subId}/${date}`, date, { date }));
    add(top[side], row); add(sub[side], row); add(sub.children.get(date)[side], row);
  }
  const result = finalize(root);
  return { ...result, daily: [...daily.values()].map(finalize) };
}

export function trend(current, previous, rate = false) {
  if (current == null || previous == null) return { direction: 'neutral', text: '—' };
  const delta = current - previous;
  if (Math.abs(delta) < (rate ? 0.00005 : 0.005)) return { direction: 'neutral', text: '0' + (rate ? ' pp' : '%') };
  const direction = delta > 0 ? 'up' : 'down';
  if (rate) return { direction, text: `${delta > 0 ? '+' : ''}${(delta * 100).toFixed(2)} pp` };
  if (previous === 0) return { direction, text: 'New' };
  return { direction, text: `${delta > 0 ? '+' : ''}${(delta / Math.abs(previous) * 100).toFixed(1)}%` };
}

// Orders with no Online Store sessions: Shop app / Shop Cash and other
// non–Online Store sales channels. A bare 0 reads as a broken join.
export function isOrderOnly(metrics) {
  return (Number(metrics?.orders) || 0) > 0 && (Number(metrics?.sessions) || 0) === 0;
}
export const ORDER_ONLY_LABEL = 'Order-only';
export const ORDER_ONLY_NOTE = 'Shop (Shop app and Shop Cash) and other non–Online Store sales channels report orders and net sales without Online Store sessions. Sessions show n/a and conversion stays —. shop_app and shop_campaigns web sessions stay on their own rows.';
export function formatMetric(value, metric, currency = 'USD', metrics) {
  if (metric === 'sessions' && isOrderOnly(metrics)) return 'n/a';
  if (value == null) return '—';
  if (metric === 'conversion') return `${(value * 100).toFixed(2)}%`;
  return new Intl.NumberFormat('en-US', metric === 'amount'
    ? { style: 'currency', currency, maximumFractionDigits: 2 }
    : { maximumFractionDigits: 0 }).format(value);
}
export function flag(code) {
  return /^[A-Z]{2}$/.test(code || '') ? [...code].map(c => String.fromCodePoint(c.charCodeAt(0) + 127397)).join('') : '🌐';
}
export function csvCell(value) {
  let text = String(value ?? '');
  if (typeof value === 'string' && /^\s*[=+@-]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}
export function exportCsv(view, report, group) {
  const columns = ['Channel', 'Country', 'Country code', 'Start', 'End', 'Previous start', 'Previous end', 'Currency', 'Time zone', ...METRICS.flatMap(m => [m.label, `Previous ${m.label}`])];
  const rows = view.children.flatMap(top => top.children.map(sub => {
    const channel = group === 'channel' ? top.label : sub.label;
    const country = group === 'channel' ? sub : top;
    return [channel, country.label, country.countryCode, report.range.start, report.range.end, report.range.previousStart, report.range.previousEnd, report.currency, report.timezone,
      ...METRICS.flatMap(m => [sub.current[m.key], report.range.comparison === 'none' ? '' : sub.previous[m.key]])];
  }));
  return [columns, ...rows].map(row => row.map(csvCell).join(',')).join('\r\n');
}
