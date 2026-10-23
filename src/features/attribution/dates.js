export const REPORT_TIMEZONE = 'Asia/Jerusalem';
export const DATE_PRESETS = [
  { id: 'today', label: 'Today' },
  { id: 'yesterday', label: 'Yesterday' },
  { id: '3', label: 'Last 3 days' },
  { id: '7', label: 'Last 7 complete days' },
  { id: '28', label: 'Last 28 complete days' },
  { id: 'mtd', label: 'Month to yesterday' },
  { id: 'lastmonth', label: 'Last month' },
];

export function reportingToday(now = new Date(), timezone = REPORT_TIMEZONE) {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now);
  const part = type => parts.find(p => p.type === type).value;
  return `${part('year')}-${part('month')}-${part('day')}`;
}
export function shiftDay(date, days) {
  const value = new Date(`${date}T12:00:00Z`);
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0, 10);
}
export function presetRange(preset, today = reportingToday()) {
  if (preset === 'today') return { start: today, end: today };
  if (preset === '3') return { start: shiftDay(today, -2), end: today };
  const end = shiftDay(today, -1);
  if (preset === 'yesterday') return { start: end, end };
  if (preset === 'mtd') return { start: `${end.slice(0, 7)}-01`, end };
  if (preset === 'lastmonth') {
    const last = shiftDay(`${today.slice(0, 7)}-01`, -1);
    return { start: `${last.slice(0, 7)}-01`, end: last };
  }
  if (!['7', '28'].includes(preset)) throw new Error('Unknown date preset');
  return { start: shiftDay(end, 1 - Number(preset)), end };
}
export const dateLabel = date => new Date(`${date}T12:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
export function validateDates({ start, end }, today = reportingToday()) {
  const valid = value => /^\d{4}-\d{2}-\d{2}$/.test(value || '') && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
  return !valid(start) || !valid(end) || start > end || end > today || Date.parse(end) - Date.parse(start) > 92 * 86400000
    ? 'Choose a complete date range of up to 93 days, ending today or earlier.' : '';
}
