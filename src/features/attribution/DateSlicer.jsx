/* eslint-disable react/prop-types -- Private control receives the report's date state. */
import { useState } from 'react';
import { CalendarDays, ChevronDown, Check } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Calendar } from '@/components/ui/calendar';
import { useIsMobile } from '@/hooks/use-mobile';
import { DATE_PRESETS, REPORT_TIMEZONE, dateLabel, presetRange, reportingToday, shiftDay, validateDates } from './dates';

const toDate = value => value ? new Date(`${value}T12:00:00`) : undefined;
const toString = date => date ? `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}` : '';

export default function DateSlicer({ preset, dates, onChange, timezone = REPORT_TIMEZONE }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(dates);
  const mobile = useIsMobile();
  const today = reportingToday(new Date(), timezone);
  const error = validateDates(draft, today);
  const initialMonth = !mobile && dates.start.slice(0, 7) === today.slice(0, 7) ? shiftDay(`${today.slice(0, 7)}-01`, -1) : dates.start;
  const choose = id => { onChange(id, presetRange(id, today)); setOpen(false); };
  return <div className="at-date-toolbar">
    <div className="at-date-quick"><span className="at-control-label">Period</span><div className="at-date-chips" role="group" aria-label="Quick date ranges">
      {DATE_PRESETS.slice(0, 5).map(p => <button key={p.id} className={`m-chip at-date-chip ${preset === p.id ? 'on' : ''}`} aria-pressed={preset === p.id} title={p.id === '3' ? 'Three calendar days, including today' : p.label} onClick={() => choose(p.id)}>{p.label.replace(' complete', '')}</button>)}
    </div></div>
    <Popover open={open} onOpenChange={next => { if (next) setDraft(dates); setOpen(next); }}>
      <PopoverTrigger asChild><button className={`at-date-trigger ${preset === 'custom' ? 'is-custom' : ''}`} aria-label="Choose date range"><CalendarDays size={16} /><span>{dateLabel(dates.start)}{dates.start !== dates.end && ` – ${dateLabel(dates.end)}`}</span><ChevronDown size={14} /></button></PopoverTrigger>
      <PopoverContent className="at-date-popover" align="end" sideOffset={10} collisionPadding={12} aria-label="Choose reporting dates">
        <div className="at-date-popover-head"><div><strong>Choose dates</strong><p>Reporting time zone · {timezone}</p></div><CalendarDays size={18} /></div>
        <div className="at-date-picker-body"><div className="at-date-presets" role="group" aria-label="Date presets">{DATE_PRESETS.map(p => <button key={p.id} className={preset === p.id ? 'active' : ''} onClick={() => choose(p.id)}>{p.label}{preset === p.id && <Check size={13} />}</button>)}<span>Select a range on the calendar for custom dates.</span></div>
          <Calendar mode="range" defaultMonth={toDate(initialMonth)} selected={{ from: toDate(draft.start), to: toDate(draft.end) }} onSelect={range => setDraft({ start: toString(range?.from), end: toString(range?.to) })} numberOfMonths={mobile ? 1 : 2} disabled={{ after: toDate(today) }} toMonth={toDate(today)} className="at-date-calendar" />
        </div>
        <div className="at-date-inputs"><label>From<input aria-label="Start date" type="date" value={draft.start} max={today} onInput={e => setDraft(current => ({ ...current, start: e.target.value }))} /></label><span aria-hidden="true">→</span><label>To<input aria-label="End date" type="date" value={draft.end} max={today} onInput={e => setDraft(current => ({ ...current, end: e.target.value }))} /></label></div>
        <div className="at-date-popover-footer"><span aria-live="polite">{error || `Up to 93 days${draft.end === today ? ' · Today is still in progress' : ''}`}</span><div><button className="m-chip" onClick={() => setOpen(false)}>Cancel</button><button className="m-chip on" disabled={!!error} onClick={() => { onChange('custom', draft); setOpen(false); }}>Apply dates</button></div></div>
      </PopoverContent>
    </Popover>
  </div>;
}
