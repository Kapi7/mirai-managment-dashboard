import { statSync } from 'node:fs';

/** Android application id for Mirai Skin. Override with PLAY_PACKAGE_NAME. */
export const DEFAULT_PACKAGE = 'com.miraiskin.mobile';

/** Management-report country split requested for the organic promo. */
export const FOCUS_COUNTRIES = Object.freeze(['US', 'AU', 'GB', 'CA', 'IL']);

/**
 * Website GA4 properties from seo/config/sites.yaml.
 * The app report must not read these and present them as Android sessions.
 */
export const WEBSITE_GA4_PROPERTY_IDS = Object.freeze(['475812683', '530345570', '530337594']);

const PACKAGE_RE = /^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$/;
const PROPERTY_RE = /^\d{6,12}$/;
const BUCKET_RE = /^[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]$/;

export function fsStatPath(target) {
  try {
    if (!target) return null;
    const info = statSync(target);
    if (info.isFile()) return 'file';
    if (info.isDirectory()) return 'dir';
    return null;
  } catch {
    return null;
  }
}

function source(state, env, blocker) {
  return { state, env, blocker: blocker || null, note: null };
}

/**
 * Read Play / GA4 app settings from the environment.
 * Credential paths stay on the returned object for server-side reads and are
 * removed before a response is sent.
 */
export function readPlayConfig(env = process.env, { statPath = fsStatPath } = {}) {
  const packageName = (env.PLAY_PACKAGE_NAME || DEFAULT_PACKAGE).trim();
  const packageOk = PACKAGE_RE.test(packageName);
  const propertyId = (env.PLAY_GA4_PROPERTY_ID || '').trim();
  const explicitKey = (env.PLAY_GOOGLE_CREDENTIALS_PATH || '').trim();
  const ambientKey = (env.GOOGLE_APPLICATION_CREDENTIALS || '').trim();
  const bucket = (env.PLAY_STATS_BUCKET || '').trim();
  const statsDir = (env.PLAY_STATS_DIR || '').trim();
  const explicitKeyOk = Boolean(explicitKey) && statPath(explicitKey) === 'file';
  const ambientKeyOk = Boolean(ambientKey) && statPath(ambientKey) === 'file';

  return {
    packageName: packageOk ? packageName : null,
    packageError: packageOk ? null : 'PLAY_PACKAGE_NAME must be an Android application id. The default is com.miraiskin.mobile.',
    countries: [...FOCUS_COUNTRIES],
    credentialsPath: explicitKeyOk ? explicitKey : null,
    ga4CredentialsPath: explicitKeyOk ? explicitKey : (ambientKeyOk ? ambientKey : null),
    bucket: null,
    statsDir: null,
    sources: {
      playInstalls: installsSource({ bucket, statsDir, explicitKeyOk, statPath, packageOk }),
      playVitals: vitalsSource({ explicitKeyOk, packageOk }),
      ga4App: ga4Source({ propertyId, explicitKeyOk, ambientKeyOk, packageOk }),
    },
    // Retained only when the install source actually selected them.
    ...selectedInstallPaths({ bucket, statsDir, explicitKeyOk, statPath }),
  };
}

function selectedInstallPaths({ bucket, statsDir, explicitKeyOk, statPath }) {
  if (bucket && statsDir) return { bucket: null, statsDir: null };
  if (statsDir && statPath(statsDir) === 'dir' && !bucket) return { bucket: null, statsDir };
  if (bucket && BUCKET_RE.test(bucket) && explicitKeyOk && !statsDir) return { bucket, statsDir: null };
  return { bucket: null, statsDir: null };
}

