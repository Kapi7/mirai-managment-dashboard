/**
 * Connection checker — one live probe per site, per source.
 *
 * Answers a single question: is this site actually wired up to Search Console,
 * GA4 and WordPress right now? It reads nothing from the database and writes
 * nothing to it — the result is the current state, not history.
 *
 * Server-side only. The credential path is resolved here and handed to the
 * Google clients; every message that leaves this module goes through
 * `redactPaths()` first, so a path can never ride out on a raw API error.
 */
import {
  ConfigurationError, googleCredentials, credentialStatusFor, redactPaths,
} from './config.js';
import * as gscApi from './gsc.js';
import * as ga4Api from './ga4.js';
import * as wordpress from './wordpress.js';
import * as wpCredentials from './wp-credentials.js';
import { shiftDate, todayIso } from './reporting.js';

/** External calls get one shot each; a local tool should not hang on a dead host. */
export const DEFAULT_TIMEOUT_MS = 10_000;

/** A probe, not a backfill: the smallest window that still proves data flows. */
const GA4_PROBE_DAYS = 7;

/** Cap on borrowed error text, so an API stack trace cannot become the message. */
const MAX_ERROR_CHARS = 200;

// --- Timeouts --------------------------------------------------------------

export class TimeoutError extends Error {
  constructor(ms) {
    super(`No response within ${Math.round(ms / 1000)}s.`);
    this.name = 'TimeoutError';
  }
}

/**
 * Reject if `promise` has not settled within `ms`.
 *
 * The underlying request may still be in flight afterwards — this bounds how
 * long the *check* waits, which is what the caller is waiting on.
 */
function withTimeout(promise, ms) {
  let timer;
  const limit = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new TimeoutError(ms)), ms);
  });
  return Promise.race([promise, limit]).finally(() => clearTimeout(timer));
}

/** Every shape a timeout arrives in: ours, fetch's, Node's, gRPC's. */
const isTimeout = (err) => {
  const names = [err?.name, err?.cause?.name];
  if (names.some((n) => n === 'TimeoutError' || n === 'AbortError')) return true;
  return err?.code === 'ETIMEDOUT' || err?.code === 'UND_ERR_CONNECT_TIMEOUT'
    || err?.code === 4; // gRPC DEADLINE_EXCEEDED
};

/** A one-line, length-capped rendering of an unexpected error. */
const shortError = (err) => {
  const text = `${err?.name || 'Error'}: ${err?.message || 'unknown failure'}`.replace(/\s+/g, ' ');
  return text.length > MAX_ERROR_CHARS ? `${text.slice(0, MAX_ERROR_CHARS)}…` : text;
};

// --- Search Console --------------------------------------------------------

/** Host without a `www.` prefix, lowercased — the unit properties are compared on. */
const bareHost = (host) => String(host).toLowerCase().replace(/^www\./, '');

/**
 * Break a property string into the parts that distinguish near-misses.
 * @returns {{raw: string, kind: 'domain'|'url', host: string, www: boolean,
 *            scheme: string|null, path: string}|null} null when unparseable
 */
function describeProperty(property) {
  if (!property) return null;
  if (property.startsWith('sc-domain:')) {
    const host = property.slice('sc-domain:'.length).trim();
    if (!host) return null;
    return { raw: property, kind: 'domain', host: bareHost(host), www: false, scheme: null, path: '/' };
  }
  try {
    const u = new URL(property);
    return {
      raw: property, kind: 'url', host: bareHost(u.host),
      www: /^www\./i.test(u.host), scheme: u.protocol.replace(':', ''),
      path: u.pathname || '/',
    };
  } catch {
    return null;
  }
}

/** How an accessible property differs from the configured one, in plain words. */
function differenceFrom(configured, candidate) {
  if (candidate.kind === 'domain') return 'a domain property covering the same host';
  // A domain property has no scheme or www to compare against, so the URL parts
  // of the candidate are not differences — they are the whole distinction.
  if (configured.kind === 'domain') return 'a URL property for the same host';
  const diffs = [];
  if (candidate.scheme !== configured.scheme) diffs.push(`${candidate.scheme}, not ${configured.scheme}`);
  if (candidate.www !== configured.www) diffs.push(candidate.www ? 'with the www. prefix' : 'without the www. prefix');
  if (candidate.path !== configured.path) diffs.push(`path ${candidate.path}`);
  // Same parts, different string: a trailing slash, or capitalisation.
  return diffs.length ? diffs.join(' and ') : 'the same host, written differently';
}

