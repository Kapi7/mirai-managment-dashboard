import { basename, join } from 'node:path';
import { readdir, readFile } from 'node:fs/promises';
import { installFilePattern, monthsInRange, aggregateInstallCsv, aggregateVitals, aggregateGa4 } from './normalize.js';

export class SourceFailure extends Error {
  constructor(message) {
    super(message);
    this.name = 'SourceFailure';
  }
}

const PLAY_SCOPE = 'https://www.googleapis.com/auth/playdeveloperreporting';
const STORAGE_SCOPE = 'https://www.googleapis.com/auth/devstorage.read_only';

async function defaultReadDir(dir) {
  return readdir(dir);
}

async function defaultReadFile(file) {
  return readFile(file, 'utf8');
}

export async function googleAccessToken({ keyFile, scopes }) {
  const { GoogleAuth } = await import('google-auth-library');
  const auth = new GoogleAuth({ keyFile, scopes });
  const client = await auth.getClient();
  const token = await client.getAccessToken();
  const value = typeof token === 'string' ? token : token?.token;
  if (!value) throw new SourceFailure('Google did not return an access token.');
  return value;
}

async function requestJson(url, { method = 'GET', token, body, fetchImpl }) {
  let response;
  try {
    response = await fetchImpl(url, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(30000),
      redirect: 'error',
    });
  } catch {
    throw new SourceFailure('The source did not respond.');
  }
  const text = await response.text();
  if (!response.ok) throw googleError(response.status, text);
  try {
    return text ? JSON.parse(text) : {};
  } catch {
    throw new SourceFailure('The source returned an unreadable response.');
  }
}

function googleError(status, body) {
  let detail = '';
  try {
    const parsed = JSON.parse(body);
    const message = parsed?.error?.message || parsed?.error?.status || '';
    if (typeof message === 'string' && message.length > 0 && message.length < 180
      && !/bearer|ya29|private_key|client_secret|credential/i.test(message)) {
      detail = ` ${message}`;
    }
  } catch { /* status alone is enough */ }
  return new SourceFailure(`Google request failed (${status}).${detail}`);
}

export async function loadInstallTexts({ config, readDir = defaultReadDir, readFile = defaultReadFile, fetchImpl, tokenProvider, range }) {
  const months = new Set(monthsInRange(range.start, range.end));
  const pattern = installFilePattern(config.packageName);
  if (config.statsDir) {
    let names;
    try { names = await readDir(config.statsDir); }
    catch { throw new SourceFailure('The install export directory could not be read, so install totals are hidden.'); }
    const files = names.filter(name => {
      const base = basename(name);
      if (base !== name || !pattern.test(base)) return false;
      return months.has(pattern.exec(base)[1]);
    });
    if (!files.length) return [];
    const texts = [];
    for (const name of files) {
      try { texts.push(await readFile(join(config.statsDir, name))); }
      catch { throw new SourceFailure('An install export could not be read, so install totals are hidden.'); }
    }
    return texts;
  }
  const token = await (tokenProvider || googleAccessToken)({ keyFile: config.credentialsPath, scopes: [STORAGE_SCOPE] });
  const prefix = `stats/installs/installs_${config.packageName}_`;
  const names = await listInstallObjects({ bucket: config.bucket, prefix, token, fetchImpl, pattern, months });
  const texts = [];
  for (const name of names) {
    const url = `https://storage.googleapis.com/storage/v1/b/${encodeURIComponent(config.bucket)}/o/${encodeURIComponent(name)}?alt=media`;
    texts.push(await requestText(url, token, fetchImpl));
  }
  return texts;
}

async function listInstallObjects({ bucket, prefix, token, fetchImpl, pattern, months }) {
  const names = [];
  let pageToken = '';
  for (let page = 0; page < 5; page += 1) {
    const url = new URL(`https://storage.googleapis.com/storage/v1/b/${encodeURIComponent(bucket)}/o`);
    url.searchParams.set('prefix', prefix);
    url.searchParams.set('fields', 'items(name),nextPageToken');
    if (pageToken) url.searchParams.set('pageToken', pageToken);
    const body = await requestJson(url, { token, fetchImpl });
    for (const item of body.items || []) {
      const base = basename(item.name || '');
      if (!pattern.test(base) || !months.has(pattern.exec(base)[1])) continue;
      names.push(item.name);
    }
    if (!body.nextPageToken) return names;
    pageToken = body.nextPageToken;
  }
  throw new SourceFailure('The Play stats bucket has more install files than this report reads, so install totals are hidden.');
}