function installsSource({ bucket, statsDir, explicitKeyOk, statPath, packageOk }) {
  const env = ['PLAY_STATS_BUCKET', 'PLAY_STATS_DIR', 'PLAY_GOOGLE_CREDENTIALS_PATH'];
  if (!packageOk) return source('misconfigured', env, 'PLAY_PACKAGE_NAME must be an Android application id. The default is com.miraiskin.mobile.');
  if (bucket && statsDir) return source('misconfigured', env, 'Set only one of PLAY_STATS_BUCKET or PLAY_STATS_DIR.');
  if (!bucket && !statsDir) {
    return source('not_configured', env, 'Set PLAY_STATS_BUCKET to the Play Console bulk-report Cloud Storage bucket, or PLAY_STATS_DIR to a directory of installs_<package>_YYYYMM_country.csv files. Play Developer Reporting does not provide install or uninstall counts.');
  }
  if (bucket) {
    if (bucket.startsWith('gs://') || bucket.includes('/')) {
      return source('misconfigured', env, 'PLAY_STATS_BUCKET must be the bucket name only, without gs:// or a path.');
    }
    if (!BUCKET_RE.test(bucket)) return source('misconfigured', env, 'PLAY_STATS_BUCKET is not a Cloud Storage bucket name.');
    if (!explicitKeyOk) return source('misconfigured', env, 'PLAY_STATS_BUCKET is set, but PLAY_GOOGLE_CREDENTIALS_PATH does not point at a service-account JSON file.');
    return source('ready', env, null);
  }
  if (statPath(statsDir) !== 'dir') return source('misconfigured', env, 'PLAY_STATS_DIR is set, but that directory is not available to the server.');
  return source('ready', env, null);
}

function vitalsSource({ explicitKeyOk, packageOk }) {
  const env = ['PLAY_GOOGLE_CREDENTIALS_PATH'];
  if (!packageOk) return source('misconfigured', env, 'PLAY_PACKAGE_NAME must be an Android application id. The default is com.miraiskin.mobile.');
  if (!explicitKeyOk) {
    return source('not_configured', env, 'Set PLAY_GOOGLE_CREDENTIALS_PATH to a service-account JSON key with Play Console access (Play Developer Reporting API). The account must be invited in Play Console → Users and permissions. This report does not reuse the SEO OAuth token.');
  }
  return source('ready', env, null);
}

function ga4Source({ propertyId, explicitKeyOk, ambientKeyOk, packageOk }) {
  const env = ['PLAY_GA4_PROPERTY_ID', 'PLAY_GOOGLE_CREDENTIALS_PATH', 'GOOGLE_APPLICATION_CREDENTIALS'];
  if (!packageOk) return source('misconfigured', env, 'PLAY_PACKAGE_NAME must be an Android application id. The default is com.miraiskin.mobile.');
  if (!propertyId) {
    return source('not_configured', env, 'Set PLAY_GA4_PROPERTY_ID to the Firebase-linked GA4 property for the Android app. Do not use the website property 475812683 (mirai-skin.com) or the satellite properties 530345570 and 530337594.');
  }
  if (!PROPERTY_RE.test(propertyId)) return source('misconfigured', env, 'PLAY_GA4_PROPERTY_ID must be the numeric GA4 property id for the Android app.');
  if (WEBSITE_GA4_PROPERTY_IDS.includes(propertyId)) {
    return source('misconfigured', env, 'PLAY_GA4_PROPERTY_ID matches a website GA4 property already used by SEO. Use the Android app property instead. Website sessions are not app sessions.');
  }
  if (!explicitKeyOk && !ambientKeyOk) {
    return source('misconfigured', env, 'PLAY_GA4_PROPERTY_ID is set, but neither PLAY_GOOGLE_CREDENTIALS_PATH nor GOOGLE_APPLICATION_CREDENTIALS points at a service-account JSON file with GA4 Viewer access on the app property.');
  }
  return { ...source('ready', env, null), propertyId };
}

/** Fields safe to send to the browser. Paths, bucket names and tokens are omitted. */
export function publicSources(sources) {
  return Object.fromEntries(Object.entries(sources).map(([key, value]) => [key, {
    state: value.state,
    env: value.env,
    blocker: value.blocker,
    note: value.note,
    ...(value.propertyId ? { propertyId: value.propertyId } : {}),
  }]));
}

export function redact(message, secrets = []) {
  let out = String(message || '');
  for (const secret of secrets) {
    if (secret) out = out.split(secret).join('[redacted]');
  }
  out = out.replace(/ya29\.[0-9A-Za-z\-_]+/g, '[redacted]');
  out = out.replace(/-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g, '[redacted]');
  out = out.replace(/\s+/g, ' ').trim();
  if (!out) return 'The source returned an error.';
  return out.length > 300 ? `${out.slice(0, 300)}…` : out;
}