/**
 * The likeliest intended property among same-host candidates.
 * A domain property wins — it covers every scheme and subdomain at once.
 */
function bestAlternative(configured, candidates) {
  const score = (c) => (c.kind === 'domain' ? 4 : 0)
    + (c.scheme === configured.scheme ? 2 : 0)
    + (c.www === configured.www ? 1 : 0);
  return [...candidates].sort((a, b) => score(b) - score(a))[0];
}

/**
 * List the properties the service account can reach. One call for the whole run.
 * @returns {{status: string, entries?: object[], message?: string}}
 */
async function listGscProperties({ credentials, gscClient, timeoutMs }) {
  if (!gscClient && !credentials.configured) {
    return { status: 'not_configured', message: credentials.reason };
  }
  try {
    const client = gscClient || await gscApi.createClient(credentials.keyFile);
    const res = await withTimeout(client.sites.list({}, { timeout: timeoutMs }), timeoutMs);
    return { status: 'ok', entries: res?.data?.siteEntry || [] };
  } catch (err) {
    if (err instanceof ConfigurationError) return { status: 'not_configured', message: err.message };
    if (isTimeout(err)) return { status: 'timed_out', message: 'Search Console did not respond in time.' };
    const httpStatus = err?.response?.status || err?.code;
    if (httpStatus === 401 || httpStatus === 403) {
      return { status: 'access_denied',
        message: 'The service account cannot list Search Console properties. Check that the '
          + 'Search Console API is enabled for the project and the key is still valid.' };
    }
    return { status: 'error', message: shortError(err) };
  }
}

/**
 * Compare one site's configured property against the accessible list. Pure —
 * reports what is wrong and what to use instead, and changes nothing.
 */
function checkGsc(site, list) {
  if (!site.gscProperty) {
    return { status: 'not_configured', property: null,
      message: 'No Search Console property set in config/sites.yaml.' };
  }
  if (list.status !== 'ok') {
    return { status: list.status, property: site.gscProperty, message: list.message };
  }

  const property = site.gscProperty;
  const exact = list.entries.find((e) => e.siteUrl === property);
  if (exact) {
    // Listed but unverified: the property appears, and Search Analytics still 403s.
    if (exact.permissionLevel === 'siteUnverifiedUser') {
      return { status: 'access_denied', property,
        message: 'Listed but unverified for this service account. Re-add it under Settings → '
          + 'Users and permissions with Restricted access.' };
    }
    return { status: 'connected', property,
      message: `Exact match, ${exact.permissionLevel || 'access granted'}.` };
  }

  const configured = describeProperty(property);
  const candidates = configured
    ? list.entries.map((e) => describeProperty(e.siteUrl)).filter((d) => d && d.host === configured.host)
    : [];
  if (candidates.length > 0) {
    const best = bestAlternative(configured, candidates);
    return { status: 'property_mismatch', property, suggestion: best.raw,
      message: `Not an accessible property. Use '${best.raw}' instead — `
        + `${differenceFrom(configured, best)}.` };
  }

  if (list.entries.length === 0) {
    return { status: 'access_denied', property,
      message: 'The service account has no accessible Search Console properties yet. Add it '
        + 'under Settings → Users and permissions.' };
  }
  return { status: 'access_denied', property,
    message: `Not among the ${list.entries.length} accessible properties. Add the service `
      + 'account under Settings → Users and permissions, or create the property.' };
}

// --- GA4 -------------------------------------------------------------------

/** @returns {{client: object}|{failure: {status: string, message: string}}} */
function resolveGa4Client({ credentials, ga4Client }) {
  if (ga4Client) return { client: ga4Client };
  if (!credentials.configured) {
    return { failure: { status: 'not_configured', message: credentials.reason } };
  }
  try {
    return { client: ga4Api.createClient(credentials.keyFile) };
  } catch (err) {
    if (err instanceof ConfigurationError) {
      return { failure: { status: 'not_configured', message: err.message } };
    }
    return { failure: { status: 'error', message: shortError(err) } };
  }
}

/**
 * One small report over the last 7 complete days, primary property only.
 *
 * Dimensioned by date so an empty result means "the API answered, and there is
 * nothing" — distinct from a measured zero, which arrives as rows summing to 0.
 */