async function requestText(url, token, fetchImpl) {
  let response;
  try {
    response = await fetchImpl(url, {
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(30000),
      redirect: 'error',
    });
  } catch {
    throw new SourceFailure('The source did not respond.');
  }
  if (!response.ok) {
    const text = await response.text();
    throw googleError(response.status, text);
  }
  const text = await response.text();
  if (text.length > 5_000_000) throw new SourceFailure('An install export is too large, so install totals are hidden.');
  return text;
}

const PLAY_DAILY_TIME_ZONE = 'America/Los_Angeles';

function isoDate(value) {
  const year = Number(value?.year);
  const month = Number(value?.month);
  const day = Number(value?.day);
  if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) return null;
  const iso = `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  const parsed = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== iso) return null;
  return iso;
}

function shiftIsoDate(iso, days) {
  const parsed = new Date(`${iso}T00:00:00Z`);
  parsed.setUTCDate(parsed.getUTCDate() + days);
  return parsed.toISOString().slice(0, 10);
}

function zonedDate(iso) {
  const [year, month, day] = iso.split('-').map(Number);
  return { year, month, day, timeZone: { id: PLAY_DAILY_TIME_ZONE } };
}

// DAILY Play timelines are America/Los_Angeles calendar dates. latestEndTime is
// the exclusive end already, so a selected range must not extend past it.
function dailyTimeline(start, end, latestEndTime) {
  const latest = latestEndTime ? isoDate(latestEndTime) : null;
  let exclusiveEnd = shiftIsoDate(end, 1);
  if (latest && exclusiveEnd > latest) exclusiveEnd = latest;
  if (start >= exclusiveEnd) return null;
  return {
    aggregationPeriod: 'DAILY',
    startTime: zonedDate(start),
    endTime: zonedDate(exclusiveEnd),
  };
}

async function latestDailyEnd({ packageName, metricSet, token, fetchImpl }) {
  const url = `https://playdeveloperreporting.googleapis.com/v1beta1/apps/${encodeURIComponent(packageName)}/${metricSet}`;
  const body = await requestJson(url, { token, fetchImpl });
  const freshnesses = body?.freshnessInfo?.freshnesses;
  if (!Array.isArray(freshnesses)) return null;
  const daily = freshnesses.find(item => item?.aggregationPeriod === 'DAILY');
  return daily?.latestEndTime || null;
}

async function queryDailyMetricSet({ packageName, metricSet, range, body, token, fetchImpl }) {
  const latestEndTime = await latestDailyEnd({ packageName, metricSet, token, fetchImpl });
  const timelineSpec = dailyTimeline(range.start, range.end, latestEndTime);
  if (!timelineSpec) return { rows: [], complete: true };
  return queryMetricSet({ packageName, metricSet, token, fetchImpl, body: { ...body, timelineSpec } });
}

async function queryMetricSet({ packageName, metricSet, body, token, fetchImpl }) {
  const url = `https://playdeveloperreporting.googleapis.com/v1beta1/apps/${encodeURIComponent(packageName)}/${metricSet}:query`;
  const rows = [];
  let pageToken;
  for (let page = 0; page < 10; page += 1) {
    const response = await requestJson(url, { method: 'POST', token, fetchImpl, body: { ...body, pageSize: body.pageSize, pageToken } });
    rows.push(...(response.rows || []));
    if (!response.nextPageToken) return { rows, complete: true };
    pageToken = response.nextPageToken;
  }
  return { rows, complete: false };
}

export async function loadVitals({ config, range, fetchImpl, tokenProvider }) {
  const token = await (tokenProvider || googleAccessToken)({ keyFile: config.credentialsPath, scopes: [PLAY_SCOPE] });
  const query = (metricSet, body) => queryDailyMetricSet({
    packageName: config.packageName, metricSet, range, body, token, fetchImpl,
  });
  const [errors, crashes, anrs] = await Promise.all([
    query('errorCountMetricSet', { dimensions: ['reportType'], metrics: ['errorReportCount'], pageSize: 1000 }),
    query('crashRateMetricSet', { metrics: ['userPerceivedCrashRate'], pageSize: 100 }),
    query('anrRateMetricSet', { metrics: ['userPerceivedAnrRate'], pageSize: 100 }),
  ]);
  const aggregated = aggregateVitals({
    errorRows: errors.rows,
    crashRows: crashes.rows,
    anrRows: anrs.rows,
    start: range.start,
    end: range.end,
    countries: config.countries,
    complete: errors.complete && crashes.complete && anrs.complete,
  });
  if (aggregated.error) throw new SourceFailure(aggregated.error);
  return aggregated;
}

