import test from 'node:test';
import assert from 'node:assert/strict';
import { presetRange, reportingToday, validateDates } from '../../src/features/attribution/dates.js';
import { reportRange } from '../server/report.js';

test('quick ranges are inclusive and cross month/year/leap boundaries correctly', () => {
  assert.deepEqual(presetRange('today', '2026-10-23'), { start: '2026-10-23', end: '2026-10-23' });
  assert.deepEqual(presetRange('yesterday', '2026-01-01'), { start: '2025-12-31', end: '2025-12-31' });
  assert.deepEqual(presetRange('3', '2024-03-01'), { start: '2024-02-28', end: '2024-03-01' });
  assert.deepEqual(presetRange('7', '2026-10-23'), { start: '2026-10-16', end: '2026-10-22' });
  assert.deepEqual(presetRange('28', '2026-10-23'), { start: '2026-09-25', end: '2026-10-22' });
  assert.deepEqual(presetRange('lastmonth', '2026-01-01'), { start: '2025-12-01', end: '2025-12-31' });
  assert.deepEqual(presetRange('mtd', '2026-10-23'), { start: '2026-10-01', end: '2026-10-22' });
  assert.equal(validateDates({ start: '2026-02-30', end: '2026-03-01' }, '2026-10-23').length > 0, true);
  assert.equal(validateDates({ start: '2026-10-01', end: '2026-10-23' }, '2026-10-23'), '');
});

test('Today follows the shop calendar across UTC midnight and DST, on client and server', () => {
  for (const [instant, today] of [['2026-10-23T21:30:00Z', '2026-10-24'], ['2026-10-25T22:30:00Z', '2026-10-26']]) {
    const now = new Date(instant);
    assert.equal(reportingToday(now), today);
    const range = reportRange(presetRange('today', reportingToday(now)), now);
    assert.equal(range.start, today); assert.equal(range.end, today); assert.equal(range.days, 1);
    assert.equal(reportRange({}, now).end, range.previousEnd);
  }
  const three = reportRange(presetRange('3', '2026-10-23'), new Date('2026-10-23'));
  assert.equal(three.days, 3); assert.equal(three.previousStart, '2026-10-18'); assert.equal(three.previousEnd, '2026-10-20');
});