async function checkGa4(site, ga4, { timeoutMs, now }) {
  const propertyId = site.ga4PropertyId;
  if (!propertyId) {
    return { status: 'not_configured', property: null,
      message: 'No GA4 property set in config/sites.yaml.' };
  }
  if (ga4.failure) return { ...ga4.failure, property: propertyId };

  const endDate = shiftDate(todayIso(now), -1);
  const startDate = shiftDate(endDate, -(GA4_PROBE_DAYS - 1));
  try {
    const [res] = await withTimeout(ga4.client.runReport({
      property: `properties/${propertyId}`,
      dimensions: [{ name: 'date' }],
      metrics: [{ name: 'sessions' }],
      dateRanges: [{ startDate, endDate }],
      limit: GA4_PROBE_DAYS,
    }, { timeout: timeoutMs }), timeoutMs);

    const rows = res?.rows || [];
    if (rows.length === 0) {
      return { status: 'connected_no_data', property: propertyId,
        message: `Reachable, but no rows for ${startDate} → ${endDate}.` };
    }
    const sessions = rows.reduce((t, r) => t + (Number(r.metricValues?.[0]?.value) || 0), 0);
    return { status: 'connected', property: propertyId, sessions,
      message: `${sessions.toLocaleString('en-US')} sessions ${startDate} → ${endDate}.` };
  } catch (err) {
    if (isTimeout(err)) {
      return { status: 'timed_out', property: propertyId, message: 'GA4 did not respond in time.' };
    }
    if (err?.code === 7) { // PERMISSION_DENIED
      return { status: 'access_denied', property: propertyId,
        message: 'Service account needs Viewer on this property (GA4 → Admin → Property '
          + 'access management).' };
    }
    if (err?.code === 5) { // NOT_FOUND
      return { status: 'not_found', property: propertyId,
        message: `No GA4 property ${propertyId}. Check the id in config/sites.yaml.` };
    }
    if (err?.code === 3) { // INVALID_ARGUMENT
      return { status: 'error', property: propertyId,
        message: 'GA4 rejected the request — the property id is not a numeric GA4 property.' };
    }
    return { status: 'error', property: propertyId, message: shortError(err) };
  }
}

/** Confirm configured outbound-click events were actually collected recently. */
async function checkGa4Outbound(site, ga4, ga4Result, { timeoutMs, now, affiliateEvents }) {
  const propertyId = site.ga4PropertyId;
  if (!['connected', 'connected_no_data'].includes(ga4Result.status)) {
    return { status: ga4Result.status, property: propertyId,
      message: `GA4 must connect first. ${ga4Result.message || ''}`.trim() };
  }
  if (!affiliateEvents?.length) {
    return { status: 'not_configured', property: propertyId,
      message: 'No outbound-click event names are configured under settings.affiliate_events.' };
  }

  const endDate = shiftDate(todayIso(now), -1);
  const startDate = shiftDate(endDate, -(GA4_PROBE_DAYS - 1));
  try {
    const [res] = await withTimeout(ga4.client.runReport({
      property: `properties/${propertyId}`,
      dimensions: [{ name: 'eventName' }],
      metrics: [{ name: 'eventCount' }],
      dateRanges: [{ startDate, endDate }],
      dimensionFilter: { filter: { fieldName: 'eventName',
        inListFilter: { values: affiliateEvents } } },
      limit: affiliateEvents.length,
    }, { timeout: timeoutMs }), timeoutMs);
    const rows = res?.rows || [];
    const count = rows.reduce((total, row) =>
      total + (Number(row.metricValues?.[0]?.value) || 0), 0);
    if (count === 0) {
      return { status: 'not_detected', property: propertyId, events: affiliateEvents,
        message: `No ${affiliateEvents.join(' or ')} events detected ${startDate} â†’ ${endDate}.` };
    }
    const detected = rows.map((row) => row.dimensionValues?.[0]?.value).filter(Boolean);
    return { status: 'enabled', property: propertyId, events: detected, count,
      message: `${count.toLocaleString('en-US')} outbound-click events detected `
        + `${startDate} â†’ ${endDate}: ${detected.join(', ') || affiliateEvents.join(', ')}.` };
  } catch (err) {
    if (isTimeout(err)) {
      return { status: 'timed_out', property: propertyId,
        message: 'The GA4 outbound-click check did not respond in time.' };
    }
    if (err?.code === 7) {
      return { status: 'access_denied', property: propertyId,
        message: 'Service account needs Viewer on this GA4 property.' };
    }
    if (err?.code === 5) {
      return { status: 'not_found', property: propertyId,
        message: `No GA4 property ${propertyId}.` };
    }
    return { status: 'error', property: propertyId, message: shortError(err) };
  }
}

