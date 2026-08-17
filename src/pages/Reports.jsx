import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Calendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Input } from '@/components/ui/input';
import {
  CalendarIcon, TrendingUp, Package, Globe, Clock, Star, RefreshCw,
  ChevronDown, ChevronRight, ArrowUpDown,
} from 'lucide-react';
import { format, subDays, startOfMonth, endOfMonth, subMonths, startOfDay, endOfDay } from 'date-fns';
import { cn } from '@/lib/utils';

// Use same-origin API to avoid CORS issues
const REPORT_API_URL = import.meta.env.VITE_REPORT_API_URL ||
  (import.meta.env.DEV ? 'http://localhost:8080' : '/reports-api');

/* ── helpers ──────────────────────────────────────────────────────────── */

const fmtUSD = (v) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(v || 0);

const fmtUSD0 = (v) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(v || 0);

const fmtPct = (v, digits = 1) => `${((v || 0) * 100).toFixed(digits)}%`;

const useIsMobile = () => {
  const [mob, setMob] = useState(() => typeof window !== 'undefined' && window.innerWidth < 1024);
  useEffect(() => {
    const onR = () => setMob(window.innerWidth < 1024);
    window.addEventListener('resize', onR);
    return () => window.removeEventListener('resize', onR);
  }, []);
  return mob;
};

const marginBadge = (frac) => {
  const cls = (frac || 0) >= 0.2 ? 'good' : (frac || 0) >= 0.08 ? 'ok' : 'bad';
  return <span className={`m-badge ${cls}`}>{fmtPct(frac)}</span>;
};

const pnl = (v) => (
  <span className={(v || 0) >= 0 ? 'm-pos' : 'm-neg'}>{fmtUSD(v)}</span>
);

/* tiny per-day bar sparkline for KPI cards */
const Spark = ({ series, color, signed = false }) => {
  if (!series || series.length < 2) return <div className="m-spark" />;
  const mx = Math.max(...series.map((v) => Math.abs(v || 0)), 1);
  return (
    <div className="m-spark">
      {series.map((v, i) => (
        <i
          key={i}
          style={{
            height: `${Math.max(8, (Math.abs(v || 0) / mx) * 100)}%`,
            background: signed ? ((v || 0) >= 0 ? 'rgba(52,211,153,.75)' : 'rgba(248,113,113,.75)') : color,
          }}
        />
      ))}
    </div>
  );
};

const channelChip = (channel) => {
  const map = {
    google: 'bg-blue-100 text-blue-800',
    meta: 'bg-indigo-100 text-indigo-700',
    shop: 'bg-purple-100 text-purple-800',
    klaviyo: 'bg-amber-100 text-amber-700',
    organic: 'bg-teal-100 text-teal-700',
  };
  return (
    <span className={`inline-block px-2 py-0.5 rounded-md text-[0.68rem] font-bold capitalize ${map[channel] || 'bg-slate-100 text-slate-600'}`}>
      {channel || '—'}
    </span>
  );
};

/* ── page ─────────────────────────────────────────────────────────────── */

