/**
 * Google Search Console Search Analytics client.
 *
 * Server-side only. The credential path is supplied by the caller (from
 * `config.googleCredentials()`) and handed straight to the Google auth
 * library — this module never reads, stores or returns the key itself.
 */
import { readGoogleCredential } from './google-credentials.js';
import { google } from 'googleapis';
import { GoogleAuth } from 'google-auth-library';
import { ConfigurationError, CREDENTIAL_ENV_VAR } from './config.js';

const SCOPES = ['https://www.googleapis.com/auth/webmasters.readonly'];
const ROW_LIMIT = 25000;
const MAX_RETRIES = 4;

/** Thrown when the service account has not been granted on a property. */
export class AccessDenied extends Error {}

/**
 * @param {string} keyFile absolute path to the service-account JSON file
 * @throws {ConfigurationError} when no credential path was resolved
 */
export async function createClient(keyFile) {
  if (!keyFile) {
    throw new ConfigurationError(
      `Search Console needs Google credentials. Set ${CREDENTIAL_ENV_VAR} in .env ` +
      `to the path of your service-account JSON file.`,
    );
  }
  const auth = new GoogleAuth({ credentials: readGoogleCredential(keyFile), scopes: SCOPES });
  return google.searchconsole({ version: 'v1', auth: await auth.getClient() });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function request(client, siteUrl, requestBody) {
  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    try {
      const res = await client.searchanalytics.query({ siteUrl, requestBody });
      return res.data.rows || [];
    } catch (err) {
      const status = err?.response?.status || err?.code;
      if (status === 401 || status === 403) {
        throw new AccessDenied(
          `No access to ${siteUrl}. Add the service account in Search Console → ` +
          `Settings → Users and permissions.`,
        );
      }
      if (status === 404) {
        throw new AccessDenied(
          `Property not found: ${siteUrl}. Check the exact URL (http vs https, ` +
          `trailing slash) in config/sites.yaml.`,
        );
      }
      if ([429, 500, 503].includes(status) && attempt < MAX_RETRIES - 1) {
        await sleep(2 ** attempt * 1000);
        continue;
      }
      throw err;
    }
  }
  return [];
}

/** Fetch every row for a date range, paging past the 25k row limit. */
async function fetchAll(client, siteUrl, startDate, endDate, dimensions) {
  const rows = [];
  let startRow = 0;
  for (;;) {
    const batch = await request(client, siteUrl, {
      startDate, endDate, dimensions,
      rowLimit: ROW_LIMIT, startRow, dataState: 'final',
    });
    rows.push(...batch);
    if (batch.length < ROW_LIMIT) break;
    startRow += ROW_LIMIT;
  }
  return rows;
}

/** Map API rows to DB tuples. keys = [date, ...extraDimensions]. */
function toTuples(site, rows, extraDims) {
  const out = [];
  for (const r of rows) {
    const keys = r.keys || [];
    if (keys.length < 1 + extraDims) continue;
    out.push([
      site, ...keys.slice(0, 1 + extraDims),
      Math.round(r.clicks || 0), Math.round(r.impressions || 0),
      r.ctr || 0, r.position || 0,
    ]);
  }
  return out;
}

export async function daily(client, site, siteUrl, start, end) {
  return toTuples(site, await fetchAll(client, siteUrl, start, end, ['date']), 0);
}

export async function pages(client, site, siteUrl, start, end) {
  return toTuples(site, await fetchAll(client, siteUrl, start, end, ['date', 'page']), 1);
}

export async function queries(client, site, siteUrl, start, end) {
  return toTuples(site, await fetchAll(client, siteUrl, start, end, ['date', 'query']), 1);
}

/**
 * Sitemap status snapshot: submitted URL counts plus per-sitemap health.
 *
 * `submitted` is what you told Google about, and is reliable. `indexed` is what
 * Google chose to index — and Google has **deprecated** that field, which now reports
 * 0 for most properties. It is still written so existing history stays intact, but
 * nothing reads it: presenting submitted URLs as "indexed pages" overstates coverage
 * and hides deindexing, which is the exact failure this dashboard exists to catch.
 * Real index coverage needs the URL Inspection API.
 *
 * @returns {object} gsc_sitemap named-parameter row
 */
export async function sitemaps(client, site, siteUrl) {
  let list;
  try {
    const res = await client.sitemaps.list({ siteUrl });
    list = res.data.sitemap || [];
  } catch (err) {
    const status = err?.response?.status || err?.code;
    if (status === 401 || status === 403) {
      throw new AccessDenied(
        `No access to sitemaps for ${siteUrl}. Add the service account in ` +
        `Search Console → Settings → Users and permissions.`,
      );
    }
    if (status === 404) {
      throw new AccessDenied(`Property not found: ${siteUrl}.`);
    }
    throw err;
  }

  let submitted = 0;
  let indexed = 0; // deprecated by Google — stored, never read. See note above.
  let errors = 0;
  let warnings = 0;
  let pending = 0;
  let lastDownloaded = null;

  for (const sm of list) {
    errors += Number(sm.errors || 0);
    warnings += Number(sm.warnings || 0);
    if (sm.isPending) pending += 1;
    const downloaded = sm.lastDownloaded ? String(sm.lastDownloaded).slice(0, 10) : null;
    if (downloaded && (!lastDownloaded || downloaded > lastDownloaded)) lastDownloaded = downloaded;
    for (const c of sm.contents || []) {
      submitted += Number(c.submitted || 0);
      indexed += Number(c.indexed || 0);
    }
  }

  return {
    site,
    date: new Date().toISOString().slice(0, 10),
    submitted,
    indexed,
    sitemapCount: list.length,
    errors,
    warnings,
    pending,
    lastDownloaded,
  };
}
