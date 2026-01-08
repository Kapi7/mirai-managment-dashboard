import React, { useState, useEffect, useMemo } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { DollarSign, TrendingUp, Clock, Target, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, ArrowUpDown, ArrowUp, ArrowDown, Search, Filter, BarChart3 } from 'lucide-react';

const API_URL = import.meta.env.VITE_REPORT_API_URL ||
  (import.meta.env.DEV ? 'http://localhost:8080' : '/reports-api');

export default function Pricing() {
  const [activeTab, setActiveTab] = useState('items');
  const [loading, setLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState('');
  const [error, setError] = useState(null);

  // Items tab state
  const [items, setItems] = useState([]);
  const [selectedMarket, setSelectedMarket] = useState('all');
  const [markets, setMarkets] = useState([]);
  const [itemsPage, setItemsPage] = useState(0);
  const [itemsPageSize, setItemsPageSize] = useState(50);
  const [itemsSortColumn, setItemsSortColumn] = useState(null);
  const [itemsSortDirection, setItemsSortDirection] = useState('asc');
  const [selectedItems, setSelectedItems] = useState(new Set());

  // Price Updates tab state
  const [priceUpdates, setPriceUpdates] = useState([]);
  const [showPasteDialog, setShowPasteDialog] = useState(false);
  const [pasteText, setPasteText] = useState('');

  // Update Log tab state
  const [updateLog, setUpdateLog] = useState([]);

  // Target Prices tab state
  const [targetPrices, setTargetPrices] = useState([]);
  const [selectedCountry, setSelectedCountry] = useState('US');
  const [countries, setCountries] = useState(['US', 'UK', 'AU', 'CA']);
  const [targetPricesPage, setTargetPricesPage] = useState(0);
  const [targetPricesPageSize, setTargetPricesPageSize] = useState(50);
  const [targetPricesSortColumn, setTargetPricesSortColumn] = useState(null);
  const [targetPricesSortDirection, setTargetPricesSortDirection] = useState('asc');
  const [targetPricesPriorityFilter, setTargetPricesPriorityFilter] = useState('all');
  const [targetPricesSearchFilter, setTargetPricesSearchFilter] = useState('');
  const [selectedTargetPrices, setSelectedTargetPrices] = useState(new Set());

  // Competitor Analysis tab state
  const [competitorAnalysis, setCompetitorAnalysis] = useState(null);

  // Pre-fetch items on mount for faster initial load
  useEffect(() => {
    fetchMarkets();
    fetchCountries();
    // Pre-load items data since that's the default tab
    if (items.length === 0) {
      fetchItems();
    }
  }, []);

  // Track if price updates were loaded from backend (to avoid overwriting user edits)
  const [priceUpdatesLoadedFromBackend, setPriceUpdatesLoadedFromBackend] = useState(false);

  // Fetch data when tab changes
  useEffect(() => {
    switch (activeTab) {
      case 'items':
        fetchItems();
        break;
      case 'price-updates':
        // Only fetch from backend if we haven't loaded yet (prevents overwriting user-added items)
        if (!priceUpdatesLoadedFromBackend) {
          fetchPriceUpdates();
        }
        break;
      case 'update-log':
        fetchUpdateLog();
        break;
      case 'target-prices':
        fetchTargetPrices();
        break;
      case 'competitor-analysis':
        fetchCompetitorAnalysis();
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
    setLoadingMessage('Loading items...');
    setError(null);
    try {
      const url = selectedMarket === 'all'
        ? `${API_URL}/pricing/items`
        : `${API_URL}/pricing/items?market=${selectedMarket}`;

      const startTime = Date.now();
      const response = await fetch(url);
      const result = await response.json();
      const duration = ((Date.now() - startTime) / 1000).toFixed(1);

      console.log(`Items loaded in ${duration}s`);

      if (result.error) {
        setError(result.error);
      } else {
        setItems(result.data || []);
        setLoadingMessage('');
      }
    } catch (err) {
      setError(`Failed to fetch items: ${err.message}`);
      setLoadingMessage('');
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
        setPriceUpdatesLoadedFromBackend(true);
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
    setLoadingMessage('Calculating target prices...');
    setError(null);
    try {
      const startTime = Date.now();
      const response = await fetch(`${API_URL}/pricing/target-prices?country=${selectedCountry}`);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      const result = await response.json();
      const duration = ((Date.now() - startTime) / 1000).toFixed(1);

      console.log(`Target prices loaded in ${duration}s`);
      console.log('Target Prices API response:', result);
      console.log('Data length:', result.data?.length);

      if (result.error) {
        setError(result.error);
      } else {
        setTargetPrices(result.data || []);
        setLoadingMessage('');
        console.log('Set target prices state:', result.data?.length || 0);
      }
    } catch (err) {
      console.error('Target prices fetch error:', err);
      setError(`Failed to fetch target prices: ${err.message}`);
      setLoadingMessage('');
    } finally {
      setLoading(false);
    }
  };

  const fetchCompetitorAnalysis = async () => {
    setLoading(true);
    setError(null);
    try {
      // Calculate competitor analysis from target prices
      const countryKey = selectedCountry;
      const withCompetitors = targetPrices.filter(p =>
        p[`comp_avg_${countryKey}`] && p[`comp_avg_${countryKey}`] > 0
      );

      const overpriced = withCompetitors.filter(p => {
        const current = p[`current_${countryKey}`];
        const compAvg = p[`comp_avg_${countryKey}`];
        return current > compAvg * 1.15;
      });

      const underpriced = withCompetitors.filter(p => {
        const current = p[`current_${countryKey}`];
        const compAvg = p[`comp_avg_${countryKey}`];
        return current < compAvg * 0.85;
      });

      const competitive = withCompetitors.filter(p => {
        const current = p[`current_${countryKey}`];
        const compAvg = p[`comp_avg_${countryKey}`];
        return current >= compAvg * 0.85 && current <= compAvg * 1.15;
      });

      setCompetitorAnalysis({
        totalProducts: targetPrices.length,
        withCompetitorData: withCompetitors.length,
        overpriced: overpriced.sort((a, b) => {
          const aDiff = (a[`current_${countryKey}`] / a[`comp_avg_${countryKey}`]) - 1;
          const bDiff = (b[`current_${countryKey}`] / b[`comp_avg_${countryKey}`]) - 1;
          return bDiff - aDiff;
        }),
        underpriced: underpriced.sort((a, b) => {
          const aDiff = 1 - (a[`current_${countryKey}`] / a[`comp_avg_${countryKey}`]);
          const bDiff = 1 - (b[`current_${countryKey}`] / b[`comp_avg_${countryKey}`]);
          return bDiff - aDiff;
        }),
        competitive,
      });
    } catch (err) {
      setError(`Failed to analyze competitor data: ${err.message}`);
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

  // Sorting and pagination for Items tab
  const sortedAndPaginatedItems = useMemo(() => {
    let sorted = [...items];

    // Apply sorting
    if (itemsSortColumn) {
      sorted.sort((a, b) => {
        let aVal, bVal;

        // Special handling for margin
        if (itemsSortColumn === 'margin') {
          aVal = a.cogs > 0 ? ((a.retail_base - a.cogs) / a.cogs * 100) : 0;
          bVal = b.cogs > 0 ? ((b.retail_base - b.cogs) / b.cogs * 100) : 0;
        } else {
          aVal = a[itemsSortColumn];
          bVal = b[itemsSortColumn];
        }

        // Handle numeric values
        if (typeof aVal === 'number' && typeof bVal === 'number') {
          return itemsSortDirection === 'asc' ? aVal - bVal : bVal - aVal;
        }

        // Handle strings
        aVal = String(aVal || '').toLowerCase();
        bVal = String(bVal || '').toLowerCase();

        if (aVal < bVal) return itemsSortDirection === 'asc' ? -1 : 1;
        if (aVal > bVal) return itemsSortDirection === 'asc' ? 1 : -1;
        return 0;
      });
    }

    // Apply pagination
    const start = itemsPage * itemsPageSize;
    const end = start + itemsPageSize;
    return sorted.slice(start, end);
  }, [items, itemsSortColumn, itemsSortDirection, itemsPage, itemsPageSize]);

  const itemsTotalPages = Math.ceil(items.length / itemsPageSize);

  const handleItemsSort = (column) => {
    if (itemsSortColumn === column) {
      setItemsSortDirection(itemsSortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setItemsSortColumn(column);
      setItemsSortDirection('asc');
    }
    setItemsPage(0); // Reset to first page when sorting
  };

  const getSortIcon = (column) => {
    if (itemsSortColumn !== column) {
      return <ArrowUpDown className="h-4 w-4 ml-2 inline" />;
    }
    return itemsSortDirection === 'asc' ?
      <ArrowUp className="h-4 w-4 ml-2 inline" /> :
      <ArrowDown className="h-4 w-4 ml-2 inline" />;
  };

  // Sorting, filtering, and pagination for Target Prices tab
  const sortedFilteredAndPaginatedTargetPrices = useMemo(() => {
    let filtered = [...targetPrices];
    const countryKey = selectedCountry;

    // Apply priority filter
    if (targetPricesPriorityFilter !== 'all') {
      filtered = filtered.filter(item => item[`priority_${countryKey}`] === targetPricesPriorityFilter);
    }

    // Apply search filter
    if (targetPricesSearchFilter) {
      const search = targetPricesSearchFilter.toLowerCase();
      filtered = filtered.filter(item =>
        item.item.toLowerCase().includes(search) ||
        item.variant_id.toLowerCase().includes(search)
      );
    }

    // Apply sorting
    if (targetPricesSortColumn) {
      filtered.sort((a, b) => {
        let aVal, bVal;

        // Handle country-specific columns
        if (targetPricesSortColumn.includes('_')) {
          aVal = a[`${targetPricesSortColumn}_${countryKey}`];
          bVal = b[`${targetPricesSortColumn}_${countryKey}`];
        } else {
          aVal = a[targetPricesSortColumn];
          bVal = b[targetPricesSortColumn];
        }

        // Special handling for priority (HIGH > MEDIUM > LOW)
        if (targetPricesSortColumn === 'priority') {
          const priorityMap = { 'HIGH': 3, 'MEDIUM': 2, 'LOW': 1 };
          aVal = priorityMap[aVal] || 0;
          bVal = priorityMap[bVal] || 0;
          return targetPricesSortDirection === 'asc' ? aVal - bVal : bVal - aVal;
        }

        // Handle numeric values
        if (typeof aVal === 'number' && typeof bVal === 'number') {
          return targetPricesSortDirection === 'asc' ? aVal - bVal : bVal - aVal;
        }

        // Handle strings
        aVal = String(aVal || '').toLowerCase();
        bVal = String(bVal || '').toLowerCase();

        if (aVal < bVal) return targetPricesSortDirection === 'asc' ? -1 : 1;
        if (aVal > bVal) return targetPricesSortDirection === 'asc' ? 1 : -1;
        return 0;
      });
    }

    // Apply pagination
    const start = targetPricesPage * targetPricesPageSize;
    const end = start + targetPricesPageSize;
    return filtered.slice(start, end);
  }, [targetPrices, targetPricesSortColumn, targetPricesSortDirection, targetPricesPage, targetPricesPageSize, targetPricesPriorityFilter, targetPricesSearchFilter, selectedCountry]);

  const targetPricesTotalPages = Math.ceil(targetPrices.length / targetPricesPageSize);

  const handleTargetPricesSort = (column) => {
    if (targetPricesSortColumn === column) {
      setTargetPricesSortDirection(targetPricesSortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setTargetPricesSortColumn(column);
      setTargetPricesSortDirection('asc');
    }
    setTargetPricesPage(0); // Reset to first page when sorting
  };

  const getTargetPricesSortIcon = (column) => {
    if (targetPricesSortColumn !== column) {
      return <ArrowUpDown className="h-4 w-4 ml-2 inline" />;
    }
    return targetPricesSortDirection === 'asc' ?
      <ArrowUp className="h-4 w-4 ml-2 inline" /> :
      <ArrowDown className="h-4 w-4 ml-2 inline" />;
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
        <TabsList className="grid w-full grid-cols-5">
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
          <TabsTrigger value="competitor-analysis">
            <BarChart3 className="h-4 w-4 mr-2" />
            Competitors
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
                <div className="flex items-center gap-3">
                  {selectedItems.size > 0 && (
                    <>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          const selectedItemsData = items.filter(item => selectedItems.has(item.variant_id));
                          const variantIds = selectedItemsData.map(item => item.variant_id).join('\n');
                          navigator.clipboard.writeText(variantIds);
                        }}
                      >
                        📋 Copy {selectedItems.size} Variant IDs
                      </Button>
                      <Button
                        variant="default"
                        size="sm"
                        onClick={() => {
                          console.log('Add to Price Updates clicked (Items)');
                          console.log('Selected items:', selectedItems);
                          // Add selected items to price updates
                          const selectedItemsData = items.filter(item => selectedItems.has(item.variant_id));
                          console.log('Selected items data:', selectedItemsData);
                          const newUpdates = selectedItemsData.map(item => ({
                            variant_id: item.variant_id,
                            item: item.item,
                            current_price: item.retail_base,
                            current_compare_at: item.compare_at_base,
                            new_price: item.retail_base,
                            new_compare_at: null,
                            compare_at_policy: 'D',
                            new_cogs: null,
                            notes: ''
                          }));
                          console.log('New updates:', newUpdates);
                          setPriceUpdates([...priceUpdates, ...newUpdates]);
                          setSelectedItems(new Set()); // Clear selection
                          setActiveTab('price-updates'); // Switch to Price Updates tab
                        }}
                      >
                        Add {selectedItems.size} to Price Updates
                      </Button>
                    </>
                  )}
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
              </div>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="space-y-4">
                  {loadingMessage && (
                    <div className="space-y-2">
                      <div className="w-full bg-slate-200 rounded-full h-2.5">
                        <div className="bg-blue-600 h-2.5 rounded-full animate-pulse" style={{width: '60%'}}></div>
                      </div>
                      <p className="text-center text-sm text-slate-600">Loading from Shopify...</p>
                    </div>
                  )}
                  <div className="space-y-2">
                    {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
                  </div>
                </div>
              ) : items.length === 0 ? (
                <div className="text-center py-8 text-slate-500">No items found</div>
              ) : (
                <>
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="w-[50px]">
                            <Checkbox
                              checked={selectedItems.size === sortedAndPaginatedItems.length && sortedAndPaginatedItems.length > 0}
                              onCheckedChange={(checked) => {
                                if (checked) {
                                  setSelectedItems(new Set(sortedAndPaginatedItems.map(i => i.variant_id)));
                                } else {
                                  setSelectedItems(new Set());
                                }
                              }}
                            />
                          </TableHead>
                          <TableHead
                            className="cursor-pointer hover:bg-slate-50"
                            onClick={() => handleItemsSort('variant_id')}
                          >
                            Variant ID{getSortIcon('variant_id')}
                          </TableHead>
                          <TableHead
                            className="cursor-pointer hover:bg-slate-50"
                            onClick={() => handleItemsSort('item')}
                          >
                            Item{getSortIcon('item')}
                          </TableHead>
                          <TableHead
                            className="text-right cursor-pointer hover:bg-slate-50"
                            onClick={() => handleItemsSort('weight')}
                          >
                            Weight (g){getSortIcon('weight')}
                          </TableHead>
                          <TableHead
                            className="text-right cursor-pointer hover:bg-slate-50"
                            onClick={() => handleItemsSort('cogs')}
                          >
                            COGS{getSortIcon('cogs')}
                          </TableHead>
                          <TableHead
                            className="text-right cursor-pointer hover:bg-slate-50"
                            onClick={() => handleItemsSort('retail_base')}
                          >
                            Retail Base{getSortIcon('retail_base')}
                          </TableHead>
                          <TableHead
                            className="text-right cursor-pointer hover:bg-slate-50"
                            onClick={() => handleItemsSort('compare_at_base')}
                          >
                            Compare At Base{getSortIcon('compare_at_base')}
                          </TableHead>
                          <TableHead
                            className="text-right cursor-pointer hover:bg-slate-50"
                            onClick={() => handleItemsSort('margin')}
                          >
                            Margin{getSortIcon('margin')}
                          </TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {sortedAndPaginatedItems.map((item) => {
                          const isSelected = selectedItems.has(item.variant_id);
                          const margin = item.cogs > 0 ? ((item.retail_base - item.cogs) / item.cogs * 100) : 0;
                          return (
                            <TableRow key={item.variant_id} className={isSelected ? 'bg-indigo-50' : ''}>
                              <TableCell>
                                <Checkbox
                                  checked={isSelected}
                                  onCheckedChange={(checked) => {
                                    const newSet = new Set(selectedItems);
                                    if (checked) {
                                      newSet.add(item.variant_id);
                                    } else {
                                      newSet.delete(item.variant_id);
                                    }
                                    setSelectedItems(newSet);
                                  }}
                                />
                              </TableCell>
                              <TableCell className="font-mono text-sm">{item.variant_id}</TableCell>
                              <TableCell className="font-medium">{item.item}</TableCell>
                              <TableCell className="text-right">{(item.weight || 0).toFixed(0)}</TableCell>
                              <TableCell className="text-right">{formatCurrency(item.cogs)}</TableCell>
                              <TableCell className="text-right">{formatCurrency(item.retail_base)}</TableCell>
                              <TableCell className="text-right">{formatCurrency(item.compare_at_base)}</TableCell>
                              <TableCell className="text-right">
                                <span className={margin < 30 ? 'text-red-600 font-semibold' : margin < 50 ? 'text-yellow-600' : 'text-green-600'}>
                                  {margin.toFixed(1)}%
                                </span>
                              </TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  </div>

                  {/* Pagination Controls */}
                  <div className="flex items-center justify-between mt-4 pt-4 border-t">
                    <div className="flex items-center gap-3">
                      <div className="text-sm text-slate-600">
                        Showing {itemsPage * itemsPageSize + 1} to {Math.min((itemsPage + 1) * itemsPageSize, items.length)} of {items.length} items
                      </div>
                      <Select value={itemsPageSize.toString()} onValueChange={(val) => {
                        setItemsPageSize(parseInt(val));
                        setItemsPage(0);
                      }}>
                        <SelectTrigger className="h-8 w-[90px]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="50">50 / page</SelectItem>
                          <SelectItem value="100">100 / page</SelectItem>
                          <SelectItem value="200">200 / page</SelectItem>
                          <SelectItem value="500">500 / page</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setItemsPage(0)}
                        disabled={itemsPage === 0}
                      >
                        <ChevronsLeft className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setItemsPage(itemsPage - 1)}
                        disabled={itemsPage === 0}
                      >
                        <ChevronLeft className="h-4 w-4" />
                      </Button>
                      <span className="text-sm text-slate-600">
                        Page {itemsPage + 1} of {itemsTotalPages}
                      </span>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setItemsPage(itemsPage + 1)}
                        disabled={itemsPage >= itemsTotalPages - 1}
                      >
                        <ChevronRight className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setItemsPage(itemsTotalPages - 1)}
                        disabled={itemsPage >= itemsTotalPages - 1}
                      >
                        <ChevronsRight className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* PRICE UPDATES TAB */}
        <TabsContent value="price-updates">
          <Card>
            <CardHeader>
              <div className="flex flex-col gap-4">
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle>Price Updates Staging</CardTitle>
                    <CardDescription>Add items, set new prices, then execute updates</CardDescription>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        // Add manual row
                        setPriceUpdates([...priceUpdates, {
                          variant_id: '',
                          item: '',
                          current_price: 0,
                          current_compare_at: 0,
                          new_price: 0,
                          new_compare_at: null,
                          compare_at_policy: 'D',
                          new_cogs: null,
                          notes: ''
                        }]);
                      }}
                    >
                      + Add Row
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setShowPasteDialog(!showPasteDialog)}
                    >
                      📋 Paste Data
                    </Button>
                    <Button
                      variant="default"
                      disabled={priceUpdates.length === 0}
                      onClick={() => {
                        alert(`Would execute ${priceUpdates.length} price updates to Shopify`);
                        // TODO: Implement actual update execution
                      }}
                    >
                      Execute Updates ({priceUpdates.length})
                    </Button>
                  </div>
                </div>

                {/* Instructions */}
                <div className="bg-slate-50 p-4 rounded-lg text-sm text-slate-600">
                  <p className="font-semibold mb-2">How to use:</p>
                  <ul className="list-disc list-inside space-y-1">
                    <li>Select items from Items or Target Prices tabs, then click "Add to Price Updates"</li>
                    <li>Click "+ Add Row" to manually add items</li>
                    <li>Edit prices inline - Use policy to control compare_at pricing</li>
                    <li><strong>Policy A:</strong> No compare at, <strong>Policy B:</strong> GMC-compliant (compare_at = price), <strong>Manual:</strong> Set compare_at manually</li>
                    <li>Paste data from Excel/Sheets (variant_id, new_price format)</li>
                    <li>Click "Execute Updates" when ready to push base price changes to Shopify</li>
                  </ul>
                </div>

                {/* Paste Dialog */}
                {showPasteDialog && (
                  <div className="bg-white border border-slate-300 rounded-lg p-4">
                    <h3 className="font-semibold mb-2">Paste Data</h3>
                    <p className="text-sm text-slate-600 mb-3">
                      Paste variant IDs and new prices (tab or comma separated). Format: variant_id, new_price
                    </p>
                    <textarea
                      className="w-full h-32 p-3 border border-slate-300 rounded-lg font-mono text-sm mb-3"
                      placeholder="51750779093364	35.99
51750800228724	24.50
51750801146228	43.99"
                      value={pasteText}
                      onChange={(e) => setPasteText(e.target.value)}
                    />
                    <div className="flex gap-2">
                      <Button
                        variant="default"
                        size="sm"
                        onClick={() => {
                          // Parse pasted data
                          const lines = pasteText.split('\n').filter(line => line.trim());
                          const newUpdates = lines.map(line => {
                            const parts = line.split(/[\t,]/).map(p => p.trim());
                            const variant_id = parts[0] || '';
                            const new_price = parseFloat(parts[1]) || 0;
                            const new_cogs = parts[2] ? parseFloat(parts[2]) : null;

                            // Try to find item in items or targetPrices
                            const itemData = items.find(i => i.variant_id === variant_id) ||
                                           targetPrices.find(p => p.variant_id === variant_id);

                            return {
                              variant_id,
                              item: itemData?.item || '',
                              current_price: itemData?.retail_base || itemData?.[`current_US`] || 0,
                              current_compare_at: itemData?.compare_at_base || 0,
                              new_price,
                              new_compare_at: null,
                              compare_at_policy: 'D',
                              new_cogs,
                              notes: ''
                            };
                          });

                          setPriceUpdates([...priceUpdates, ...newUpdates]);
                          setPasteText('');
                          setShowPasteDialog(false);
                        }}
                      >
                        Add {pasteText.split('\n').filter(l => l.trim()).length} Items
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          setPasteText('');
                          setShowPasteDialog(false);
                        }}
                      >
                        Cancel
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            </CardHeader>
            <CardContent>
              {priceUpdates.length === 0 ? (
                <div className="text-center py-12 text-slate-500">
                  <p className="text-lg font-medium mb-2">No price updates staged</p>
                  <p className="text-sm">Select items from other tabs or click "+ Add Row" to begin</p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-[40px] text-center"></TableHead>
                        <TableHead className="text-center">Variant ID</TableHead>
                        <TableHead className="text-center">Item</TableHead>
                        <TableHead className="text-center">Current Price</TableHead>
                        <TableHead className="text-center">Current Compare At</TableHead>
                        <TableHead className="text-center">New Price</TableHead>
                        <TableHead className="text-center">New Compare At</TableHead>
                        <TableHead className="text-center">Compare At Policy</TableHead>
                        <TableHead className="text-center">New COGS</TableHead>
                        <TableHead className="text-center">Change %</TableHead>
                        <TableHead className="text-center">Notes</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {priceUpdates.map((update, idx) => {
                        const changePct = update.current_price > 0
                          ? ((update.new_price - update.current_price) / update.current_price) * 100
                          : 0;
                        return (
                          <TableRow key={idx}>
                            <TableCell className="text-center">
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-6 w-6 p-0 text-red-600 hover:text-red-700 hover:bg-red-50"
                                onClick={() => {
                                  setPriceUpdates(priceUpdates.filter((_, i) => i !== idx));
                                }}
                              >
                                ×
                              </Button>
                            </TableCell>
                            <TableCell className="text-center">
                              <Input
                                className="font-mono text-sm h-8 text-center"
                                value={update.variant_id}
                                onChange={(e) => {
                                  const newUpdates = [...priceUpdates];
                                  const enteredId = e.target.value;
                                  newUpdates[idx].variant_id = enteredId;

                                  // Auto-lookup item details when variant ID is entered
                                  if (enteredId.trim()) {
                                    const itemData = items.find(i => i.variant_id === enteredId) ||
                                                   targetPrices.find(p => p.variant_id === enteredId);

                                    if (itemData) {
                                      newUpdates[idx].item = itemData.item;
                                      newUpdates[idx].current_price = itemData.retail_base || itemData[`current_US`] || 0;
                                      newUpdates[idx].current_compare_at = itemData.compare_at_base || 0;
                                      // Set new_price to current if not already set
                                      if (newUpdates[idx].new_price === 0) {
                                        newUpdates[idx].new_price = newUpdates[idx].current_price;
                                      }
                                    }
                                  }

                                  setPriceUpdates(newUpdates);
                                }}
                                placeholder="Variant ID"
                              />
                            </TableCell>
                            <TableCell className="font-medium text-sm max-w-[200px] truncate text-center">{update.item || '-'}</TableCell>
                            <TableCell className="text-center text-sm">{formatCurrency(update.current_price)}</TableCell>
                            <TableCell className="text-center text-sm">{formatCurrency(update.current_compare_at || 0)}</TableCell>
                            <TableCell className="text-center">
                              <div className="flex justify-center">
                                <Input
                                  type="number"
                                  step="0.01"
                                  className="text-center h-8 w-[100px]"
                                  value={update.new_price}
                                  onChange={(e) => {
                                    const newUpdates = [...priceUpdates];
                                    newUpdates[idx].new_price = parseFloat(e.target.value) || 0;
                                    setPriceUpdates(newUpdates);
                                  }}
                                />
                              </div>
                            </TableCell>
                            <TableCell className="text-center">
                              <div className="flex justify-center">
                                {update.compare_at_policy === 'Manual' ? (
                                  <Input
                                    type="number"
                                    step="0.01"
                                    className="text-center h-8 w-[100px]"
                                    value={update.new_compare_at ?? ''}
                                    onChange={(e) => {
                                      const newUpdates = [...priceUpdates];
                                      newUpdates[idx].new_compare_at = e.target.value ? parseFloat(e.target.value) : null;
                                      setPriceUpdates(newUpdates);
                                    }}
                                    placeholder="Enter value"
                                  />
                                ) : (
                                  <span className="text-sm text-slate-500">Auto</span>
                                )}
                              </div>
                            </TableCell>
                            <TableCell className="text-center">
                              <div className="flex justify-center">
                                <Select
                                  value={update.compare_at_policy || 'D'}
                                  onValueChange={(value) => {
                                    const newUpdates = [...priceUpdates];
                                    // Map B/D to backend values (B stays B, D stays D)
                                    newUpdates[idx].compare_at_policy = value;
                                    // Clear new_compare_at if switching away from Manual
                                    if (value !== 'Manual') {
                                      newUpdates[idx].new_compare_at = null;
                                    }
                                    setPriceUpdates(newUpdates);
                                  }}
                                >
                                  <SelectTrigger className="h-8 w-[90px]">
                                    <SelectValue />
                                  </SelectTrigger>
                                  <SelectContent>
                                    <SelectItem value="A">A</SelectItem>
                                    <SelectItem value="B">B</SelectItem>
                                    <SelectItem value="Manual">Manual</SelectItem>
                                  </SelectContent>
                                </Select>
                              </div>
                            </TableCell>
                            <TableCell className="text-center">
                              <div className="flex justify-center">
                                <Input
                                  type="number"
                                  step="0.01"
                                  className="text-center h-8 w-[100px]"
                                  value={update.new_cogs ?? ''}
                                  onChange={(e) => {
                                    const newUpdates = [...priceUpdates];
                                    newUpdates[idx].new_cogs = e.target.value ? parseFloat(e.target.value) : null;
                                    setPriceUpdates(newUpdates);
                                  }}
                                  placeholder="Optional"
                                />
                              </div>
                            </TableCell>
                            <TableCell className="text-center">
                              <span className={changePct >= 0 ? 'text-green-600 font-semibold' : 'text-red-600 font-semibold'}>
                                {changePct >= 0 ? '+' : ''}{changePct.toFixed(2)}%
                              </span>
                            </TableCell>
                            <TableCell className="text-center">
                              <Input
                                className="h-8 text-sm text-center"
                                value={update.notes}
                                onChange={(e) => {
                                  const newUpdates = [...priceUpdates];
                                  newUpdates[idx].notes = e.target.value;
                                  setPriceUpdates(newUpdates);
                                }}
                                placeholder="Optional notes"
                              />
                            </TableCell>
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
              <div className="flex flex-col gap-4">
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

                {/* Filters */}
                <div className="flex items-center gap-4">
                  <div className="relative flex-1">
                    <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-slate-400" />
                    <Input
                      placeholder="Search by item name or variant ID..."
                      value={targetPricesSearchFilter}
                      onChange={(e) => setTargetPricesSearchFilter(e.target.value)}
                      className="pl-10"
                    />
                  </div>
                  <Select value={targetPricesPriorityFilter} onValueChange={setTargetPricesPriorityFilter}>
                    <SelectTrigger className="w-[180px]">
                      <Filter className="h-4 w-4 mr-2" />
                      <SelectValue placeholder="Priority" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Priorities</SelectItem>
                      <SelectItem value="HIGH">HIGH</SelectItem>
                      <SelectItem value="MEDIUM">MEDIUM</SelectItem>
                      <SelectItem value="LOW">LOW</SelectItem>
                    </SelectContent>
                  </Select>
                  {selectedTargetPrices.size > 0 && (
                    <>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          const selectedPricesData = targetPrices.filter(price => selectedTargetPrices.has(price.variant_id));
                          const variantIds = selectedPricesData.map(price => price.variant_id).join('\n');
                          navigator.clipboard.writeText(variantIds);
                        }}
                      >
                        📋 Copy {selectedTargetPrices.size} Variant IDs
                      </Button>
                      <Button
                        variant="default"
                        size="sm"
                        onClick={() => {
                          console.log('Add to Price Updates clicked (Target Prices)');
                          console.log('Selected target prices:', selectedTargetPrices);
                          // Add selected target prices to price updates
                          const countryKey = selectedCountry;
                          const selectedPricesData = targetPrices.filter(price => selectedTargetPrices.has(price.variant_id));
                          console.log('Selected prices data:', selectedPricesData);
                          const newUpdates = selectedPricesData.map(price => ({
                            variant_id: price.variant_id,
                            item: price.item,
                            current_price: price[`current_${countryKey}`],
                            current_compare_at: 0,
                            new_price: price[`final_suggested_${countryKey}`],
                            new_compare_at: null,
                            compare_at_policy: 'D',
                            new_cogs: null,
                            notes: `Priority: ${price[`priority_${countryKey}`]}, Loss: ${formatCurrency(price[`loss_amount_${countryKey}`])}`
                          }));
                          console.log('New updates:', newUpdates);
                          setPriceUpdates([...priceUpdates, ...newUpdates]);
                          setSelectedTargetPrices(new Set()); // Clear selection
                          setActiveTab('price-updates'); // Switch to Price Updates tab
                        }}
                      >
                        Add {selectedTargetPrices.size} to Price Updates
                      </Button>
                    </>
                  )}
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="space-y-4">
                  {loadingMessage && (
                    <div className="space-y-2">
                      <div className="w-full bg-slate-200 rounded-full h-2.5">
                        <div className="bg-blue-600 h-2.5 rounded-full animate-pulse" style={{width: '60%'}}></div>
                      </div>
                      <p className="text-center text-sm text-slate-600">Calculating target prices...</p>
                    </div>
                  )}
                  <div className="space-y-2">
                    {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
                  </div>
                </div>
              ) : targetPrices.length === 0 ? (
                <div className="text-center py-8 text-slate-500">No target prices available</div>
              ) : (
                <>
                  {/* Competitor Price Summary */}
                  {(() => {
                    const countryKey = selectedCountry;
                    const withCompData = targetPrices.filter(p =>
                      p[`comp_avg_${countryKey}`] && p[`comp_avg_${countryKey}`] > 0
                    );

                    if (withCompData.length === 0) return null;

                    const compLows = withCompData.map(p => p[`comp_low_${countryKey}`]).filter(v => v > 0);
                    const compAvgs = withCompData.map(p => p[`comp_avg_${countryKey}`]).filter(v => v > 0);
                    const compHighs = withCompData.map(p => p[`comp_high_${countryKey}`]).filter(v => v > 0);

                    const avgLow = compLows.length > 0 ? compLows.reduce((a, b) => a + b, 0) / compLows.length : 0;
                    const avgAvg = compAvgs.length > 0 ? compAvgs.reduce((a, b) => a + b, 0) / compAvgs.length : 0;
                    const avgHigh = compHighs.length > 0 ? compHighs.reduce((a, b) => a + b, 0) / compHighs.length : 0;

                    return (
                      <div className="mb-6 p-4 bg-blue-50 rounded-lg">
                        <h3 className="text-sm font-semibold text-blue-900 mb-3">Competitor Price Summary ({withCompData.length} products)</h3>
                        <div className="grid grid-cols-3 gap-4">
                          <div>
                            <p className="text-xs text-slate-600 mb-1">Average Low Price</p>
                            <p className="text-2xl font-bold text-blue-600">{formatCurrency(avgLow)}</p>
                          </div>
                          <div>
                            <p className="text-xs text-slate-600 mb-1">Average Mid Price</p>
                            <p className="text-2xl font-bold text-blue-700">{formatCurrency(avgAvg)}</p>
                          </div>
                          <div>
                            <p className="text-xs text-slate-600 mb-1">Average High Price</p>
                            <p className="text-2xl font-bold text-blue-800">{formatCurrency(avgHigh)}</p>
                          </div>
                        </div>
                      </div>
                    );
                  })()}


                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="w-[50px]">
                            <Checkbox
                              checked={selectedTargetPrices.size === sortedFilteredAndPaginatedTargetPrices.length && sortedFilteredAndPaginatedTargetPrices.length > 0}
                              onCheckedChange={(checked) => {
                                if (checked) {
                                  setSelectedTargetPrices(new Set(sortedFilteredAndPaginatedTargetPrices.map(p => p.variant_id)));
                                } else {
                                  setSelectedTargetPrices(new Set());
                                }
                              }}
                            />
                          </TableHead>
                          <TableHead
                            className="cursor-pointer hover:bg-slate-50"
                            onClick={() => handleTargetPricesSort('variant_id')}
                          >
                            Variant ID{getTargetPricesSortIcon('variant_id')}
                          </TableHead>
                          <TableHead
                            className="cursor-pointer hover:bg-slate-50"
                            onClick={() => handleTargetPricesSort('item')}
                          >
                            Item{getTargetPricesSortIcon('item')}
                          </TableHead>
                          <TableHead
                            className="text-right cursor-pointer hover:bg-slate-50"
                            onClick={() => handleTargetPricesSort('weight_g')}
                          >
                            Weight{getTargetPricesSortIcon('weight_g')}
                          </TableHead>
                          <TableHead
                            className="text-right cursor-pointer hover:bg-slate-50"
                            onClick={() => handleTargetPricesSort('cogs')}
                          >
                            COGS{getTargetPricesSortIcon('cogs')}
                          </TableHead>
                          <TableHead
                            className="text-right cursor-pointer hover:bg-slate-50"
                            onClick={() => handleTargetPricesSort('current')}
                          >
                            Current{getTargetPricesSortIcon('current')}
                          </TableHead>
                          <TableHead
                            className="text-right cursor-pointer hover:bg-slate-50"
                            onClick={() => handleTargetPricesSort('ship')}
                          >
                            Ship{getTargetPricesSortIcon('ship')}
                          </TableHead>
                          <TableHead
                            className="text-right cursor-pointer hover:bg-slate-50"
                            onClick={() => handleTargetPricesSort('breakeven')}
                          >
                            Breakeven{getTargetPricesSortIcon('breakeven')}
                          </TableHead>
                          <TableHead
                            className="text-right cursor-pointer hover:bg-slate-50"
                            onClick={() => handleTargetPricesSort('target')}
                          >
                            Target{getTargetPricesSortIcon('target')}
                          </TableHead>
                          <TableHead
                            className="text-right cursor-pointer hover:bg-slate-50"
                            onClick={() => handleTargetPricesSort('suggested')}
                          >
                            Suggested{getTargetPricesSortIcon('suggested')}
                          </TableHead>
                          <TableHead
                            className="text-right cursor-pointer hover:bg-slate-50"
                            onClick={() => handleTargetPricesSort('final_suggested')}
                          >
                            Final{getTargetPricesSortIcon('final_suggested')}
                          </TableHead>
                          <TableHead
                            className="text-right cursor-pointer hover:bg-slate-50"
                            onClick={() => handleTargetPricesSort('comp_low')}
                          >
                            Comp Low{getTargetPricesSortIcon('comp_low')}
                          </TableHead>
                          <TableHead
                            className="text-right cursor-pointer hover:bg-slate-50"
                            onClick={() => handleTargetPricesSort('comp_avg')}
                          >
                            Comp Avg{getTargetPricesSortIcon('comp_avg')}
                          </TableHead>
                          <TableHead
                            className="text-right cursor-pointer hover:bg-slate-50"
                            onClick={() => handleTargetPricesSort('comp_high')}
                          >
                            Comp High{getTargetPricesSortIcon('comp_high')}
                          </TableHead>
                          <TableHead
                            className="text-right cursor-pointer hover:bg-slate-50"
                            onClick={() => handleTargetPricesSort('loss_amount')}
                          >
                            Loss ${getTargetPricesSortIcon('loss_amount')}
                          </TableHead>
                          <TableHead
                            className="cursor-pointer hover:bg-slate-50"
                            onClick={() => handleTargetPricesSort('priority')}
                          >
                            Priority{getTargetPricesSortIcon('priority')}
                          </TableHead>
                          <TableHead
                            className="text-right cursor-pointer hover:bg-slate-50"
                            onClick={() => handleTargetPricesSort('inc_pct')}
                          >
                            Inc %{getTargetPricesSortIcon('inc_pct')}
                          </TableHead>
                        </TableRow>
                      </TableHeader>
                    <TableBody>
                      {sortedFilteredAndPaginatedTargetPrices.map((price) => {
                        const countryKey = selectedCountry;
                        const isSelected = selectedTargetPrices.has(price.variant_id);
                        return (
                          <TableRow key={price.variant_id} className={isSelected ? 'bg-indigo-50' : ''}>
                            <TableCell>
                              <Checkbox
                                checked={isSelected}
                                onCheckedChange={(checked) => {
                                  const newSet = new Set(selectedTargetPrices);
                                  if (checked) {
                                    newSet.add(price.variant_id);
                                  } else {
                                    newSet.delete(price.variant_id);
                                  }
                                  setSelectedTargetPrices(newSet);
                                }}
                              />
                            </TableCell>
                            <TableCell className="font-mono text-sm">{price.variant_id}</TableCell>
                            <TableCell className="font-medium max-w-[250px] truncate">{price.item}</TableCell>
                            <TableCell className="text-right">{(price.weight_g || 0).toFixed(0)}</TableCell>
                            <TableCell className="text-right">{formatCurrency(price.cogs)}</TableCell>
                            <TableCell className="text-right">{formatCurrency(price[`current_${countryKey}`])}</TableCell>
                            <TableCell className="text-right">{formatCurrency(price[`ship_${countryKey}`])}</TableCell>
                            <TableCell className="text-right">{formatCurrency(price[`breakeven_${countryKey}`])}</TableCell>
                            <TableCell className="text-right">{formatCurrency(price[`target_${countryKey}`])}</TableCell>
                            <TableCell className="text-right">{formatCurrency(price[`suggested_${countryKey}`])}</TableCell>
                            <TableCell className="text-right font-semibold">{formatCurrency(price[`final_suggested_${countryKey}`])}</TableCell>
                            <TableCell className="text-right text-slate-500">{formatCurrency(price[`comp_low_${countryKey}`] || 0)}</TableCell>
                            <TableCell className="text-right text-slate-500">{formatCurrency(price[`comp_avg_${countryKey}`] || 0)}</TableCell>
                            <TableCell className="text-right text-slate-500">{formatCurrency(price[`comp_high_${countryKey}`] || 0)}</TableCell>
                            <TableCell className="text-right">
                              <span className={(price[`loss_amount_${countryKey}`] || 0) < 0 ? 'text-red-600 font-semibold' : 'text-green-600'}>
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

                {/* Pagination Controls */}
                <div className="flex items-center justify-between mt-4 pt-4 border-t">
                  <div className="flex items-center gap-3">
                    <div className="text-sm text-slate-600">
                      Showing {targetPricesPage * targetPricesPageSize + 1} to {Math.min((targetPricesPage + 1) * targetPricesPageSize, targetPrices.length)} of {targetPrices.length} items
                      {(targetPricesPriorityFilter !== 'all' || targetPricesSearchFilter) && ` (filtered)`}
                    </div>
                    <Select value={targetPricesPageSize.toString()} onValueChange={(val) => {
                      setTargetPricesPageSize(parseInt(val));
                      setTargetPricesPage(0);
                    }}>
                      <SelectTrigger className="h-8 w-[90px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="50">50 / page</SelectItem>
                        <SelectItem value="100">100 / page</SelectItem>
                        <SelectItem value="200">200 / page</SelectItem>
                        <SelectItem value="500">500 / page</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setTargetPricesPage(0)}
                      disabled={targetPricesPage === 0}
                    >
                      <ChevronsLeft className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setTargetPricesPage(targetPricesPage - 1)}
                      disabled={targetPricesPage === 0}
                    >
                      <ChevronLeft className="h-4 w-4" />
                    </Button>
                    <span className="text-sm text-slate-600">
                      Page {targetPricesPage + 1} of {targetPricesTotalPages || 1}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setTargetPricesPage(targetPricesPage + 1)}
                      disabled={targetPricesPage >= targetPricesTotalPages - 1}
                    >
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setTargetPricesPage(targetPricesTotalPages - 1)}
                      disabled={targetPricesPage >= targetPricesTotalPages - 1}
                    >
                      <ChevronsRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* COMPETITOR ANALYSIS TAB */}
        <TabsContent value="competitor-analysis">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Competitor Price Analysis</CardTitle>
                  <CardDescription>Smart comparison of your prices vs. competitors</CardDescription>
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
              ) : !competitorAnalysis ? (
                <div className="text-center py-8 text-slate-500">
                  <p>Loading competitor analysis...</p>
                  <p className="text-sm mt-2">Switch to Target Prices tab first to load data</p>
                </div>
              ) : (
                <div className="space-y-6">
                  {/* Summary Cards */}
                  <div className="grid grid-cols-4 gap-4">
                    <Card>
                      <CardContent className="pt-6">
                        <div className="text-2xl font-bold">{competitorAnalysis.totalProducts}</div>
                        <p className="text-xs text-slate-500 mt-1">Total Products</p>
                      </CardContent>
                    </Card>
                    <Card>
                      <CardContent className="pt-6">
                        <div className="text-2xl font-bold text-blue-600">{competitorAnalysis.withCompetitorData}</div>
                        <p className="text-xs text-slate-500 mt-1">With Competitor Data</p>
                      </CardContent>
                    </Card>
                    <Card>
                      <CardContent className="pt-6">
                        <div className="text-2xl font-bold text-red-600">{competitorAnalysis.overpriced.length}</div>
                        <p className="text-xs text-slate-500 mt-1">Overpriced (&gt;15%)</p>
                      </CardContent>
                    </Card>
                    <Card>
                      <CardContent className="pt-6">
                        <div className="text-2xl font-bold text-green-600">{competitorAnalysis.underpriced.length}</div>
                        <p className="text-xs text-slate-500 mt-1">Underpriced (&lt;15%)</p>
                      </CardContent>
                    </Card>
                  </div>

                  {/* Overpriced Products */}
                  {competitorAnalysis.overpriced.length > 0 && (
                    <div>
                      <h3 className="text-lg font-semibold mb-3 text-red-700">🚨 Overpriced Products ({competitorAnalysis.overpriced.length})</h3>
                      <p className="text-sm text-slate-600 mb-4">Your prices are &gt;15% higher than competitor average - you may be losing sales</p>
                      <div className="overflow-x-auto">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>Item</TableHead>
                              <TableHead className="text-right">Your Price</TableHead>
                              <TableHead className="text-right">Comp Low</TableHead>
                              <TableHead className="text-right">Comp Avg</TableHead>
                              <TableHead className="text-right">Comp High</TableHead>
                              <TableHead className="text-right">vs Average</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {competitorAnalysis.overpriced.slice(0, 10).map((product) => {
                              const countryKey = selectedCountry;
                              const current = product[`current_${countryKey}`];
                              const compAvg = product[`comp_avg_${countryKey}`];
                              const compLow = product[`comp_low_${countryKey}`];
                              const compHigh = product[`comp_high_${countryKey}`];
                              const diffPct = ((current - compAvg) / compAvg) * 100;
                              return (
                                <TableRow key={product.variant_id}>
                                  <TableCell className="font-medium max-w-[300px] truncate">{product.item}</TableCell>
                                  <TableCell className="text-right font-semibold">{formatCurrency(current)}</TableCell>
                                  <TableCell className="text-right text-slate-600">{formatCurrency(compLow)}</TableCell>
                                  <TableCell className="text-right text-slate-600">{formatCurrency(compAvg)}</TableCell>
                                  <TableCell className="text-right text-slate-600">{formatCurrency(compHigh)}</TableCell>
                                  <TableCell className="text-right">
                                    <span className="text-red-600 font-semibold">+{diffPct.toFixed(1)}%</span>
                                  </TableCell>
                                </TableRow>
                              );
                            })}
                          </TableBody>
                        </Table>
                      </div>
                      {competitorAnalysis.overpriced.length > 10 && (
                        <p className="text-sm text-slate-500 mt-2">... and {competitorAnalysis.overpriced.length - 10} more</p>
                      )}
                    </div>
                  )}

                  {/* Underpriced Products */}
                  {competitorAnalysis.underpriced.length > 0 && (
                    <div>
                      <h3 className="text-lg font-semibold mb-3 text-green-700">💰 Underpriced Products ({competitorAnalysis.underpriced.length})</h3>
                      <p className="text-sm text-slate-600 mb-4">Your prices are &lt;15% lower than competitor average - opportunity to raise prices</p>
                      <div className="overflow-x-auto">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>Item</TableHead>
                              <TableHead className="text-right">Your Price</TableHead>
                              <TableHead className="text-right">Comp Low</TableHead>
                              <TableHead className="text-right">Comp Avg</TableHead>
                              <TableHead className="text-right">Comp High</TableHead>
                              <TableHead className="text-right">vs Average</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {competitorAnalysis.underpriced.slice(0, 10).map((product) => {
                              const countryKey = selectedCountry;
                              const current = product[`current_${countryKey}`];
                              const compAvg = product[`comp_avg_${countryKey}`];
                              const compLow = product[`comp_low_${countryKey}`];
                              const compHigh = product[`comp_high_${countryKey}`];
                              const diffPct = ((current - compAvg) / compAvg) * 100;
                              return (
                                <TableRow key={product.variant_id}>
                                  <TableCell className="font-medium max-w-[300px] truncate">{product.item}</TableCell>
                                  <TableCell className="text-right font-semibold">{formatCurrency(current)}</TableCell>
                                  <TableCell className="text-right text-slate-600">{formatCurrency(compLow)}</TableCell>
                                  <TableCell className="text-right text-slate-600">{formatCurrency(compAvg)}</TableCell>
                                  <TableCell className="text-right text-slate-600">{formatCurrency(compHigh)}</TableCell>
                                  <TableCell className="text-right">
                                    <span className="text-green-600 font-semibold">{diffPct.toFixed(1)}%</span>
                                  </TableCell>
                                </TableRow>
                              );
                            })}
                          </TableBody>
                        </Table>
                      </div>
                      {competitorAnalysis.underpriced.length > 10 && (
                        <p className="text-sm text-slate-500 mt-2">... and {competitorAnalysis.underpriced.length - 10} more</p>
                      )}
                    </div>
                  )}

                  {/* Competitive Products */}
                  {competitorAnalysis.competitive.length > 0 && (
                    <div>
                      <h3 className="text-lg font-semibold mb-3 text-blue-700">✅ Competitively Priced ({competitorAnalysis.competitive.length})</h3>
                      <p className="text-sm text-slate-600 mb-2">Your prices are within ±15% of competitor average - well positioned</p>
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
