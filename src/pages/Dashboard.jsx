
import React, { useState, useEffect } from "react";
import { base44 } from "@/api/base44Client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { 
  RefreshCw, 
  TrendingUp, 
  ShoppingCart, 
  DollarSign, 
  Package,
  Send,
  Loader2,
  Calendar as CalendarIcon,
  ArrowUpRight,
  ArrowDownRight
} from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { format, subDays } from "date-fns";

export default function Dashboard() {
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [todayData, setTodayData] = useState(null);
  const [yesterdayData, setYesterdayData] = useState(null);
  const [error, setError] = useState(null);
  const [selectedDate, setSelectedDate] = useState(new Date());

  const fetchDashboardData = async (date = new Date()) => {
    setLoading(true);
    setError(null);
    try {
      const dateStr = format(date, 'yyyy-MM-dd');
      const response = await base44.functions.invoke('getDashboardMetrics', { date: dateStr });
      setTodayData(response.data.today);
      setYesterdayData(response.data.yesterday);
    } catch (err) {
      setError(err.message || "Failed to load dashboard data");
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    await fetchDashboardData(selectedDate);
    setRefreshing(false);
  };

  const sendTelegramSummary = async () => {
    try {
      await base44.functions.invoke('sendTelegramSummary', {});
    } catch (err) {
      setError(err.message || "Failed to send Telegram summary");
    }
  };

  useEffect(() => {
    fetchDashboardData(selectedDate);
  }, [selectedDate]);

  const MetricCard = ({ title, value, change, icon: Icon, format = "currency", loading }) => {
    const isPositive = change >= 0;
    const formatted = format === "currency" 
      ? `$${(value || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
      : format === "number"
      ? (value || 0).toLocaleString('en-US')
      : format === "percent"
      ? `${(value || 0).toFixed(1)}%`
      : value;

    return (
      <Card className="relative overflow-hidden border-slate-200 shadow-sm hover:shadow-md transition-shadow">
        <div className="absolute top-0 right-0 w-32 h-32 bg-gradient-to-br from-indigo-500/10 to-purple-600/10 rounded-full transform translate-x-12 -translate-y-12" />
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium text-slate-600">{title}</CardTitle>
          <div className="p-2 bg-indigo-100 rounded-lg">
            <Icon className="h-4 w-4 text-indigo-600" />
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <Skeleton className="h-8 w-24" />
          ) : (
            <>
              <div className="text-2xl font-bold text-slate-900">{formatted}</div>
              {change !== undefined && (
                <div className={`flex items-center gap-1 mt-1 text-sm ${isPositive ? 'text-green-600' : 'text-red-600'}`}>
                  {isPositive ? <ArrowUpRight className="w-4 h-4" /> : <ArrowDownRight className="w-4 h-4" />}
                  <span>{Math.abs(change).toFixed(1)}% vs yesterday</span>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    );
  };

  const calculateChange = (today, yesterday) => {
    if (!yesterday || yesterday === 0) return 0;
    return ((today - yesterday) / yesterday) * 100;
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">Dashboard</h1>
          <p className="text-slate-500 mt-1">Real-time overview of your Mirai Skin store</p>
        </div>
        <div className="flex gap-3 flex-wrap">
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" className="gap-2">
                <CalendarIcon className="w-4 h-4" />
                {format(selectedDate, 'MMM dd, yyyy')}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="end">
              <Calendar
                mode="single"
                selected={selectedDate}
                onSelect={(date) => date && setSelectedDate(date)}
                initialFocus
              />
            </PopoverContent>
          </Popover>
          <Button
            variant="outline"
            onClick={sendTelegramSummary}
            className="gap-2"
          >
            <Send className="w-4 h-4" />
            Send to Telegram
          </Button>
          <Button
            onClick={handleRefresh}
            disabled={refreshing}
            className="gap-2 bg-indigo-600 hover:bg-indigo-700"
          >
            {refreshing ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <RefreshCw className="w-4 h-4" />
            )}
            Refresh Data
          </Button>
        </div>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="flex items-center gap-2 text-sm text-slate-500">
        <CalendarIcon className="w-4 h-4" />
        <span>Showing data for: {format(selectedDate, 'MMMM dd, yyyy')}</span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard
          title="Net Sales"
          value={todayData?.net_sales}
          change={calculateChange(todayData?.net_sales, yesterdayData?.net_sales)}
          icon={DollarSign}
          format="currency"
          loading={loading}
        />
        <MetricCard
          title="Orders"
          value={todayData?.orders}
          change={calculateChange(todayData?.orders, yesterdayData?.orders)}
          icon={ShoppingCart}
          format="number"
          loading={loading}
        />
        <MetricCard
          title="Net Margin"
          value={todayData?.net_margin}
          change={calculateChange(todayData?.net_margin, yesterdayData?.net_margin)}
          icon={TrendingUp}
          format="currency"
          loading={loading}
        />
        <MetricCard
          title="COGS"
          value={todayData?.cogs}
          change={calculateChange(todayData?.cogs, yesterdayData?.cogs)}
          icon={Package}
          format="currency"
          loading={loading}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="border-slate-200 shadow-sm">
          <CardHeader>
            <CardTitle className="text-lg">Today's Performance</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {loading ? (
              <>
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-full" />
              </>
            ) : (
              <>
                <div className="flex justify-between items-center py-2 border-b border-slate-100">
                  <span className="text-sm text-slate-600">Gross Sales</span>
                  <span className="font-semibold">${(todayData?.gross_sales || 0).toFixed(2)}</span>
                </div>
                <div className="flex justify-between items-center py-2 border-b border-slate-100">
                  <span className="text-sm text-slate-600">Discounts</span>
                  <span className="font-semibold text-red-600">-${(todayData?.discounts || 0).toFixed(2)}</span>
                </div>
                <div className="flex justify-between items-center py-2 border-b border-slate-100">
                  <span className="text-sm text-slate-600">Refunds</span>
                  <span className="font-semibold text-red-600">-${(todayData?.refunds || 0).toFixed(2)}</span>
                </div>
                <div className="flex justify-between items-center py-2 border-b border-slate-100">
                  <span className="text-sm text-slate-600">Shipping Charged</span>
                  <span className="font-semibold text-green-600">${(todayData?.shipping_charged || 0).toFixed(2)}</span>
                </div>
                <div className="flex justify-between items-center py-2 border-b border-slate-100">
                  <span className="text-sm text-slate-600">Shipping Cost</span>
                  <span className="font-semibold text-red-600">-${(todayData?.shipping_cost || 0).toFixed(2)}</span>
                </div>
                <div className="flex justify-between items-center py-2 border-b border-slate-100">
                  <span className="text-sm text-slate-600">PSP Fees</span>
                  <span className="font-semibold text-red-600">-${(todayData?.psp_fees || 0).toFixed(2)}</span>
                </div>
                <div className="flex justify-between items-center py-2 pt-4 border-t-2 border-slate-200">
                  <span className="text-sm font-semibold text-slate-900">Operational Profit</span>
                  <span className="font-bold text-lg text-indigo-600">${(todayData?.operational_profit || 0).toFixed(2)}</span>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        <Card className="border-slate-200 shadow-sm">
          <CardHeader>
            <CardTitle className="text-lg">Marketing Spend</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {loading ? (
              <>
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-full" />
              </>
            ) : (
              <>
                <div className="flex justify-between items-center py-2 border-b border-slate-100">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-slate-600">Google Ads</span>
                    <Badge variant="secondary" className="text-xs">{todayData?.google_purchases || 0} purchases</Badge>
                  </div>
                  <span className="font-semibold">${(todayData?.google_spend || 0).toFixed(2)}</span>
                </div>
                <div className="flex justify-between items-center py-2 border-b border-slate-100">
                  <span className="text-sm text-slate-600">Google CPA</span>
                  <span className="font-semibold text-purple-600">
                    {todayData?.google_cpa ? `$${todayData.google_cpa.toFixed(2)}` : '—'}
                  </span>
                </div>
                <div className="flex justify-between items-center py-2 border-b border-slate-100">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-slate-600">Meta Ads</span>
                    <Badge variant="secondary" className="text-xs">{todayData?.meta_purchases || 0} purchases</Badge>
                  </div>
                  <span className="font-semibold">${(todayData?.meta_spend || 0).toFixed(2)}</span>
                </div>
                <div className="flex justify-between items-center py-2 border-b border-slate-100">
                  <span className="text-sm text-slate-600">Meta CPA</span>
                  <span className="font-semibold text-purple-600">
                    {todayData?.meta_cpa ? `$${todayData.meta_cpa.toFixed(2)}` : '—'}
                  </span>
                </div>
                <div className="flex justify-between items-center py-2 pt-4 border-t-2 border-slate-200">
                  <span className="text-sm font-semibold text-slate-900">Total Spend</span>
                  <span className="font-bold text-lg text-red-600">${(todayData?.total_spend || 0).toFixed(2)}</span>
                </div>
                <div className="flex justify-between items-center py-2 border-t border-slate-100">
                  <span className="text-sm font-semibold text-slate-900">General CPA</span>
                  <span className="font-bold text-purple-600">
                    {todayData?.general_cpa ? `$${todayData.general_cpa.toFixed(2)}` : '—'}
                  </span>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
