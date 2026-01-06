import React, { useState, useEffect } from "react";
import { base44 } from "@/api/base44Client";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { FileText, Calendar as CalendarIcon, AlertCircle } from "lucide-react";
import { format, subDays } from "date-fns";

export default function DailyReports() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState([]);
  const [error, setError] = useState(null);
  const [startDate, setStartDate] = useState(subDays(new Date(), 30));
  const [endDate, setEndDate] = useState(new Date());

  const fetchReport = async () => {
    setLoading(true);
    setError(null);
    try {
      const start = format(startDate, 'yyyy-MM-dd');
      const end = format(endDate, 'yyyy-MM-dd');
      
      const response = await base44.functions.invoke('getDailyReport', { 
        start_date: start, 
        end_date: end 
      });
      
      if (response.data.error) {
        throw new Error(response.data.error);
      }
      
      setData(response.data.data || []);
    } catch (err) {
      setError(err.message || 'Failed to load report');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchReport();
  }, []);

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">Daily Reports</h1>
          <p className="text-slate-500 mt-1">Historical performance from Python backend</p>
        </div>
        <div className="flex gap-3 flex-wrap">
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" className="gap-2">
                <CalendarIcon className="w-4 h-4" />
                {format(startDate, 'MMM dd')} - {format(endDate, 'MMM dd')}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="end">
              <Calendar
                mode="range"
                selected={{ from: startDate, to: endDate }}
                onSelect={(range) => {
                  if (range?.from) setStartDate(range.from);
                  if (range?.to) setEndDate(range.to);
                }}
                numberOfMonths={2}
                initialFocus
              />
            </PopoverContent>
          </Popover>
          <Button onClick={fetchReport} className="bg-indigo-600 hover:bg-indigo-700">
            Load Report
          </Button>
        </div>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            <div className="font-semibold">Failed to load report</div>
            <div className="text-sm mt-1">{error}</div>
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="w-5 h-5" />
            Daily Performance
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">
              {[...Array(10)].map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : data.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200">
                    <th className="text-left p-3 font-semibold text-slate-700">Date</th>
                    <th className="text-right p-3 font-semibold text-slate-700">Orders</th>
                    <th className="text-right p-3 font-semibold text-slate-700">Gross</th>
                    <th className="text-right p-3 font-semibold text-slate-700">Discounts</th>
                    <th className="text-right p-3 font-semibold text-slate-700">Refunds</th>
                    <th className="text-right p-3 font-semibold text-slate-700">Net</th>
                    <th className="text-right p-3 font-semibold text-slate-700">COGS</th>
                    <th className="text-right p-3 font-semibold text-slate-700">Ship Charged</th>
                    <th className="text-right p-3 font-semibold text-slate-700">Ship Cost</th>
                    <th className="text-right p-3 font-semibold text-slate-700">Google</th>
                    <th className="text-right p-3 font-semibold text-slate-700">Meta</th>
                    <th className="text-right p-3 font-semibold text-slate-700">Total Spend</th>
                    <th className="text-right p-3 font-semibold text-slate-700">PSP Fee</th>
                    <th className="text-right p-3 font-semibold text-slate-700">Op Profit</th>
                    <th className="text-right p-3 font-semibold text-slate-700">Net Margin</th>
                    <th className="text-right p-3 font-semibold text-slate-700">Margin %</th>
                    <th className="text-right p-3 font-semibold text-slate-700">AOV</th>
                    <th className="text-right p-3 font-semibold text-slate-700">Returning</th>
                    <th className="text-right p-3 font-semibold text-slate-700">General CPA</th>
                  </tr>
                </thead>
                <tbody>
                  {data.map((row, idx) => {
                    const totalSpend = (row.google_spend || 0) + (row.meta_spend || 0);
                    const marginPct = row.margin_pct !== null && row.margin_pct !== undefined 
                      ? `${(row.margin_pct * 100).toFixed(1)}%` 
                      : '—';

                    return (
                      <tr key={idx} className="border-b border-slate-100 hover:bg-slate-50">
                        <td className="p-3 whitespace-nowrap">{row.day || row.date}</td>
                        <td className="p-3 text-right">{row.orders || 0}</td>
                        <td className="p-3 text-right">${(row.gross || 0).toFixed(2)}</td>
                        <td className="p-3 text-right text-red-600">-${(row.discounts || 0).toFixed(2)}</td>
                        <td className="p-3 text-right text-red-600">-${(row.refunds || 0).toFixed(2)}</td>
                        <td className="p-3 text-right font-semibold">${(row.net || 0).toFixed(2)}</td>
                        <td className="p-3 text-right">${(row.cogs || 0).toFixed(2)}</td>
                        <td className="p-3 text-right text-green-600">${(row.shipping_charged || 0).toFixed(2)}</td>
                        <td className="p-3 text-right text-red-600">-${(row.shipping_cost || 0).toFixed(2)}</td>
                        <td className="p-3 text-right">${(row.google_spend || 0).toFixed(2)}</td>
                        <td className="p-3 text-right">${(row.meta_spend || 0).toFixed(2)}</td>
                        <td className="p-3 text-right font-semibold text-red-600">${(row.total_spend || totalSpend).toFixed(2)}</td>
                        <td className="p-3 text-right">${(row.psp_usd || 0).toFixed(2)}</td>
                        <td className="p-3 text-right font-semibold text-indigo-600">
                          ${(row.operational || row.operational_profit || 0).toFixed(2)}
                        </td>
                        <td className="p-3 text-right font-semibold text-green-600">
                          ${(row.margin || row.net_margin || 0).toFixed(2)}
                        </td>
                        <td className="p-3 text-right">{marginPct}</td>
                        <td className="p-3 text-right">${(row.aov || 0).toFixed(2)}</td>
                        <td className="p-3 text-right">{row.returning_count || 0}</td>
                        <td className="p-3 text-right font-semibold text-purple-600">
                          {row.general_cpa ? `$${row.general_cpa.toFixed(2)}` : '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-12">
              <FileText className="w-12 h-12 text-slate-300 mx-auto mb-3" />
              <p className="text-slate-600 font-medium">No data loaded</p>
              <p className="text-slate-500 text-sm mt-1">Click "Load Report" to fetch data</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}