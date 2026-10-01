/**
 * Reporting windows, as-of dates, dense date series and position weighting.
 *
 * All window arithmetic lives here so there is exactly one definition of "the
 * current period". Two rules drive the design:
 *
 *   1. Today is never assumed to be a complete data date. Windows end on a date the
 *      source has actually delivered (`asOf`), read from storage — not from the clock.
 *   2. Sources have independent delays. Search Console lags 2-3 days; GA4 finalises in
 *      ~24-48h; WordPress and sitemap snapshots are point-in-time. Each gets its own
 *      as-of date, so one request may legitimately use two different window pairs.
 *
 * Dates are ISO `YYYY-MM-DD` strings in UTC throughout, matching what the Google APIs
 * return and what is stored. String comparison is therefore also chronological
 * comparison, which is why the SQL can use plain `>=` / `<=` on dates.
 */
import { STATE, isMeasuring } from './metric-state.js';

/** Logical sources. These are also the `fetch_log.source` values. */
export const SOURCE = {
  GSC: 'gsc',
  GA4: 'ga4',
  WORDPRESS: 'wordpress',
  SITEMAP: 'gsc_sitemap',
  AHREFS: 'ahrefs',
};

/**
 * How many days behind "today" each source's latest *complete* day sits.
 *
 * Only used as an upper bound when requesting data and as a fallback when storage is
 * empty. The authoritative as-of date always comes from what was actually stored.
 */
export const DEFAULT_LAG_DAYS = {
  [SOURCE.GSC]: 3,
  [SOURCE.GA4]: 1,
  [SOURCE.WORDPRESS]: 0,
  [SOURCE.SITEMAP]: 0,
  [SOURCE.AHREFS]: 0,
};

/** The table holding dated rows for each source. */
const SOURCE_TABLE = {
  [SOURCE.GSC]: 'gsc_daily',
  [SOURCE.GA4]: 'ga4_daily',
  [SOURCE.WORDPRESS]: 'wp_content',
  [SOURCE.SITEMAP]: 'gsc_sitemap',
  [SOURCE.AHREFS]: 'ahrefs_snapshot',
};

export const tableFor = (source) => SOURCE_TABLE[source] || null;

// --- Date primitives -------------------------------------------------------

const MS_PER_DAY = 86400000;

export const toUtcDate = (isoStr) => new Date(`${String(isoStr).slice(0, 10)}T00:00:00Z`);
export const isoDate = (d) => d.toISOString().slice(0, 10);

/** Today in UTC, as an ISO date. Injectable clock so tests are deterministic. */
export const todayIso = (now = new Date()) => isoDate(now);

/** Shift an ISO date by whole days. Immutable — returns a new string. */
export const shiftDate = (isoStr, n) =>
  isoDate(new Date(toUtcDate(isoStr).getTime() + n * MS_PER_DAY));

/** Inclusive day count between two ISO dates: daysBetween(d, d) === 1. */
export const daysBetween = (start, end) =>
  Math.round((toUtcDate(end).getTime() - toUtcDate(start).getTime()) / MS_PER_DAY) + 1;

/** Every calendar date in [start, end] inclusive. Empty when end precedes start. */
export function enumerateDates(start, end) {
  const out = [];
  if (!start || !end || end < start) return out;
  for (let d = String(start).slice(0, 10); d <= String(end).slice(0, 10); d = shiftDate(d, 1)) {
    out.push(d);
  }
  return out;
}

/**
 * The newest date a source could plausibly have complete data for, derived from the
 * clock and the source's lag.
 *
 * This is an upper bound for *requests* and a fallback for an empty database. It is
 * deliberately not used as a reporting anchor — reporting anchors on delivered data.
 */
export function latestCompleteDate(source, lagDays = {}, now = new Date()) {
  const lag = Number(lagDays[source] ?? DEFAULT_LAG_DAYS[source] ?? 0);
  return shiftDate(todayIso(now), -Math.max(0, lag));
}

// --- Comparison windows ----------------------------------------------------

/**
 * A current window and the equal-length window immediately before it, both ending on
 * a date the source has delivered.
 *
 * Ranges are **inclusive** on both ends and each contains exactly `days` calendar
 * dates. The previous window ends the day before the current one starts: no overlap,
 * no gap. Anchoring on `asOf` rather than on today is what stops an incomplete
 * current period from being compared against a complete previous one.
 *
 *   asOf 2026-07-23, days 28
 *     current  2026-06-26 .. 2026-07-23   (28 dates)
 *     previous 2026-05-29 .. 2026-06-25   (28 dates)
 *
 * `range`, when given, overrides both `asOf` and `days` with an explicit
 * current window — a user-picked custom date range rather than a preset
 * length anchored on the source's own as-of date. The previous window is
 * still derived the same way: equal length, immediately before it.
 *
 * @param {{asOf: string, days: number, range?: {start: string, end: string}}} o
 * @returns {{days:number, asOf:string,
 *            current:{start:string,end:string}, previous:{start:string,end:string},
 *            curStart:string, curEnd:string, prevStart:string, prevEnd:string}}
 */
