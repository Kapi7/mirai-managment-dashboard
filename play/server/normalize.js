import { FOCUS_COUNTRIES } from './config.js';

export const COUNTRY_NAMES = Object.freeze({
  US: 'United States',
  AU: 'Australia',
  GB: 'United Kingdom',
  CA: 'Canada',
  IL: 'Israel',
  OTHER: 'Other countries',
});

export const DEFINITIONS = Object.freeze({
  installs: 'Daily device installs from the Play Console country export (installs_<package>_YYYYMM_country.csv). Not GA4 first_open.',
  uninstalls: 'Daily device uninstalls from the same Play Console country export. Not GA4 app_remove.',
  crashes: 'Play Developer Reporting errorReportCount where reportType is CRASH. A user-perceived crash rate is separate and is not a count. Error counts have no country breakdown.',
  anrs: 'Play Developer Reporting errorReportCount where reportType is ANR. Error counts have no country breakdown.',
  crashRate: 'Latest daily user-perceived crash rate in the selected range. Rates are not averaged.',
  anrRate: 'Latest daily user-perceived ANR rate in the selected range. Rates are not averaged.',
  sessions: 'GA4 sessions for the Firebase app property in PLAY_GA4_PROPERTY_ID. Not Shopify sessions and not the mirai-skin.com website property.',
  activeUsers: 'GA4 active users across the selected dates. This is not the sum of daily active users.',
  latestDayActiveUsers: 'GA4 active users on the latest date the app property returned. This is the daily figure.',
  firstOpen: 'GA4 first_open events. A proxy for first opens, not Play install counts.',
  appRemove: 'GA4 app_remove events, when Firebase records them. Not a Play uninstall count.',
});

export function emptyMetrics() {
  return {
    installs: null,
    uninstalls: null,
    crashes: null,
    anrs: null,
    crashRate: null,
    crashRateDate: null,
    anrRate: null,
    anrRateDate: null,
    sessions: null,
    activeUsers: null,
    latestDay: null,
    latestDayActiveUsers: null,
    firstOpen: null,
    appRemove: null,
  };
}

export function countryRows(countries = FOCUS_COUNTRIES) {
  return [...countries, 'OTHER'].map(code => ({
    code,
    name: COUNTRY_NAMES[code] || code,
    installs: null,
    uninstalls: null,
    crashes: null,
    anrs: null,
    sessions: null,
    activeUsers: null,
    firstOpen: null,
    appRemove: null,
  }));
}

export function shiftIso(iso, days) {
  const [year, month, day] = iso.split('-').map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function validDate(value) {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)
    && Number.isFinite(Date.parse(`${value}T00:00:00Z`))
    && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
}

export function reportRange(query = {}, now = new Date()) {
  const today = now.toISOString().slice(0, 10);
  const end = query.end || shiftIso(today, -1);
  const start = query.start || shiftIso(end, -6);
  const message = 'Choose a valid UTC date range of up to 93 days, ending today or earlier.';
  if (!validDate(start) || !validDate(end) || start > end || end > today) throw new RangeError(message);
  const days = Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86400000) + 1;
  if (days > 93) throw new RangeError(message);
  return { start, end, days, timeZone: 'UTC' };
}

export function monthsInRange(start, end) {
  const months = [];
  let year = Number(start.slice(0, 4));
  let month = Number(start.slice(5, 7));
  const endKey = end.slice(0, 7);
  for (let guard = 0; guard < 6; guard += 1) {
    months.push(`${year}${String(month).padStart(2, '0')}`);
    if (`${year}-${String(month).padStart(2, '0')}` === endKey) return months;
    month += 1;
    if (month === 13) { month = 1; year += 1; }
  }
  return months;
}

export function installFilePattern(packageName) {
  const escaped = packageName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`^installs_${escaped}_(\\d{6})_country\\.csv$`);
}

export function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = '';
  let quoted = false;
  const input = String(text).replace(/^\uFEFF/, '');
  for (let i = 0; i < input.length; i += 1) {
    const ch = input[i];
    if (quoted) {
      if (ch === '"') {
        if (input[i + 1] === '"') { cell += '"'; i += 1; }
        else quoted = false;
      } else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ',') { row.push(cell); cell = ''; }
    else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && input[i + 1] === '\n') i += 1;
      row.push(cell);
      cell = '';
      if (row.some(value => value.length)) rows.push(row);
      row = [];
    } else cell += ch;
  }
  if (cell.length || row.length) {
    row.push(cell);
    if (row.some(value => value.length)) rows.push(row);
  }
  return rows;
}

