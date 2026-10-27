/* eslint-disable react/prop-types -- Private presentation helpers receive normalized records from buildView. */
import { Children, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronDown, ChevronRight, Download, RefreshCw, ArrowUpRight, ArrowDownRight, Minus, BarChart3, CalendarDays, Globe, Info } from 'lucide-react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts';
import { useAuth } from '@/contexts/AuthContext';
import { useIsMobile } from '@/hooks/use-mobile';
import { METRICS, buildView, countryKey, exportCsv, flag, formatMetric, trend } from '@/features/attribution/model';
import DateSlicer from '@/features/attribution/DateSlicer';
import { dateLabel, presetRange, validateDates } from '@/features/attribution/dates';
import { Select as MenuSelect, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import '@/features/attribution/style.css';

function useMaxWidth(maxWidth) {
  const query = `(max-width: ${maxWidth}px)`;
  const [matches, setMatches] = useState(() => typeof window !== 'undefined' && window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, [query]);
  return matches;
}

function Select({ label, value, onChange, children }) {
  return <div className="at-filter"><span>{label}</span><MenuSelect value={String(value)} onValueChange={onChange}><SelectTrigger aria-label={label} className="at-select-trigger"><SelectValue /></SelectTrigger><SelectContent className="at-select-menu">{Children.toArray(children).map(option => <SelectItem className="at-select-option" key={option.props.value} value={String(option.props.value)}>{option.props.children}</SelectItem>)}</SelectContent></MenuSelect></div>;
}
function Change({ current, previous, metric, currency, compare }) {
  if (!compare) return null;
  const change = trend(current, previous, metric === 'conversion');
  const Icon = change.direction === 'up' ? ArrowUpRight : change.direction === 'down' ? ArrowDownRight : Minus;
  return <span className={`at-change ${change.direction}`} title={`Previous: ${formatMetric(previous, metric, currency)}`} aria-label={`${change.direction === 'neutral' ? 'Change' : change.direction}: ${change.text}; previous ${formatMetric(previous, metric, currency)}`}><Icon size={12} aria-hidden="true" />{change.text}</span>;
}
function RowLabel({ row }) {
  return <>{row.isCountry && <span className="at-flag" role="img" aria-label={`${row.label} flag`}>{flag(row.countryCode)}</span>}{row.date ? dateLabel(row.date) : row.label}</>;
}
function salesChannelWithoutSessions(current) {
  return (current?.orders || 0) > 0 && (current?.sessions || 0) === 0;
}
function CardMetricValue({ metricKey, current, currency }) {
  return <>
    <strong className={metricKey === 'amount' ? 'm-rev' : ''}>{formatMetric(current[metricKey], metricKey, currency)}</strong>
    {metricKey === 'sessions' && salesChannelWithoutSessions(current) && <span className="at-card-hint">n/a (sales channel)</span>}
  </>;
}
function ReportRow({ row, level = 0, expanded, toggle, currency, compare, sort }) {
  const open = expanded.has(row.id);
  const hasChildren = row.children.length > 0;
  const children = level === 1 ? [...row.children].sort((a, b) => b.date.localeCompare(a.date)) : sort(row.children);
  return <><tr className={`at-level-${level} ${open ? 'at-open' : ''}`}>
    <th scope="row"><div style={{ paddingLeft: level * 18 }}>{hasChildren ? <button className="at-row-toggle" aria-expanded={open} onClick={() => toggle(row.id)}>
      {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}<RowLabel row={row} /><span className="at-count">{row.children.length}</span>
    </button> : <span className="at-day"><CalendarDays size={12} /><RowLabel row={row} /></span>}</div></th>
    {METRICS.map(m => <td key={m.key}><strong className={m.key === 'amount' ? 'm-rev' : ''}>{formatMetric(row.current[m.key], m.key, currency)}</strong><Change current={row.current[m.key]} previous={row.previous[m.key]} metric={m.key} currency={currency} compare={compare} /></td>)}
  </tr>{open && children.map(child => <ReportRow key={child.id} row={child} level={level + 1} expanded={expanded} toggle={toggle} currency={currency} compare={compare} sort={sort} />)}</>;
}


function ReportCard({ row, level = 0, expanded, toggle, currency, compare, sort, primaryMetric }) {
  const open = expanded.has(row.id);
  const hasChildren = row.children.length > 0;
  const children = level === 1 ? [...row.children].sort((a, b) => b.date.localeCompare(a.date)) : sort(row.children);
  const primary = METRICS.find(m => m.key === primaryMetric) || METRICS[0];
  const secondary = METRICS.filter(m => m.key !== primary.key);

  return (
    <div className={`at-card level-${level} ${open ? 'at-open' : ''}`}>
      {hasChildren ? (
        <button type="button" className="at-card-head" aria-expanded={open} onClick={() => toggle(row.id)}>
          {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
          <RowLabel row={row} />
          <span className="at-count">{row.children.length}</span>
        </button>
      ) : (
        <div className="at-card-head">
          <span className="at-day"><CalendarDays size={12} /><RowLabel row={row} /></span>
        </div>
      )}
      <div className="at-card-primary">
        <span className="at-card-metric-label">{primary.label}</span>
        <CardMetricValue metricKey={primary.key} current={row.current} currency={currency} />
        <Change current={row.current[primary.key]} previous={row.previous[primary.key]} metric={primary.key} currency={currency} compare={compare} />
      </div>
      <div className="at-card-metrics">
        {secondary.map(m => (
          <div key={m.key}>
            <span className="at-card-metric-label">{m.label}</span>
            <CardMetricValue metricKey={m.key} current={row.current} currency={currency} />
            <Change current={row.current[m.key]} previous={row.previous[m.key]} metric={m.key} currency={currency} compare={compare} />
          </div>
        ))}
      </div>
      {open && hasChildren && (
        <div className="at-card-children">
          {children.map(child => (
            <ReportCard
              key={child.id}
              row={child}
              level={level + 1}
              expanded={expanded}
              toggle={toggle}
              currency={currency}
              compare={compare}
              sort={sort}
              primaryMetric={primaryMetric}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function Attribution() {
  const { getAuthHeader } = useAuth();
  const isMobile = useIsMobile();
  const phoneFilters = useMaxWidth(480);
  const [preset, setPreset] = useState('28');
  const [dates, setDates] = useState(() => presetRange('28'));
  const [comparison, setComparison] = useState('previous');
  const [channel, setChannel] = useState('all');
  const [country, setCountry] = useState('all');
  const [group, setGroup] = useState('channel');
  const [sortKey, setSortKey] = useState('amount');
  const [sortDirection, setSortDirection] = useState(-1);
  const [metric, setMetric] = useState('amount');
  const [expanded, setExpanded] = useState(new Set());
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const validation = validateDates(dates);

  useEffect(() => {
    const controller = new AbortController();
    setReport(null); setError('');
    if (validation) { setLoading(false); return () => controller.abort(); }
    setLoading(true);
    const params = new URLSearchParams({ ...dates, comparison });
    fetch(`/attribution-api?${params}`, { headers: getAuthHeader(), signal: controller.signal, cache: 'no-store' })
      .then(async response => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.message || 'Attribution could not be loaded.');
        if (!body.range || !Array.isArray(body.rows)) throw new Error('The report response was incomplete.');
        return body;
      }).then(body => { if (!controller.signal.aborted) setReport(body); }).catch(err => { if (!controller.signal.aborted) setError(err.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [dates, comparison, refresh, getAuthHeader, validation]);

  const view = useMemo(() => report ? buildView(report, { channel, country, group }) : null, [report, channel, country, group]);
  const channels = useMemo(() => [...new Set((report?.rows || []).map(r => r.channel))].sort(), [report]);
  const countries = useMemo(() => [...new Map((report?.rows || []).map(r => [countryKey(r), r])).values()].sort((a, b) => a.country.localeCompare(b.country)), [report]);
  const compare = comparison !== 'none';
  useEffect(() => { setPage(1); }, [channel, country, group, sortKey, sortDirection, pageSize, report]);
  const toggle = id => setExpanded(previous => { const next = new Set(previous); next.has(id) ? next.delete(id) : next.add(id); return next; });
  const sort = rows => [...rows].sort((a, b) => {
    const left = a.current[sortKey], right = b.current[sortKey];
    if (left == null || right == null) return left == null ? right == null ? 0 : 1 : -1;
    return (left - right) * sortDirection || a.label.localeCompare(b.label);
  });
  const sortBy = key => { setSortDirection(key === sortKey ? -sortDirection : -1); setSortKey(key); };
  const download = () => {
    const url = URL.createObjectURL(new Blob(['\ufeff', exportCsv(view, report, group)], { type: 'text/csv;charset=utf-8;' }));
    const link = document.createElement('a'); link.href = url; link.download = `mirai-attribution-${dates.start}-${dates.end}.csv`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const chart = view?.daily.map(day => ({ date: dateLabel(day.id), current: day.current[metric], previous: day.previous[metric] }));
  const selectedMetric = METRICS.find(m => m.key === metric);
  const sortedRows = view ? sort(view.children) : [];
  const pageCount = Math.max(1, Math.ceil(sortedRows.length / pageSize));
  const currentPage = Math.min(page, pageCount);
  const visibleRows = sortedRows.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  const unallocated = report?.rows.filter(row => row.unallocated && row.date >= report.range.start).reduce((total, row) => total + row.sessions, 0) || 0;
  const displayChannels = channels.includes(channel) || channel === 'all' ? channels : [...channels, channel];
  const filterGrid = <div className="at-filter-grid">
    <Select label="Compare with" value={comparison} onChange={setComparison}><option value="previous">Previous period</option><option value="none">No comparison</option></Select>
    <Select label="Channel" value={channel} onChange={value => { setChannel(value); setExpanded(new Set()); }}><option value="all">All channels</option>{displayChannels.map(c => <option key={c} value={c}>{c}</option>)}</Select>
    <Select label="Country" value={country} onChange={value => { setCountry(value); setExpanded(new Set()); }}><option value="all">All countries</option>{countries.map(c => <option key={countryKey(c)} value={countryKey(c)}>{flag(c.countryCode)} {c.country}</option>)}{country !== 'all' && !countries.some(c => countryKey(c) === country) && <option value={country}>{country}</option>}</Select>
    <Select label="Breakdown" value={group} onChange={value => { setGroup(value); setExpanded(new Set()); }}><option value="channel">Channel → Country</option><option value="country">Country → Channel</option></Select>
  </div>;

  return <div className="at-report space-y-4 p-3 lg:p-6">
    <header className="at-header">
      <div><div className="at-eyebrow"><BarChart3 size={13} /> MIRAI MANAGEMENT <span>/</span> ANALYTICS</div>
        <h1>Attribution report <span className="at-source">Shopify</span></h1>
        <p>See which channels and countries bring traffic, sales and returning customers.</p></div>
      <div className="at-actions"><button className="m-chip" onClick={() => setRefresh(x => x + 1)} disabled={loading || !!validation}><RefreshCw size={14} className={loading ? 'animate-spin' : ''} />Reload</button><button className="m-chip on" onClick={download} disabled={!view || !view.children.length}><Download size={14} />Export CSV</button></div>
    </header>
    <nav className="m-seg" aria-label="Business reports"><Link className="m-chip !border-0" to="/Reports">Daily & order reports</Link><span className="m-chip on !border-0" aria-current="page">Attribution</span></nav>

    <section className="m-glow-card at-controls" aria-label="Report filters">
      <DateSlicer preset={preset} dates={dates} timezone={report?.timezone} onChange={(value, range) => { setPreset(value); setDates(range); setExpanded(new Set()); }} />
      {phoneFilters ? <details className="at-filters-sheet">
        <summary>
          <span>Filters</span>
          <span className="at-filters-summary">
            {[
              channel === 'all' ? 'All channels' : channel,
              country === 'all'
                ? 'All countries'
                : (countries.find(c => countryKey(c) === country)?.country || country),
            ].join(' · ')}
          </span>
        </summary>
        {filterGrid}
      </details> : filterGrid}
      <div className="at-period"><CalendarDays size={14} /><strong>{dates.start && dateLabel(dates.start)} – {dates.end && dateLabel(dates.end)}</strong>{report && <><span>{compare ? `vs ${dateLabel(report.range.previousStart)} – ${dateLabel(report.range.previousEnd)}` : 'No comparison'}</span><span className="at-period-meta">{report.currency} · {report.timezone} · Updated {new Date(report.fetchedAt).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}</span></>}</div>
    </section>

    {(validation || error) && <div role="alert" className="m-glow-card at-error"><strong>{validation ? 'Check the date range' : 'Report unavailable'}</strong><p>{validation || error}</p>{error && <button className="m-chip" onClick={() => setRefresh(x => x + 1)}>Try again</button>}</div>}
    {loading && <div role="status" className="at-loading"><RefreshCw className="animate-spin" size={22} /><strong>Loading Shopify attribution…</strong><span>Checking sessions and sales for both periods.</span></div>}

    {view && <>
      {unallocated > 0 && channel === 'all' && country === 'all' && <p className="at-quality"><Info size={14} />{unallocated.toLocaleString()} sessions lack channel/country detail in Shopify. Included under “Unallocated detail” so totals reconcile.</p>}
      <div className="at-kpis">
        {METRICS.map(m => <button key={m.key} className={`m-glow-card m-kpi at-kpi ${metric === m.key ? 'selected' : ''}`} style={{ '--kpi-c1': m.color, '--kpi-c2': m.color, '--kpi-glow': `${m.color}18` }} onClick={() => setMetric(m.key)} aria-pressed={metric === m.key} title={m.description}>
          <div className="k-label">{m.label}</div><div className="k-value" style={{ color: m.key === 'amount' ? m.color : undefined }}>{formatMetric(view.current[m.key], m.key, report.currency)}</div>
          <div className="at-kpi-change"><Change current={view.current[m.key]} previous={view.previous[m.key]} metric={m.key} currency={report.currency} compare={compare} /><span>{compare ? 'vs previous period' : 'Selected period'}</span></div>
          <div className="at-spark" aria-hidden="true">{view.daily.map(day => <i key={day.id} style={{ height: `${Math.max(3, Math.abs(day.current[m.key] || 0) / Math.max(...view.daily.map(d => Math.abs(d.current[m.key] || 0)), 0.001) * 100)}%`, background: m.color, opacity: day.current[m.key] ? 0.65 : 0.12 }} />)}</div>
        </button>)}
      </div>
      <section className="m-glow-card at-chart">
        <div className="at-section-head"><div><h2>{selectedMetric.label} over time</h2><p>{channel === 'all' ? 'All channels' : channel} · {country === 'all' ? 'All countries' : countries.find(c => countryKey(c) === country)?.country || country}</p></div><div className="at-legend"><span><i style={{ background: selectedMetric.color }} />Selected period</span>{compare && <span><i className="previous" />Previous period</span>}</div></div>
        <div className="at-chart-canvas"><ResponsiveContainer width="100%" height="100%"><AreaChart data={chart} margin={{ top: 10, right: 16, left: 4, bottom: 0 }}>
          <defs><linearGradient id="at-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={selectedMetric.color} stopOpacity={0.24} /><stop offset="100%" stopColor={selectedMetric.color} stopOpacity={0} /></linearGradient></defs>
          <CartesianGrid stroke="#2b3a55" strokeDasharray="3 5" vertical={false} /><XAxis dataKey="date" tick={{ fill: '#8fa0b8', fontSize: 11 }} axisLine={false} tickLine={false} minTickGap={isMobile ? 48 : 36} /><YAxis tick={{ fill: '#8fa0b8', fontSize: 11 }} axisLine={false} tickLine={false} width={isMobile ? 40 : 65} tickFormatter={v => metric === 'conversion' ? `${(v * 100).toFixed(1)}%` : new Intl.NumberFormat('en-US', { notation: 'compact' }).format(v)} />
          <Tooltip contentStyle={{ background: '#121a30', border: '1px solid #46557a', borderRadius: 10 }} labelStyle={{ color: '#e2e8f0' }} formatter={(value, name) => [formatMetric(value, metric, report.currency), name === 'current' ? 'Selected period' : 'Previous period (aligned day)']} />
          {compare && <Area type="monotone" dataKey="previous" stroke="#8292ad" strokeDasharray="5 5" fill="transparent" strokeWidth={1.5} isAnimationActive={false} />}
          <Area type="monotone" dataKey="current" stroke={selectedMetric.color} fill="url(#at-fill)" strokeWidth={2.2} isAnimationActive={false} />
        </AreaChart></ResponsiveContainer></div>
      </section>

      <section className="m-glow-card at-breakdown">
        <div className="at-section-head"><div><h2><Globe size={17} />{group === 'channel' ? 'Channel & country performance' : 'Country & channel performance'}</h2><p>Open a row to see its breakdown, then open a country or channel to see each day.</p></div><div className="at-actions"><button className="m-chip" onClick={() => setExpanded(new Set(visibleRows.map(r => r.id)))}>Expand page</button><button className="m-chip" onClick={() => setExpanded(new Set())}>Collapse all</button></div></div>
        {!view.children.length ? <div className="at-empty"><Globe size={28} /><h3>No activity for these filters</h3><p>Choose another channel, country or date range.</p><button className="m-chip" onClick={() => { setChannel('all'); setCountry('all'); }}>Reset channel & country</button></div> : <><div className="at-table-wrap" tabIndex={0} aria-label="Attribution breakdown; scroll horizontally on small screens"><table className="m-table at-table">
          <thead><tr><th>{group === 'channel' ? 'Channel / Country' : 'Country / Channel'}</th>{METRICS.map(m => <th key={m.key} aria-sort={sortKey === m.key ? sortDirection < 0 ? 'descending' : 'ascending' : 'none'}><button onClick={() => sortBy(m.key)} title={m.description}>{m.label} <span>{sortKey === m.key ? sortDirection < 0 ? '↓' : '↑' : '↕'}</span></button></th>)}</tr></thead>
          <tbody><tr className="at-total"><th scope="row">All selected <span className="at-count">{view.children.length} {group === 'channel' ? 'channels' : 'countries'}</span></th>{METRICS.map(m => <td key={m.key}><strong>{formatMetric(view.current[m.key], m.key, report.currency)}</strong><Change current={view.current[m.key]} previous={view.previous[m.key]} metric={m.key} currency={report.currency} compare={compare} /></td>)}</tr>{visibleRows.map(row => <ReportRow key={row.id} row={row} expanded={expanded} toggle={toggle} currency={report.currency} compare={compare} sort={sort} />)}</tbody>
        </table></div>
        <div className="at-card-list" aria-label="Attribution breakdown cards">
          <div className="at-card-total">
            <div className="at-card-total-label">
              All selected <span className="at-count">{view.children.length} {group === 'channel' ? 'channels' : 'countries'}</span>
            </div>
            <div className="at-card-primary">
              <span className="at-card-metric-label">{selectedMetric.label}</span>
              <CardMetricValue metricKey={metric} current={view.current} currency={report.currency} />
              <Change current={view.current[metric]} previous={view.previous[metric]} metric={metric} currency={report.currency} compare={compare} />
            </div>
            <div className="at-card-metrics">
              {METRICS.filter(m => m.key !== metric).map(m => (
                <div key={m.key}>
                  <span className="at-card-metric-label">{m.label}</span>
                  <CardMetricValue metricKey={m.key} current={view.current} currency={report.currency} />
                  <Change current={view.current[m.key]} previous={view.previous[m.key]} metric={m.key} currency={report.currency} compare={compare} />
                </div>
              ))}
            </div>
          </div>
          {visibleRows.map(row => (
            <ReportCard
              key={row.id}
              row={row}
              expanded={expanded}
              toggle={toggle}
              currency={report.currency}
              compare={compare}
              sort={sort}
              primaryMetric={metric}
            />
          ))}
        </div></>}
        <div className="at-table-footer"><span><i className="at-dot up" /> Increase <i className="at-dot down" /> Decrease <span className="at-muted">· Conversion changes in percentage points</span></span><span>Sessions: visitor country · Sales: shipping country</span></div>
        {view.children.length > 0 && <div className="at-pagination"><Select label="Rows per page" value={pageSize} onChange={value => setPageSize(Number(value))}><option value={20}>20 rows</option><option value={50}>50 rows</option><option value={1000}>All rows</option></Select><span>Page {currentPage} of {pageCount} · {view.children.length} groups</span><button className="m-chip" disabled={currentPage === 1} onClick={() => setPage(p => p - 1)}>Previous</button><button className="m-chip" disabled={currentPage === pageCount} onClick={() => setPage(p => p + 1)}>Next</button></div>}
      </section>
      <details className="m-glow-card at-definitions"><summary><Info size={15} />How to read this report<ChevronDown size={14} /></summary><div>
        <p><strong>Country:</strong> sessions and conversion use visitor location; orders, net sales and returning orders use shipping country. These can differ. Conversion uses completed-checkout sessions, so it is not orders divided by sessions.</p>
        <p><strong>Channel:</strong> Shopify’s recorded referring channel and paid/organic classification. Shop and other sales channels are shown separately. Missing attribution stays “Unattributed”; it is never inferred to be organic or direct.</p>
        <p><strong>Unallocated detail:</strong> the measured difference between Shopify’s daily totals and its channel/country breakdown. This is kept visible under unknown country, never distributed across known channels. Channel and country filters exclude it unless selected.</p>
        <p><strong>Returning orders:</strong> repeat purchases, not returned or refunded items. Net sales includes Shopify sales reversals on their posting dates, excluding shipping and taxes.{view.current.unknownCustomerOrders > 0 && ` ${view.current.unknownCustomerOrders} orders have an unknown customer type.`}</p>
        <p><strong>Comparison:</strong> the immediately preceding period with the same number of days, in {report.timezone}. “New” means the previous value was zero; “—” means conversion has no session denominator. All session traffic is included. A period containing today is incomplete. Results are cached for up to five minutes; Shopify may revise recent attribution.</p>
      </div></details>
    </>}
  </div>;
}