export function comparisonWindows({ asOf, days, range }) {
  let curStart, curEnd, n;
  if (range) {
    curStart = range.start;
    curEnd = range.end;
    n = daysBetween(curStart, curEnd);
  } else {
    if (!asOf) throw new Error('comparisonWindows requires an asOf date');
    n = Math.max(1, Math.floor(Number(days) || 1));
    curEnd = String(asOf).slice(0, 10);
    curStart = shiftDate(curEnd, -(n - 1));
  }
  const prevEnd = shiftDate(curStart, -1);
  const prevStart = shiftDate(prevEnd, -(n - 1));
  return {
    days: n,
    asOf: curEnd,
    current: { start: curStart, end: curEnd },
    previous: { start: prevStart, end: prevEnd },
    // Flat aliases for named SQL parameter binding.
    curStart, curEnd, prevStart, prevEnd,
  };
}

// --- As-of dates read from storage ----------------------------------------

/**
 * Newest stored date for a source, optionally scoped to one site.
 *
 * Returns null when the source has no rows at all — the caller must not substitute
 * today, which would claim data exists that does not.
 */
export function sourceAsOf(db, source, { site = null, scope = null } = {}) {
  const table = tableFor(source);
  if (!table) throw new Error(`Unknown source: ${source}`);
  const where = [];
  const params = {};
  if (site) { where.push('site = @site'); params.site = site; }
  if (scope?.clause) { where.push(scope.clause); Object.assign(params, scope.params); }
  const sql = `SELECT MAX(date) AS d FROM ${table}` +
    (where.length ? ` WHERE ${where.join(' AND ')}` : '');
  try {
    return db.prepare(sql).get(params)?.d || null;
  } catch {
    // Table absent on a database created before this source existed.
    return null;
  }
}

/** Map of site → newest stored date for a source. Sites with no rows are absent. */
export function sourceAsOfBySite(db, source, { scope = null } = {}) {
  const table = tableFor(source);
  if (!table) throw new Error(`Unknown source: ${source}`);
  const sql = `SELECT site, MAX(date) AS d FROM ${table}` +
    (scope?.clause ? ` WHERE ${scope.clause}` : '') + ' GROUP BY site';
  try {
    return new Map(db.prepare(sql).all(scope?.params || {}).map((r) => [r.site, r.d]));
  } catch {
    return new Map();
  }
}

/**
 * The reporting anchor for a source: the newest delivered date, falling back to a
 * clock-derived bound only when storage is empty.
 *
 * `resolved` distinguishes the two, so callers can report "no data yet" instead of
 * presenting a window computed from nothing as though it were real.
 */
export function resolveAsOf(db, source, { site = null, scope = null, lagDays = {}, now = new Date() } = {}) {
  const stored = sourceAsOf(db, source, { site, scope });
  if (stored) return { asOf: stored, resolved: true };
  return { asOf: latestCompleteDate(source, lagDays, now), resolved: false };
}

// --- Dense date series -----------------------------------------------------

/**
 * Join stored metrics onto every calendar date in a range.
 *
 * Search Console omits dates with no rows entirely, so a raw query returns a series
 * shorter than the window and a chart plotted from it silently compresses the gaps.
 * This fills the gaps — but only where filling them is honest:
 *
 *   - source is measuring (`ok`/`stale`/`zero`) and the date has no row → 0 / `zero`
 *   - source is measuring but the date is past the site's own as-of  → null / `no_data`
 *   - source is `not_configured` / `no_access` / `error` / `no_data` → null / that state
 *
 * A failed or unconfigured source is never converted into zeros: that is the
 * difference between "this site earned nothing" and "we never asked".
 *
 * @returns {Array<{date: string, value: number|null, state: string}>} always objects,
 *   never bare numbers, so a consumer cannot mistake a null for a zero.
 */
export function denseDateSeries({
  start,
  end,
  rows = [],
  dateKey = 'date',
  valueKey = 'value',
  sourceState = STATE.OK,
  asOf = null,
}) {
  const byDate = new Map();
  for (const r of rows) {
    if (r == null) continue;
    byDate.set(String(r[dateKey]).slice(0, 10), r[valueKey]);
  }
  const measuring = isMeasuring(sourceState);
  const boundary = asOf ? String(asOf).slice(0, 10) : null;

  return enumerateDates(start, end).map((date) => {
    if (!measuring) return { date, value: null, state: sourceState };

    if (byDate.has(date)) {
      const raw = byDate.get(date);
      const n = Number(raw);
      if (raw == null || !Number.isFinite(n)) return { date, value: null, state: STATE.NO_DATA };
      return { date, value: n, state: n === 0 ? STATE.ZERO : STATE.OK };
    }
    // No row. Beyond what the source has delivered this is "not yet", not "zero".
    if (boundary && date > boundary) return { date, value: null, state: STATE.NO_DATA };
    return { date, value: 0, state: STATE.ZERO };
  });
}