// --- WordPress -------------------------------------------------------------

/**
 * One published post from the REST API. Reuses the fetcher's own client so the
 * check exercises the exact request the nightly fetch makes.
 */
async function checkWordpress(site, { fetchImpl, timeoutMs }) {
  if (!site.wpOrigin) {
    return { status: 'not_configured', origin: null,
      message: 'No WordPress URL. Set `wordpress:` in config/sites.yaml, or `false` to skip it.' };
  }
  // Abort the socket at the deadline; the outer guard covers a fetch that ignores it.
  const timed = (url, options = {}) =>
    fetchImpl(url, { ...options, signal: AbortSignal.timeout(timeoutMs) });

  try {
    const [, , postCount, lastPostDate] = await withTimeout(
      wordpress.content(site.slug, site.wpOrigin, { fetchImpl: timed }), timeoutMs + 500);
    return { status: 'connected', origin: site.wpOrigin, postCount, lastPostDate,
      message: `${postCount.toLocaleString('en-US')} published posts`
        + `${lastPostDate ? `, newest ${lastPostDate}` : ''}.` };
  } catch (err) {
    if (isTimeout(err)) {
      return { status: 'timed_out', origin: site.wpOrigin,
        message: 'The WordPress REST API did not respond in time.' };
    }
    if (err instanceof wordpress.WpUnavailable) {
      return { status: err.code === 'invalid_response' ? 'invalid_response' : 'error',
        origin: site.wpOrigin, message: err.message };
    }
    return { status: 'error', origin: site.wpOrigin, message: shortError(err) };
  }
}

/**
 * The Aether Connector plugin: installed, keyed, and answering?
 *
 * Deliberately separate from checkWordpress above. That check asks "does this
 * site have a public REST API", which stays true whether or not the plugin is
 * there; this one asks "can the dashboard authenticate to it", and conflating
 * the two would hide a rollout gap behind a green tick.
 *
 * No key material appears in the returned object — it is sent to the browser.
 */
async function checkConnector(site, { fetchImpl, timeoutMs, keyFor }) {
  const base = { origin: site.wpOrigin, installed: null, version: null };
  if (!site.wpOrigin) {
    return { ...base, status: 'not_configured',
      message: 'No WordPress URL configured for this site.' };
  }
  const timed = (url, options = {}) =>
    fetchImpl(url, { ...options, signal: AbortSignal.timeout(timeoutMs) });

  let ping;
  try {
    ping = await withTimeout(
      wordpress.connectorPing(site.wpOrigin, { fetchImpl: timed }), timeoutMs + 500);
  } catch (err) {
    if (isTimeout(err)) {
      return { ...base, status: 'timed_out', message: 'The connector did not respond in time.' };
    }
    return { ...base, status: 'error',
      message: err instanceof wordpress.WpUnavailable ? err.message : shortError(err) };
  }

  if (!ping.installed) {
    return { ...base, status: 'not_installed', installed: false,
      message: 'The Aether Connector plugin is not installed on this site.' };
  }

  const detail = { ...base, installed: true, version: ping.version };

  if (!ping.keySet) {
    return { ...detail, status: 'no_key_on_site',
      message: `Plugin v${ping.version} is active, but no key has been generated `
        + 'on the site (Settings → Aether Connector).' };
  }
  if (!ping.https) {
    return { ...detail, status: 'insecure',
      message: `Plugin v${ping.version} is active, but the site does not see requests `
        + 'as HTTPS, so it will refuse to authenticate.' };
  }

  const key = keyFor(site.slug);
  if (!key) {
    return { ...detail, status: 'no_key_stored',
      message: `Plugin v${ping.version} is active and keyed, but the dashboard has no `
        + `key for '${site.slug}'. Run: npm run wp:key ${site.slug}` };
  }

  try {
    const report = await withTimeout(
      wordpress.connectorSite(site.wpOrigin, key, { fetchImpl: timed }), timeoutMs + 500);
    const pluginUpdates = (report.plugins || []).filter((p) => p.update_to).length;
    const posts = report.counts?.post?.publish ?? null;
    const pages = report.counts?.page?.publish ?? null;
    return {
      ...detail,
      status: 'connected',
      wpVersion: report.wp_version ?? null,
      phpVersion: report.php_version ?? null,
      coreUpdateTo: report.core_update_to ?? null,
      pluginCount: (report.plugins || []).length,
      pluginUpdates,
      posts,
      pages,
      // 0 means "the site says no", null means "the site did not say".
      blogPublic: report.blog_public ?? null,
      message: `WordPress ${report.wp_version}, PHP ${report.php_version}. `
        + `${posts ?? '—'} posts, ${pages ?? '—'} pages. `
        + `${pluginUpdates} plugin update${pluginUpdates === 1 ? '' : 's'} pending`
        + `${report.core_update_to ? `, core ${report.core_update_to} available` : ''}.`,
    };
  } catch (err) {
    if (isTimeout(err)) {
      return { ...detail, status: 'timed_out', message: 'The connector did not respond in time.' };
    }
    if (err instanceof wordpress.WpUnavailable) {
      return { ...detail, status: err.code === 'key_rejected' ? 'key_rejected' : 'error',
        message: err.message };
    }
    return { ...detail, status: 'error', message: shortError(err) };
  }
}

