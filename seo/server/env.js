/**
 * Minimal `.env` loader.
 *
 * Zero-dependency on purpose: this is a local tool with a two-line env file and
 * no build-time config step, so a parser is cheaper than a dependency.
 *
 * Real environment variables always win over the file, so a shell variable or a
 * Task Scheduler setting can override `.env` without editing it.
 *
 * The file holds *paths*, never secret material — see .env.example.
 */
import { existsSync, readFileSync } from 'node:fs';

const LINE = /^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/;

/** Strip surrounding quotes, or a trailing ` # comment` on unquoted values. */
function unquote(rawValue) {
  const value = rawValue.trim();
  const quote = value[0];
  if (value.length > 1 && (quote === '"' || quote === "'") && value.endsWith(quote)) {
    const inner = value.slice(1, -1);
    return quote === '"' ? inner.replace(/\\n/g, '\n') : inner;
  }
  return value.replace(/\s+#.*$/, '').trim();
}

/** Parse env-file text into a plain object. Exported for testing. */
export function parseEnv(text) {
  const out = {};
  for (const line of text.split(/\r?\n/)) {
    if (!line.trim() || line.trimStart().startsWith('#')) continue;
    const match = LINE.exec(line);
    if (!match) continue;
    out[match[1]] = unquote(match[2]);
  }
  return out;
}

/**
 * Load `path` into process.env without overwriting variables already set.
 * A missing file is not an error — the environment may be configured directly.
 *
 * @returns {string[]} names of the variables this call applied
 */
export function loadEnvFile(path) {
  if (!existsSync(path)) return [];
  let parsed;
  try {
    parsed = parseEnv(readFileSync(path, 'utf8'));
  } catch (err) {
    console.warn(`Warning: could not read ${path} — ${err.message}`);
    return [];
  }
  const applied = [];
  for (const [key, value] of Object.entries(parsed)) {
    if (process.env[key] !== undefined) continue;
    process.env[key] = value;
    applied.push(key);
  }
  return applied;
}
