/** Ahrefs API v3. Credentials and all provider calls stay on the server. */
import { readFileSync, existsSync } from 'node:fs';
import { todayIso } from './reporting.js';
export const API_KEY_ENV_VAR = 'MIRAI_SEO_AHREFS_API_KEY';
const tokenPath = process.env.MIRAI_SEO_AHREFS_TOKEN_PATH || '/etc/secrets/mirai-ahrefs-token';
if (!process.env[API_KEY_ENV_VAR] && existsSync(tokenPath)) process.env[API_KEY_ENV_VAR] = readFileSync(tokenPath, 'utf8').trim();
const BASE = 'https://api.ahrefs.com/v3/';
export class AccessDenied extends Error {}
export class AhrefsUnavailable extends Error {}
export class BudgetExceeded extends Error {}
export function credentialStatus() {
  const configured = Boolean((process.env[API_KEY_ENV_VAR] || '').trim());
  return { configured, reason: configured ? null : `Set ${API_KEY_ENV_VAR} in .env to an Ahrefs API v3 key.` };
}
export function targetForSite(site) {
  const configured = site.wpOrigin || site.gscProperty;
  if (!configured) return null;
  try { return new URL(configured.startsWith('sc-domain:') ? `https://${configured.slice(10)}` : configured).origin; } catch { return null; }
}
export const nullableNumber = value => (typeof value === 'number' || (typeof value === 'string' && value.trim() !== '')) && Number.isFinite(Number(value)) && Number(value) >= 0 ? Number(value) : null;

export async function apiRequest(path, { params, body, apiKey = process.env[API_KEY_ENV_VAR], fetchImpl = fetch, onCost } = {}) {
  const key = String(apiKey || '').trim();
  if (!key) throw new AccessDenied(`Set ${API_KEY_ENV_VAR} in .env to an Ahrefs API v3 key.`);
  const url = new URL(path, BASE);
  if (!url.href.startsWith(BASE)) throw new AhrefsUnavailable('Invalid Ahrefs endpoint.');
  if (params) url.search = new URLSearchParams(params).toString();
  let response;
  try {
    response = await fetchImpl(url.href, {
      method: body ? 'POST' : 'GET', signal: AbortSignal.timeout(30000), redirect: 'error',
      headers: { Authorization: `Bearer ${key}`, Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json' } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
  } catch { throw new AhrefsUnavailable('Ahrefs could not be reached within 30 seconds. Try again later.'); }
  const cost = nullableNumber(response.headers?.get('x-api-units-cost-total-actual'));
  onCost?.(cost);
  const data = await response.json().catch(() => ({}));
  if (response.status === 401 || response.status === 403) {
    if (/api units/i.test(String(data?.error || data?.message || ''))) throw new AccessDenied('Ahrefs API units are used up for this billing period; the key itself works.');
    throw new AccessDenied('Ahrefs rejected the API key or the subscription lacks API access.');
  }
  if (!response.ok) throw new AhrefsUnavailable(response.status === 429 ? 'Ahrefs is rate limiting requests. Try again later.' : `Ahrefs returned HTTP ${response.status}. Check the request or subscription.`);
  return data;
}
export async function limitsAndUsage(options = {}) {
  const body = await apiRequest('subscription-info/limits-and-usage', options), u = body.limits_and_usage;
  if (!u || nullableNumber(u.units_usage_api_key) === null) throw new AhrefsUnavailable('Ahrefs returned no usable allowance information.');
  const remaining = (limit, used) => nullableNumber(limit) !== null && nullableNumber(used) !== null ? Math.max(0, Number(limit) - Number(used)) : null;
  const keyRemaining = remaining(u.units_limit_api_key, u.units_usage_api_key), workspaceRemaining = remaining(u.units_limit_workspace, u.units_usage_workspace);
  return { subscription: u.subscription || null, resetDate: u.usage_reset_date || null, keyRemaining, workspaceRemaining,
    remaining: workspaceRemaining === null ? null : Math.min(workspaceRemaining, keyRemaining ?? Infinity) };
}
export function requireAllowance(usage, units) {
  const remaining = nullableNumber(usage?.remaining);
  if (remaining === null || remaining < units) throw new BudgetExceeded(`This run needs up to ${units} API units. The included allowance is ${remaining === null ? 'unverified' : remaining + ' units'}. No paid request was sent.`);
}
export const PROFILE_UNITS_PER_SITE = 22;
export async function batchMetrics(sites, options = {}) {
  const { now = new Date(), extended = false } = options;
  const targets = sites.map(site => ({ site, url: targetForSite(site) })).filter(t => t.url);
  if (!targets.length) return [];
  const select = ['index', 'backlinks', 'backlinks_dofollow', 'backlinks_nofollow', 'domain_rating'];
  if (extended) select.push('refdomains', 'org_keywords', 'org_traffic');
  const body = await apiRequest('batch-analysis/batch-analysis', { ...options, body: {
    select, targets: targets.map(({ url }) => ({ url, mode: 'subdomains', protocol: 'both' })), output: 'json',
  } });
  if (!Array.isArray(body.targets)) throw new AhrefsUnavailable('Ahrefs returned an invalid Batch Analysis response.');
  const byIndex = new Map(body.targets.map(row => [Number(row.index), row]));
  return targets.map(({ site }, index) => {
    const row = byIndex.get(index);
    if (!row) throw new AhrefsUnavailable(`Ahrefs omitted target ${index} from its response.`);
    const counts = ['backlinks', 'backlinks_dofollow', 'backlinks_nofollow'].map(k => nullableNumber(row[k]));
    if (counts.some(n => n === null)) throw new AhrefsUnavailable('Ahrefs returned incomplete backlink counts; the previous snapshot was preserved.');
    const values = [site.slug, todayIso(now), ...counts, nullableNumber(row.domain_rating)];
    return extended ? [...values, ...['refdomains', 'org_keywords', 'org_traffic'].map(k => nullableNumber(row[k]))] : values;
  });
}
