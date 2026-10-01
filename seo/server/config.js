/**
 * Configuration loading and validation.
 *
 * config/sites.yaml is the single source of truth for *sites* — which properties
 * to pull and how far back. Credentials never live there: the path to the Google
 * service-account key comes from the environment (see `googleCredentials`), so a
 * shared config file can never carry a secret.
 */
import { readFileSync, existsSync, statSync } from 'node:fs';
import { dirname, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import YAML from 'yaml';
import { loadEnvFile } from './env.js';

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const CONFIG_PATH = resolve(ROOT, 'config/sites.yaml');

// Every entry point (server, fetcher, smoke test) imports this module, so this
// is the one place `.env` needs to be loaded. Real env vars still take priority.
loadEnvFile(resolve(ROOT, '.env'));

// --- Google credentials ----------------------------------------------------

/** The environment variable holding the path to the service-account JSON file. */
export const CREDENTIAL_ENV_VAR = 'MIRAI_SEO_GOOGLE_TOKEN_PATH';
if (!process.env[CREDENTIAL_ENV_VAR] && existsSync('/etc/secrets/mirai-seo-google.json')) process.env[CREDENTIAL_ENV_VAR] = '/etc/secrets/mirai-seo-google.json';

/**
 * Credential kinds the registry accepts. Both are a *path in an env var* to a
 * JSON file normalized for the Google client libraries on the server.
 *
 *   service_account  a service-account key (`"type": "service_account"`)
 *   oauth_token      a stored user authorisation (`"type": "authorized_user"`,
 *                    i.e. client id/secret + refresh token), including Mirai’s
 *                    existing Python OAuth export.
 */
const CREDENTIAL_KINDS = new Set(['service_account', 'oauth_token']);

/** Registry when sites.yaml has no `credentials:` block — the original setup. */
const DEFAULT_CREDENTIALS = {
  mirai: { name: 'mirai', kind: 'oauth_token', envVar: CREDENTIAL_ENV_VAR },
};

/** Every env var that may hold a credential path — the redaction list. */
const credentialEnvVars = new Set([CREDENTIAL_ENV_VAR]);

/**
 * A missing or unusable credential — distinct from an API error, so callers can
 * report "not configured" rather than pretending a source failed.
 *
 * `message` is safe to show anywhere. `detail` may contain a filesystem path and
 * must stay on the server.
 */
export class ConfigurationError extends Error {
  constructor(message, { detail = null } = {}) {
    super(message);
    this.name = 'ConfigurationError';
    this.code = 'not_configured';
    this.detail = detail;
  }
}

const SETUP_HINT =
  `Set ${CREDENTIAL_ENV_VAR} to your Mirai Google OAuth or service-account JSON file, kept outside the repository.`;

/**
 * Resolve one credential's key path from its environment variable.
 *
 * Only ever touches the file's *metadata* — the credential itself is read by the
 * server-side Google credential adapter. Callers must not send
 * `keyFile` or `detail` to the browser; use `reason` there instead.
 *
 * @param {string} envVar which environment variable holds the path
 * @param {string} [hint] appended to every failure reason
 * @returns {{configured: boolean, keyFile: string|null, insideRepo: boolean,
 *            reason: string|null, detail: string|null}}
 */
export function credentialStatus(envVar, hint = SETUP_HINT) {
  const raw = (process.env[envVar] || '').trim();
  const missing = (reason, detail = null) =>
    ({ configured: false, keyFile: null, insideRepo: false, reason, detail });

  if (!raw) {
    return missing(`Google credentials are not configured (${envVar} is unset). ${hint}`);
  }
  // A relative path resolves against the project root so the variable reads the
  // same from a .bat file, a terminal, or Task Scheduler.
  const keyFile = resolve(ROOT, raw);
  if (!existsSync(keyFile)) {
    return missing(
      `${envVar} points at a file that does not exist. ${hint}`,
      keyFile,
    );
  }
  if (!statSync(keyFile).isFile()) {
    return missing(
      `${envVar} must point at a JSON file, not a folder. ${hint}`,
      keyFile,
    );
  }
  return {
    configured: true,
    keyFile,
    insideRepo: keyFile.startsWith(ROOT + sep),
    reason: null,
    detail: null,
  };
}

/** The default service-account credential — GA4 and the seogrid GSC sites. */
export function googleCredentials() {
  return credentialStatus(CREDENTIAL_ENV_VAR);
}

/**
 * Status of a registry credential (`cfg.credentials[name]`).
 * The env-var name rides in the reason so a gap names the exact line to add.
 */
export function credentialStatusFor(cred) {
  if (!cred) {
    return { configured: false, keyFile: null, insideRepo: false, detail: null,
      reason: 'Unknown credential — not defined under `credentials:` in config/sites.yaml.' };
  }
  const hint = cred.kind === 'oauth_token'
    ? `Set ${cred.envVar} in .env to the path of the stored OAuth token JSON, kept outside this folder.`
    : `Set ${cred.envVar} in .env to the path of the service-account JSON key, kept outside this folder.`;
  return credentialStatus(cred.envVar, hint);
}

/**
 * The credential path, or a ConfigurationError explaining what to set.
 * Server-side only — the returned path must never reach a client.
 */
export function requireGoogleCredentials() {
  const cred = googleCredentials();
  if (!cred.configured) throw new ConfigurationError(cred.reason, { detail: cred.detail });
  return cred.keyFile;
}

/**
 * Strip the credential path and the project root out of a message before it
 * leaves the server. Defence in depth: messages built here are already
 * path-free, but third-party errors are not under our control.
 */
export function redactPaths(text) {
  if (!text) return text;
  let out = String(text);
  // Every env var ever registered as a credential source, raw and resolved.
  for (const envVar of credentialEnvVars) {
    const configured = (process.env[envVar] || '').trim();
    const { keyFile } = credentialStatus(envVar);
    for (const secretPath of [keyFile, configured]) {
      if (secretPath) out = out.split(secretPath).join('<credential file>');
    }
  }
  return out.split(ROOT).join('.');
}

/**
 * Parse the `credentials:` registry from sites.yaml.
 *
 * Each entry names an env var that holds a *path* — never the credential itself,
 * so this file stays safe to share and commit. Absent block → the original
 * single-service-account setup.
 */
function parseCredentials(raw, path) {
  if (!raw) return { ...DEFAULT_CREDENTIALS };
  const out = {};
  for (const [name, def] of Object.entries(raw)) {
    const ctx = `${path} credentials.${name}`;
    const kind = String(required(def, 'kind', ctx));
    if (!CREDENTIAL_KINDS.has(kind)) {
      throw new Error(`${ctx}: kind must be one of ${[...CREDENTIAL_KINDS].join(', ')} — got '${kind}'`);
    }
    const envVar = String(required(def, 'env', ctx));
    if (def.path || def.key || def.token) {
      throw new Error(`${ctx}: credentials are referenced by env var only — remove the inline value`);
    }
    out[name] = { name, kind, envVar };
    credentialEnvVars.add(envVar);
  }
  if (Object.keys(out).length === 0) return { ...DEFAULT_CREDENTIALS };
  return out;
}

// --- Site registry ---------------------------------------------------------

function required(obj, key, context) {
  const value = obj?.[key];
  if (value === undefined || value === null || value === '') {
    throw new Error(`${context}: missing required field '${key}'`);
  }
  return value;
}

/** The site origin (https://host) to hit for WordPress REST calls, or null to skip. */
function deriveWpOrigin(wordpress, gscProperty) {
  if (wordpress === false) return null;
  if (typeof wordpress === 'string' && wordpress.trim()) {
    try { return new URL(wordpress).origin; } catch { return null; }
  }
  if (!gscProperty) return null;
  // A URL property gives the origin directly; sc-domain:host needs a scheme added.
  const asUrl = gscProperty.startsWith('sc-domain:')
    ? `https://${gscProperty.slice('sc-domain:'.length)}`
    : gscProperty;
  try { return new URL(asUrl).origin; } catch { return null; }
}

export function loadConfig(path = CONFIG_PATH) {
  if (!existsSync(path)) throw new Error(`Config not found: ${path}`);

  const raw = YAML.parse(readFileSync(path, 'utf8')) || {};
  const s = raw.settings || {};
  const rawSites = raw.sites || [];
  if (rawSites.length === 0) throw new Error(`${path}: no sites defined`);

  const credentials = parseCredentials(raw.credentials, path);

  // Credentials moved to the environment. Warn rather than throw so an old copy
  // of the file still starts — the key in it is simply ignored.
  if (s.service_account_key) {
    console.warn(
      `Warning: ${path} still sets 'service_account_key'. It is ignored — set ` +
      `${CREDENTIAL_ENV_VAR} in .env instead, then delete the line.`,
    );
  }

  // Reporting delay per source. These differ materially — Search Console revises for
  // 2-3 days, GA4 finalises in roughly 24-48h — and applying one source's delay to
  // another silently truncates the faster source's window.
  const gscLagDays = Math.max(0, Number(s.gsc_lag_days ?? 3));
  const ga4LagDays = Math.max(0, Number(s.ga4_lag_days ?? 1));

  const settings = {
    database: resolve(ROOT, process.env.MIRAI_SEO_DATABASE_PATH || s.database || 'data/mirai-seo.db'),
    // Operational Google Sheet. An id, not a credential — see the note in
    // sites.yaml. Null when unset, so callers report not_configured rather than
    // failing a call they were never configured to make.
    sheetId: s.sheet_id ? String(s.sheet_id) : null,
    // 16 months is Google's hard limit on Search Console history.
    backfillMonths: Math.max(1, Math.min(Number(process.env.MIRAI_SEO_BACKFILL_MONTHS || s.backfill_months || 16), 16)),
    refreshWindowDays: Number(s.refresh_window_days ?? 7),
    gscLagDays,
    ga4LagDays,
    // Keyed by the logical source names in reporting.SOURCE. Snapshot sources are
    // point-in-time and have no lag.
    sourceLagDays: {
      gsc: gscLagDays,
      ga4: ga4LagDays,
      wordpress: 0,
      gsc_sitemap: 0,
      ahrefs: 0,
    },
    affiliateEvents: s.affiliate_events || [],
  };

  const seen = new Set();
  const sites = rawSites.map((rs, i) => {
    const ctx = `${path} sites[${i}]`;
    const slug = String(required(rs, 'slug', ctx));
    if (seen.has(slug)) throw new Error(`${ctx}: duplicate slug '${slug}'`);
    seen.add(slug);

    const gsc = rs.gsc_property || null;
    if (gsc && !/^(https?:\/\/|sc-domain:)/.test(gsc)) {
      throw new Error(`${ctx}: gsc_property must be a full URL or sc-domain: — got '${gsc}'`);
    }

    // Which registry credential reaches this site's properties, per source.
    // Validated at load so a typo fails here, not as a silent no_access at 2am.
    const gscAuth = String(rs.gsc_auth || 'mirai');
    const ga4Auth = String(rs.ga4_auth || 'mirai');
    for (const [field, name, active] of [['gsc_auth', gscAuth, Boolean(gsc)],
      ['ga4_auth', ga4Auth, Boolean(rs.ga4_property_id)]]) {
      if (active && !credentials[name]) {
        throw new Error(
          `${ctx}: ${field} '${name}' is not defined under credentials: ` +
          `(have: ${Object.keys(credentials).join(', ')})`);
      }
    }
    const ga4 = rs.ga4_property_id ? String(rs.ga4_property_id) : null;
    const ga4Alt = rs.ga4_property_id_alt ? String(rs.ga4_property_id_alt) : null;
    if (!gsc && !ga4) {
      throw new Error(`${ctx}: site '${slug}' has neither a GA4 nor a GSC property`);
    }

    // WordPress base URL for REST calls. Explicit `wordpress:` in the config wins:
    // a string sets the origin directly, `false` disables the source. Otherwise we
    // derive the origin from the GSC property, so WordPress sites need no extra field.
    const wpOrigin = deriveWpOrigin(rs.wordpress, gsc);

    return {
      slug,
      name: String(rs.name || slug),
      vertical: String(rs.vertical || 'Unclassified'),
      platform: String(rs.platform || 'Website'),
      hosts: Array.isArray(rs.hosts) ? rs.hosts.map(String) : [],
      // The primary property is the ONLY one that may contribute to dashboard totals.
      ga4PropertyId: ga4,
      ga4PropertyIdAlt: ga4Alt,
      // Every property, for fetching and for the property-comparison diagnostic only.
      // Never use this to aggregate metrics: summing two properties that track the
      // same website double-counts sessions, users, page views and events.
      ga4PropertyIds: [ga4, ga4Alt].filter(Boolean),
      ga4Properties: [ga4, ga4Alt].filter(Boolean),
      gscProperty: gsc,
      gscAuth,
      ga4Auth,
      wpOrigin,
    };
  });

  return {
    settings,
    credentials,
    sites,
    site: (slug) => {
      const found = sites.find((x) => x.slug === slug);
      if (!found) throw new Error(`Unknown site slug: ${slug}`);
      return found;
    },
    gscSites: sites.filter((x) => x.gscProperty),
    ga4Sites: sites.filter((x) => x.ga4PropertyIds.length > 0),
    wpSites: sites.filter((x) => x.wpOrigin),
  };
}
