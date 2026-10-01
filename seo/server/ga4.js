/**
 * Google Analytics 4 Data API client.
 *
 * Server-side only. The credential path is supplied by the caller (from
 * `config.googleCredentials()`) and handed straight to the Google client
 * library — this module never reads, stores or returns the key itself.
 */
import { readGoogleCredential } from './google-credentials.js';
import { loadConfig } from './config.js';
import { BetaAnalyticsDataClient } from '@google-analytics/data';
import { ConfigurationError, CREDENTIAL_ENV_VAR } from './config.js';

const PAGE_SIZE = 100000;
const BASE_METRICS = ['sessions', 'activeUsers', 'engagedSessions', 'screenPageViews'];

/** Thrown when the service account lacks Viewer on a GA4 property. */
export class AccessDenied extends Error {}

/**
 * @param {string} keyFilename absolute path to the service-account JSON file
 * @throws {ConfigurationError} when no credential path was resolved
 */
export function createClient(keyFilename) {
  if (!keyFilename) {
    throw new ConfigurationError(
      `GA4 needs Google credentials. Set ${CREDENTIAL_ENV_VAR} in .env to the ` +
      `path of your service-account JSON file.`,
    );
  }
  return new BetaAnalyticsDataClient({ credentials: readGoogleCredential(keyFilename), fallback: true });
}

function isPermissionError(err) {
  // gRPC: 7 = PERMISSION_DENIED, 5 = NOT_FOUND
  return err?.code === 7 || err?.code === 5;
}

/** SERVICE_DISABLED is a project toggle, not a grant — the fix is different. */
function isServiceDisabled(err) {
  const details = err?.statusDetails || err?.details || [];
  const text = typeof details === 'string' ? details : JSON.stringify(details);
  return String(err?.message).includes('has not been used in project') ||
    text.includes('SERVICE_DISABLED');
}

function accessDeniedFor(err, propertyId) {
  if (isServiceDisabled(err)) {
    return new AccessDenied(
      `The Google Analytics Data API is disabled on this credential's Google Cloud ` +
      `project. Enable it once (see docs/ACCESS_GRANTS.md) and property ${propertyId} ` +
      `becomes readable — the access grant itself already exists.`,
    );
  }
  return new AccessDenied(
    `No access to GA4 property ${propertyId}. Add the service account as ` +
    `Viewer in GA4 → Admin → Property access management.`,
  );
}

function isInvalidArgument(err) {
  return err?.code === 3; // INVALID_ARGUMENT
}

export function hostFilter(propertyId) {
  const site = loadConfig().sites.find(s => s.ga4PropertyId === String(propertyId));
  return site?.hosts?.length ? { dimensionFilter: { filter: { fieldName: 'hostName', inListFilter: { values: site.hosts, caseSensitive: false } } } } : {};
}

async function runReport(client, propertyId, dimensions, metrics, startDate, endDate) {
  const rows = [];
  let offset = 0;
  for (;;) {
    let response;
    try {
      [response] = await client.runReport({
        property: `properties/${propertyId}`,
        ...hostFilter(propertyId),
        dimensions: dimensions.map((name) => ({ name })),
        metrics: metrics.map((name) => ({ name })),
        dateRanges: [{ startDate, endDate }],
        limit: PAGE_SIZE,
        offset,
      });
    } catch (err) {
      if (isPermissionError(err)) throw accessDeniedFor(err, propertyId);
      throw err;
    }
    const batch = response.rows || [];
    rows.push(...batch);
    offset += batch.length;
    if (batch.length < PAGE_SIZE || offset >= (response.rowCount || 0)) break;
  }
  return rows;
}

const toInt = (v) => {
  const n = Number(v);
  return Number.isFinite(n) ? Math.round(n) : 0;
};