export async function defaultGa4RunReport({ propertyId, keyFile, request }) {
  const { BetaAnalyticsDataClient } = await import('@google-analytics/data');
  const client = new BetaAnalyticsDataClient({ keyFilename: keyFile });
  const [response] = await client.runReport({ property: `properties/${propertyId}`, ...request });
  return response;
}

export async function loadGa4({ config, range, ga4RunReport = defaultGa4RunReport }) {
  const propertyId = config.sources.ga4App.propertyId;
  const keyFile = config.ga4CredentialsPath;
  const run = request => ga4RunReport({ propertyId, keyFile, request });
  const dateRanges = [{ startDate: range.start, endDate: range.end }];
  let rangeResponse;
  let dailyResponse;
  let countryResponse;
  let eventResponse;
  try {
    [rangeResponse, dailyResponse, countryResponse, eventResponse] = await Promise.all([
      run({ dateRanges, metrics: [{ name: 'sessions' }, { name: 'activeUsers' }], limit: 5 }),
      run({ dateRanges, dimensions: [{ name: 'date' }], metrics: [{ name: 'activeUsers' }], limit: 100 }),
      run({ dateRanges, dimensions: [{ name: 'countryId' }], metrics: [{ name: 'sessions' }, { name: 'activeUsers' }], limit: 300 }),
      run({
        dateRanges,
        dimensions: [{ name: 'countryId' }, { name: 'eventName' }],
        metrics: [{ name: 'eventCount' }],
        dimensionFilter: { filter: { fieldName: 'eventName', inListFilter: { values: ['first_open', 'app_remove'] } } },
        limit: 500,
      }),
    ]);
  } catch (error) {
    if (error instanceof SourceFailure) throw error;
    throw new SourceFailure('GA4 did not return the app report.');
  }
  try {
    return aggregateGa4({
      rangeResponse, dailyResponse, countryResponse, eventResponse,
      start: range.start, end: range.end, countries: config.countries,
    });
  } catch (error) {
    throw new SourceFailure(error.message || 'GA4 did not return the app report.');
  }
}

export function applyInstalls(totals, rows, result) {
  totals.installs = result.installs;
  totals.uninstalls = result.uninstalls;
  for (const row of rows) {
    const source = row.code === 'OTHER' ? result.other : result.byCountry[row.code];
    if (!source) continue;
    row.installs = source.installs;
    row.uninstalls = source.uninstalls;
  }
}

export function applyVitals(totals, rows, result) {
  totals.crashes = result.crashes;
  totals.anrs = result.anrs;
  totals.crashRate = result.crashRate;
  totals.crashRateDate = result.crashRateDate;
  totals.anrRate = result.anrRate;
  totals.anrRateDate = result.anrRateDate;
  for (const row of rows) {
    const source = row.code === 'OTHER' ? result.other : result.byCountry[row.code];
    if (!source) continue;
    row.crashes = source.crashes;
    row.anrs = source.anrs;
  }
}

export function applyGa4(totals, rows, result) {
  totals.sessions = result.sessions;
  totals.activeUsers = result.activeUsers;
  totals.latestDay = result.latestDay;
  totals.latestDayActiveUsers = result.latestDayActiveUsers;
  totals.firstOpen = result.firstOpen;
  totals.appRemove = result.appRemove;
  for (const row of rows) {
    const source = row.code === 'OTHER' ? result.other : result.byCountry[row.code];
    if (!source) continue;
    row.sessions = source.sessions;
    row.activeUsers = source.activeUsers;
    row.firstOpen = source.firstOpen;
    row.appRemove = source.appRemove;
  }
}

export async function readInstalls(options) {
  const texts = await loadInstallTexts(options);
  if (!texts.length) {
    const blank = { installs: null, uninstalls: null };
    return {
      observed: false,
      installs: null,
      uninstalls: null,
      byCountry: Object.fromEntries(options.config.countries.map(code => [code, { ...blank }])),
      other: { ...blank },
      note: 'No installs_<package>_YYYYMM_country.csv file for these months was found. Missing files are not shown as zero.',
    };
  }
  const aggregated = aggregateInstallCsv(texts, {
    ...options.range,
    packageName: options.config.packageName,
    countries: options.config.countries,
  });
  if (aggregated.error) throw new SourceFailure(aggregated.error);
  return aggregated;
}
