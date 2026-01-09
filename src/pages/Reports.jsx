import React, { useState, useEffect, useMemo } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Calendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Input } from '@/components/ui/input';
import { CalendarIcon, TrendingUp, TrendingDown, DollarSign, ShoppingCart, Target, Percent, Package, Users, Globe, Clock, ArrowUpDown } from 'lucide-react';
import { format, subDays } from 'date-fns';
import { cn } from '@/lib/utils';

// Use same-origin API to avoid CORS issues
const REPORT_API_URL = import.meta.env.VITE_REPORT_API_URL ||
  (import.meta.env.DEV ? 'http://localhost:8080' : '/reports-api');

export default function Reports() {
  const [activeTab, setActiveTab] = useState('daily');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [reportData, setReportData] = useState([]);
  const [orderData, setOrderData] = useState({ orders: [], analytics: null });
  const [orderSearch, setOrderSearch] = useState('');
  const [dateRange, setDateRange] = useState({
    from: subDays(new Date(), 7),
    to: new Date()
  });

  // Cache key for localStorage
  const getCacheKey = () => {
    return `reports_${format(dateRange.from, 'yyyy-MM-dd')}_${format(dateRange.to, 'yyyy-MM-dd')}`;
  };

  // Load data when date range or tab changes
  useEffect(() => {
    if (activeTab === 'daily') {
      const cacheKey = getCacheKey();
      const cached = localStorage.getItem(cacheKey);

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
    }
  }, [dateRange, activeTab]);

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

  const fetchOrderData = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`${REPORT_API_URL}/order-report`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          start_date: format(dateRange.from, 'yyyy-MM-dd'),
          end_date: format(dateRange.to, 'yyyy-MM-dd')
        })
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const result = await response.json();
      setOrderData(result.data || { orders: [], analytics: null });
    } catch (err) {
      console.error('Failed to fetch order data:', err);
      setError(`Failed to fetch order report: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  // Filter orders by search
  const filteredOrders = useMemo(() => {
    if (!orderSearch.trim()) return orderData.orders || [];
    const search = orderSearch.toLowerCase();
    return (orderData.orders || []).filter(o =>
      o.order_name?.toLowerCase().includes(search) ||
      o.customer_name?.toLowerCase().includes(search) ||
      o.customer_email?.toLowerCase().includes(search) ||
      o.country?.toLowerCase().includes(search)
    );
  }, [orderData.orders, orderSearch]);

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
    return `${((value || 0) * 100).toFixed(2)}%`;
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">Business Reports</h1>
          <p className="text-slate-500 mt-1">Daily performance metrics and order analytics</p>
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
            <Button onClick={activeTab === 'daily' ? fetchReportData : fetchOrderData} variant="outline">Retry</Button>
          </CardContent>
        </Card>
      )}

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <TabsList>
          <TabsTrigger value="daily">
            <TrendingUp className="h-4 w-4 mr-2" />
            Daily Report
          </TabsTrigger>
          <TabsTrigger value="orders">
            <Package className="h-4 w-4 mr-2" />
            Order Report
          </TabsTrigger>
        </TabsList>

        {/* DAILY REPORT TAB */}
        <TabsContent value="daily" className="space-y-4">
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
                    <TableHead className="text-right">Net Sales</TableHead>
                    <TableHead className="text-right">COGS</TableHead>
                    <TableHead className="text-right">Shipping Charged</TableHead>
                    <TableHead className="text-right">Est Shipping</TableHead>
                    <TableHead className="text-right">Ad Spend</TableHead>
                    <TableHead className="text-right">Operational Profit</TableHead>
                    <TableHead className="text-right">Margin $</TableHead>
                    <TableHead className="text-right">Margin %</TableHead>
                    <TableHead className="text-right">AOV</TableHead>
                    <TableHead className="text-right">CPA</TableHead>
                    <TableHead className="text-right">Return Customers</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {reportData.map((day) => (
                    <TableRow key={day.date}>
                      <TableCell className="font-medium">
                        {day.label}
                      </TableCell>
                      <TableCell className="text-right">{day.orders}</TableCell>
                      <TableCell className="text-right">{formatCurrency(day.net)}</TableCell>
                      <TableCell className="text-right">{formatCurrency(day.cogs)}</TableCell>
                      <TableCell className="text-right">{formatCurrency(day.shipping_charged)}</TableCell>
                      <TableCell className="text-right">{formatCurrency(day.shipping_cost)}</TableCell>
                      <TableCell className="text-right">{formatCurrency(day.total_spend)}</TableCell>
                      <TableCell className="text-right">
                        <span className={day.operational_profit >= 0 ? 'text-green-600' : 'text-red-600'}>
                          {formatCurrency(day.operational_profit)}
                        </span>
                      </TableCell>
                      <TableCell className="text-right">
                        <span className={day.net_margin >= 0 ? 'text-green-600' : 'text-red-600'}>
                          {formatCurrency(day.net_margin)}
                        </span>
                      </TableCell>
                      <TableCell className="text-right">
                        <Badge variant={day.margin_pct >= 20 ? 'default' : day.margin_pct >= 10 ? 'secondary' : 'destructive'}>
                          {formatPercent(day.margin_pct)}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">{formatCurrency(day.aov)}</TableCell>
                      <TableCell className="text-right">{formatCurrency(day.general_cpa)}</TableCell>
                      <TableCell className="text-right">{day.returning_customers}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
        </TabsContent>

        {/* ORDER REPORT TAB */}
        <TabsContent value="orders" className="space-y-4">
          {loading ? (
            <div className="space-y-4">
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
                {[1, 2, 3, 4].map((i) => (
                  <Card key={i}>
                    <CardContent className="pt-6">
                      <Skeleton className="h-8 w-20" />
                      <Skeleton className="h-4 w-24 mt-2" />
                    </CardContent>
                  </Card>
                ))}
              </div>
              {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
            </div>
          ) : (
            <>
              {/* Order Analytics Summary */}
              {orderData.analytics && (
                <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
                  <Card>
                    <CardContent className="pt-6">
                      <div className="text-2xl font-bold">{orderData.analytics.total_orders}</div>
                      <p className="text-xs text-muted-foreground">Total Orders</p>
                      {orderData.analytics.cancelled_orders > 0 && (
                        <p className="text-xs text-red-500 mt-1">{orderData.analytics.cancelled_orders} cancelled</p>
                      )}
                    </CardContent>
                  </Card>
                  <Card>
                    <CardContent className="pt-6">
                      <div className="text-2xl font-bold">{formatCurrency(orderData.analytics.total_net)}</div>
                      <p className="text-xs text-muted-foreground">Net Revenue</p>
                      <p className="text-xs text-slate-500 mt-1">AOV: {formatCurrency(orderData.analytics.avg_order_value)}</p>
                    </CardContent>
                  </Card>
                  <Card>
                    <CardContent className="pt-6">
                      <div className={`text-2xl font-bold ${orderData.analytics.total_profit >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                        {formatCurrency(orderData.analytics.total_profit)}
                      </div>
                      <p className="text-xs text-muted-foreground">Total Profit</p>
                      <p className="text-xs text-slate-500 mt-1">Margin: {orderData.analytics.avg_margin_pct?.toFixed(1)}%</p>
                    </CardContent>
                  </Card>
                  <Card>
                    <CardContent className="pt-6">
                      <div className="text-2xl font-bold">{orderData.analytics.returning_customers}</div>
                      <p className="text-xs text-muted-foreground">Returning Customers</p>
                      <p className="text-xs text-slate-500 mt-1">
                        {orderData.analytics.total_orders > 0
                          ? `${((orderData.analytics.returning_customers / orderData.analytics.total_orders) * 100).toFixed(1)}% repeat`
                          : '0%'}
                      </p>
                    </CardContent>
                  </Card>
                  <Card>
                    <CardContent className="pt-6">
                      <div className="text-sm font-semibold mb-2">Channels</div>
                      <div className="space-y-1 text-xs">
                        <div className="flex justify-between">
                          <span>Google</span>
                          <Badge variant="outline">{orderData.analytics.channels?.google || 0}</Badge>
                        </div>
                        <div className="flex justify-between">
                          <span>Meta</span>
                          <Badge variant="outline">{orderData.analytics.channels?.meta || 0}</Badge>
                        </div>
                        <div className="flex justify-between">
                          <span>Organic</span>
                          <Badge variant="outline">{orderData.analytics.channels?.organic || 0}</Badge>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </div>
              )}

              {/* Top Countries & Peak Hours */}
              {orderData.analytics && (
                <div className="grid gap-4 md:grid-cols-2">
                  <Card>
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm font-medium flex items-center gap-2">
                        <Globe className="h-4 w-4" /> Top Countries
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-2">
                        {(orderData.analytics.top_countries || []).slice(0, 5).map((c, i) => (
                          <div key={i} className="flex justify-between items-center text-sm">
                            <span>{c.country}</span>
                            <Badge variant="secondary">{c.count} orders</Badge>
                          </div>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                  <Card>
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm font-medium flex items-center gap-2">
                        <Clock className="h-4 w-4" /> Peak Hours
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-2">
                        {(orderData.analytics.peak_hours || []).map((h, i) => (
                          <div key={i} className="flex justify-between items-center text-sm">
                            <span>{h.hour}:00 - {h.hour}:59</span>
                            <Badge variant="secondary">{h.count} orders</Badge>
                          </div>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                </div>
              )}

              {/* Orders Table */}
              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div>
                      <CardTitle>Order Breakdown</CardTitle>
                      <CardDescription>
                        {filteredOrders.length} orders in selected date range
                      </CardDescription>
                    </div>
                    <Input
                      placeholder="Search orders..."
                      value={orderSearch}
                      onChange={(e) => setOrderSearch(e.target.value)}
                      className="w-[250px]"
                    />
                  </div>
                </CardHeader>
                <CardContent>
                  {filteredOrders.length === 0 ? (
                    <div className="text-center py-8 text-slate-500">
                      No orders found for the selected date range
                    </div>
                  ) : (
                    <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
                      <Table>
                        <TableHeader className="sticky top-0 bg-white">
                          <TableRow>
                            <TableHead>Order</TableHead>
                            <TableHead>Date/Time</TableHead>
                            <TableHead>Customer</TableHead>
                            <TableHead>Channel</TableHead>
                            <TableHead>Country</TableHead>
                            <TableHead className="text-right">Gross</TableHead>
                            <TableHead className="text-right">Net</TableHead>
                            <TableHead className="text-right">COGS</TableHead>
                            <TableHead className="text-right">Profit</TableHead>
                            <TableHead className="text-right">Margin</TableHead>
                            <TableHead className="text-right">Items</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {filteredOrders.slice(0, 100).map((order) => (
                            <TableRow key={order.order_id} className={order.is_cancelled ? 'opacity-50' : ''}>
                              <TableCell className="font-medium">
                                {order.order_name}
                                {order.is_cancelled && <Badge variant="destructive" className="ml-2 text-xs">Cancelled</Badge>}
                              </TableCell>
                              <TableCell className="text-sm">
                                <div>{order.date}</div>
                                <div className="text-xs text-slate-500">{order.time}</div>
                              </TableCell>
                              <TableCell>
                                <div className="text-sm">{order.customer_name}</div>
                                {order.is_returning && (
                                  <Badge variant="outline" className="text-xs">Returning</Badge>
                                )}
                              </TableCell>
                              <TableCell>
                                <Badge variant={
                                  order.channel === 'google' ? 'default' :
                                  order.channel === 'meta' ? 'secondary' : 'outline'
                                }>
                                  {order.channel}
                                </Badge>
                              </TableCell>
                              <TableCell>{order.country}</TableCell>
                              <TableCell className="text-right">{formatCurrency(order.gross)}</TableCell>
                              <TableCell className="text-right">{formatCurrency(order.net)}</TableCell>
                              <TableCell className="text-right">{formatCurrency(order.cogs)}</TableCell>
                              <TableCell className="text-right">
                                <span className={order.profit >= 0 ? 'text-green-600' : 'text-red-600'}>
                                  {formatCurrency(order.profit)}
                                </span>
                              </TableCell>
                              <TableCell className="text-right">
                                <Badge variant={order.margin_pct >= 20 ? 'default' : order.margin_pct >= 10 ? 'secondary' : 'destructive'}>
                                  {order.margin_pct?.toFixed(1)}%
                                </Badge>
                              </TableCell>
                              <TableCell className="text-right">{order.items_count}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                      {filteredOrders.length > 100 && (
                        <p className="text-sm text-slate-500 text-center py-2">
                          Showing first 100 of {filteredOrders.length} orders
                        </p>
                      )}
                    </div>
                  )}
                </CardContent>
              </Card>
            </>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