/** GA4 returns YYYYMMDD; normalise to YYYY-MM-DD so it joins with GSC dates. */
const fmtDate = (d) =>
  d && d.length === 8 ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}` : d;

/**
 * Sessions/users/engagement by date and default channel group.
 * keyEvents is requested tolerantly: properties with no key events configured
 * reject the metric outright, and that must not cost us the traffic data.
 */
export async function traffic(client, site, propertyId, startDate, endDate) {
  const dims = ['date', 'sessionDefaultChannelGroup'];
  let rows;
  let hasKeyEvents = true;
  try {
    rows = await runReport(client, propertyId, dims, [...BASE_METRICS, 'keyEvents'],
      startDate, endDate);
  } catch (err) {
    if (!isInvalidArgument(err)) throw err;
    hasKeyEvents = false;
    rows = await runReport(client, propertyId, dims, BASE_METRICS, startDate, endDate);
  }

  return rows.map((r) => [
    site, propertyId,
    fmtDate(r.dimensionValues[0].value),
    r.dimensionValues[1].value || '(not set)',
    toInt(r.metricValues[0].value),
    toInt(r.metricValues[1].value),
    toInt(r.metricValues[2].value),
    toInt(r.metricValues[3].value),
    hasKeyEvents ? Number(r.metricValues[4].value || 0) : 0,
  ]);
}

/**
 * Sessions by date and country.
 *
 * `countryId` is GA4's ISO 3166-1 alpha-2 code and is stored beside the display
 * name so the UI can key off the code rather than off a localised string. GA4
 * reports '(not set)' for sessions it could not place, and that is kept: those
 * visits happened, and dropping them would make the geo split disagree with the
 * session total it is supposed to explain.
 */
export async function geography(client, site, propertyId, startDate, endDate) {
  const rows = await runReport(client, propertyId, ['date', 'country', 'countryId'],
    ['sessions', 'activeUsers', 'engagedSessions'], startDate, endDate);
  return rows.map((r) => [
    site, propertyId,
    fmtDate(r.dimensionValues[0].value),
    r.dimensionValues[1].value || '(not set)',
    r.dimensionValues[2].value || '',
    toInt(r.metricValues[0].value),
    toInt(r.metricValues[1].value),
    toInt(r.metricValues[2].value),
  ]);
}

/**
 * Sessions by date, session source and session medium — where the visit came from.
 *
 * Session-scoped (not user- or event-scoped) so the dimensions describe the same
 * unit the `sessions` metric counts. `sessionDefaultChannelGroup` is already stored
 * in ga4_daily; this is the grain underneath it, which is what distinguishes
 * google/organic from google/cpc inside one channel.
 *
 * GA4's own placeholders — '(direct)', '(none)', '(not set)' — are stored verbatim.
 * They are what was measured, and rewriting them would invent an attribution.
 */
export async function acquisition(client, site, propertyId, startDate, endDate) {
  const rows = await runReport(client, propertyId, ['date', 'sessionSource', 'sessionMedium'],
    ['sessions', 'activeUsers', 'engagedSessions'], startDate, endDate);
  return rows.map((r) => [
    site, propertyId,
    fmtDate(r.dimensionValues[0].value),
    r.dimensionValues[1].value || '(not set)',
    r.dimensionValues[2].value || '(not set)',
    toInt(r.metricValues[0].value),
    toInt(r.metricValues[1].value),
    toInt(r.metricValues[2].value),
  ]);
}

/**
 * All event counts by date and event name.
 *
 * Pulled unfiltered rather than narrowed to a known affiliate event, because
 * the affiliate event name is not confirmed yet. Once it is, the history is
 * already here — no re-fetch needed.
 */
export async function events(client, site, propertyId, startDate, endDate) {
  const rows = await runReport(client, propertyId, ['date', 'eventName'],
    ['eventCount'], startDate, endDate);
  return rows.map((r) => [
    site, propertyId,
    fmtDate(r.dimensionValues[0].value),
    r.dimensionValues[1].value || '(not set)',
    toInt(r.metricValues[0].value),
  ]);
}

/**
 * The configured affiliate events broken down by destination URL.
 *
 * Restricted to `eventNames` because linkUrl explodes cardinality — every event
 * at every URL is mostly page_view noise. The URL is stored raw; brand/geo are
 * parsed at read time (see server/brands.js). GA4 reports '(not set)' when a
 * click carried no link_url parameter, and that is kept: those clicks happened,
 * and hiding them would under-count monetization.
 *
 * @param {string[]} eventNames from settings.affiliateEvents; [] fetches nothing
 */
export async function eventLinks(client, site, propertyId, startDate, endDate, eventNames) {
  if (!eventNames || eventNames.length === 0) return [];
  const rows = [];
  let offset = 0;
  for (;;) {
    let response;
    try {
      [response] = await client.runReport({
        property: `properties/${propertyId}`,
        ...hostFilter(propertyId),
        dimensions: [{ name: 'date' }, { name: 'eventName' }, { name: 'linkUrl' }],
        metrics: [{ name: 'eventCount' }],
        dateRanges: [{ startDate, endDate }],
        dimensionFilter: { andGroup: { expressions: [
          ...(hostFilter(propertyId).dimensionFilter ? [hostFilter(propertyId).dimensionFilter] : []),
          { filter: { fieldName: 'eventName', inListFilter: { values: eventNames } } },
        ] } },
        limit: PAGE_SIZE,
        offset,
      });
    } catch (err) {
      if (isPermissionError(err)) throw accessDeniedFor(err, propertyId);
      throw err;
    }
    const batch = response.rows || [];
    rows.push(...batch);
    offset += batch.length;
    if (batch.length < PAGE_SIZE || offset >= (response.rowCount || 0)) break;
  }
  return rows.map((r) => [
    site, propertyId,
    fmtDate(r.dimensionValues[0].value),
    r.dimensionValues[1].value || '(not set)',
    r.dimensionValues[2].value || '(not set)',
    toInt(r.metricValues[0].value),
  ]);
}