// --- Public web endpoints --------------------------------------------------

/** Public origin independent of whether the site uses WordPress. */
function siteOrigin(site) {
  if (site.wpOrigin) return site.wpOrigin;
  if (!site.gscProperty) return null;
  const value = site.gscProperty.startsWith('sc-domain:')
    ? `https://${site.gscProperty.slice('sc-domain:'.length)}`
    : site.gscProperty;
  try { return new URL(value).origin; } catch { return null; }
}

async function fetchPublic(url, { fetchImpl, timeoutMs }) {
  return withTimeout(fetchImpl(url, {
    redirect: 'follow',
    headers: { 'user-agent': 'Aether-SEO-Dashboard/1.0' },
    signal: AbortSignal.timeout(timeoutMs),
  }), timeoutMs + 500);
}

/** Strong maintenance-page signals visible in the rendered response itself. */
const looksLikeMaintenance = (body) => {
  const sample = String(body || '').slice(0, 200_000);
  return /<(?:title|h1)[^>]*>[^<]*(?:maintenance|under construction|coming soon)/i.test(sample)
    || /\bbriefly unavailable for scheduled maintenance\b/i.test(sample)
    || /\b(?:the )?site is temporarily unavailable\b/i.test(sample);
};

/** Homepage health: maintenance wins over the HTTP code; otherwise only 200 is live. */
async function checkStatusCode(site, deps) {
  const origin = siteOrigin(site);
  if (!origin) return { status: 'not_configured', statusCode: null,
    message: 'No public site origin can be derived from the site configuration.' };
  try {
    const res = await fetchPublic(`${origin}/`, deps);
    const statusCode = Number(res.status);
    const body = typeof res.text === 'function'
      ? await withTimeout(res.text(), deps.timeoutMs)
      : '';
    if (looksLikeMaintenance(body)) {
      return { status: 'maintenance', statusCode, url: res.url || `${origin}/`,
        message: `Maintenance page detected (HTTP ${statusCode}).` };
    }
    return { status: statusCode === 200 ? 'connected'
      : statusCode === 404 ? 'not_found' : 'error',
      statusCode, url: res.url || `${origin}/`,
      message: statusCode === 200 ? 'Homepage is live (HTTP 200).'
        : `Homepage returned HTTP ${statusCode}.` };
  } catch (err) {
    if (isTimeout(err)) return { status: 'timed_out', statusCode: null,
      message: 'The homepage did not respond in time.' };
    return { status: 'error', statusCode: null, message: shortError(err) };
  }
}

/** Existence means exactly what the operator specified: this exact path returns HTTP 200. */
async function checkPublicFile(site, path, { fetchImpl, timeoutMs }) {
  const origin = siteOrigin(site);
  const label = path.slice(1);
  if (!origin) return { status: 'not_configured', url: null,
    message: `No public site origin can be derived for ${label}.` };
  const url = new URL(path, `${origin}/`).toString();
  try {
    const res = await fetchPublic(url, { fetchImpl, timeoutMs });
    const statusCode = Number(res.status);
    if (res.body?.cancel) await res.body.cancel().catch(() => {});
    if (statusCode === 200) return { status: 'connected', url, statusCode,
      message: `${label} exists (HTTP 200).` };
    if (statusCode === 404) return { status: 'not_found', url, statusCode,
      message: `${label} returned HTTP 404.` };
    return { status: 'error', url, statusCode,
      message: `${label} returned HTTP ${statusCode}.` };
  } catch (err) {
    if (isTimeout(err)) return { status: 'timed_out', url,
      message: `${label} did not respond in time.` };
    return { status: 'error', url, message: shortError(err) };
  }
}