export default function Reports() {
  const [activeTab, setActiveTab] = useState('daily');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [reportData, setReportData] = useState([]);
  const [orderData, setOrderData] = useState({ orders: [], analytics: null });
  const [orderSearch, setOrderSearch] = useState('');
  const [bestsellersData, setBestsellersData] = useState(null);
  const [bestsellersDay, setBestsellersDay] = useState(30); // 7, 30, or 60
  const [dateRange, setDateRange] = useState({ from: subDays(new Date(), 7), to: new Date() });
  const [expandedOrders, setExpandedOrders] = useState({});
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [dailySort, setDailySort] = useState({ key: 'date', dir: -1 });
  const [preset, setPreset] = useState('7d');
  const isMobile = useIsMobile();

  const getCacheKey = () =>
    `reports_${format(dateRange.from, 'yyyy-MM-dd')}_${format(dateRange.to, 'yyyy-MM-dd')}`;

  useEffect(() => {
    if (activeTab === 'daily') {
      const cached = localStorage.getItem(getCacheKey());
      if (cached) {
        try {
          const { data, timestamp } = JSON.parse(cached);
          if (Date.now() - timestamp < 5 * 60 * 1000) {
            setReportData(data);
            return;
          }
        } catch (e) {}
      }
      fetchReportData();
    } else if (activeTab === 'orders') {
      fetchOrderData();
    } else if (activeTab === 'bestsellers') {
      fetchBestsellers();
    }
  }, [dateRange, activeTab]);

  useEffect(() => {
    if (activeTab === 'bestsellers') fetchBestsellers();
  }, [bestsellersDay]);

  const fetchReportData = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${REPORT_API_URL}/daily-report`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          start_date: format(dateRange.from, 'yyyy-MM-dd'),
          end_date: format(dateRange.to, 'yyyy-MM-dd'),
        }),
        mode: 'cors',
      });
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      const result = await response.json();
      const data = result.data || [];
      setReportData(data);
      localStorage.setItem(getCacheKey(), JSON.stringify({ data, timestamp: Date.now() }));
    } catch (err) {
      console.error('Failed to fetch report data:', err);
      setError(`Unable to reach the reporting API: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const fetchOrderData = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${REPORT_API_URL}/order-report`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          start_date: format(dateRange.from, 'yyyy-MM-dd'),
          end_date: format(dateRange.to, 'yyyy-MM-dd'),
        }),
      });
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      const result = await response.json();
      setOrderData(result.data || { orders: [], analytics: null });
    } catch (err) {
      console.error('Failed to fetch order data:', err);
      setError(`Failed to fetch order report: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const fetchBestsellers = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${REPORT_API_URL}/bestsellers/${bestsellersDay}`);
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      const result = await response.json();
      setBestsellersData(result.data || null);
    } catch (err) {
      console.error('Failed to fetch bestsellers:', err);
      setError(`Failed to fetch bestsellers: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleRefreshDaily = async () => {
    setIsRefreshing(true);
    localStorage.removeItem(getCacheKey());
    await fetchReportData();
    setIsRefreshing(false);
  };

  const handleRefreshOrders = async () => {
    setIsRefreshing(true);
    await fetchOrderData();
    setIsRefreshing(false);
  };

  const toggleOrderExpansion = (orderId) =>
    setExpandedOrders((prev) => ({ ...prev, [orderId]: !prev[orderId] }));

  const filteredOrders = useMemo(() => {
    if (!orderSearch.trim()) return orderData.orders || [];
    const search = orderSearch.toLowerCase();
    return (orderData.orders || []).filter(
      (o) =>
        o.order_name?.toLowerCase().includes(search) ||
        o.customer_name?.toLowerCase().includes(search) ||
        o.customer_email?.toLowerCase().includes(search) ||
        o.country?.toLowerCase().includes(search)
    );
  }, [orderData.orders, orderSearch]);

  /* summary: profit uses ?? (a legit $0 margin must not fall through),
     margin is REVENUE-WEIGHTED, ad spend carries the G/M/Shop split */
  const summary = useMemo(() => {
    const s = reportData.reduce(
      (acc, day) => {
        const profit = day.margin ?? day.operational ?? 0;
        const revBase = day.revenue_base ?? ((day.net || 0) + (day.shipping_charged || 0));
        return {
          totalOrders: acc.totalOrders + (day.orders || 0),
          totalGross: acc.totalGross + (day.gross || 0),
          totalNet: acc.totalNet + (day.net || 0),
          totalSpend: acc.totalSpend + (day.total_spend || 0),
          totalGoogle: acc.totalGoogle + (day.google_spend || 0),
          totalMeta: acc.totalMeta + (day.meta_spend || 0),
          totalShop: acc.totalShop + (day.shop_spend || 0),
          totalProfit: acc.totalProfit + profit,
          totalRevBase: acc.totalRevBase + revBase,
        };
      },
      { totalOrders: 0, totalGross: 0, totalNet: 0, totalSpend: 0, totalGoogle: 0, totalMeta: 0, totalShop: 0, totalProfit: 0, totalRevBase: 0 }
    );
    s.weightedMargin = s.totalRevBase > 0 ? s.totalProfit / s.totalRevBase : 0;
    s.avgAOV = s.totalOrders > 0 ? s.totalNet / s.totalOrders : 0;
    return s;
  }, [reportData]);

  /* chronological series for the KPI sparklines */
  const series = useMemo(() => {
    const asc = [...reportData].sort((a, b) => (a.date || '').localeCompare(b.date || ''));
    return {
      orders: asc.map((d) => d.orders || 0),
      net: asc.map((d) => d.net || 0),
      spend: asc.map((d) => d.total_spend || 0),
      profit: asc.map((d) => d.margin ?? d.operational ?? 0),
    };
  }, [reportData]);

  const sortedDaily = useMemo(() => {
    const rows = [...reportData];
    const { key, dir } = dailySort;
    rows.sort((a, b) => {
      const av = key === 'date' ? a.date || '' : a[key] ?? -Infinity;
      const bv = key === 'date' ? b.date || '' : b[key] ?? -Infinity;
      if (av < bv) return -dir;
      if (av > bv) return dir;
      return 0;
    });
    return rows;
  }, [reportData, dailySort]);

  const sortDaily = (key) =>
    setDailySort((s) => ({ key, dir: s.key === key ? -s.dir : -1 }));

  const applyPreset = (id, range) => {
    setPreset(id);
    setDateRange(range);
  };

  const presets = [
    { id: 'today', label: 'Today', range: () => ({ from: startOfDay(new Date()), to: endOfDay(new Date()) }) },
    { id: 'yday', label: 'Yesterday', range: () => ({ from: startOfDay(subDays(new Date(), 1)), to: endOfDay(subDays(new Date(), 1)) }) },
    { id: '3d', label: '3D', range: () => ({ from: subDays(new Date(), 3), to: new Date() }) },
    { id: '7d', label: '7D', range: () => ({ from: subDays(new Date(), 7), to: new Date() }) },
    { id: '30d', label: '30D', range: () => ({ from: subDays(new Date(), 30), to: new Date() }) },
    { id: 'month', label: 'This Month', range: () => ({ from: startOfMonth(new Date()), to: endOfMonth(new Date()) }) },
    { id: 'lastm', label: 'Last Month', range: () => ({ from: startOfMonth(subMonths(new Date(), 1)), to: endOfMonth(subMonths(new Date(), 1)) }) },
  ];

  const spendTooltip = `Google ${fmtUSD(summary.totalGoogle)} · Meta ${fmtUSD(summary.totalMeta)} · Shop ${fmtUSD(summary.totalShop)}`;

  /* ── KPI cards ──────────────────────────────────────────────────────── */
  const kpiCards = (
    <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
      <div className="m-glow-card m-kpi" style={{ '--kpi-c1': '#6366f1', '--kpi-c2': '#a5b4fc', '--kpi-glow': 'rgba(99,102,241,.10)' }}>
        <div className="k-label">Total Orders</div>
        <div className="k-value">{summary.totalOrders}</div>
        <div className="k-sub">AOV <b>{fmtUSD(summary.avgAOV)}</b></div>
        <Spark series={series.orders} color="rgba(129,140,248,.7)" />
      </div>

      <div className="m-glow-card m-kpi" style={{ '--kpi-c1': '#22d3ee', '--kpi-c2': '#67e8f9', '--kpi-glow': 'rgba(34,211,238,.09)' }}>
        <div className="k-label">Revenue (Net)</div>
        <div className="k-value m-rev">{fmtUSD0(summary.totalNet)}</div>
        <div className="k-sub">Gross <b>{fmtUSD0(summary.totalGross)}</b></div>
        <Spark series={series.net} color="rgba(34,211,238,.65)" />
      </div>

      <div className="m-glow-card m-kpi" style={{ '--kpi-c1': '#f59e0b', '--kpi-c2': '#fbbf24', '--kpi-glow': 'rgba(245,158,11,.10)' }} title={spendTooltip}>
        <div className="k-label">Ad Spend</div>
        <div className="k-value m-gold">{fmtUSD0(summary.totalSpend)}</div>
        <div className="k-sub">
          G <b>{fmtUSD0(summary.totalGoogle)}</b> · M <b>{fmtUSD0(summary.totalMeta)}</b> · Shop <b>{fmtUSD0(summary.totalShop)}</b>
        </div>
        <Spark series={series.spend} color="rgba(251,191,36,.65)" />
      </div>

      <div
        className="m-glow-card m-kpi"
        style={
          summary.totalProfit >= 0
            ? { '--kpi-c1': '#10b981', '--kpi-c2': '#34d399', '--kpi-glow': 'rgba(16,185,129,.10)' }
            : { '--kpi-c1': '#ef4444', '--kpi-c2': '#f87171', '--kpi-glow': 'rgba(239,68,68,.10)' }
        }
      >
        <div className="k-label">Net Profit</div>
        <div className={`k-value ${summary.totalProfit >= 0 ? 'm-pos' : 'm-neg'}`}>{fmtUSD0(summary.totalProfit)}</div>
        <div className="k-sub">Margin <b>{fmtPct(summary.weightedMargin)}</b> of revenue</div>
        <Spark series={series.profit} signed />
      </div>
    </div>
  );

  /* ── daily table / cards ────────────────────────────────────────────── */
  const dailyCols = [
    { key: 'date', label: 'Date' },
    { key: 'orders', label: 'Orders' },
    { key: 'net', label: 'Net Sales' },
    { key: 'cogs', label: 'COGS' },
    { key: 'shipping_charged', label: 'Ship Chg' },
    { key: 'shipping_cost', label: 'Est Ship' },
    { key: 'psp_usd', label: 'PSP' },
    { key: 'total_spend', label: 'Ad Spend' },
    { key: 'operational', label: 'Operational' },
    { key: 'margin', label: 'Margin $' },
    { key: 'margin_pct', label: 'Margin %' },
    { key: 'aov', label: 'AOV' },
    { key: 'general_cpa', label: 'CPA' },
    { key: 'returning_customers', label: 'Ret.' },
  ];

  const dailyTable = (
    <div className="overflow-x-auto rounded-b-[14px]">
      <table className="m-table">
        <thead>
          <tr>
            {dailyCols.map((c) => (
              <th key={c.key} className={c.key === 'date' ? 'sticky-col' : ''} onClick={() => sortDaily(c.key)}>
                {c.label}
                {dailySort.key === c.key && <span className="text-rose-300"> {dailySort.dir === 1 ? '▲' : '▼'}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedDaily.map((day) => (
            <tr key={day.date}>
              <td className="sticky-col">{day.label}</td>
              <td>{day.orders}</td>
              <td className="m-rev">{fmtUSD(day.net)}</td>
              <td>{fmtUSD(day.cogs)}</td>
              <td>{fmtUSD(day.shipping_charged)}</td>
              <td>{fmtUSD(day.shipping_cost)}</td>
              <td>{fmtUSD(day.psp_usd)}</td>
              <td
                className="m-gold"
                title={`Google ${fmtUSD(day.google_spend)} · Meta ${fmtUSD(day.meta_spend)} · Shop ${fmtUSD(day.shop_spend)}`}
              >
                {fmtUSD(day.total_spend)}
              </td>
              <td>{pnl(day.operational)}</td>
              <td>{pnl(day.margin)}</td>
              <td>{marginBadge(day.margin_pct)}</td>
              <td>{fmtUSD(day.aov)}</td>
              <td>{day.general_cpa != null ? fmtUSD(day.general_cpa) : '—'}</td>
              <td>{day.returning_customers}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  const dailyCards = (
    <div className="space-y-2.5 p-3">
      {sortedDaily.map((day) => (
        <div key={day.date} className="m-mcard">
          <div className="mc-head">
            <b className="text-white text-[0.86rem]">{day.label}</b>
            <div className="flex items-center gap-2">
              {marginBadge(day.margin_pct)}
              <span className="text-[0.8rem] font-extrabold">{pnl(day.margin)}</span>
            </div>
          </div>
          <div className="mc-grid">
            <div className="mc-cell"><i>Orders</i><b>{day.orders}</b></div>
            <div className="mc-cell"><i>Net</i><b className="m-rev">{fmtUSD0(day.net)}</b></div>
            <div className="mc-cell"><i>Spend</i><b className="m-gold">{fmtUSD0(day.total_spend)}</b></div>
            <div className="mc-cell"><i>COGS</i><b>{fmtUSD0(day.cogs)}</b></div>
            <div className="mc-cell"><i>Est Ship</i><b>{fmtUSD0(day.shipping_cost)}</b></div>
            <div className="mc-cell"><i>Operational</i><b>{pnl(day.operational)}</b></div>
            <div className="mc-cell"><i>AOV</i><b>{fmtUSD0(day.aov)}</b></div>
            <div className="mc-cell"><i>CPA</i><b>{day.general_cpa != null ? fmtUSD0(day.general_cpa) : '—'}</b></div>
            <div className="mc-cell"><i>Returning</i><b>{day.returning_customers}</b></div>
          </div>
        </div>
      ))}
    </div>
  );

  /* ── order cards (mobile) ───────────────────────────────────────────── */
  const orderCards = (
    <div className="space-y-2.5 p-3">
      {filteredOrders.slice(0, 100).map((order) => (
        <div key={order.order_id} className={cn('m-mcard', order.is_cancelled && 'opacity-50')}>
          <div className="mc-head">
            <div className="flex items-center gap-2 min-w-0">
              <b className="text-white text-[0.86rem]">{order.order_name}</b>
              {channelChip(order.channel)}
              {order.is_cancelled && <span className="m-badge bad">Cancelled</span>}
            </div>
            <span className="text-[0.8rem] font-extrabold">{pnl(order.profit)}</span>
          </div>
          <div className="text-[0.7rem] text-[#8fa0b8] mb-2 truncate">
            {order.date} {order.time} · {order.customer_name} · {order.country}
            {order.is_returning ? ' · returning' : ' · first-time'}
          </div>
          <div className="mc-grid">
            <div className="mc-cell"><i>Net</i><b className="m-rev">{fmtUSD(order.net)}</b></div>
            <div className="mc-cell"><i>COGS</i><b>{fmtUSD(order.cogs)}</b></div>
            <div className="mc-cell"><i>Ship Cost</i><b>{fmtUSD(order.shipping_cost)}</b></div>
            <div className="mc-cell"><i>PSP</i><b>{fmtUSD(order.psp_fee)}</b></div>
            {(order.shop_ad_cost || 0) > 0 && (
              <div className="mc-cell"><i>Shop Ads</i><b className="m-gold">{fmtUSD(order.shop_ad_cost)}</b></div>
            )}
            <div className="mc-cell"><i>Margin</i><b>{marginBadge((order.margin_pct || 0) / 100)}</b></div>
            <div className="mc-cell"><i>Items</i><b>{order.items_count}</b></div>
          </div>
          {order.items && order.items.length > 0 && (
            <button
              className="mt-2 text-[0.7rem] font-bold text-rose-300 flex items-center gap-1"
              onClick={() => toggleOrderExpansion(order.order_id)}
            >
              {expandedOrders[order.order_id] ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
              {order.items.length} line item{order.items.length > 1 ? 's' : ''}
            </button>
          )}
          {expandedOrders[order.order_id] && order.items && (
            <div className="mt-2 space-y-1">
              {order.items.map((item, idx) => (
                <div key={idx} className="flex items-center justify-between gap-2 text-[0.72rem] bg-black/25 rounded-lg px-2.5 py-1.5">
                  <span className="text-[#c3cede] truncate">{item.name || 'Unknown Item'}</span>
                  <span className="text-[#8fa0b8] whitespace-nowrap">×{item.quantity} · {fmtUSD(item.gross)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );

  /* ── render ─────────────────────────────────────────────────────────── */
  return (
    <div className="m-page space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h1 className="text-[1.45rem] lg:text-3xl font-extrabold tracking-tight text-white flex items-center gap-2.5 leading-tight">
            Business Reports
            <span className="m-live"><i />LIVE</span>
          </h1>
          <p className="text-[#8fa0b8] text-[0.78rem] lg:text-sm mt-0.5">
            Daily performance · orders · best sellers
          </p>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <Popover>
            <PopoverTrigger asChild>
              <button className="m-chip on-indigo !text-[0.72rem]">
                <CalendarIcon className="h-3.5 w-3.5" />
                {dateRange?.from
                  ? dateRange.to
                    ? `${format(dateRange.from, 'MMM d')} – ${format(dateRange.to, 'MMM d')}`
                    : format(dateRange.from, 'MMM d, y')
                  : 'Pick dates'}
              </button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-3 max-w-[94vw]" align="end">
              <div className="flex flex-wrap gap-1.5 mb-2">
                {presets.map((p) => (
                  <button
                    key={p.id}
                    className={cn('m-chip !py-1 !px-3 !text-[0.68rem]', preset === p.id && 'on')}
                    onClick={() => applyPreset(p.id, p.range())}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              <Calendar
                initialFocus
                mode="range"
                defaultMonth={dateRange?.from}
                selected={dateRange}
                onSelect={(r) => { setPreset(null); setDateRange(r); }}
                numberOfMonths={isMobile ? 1 : 2}
              />
            </PopoverContent>
          </Popover>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="m-glow-card p-4 !border-red-400/40">
          <div className="font-bold text-red-300 mb-1">Error loading reports</div>
          <div className="text-[0.8rem] text-[#a9b7cc] mb-3">{error}</div>
          <button
            className="m-chip on"
            onClick={activeTab === 'daily' ? fetchReportData : activeTab === 'orders' ? fetchOrderData : fetchBestsellers}
          >
            Retry
          </button>
        </div>
      )}

      {/* Tab switch */}
      <div className="m-seg no-scrollbar">
        {[
          { id: 'daily', label: 'Daily Report', icon: TrendingUp },
          { id: 'orders', label: 'Orders', icon: Package },
          { id: 'bestsellers', label: 'Best Sellers', icon: Star },
        ].map((t) => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            className={cn('m-chip !border-0', activeTab === t.id && 'on')}
          >
            <t.icon className="h-3.5 w-3.5" />
            {t.label}
          </button>
        ))}
      </div>

      {/* ════════ DAILY ════════ */}
      {activeTab === 'daily' && (
        <div className="space-y-4">
          {loading ? (
            <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="m-glow-card p-4">
                  <Skeleton className="h-3 w-20 bg-white/10" />
                  <Skeleton className="h-7 w-24 mt-2 bg-white/10" />
                  <Skeleton className="h-6 w-full mt-3 bg-white/5" />
                </div>
              ))}
            </div>
          ) : (
            kpiCards
          )}

          <div className="m-glow-card">
            <div className="flex items-center justify-between gap-3 px-4 pt-3.5 pb-2.5 border-b border-[#22304d]">
              <div>
                <div className="font-extrabold text-white text-[0.95rem]">Daily Performance</div>
                <div className="text-[0.7rem] text-[#8fa0b8]">Per-day breakdown · tap a header to sort</div>
              </div>
              <button className="m-chip !px-3" onClick={handleRefreshDaily} disabled={isRefreshing || loading}>
                <RefreshCw className={cn('h-3.5 w-3.5', isRefreshing && 'animate-spin')} />
                <span className="desk-only">Refresh</span>
              </button>
            </div>

            {loading ? (
              <div className="space-y-2 p-4">
                {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-10 w-full bg-white/5" />)}
              </div>
            ) : reportData.length === 0 ? (
              <div className="text-center py-10 text-[#8fa0b8] text-sm">No data for the selected range</div>
            ) : isMobile ? (
              dailyCards
            ) : (
              dailyTable
            )}
          </div>
        </div>
      )}

      {/* ════════ ORDERS ════════ */}
      {activeTab === 'orders' && (
        <div className="space-y-4">
          {loading ? (
            <div className="grid gap-3 grid-cols-2 lg:grid-cols-5">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="m-glow-card p-4">
                  <Skeleton className="h-7 w-16 bg-white/10" />
                  <Skeleton className="h-3 w-20 mt-2 bg-white/5" />
                </div>
              ))}
            </div>
          ) : (
            <>
              {orderData.analytics && (
                <div className="grid gap-3 grid-cols-2 lg:grid-cols-5">
                  <div className="m-glow-card m-kpi" style={{ '--kpi-c1': '#6366f1', '--kpi-c2': '#a5b4fc' }}>
                    <div className="k-label">Orders</div>
                    <div className="k-value">{orderData.analytics.total_orders}</div>
                    <div className="k-sub">
                      {orderData.analytics.cancelled_orders > 0
                        ? <span className="m-neg">{orderData.analytics.cancelled_orders} cancelled</span>
                        : 'no cancellations'}
                    </div>
                  </div>
                  <div className="m-glow-card m-kpi" style={{ '--kpi-c1': '#22d3ee', '--kpi-c2': '#67e8f9' }}>
                    <div className="k-label">Net Revenue</div>
                    <div className="k-value m-rev">{fmtUSD0(orderData.analytics.total_net)}</div>
                    <div className="k-sub">AOV <b>{fmtUSD(orderData.analytics.avg_order_value)}</b></div>
                  </div>
                  <div
                    className="m-glow-card m-kpi"
                    style={orderData.analytics.total_profit >= 0
                      ? { '--kpi-c1': '#10b981', '--kpi-c2': '#34d399' }
                      : { '--kpi-c1': '#ef4444', '--kpi-c2': '#f87171' }}
                  >
                    <div className="k-label">Profit</div>
                    <div className={`k-value ${orderData.analytics.total_profit >= 0 ? 'm-pos' : 'm-neg'}`}>
                      {fmtUSD0(orderData.analytics.total_profit)}
                    </div>
                    <div className="k-sub">Avg margin <b>{orderData.analytics.avg_margin_pct?.toFixed(1)}%</b></div>
                  </div>
                  <div className="m-glow-card m-kpi" style={{ '--kpi-c1': '#a78bfa', '--kpi-c2': '#c4b5fd' }}>
                    <div className="k-label">Returning</div>
                    <div className="k-value">{orderData.analytics.returning_customers}</div>
                    <div className="k-sub">
                      <b>
                        {orderData.analytics.total_orders > 0
                          ? `${((orderData.analytics.returning_customers / orderData.analytics.total_orders) * 100).toFixed(1)}%`
                          : '0%'}
                      </b>{' '}
                      repeat rate
                    </div>
                  </div>
                  <div className="m-glow-card m-kpi col-span-2 lg:col-span-1" style={{ '--kpi-c1': '#fb7185', '--kpi-c2': '#f0abfc' }}>
                    <div className="k-label">Channels</div>
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {['google', 'meta', 'shop', 'klaviyo', 'organic'].map((ch) => (
                        <span key={ch} className="inline-flex items-center gap-1">
                          {channelChip(ch)}
                          <b className="text-[0.74rem] text-white">{orderData.analytics.channels?.[ch] || 0}</b>
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {orderData.analytics && (
                <div className="grid gap-3 lg:grid-cols-2">
                  <div className="m-glow-card p-4">
                    <div className="font-bold text-white text-[0.82rem] flex items-center gap-2 mb-3">
                      <Globe className="h-4 w-4 text-rose-300" /> Top Countries
                    </div>
                    <div className="space-y-2">
                      {(() => {
                        const tc = (orderData.analytics.top_countries || []).slice(0, 5);
                        const mx = Math.max(...tc.map((c) => c.count), 1);
                        return tc.map((c, i) => (
                          <div key={i}>
                            <div className="flex justify-between items-center text-[0.78rem] mb-1">
                              <span className="text-[#c3cede]">{c.country}</span>
                              <b className="text-white">{c.count}</b>
                            </div>
                            <div className="h-[4px] rounded bg-[#22304d]/60 overflow-hidden">
                              <div
                                className="h-full rounded bg-gradient-to-r from-indigo-500 to-indigo-300"
                                style={{ width: `${(c.count / mx) * 100}%` }}
                              />
                            </div>
                          </div>
                        ));
                      })()}
                    </div>
                  </div>
                  <div className="m-glow-card p-4">
                    <div className="font-bold text-white text-[0.82rem] flex items-center gap-2 mb-3">
                      <Clock className="h-4 w-4 text-rose-300" /> Peak Hours
                    </div>
                    <div className="space-y-2">
                      {(() => {
                        const ph = orderData.analytics.peak_hours || [];
                        const mx = Math.max(...ph.map((h) => h.count), 1);
                        return ph.map((h, i) => (
                          <div key={i}>
                            <div className="flex justify-between items-center text-[0.78rem] mb-1">
                              <span className="text-[#c3cede]">{String(h.hour).padStart(2, '0')}:00 – {String(h.hour).padStart(2, '0')}:59</span>
                              <b className="text-white">{h.count}</b>
                            </div>
                            <div className="h-[4px] rounded bg-[#22304d]/60 overflow-hidden">
                              <div
                                className="h-full rounded bg-gradient-to-r from-rose-500 to-fuchsia-300"
                                style={{ width: `${(h.count / mx) * 100}%` }}
                              />
                            </div>
                          </div>
                        ));
                      })()}
                    </div>
                  </div>
                </div>
              )}

              <div className="m-glow-card">
                <div className="flex flex-wrap items-center gap-2 px-4 pt-3.5 pb-2.5 border-b border-[#22304d]">
                  <div className="min-w-0 mr-auto">
                    <div className="font-extrabold text-white text-[0.95rem]">Order Breakdown</div>
                    <div className="text-[0.7rem] text-[#8fa0b8]">{filteredOrders.length} orders in range</div>
                  </div>
                  <Input
                    placeholder="Search orders…"
                    value={orderSearch}
                    onChange={(e) => setOrderSearch(e.target.value)}
                    className="w-[160px] lg:w-[240px] h-8 text-[0.78rem] bg-[#0f1830] border-[#2b3a55]"
                  />
                  <button className="m-chip !px-3" onClick={handleRefreshOrders} disabled={isRefreshing || loading}>
                    <RefreshCw className={cn('h-3.5 w-3.5', isRefreshing && 'animate-spin')} />
                  </button>
                </div>

                {filteredOrders.length === 0 ? (
                  <div className="text-center py-10 text-[#8fa0b8] text-sm">No orders found</div>
                ) : isMobile ? (
                  orderCards
                ) : (
                  <div className="overflow-x-auto max-h-[640px] overflow-y-auto rounded-b-[14px]">
                    <table className="m-table">
                      <thead>
                        <tr>
                          <th className="!cursor-default w-8"></th>
                          <th className="!cursor-default !text-left">Order</th>
                          <th className="!cursor-default !text-left">Date</th>
                          <th className="!cursor-default !text-left">Customer</th>
                          <th className="!cursor-default !text-left">Channel</th>
                          <th className="!cursor-default !text-left">Country</th>
                          <th className="!cursor-default">Gross</th>
                          <th className="!cursor-default">Ship Chg</th>
                          <th className="!cursor-default">Ship Cost</th>
                          <th className="!cursor-default">Net</th>
                          <th className="!cursor-default">COGS</th>
                          <th className="!cursor-default">PSP</th>
                          <th className="!cursor-default" title="Shop Campaigns ad cost (new-customer acquisitions only)">Shop Ads</th>
                          <th className="!cursor-default">Profit</th>
                          <th className="!cursor-default">Margin</th>
                          <th className="!cursor-default">Items</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredOrders.slice(0, 100).map((order) => (
                          <React.Fragment key={order.order_id}>
                            <tr className={cn(order.is_cancelled && 'opacity-45')}>
                              <td className="!text-center">
                                {order.items && order.items.length > 0 && (
                                  <button
                                    className="p-0.5 rounded text-[#8fa0b8] hover:text-white"
                                    onClick={() => toggleOrderExpansion(order.order_id)}
                                  >
                                    {expandedOrders[order.order_id]
                                      ? <ChevronDown className="h-3.5 w-3.5" />
                                      : <ChevronRight className="h-3.5 w-3.5" />}
                                  </button>
                                )}
                              </td>
                              <td>
                                {order.order_name}
                                {order.is_cancelled && <span className="m-badge bad ml-2 !min-w-0">✕</span>}
                              </td>
                              <td className="!text-left !text-[0.74rem]">
                                <span className="text-[#c3cede]">{order.date}</span>{' '}
                                <span className="text-[#7487a3]">{order.time}</span>
                              </td>
                              <td className="!text-left max-w-[160px]">
                                <div className="truncate text-[#c3cede]">{order.customer_name}</div>
                                <span className={cn('text-[0.62rem] font-bold', order.is_returning ? 'text-blue-300' : 'text-emerald-300')}>
                                  {order.is_returning ? '↻ returning' : '★ first-time'}
                                </span>
                              </td>
                              <td className="!text-left">{channelChip(order.channel)}</td>
                              <td className="!text-left text-[#c3cede]">{order.country}</td>
                              <td>{fmtUSD(order.gross)}</td>
                              <td>{fmtUSD(order.shipping)}</td>
                              <td>{fmtUSD(order.shipping_cost)}</td>
                              <td className="m-rev">{fmtUSD(order.net)}</td>
                              <td>{fmtUSD(order.cogs)}</td>
                              <td>{fmtUSD(order.psp_fee)}</td>
                              <td className={cn((order.shop_ad_cost || 0) > 0 && 'm-gold')}>
                                {(order.shop_ad_cost || 0) > 0 ? fmtUSD(order.shop_ad_cost) : '—'}
                              </td>
                              <td>{pnl(order.profit)}</td>
                              <td>{marginBadge((order.margin_pct || 0) / 100)}</td>
                              <td>{order.items_count}</td>
                            </tr>
                            {expandedOrders[order.order_id] && order.items && order.items.length > 0 && (
                              <tr>
                                <td colSpan={16} className="!p-0 !text-left bg-black/20">
                                  <div className="px-10 py-2.5 space-y-1">
                                    {order.items.map((item, idx) => (
                                      <div key={idx} className="flex items-center justify-between gap-3 text-[0.74rem] bg-[#101a30] border border-[#22304d] rounded-lg px-3 py-1.5">
                                        <span className="text-[#c3cede] truncate">
                                          {item.name || 'Unknown Item'}
                                          {item.sku && <span className="text-[#63748f] ml-2">SKU {item.sku}</span>}
                                        </span>
                                        <span className="text-[#8fa0b8] whitespace-nowrap">
                                          ×{item.quantity} · {fmtUSD(item.gross)} · COGS {fmtUSD(item.total_cogs)}
                                        </span>
                                      </div>
                                    ))}
                                  </div>
                                </td>
                              </tr>
                            )}
                          </React.Fragment>
                        ))}
                      </tbody>
                    </table>
                    {filteredOrders.length > 100 && (
                      <p className="text-[0.72rem] text-[#8fa0b8] text-center py-2">
                        Showing first 100 of {filteredOrders.length} orders
                      </p>
                    )}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}

      {/* ════════ BEST SELLERS ════════ */}
      {activeTab === 'bestsellers' && (
        <div className="space-y-4">
          <div className="flex items-center gap-1.5">
            {[7, 30, 60].map((days) => (
              <button
                key={days}
                className={cn('m-chip', bestsellersDay === days && 'on')}
                onClick={() => setBestsellersDay(days)}
              >
                {days}D
              </button>
            ))}
          </div>

          {loading ? (
            <div className="grid gap-3 grid-cols-2 lg:grid-cols-5">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="m-glow-card p-4">
                  <Skeleton className="h-7 w-16 bg-white/10" />
                  <Skeleton className="h-3 w-20 mt-2 bg-white/5" />
                </div>
              ))}
            </div>
          ) : !bestsellersData ? (
            <div className="text-center py-10 text-[#8fa0b8] text-sm">No bestsellers data available</div>
          ) : (
            <>
              <div className="grid gap-3 grid-cols-2 lg:grid-cols-5">
                <div className="m-glow-card m-kpi" style={{ '--kpi-c1': '#6366f1', '--kpi-c2': '#a5b4fc' }}>
                  <div className="k-label">Products Sold</div>
                  <div className="k-value">{bestsellersData.analytics?.total_products_sold || 0}</div>
                </div>
                <div className="m-glow-card m-kpi" style={{ '--kpi-c1': '#a78bfa', '--kpi-c2': '#c4b5fd' }}>
                  <div className="k-label">Units</div>
                  <div className="k-value">{bestsellersData.analytics?.total_units_sold || 0}</div>
                </div>
                <div className="m-glow-card m-kpi" style={{ '--kpi-c1': '#22d3ee', '--kpi-c2': '#67e8f9' }}>
                  <div className="k-label">Revenue</div>
                  <div className="k-value m-rev">{fmtUSD0(bestsellersData.analytics?.total_revenue || 0)}</div>
                </div>
                <div
                  className="m-glow-card m-kpi"
                  style={(bestsellersData.analytics?.total_profit || 0) >= 0
                    ? { '--kpi-c1': '#10b981', '--kpi-c2': '#34d399' }
                    : { '--kpi-c1': '#ef4444', '--kpi-c2': '#f87171' }}
                >
                  <div className="k-label">Profit</div>
                  <div className={`k-value ${(bestsellersData.analytics?.total_profit || 0) >= 0 ? 'm-pos' : 'm-neg'}`}>
                    {fmtUSD0(bestsellersData.analytics?.total_profit || 0)}
                  </div>
                </div>
                <div className="m-glow-card m-kpi col-span-2 lg:col-span-1" style={{ '--kpi-c1': '#fb7185', '--kpi-c2': '#f0abfc' }}>
                  <div className="k-label">Orders</div>
                  <div className="k-value">{bestsellersData.analytics?.total_orders || 0}</div>
                </div>
              </div>

              <div className="grid gap-3 lg:grid-cols-3">
                {[
                  { title: 'Top by Quantity', rows: bestsellersData.top_by_quantity, val: (p) => `${p.total_qty} units` },
                  { title: 'Top by Revenue', rows: bestsellersData.top_by_revenue, val: (p) => fmtUSD0(p.total_revenue) },
                  { title: 'Top by Profit', rows: bestsellersData.top_by_profit, val: (p) => fmtUSD0(p.total_profit) },
                ].map((block) => (
                  <div key={block.title} className="m-glow-card p-4">
                    <div className="font-bold text-white text-[0.82rem] mb-3">{block.title}</div>
                    <div className="space-y-2">
                      {(block.rows || []).slice(0, 5).map((p, i) => (
                        <div key={i} className="flex justify-between items-center gap-2 text-[0.78rem]">
                          <span className="truncate text-[#c3cede]" title={`${p.product_title} ${p.variant_title || ''}`}>
                            <b className={cn('mr-1.5', i === 0 ? 'text-amber-300' : i === 1 ? 'text-slate-300' : i === 2 ? 'text-orange-300' : 'text-[#63748f]')}>
                              {i + 1}
                            </b>
                            {p.product_title}
                          </span>
                          <b className="text-white whitespace-nowrap">{block.val(p)}</b>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>

              <div className="m-glow-card">
                <div className="px-4 pt-3.5 pb-2.5 border-b border-[#22304d]">
                  <div className="font-extrabold text-white text-[0.95rem]">All Best Sellers</div>
                  <div className="text-[0.7rem] text-[#8fa0b8]">Top 100 by quantity · last {bestsellersDay} days</div>
                </div>
                {isMobile ? (
                  <div className="space-y-2 p-3">
                    {(bestsellersData.bestsellers || []).map((p, idx) => (
                      <div key={p.variant_id} className="m-mcard !p-2.5">
                        <div className="flex items-center gap-2.5">
                          <b className={cn('text-[0.82rem] w-6 text-center shrink-0', idx < 3 ? 'text-amber-300' : 'text-[#63748f]')}>{idx + 1}</b>
                          <div className="min-w-0 flex-1">
                            <div className="text-[0.78rem] font-semibold text-white truncate">{p.product_title}</div>
                            <div className="text-[0.66rem] text-[#8fa0b8] truncate">
                              {p.variant_title || 'Default'} · {p.total_qty} units · {fmtUSD0(p.total_revenue)}
                            </div>
                          </div>
                          <div className="text-right shrink-0">
                            <div className="text-[0.76rem] font-bold">{pnl(p.total_profit)}</div>
                            {marginBadge((p.margin_pct || 0) / 100)}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="overflow-x-auto max-h-[560px] overflow-y-auto rounded-b-[14px]">
                    <table className="m-table">
                      <thead>
                        <tr>
                          <th className="!cursor-default w-10">#</th>
                          <th className="!cursor-default !text-left">Product</th>
                          <th className="!cursor-default !text-left">Variant</th>
                          <th className="!cursor-default">Qty</th>
                          <th className="!cursor-default">Orders</th>
                          <th className="!cursor-default">Revenue</th>
                          <th className="!cursor-default">COGS</th>
                          <th className="!cursor-default">Profit</th>
                          <th className="!cursor-default">Margin</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(bestsellersData.bestsellers || []).map((p, idx) => (
                          <tr key={p.variant_id}>
                            <td className={cn('!text-center font-extrabold', idx < 3 ? 'text-amber-300' : 'text-[#63748f]')}>{idx + 1}</td>
                            <td className="max-w-[260px] truncate" title={p.product_title}>{p.product_title}</td>
                            <td className="!text-left !text-[#8fa0b8] max-w-[150px] truncate">{p.variant_title || 'Default'}</td>
                            <td className="font-bold text-white">{p.total_qty}</td>
                            <td>{p.order_count}</td>
                            <td className="m-rev">{fmtUSD(p.total_revenue)}</td>
                            <td>{fmtUSD(p.total_cogs)}</td>
                            <td>{pnl(p.total_profit)}</td>
                            <td>{marginBadge((p.margin_pct || 0) / 100)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
