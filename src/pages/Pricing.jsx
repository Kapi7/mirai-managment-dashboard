import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Badge } from '@/components/ui/badge';
import { DollarSign, TrendingUp, Clock, Target } from 'lucide-react';

const API_URL = import.meta.env.VITE_REPORT_API_URL ||
  (import.meta.env.DEV ? 'http://localhost:8080' : '/reports-api');

export default function Pricing() {
  const [activeTab, setActiveTab] = useState('items');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Items tab state
  const [items, setItems] = useState([]);
  const [selectedMarket, setSelectedMarket] = useState('all');
  const [markets, setMarkets] = useState([]);

  // Price Updates tab state
  const [priceUpdates, setPriceUpdates] = useState([]);

  // Update Log tab state
  const [updateLog, setUpdateLog] = useState([]);

  // Target Prices tab state
  const [targetPrices, setTargetPrices] = useState([]);
  const [selectedCountry, setSelectedCountry] = useState('US');
  const [countries, setCountries] = useState(['US', 'UK', 'AU', 'CA']);

  // Fetch markets on mount
  useEffect(() => {
    fetchMarkets();
    fetchCountries();
  }, []);

  // Fetch data when tab changes
  useEffect(() => {
    switch (activeTab) {
      case 'items':
        fetchItems();
        break;
      case 'price-updates':
        fetchPriceUpdates();
        break;
      case 'update-log':
        fetchUpdateLog();
        break;
      case 'target-prices':
        fetchTargetPrices();
        break;
      default:
        break;
    }
  }, [activeTab, selectedMarket, selectedCountry]);

  const fetchMarkets = async () => {
    try {
      const response = await fetch(`${API_URL}/pricing/markets`);
      const result = await response.json();
      if (result.markets) {
        setMarkets(['all', ...result.markets]);
      }
    } catch (err) {
      console.error('Error fetching markets:', err);
    }
  };

  const fetchCountries = async () => {
    try {
      const response = await fetch(`${API_URL}/pricing/countries`);
      const result = await response.json();
      if (result.countries) {
        setCountries(result.countries);
      }
    } catch (err) {
      console.error('Error fetching countries:', err);
    }
  };

  const fetchItems = async () => {
    setLoading(true);
    setError(null);
    try {
      const url = selectedMarket === 'all'
        ? `${API_URL}/pricing/items`
        : `${API_URL}/pricing/items?market=${selectedMarket}`;

      const response = await fetch(url);
      const result = await response.json();

      if (result.error) {
        setError(result.error);
      } else {
        setItems(result.data || []);
      }
    } catch (err) {
      setError(`Failed to fetch items: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const fetchPriceUpdates = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_URL}/pricing/price-updates`);
      const result = await response.json();

      if (result.error) {
        setError(result.error);
      } else {
        setPriceUpdates(result.data || []);
      }
    } catch (err) {
      setError(`Failed to fetch price updates: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const fetchUpdateLog = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_URL}/pricing/update-log?limit=100`);
      const result = await response.json();

      if (result.error) {
        setError(result.error);
      } else {
        setUpdateLog(result.data || []);
      }
    } catch (err) {
      setError(`Failed to fetch update log: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const fetchTargetPrices = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_URL}/pricing/target-prices?country=${selectedCountry}`);
      const result = await response.json();

      if (result.error) {
        setError(result.error);
      } else {
        setTargetPrices(result.data || []);
      }
    } catch (err) {
      setError(`Failed to fetch target prices: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

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
          <h1 className="text-3xl font-bold text-slate-900">Pricing Management</h1>
          <p className="text-slate-500 mt-1">Manage product pricing across markets</p>
        </div>
      </div>

      {/* Error State */}
      {error && (
        <Card className="border-red-200 bg-red-50">
          <CardHeader>
            <CardTitle className="text-red-900">Error Loading Data</CardTitle>
            <CardDescription className="text-red-700">{error}</CardDescription>
          </CardHeader>
        </Card>
      )}

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid w-full grid-cols-4">
          <TabsTrigger value="items">
            <DollarSign className="h-4 w-4 mr-2" />
            Items
          </TabsTrigger>
          <TabsTrigger value="price-updates">
            <TrendingUp className="h-4 w-4 mr-2" />
            Price Updates
          </TabsTrigger>
          <TabsTrigger value="update-log">
            <Clock className="h-4 w-4 mr-2" />
            Update Log
          </TabsTrigger>
          <TabsTrigger value="target-prices">
            <Target className="h-4 w-4 mr-2" />
            Target Prices
          </TabsTrigger>
        </TabsList>

        {/* ITEMS TAB */}
        <TabsContent value="items">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Product Items</CardTitle>
                  <CardDescription>View product inventory with pricing</CardDescription>
                </div>
                <Select value={selectedMarket} onValueChange={setSelectedMarket}>
                  <SelectTrigger className="w-[180px]">
                    <SelectValue placeholder="Select market" />
                  </SelectTrigger>
                  <SelectContent>
                    {markets.map((market) => (
                      <SelectItem key={market} value={market}>
                        {market === 'all' ? 'All Markets' : market}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="space-y-2">
                  {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
                </div>
              ) : items.length === 0 ? (
                <div className="text-center py-8 text-slate-500">No items found</div>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Variant ID</TableHead>
                        <TableHead>Item</TableHead>
                        <TableHead className="text-right">Weight (g)</TableHead>
                        <TableHead className="text-right">COGS</TableHead>
                        <TableHead className="text-right">Retail Base</TableHead>
                        <TableHead className="text-right">Compare At Base</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {items.map((item) => (
                        <TableRow key={item.variant_id}>
                          <TableCell className="font-mono text-sm">{item.variant_id}</TableCell>
                          <TableCell className="font-medium">{item.item}</TableCell>
                          <TableCell className="text-right">{item.weight.toFixed(0)}</TableCell>
                          <TableCell className="text-right">{formatCurrency(item.cogs)}</TableCell>
                          <TableCell className="text-right">{formatCurrency(item.retail_base)}</TableCell>
                          <TableCell className="text-right">{formatCurrency(item.compare_at_base)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* PRICE UPDATES TAB */}
        <TabsContent value="price-updates">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Pending Price Updates</CardTitle>
                  <CardDescription>Review and apply price changes</CardDescription>
                </div>
                <Button variant="default" disabled={priceUpdates.length === 0}>
                  Apply Updates ({priceUpdates.length})
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="space-y-2">
                  {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
                </div>
              ) : priceUpdates.length === 0 ? (
                <div className="text-center py-8 text-slate-500">No pending updates</div>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Variant ID</TableHead>
                        <TableHead>Item</TableHead>
                        <TableHead>Market</TableHead>
                        <TableHead className="text-right">Current Price</TableHead>
                        <TableHead className="text-right">New Price</TableHead>
                        <TableHead className="text-right">Change</TableHead>
                        <TableHead className="text-right">Compare At</TableHead>
                        <TableHead>Notes</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {priceUpdates.map((update, idx) => {
                        const changePct = ((update.new_price - update.current_price) / update.current_price) * 100;
                        return (
                          <TableRow key={idx}>
                            <TableCell className="font-mono text-sm">{update.variant_id}</TableCell>
                            <TableCell className="font-medium">{update.item}</TableCell>
                            <TableCell><Badge variant="outline">{update.market}</Badge></TableCell>
                            <TableCell className="text-right">{formatCurrency(update.current_price)}</TableCell>
                            <TableCell className="text-right font-semibold">{formatCurrency(update.new_price)}</TableCell>
                            <TableCell className="text-right">
                              <span className={changePct >= 0 ? 'text-green-600' : 'text-red-600'}>
                                {changePct >= 0 ? '+' : ''}{formatPercent(changePct)}
                              </span>
                            </TableCell>
                            <TableCell className="text-right">{formatCurrency(update.compare_at)}</TableCell>
                            <TableCell className="text-sm text-slate-600">{update.notes}</TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* UPDATE LOG TAB */}
        <TabsContent value="update-log">
          <Card>
            <CardHeader>
              <CardTitle>Price Update History</CardTitle>
              <CardDescription>Recent price changes and their status</CardDescription>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="space-y-2">
                  {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
                </div>
              ) : updateLog.length === 0 ? (
                <div className="text-center py-8 text-slate-500">No update history</div>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Timestamp</TableHead>
                        <TableHead>Variant ID</TableHead>
                        <TableHead>Item</TableHead>
                        <TableHead>Market</TableHead>
                        <TableHead className="text-right">Old Price</TableHead>
                        <TableHead className="text-right">New Price</TableHead>
                        <TableHead className="text-right">Change %</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Notes</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {updateLog.map((log, idx) => (
                        <TableRow key={idx}>
                          <TableCell className="text-sm">{log.timestamp}</TableCell>
                          <TableCell className="font-mono text-sm">{log.variant_id}</TableCell>
                          <TableCell className="font-medium">{log.item}</TableCell>
                          <TableCell><Badge variant="outline">{log.market}</Badge></TableCell>
                          <TableCell className="text-right">{formatCurrency(log.old_price)}</TableCell>
                          <TableCell className="text-right">{formatCurrency(log.new_price)}</TableCell>
                          <TableCell className="text-right">
                            <span className={log.change_pct >= 0 ? 'text-green-600' : 'text-red-600'}>
                              {log.change_pct >= 0 ? '+' : ''}{formatPercent(log.change_pct)}
                            </span>
                          </TableCell>
                          <TableCell>
                            <Badge variant={log.status === 'success' ? 'default' : 'destructive'}>
                              {log.status}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-sm text-slate-600">{log.notes}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* TARGET PRICES TAB */}
        <TabsContent value="target-prices">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Target Prices</CardTitle>
                  <CardDescription>Calculated target prices with competitive analysis</CardDescription>
                </div>
                <Select value={selectedCountry} onValueChange={setSelectedCountry}>
                  <SelectTrigger className="w-[180px]">
                    <SelectValue placeholder="Select country" />
                  </SelectTrigger>
                  <SelectContent>
                    {countries.map((country) => (
                      <SelectItem key={country} value={country}>
                        {country}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="space-y-2">
                  {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
                </div>
              ) : targetPrices.length === 0 ? (
                <div className="text-center py-8 text-slate-500">No target prices available</div>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Variant ID</TableHead>
                        <TableHead>Item</TableHead>
                        <TableHead className="text-right">Weight (g)</TableHead>
                        <TableHead className="text-right">COGS</TableHead>
                        <TableHead className="text-right">Current</TableHead>
                        <TableHead className="text-right">Ship</TableHead>
                        <TableHead className="text-right">Breakeven</TableHead>
                        <TableHead className="text-right">Target</TableHead>
                        <TableHead className="text-right">Suggested</TableHead>
                        <TableHead className="text-right">Comp Low</TableHead>
                        <TableHead className="text-right">Comp Avg</TableHead>
                        <TableHead className="text-right">Comp High</TableHead>
                        <TableHead className="text-right">Competitive</TableHead>
                        <TableHead className="text-right">Final</TableHead>
                        <TableHead className="text-right">Loss $</TableHead>
                        <TableHead>Priority</TableHead>
                        <TableHead className="text-right">Inc %</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {targetPrices.map((price) => {
                        const countryKey = selectedCountry;
                        return (
                          <TableRow key={price.variant_id}>
                            <TableCell className="font-mono text-sm">{price.variant_id}</TableCell>
                            <TableCell className="font-medium max-w-[200px] truncate">{price.item}</TableCell>
                            <TableCell className="text-right">{price.weight_g.toFixed(0)}</TableCell>
                            <TableCell className="text-right">{formatCurrency(price.cogs)}</TableCell>
                            <TableCell className="text-right">{formatCurrency(price[`current_${countryKey}`])}</TableCell>
                            <TableCell className="text-right">{formatCurrency(price[`ship_${countryKey}`])}</TableCell>
                            <TableCell className="text-right">{formatCurrency(price[`breakeven_${countryKey}`])}</TableCell>
                            <TableCell className="text-right">{formatCurrency(price[`target_${countryKey}`])}</TableCell>
                            <TableCell className="text-right">{formatCurrency(price[`suggested_${countryKey}`])}</TableCell>
                            <TableCell className="text-right">{formatCurrency(price[`comp_low_${countryKey}`])}</TableCell>
                            <TableCell className="text-right">{formatCurrency(price[`comp_avg_${countryKey}`])}</TableCell>
                            <TableCell className="text-right">{formatCurrency(price[`comp_high_${countryKey}`])}</TableCell>
                            <TableCell className="text-right">{formatCurrency(price[`competitive_price_${countryKey}`])}</TableCell>
                            <TableCell className="text-right font-semibold">{formatCurrency(price[`final_suggested_${countryKey}`])}</TableCell>
                            <TableCell className="text-right">
                              <span className={price[`loss_amount_${countryKey}`] < 0 ? 'text-red-600' : 'text-green-600'}>
                                {formatCurrency(price[`loss_amount_${countryKey}`])}
                              </span>
                            </TableCell>
                            <TableCell>
                              <Badge variant={
                                price[`priority_${countryKey}`] === 'HIGH' ? 'destructive' :
                                price[`priority_${countryKey}`] === 'MEDIUM' ? 'secondary' : 'default'
                              }>
                                {price[`priority_${countryKey}`]}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-right">{formatPercent(price[`inc_pct_${countryKey}`])}</TableCell>
                          </TableRow>
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
