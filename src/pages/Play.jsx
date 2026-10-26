import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { RefreshCw, Smartphone } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { formatCount, formatDay, formatRate, SOURCE_LABELS, sourceStateLabel } from '@/features/play/model';

function utcDay(offset) {
  const now = new Date();
  const day = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  day.setUTCDate(day.getUTCDate() + offset);
  return day.toISOString().slice(0, 10);
}

const STATUS_COPY = {
  not_configured: 'Android performance is not connected yet. Cards stay blank until Play Console exports and the Firebase app property are configured. Nothing is estimated.',
  misconfigured: 'A Play or GA4 setting is present but cannot be used. Unready sources stay blank. Nothing is estimated.',
  partial: 'Some sources reported. The others are blank. Blank is not zero.',
  ready: 'Connected sources reported for this range. A blank cell was not in the source response.',
  error: 'The configured sources did not return a usable report. No numbers were substituted.',
};

const CARDS = [
  { key: 'installs', label: 'Installs', sub: 'Play device installs' },
  { key: 'uninstalls', label: 'Uninstalls', sub: 'Play device uninstalls' },
  { key: 'crashes', label: 'Crashes', sub: 'Play error reports', rate: 'crashRate', rateDate: 'crashRateDate' },
  { key: 'anrs', label: 'ANRs', sub: 'Play error reports', rate: 'anrRate', rateDate: 'anrRateDate' },
  { key: 'sessions', label: 'Sessions', sub: 'GA4 app property' },
  { key: 'activeUsers', label: 'Active users', sub: 'GA4 range, not summed days' },
  { key: 'latestDayActiveUsers', label: 'Daily active users', sub: 'Latest GA4 day' },
];

const COLUMNS = [
  ['installs', 'Installs'],
  ['uninstalls', 'Uninstalls'],
  ['crashes', 'Crashes'],
  ['anrs', 'ANRs'],
  ['sessions', 'Sessions'],
  ['activeUsers', 'Active users'],
  ['firstOpen', 'GA4 first_open'],
  ['appRemove', 'GA4 app_remove'],
];

