/**
 * The AIO dashboard page (web/family) — the page the portal shows at BASE_PATH.
 *
 * No bundler is involved: the page sources are plain browser JavaScript that
 * share one scope, so they are concatenated in a fixed order inside the loader
 * (web/family/boot.js), which fetches /api/dashboard and hands the dataset over.
 * The shell HTML gets the mount prefix filled in, so the same files work at the
 * origin root in development and under /seo inside the portal.
 *
 * Assets are fingerprinted with a hash of their content and cached for a year;
 * the HTML itself is never cached, so a deploy (which restarts the service)
 * reaches every browser on its next load.
 */
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { ROOT } from './config.js';

export const FAMILY_DIR = resolve(ROOT, 'web/family');

/** Load order matters: later files use what earlier ones define. */
export const SCRIPT_ORDER = [
  'core.js', 'navigation.js', 'charts.js', 'conn.js', 'ecosystem.js', 'views-top.js', 'tabs-a.js', 'authority.js', 'tabs-b.js', 'drawer.js', 'ui.js',
];

const APP_SLOT = '/*__APP__*/';
/** A mount prefix is a plain path: /seo, /tools/seo. Anything else is refused. */
const BASE_RE = /^(\/[A-Za-z0-9._~-]+)*$/;

const cache = new Map();

/** Read and assemble everything once per directory. */
function load(dir = FAMILY_DIR) {
  if (cache.has(dir)) return cache.get(dir);
  const boot = readFileSync(resolve(dir, 'boot.js'), 'utf8');
  if (!boot.includes(APP_SLOT)) throw new Error(`${dir}/boot.js has no ${APP_SLOT} slot`);
  const sources = SCRIPT_ORDER.map((f) => `/* ---- src/${f} ---- */\n${readFileSync(resolve(dir, 'src', f), 'utf8')}`);
  const script = boot.replace(APP_SLOT, () => sources.join('\n'));
  const css = readFileSync(resolve(dir, 'style.css'), 'utf8');
  const theme = readFileSync(resolve(dir, 'theme.js'), 'utf8');
  const html = readFileSync(resolve(dir, 'index.html'), 'utf8')
    .replace('/*__THEME__*/', () => theme);
  const version = createHash('sha256').update(script).update(css).update(html).digest('hex').slice(0, 12);
  const entry = { script, css, html, version };
  cache.set(dir, entry);
  return entry;
}

/** The normalised prefix: '' at the origin root, '/seo' when mounted. */
export function basePrefix(basePath) {
  const base = !basePath || basePath === '/' ? '' : String(basePath).replace(/\/+$/, '');
  if (!BASE_RE.test(base)) throw new Error(`BASE_PATH must be a plain path like /seo — got '${basePath}'`);
  return base;
}

export function familyHtml(basePath, dir) {
  const { html, version } = load(dir);
  return html.replaceAll('%BASE%', basePrefix(basePath)).replaceAll('%VER%', version);
}
export const familyScript = (dir) => load(dir).script;
export const familyCss = (dir) => load(dir).css;
export const familyVersion = (dir) => load(dir).version;
