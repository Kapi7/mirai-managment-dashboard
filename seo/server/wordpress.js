/**
 * WordPress REST API client.
 *
 * One request per site returns both the total post count (from the X-WP-Total
 * response header) and the latest post date (from the single newest post), so
 * we never page through an entire archive just to count it.
 */

/** Thrown when a site has no reachable WordPress REST API (disabled, blocked,
 *  or not WordPress). Mirrors gsc.AccessDenied so the fetcher treats it the same.
 *
 *  `code` says *how* it failed, so the connection checker can tell a malformed
 *  response apart from an unreachable host without parsing the message. `cause`
 *  keeps the original error, which is where an abort/timeout is visible. */
export class WpUnavailable extends Error {
  constructor(message, { code = 'error', cause } = {}) {
    super(message, cause === undefined ? undefined : { cause });
    this.name = 'WpUnavailable';
    this.code = code;
  }
}

const iso = (d) => d.toISOString().slice(0, 10);

// --- Aether Connector plugin ----------------------------------------------

/** Header the connector plugin authenticates on. Never a query parameter:
 *  query strings are recorded in access logs and Referer headers. */
export const CONNECTOR_HEADER = 'X-Aether-Key';

/** The plugin's namespace. Not `aether/v1`, which is already taken on
 *  casinopan.com by unrelated brand-sideload routes. */
const CONNECTOR_BASE = '/wp-json/aether-connector/v1';

/**
 * A per-request cache-buster.
 *
 * Not decoration. At least one site sits behind a page cache that stores REST
 * responses keyed on the URL alone, ignoring both the key header and
 * `Cache-Control: no-store`. Verified on casinopan.com 2026-08-17: a bare URL
 * replayed an authenticated response to a caller presenting no key at all. A
 * unique URL per request means a stored copy is never retrievable by anyone
 * else. The plugin sends every no-cache header it can, but the cache ignored
 * them, so this is the half we actually control.
 */
const cacheBuster = () => `_ts=${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;

/** Build a connector URL, always cache-busted. */
function connectorUrl(origin, path) {
  const sep = path.includes('?') ? '&' : '?';
  return `${origin}${CONNECTOR_BASE}${path}${sep}${cacheBuster()}`;
}

/**
 * Is the connector plugin present? Unauthenticated, so it distinguishes
 * "plugin not installed" from "key rejected" without needing a key.
 *
 * @returns {Promise<{installed: boolean, version: string|null, keySet: boolean|null,
 *                    https: boolean|null}>}
 */
export async function connectorPing(origin, { fetchImpl = fetch } = {}) {
  let res;
  try {
    res = await fetchImpl(connectorUrl(origin, '/ping'), { headers: { Accept: 'application/json' } });
  } catch (err) {
    throw new WpUnavailable(`Could not reach ${origin} — ${err.message}`,
      { code: 'unreachable', cause: err });
  }
  if (res.status === 404) {
    return { installed: false, version: null, keySet: null, https: null };
  }
  if (!res.ok) {
    throw new WpUnavailable(`Connector ping returned HTTP ${res.status} for ${origin}.`,
      { code: 'http_error' });
  }
  let body;
  try {
    body = await res.json();
  } catch {
    throw new WpUnavailable(`Connector ping at ${origin} did not return JSON.`,
      { code: 'invalid_response' });
  }
  if (body?.connector !== 'aether') {
    return { installed: false, version: null, keySet: null, https: null };
  }
  return {
    installed: true,
    version: body.version ?? null,
    keySet: Boolean(body.key_set),
    https: Boolean(body.https),
  };
}

/**
 * The authenticated site report: versions, plugin updates, content counts.
 *
 * `key` is server-side only and must never be echoed into a response body.
 *
 * @returns {Promise<object>} the plugin's /site payload
 */
export async function connectorSite(origin, key, { fetchImpl = fetch } = {}) {
  if (!key) {
    throw new WpUnavailable('No connector key configured for this site.',
      { code: 'not_configured' });
  }

  let res;
  try {
    res = await fetchImpl(connectorUrl(origin, '/site'), {
      headers: { Accept: 'application/json', [CONNECTOR_HEADER]: key },
    });
  } catch (err) {
    throw new WpUnavailable(`Could not reach ${origin} — ${err.message}`,
      { code: 'unreachable', cause: err });
  }

  if (res.status === 404) {
    throw new WpUnavailable('The Aether Connector plugin is not installed on this site.',
      { code: 'not_installed' });
  }
  if (res.status === 401 || res.status === 403) {
    let code = null;
    try { code = (await res.json())?.code || null; } catch { /* body may be empty */ }
    const message = code === 'aether_no_key'
      ? 'No key has been generated on the site yet (Settings → Aether Connector).'
      : code === 'aether_insecure_transport'
        ? 'The site refused the request because it did not arrive over HTTPS.'
        : 'The site rejected this key. Generate a new one and store it again.';
    throw new WpUnavailable(message, { code: 'key_rejected' });
  }
  if (res.status === 429) {
    throw new WpUnavailable('Too many failed attempts; the site is throttling this address.',
      { code: 'throttled' });
  }
  if (!res.ok) {
    throw new WpUnavailable(`Connector returned HTTP ${res.status} for ${origin}.`,
      { code: 'http_error' });
  }

  let body;
  try {
    body = await res.json();
  } catch {
    throw new WpUnavailable(`Connector at ${origin} did not return JSON.`,
      { code: 'invalid_response' });
  }
  if (!body || typeof body !== 'object' || !body.wp_version) {
    throw new WpUnavailable(`Unexpected connector response from ${origin}.`,
      { code: 'invalid_response' });
  }
  return body;
}

/**
 * Fetch a content snapshot for one site.
 * @returns {[string, string, number, string|null]} wp_content upsert tuple:
 *   [site, today, postCount, lastPostDate]
 */
export async function content(site, origin, { fetchImpl = fetch } = {}) {
  const url =
    `${origin}/wp-json/wp/v2/posts?per_page=1&_fields=date&orderby=date&order=desc`;

  let res;
  try {
    res = await fetchImpl(url, { headers: { Accept: 'application/json' } });
  } catch (err) {
    throw new WpUnavailable(`Could not reach ${origin}/wp-json — ${err.message}`,
      { code: 'unreachable', cause: err });
  }

  if (res.status === 401 || res.status === 403 || res.status === 404) {
    throw new WpUnavailable(
      `WordPress REST API not available at ${origin} (HTTP ${res.status}). ` +
      `The REST API may be disabled, or this is not a WordPress site. ` +
      `Set 'wordpress: false' in config/sites.yaml to skip it.`,
      { code: 'not_available' },
    );
  }
  if (!res.ok) {
    throw new WpUnavailable(`WordPress REST API returned HTTP ${res.status} for ${origin}.`,
      { code: 'http_error' });
  }

  const total = Number(res.headers.get('x-wp-total'));
  let body;
  try {
    body = await res.json();
  } catch {
    throw new WpUnavailable(`WordPress REST API at ${origin} did not return JSON.`,
      { code: 'invalid_response' });
  }
  if (!Array.isArray(body)) {
    throw new WpUnavailable(`Unexpected WordPress REST response from ${origin}.`,
      { code: 'invalid_response' });
  }

  const postCount = Number.isFinite(total) ? total : body.length;
  const lastPostDate = body[0]?.date ? body[0].date.slice(0, 10) : null;
  return [site, iso(new Date()), postCount, lastPostDate];
}
