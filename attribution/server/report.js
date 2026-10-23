import express from 'express';
import process from 'node:process';
import { authorizeMirai } from '../../seo/server/router.js';

const DAY = 86400000;
const LIMIT = 100000;
export const GRAPHQL = `query Attribution($q: String!) {
  shop { currencyCode ianaTimezone }
  shopifyqlQuery(query: $q) { tableData { columns { name dataType } rows } parseErrors }
}`;
const iso = date => date.toISOString().slice(0, 10);
const validDate = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)
  && Number.isFinite(Date.parse(value)) && iso(new Date(value)) === value;

export function reportRange(query = {}, now = new Date()) {
  const end = query.end || iso(new Date(now.getTime() - DAY));
  const start = query.start || iso(new Date(Date.parse(end) - 27 * DAY));
  if (!validDate(start) || !validDate(end) || start > end || end > iso(now)
      || Date.parse(end) - Date.parse(start) > 92 * DAY) {
    throw new Error('Choose a valid date range of up to 93 days, ending today or earlier.');
  }
  const days = Math.round((Date.parse(end) - Date.parse(start)) / DAY) + 1;
  const comparison = query.comparison || 'previous';
  if (!['previous', 'none'].includes(comparison)) throw new Error('Choose a supported comparison.');
  return { start, end, days, comparison,
    previousStart: comparison === 'previous' ? iso(new Date(Date.parse(start) - days * DAY)) : null,
    previousEnd: comparison === 'previous' ? iso(new Date(Date.parse(start) - DAY)) : null };
}

export function queries(range) {
  const window = `SINCE ${range.previousStart || range.start} UNTIL ${range.end} LIMIT ${LIMIT}`;
  return {
    sessions: `FROM sessions SHOW sessions, sessions_that_completed_checkout GROUP BY day, referring_channel, traffic_type, session_country, session_country_code ${window}`,
    sales: `FROM sales SHOW orders, net_sales GROUP BY day, referring_channel, traffic_type, shipping_country, shipping_country_code, new_or_returning_customer, sales_channel ${window}`,
    sessionTotals: `FROM sessions SHOW sessions, sessions_that_completed_checkout GROUP BY day ${window}`,
    salesTotals: `FROM sales SHOW orders, net_sales GROUP BY day, new_or_returning_customer ${window}`,
  };
}

export class SourceError extends Error {
  constructor(message, status = 502) { super(message); this.status = status; }
}

export function parseTable(body, expected) {
  if (body.errors?.length) throw new SourceError('Shopify analytics access is unavailable. Check the reporting connection and read_reports permission.');
  const result = body.data?.shopifyqlQuery;
  if (result?.parseErrors?.length) throw new SourceError('Shopify could not run this report. Its reporting schema may have changed.');
  const table = result?.tableData;
  if (!table || !Array.isArray(table.rows) || !Array.isArray(table.columns)) throw new SourceError('Shopify returned an incomplete report. Please retry.');
  if (table.rows.length >= LIMIT) throw new SourceError('This period has too many rows. Select a shorter date range.');
  const names = table.columns.map(c => c.name);
  if (expected.some(name => !names.includes(name))) throw new SourceError('Shopify returned unexpected report columns.');
  const rows = table.rows.map(row => Array.isArray(row) ? Object.fromEntries(names.map((name, index) => [name, row[index]])) : row);
  return { rows, shop: body.data?.shop };
}