export default function Play() {
  const { getAuthHeader } = useAuth();
  const [start, setStart] = useState(() => utcDay(-7));
  const [end, setEnd] = useState(() => utcDay(-1));
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const invalid = !/^\d{4}-\d{2}-\d{2}$/.test(start) || !/^\d{4}-\d{2}-\d{2}$/.test(end) || start > end;

  useEffect(() => {
    const controller = new AbortController();
    if (invalid) { setLoading(false); setReport(null); return undefined; }
    setLoading(true);
    setError('');
    const params = new URLSearchParams({ start, end });
    fetch(`/play-api?${params}`, { headers: getAuthHeader(), signal: controller.signal, cache: 'no-store' })
      .then(async response => {
        const text = await response.text();
        let body;
        try { body = JSON.parse(text); } catch { body = null; }
        if (response.status === 401 || response.status === 403) throw new Error('Sign in to Mirai Management to view app performance.');
        if (!response.ok) throw new Error(body?.message || 'App performance could not be loaded.');
        if (!body?.sources || !body?.totals || !Array.isArray(body?.byCountry)) throw new Error('App performance API is not available on this server.');
        return body;
      })
      .then(body => { if (!controller.signal.aborted) setReport(body); })
      .catch(err => { if (!controller.signal.aborted) { setReport(null); setError(err.message || 'App performance could not be loaded.'); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [start, end, refresh, getAuthHeader, invalid]);

  const totals = report?.totals || {};

  return (
    <div className="m-page space-y-4">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0">
          <h1 className="text-[1.3rem] lg:text-3xl font-extrabold tracking-tight text-white flex items-center gap-2.5">
            <Smartphone className="h-6 w-6 text-rose-300" aria-hidden="true" />
            App / Play
          </h1>
          <p className="text-[#8fa0b8] text-[0.78rem] lg:text-sm mt-1 max-w-3xl">
            Android performance for {report?.packageName || 'com.miraiskin.mobile'}. Play 1.0.0 was reported live by Mirai Skin. This page does not confirm the store listing.
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Link className="m-chip" to="/Reports">Business Reports</Link>
          <Link className="m-chip" to="/Attribution">Attribution</Link>
          <button className="m-chip" type="button" onClick={() => setRefresh(value => value + 1)} disabled={loading || invalid}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            Reload
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-2">
        <label className="text-[0.72rem] text-[#8fa0b8]">Start (UTC)
          <input className="mt-1 block bg-[#101a30] border border-[#2b3a55] text-white rounded-lg px-2 py-1 text-sm" type="date" value={start} onChange={event => setStart(event.target.value)} />
        </label>
        <label className="text-[0.72rem] text-[#8fa0b8]">End (UTC)
          <input className="mt-1 block bg-[#101a30] border border-[#2b3a55] text-white rounded-lg px-2 py-1 text-sm" type="date" value={end} onChange={event => setEnd(event.target.value)} />
        </label>
        <button className="m-chip" type="button" onClick={() => { setStart(utcDay(-7)); setEnd(utcDay(-1)); }}>Last 7 days</button>
        <button className="m-chip" type="button" onClick={() => { setStart(utcDay(-28)); setEnd(utcDay(-1)); }}>Last 28 days</button>
      </div>

      {invalid && <div className="m-glow-card p-4 text-red-300" role="alert">Choose a start date on or before the end date.</div>}
      {error && <div className="m-glow-card p-4 text-red-300" role="alert">{error}</div>}
      {loading && <div role="status" className="text-[#8fa0b8] text-sm">Loading app performance…</div>}

      {report && (
        <>
          <div className="m-glow-card p-4 text-[0.84rem] text-[#c3cede]">
            <strong className="text-white">{sourceStateLabel(report.status)}. </strong>
            {STATUS_COPY[report.status] || STATUS_COPY.error}
          </div>

          <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
            {CARDS.map(card => (
              <div key={card.key} className="m-glow-card m-kpi" style={{ '--kpi-c1': '#fb7185', '--kpi-c2': '#c4b5fd' }}>
                <div className="k-label">{card.label}</div>
                <div className="k-value">{formatCount(totals[card.key])}</div>
                <div className="k-sub">
                  {card.sub}
                  {card.key === 'latestDayActiveUsers' && totals.latestDay ? ` · ${formatDay(totals.latestDay)}` : ''}
                  {card.rate && formatRate(totals[card.rate]) ? ` · ${formatRate(totals[card.rate])} on ${formatDay(totals[card.rateDate])}` : ''}
                </div>
              </div>
            ))}
          </div>

          <div className="rounded-[14px] border border-[#22304d] overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm text-left">
              <caption className="text-left px-4 py-3 text-white font-extrabold">US, AU, GB, CA, IL and other observed countries</caption>
              <thead className="text-[0.68rem] uppercase tracking-wide text-[#8fa0b8]">
                <tr>{['Country', ...COLUMNS.map(([, label]) => label)].map(label => <th key={label} className="px-3 py-2 font-bold">{label}</th>)}</tr>
              </thead>
              <tbody>
                {report.byCountry.map(row => (
                  <tr key={row.code} className="border-t border-[#22304d] text-[#d5deea]">
                    <th scope="row" className="px-3 py-2 text-white font-semibold">{row.name}</th>
                    {COLUMNS.map(([key]) => <td key={key} className="px-3 py-2 tabular-nums">{formatCount(row[key])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <section className="m-glow-card p-4 space-y-3">
            <h2 className="text-white font-extrabold">Sources</h2>
            <ul className="space-y-2">
              {Object.entries(SOURCE_LABELS).map(([key, label]) => {
                const source = report.sources[key] || {};
                return (
                  <li key={key} className="text-[0.84rem] text-[#c3cede]">
                    <strong className="text-white">{label}. </strong>
                    {sourceStateLabel(source.state)}
                    {source.propertyId ? ` · property ${source.propertyId}` : ''}
                    <div className="text-[#8fa0b8]">{source.blocker || source.note || 'No detail returned.'}</div>
                  </li>
                );
              })}
            </ul>
            <details>
              <summary className="cursor-pointer text-white font-semibold">What each number means</summary>
              <dl className="mt-2 space-y-1 text-[0.8rem] text-[#8fa0b8]">
                {Object.entries(report.definitions || {}).map(([key, text]) => <div key={key}><dt className="inline text-white">{key}. </dt><dd className="inline">{text}</dd></div>)}
              </dl>
            </details>
          </section>
        </>
      )}
    </div>
  );
}