// --- Orchestration ---------------------------------------------------------

/** Last line of defence: no message leaves here carrying a filesystem path. */
const clean = (check) => ({ ...check, message: redactPaths(check.message) || null });

/**
 * Probe every given site. Sites run in parallel; Search Console property access
 * still needs only one shared list call per credential.
 *
 * @param {object[]} sites config-shaped sites (see config.loadConfig)
 * @param {object} [deps] injection points for tests — real clients by default
 * @returns {Promise<object[]>} one row containing all eight checks per site
 */
export async function checkConnections(sites, {
  credentials = googleCredentials(),
  registry = null,
  gscClient = null,
  ga4Client = null,
  fetchImpl = fetch,
  timeoutMs = DEFAULT_TIMEOUT_MS,
  now = new Date(),
  affiliateEvents = [],
  // Injected so tests can supply keys without a credentials file on disk.
  keyFor = wpCredentials.keyFor,
} = {}) {
  // One property list per credential the given sites actually use. A site with
  // no registry entry (or no registry at all — tests, old callers) falls back to
  // the injected default credential, preserving the original behaviour.
  const credNames = [...new Set(sites.filter((s) => s.gscProperty).map((s) => s.gscAuth || null))];
  const gscLists = new Map();
  for (const name of credNames) {
    const cred = name && registry ? registry[name] : null;
    gscLists.set(name, await listGscProperties({
      credentials: cred ? credentialStatusFor(cred) : credentials,
      gscClient, timeoutMs,
    }));
  }
  const emptyList = { status: 'ok', entries: [] };
  // GA4 clients per credential, mirroring the GSC lists above.
  const ga4Clients = new Map();
  for (const name of [...new Set(sites.filter((s) => s.ga4PropertyId).map((s) => s.ga4Auth || null))]) {
    const cred = name && registry ? registry[name] : null;
    ga4Clients.set(name, resolveGa4Client({
      credentials: cred ? credentialStatusFor(cred) : credentials, ga4Client,
    }));
  }
  const noGa4 = { failure: { status: 'not_configured', message: 'No GA4 property configured.' } };

  return Promise.all(sites.map(async (site) => {
    const gscList = gscLists.get(site.gscAuth || null) || emptyList;
    const gscResult = checkGsc(site, gscList);
    const ga4 = ga4Clients.get(site.ga4Auth || null) || noGa4;
    const ga4Promise = checkGa4(site, ga4, { timeoutMs, now });
    const outboundPromise = ga4Promise.then((ga4Result) =>
      checkGa4Outbound(site, ga4, ga4Result, { timeoutMs, now, affiliateEvents }));
    const [ga4Result, outboundResult, wpResult, connectorResult, sitemapResult,
      robotsResult, llmsResult, statusResult] = await Promise.all([
      ga4Promise,
      outboundPromise,
      checkWordpress(site, { fetchImpl, timeoutMs }),
      checkConnector(site, { fetchImpl, timeoutMs, keyFor }),
      checkPublicFile(site, '/sitemap.xml', { fetchImpl, timeoutMs }),
      checkPublicFile(site, '/robots.txt', { fetchImpl, timeoutMs }),
      checkPublicFile(site, '/llms.txt', { fetchImpl, timeoutMs }),
      checkStatusCode(site, { fetchImpl, timeoutMs }),
    ]);
    return {
      slug: site.slug,
      name: site.name,
      gsc: clean(gscResult),
      sitemap: clean(sitemapResult),
      robots: clean(robotsResult),
      llms: clean(llmsResult),
      ga4: clean(ga4Result),
      ga4Outbound: clean(outboundResult),
      wordpress: clean(wpResult),
      connector: clean(connectorResult),
      statusCode: clean(statusResult),
    };
  }));
}

// Exported for tests: property matching is the part with real logic in it.
export { describeProperty, checkGsc };