/**
 * Mean of a dense series over the dates it actually covers.
 *
 * Divides by the number of measured dates rather than by the nominal window length,
 * so the average always describes the same dates the series shows. Returns null when
 * nothing was measured — never 0.
 */
export function seriesAverage(series, digits = 1) {
  const measured = (series || []).filter((p) => p && p.value != null);
  if (measured.length === 0) return null;
  const sum = measured.reduce((s, p) => s + p.value, 0);
  return Number((sum / measured.length).toFixed(digits));
}

/** Sum of a dense series' measured values, or null when nothing was measured. */
export function seriesTotal(series) {
  const measured = (series || []).filter((p) => p && p.value != null);
  if (measured.length === 0) return null;
  return measured.reduce((s, p) => s + p.value, 0);
}

// --- Position weighting ----------------------------------------------------

/**
 * Impressions-weighted average position.
 *
 *   SUM(position * impressions) / NULLIF(SUM(impressions), 0)
 *
 * `gsc_daily.position` is already an impressions-weighted mean *within* a single date
 * — that is what the Search Console API returns. Averaging those daily means with
 * AVG() weights every date equally, so one impression at position 3 counts as much as
 * a thousand impressions at position 30. Re-weighting by impressions restores the
 * position the site actually held across the window.
 *
 * NULLIF makes a zero-impression group return NULL rather than dividing by zero.
 * Position 0 does not exist in Search Console, so NULL is the only honest answer and
 * callers surface it as "no position" instead of a flattering 0.
 */
export const weightedPosition = (positionCol = 'position', impressionsCol = 'impressions') =>
  `SUM(${positionCol} * ${impressionsCol}) / NULLIF(SUM(${impressionsCol}), 0)`;

/**
 * Impressions-weighted average position restricted to rows matching `condition`.
 * Used for current-vs-previous windows in a single grouped query.
 */
export const weightedPositionWhen = (
  condition,
  positionCol = 'position',
  impressionsCol = 'impressions',
) =>
  `SUM(CASE WHEN ${condition} THEN ${positionCol} * ${impressionsCol} END) / ` +
  `NULLIF(SUM(CASE WHEN ${condition} THEN ${impressionsCol} END), 0)`;

// --- GA4 property scoping --------------------------------------------------

/**
 * A SQL clause restricting `ga4_daily` / `ga4_event` to each site's **primary** GA4
 * property.
 *
 * Sites may have two properties tracking the same website (`ga4_property_id` and
 * `ga4_property_id_alt`). Both are fetched so they can be compared, but summing them
 * double-counts every session, user, page view and event. Dashboard totals must name
 * one property per site explicitly — hence an allow-list of `(site, property_id)`
 * pairs rather than an implicit "everything for this site".
 *
 * Named parameters (not `?`) because better-sqlite3 forbids mixing named and
 * anonymous placeholders in one statement, and every caller already uses named ones.
 *
 * @param {Array<{slug:string, ga4PropertyId:string|null}>} sites
 * @param {{alias?: string, prefix?: string}} o alias qualifies the columns in joins
 * @returns {{clause: string, params: object, pairs: Array<[string,string]>}}
 */
export function primaryGa4Scope(sites, { alias = '', prefix = 'pg' } = {}) {
  const q = alias ? `${alias}.` : '';
  const pairs = (sites || [])
    .filter((s) => s && s.ga4PropertyId)
    .map((s) => [s.slug, String(s.ga4PropertyId)]);

  // No primary property anywhere: match nothing rather than everything. Returning a
  // true clause here would silently re-enable the alternate-property double count.
  if (pairs.length === 0) return { clause: '1 = 0', params: {}, pairs };

  const params = {};
  const terms = pairs.map(([slug, propertyId], n) => {
    params[`${prefix}s${n}`] = slug;
    params[`${prefix}p${n}`] = propertyId;
    return `(${q}site = @${prefix}s${n} AND ${q}property_id = @${prefix}p${n})`;
  });
  return { clause: `(${terms.join(' OR ')})`, params, pairs };
}

/** Map of site → primary GA4 property id, for sites that have one. */
export const primaryGa4Map = (sites) =>
  new Map((sites || []).filter((s) => s?.ga4PropertyId).map((s) => [s.slug, String(s.ga4PropertyId)]));
