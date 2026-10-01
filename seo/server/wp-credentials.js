/**
 * WordPress connector keys — one per site, issued by the Aether Connector plugin.
 *
 * Same rule as every other credential in this project: the environment holds a
 * PATH, the file lives outside the repository, and nothing here ever travels to
 * the browser. `status()` answers whether a site has a key; the key itself is
 * returned only by `keyFor()`, which is server-side and never serialised into a
 * response body.
 *
 * The file is read once and cached, because the connection checker asks for
 * every site in one pass and re-reading per site would be pointless I/O.
 */
import { readFileSync, existsSync, statSync } from 'node:fs';
import { resolve, sep } from 'node:path';
import { ROOT } from './config.js';

export const KEYS_ENV_VAR = 'WP_CREDENTIALS_PATH';

/** Shape a key must have to be one of ours — see Aether_Auth::generate(). */
const KEY_PATTERN = /^aeth_[0-9a-f]{64}$/;

const SETUP_HINT =
  `Set ${KEYS_ENV_VAR} in .env to a JSON file kept outside this folder, shaped `
  + '{"<site-slug>": {"key": "aeth_..."}}. Generate each key in WordPress under '
  + 'Settings → Aether Connector.';

let cache = null;

/** Drop the cached file, so a newly added key is picked up without a restart. */
export function reset() {
  cache = null;
}

/**
 * Load and validate the keys file.
 *
 * Never throws: a missing or malformed file is a *configuration* state, not an
 * error, and must not take down a connection check that also covers GA4 and
 * Search Console.
 *
 * @returns {{configured: boolean, reason: string|null, keys: object, invalid: string[]}}
 */
function load() {
  if (cache) return cache;

  const raw = (process.env[KEYS_ENV_VAR] || '').trim();
  const empty = (reason) => ({ configured: false, reason, keys: {}, invalid: [] });

  if (!raw) {
    cache = empty(`No WordPress connector keys configured (${KEYS_ENV_VAR} is unset). ${SETUP_HINT}`);
    return cache;
  }

  const path = resolve(ROOT, raw);
  if (path.startsWith(ROOT + sep)) {
    cache = empty(
      `${KEYS_ENV_VAR} points inside this repository, where a key could be committed. `
      + 'Move the file outside the project folder.',
    );
    return cache;
  }
  if (!existsSync(path)) {
    cache = empty(`${KEYS_ENV_VAR} points at a file that does not exist. ${SETUP_HINT}`);
    return cache;
  }
  if (!statSync(path).isFile()) {
    cache = empty(`${KEYS_ENV_VAR} must point at a JSON file, not a folder. ${SETUP_HINT}`);
    return cache;
  }

  let parsed;
  try {
    parsed = JSON.parse(readFileSync(path, 'utf8'));
  } catch (err) {
    // The message deliberately carries no path and no file content.
    cache = empty(`The WordPress keys file is not valid JSON (${err.message}).`);
    return cache;
  }

  const keys = {};
  const invalid = [];
  for (const [slug, entry] of Object.entries(parsed || {})) {
    const key = typeof entry === 'string' ? entry : entry?.key;
    if (typeof key === 'string' && KEY_PATTERN.test(key)) keys[slug] = key;
    else invalid.push(slug);
  }

  cache = {
    configured: Object.keys(keys).length > 0,
    reason: Object.keys(keys).length > 0 ? null
      : `The WordPress keys file holds no usable keys. ${SETUP_HINT}`,
    keys,
    invalid,
  };
  return cache;
}

/**
 * Whether any key is configured at all, and which entries were unusable.
 * Safe to send to the browser: names slugs, never keys or paths.
 */
export function status() {
  const { configured, reason, keys, invalid } = load();
  return { configured, reason, slugs: Object.keys(keys).sort(), invalid };
}

/** Whether this specific site has a usable key. Safe for the browser. */
export function hasKey(slug) {
  return Boolean(load().keys[slug]);
}

/**
 * The key for one site, or null.
 * SERVER-SIDE ONLY — must never be placed in a response body or a log line.
 */
export function keyFor(slug) {
  return load().keys[slug] || null;
}
