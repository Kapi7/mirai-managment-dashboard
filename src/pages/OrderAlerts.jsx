import React, { useState, useEffect } from "react";
import { base44 } from "@/api/base44Client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Bell, Calendar as CalendarIcon, RefreshCw, Loader2, Package, DollarSign, TrendingUp } from "lucide-react";
import { format } from "date-fns";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";

export default function OrderAlerts() {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedDate, setSelectedDate] = useState(new Date());

  const fetchOrders = async (date) => {
    setLoading(true);
    setError(null);
    try {
      const dateStr = format(date, 'yyyy-MM-dd');
      const response = await base44.functions.invoke('getOrderAlerts', { date: dateStr });
      setOrders(response.data.orders || []);
    } catch (err) {
      setError(err.message || "Failed to load orders");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOrders(selectedDate);
  }, [selectedDate]);

  const OrderCard = ({ order }) => {
    const isReturning = order.customer_type === 'returning';
    const profitColor = order.approx_profit >= 0 ? 'text-green-600' : 'text-red-600';
    
    return (
      <Card className="border-slate-200 hover:shadow-md transition-shadow">
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-2">
              <Package className="w-5 h-5 text-indigo-600" />
              <CardTitle className="text-lg font-semibold">
                Order #{order.order_number}
              </CardTitle>
              {order.country_flag && (
                <span className="text-xl">{order.country_flag}</span>
              )}
            </div>
            <Badge variant={isReturning ? "secondary" : "default"} className="text-xs">
              {isReturning ? '🔄 Returning' : '✨ New'}
            </Badge>
          </div>
          <div className="text-xs text-slate-500 mt-1">
            {order.marketing_channel && (
              <span className="inline-flex items-center gap-1">
                📣 {order.marketing_channel}
              </span>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <div className="flex justify-between border-b border-slate-100 py-1">
              <span className="text-slate-600">💵 Gross:</span>
              <span className="font-semibold">${order.gross.toFixed(2)}</span>
            </div>
            <div className="flex justify-between border-b border-slate-100 py-1">
              <span className="text-slate-600">🧾 Net:</span>
              <span className="font-semibold">${order.net.toFixed(2)}</span>
            </div>
            <div className="flex justify-between border-b border-slate-100 py-1">
              <span className="text-slate-600">📦 Shipping:</span>
              <span className="font-semibold text-green-600">${order.shipping_charged.toFixed(2)}</span>
            </div>
            <div className="flex justify-between border-b border-slate-100 py-1">
              <span className="text-slate-600">💰 COGS:</span>
              <span className="font-semibold text-red-600">${order.cogs.toFixed(2)}</span>
            </div>
            {order.approx_shipping !== null && (
              <div className="flex justify-between border-b border-slate-100 py-1">
                <span className="text-slate-600">🚚 Ship Cost:</span>
                <span className="font-semibold text-orange-600">
                  ${order.approx_shipping.toFixed(2)}
                  {order.weight_g && <span className="text-xs text-slate-500 ml-1">({order.weight_g}g)</span>}
                </span>
              </div>
            )}
            {order.psp_fee !== null && (
              <div className="flex justify-between border-b border-slate-100 py-1">
                <span className="text-slate-600">💳 PSP Fee:</span>
                <span className="font-semibold text-purple-600">${order.psp_fee.toFixed(2)}</span>
              </div>
            )}
          </div>
          
          {order.approx_profit !== null && (
            <div className="flex items-center justify-between pt-3 mt-3 border-t-2 border-slate-200">
              <span className="text-sm font-semibold text-slate-900 flex items-center gap-1">
                <TrendingUp className="w-4 h-4" />
                Approx. Profit:
              </span>
              <span className={`text-lg font-bold ${profitColor}`}>
                ${order.approx_profit.toFixed(2)}
              </span>
            </div>
          )}
        </CardContent>
      </Card>
    );
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-3xl font-bold text-slate-900 flex items-center gap-2">
            <Bell className="w-8 h-8" />
            Order Alerts
          </h1>
          <p className="text-slate-500 mt-1">Individual order details with profit calculations</p>
        </div>
        
        <div className="flex gap-3">
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
            onClick={() => fetchOrders(selectedDate)}
            disabled={loading}
            className="gap-2 bg-indigo-600 hover:bg-indigo-700"
          >
            {loading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <RefreshCw className="w-4 h-4" />
            )}
            Refresh
          </Button>
        </div>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="flex items-center justify-between">
        <div className="text-sm text-slate-600">
          Showing {orders.length} orders for {format(selectedDate, 'MMMM dd, yyyy')}
        </div>
        {orders.length > 0 && (
          <div className="flex items-center gap-4 text-sm">
            <div className="flex items-center gap-1">
              <DollarSign className="w-4 h-4 text-green-600" />
              <span>Total: ${orders.reduce((sum, o) => sum + o.net, 0).toFixed(2)}</span>
            </div>
            <div className="flex items-center gap-1">
              <TrendingUp className="w-4 h-4 text-indigo-600" />
              <span>Profit: ${orders.reduce((sum, o) => sum + (o.approx_profit || 0), 0).toFixed(2)}</span>
            </div>
          </div>
        )}
      </div>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3, 4, 5, 6].map(i => (
            <Card key={i} className="border-slate-200">
              <CardHeader>
                <Skeleton className="h-6 w-32" />
              </CardHeader>
              <CardContent className="space-y-2">
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-full" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : orders.length === 0 ? (
        <Card className="border-slate-200">
          <CardContent className="py-12 text-center">
            <Bell className="w-12 h-12 text-slate-300 mx-auto mb-4" />
            <p className="text-slate-600">No orders found for this date</p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {orders.map((order, idx) => (
            <OrderCard key={idx} order={order} />
          ))}
        </div>
      )}
    </div>
  );
}