function headerMap(headers) {
  return new Map(headers.map((header, index) => [String(header).trim().toLowerCase(), index]));
}

function cell(row, map, name) {
  const index = map.get(name);
  return index == null ? undefined : row[index];
}

function integerCell(value) {
  const text = String(value ?? '').trim();
  if (!text || !/^-?\d+$/.test(text)) return null;
  return Number(text);
}

function normalizeDay(value) {
  const text = String(value ?? '').trim();
  if (validDate(text)) return text;
  if (/^\d{8}$/.test(text)) {
    const iso = `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`;
    return validDate(iso) ? iso : null;
  }
  return null;
}

function add(current, value) {
  if (value == null) return current;
  return (current == null ? 0 : current) + value;
}

/**
 * Sum Play Console country install exports.
 * A missing country stays null. An explicit 0 stays 0.
 * Daily device installs are used; daily user installs are not a substitute.
 */
export function aggregateInstallCsv(texts, { start, end, packageName, countries = FOCUS_COUNTRIES }) {
  const seen = new Map();
  let rowsRead = 0;
  for (const text of texts) {
    if (String(text).length > 5_000_000) {
      return { error: 'An install export is too large, so install totals are hidden.' };
    }
    const table = parseCsv(text);
    if (!table.length) return { error: 'An install export is empty, so install totals are hidden.' };
    const columns = headerMap(table[0]);
    for (const name of ['date', 'country', 'daily device installs', 'daily device uninstalls']) {
      if (!columns.has(name)) return { error: 'The install export is missing Daily Device Installs or Daily Device Uninstalls, so install totals are hidden.' };
    }
    const hasPackage = columns.has('package name');
    for (const raw of table.slice(1)) {
      rowsRead += 1;
      if (rowsRead > 100_000) return { error: 'The install export has too many rows, so install totals are hidden.' };
      if (hasPackage && String(cell(raw, columns, 'package name') || '').trim() !== packageName) continue;
      const date = normalizeDay(cell(raw, columns, 'date'));
      const country = String(cell(raw, columns, 'country') || '').trim().toUpperCase();
      if (!date || date < start || date > end) continue;
      if (!/^[A-Z]{2}$/.test(country)) return { error: 'Install export country values are not 2-letter codes, so totals are hidden.' };
      const installs = integerCell(cell(raw, columns, 'daily device installs'));
      const uninstalls = integerCell(cell(raw, columns, 'daily device uninstalls'));
      if (installs == null || uninstalls == null) return { error: 'An install export row did not contain whole-number device counts, so totals are hidden.' };
      const key = `${date}|${country}`;
      const previous = seen.get(key);
      if (previous && (previous.installs !== installs || previous.uninstalls !== uninstalls)) {
        return { error: 'The install export has conflicting rows for the same date and country, so install totals are hidden.' };
      }
      if (!previous) seen.set(key, { country, installs, uninstalls });
    }
  }

  if (!seen.size) {
    return {
      observed: false,
      installs: null,
      uninstalls: null,
      byCountry: Object.fromEntries(countries.map(code => [code, { installs: null, uninstalls: null }])),
      other: { installs: null, uninstalls: null },
      note: 'No install rows for this package fell inside the selected dates. Missing rows are not shown as zero.',
    };
  }

  const byCountry = Object.fromEntries(countries.map(code => [code, { installs: null, uninstalls: null }]));
  const other = { installs: null, uninstalls: null };
  let installs = null;
  let uninstalls = null;
  for (const row of seen.values()) {
    installs = add(installs, row.installs);
    uninstalls = add(uninstalls, row.uninstalls);
    const target = byCountry[row.country] || other;
    target.installs = add(target.installs, row.installs);
    target.uninstalls = add(target.uninstalls, row.uninstalls);
  }
  return {
    observed: true,
    installs,
    uninstalls,
    byCountry,
    other,
    note: 'Daily device installs and uninstalls from the Play Console country export. Countries with no row stay blank.',
  };
}