export function createShopifyClient({ env = process.env, fetchImpl = fetch } = {}) {
  return async (q, expected) => {
    const store = (env.SHOPIFY_STORE || '').trim();
    const token = (env.SHOPIFY_ACCESS_TOKEN || '').trim();
    const version = (env.SHOPIFYQL_API_VERSION || 'unstable').trim();
    if (!/^[a-z0-9][a-z0-9-]*\.myshopify\.com$/.test(store) || !token || !/^(unstable|\d{4}-\d{2})$/.test(version)) {
      throw new SourceError('Connect the Mirai Shopify reporting credentials to load attribution.', 503);
    }
    let response;
    try {
      response = await fetchImpl(`https://${store}/admin/api/${version}/graphql.json`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Shopify-Access-Token': token },
        body: JSON.stringify({ query: GRAPHQL, variables: { q } }),
        signal: AbortSignal.timeout(60000), redirect: 'error',
      });
    } catch { throw new SourceError('Shopify did not respond. Please retry in a moment.', 503); }
    if (!response.ok) throw new SourceError(response.status === 429 ? 'Shopify is busy. Please retry shortly.' : 'The Shopify reporting connection is unavailable.', 503);
    let body;
    try { body = await response.json(); } catch { throw new SourceError('Shopify returned an unreadable report.'); }
    return parseTable(body, expected);
  };
}

function number(value) {
  if (value == null || value === '' || !Number.isFinite(Number(value))) throw new SourceError('Shopify returned a missing or invalid metric.');
  return Number(value);
}

export function channelFor(row, sales = false) {
  // A missing source is not evidence of organic or direct traffic.
  const salesChannel = String(row.sales_channel || '').trim();
  if (sales && salesChannel && salesChannel.toLowerCase() !== 'online store') return salesChannel;
  const source = String(row.referring_channel || '').trim();
  const traffic = String(row.traffic_type || '').trim().toLowerCase();
  if (!source || ['unknown', 'unattributed', 'none'].includes(source.toLowerCase())) return 'Unattributed';
  const labels = { google: 'Google', facebook: 'Facebook', instagram: 'Instagram', direct: 'Direct', shop: 'Shop',
    bing: 'Bing', tiktok: 'TikTok', youtube: 'YouTube', klaviyo: 'Klaviyo', pinterest: 'Pinterest', chatgpt: 'ChatGPT' };
  const name = labels[source.toLowerCase()] || source;
  return ['paid', 'organic'].includes(traffic) ? `${name} · ${traffic === 'paid' ? 'Paid' : 'Organic'}` : name;
}

export function normalizeReport(sessionRows, salesRows, range) {
  const rows = new Map();
  function get(row, sales) {
    const date = String(row.day || '').slice(0, 10);
    if (!validDate(date) || date < (range.previousStart || range.start) || date > range.end) throw new SourceError('Shopify returned a date outside this report.');
    const country = String(row[sales ? 'shipping_country' : 'session_country'] || 'Unknown country');
    const rawCode = String(row[sales ? 'shipping_country_code' : 'session_country_code'] || '').toUpperCase();
    const countryCode = /^[A-Z]{2}$/.test(rawCode) && !['ZZ', 'XX'].includes(rawCode) ? rawCode : '';
    const channel = channelFor(row, sales);
    const key = JSON.stringify([date, channel, countryCode || country]);
    if (!rows.has(key)) rows.set(key, { date, channel, country, countryCode, sessions: 0, convertedSessions: 0, orders: 0, amount: 0, returningOrders: 0, unknownCustomerOrders: 0 });
    return rows.get(key);
  }
  for (const row of sessionRows) {
    const target = get(row, false);
    target.sessions += number(row.sessions);
    target.convertedSessions += number(row.sessions_that_completed_checkout);
  }
  for (const row of salesRows) {
    const target = get(row, true);
    const orders = number(row.orders);
    target.orders += orders;
    target.amount += number(row.net_sales);
    const type = String(row.new_or_returning_customer || '').toLowerCase();
    if (type === 'returning') target.returningOrders += orders;
    else if (type !== 'new') target.unknownCustomerOrders += orders;
  }
  return [...rows.values()].sort((a, b) => a.date.localeCompare(b.date));
}

