/**
 * Explicit states for metrics and sources.
 *
 * The rule this module exists to enforce: a numeric zero means "measured, and the
 * answer was zero". It never stands in for "not configured", "no access",
 * "nothing fetched yet" or "the fetch failed". Those are states, and a metric in
 * one of them carries `value: null` plus the state that explains it.
 *
 * Callers must not coerce a null value with `|| 0` — that reintroduces exactly the
 * ambiguity this vocabulary removes.
 */

/** The complete state vocabulary. Nothing outside this set is a valid state. */
export const STATE = {
  /** Measured, non-zero. */
  OK: 'ok',
  /** Measured, and genuinely zero. */
  ZERO: 'zero',
  /** Source is configured and was fetched, but has no row for this date/window. */
  NO_DATA: 'no_data',
  /** No property/credential configured for this source. A setup gap, not a failure. */
  NOT_CONFIGURED: 'not_configured',
  /** Configured, but the service account has not been granted on the property. */
  NO_ACCESS: 'no_access',
  /** Fetched successfully, but the newest data predates the reporting as-of date. */
  STALE: 'stale',
  /** The fetch attempt failed unexpectedly. */
  ERROR: 'error',
};

const ALL_STATES = new Set(Object.values(STATE));

/** States in which the source actually measured something. */
const MEASURING = new Set([STATE.OK, STATE.ZERO, STATE.STALE]);

/** True when a numeric value from this state is real and safe to sum or chart. */
export const isMeasuring = (state) => MEASURING.has(state);

export const isValidState = (state) => ALL_STATES.has(state);

/**
 * Wrap a raw value in its state.
 *
 * A non-measuring source state always yields `value: null` — the numeric value is
 * discarded rather than passed through, so a `COALESCE(...,0)` upstream cannot leak
 * a fake zero into the response.
 *
 * @param {number|null|undefined} value
 * @param {string} sourceState one of STATE
 * @returns {{value: number|null, state: string}}
 */
export function metricValue(value, sourceState = STATE.OK) {
  if (!isMeasuring(sourceState)) return { value: null, state: sourceState };
  if (value == null) return { value: null, state: STATE.NO_DATA };
  const n = Number(value);
  if (!Number.isFinite(n)) return { value: null, state: STATE.NO_DATA };
  if (n === 0) return { value: 0, state: STATE.ZERO };
  return { value: n, state: sourceState === STATE.STALE ? STATE.STALE : STATE.OK };
}

/**
 * Resolve a source's state for one site and one reporting window.
 *
 * Precedence is fixed and deliberate — the most actionable cause wins, so a site
 * that is both unconfigured and stale reports `not_configured` (the thing to fix)
 * rather than `stale` (a symptom of it).
 *
 *   1. not configured in sites.yaml
 *   2. not configured by credentials (fetch log said so)
 *   3. no access (grant missing)
 *   4. error (unexpected failure)
 *   5. never fetched / no rows at all      → no_data
 *   6. newest row predates the window      → no_data
 *   7. newest row predates the as-of date  → stale
 *   8. otherwise                           → ok
 *
 * @param {object}      o
 * @param {boolean}     o.configured   site has a property/origin for this source
 * @param {string|null} o.healthStatus latest fetch_log status, if any
 * @param {string|null} o.siteAsOf     newest stored date for this site+source
 * @param {string|null} o.windowStart  inclusive start of the reporting window
 * @param {string|null} o.windowEnd    the reporting as-of date for this source
 * @returns {string} one of STATE
 */
export function resolveSourceState({
  configured,
  healthStatus = null,
  siteAsOf = null,
  windowStart = null,
  windowEnd = null,
} = {}) {
  if (!configured) return STATE.NOT_CONFIGURED;
  if (healthStatus === STATE.NOT_CONFIGURED) return STATE.NOT_CONFIGURED;
  if (healthStatus === STATE.NO_ACCESS) return STATE.NO_ACCESS;
  if (healthStatus === STATE.ERROR) return STATE.ERROR;
  if (!siteAsOf) return STATE.NO_DATA;
  if (windowStart && siteAsOf < windowStart) return STATE.NO_DATA;
  if (windowEnd && siteAsOf < windowEnd) return STATE.STALE;
  return STATE.OK;
}

// --- Period-over-period change ---------------------------------------------

/**
 * Change states. `pct` is only a number for CHANGED and LOST; for the other two no
 * finite percentage exists and `pct` is null.
 */
export const CHANGE = {
  /** Both periods zero. Nothing happened either side. */
  NO_ACTIVITY: 'no_activity',
  /** Previous zero, current positive. Growth from nothing — percentage undefined. */
  NEW: 'new',
  /** Previous positive, current zero. Exactly -100%. */
  LOST: 'lost',
  /** Both periods non-zero. A real percentage. */
  CHANGED: 'changed',
};

/**
 * Period-over-period change with explicit zero-denominator semantics.
 *
 * Returning 0 for a zero denominator (the previous behaviour) claimed "no change"
 * for the most significant case there is: a page or query that went from nothing to
 * something. `pct: null` forces callers to branch on `state` instead.
 *
 * @param {number|null} cur
 * @param {number|null} prev
 * @returns {{pct: number|null, state: string}}
 */
export function changeOf(cur, prev) {
  const c = Number(cur) || 0;
  const p = Number(prev) || 0;
  if (p === 0 && c === 0) return { pct: null, state: CHANGE.NO_ACTIVITY };
  if (p === 0) return { pct: null, state: CHANGE.NEW };
  if (c === 0) return { pct: -100, state: CHANGE.LOST };
  return { pct: Number((((c - p) / p) * 100).toFixed(1)), state: CHANGE.CHANGED };
}

/** True when a change is a real decline of at least `threshold` percent. */
export function isDeclineOf(change, threshold) {
  if (change.state === CHANGE.LOST) return true;
  return change.state === CHANGE.CHANGED && change.pct <= -Math.abs(threshold);
}

/**
 * True when a change is real growth of at least `threshold` percent.
 * `new` counts: growth from zero is growth, and excluding it is what hid every
 * genuinely new query from the rising-queries panel.
 */
export function isGrowthOf(change, threshold) {
  if (change.state === CHANGE.NEW) return true;
  return change.state === CHANGE.CHANGED && change.pct >= Math.abs(threshold);
}

/** Difference of two changes in percentage points, or null when either is undefined. */
export function divergenceOf(a, b) {
  if (a.pct == null || b.pct == null) return null;
  return Number((a.pct - b.pct).toFixed(1));
}
