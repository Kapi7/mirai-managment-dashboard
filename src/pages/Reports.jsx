import React, { useState, useEffect, useMemo } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Calendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { CalendarIcon, TrendingUp, TrendingDown, DollarSign, ShoppingCart, Target, Percent } from 'lucide-react';
import { format, subDays } from 'date-fns';
import { cn } from '@/lib/utils';

// Use same-origin API to avoid CORS issues
const REPORT_API_URL = import.meta.env.VITE_REPORT_API_URL ||
  (import.meta.env.DEV ? 'http://localhost:8080' : '/reports-api');

export default function Reports() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [reportData, setReportData] = useState([]);
  const [dateRange, setDateRange] = useState({
    from: subDays(new Date(), 7),
    to: new Date()
  });

  // Cache key for localStorage
  const getCacheKey = () => {
    return `reports_${format(dateRange.from, 'yyyy-MM-dd')}_${format(dateRange.to, 'yyyy-MM-dd')}`;
  };

  // Load from cache on mount
  useEffect(() => {
    const cacheKey = getCacheKey();
    const cached = localStorage.getItem(cacheKey);

    if (cached) {
      try {
        const { data, timestamp } = JSON.parse(cached);
        // Cache valid for 5 minutes
        if (Date.now() - timestamp < 5 * 60 * 1000) {
          setReportData(data);
          return; // Skip API call
        }
      } catch (e) {
        // Invalid cache, continue to fetch
      }
    }

    fetchReportData();
  }, [dateRange]);

  const fetchReportData = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`${REPORT_API_URL}/daily-report`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          start_date: format(dateRange.from, 'yyyy-MM-dd'),
          end_date: format(dateRange.to, 'yyyy-MM-dd')
        }),
        mode: 'cors'
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const result = await response.json();
      const data = result.data || [];
      setReportData(data);

      // Cache the result
      const cacheKey = getCacheKey();
      localStorage.setItem(cacheKey, JSON.stringify({
        data,
        timestamp: Date.now()
      }));
    } catch (err) {
      console.error('Failed to fetch report data:', err);
      setError(`Unable to connect to reporting API: ${err.message}. Please check that mirai-reports.onrender.com is deployed and has CORS enabled.`);
    } finally {
      setLoading(false);
    }
  };

  // Calculate summary metrics (memoized to avoid recalculation on every render)
  const summary = useMemo(() => {
    return reportData.reduce((acc, day) => ({
      totalOrders: acc.totalOrders + (day.orders || 0),
      totalGross: acc.totalGross + (day.gross || 0),
      totalNet: acc.totalNet + (day.net || 0),
      totalSpend: acc.totalSpend + (day.total_spend || 0),
      totalProfit: acc.totalProfit + (day.operational_profit || 0),
    }), { totalOrders: 0, totalGross: 0, totalNet: 0, totalSpend: 0, totalProfit: 0 });
  }, [reportData]);

  const avgMargin = useMemo(() => {
    return reportData.length > 0
      ? reportData.reduce((sum, day) => sum + (day.margin_pct || 0), 0) / reportData.length
      : 0;
  }, [reportData]);

  const avgAOV = useMemo(() => {
    return summary.totalOrders > 0 ? summary.totalNet / summary.totalOrders : 0;
  }, [summary]);

  const formatCurrency = (value) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2
    }).format(value || 0);
  };

  const formatPercent = (value) => {
    return `${(value || 0).toFixed(2)}%`;
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">Business Reports</h1>
          <p className="text-slate-500 mt-1">Daily performance metrics and insights</p>
        </div>

        {/* Date Range Picker */}
        <Popover>
          <PopoverTrigger asChild>
            <Button
              variant="outline"
              className={cn(
                "w-[280px] justify-start text-left font-normal",
                !dateRange && "text-muted-foreground"
              )}
            >
              <CalendarIcon className="mr-2 h-4 w-4" />
              {dateRange?.from ? (
                dateRange.to ? (
                  <>
                    {format(dateRange.from, "LLL dd, y")} -{" "}
                    {format(dateRange.to, "LLL dd, y")}
                  </>
                ) : (
                  format(dateRange.from, "LLL dd, y")
                )
              ) : (
                <span>Pick a date range</span>
              )}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0" align="end">
            <div className="p-3 space-y-2">
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setDateRange({ from: subDays(new Date(), 7), to: new Date() })}
                >
                  Last 7 Days
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setDateRange({ from: subDays(new Date(), 30), to: new Date() })}
                >
                  Last 30 Days
                </Button>
              </div>
              <Calendar
                initialFocus
                mode="range"
                defaultMonth={dateRange?.from}
                selected={dateRange}
                onSelect={setDateRange}
                numberOfMonths={2}
              />
            </div>
          </PopoverContent>
        </Popover>
      </div>

      {/* Error State */}
      {error && (
        <Card className="border-red-200 bg-red-50">
          <CardHeader>
            <CardTitle className="text-red-900">Error Loading Reports</CardTitle>
            <CardDescription className="text-red-700">{error}</CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={fetchReportData} variant="outline">Retry</Button>
          </CardContent>
        </Card>
      )}

      {/* Summary Cards */}
      {loading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <Card key={i}>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <Skeleton className="h-4 w-[100px]" />
                <Skeleton className="h-4 w-4 rounded-full" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-8 w-[120px]" />
                <Skeleton className="h-3 w-[80px] mt-2" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {/* Total Orders */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Total Orders</CardTitle>
              <ShoppingCart className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{summary.totalOrders}</div>
              <p className="text-xs text-muted-foreground">
                Avg AOV: {formatCurrency(avgAOV)}
              </p>
            </CardContent>
          </Card>

          {/* Total Revenue */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Total Revenue</CardTitle>
              <DollarSign className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{formatCurrency(summary.totalNet)}</div>
              <p className="text-xs text-muted-foreground">
                Gross: {formatCurrency(summary.totalGross)}
              </p>
            </CardContent>
          </Card>

          {/* Total Spend */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Total Ad Spend</CardTitle>
              <Target className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{formatCurrency(summary.totalSpend)}</div>
              <p className="text-xs text-muted-foreground">
                Google + Meta ads
              </p>
            </CardContent>
          </Card>

          {/* Profit */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Net Profit</CardTitle>
              <Percent className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className={`text-2xl font-bold ${summary.totalProfit >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                {formatCurrency(summary.totalProfit)}
              </div>
              <p className="text-xs text-muted-foreground">
                Avg Margin: {formatPercent(avgMargin)}
              </p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Detailed Daily Report Table */}
      <Card>
        <CardHeader>
          <CardTitle>Daily Performance Breakdown</CardTitle>
          <CardDescription>
            Detailed metrics for each day in the selected range
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">
              {[1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : reportData.length === 0 ? (
            <div className="text-center py-8 text-slate-500">
              No data available for the selected date range
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Date</TableHead>
                    <TableHead className="text-right">Orders</TableHead>
                    <TableHead className="text-right">Revenue</TableHead>
                    <TableHead className="text-right">Ad Spend</TableHead>
                    <TableHead className="text-right">Profit</TableHead>
                    <TableHead className="text-right">Margin %</TableHead>
                    <TableHead className="text-right">AOV</TableHead>
                    <TableHead className="text-right">CPA</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {reportData.map((day) => (
                    <TableRow key={day.date}>
                      <TableCell className="font-medium">
                        {day.label || format(new Date(day.date), 'MMM dd, yyyy')}
                      </TableCell>
                      <TableCell className="text-right">{day.orders}</TableCell>
                      <TableCell className="text-right">{formatCurrency(day.net)}</TableCell>
                      <TableCell className="text-right">{formatCurrency(day.total_spend)}</TableCell>
                      <TableCell className="text-right">
                        <span className={day.operational_profit >= 0 ? 'text-green-600' : 'text-red-600'}>
                          {formatCurrency(day.operational_profit)}
                        </span>
                      </TableCell>
                      <TableCell className="text-right">
                        <Badge variant={day.margin_pct >= 20 ? 'default' : day.margin_pct >= 10 ? 'secondary' : 'destructive'}>
                          {formatPercent(day.margin_pct)}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">{formatCurrency(day.aov)}</TableCell>
                      <TableCell className="text-right">{formatCurrency(day.general_cpa)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