// Related-dimension joins can omit sessions with no usable source/geo record.
// Keep their measured residual visible without inventing a channel or country.
export function reconcileRows(rows, sessionTotals, salesTotals, range) {
  const totals = normalizeReport(sessionTotals, salesTotals, range);
  const details = new Map();
  const fields = ['sessions', 'convertedSessions', 'orders', 'amount', 'returningOrders', 'unknownCustomerOrders'];
  for (const row of rows) {
    if (!details.has(row.date)) details.set(row.date, Object.fromEntries(fields.map(k => [k, 0])));
    for (const key of fields) details.get(row.date)[key] += row[key];
  }
  const expected = new Map();
  for (const row of totals) {
    if (!expected.has(row.date)) expected.set(row.date, Object.fromEntries(fields.map(k => [k, 0])));
    for (const key of fields) expected.get(row.date)[key] += row[key];
  }
  const result = [...rows];
  for (const date of new Set([...details.keys(), ...expected.keys()])) {
    const residual = {};
    for (const key of fields) {
      residual[key] = (expected.get(date)?.[key] || 0) - (details.get(date)?.[key] || 0);
      if (key === 'amount') residual[key] = Math.round(residual[key] * 100) / 100;
      else if (residual[key] < 0) throw new SourceError('Shopify is revising this period. Its totals and details disagree; please reload shortly.');
    }
    if (fields.some(key => Math.abs(residual[key]) > 0.001)) result.push({ date, channel: 'Unallocated detail', country: 'Unknown country', countryCode: '', ...residual, unallocated: true });
  }
  return result.sort((a, b) => a.date.localeCompare(b.date));
}

export function createReportService({ client = createShopifyClient(), now = () => new Date() } = {}) {
  const cache = new Map();
  const pending = new Map();
  return async function report(query) {
    const range = reportRange(query, now());
    const key = JSON.stringify(range);
    const cached = cache.get(key);
    if (cached && now().getTime() - Date.parse(cached.fetchedAt) < 5 * 60000) return cached;
    if (pending.has(key)) return pending.get(key);
    if (pending.size >= 3) throw new SourceError('Other reports are loading. Please retry shortly.', 503);
    const job = (async () => {
      const q = queries(range);
      // Keep the two source reads bounded; never substitute one source for the other.
      const [sessions, sales] = await Promise.all([
        client(q.sessions, ['day', 'referring_channel', 'traffic_type', 'session_country', 'session_country_code', 'sessions', 'sessions_that_completed_checkout']),
        client(q.sales, ['day', 'referring_channel', 'traffic_type', 'shipping_country', 'shipping_country_code', 'new_or_returning_customer', 'sales_channel', 'orders', 'net_sales']),
      ]);
      const [sessionTotals, salesTotals] = await Promise.all([
        client(q.sessionTotals, ['day', 'sessions', 'sessions_that_completed_checkout']),
        client(q.salesTotals, ['day', 'new_or_returning_customer', 'orders', 'net_sales']),
      ]);
      const shop = sales.shop;
      if (!shop?.currencyCode || !shop?.ianaTimezone || sessions.shop?.currencyCode !== shop.currencyCode || sessions.shop?.ianaTimezone !== shop.ianaTimezone) throw new SourceError('Shopify did not confirm the report currency and time zone.');
      const rows = reconcileRows(normalizeReport(sessions.rows, sales.rows, range), sessionTotals.rows, salesTotals.rows, range);
      const result = { range, currency: shop.currencyCode, timezone: shop.ianaTimezone,
        fetchedAt: now().toISOString(), rows };
      cache.delete(key);
      cache.set(key, result);
      while (cache.size > 12) cache.delete(cache.keys().next().value);
      return result;
    })();
    pending.set(key, job);
    try { return await job; } finally { pending.delete(key); }
  };
}

export function createAttributionRouter({ authorize = authorizeMirai, report = createReportService() } = {}) {
  const router = express.Router();
  router.use((_req, res, next) => { res.set('Cache-Control', 'no-store'); next(); });
  router.use(authorize);
  router.get('/', async (req, res) => {
    try { reportRange(req.query); } catch (error) { return res.status(400).json({ message: error.message }); }
    try { res.json(await report(req.query)); }
    catch (error) { res.status(error instanceof SourceError ? error.status : 502).json({ message: error instanceof SourceError ? error.message : 'Attribution could not be loaded. Please retry.' }); }
  });
  return router;
}