export function metricNumber(metric) {
  if (!metric || typeof metric !== 'object') return null;
  const raw = metric.decimalValue?.value ?? metric.integerValue ?? metric.stringValue;
  if (raw == null || raw === '') return null;
  if (!/^-?\d+(\.\d+)?$/.test(String(raw))) return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

function playDate(value) {
  if (!value || !value.year || !value.month || !value.day) return null;
  const iso = `${String(value.year).padStart(4, '0')}-${String(value.month).padStart(2, '0')}-${String(value.day).padStart(2, '0')}`;
  return validDate(iso) ? iso : null;
}

function dimensionMap(row) {
  return Object.fromEntries((row.dimensions || []).map(item => [item.dimension, String(item.stringValue ?? item.int64Value ?? '')]));
}

function metricMap(row) {
  return Object.fromEntries((row.metrics || []).map(item => [item.metric, metricNumber(item)]));
}

export function aggregateVitals({ errorRows = [], crashRows = [], anrRows = [], start, end, countries = FOCUS_COUNTRIES, complete = true }) {
  if (!complete) return { error: 'Play Developer Reporting returned a partial page, so crash and ANR totals are hidden.' };
  const byCountry = Object.fromEntries(countries.map(code => [code, { crashes: null, anrs: null }]));
  const other = { crashes: null, anrs: null };
  let crashes = null;
  let anrs = null;
  for (const row of errorRows) {
    const date = playDate(row.startTime);
    if (!date || date < start || date > end) continue;
    const dimensions = dimensionMap(row);
    const count = metricMap(row).errorReportCount;
    if (count == null) return { error: 'Play Developer Reporting omitted an error count, so crash and ANR totals are hidden.' };
    const type = String(dimensions.reportType || '').toUpperCase();
    const field = type === 'CRASH' ? 'crashes' : type === 'ANR' ? 'anrs' : null;
    if (!field) continue;
    const country = String(dimensions.countryCode ?? '').trim().toUpperCase();
    if (country) {
      const target = byCountry[country] || other;
      target[field] = add(target[field], count);
    }
    if (field === 'crashes') crashes = add(crashes, count);
    else anrs = add(anrs, count);
  }
  const crashRate = latestRate(crashRows, 'userPerceivedCrashRate', start, end);
  const anrRate = latestRate(anrRows, 'userPerceivedAnrRate', start, end);
  if (crashRate.error) return { error: crashRate.error };
  if (anrRate.error) return { error: anrRate.error };
  const countrySplit = Object.values(byCountry).some(row => row.crashes != null || row.anrs != null)
    || other.crashes != null || other.anrs != null;
  const any = crashes != null || anrs != null || crashRate.value != null || anrRate.value != null || countrySplit;
  const countryNote = (crashes != null || anrs != null) && !countrySplit
    ? ' Crash and ANR counts are for the whole app; Play error counts have no country breakdown, so those cells stay blank.'
    : '';
  return {
    observed: any,
    crashes,
    anrs,
    crashRate: crashRate.value,
    crashRateDate: crashRate.date,
    anrRate: anrRate.value,
    anrRateDate: anrRate.date,
    byCountry,
    other,
    note: any
      ? `Play Developer Reporting error reports.${countryNote} Counts are blank when the API returns no row. User-perceived rates are the latest daily rate in the range, not an average.`
      : 'Play Developer Reporting returned no crash or ANR rows for these dates. Missing rows are not shown as zero.',
  };
}

function latestRate(rows, metric, start, end) {
  const matching = [];
  for (const row of rows) {
    const date = playDate(row.startTime);
    if (!date || date < start || date > end) continue;
    if ((row.dimensions || []).length) return { error: 'Play returned a crash or ANR rate split this report does not combine, so rates are hidden.' };
    const value = metricMap(row)[metric];
    if (value == null) return { error: 'Play omitted a crash or ANR rate, so rates are hidden.' };
    matching.push({ date, value });
  }
  if (!matching.length) return { value: null, date: null };
  const latest = matching.map(item => item.date).sort().at(-1);
  const sameDay = matching.filter(item => item.date === latest);
  if (sameDay.length !== 1) return { error: 'Play returned more than one crash or ANR rate for the latest day, so rates are hidden.' };
  return { value: sameDay[0].value, date: latest };
}

function ga4Number(value) {
  if (value == null || value === '') return null;
  if (!/^-?\d+(\.\d+)?$/.test(String(value))) {
    throw new Error('GA4 returned a metric this report could not read, so those metrics are hidden.');
  }
  return Number(value);
}

function ga4Records(response, limit) {
  const rows = response?.rows || [];
  if ((response?.rowCount != null && Number(response.rowCount) > rows.length) || rows.length >= limit) {
    throw new Error('GA4 returned a partial result, so those metrics are hidden.');
  }
  const dimensions = (response?.dimensionHeaders || []).map(header => header.name);
  const metrics = (response?.metricHeaders || []).map(header => header.name);
  return rows.map(row => {
    const record = {};
    dimensions.forEach((name, index) => { record[name] = row.dimensionValues?.[index]?.value ?? ''; });
    metrics.forEach((name, index) => { record[name] = ga4Number(row.metricValues?.[index]?.value); });
    return record;
  });
}

function ga4Day(value) {
  if (validDate(value)) return value;
  if (/^\d{8}$/.test(value)) return normalizeDay(value);
  return null;
}

export function aggregateGa4({ rangeResponse, dailyResponse, countryResponse, eventResponse, start, end, countries = FOCUS_COUNTRIES }) {
  const rangeRows = ga4Records(rangeResponse, 5);
  const dailyRows = ga4Records(dailyResponse, 100);
  const countryList = ga4Records(countryResponse, 300);
  const events = ga4Records(eventResponse, 500);
  if (rangeRows.length > 1) throw new Error('GA4 returned more than one total row, so those metrics are hidden.');

  const sessions = rangeRows[0]?.sessions ?? null;
  const activeUsers = rangeRows[0]?.activeUsers ?? null;
  const byDate = new Map();
  for (const row of dailyRows) {
    const date = ga4Day(row.date);
    if (!date || date < start || date > end) continue;
    if (byDate.has(date)) throw new Error('GA4 returned more than one row for a day, so daily active users are hidden.');
    if (row.activeUsers == null) throw new Error('GA4 omitted active users for a day, so daily active users are hidden.');
    byDate.set(date, row.activeUsers);
  }
  const latestDay = [...byDate.keys()].sort().at(-1) || null;
  const byCountry = Object.fromEntries(countries.map(code => [code, {
    sessions: null, activeUsers: null, firstOpen: null, appRemove: null,
  }]));
  const other = { sessions: null, activeUsers: null, firstOpen: null, appRemove: null };
  const seenCountries = new Set();
  for (const row of countryList) {
    const code = String(row.countryId || '').toUpperCase();
    if (row.sessions == null) throw new Error('GA4 omitted country sessions, so the country split is hidden.');
    if (seenCountries.has(code)) throw new Error('GA4 returned more than one row for a country, so the country split is hidden.');
    seenCountries.add(code);
    const target = byCountry[code] || other;
    target.sessions = add(target.sessions, row.sessions);
    if (byCountry[code]) target.activeUsers = row.activeUsers;
  }
  let firstOpen = null;
  let appRemove = null;
  for (const row of events) {
    const code = String(row.countryId || '').toUpperCase();
    const name = row.eventName;
    if (name !== 'first_open' && name !== 'app_remove') continue;
    if (row.eventCount == null) throw new Error('GA4 omitted an event count, so first_open and app_remove are hidden.');
    const field = name === 'first_open' ? 'firstOpen' : 'appRemove';
    const target = byCountry[code] || other;
    target[field] = add(target[field], row.eventCount);
    if (field === 'firstOpen') firstOpen = add(firstOpen, row.eventCount);
    else appRemove = add(appRemove, row.eventCount);
  }
  const measured = [sessions, activeUsers, latestDay, firstOpen, appRemove].some(value => value != null)
    || Object.values(byCountry).some(row => row.sessions != null || row.activeUsers != null || row.firstOpen != null || row.appRemove != null)
    || other.sessions != null || other.firstOpen != null || other.appRemove != null;
  return {
    observed: measured,
    sessions,
    activeUsers,
    latestDay,
    latestDayActiveUsers: latestDay ? byDate.get(latestDay) : null,
    firstOpen,
    appRemove,
    byCountry,
    other,
    note: measured
      ? 'Firebase / GA4 app property. Active users cover the whole range. Daily active users are the latest returned date only. first_open and app_remove are not Play install or uninstall counts.'
      : 'The GA4 app property returned no rows for these dates. Missing rows are not shown as zero.',
  };
}
