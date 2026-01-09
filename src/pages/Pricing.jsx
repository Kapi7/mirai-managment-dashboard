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
import { DollarSign, TrendingUp, Clock, Target, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, ArrowUpDown, ArrowUp, ArrowDown, Search, Filter, BarChart3, Package } from 'lucide-react';

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
  const [itemsSearchFilter, setItemsSearchFilter] = useState('');

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
  const [orderCounts, setOrderCounts] = useState({}); // variant_id -> order count
  const [loadingOrderCounts, setLoadingOrderCounts] = useState(false);

  // Competitor Analysis tab state
  const [competitorAnalysis, setCompetitorAnalysis] = useState(null);
  const [variantIdsToCheck, setVariantIdsToCheck] = useState('');
  const [scanHistory, setScanHistory] = useState([]);
  const [scanHistorySortColumn, setScanHistorySortColumn] = useState('timestamp');
  const [scanHistorySortDirection, setScanHistorySortDirection] = useState('desc');
  const [backgroundScan, setBackgroundScan] = useState(null); // { taskId, status, progress, total, currentItem }
  const [backgroundUpdate, setBackgroundUpdate] = useState(null); // { taskId, status, progress, total, currentItem }
  const [expandedCompetitorSections, setExpandedCompetitorSections] = useState({}); // { overpriced: false, underpriced: false, competitive: false }

  // Product Management tab state
  const [productManagementActions, setProductManagementActions] = useState([]);
  const [productPasteInput, setProductPasteInput] = useState('');

  // Korealy Reconciliation tab state
  const [korealyReconciliation, setKorealyReconciliation] = useState([]);
  const [korealyStats, setKorealyStats] = useState({});
  const [korealySelectedRows, setKorealySelectedRows] = useState(new Set());
  const [korealyStatusFilter, setKorealyStatusFilter] = useState('all');
  const [currentScanTask, setCurrentScanTask] = useState(null);
  const [scanProgress, setScanProgress] = useState(null);

  // Display settings
  const [expandProductNames, setExpandProductNames] = useState(false);

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
        fetchScanHistory();
        break;
      case 'korealy-reconciliation':
        fetchKorealyReconciliation();
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

  const fetchKorealyReconciliation = async () => {
    setLoading(true);
    setLoadingMessage('Running Korealy reconciliation...');
    setError(null);
    try {
      const response = await fetch(`${API_URL}/pricing/korealy-reconciliation`);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      const result = await response.json();

      if (result.success) {
        setKorealyReconciliation(result.results || []);
        setKorealyStats(result.stats || {});
        setLoadingMessage('');
      } else {
        setError(result.message || 'Failed to run Korealy reconciliation');
      }
    } catch (err) {
      console.error('Korealy reconciliation error:', err);
      setError(`Failed to run Korealy reconciliation: ${err.message}`);
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
        return current > compAvg * 1.35; // 35% above competitor average
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

  const fetchScanHistory = async () => {
    try {
      const response = await fetch(`${API_URL}/pricing/scan-history?limit=200`);
      const result = await response.json();
      if (result.data) {
        setScanHistory(result.data);
      }
    } catch (err) {
      console.error('Error fetching scan history:', err);
    }
  };

  // Sort scan history
  const sortedScanHistory = useMemo(() => {
    if (!scanHistory.length) return [];
    const sorted = [...scanHistory].sort((a, b) => {
      let aVal = a[scanHistorySortColumn];
      let bVal = b[scanHistorySortColumn];
      if (scanHistorySortColumn === 'timestamp') {
        aVal = new Date(aVal || 0).getTime();
        bVal = new Date(bVal || 0).getTime();
      } else if (typeof aVal === 'number' && typeof bVal === 'number') {
        // numeric compare
      } else {
        aVal = String(aVal || '').toLowerCase();
        bVal = String(bVal || '').toLowerCase();
      }
      if (aVal < bVal) return scanHistorySortDirection === 'asc' ? -1 : 1;
      if (aVal > bVal) return scanHistorySortDirection === 'asc' ? 1 : -1;
      return 0;
    });
    return sorted;
  }, [scanHistory, scanHistorySortColumn, scanHistorySortDirection]);

  const handleScanHistorySort = (column) => {
    if (scanHistorySortColumn === column) {
      setScanHistorySortDirection(scanHistorySortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setScanHistorySortColumn(column);
      setScanHistorySortDirection('desc');
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

  // Sorting, filtering, and pagination for Items tab
  const sortedFilteredAndPaginatedItems = useMemo(() => {
    let filtered = [...items];

    // Apply search filter
    if (itemsSearchFilter) {
      const search = itemsSearchFilter.toLowerCase();
      filtered = filtered.filter(item =>
        item.item.toLowerCase().includes(search) ||
        item.variant_id.toLowerCase().includes(search)
      );
    }

    // Apply sorting
    if (itemsSortColumn) {
      filtered.sort((a, b) => {
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
    return filtered.slice(start, end);
  }, [items, itemsSortColumn, itemsSortDirection, itemsPage, itemsPageSize, itemsSearchFilter]);

  const itemsTotalFiltered = useMemo(() => {
    if (!itemsSearchFilter) return items.length;
    const search = itemsSearchFilter.toLowerCase();
    return items.filter(item =>
      item.item.toLowerCase().includes(search) ||
      item.variant_id.toLowerCase().includes(search)
    ).length;
  }, [items, itemsSearchFilter]);

  const itemsTotalPages = Math.ceil(itemsTotalFiltered / itemsPageSize);

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
        if (targetPricesSortColumn === 'priority' || targetPricesSortColumn.startsWith('priority_')) {
          const priorityMap = { 'HIGH': 3, 'MEDIUM': 2, 'LOW': 1 };
          // aVal and bVal are already set above with country key
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
        <TabsList className="grid w-full grid-cols-7">
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
          <TabsTrigger value="korealy-reconciliation">
            <Filter className="h-4 w-4 mr-2" />
            Korealy
          </TabsTrigger>
          {/* Products tab hidden per user request */}
          {false && (
            <TabsTrigger value="product-management">
              <Package className="h-4 w-4 mr-2" />
              Products
            </TabsTrigger>
          )}
        </TabsList>

        {/* GLOBAL PROGRESS INDICATOR - Always visible when background task is running */}
        {(backgroundScan || backgroundUpdate) && (
          <div className="mt-4 p-4 bg-gradient-to-r from-blue-50 to-purple-50 border border-blue-200 rounded-lg shadow-sm">
            <div className="flex items-center gap-4">
              <div className="flex-shrink-0">
                <div className="animate-spin h-6 w-6 border-2 border-blue-500 border-t-transparent rounded-full"></div>
              </div>
              <div className="flex-1">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-semibold text-blue-900">
                    {backgroundScan ? '🔍 Scanning Competitor Prices' : '💰 Updating Prices'}
                  </span>
                  <span className="text-sm font-bold text-blue-700">
                    {backgroundScan ? `${backgroundScan.progress} / ${backgroundScan.total}` : `${backgroundUpdate.progress} / ${backgroundUpdate.total}`}
                  </span>
                </div>
                <div className="w-full bg-blue-200 rounded-full h-3">
                  <div
                    className="bg-gradient-to-r from-blue-500 to-purple-500 h-3 rounded-full transition-all duration-500 ease-out"
                    style={{
                      width: `${(() => {
                        const task = backgroundScan || backgroundUpdate;
                        return task.total > 0 ? (task.progress / task.total) * 100 : 0;
                      })()}%`
                    }}
                  ></div>
                </div>
                <div className="flex items-center justify-between mt-1">
                  <p className="text-xs text-blue-700 truncate max-w-md">
                    {backgroundScan?.currentItem || backgroundUpdate?.currentItem || 'Processing...'}
                  </p>
                  <span className="text-xs text-blue-600 font-medium">
                    {(() => {
                      const task = backgroundScan || backgroundUpdate;
                      if (task.status === 'completed') return '✅ Complete!';
                      if (task.status === 'failed') return '❌ Failed';
                      if (task.total > 0) {
                        const pct = ((task.progress / task.total) * 100).toFixed(0);
                        return `${pct}% complete`;
                      }
                      return 'Starting...';
                    })()}
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ITEMS TAB */}
        <TabsContent value="items">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div className="flex-1">
                  <CardTitle>Product Items</CardTitle>
                  <CardDescription>View product inventory with pricing</CardDescription>
                  <div className="mt-2">
                    <div className="relative">
                      <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-slate-400" />
                      <Input
                        placeholder="Search by item name or variant ID..."
                        value={itemsSearchFilter}
                        onChange={(e) => {
                          setItemsSearchFilter(e.target.value);
                          setItemsPage(0); // Reset to first page on search
                        }}
                        className="pl-10 h-9"
                      />
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-3 pt-8">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setExpandProductNames(!expandProductNames)}
                    title={expandProductNames ? "Compact view" : "Expand product names"}
                  >
                    {expandProductNames ? "Compact" : "Expand"}
                  </Button>
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
                          const newUpdates = selectedItemsData.map(item => {
                            // Try to find suggested price and breakeven from target prices
                            const targetPrice = targetPrices.find(p => p.variant_id === item.variant_id);
                            return {
                              variant_id: item.variant_id,
                              item: item.item,
                              current_price: item.retail_base,
                              current_compare_at: item.compare_at_base,
                              new_price: item.retail_base,
                              new_compare_at: null,
                              compare_at_policy: 'D',
                              new_cogs: null,
                              notes: '',
                              suggested_price: targetPrice ? targetPrice[`final_suggested_${selectedCountry}`] : null,
                              breakeven_price: targetPrice ? targetPrice[`breakeven_${selectedCountry}`] : null
                            };
                          });
                          console.log('New updates:', newUpdates);
                          setPriceUpdates([...priceUpdates, ...newUpdates]);
                          setPriceUpdatesLoadedFromBackend(true); // Mark as loaded to prevent fetch overwrite
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
                              checked={selectedItems.size === sortedFilteredAndPaginatedItems.length && sortedFilteredAndPaginatedItems.length > 0}
                              onCheckedChange={(checked) => {
                                if (checked) {
                                  setSelectedItems(new Set(sortedFilteredAndPaginatedItems.map(i => i.variant_id)));
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
                        {sortedFilteredAndPaginatedItems.map((item) => {
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
                        Showing {itemsPage * itemsPageSize + 1} to {Math.min((itemsPage + 1) * itemsPageSize, itemsTotalFiltered)} of {itemsTotalFiltered} items
                        {itemsSearchFilter && ` (filtered from ${items.length})`}
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
                          notes: '',
                          suggested_price: null,
                          breakeven_price: null
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
                      variant="outline"
                      size="sm"
                      disabled={priceUpdates.length === 0}
                      onClick={() => {
                        // Apply suggested prices to all items that have them
                        const newUpdates = priceUpdates.map(update => {
                          if (update.suggested_price && update.suggested_price > 0) {
                            return { ...update, new_price: update.suggested_price };
                          }
                          return update;
                        });
                        setPriceUpdates(newUpdates);
                      }}
                      title="Set all prices to suggested prices"
                    >
                      📊 Apply Suggested
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={priceUpdates.length === 0}
                      onClick={() => {
                        // Apply breakeven prices to all items that have them
                        const newUpdates = priceUpdates.map(update => {
                          if (update.breakeven_price && update.breakeven_price > 0) {
                            return { ...update, new_price: update.breakeven_price };
                          }
                          return update;
                        });
                        setPriceUpdates(newUpdates);
                      }}
                      title="Set all prices to breakeven prices"
                    >
                      ⚖️ Apply Breakeven
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={priceUpdates.length === 0}
                      onClick={() => {
                        // Apply mid-point between breakeven and suggested
                        const newUpdates = priceUpdates.map(update => {
                          if (update.breakeven_price && update.suggested_price &&
                              update.breakeven_price > 0 && update.suggested_price > 0) {
                            const midPrice = (update.breakeven_price + update.suggested_price) / 2;
                            return { ...update, new_price: parseFloat(midPrice.toFixed(2)) };
                          }
                          return update;
                        });
                        setPriceUpdates(newUpdates);
                      }}
                      title="Set all prices to mid-point between breakeven and suggested"
                    >
                      🎯 Apply Mid-Point
                    </Button>
                    <Button
                      variant="default"
                      disabled={priceUpdates.length === 0}
                      onClick={async () => {
                        if (!confirm(`Execute ${priceUpdates.length} price updates to Shopify?`)) {
                          return;
                        }

                        try {
                          const response = await fetch(`${API_URL}/pricing/execute-updates`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ updates: priceUpdates })
                          });

                          if (!response.ok) {
                            const errorText = await response.text();
                            throw new Error(`HTTP ${response.status}: ${errorText}`);
                          }

                          const result = await response.json();

                          // Check if this is a background task
                          if (result.background && result.task_id) {
                            setBackgroundUpdate({
                              taskId: result.task_id,
                              status: 'running',
                              progress: 0,
                              total: priceUpdates.length,
                              currentItem: 'Starting...'
                            });

                            // Poll for status
                            const pollInterval = setInterval(async () => {
                              try {
                                const statusResponse = await fetch(`${API_URL}/pricing/update-status/${result.task_id}`);
                                const status = await statusResponse.json();

                                setBackgroundUpdate({
                                  taskId: result.task_id,
                                  status: status.status,
                                  progress: status.progress,
                                  total: status.total,
                                  currentItem: status.current_item || ''
                                });

                                if (status.status === 'completed' || status.status === 'failed') {
                                  clearInterval(pollInterval);

                                  if (status.status === 'completed') {
                                    alert(`✅ Success!\n\nUpdated: ${status.updated_count}\nFailed: ${status.failed_count}\n\n${status.message}`);
                                    setPriceUpdates([]);
                                    setPriceUpdatesLoadedFromBackend(false);
                                    setActiveTab('update-log');
                                    fetchUpdateLog();
                                  } else {
                                    alert(`❌ Error: ${status.error || 'Unknown error'}`);
                                  }

                                  setTimeout(() => setBackgroundUpdate(null), 3000);
                                }
                              } catch (pollErr) {
                                console.error('Poll error:', pollErr);
                              }
                            }, 1500);
                          } else if (result.success) {
                            // Synchronous result
                            alert(`✅ Success!\n\nUpdated: ${result.updated_count}\nFailed: ${result.failed_count}\n\n${result.message}`);
                            setPriceUpdates([]);
                            setPriceUpdatesLoadedFromBackend(false);
                            setActiveTab('update-log');
                            fetchUpdateLog();
                          } else {
                            alert(`❌ Error: ${result.message || 'Unknown error'}`);
                          }
                        } catch (err) {
                          console.error('Execute updates error:', err);
                          alert(`Failed to execute updates: ${err.message}`);
                        }
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
                    <li><strong>Policy B:</strong> GMC-compliant (compare_at = price), <strong>Policy D:</strong> Keep discount %, <strong>Manual:</strong> Set compare_at manually</li>
                    <li><strong>🧠 Smart Pricing:</strong> Suggested & Breakeven use dynamic CPA (12% of retail, $8-$25) + Smart competitor analysis (trusted sellers, outlier-filtered)</li>
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
                        <TableHead className="text-center">Current</TableHead>
                        <TableHead className="text-center">Breakeven</TableHead>
                        <TableHead className="text-center">Suggested</TableHead>
                        <TableHead className="text-center">New Price</TableHead>
                        <TableHead className="text-center">Smart Update</TableHead>
                        <TableHead className="text-center">Compare At</TableHead>
                        <TableHead className="text-center">Policy</TableHead>
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
                                    const itemData = items.find(i => i.variant_id === enteredId);
                                    const targetPrice = targetPrices.find(p => p.variant_id === enteredId);

                                    if (itemData || targetPrice) {
                                      newUpdates[idx].item = (itemData?.item || targetPrice?.item || '');
                                      newUpdates[idx].current_price = itemData?.retail_base || targetPrice?.[`current_${selectedCountry}`] || 0;
                                      newUpdates[idx].current_compare_at = itemData?.compare_at_base || 0;

                                      // Add suggested and breakeven from target prices
                                      if (targetPrice) {
                                        newUpdates[idx].suggested_price = targetPrice[`final_suggested_${selectedCountry}`] || null;
                                        newUpdates[idx].breakeven_price = targetPrice[`breakeven_${selectedCountry}`] || null;
                                      }

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
                            <TableCell className="text-center text-sm text-orange-600 font-semibold">
                              {update.breakeven_price ? formatCurrency(update.breakeven_price) : '-'}
                            </TableCell>
                            <TableCell className="text-center text-sm text-blue-600 font-semibold">
                              {update.suggested_price ? formatCurrency(update.suggested_price) : '-'}
                            </TableCell>
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
                              <div className="flex gap-1 justify-center">
                                {update.suggested_price && (
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-7 px-2 text-xs"
                                    onClick={() => {
                                      const newUpdates = [...priceUpdates];
                                      newUpdates[idx].new_price = update.suggested_price;
                                      setPriceUpdates(newUpdates);
                                    }}
                                    title="Use suggested price"
                                  >
                                    📊
                                  </Button>
                                )}
                                {update.breakeven_price && (
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-7 px-2 text-xs"
                                    onClick={() => {
                                      const newUpdates = [...priceUpdates];
                                      newUpdates[idx].new_price = update.breakeven_price;
                                      setPriceUpdates(newUpdates);
                                    }}
                                    title="Use breakeven price"
                                  >
                                    ⚖️
                                  </Button>
                                )}
                                {update.breakeven_price && update.suggested_price && (
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-7 px-2 text-xs"
                                    onClick={() => {
                                      const newUpdates = [...priceUpdates];
                                      const midPrice = (update.breakeven_price + update.suggested_price) / 2;
                                      newUpdates[idx].new_price = parseFloat(midPrice.toFixed(2));
                                      setPriceUpdates(newUpdates);
                                    }}
                                    title="Use mid-point"
                                  >
                                    🎯
                                  </Button>
                                )}
                              </div>
                            </TableCell>
                            <TableCell className="text-center">
                              <div className="flex justify-center">
                                {update.compare_at_policy === 'Manual' ? (
                                  <Input
                                    type="number"
                                    step="0.01"
                                    className="text-center h-8 w-[80px]"
                                    value={update.new_compare_at ?? ''}
                                    onChange={(e) => {
                                      const newUpdates = [...priceUpdates];
                                      newUpdates[idx].new_compare_at = e.target.value ? parseFloat(e.target.value) : null;
                                      setPriceUpdates(newUpdates);
                                    }}
                                    placeholder="Enter"
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
                                  <SelectTrigger className="h-8 w-[80px]">
                                    <SelectValue />
                                  </SelectTrigger>
                                  <SelectContent>
                                    <SelectItem value="B">B</SelectItem>
                                    <SelectItem value="D">D</SelectItem>
                                    <SelectItem value="Manual">Manual</SelectItem>
                                  </SelectContent>
                                </Select>
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
              <CardDescription>Recent price changes and their status (includes Korealy COGS syncs)</CardDescription>
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
                        <TableHead>Type</TableHead>
                        <TableHead className="text-right">Old Value</TableHead>
                        <TableHead className="text-right">New Value</TableHead>
                        <TableHead className="text-right">Change %</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Notes</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {updateLog.map((log, idx) => {
                        // Parse Korealy COGS updates from notes format: KOREALY_COGS|old|new
                        const isKorealyCogs = log.notes?.startsWith('KOREALY_COGS|');
                        let oldCogs = null, newCogs = null, displayNotes = log.notes;
                        if (isKorealyCogs) {
                          const parts = log.notes.split('|');
                          oldCogs = parseFloat(parts[1]) || 0;
                          newCogs = parseFloat(parts[2]) || 0;
                          displayNotes = `COGS: $${oldCogs.toFixed(2)} → $${newCogs.toFixed(2)}`;
                        }

                        return (
                          <TableRow key={idx} className={isKorealyCogs ? 'bg-purple-50' : ''}>
                            <TableCell className="text-sm">{log.timestamp}</TableCell>
                            <TableCell className="font-mono text-sm">{log.variant_id}</TableCell>
                            <TableCell className={`font-medium ${expandProductNames ? '' : 'max-w-[200px] truncate'}`} title={log.item}>{log.item}</TableCell>
                            <TableCell>
                              <Badge variant={isKorealyCogs ? 'secondary' : 'outline'}>
                                {isKorealyCogs ? 'Korealy COGS' : log.market || 'Price'}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-right">
                              {isKorealyCogs ? formatCurrency(oldCogs) : formatCurrency(log.old_price)}
                            </TableCell>
                            <TableCell className="text-right">
                              {isKorealyCogs ? formatCurrency(newCogs) : formatCurrency(log.new_price)}
                            </TableCell>
                            <TableCell className="text-right">
                              {(() => {
                                const oldVal = isKorealyCogs ? oldCogs : log.old_price;
                                const newVal = isKorealyCogs ? newCogs : log.new_price;
                                const changePct = oldVal > 0 ? ((newVal - oldVal) / oldVal) * 100 : 0;
                                return (
                                  <span className={changePct >= 0 ? 'text-green-600' : 'text-red-600'}>
                                    {changePct >= 0 ? '+' : ''}{changePct.toFixed(1)}%
                                  </span>
                                );
                              })()}
                            </TableCell>
                            <TableCell>
                              <Badge variant={log.status === 'success' ? 'default' : 'destructive'}>
                                {log.status}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-sm text-slate-600 max-w-[200px] truncate" title={displayNotes}>
                              {displayNotes}
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
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={loadingOrderCounts || targetPrices.length === 0}
                    onClick={async () => {
                      setLoadingOrderCounts(true);
                      try {
                        const variantIds = targetPrices.map(p => p.variant_id);
                        const response = await fetch(`${API_URL}/variant-order-counts`, {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ variant_ids: variantIds, days: 30 })
                        });
                        if (!response.ok) throw new Error('Failed to fetch order counts');
                        const result = await response.json();
                        if (result.success) {
                          setOrderCounts(result.counts || {});
                        }
                      } catch (err) {
                        console.error('Error fetching order counts:', err);
                        alert(`Failed to fetch order counts: ${err.message}`);
                      } finally {
                        setLoadingOrderCounts(false);
                      }
                    }}
                  >
                    {loadingOrderCounts ? '⏳ Loading...' : '📊 Load Orders (30d)'}
                  </Button>
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
                            notes: `Priority: ${price[`priority_${countryKey}`]}, Loss: ${formatCurrency(price[`loss_amount_${countryKey}`])}`,
                            suggested_price: price[`final_suggested_${countryKey}`],
                            breakeven_price: price[`breakeven_${countryKey}`]
                          }));
                          console.log('New updates:', newUpdates);
                          setPriceUpdates([...priceUpdates, ...newUpdates]);
                          setPriceUpdatesLoadedFromBackend(true); // Mark as loaded to prevent fetch overwrite
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
                          <TableHead className="text-right">
                            Orders (30d)
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
                            <TableCell className={`font-medium ${expandProductNames ? '' : 'max-w-[250px] truncate'}`}>{price.item}</TableCell>
                            <TableCell className="text-right">{(price.weight_g || 0).toFixed(0)}</TableCell>
                            <TableCell className="text-right">{formatCurrency(price.cogs)}</TableCell>
                            <TableCell className="text-right">
                              {orderCounts[price.variant_id] !== undefined ? (
                                <Badge variant={orderCounts[price.variant_id] > 0 ? 'default' : 'outline'}>
                                  {orderCounts[price.variant_id]}
                                </Badge>
                              ) : (
                                <span className="text-slate-400">-</span>
                              )}
                            </TableCell>
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
                  {/* Variant ID Price Check */}
                  <div className="bg-blue-50 p-4 rounded-lg border border-blue-200">
                    <h3 className="text-sm font-semibold text-blue-900 mb-2">🧠 Smart Competitor Price Analysis</h3>
                    <p className="text-xs text-blue-700 mb-3">
                      Intelligent price scanning with automatic filtering:
                      <span className="font-semibold"> Trusted Sellers Only</span> (excludes Mercari, Poshmark, eBay individuals) +
                      <span className="font-semibold"> Outlier Removal</span> (median-based 0.4x-2.5x filtering)
                    </p>
                    <div className="flex gap-2">
                      <textarea
                        className="flex-1 p-2 border border-blue-300 rounded-lg font-mono text-sm"
                        placeholder="51750779093364&#10;51750800228724&#10;51750801146228"
                        value={variantIdsToCheck}
                        onChange={(e) => setVariantIdsToCheck(e.target.value)}
                        rows={3}
                      />
                      <div className="flex flex-col gap-2">
                        <Button
                          variant="default"
                          size="sm"
                          onClick={async () => {
                            const ids = variantIdsToCheck.split('\n').filter(id => id.trim());
                            if (ids.length === 0) {
                              alert('Please enter at least one variant ID');
                              return;
                            }

                            if (!confirm(`Scan competitor prices for ${ids.length} variant IDs?\n\n⏱️ Estimated time: ~${Math.ceil(ids.length * 0.8 / 60)} minutes\n\n${ids.length > 5 ? '📊 Large batch: Will run in background with live progress updates!' : '⚡ Small batch: Running synchronously'}\n\n🧠 Smart filtering will be applied:\n- Trusted sellers only\n- Outlier removal\n- Low/Avg/High pricing`)) {
                              return;
                            }

                            try {
                              const response = await fetch(`${API_URL}/pricing/check-competitor-prices`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ variant_ids: ids })
                              });

                              if (!response.ok) {
                                const errorText = await response.text();
                                throw new Error(`HTTP ${response.status}: ${errorText}`);
                              }

                              const result = await response.json();

                              // Check if this is a background task
                              if (result.background && result.task_id) {
                                // Start polling for progress
                                setBackgroundScan({
                                  taskId: result.task_id,
                                  status: 'running',
                                  progress: 0,
                                  total: ids.length,
                                  currentItem: 'Starting...'
                                });

                                // Poll for status
                                const pollInterval = setInterval(async () => {
                                  try {
                                    const statusResponse = await fetch(`${API_URL}/pricing/scan-status/${result.task_id}`);
                                    const status = await statusResponse.json();

                                    setBackgroundScan({
                                      taskId: result.task_id,
                                      status: status.status,
                                      progress: status.progress,
                                      total: status.total,
                                      currentItem: status.current_item || ''
                                    });

                                    if (status.status === 'completed' || status.status === 'failed') {
                                      clearInterval(pollInterval);

                                      if (status.status === 'completed') {
                                        alert(`✅ Scan Complete!\n\n${status.message}\n\nResults have been merged into Target Prices tab.`);
                                        fetchTargetPrices();
                                        fetchScanHistory();
                                      } else {
                                        alert(`❌ Scan failed: ${status.error || 'Unknown error'}`);
                                      }

                                      // Clear background scan state after a delay
                                      setTimeout(() => setBackgroundScan(null), 3000);
                                    }
                                  } catch (pollErr) {
                                    console.error('Poll error:', pollErr);
                                  }
                                }, 2000); // Poll every 2 seconds

                              } else if (result.success) {
                                // Synchronous result (small batch)
                                alert(`✅ Scan Complete!\n\nScanned: ${result.scanned_count} variants\n\n${result.message}\n\nResults have been merged into Target Prices tab.`);
                                fetchTargetPrices();
                                fetchScanHistory();
                              } else {
                                alert(`❌ Scan failed: ${result.message || 'Unknown error'}`);
                              }
                            } catch (err) {
                              console.error('Competitor price scan error:', err);
                              alert(`❌ Failed to scan prices: ${err.message}`);
                            }
                          }}
                          disabled={loading || backgroundScan?.status === 'running'}
                        >
                          {backgroundScan?.status === 'running' ? '⏳ Scanning...' : '🚀 Scan Prices'}
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            // Export variant IDs to clipboard for pasting into Google Sheets
                            navigator.clipboard.writeText(variantIdsToCheck);
                            alert('Variant IDs copied!\n\nPaste into column A of the "Items" tab in your Google Sheet.');
                          }}
                        >
                          📋 Export IDs
                        </Button>
                      </div>
                    </div>

                    <div className="mt-3 text-xs text-blue-700 bg-blue-100 p-2 rounded">
                      <p className="font-semibold mb-1">🧠 Smart Analysis Features:</p>
                      <ul className="list-disc list-inside ml-2 space-y-1">
                        <li><strong>Trusted Sellers:</strong> Auto-filters out Mercari, Poshmark, eBay individuals, AliExpress, Wish, Temu</li>
                        <li><strong>Outlier Removal:</strong> Median-based filtering (keeps 0.4x to 2.5x median range, requires 5+ prices)</li>
                        <li><strong>Dynamic CPA:</strong> 12% of retail price ($8-$25 bounds) - not fixed $15</li>
                        <li><strong>Competitive Strategy:</strong> Undercut avg by 3%, never below 25% margin floor</li>
                        <li><strong>Results:</strong> After scanning, data syncs to Target Prices tab with smart calculations</li>
                      </ul>
                    </div>
                  </div>
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
                        <p className="text-xs text-slate-500 mt-1">With Smart-Filtered Data</p>
                        <p className="text-xs text-blue-600 font-semibold mt-1">🧠 Trusted + Outliers Removed</p>
                      </CardContent>
                    </Card>
                    <Card>
                      <CardContent className="pt-6">
                        <div className="text-2xl font-bold text-red-600">{competitorAnalysis.overpriced.length}</div>
                        <p className="text-xs text-slate-500 mt-1">Overpriced (&gt;35%)</p>
                      </CardContent>
                    </Card>
                    <Card>
                      <CardContent className="pt-6">
                        <div className="text-2xl font-bold text-green-600">{competitorAnalysis.underpriced.length}</div>
                        <p className="text-xs text-slate-500 mt-1">Underpriced (&lt;15%)</p>
                        <p className="text-xs text-green-600 font-semibold mt-1">💰 Revenue Opportunity</p>
                      </CardContent>
                    </Card>
                  </div>

                  {/* Overpriced Products */}
                  {competitorAnalysis.overpriced.length > 0 && (
                    <div>
                      <h3 className="text-lg font-semibold mb-3 text-red-700">🚨 Overpriced Products ({competitorAnalysis.overpriced.length})</h3>
                      <p className="text-sm text-slate-600 mb-4">Your prices are &gt;35% higher than competitor average - you may be losing sales</p>
                      <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
                        <Table>
                          <TableHeader className="sticky top-0 bg-white">
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
                            {(expandedCompetitorSections.overpriced
                              ? competitorAnalysis.overpriced
                              : competitorAnalysis.overpriced.slice(0, 10)
                            ).map((product) => {
                              const countryKey = selectedCountry;
                              const current = product[`current_${countryKey}`];
                              const compAvg = product[`comp_avg_${countryKey}`];
                              const compLow = product[`comp_low_${countryKey}`];
                              const compHigh = product[`comp_high_${countryKey}`];
                              const diffPct = ((current - compAvg) / compAvg) * 100;
                              return (
                                <TableRow key={product.variant_id}>
                                  <TableCell className={`font-medium ${expandProductNames ? '' : 'max-w-[300px] truncate'}`}>{product.item}</TableCell>
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
                        <Button
                          variant="link"
                          size="sm"
                          onClick={() => setExpandedCompetitorSections(prev => ({
                            ...prev,
                            overpriced: !prev.overpriced
                          }))}
                          className="mt-2 text-red-600"
                        >
                          {expandedCompetitorSections.overpriced
                            ? '▲ Show Less'
                            : `▼ Show ${competitorAnalysis.overpriced.length - 10} more`
                          }
                        </Button>
                      )}
                    </div>
                  )}

                  {/* Underpriced Products */}
                  {competitorAnalysis.underpriced.length > 0 && (
                    <div>
                      <h3 className="text-lg font-semibold mb-3 text-green-700">💰 Underpriced Products ({competitorAnalysis.underpriced.length})</h3>
                      <p className="text-sm text-slate-600 mb-4">Your prices are &lt;15% lower than competitor average - opportunity to raise prices</p>
                      <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
                        <Table>
                          <TableHeader className="sticky top-0 bg-white">
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
                            {(expandedCompetitorSections.underpriced
                              ? competitorAnalysis.underpriced
                              : competitorAnalysis.underpriced.slice(0, 10)
                            ).map((product) => {
                              const countryKey = selectedCountry;
                              const current = product[`current_${countryKey}`];
                              const compAvg = product[`comp_avg_${countryKey}`];
                              const compLow = product[`comp_low_${countryKey}`];
                              const compHigh = product[`comp_high_${countryKey}`];
                              const diffPct = ((current - compAvg) / compAvg) * 100;
                              return (
                                <TableRow key={product.variant_id}>
                                  <TableCell className={`font-medium ${expandProductNames ? '' : 'max-w-[300px] truncate'}`}>{product.item}</TableCell>
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
                        <Button
                          variant="link"
                          size="sm"
                          onClick={() => setExpandedCompetitorSections(prev => ({
                            ...prev,
                            underpriced: !prev.underpriced
                          }))}
                          className="mt-2 text-green-600"
                        >
                          {expandedCompetitorSections.underpriced
                            ? '▲ Show Less'
                            : `▼ Show ${competitorAnalysis.underpriced.length - 10} more`
                          }
                        </Button>
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

                  {/* Scan History Section */}
                  <div className="mt-6 pt-6 border-t">
                    <div className="flex items-center justify-between mb-4">
                      <div>
                        <h3 className="text-lg font-semibold text-slate-800">📜 Scan History</h3>
                        <p className="text-sm text-slate-600">Previous competitor price scans with timestamps</p>
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={fetchScanHistory}
                      >
                        🔄 Refresh
                      </Button>
                    </div>
                    {sortedScanHistory.length === 0 ? (
                      <div className="text-center py-6 text-slate-500">
                        <p>No scan history yet. Run a competitor price scan to see results here.</p>
                      </div>
                    ) : (
                      <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
                        <Table>
                          <TableHeader className="sticky top-0 bg-white">
                            <TableRow>
                              <TableHead
                                className="cursor-pointer hover:bg-slate-50"
                                onClick={() => handleScanHistorySort('timestamp')}
                              >
                                <div className="flex items-center gap-1">
                                  Timestamp
                                  {scanHistorySortColumn === 'timestamp' && (
                                    scanHistorySortDirection === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />
                                  )}
                                </div>
                              </TableHead>
                              <TableHead
                                className="cursor-pointer hover:bg-slate-50"
                                onClick={() => handleScanHistorySort('item')}
                              >
                                <div className="flex items-center gap-1">
                                  Item
                                  {scanHistorySortColumn === 'item' && (
                                    scanHistorySortDirection === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />
                                  )}
                                </div>
                              </TableHead>
                              <TableHead className="text-right">Comp Low</TableHead>
                              <TableHead className="text-right">Comp Avg</TableHead>
                              <TableHead className="text-right">Comp High</TableHead>
                              <TableHead className="text-right">Prices Found</TableHead>
                              <TableHead className="text-center">Actions</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {sortedScanHistory.map((scan, idx) => (
                              <TableRow key={`${scan.variant_id}-${scan.timestamp}-${idx}`}>
                                <TableCell className="text-sm text-slate-600 whitespace-nowrap">
                                  {new Date(scan.timestamp).toLocaleString()}
                                </TableCell>
                                <TableCell className={`font-medium ${expandProductNames ? '' : 'max-w-[250px] truncate'}`} title={scan.item}>
                                  {scan.item}
                                </TableCell>
                                <TableCell className="text-right text-slate-600">
                                  {scan.comp_low ? formatCurrency(scan.comp_low) : '-'}
                                </TableCell>
                                <TableCell className="text-right text-slate-600">
                                  {scan.comp_avg ? formatCurrency(scan.comp_avg) : '-'}
                                </TableCell>
                                <TableCell className="text-right text-slate-600">
                                  {scan.comp_high ? formatCurrency(scan.comp_high) : '-'}
                                </TableCell>
                                <TableCell className="text-right text-sm">
                                  <span className="text-slate-600" title={`Raw: ${scan.raw_count}, Trusted: ${scan.trusted_count}, Filtered: ${scan.filtered_count}`}>
                                    {scan.filtered_count || 0} / {scan.raw_count || 0}
                                  </span>
                                </TableCell>
                                <TableCell className="text-center">
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={async () => {
                                      if (!confirm(`Re-scan competitor prices for:\n${scan.item}?`)) return;
                                      setLoading(true);
                                      setLoadingMessage('Re-scanning prices...');
                                      try {
                                        const response = await fetch(`${API_URL}/pricing/check-competitor-prices`, {
                                          method: 'POST',
                                          headers: { 'Content-Type': 'application/json' },
                                          body: JSON.stringify({ variant_ids: [scan.variant_id] })
                                        });
                                        const result = await response.json();
                                        if (result.success) {
                                          alert(`✅ Re-scan complete!\n\n${result.message}`);
                                          fetchScanHistory();
                                          fetchTargetPrices();
                                        } else {
                                          alert(`❌ Re-scan failed: ${result.message}`);
                                        }
                                      } catch (err) {
                                        alert(`❌ Re-scan failed: ${err.message}`);
                                      } finally {
                                        setLoading(false);
                                        setLoadingMessage('');
                                      }
                                    }}
                                    title="Re-scan this item"
                                  >
                                    🔍 Re-scan
                                  </Button>
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* KOREALY RECONCILIATION TAB */}
        <TabsContent value="korealy-reconciliation">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Korealy Reconciliation</CardTitle>
                  <CardDescription>
                    Compare Korealy supplier prices with Shopify COGS and sync mismatches
                  </CardDescription>
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    onClick={() => {
                      setKorealyReconciliation([]);
                      setKorealyStats({});
                      setKorealySelectedRows(new Set());
                      fetchKorealyReconciliation();
                    }}
                  >
                    🔄 Re-run Reconciliation
                  </Button>
                  <Button
                    onClick={async () => {
                      if (korealySelectedRows.size === 0) {
                        alert('Please select items to sync');
                        return;
                      }

                      if (!confirm(`Sync ${korealySelectedRows.size} selected items to Shopify?`)) {
                        return;
                      }

                      setLoading(true);
                      try {
                        // Build updates array
                        const updates = Array.from(korealySelectedRows).map(idx => {
                          const record = korealyReconciliation[idx];
                          return {
                            variant_id: record.variant_id,
                            new_cogs: record.korealy_cogs
                          };
                        });

                        const response = await fetch(`${API_URL}/pricing/korealy-sync`, {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ updates })
                        });

                        const result = await response.json();

                        // Handle background task
                        if (result.background && result.task_id) {
                          setCurrentScanTask({ taskId: result.task_id, type: 'korealy_sync' });
                          setScanProgress({ current: 0, total: updates.length, status: 'running', currentItem: '' });

                          // Poll for status
                          const pollInterval = setInterval(async () => {
                            try {
                              const statusRes = await fetch(`${API_URL}/pricing/korealy-sync-status/${result.task_id}`);
                              const status = await statusRes.json();

                              setScanProgress({
                                current: status.progress,
                                total: status.total,
                                status: status.status,
                                currentItem: status.current_item
                              });

                              if (status.status === 'completed' || status.status === 'failed') {
                                clearInterval(pollInterval);
                                setCurrentScanTask(null);
                                setScanProgress(null);
                                setLoading(false);

                                if (status.status === 'completed') {
                                  alert(`✅ Synced ${status.updated_count} items to Shopify (${status.skipped_count} skipped, ${status.failed_count} failed)`);
                                  setKorealySelectedRows(new Set());
                                  fetchKorealyReconciliation(); // Refresh
                                } else {
                                  alert(`❌ Sync failed: ${status.error || status.message}`);
                                }
                              }
                            } catch (pollErr) {
                              console.error('Poll error:', pollErr);
                            }
                          }, 1000);
                          return; // Don't setLoading(false) - let the polling handle it
                        }

                        // Synchronous result
                        if (result.success) {
                          alert(`✅ Synced ${result.updated_count} items to Shopify`);
                          setKorealySelectedRows(new Set());
                          fetchKorealyReconciliation(); // Refresh
                        } else {
                          alert(`❌ Sync failed: ${result.message}`);
                        }
                      } catch (err) {
                        alert(`❌ Sync failed: ${err.message}`);
                      } finally {
                        if (!currentScanTask) setLoading(false);
                      }
                    }}
                    disabled={korealySelectedRows.size === 0 || loading}
                  >
                    💾 Sync {korealySelectedRows.size > 0 ? korealySelectedRows.size : ''} to Shopify
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {/* Summary Stats */}
              {korealyStats && Object.keys(korealyStats).length > 0 && (
                <div className="grid grid-cols-6 gap-4 mb-6">
                  <div className="bg-blue-50 p-4 rounded-lg">
                    <div className="text-sm text-blue-600 font-medium">Total</div>
                    <div className="text-2xl font-bold">{korealyStats.total || 0}</div>
                  </div>
                  <div className="bg-green-50 p-4 rounded-lg">
                    <div className="text-sm text-green-600 font-medium">Match</div>
                    <div className="text-2xl font-bold">{korealyStats.MATCH || 0}</div>
                  </div>
                  <div className="bg-red-50 p-4 rounded-lg">
                    <div className="text-sm text-red-600 font-medium">Mismatch</div>
                    <div className="text-2xl font-bold">{korealyStats.MISMATCH || 0}</div>
                  </div>
                  <div className="bg-yellow-50 p-4 rounded-lg">
                    <div className="text-sm text-yellow-600 font-medium">No Mapping</div>
                    <div className="text-2xl font-bold">{korealyStats.NO_MAPPING || 0}</div>
                  </div>
                  <div className="bg-orange-50 p-4 rounded-lg">
                    <div className="text-sm text-orange-600 font-medium">No Korealy COGS</div>
                    <div className="text-2xl font-bold">{korealyStats.NO_COGS_IN_KOREALY || 0}</div>
                  </div>
                  <div className="bg-purple-50 p-4 rounded-lg">
                    <div className="text-sm text-purple-600 font-medium">No Shopify COGS</div>
                    <div className="text-2xl font-bold">{korealyStats.NO_COGS_IN_SHOPIFY || 0}</div>
                  </div>
                </div>
              )}

              {/* Status Filter */}
              <div className="flex gap-2 mb-4">
                <Button
                  variant={korealyStatusFilter === 'all' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setKorealyStatusFilter('all')}
                >
                  All ({korealyReconciliation.length})
                </Button>
                <Button
                  variant={korealyStatusFilter === 'MISMATCH' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setKorealyStatusFilter('MISMATCH')}
                >
                  Mismatch ({korealyStats.MISMATCH || 0})
                </Button>
                <Button
                  variant={korealyStatusFilter === 'NO_MAPPING' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setKorealyStatusFilter('NO_MAPPING')}
                >
                  No Mapping ({korealyStats.NO_MAPPING || 0})
                </Button>
                <Button
                  variant={korealyStatusFilter === 'NO_COGS_IN_SHOPIFY' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setKorealyStatusFilter('NO_COGS_IN_SHOPIFY')}
                >
                  No Shopify COGS ({korealyStats.NO_COGS_IN_SHOPIFY || 0})
                </Button>
                <Button
                  variant={korealyStatusFilter === 'MATCH' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setKorealyStatusFilter('MATCH')}
                >
                  Match ({korealyStats.MATCH || 0})
                </Button>
              </div>

              {/* Results Table */}
              {(() => {
                const filtered = korealyStatusFilter === 'all'
                  ? korealyReconciliation
                  : korealyReconciliation.filter(r => r.status === korealyStatusFilter);

                return (
                  <div className="border rounded-lg overflow-hidden">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="w-12">
                            <input
                              type="checkbox"
                              checked={korealySelectedRows.size === filtered.length && filtered.length > 0}
                              onChange={(e) => {
                                if (e.target.checked) {
                                  const newSet = new Set();
                                  filtered.forEach((_, idx) => {
                                    const originalIdx = korealyReconciliation.indexOf(_);
                                    newSet.add(originalIdx);
                                  });
                                  setKorealySelectedRows(newSet);
                                } else {
                                  setKorealySelectedRows(new Set());
                                }
                              }}
                            />
                          </TableHead>
                          <TableHead>Status</TableHead>
                          <TableHead>Korealy Title</TableHead>
                          <TableHead>Shopify Item</TableHead>
                          <TableHead className="text-right">Korealy COGS</TableHead>
                          <TableHead className="text-right">Shopify COGS</TableHead>
                          <TableHead className="text-right">Delta</TableHead>
                          <TableHead className="text-right">% Diff</TableHead>
                          <TableHead>Variant ID</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {filtered.length === 0 ? (
                          <TableRow>
                            <TableCell colSpan={9} className="text-center text-slate-500 py-8">
                              {korealyReconciliation.length === 0
                                ? 'No reconciliation data. Click "Re-run Reconciliation" to load data.'
                                : 'No items match the current filter.'}
                            </TableCell>
                          </TableRow>
                        ) : (
                          filtered.map((record, idx) => {
                            const originalIdx = korealyReconciliation.indexOf(record);
                            const isSelected = korealySelectedRows.has(originalIdx);
                            const canSync = record.status === 'MISMATCH' && record.variant_id;

                            return (
                              <TableRow key={idx}>
                                <TableCell>
                                  <input
                                    type="checkbox"
                                    checked={isSelected}
                                    disabled={!canSync}
                                    onChange={(e) => {
                                      const newSet = new Set(korealySelectedRows);
                                      if (e.target.checked) {
                                        newSet.add(originalIdx);
                                      } else {
                                        newSet.delete(originalIdx);
                                      }
                                      setKorealySelectedRows(newSet);
                                    }}
                                  />
                                </TableCell>
                                <TableCell>
                                  <span className={`px-2 py-1 rounded text-xs font-medium ${
                                    record.status === 'MATCH' ? 'bg-green-100 text-green-800' :
                                    record.status === 'MISMATCH' ? 'bg-red-100 text-red-800' :
                                    record.status === 'NO_MAPPING' ? 'bg-yellow-100 text-yellow-800' :
                                    'bg-gray-100 text-gray-800'
                                  }`}>
                                    {record.status}
                                  </span>
                                </TableCell>
                                <TableCell className={expandProductNames ? '' : 'max-w-xs truncate'} title={record.korealy_title}>
                                  {record.korealy_title}
                                </TableCell>
                                <TableCell className={expandProductNames ? '' : 'max-w-xs truncate'} title={record.shopify_item || '-'}>
                                  {record.shopify_item || '-'}
                                </TableCell>
                                <TableCell className="text-right">
                                  {record.korealy_cogs ? `${record.korealy_currency} ${record.korealy_cogs.toFixed(2)}` : '-'}
                                </TableCell>
                                <TableCell className="text-right">
                                  {record.shopify_cogs ? `${record.shopify_currency} ${record.shopify_cogs.toFixed(2)}` : '-'}
                                </TableCell>
                                <TableCell className="text-right">
                                  {record.delta !== null ? (
                                    <span className={record.delta > 0 ? 'text-red-600' : record.delta < 0 ? 'text-green-600' : ''}>
                                      {record.delta > 0 ? '+' : ''}{record.delta.toFixed(2)}
                                    </span>
                                  ) : '-'}
                                </TableCell>
                                <TableCell className="text-right">
                                  {record.pct_diff !== null ? (
                                    <span className={record.pct_diff > 0 ? 'text-red-600' : record.pct_diff < 0 ? 'text-green-600' : ''}>
                                      {record.pct_diff > 0 ? '+' : ''}{record.pct_diff.toFixed(1)}%
                                    </span>
                                  ) : '-'}
                                </TableCell>
                                <TableCell className="font-mono text-sm">
                                  {record.variant_id || '-'}
                                </TableCell>
                              </TableRow>
                            );
                          })
                        )}
                      </TableBody>
                    </Table>
                  </div>
                );
              })()}
            </CardContent>
          </Card>
        </TabsContent>

        {/* PRODUCT MANAGEMENT TAB */}
        <TabsContent value="product-management">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Product Management</CardTitle>
                  <CardDescription>Add or delete products from Shopify</CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <div className="space-y-6">
                {/* Bulk Paste Section */}
                <div className="bg-blue-50 p-4 rounded-lg border border-blue-200">
                  <h3 className="text-sm font-semibold text-blue-900 mb-2">📋 Bulk Product Operations</h3>
                  <p className="text-xs text-blue-700 mb-3">
                    Paste variant IDs (one per line) to perform bulk operations. Default action is <strong>Delete</strong>.
                  </p>
                  <div className="flex gap-2">
                    <textarea
                      className="flex-1 p-2 border border-blue-300 rounded-lg font-mono text-sm"
                      placeholder="51750779093364&#10;51750800228724&#10;51750801146228"
                      value={productPasteInput}
                      onChange={(e) => setProductPasteInput(e.target.value)}
                      rows={5}
                    />
                    <div className="flex flex-col gap-2">
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => {
                          const ids = productPasteInput.split('\n').filter(id => id.trim());
                          if (ids.length === 0) {
                            alert('Please enter at least one variant ID');
                            return;
                          }

                          // Add all as delete actions
                          const newActions = ids.map(id => ({
                            action: 'delete',
                            variant_id: id.trim(),
                            title: '',
                            price: 0,
                            sku: '',
                            inventory: 0
                          }));

                          setProductManagementActions([...productManagementActions, ...newActions]);
                          setProductPasteInput('');
                        }}
                      >
                        🗑️ Add {productPasteInput.split('\n').filter(id => id.trim()).length > 0 ? productPasteInput.split('\n').filter(id => id.trim()).length : ''} for Delete
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          const ids = productPasteInput.split('\n').filter(id => id.trim());
                          if (ids.length === 0) {
                            alert('Please enter at least one variant ID');
                            return;
                          }

                          // Add all as add actions (user will need to fill details)
                          const newActions = ids.map(id => ({
                            action: 'add',
                            variant_id: id.trim(),
                            title: '',
                            price: 0,
                            sku: '',
                            inventory: 0
                          }));

                          setProductManagementActions([...productManagementActions, ...newActions]);
                          setProductPasteInput('');
                        }}
                      >
                        ➕ Add {productPasteInput.split('\n').filter(id => id.trim()).length > 0 ? productPasteInput.split('\n').filter(id => id.trim()).length : ''} for Creation
                      </Button>
                    </div>
                  </div>
                </div>

                {/* Action Buttons */}
                <div className="flex gap-3">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setProductManagementActions([...productManagementActions, {
                        action: 'delete',
                        variant_id: '',
                        title: '',
                        price: 0,
                        sku: '',
                        inventory: 0
                      }]);
                    }}
                  >
                    + Add Row (Delete)
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      // Set all actions to delete
                      const newActions = productManagementActions.map(action => ({
                        ...action,
                        action: 'delete'
                      }));
                      setProductManagementActions(newActions);
                    }}
                    disabled={productManagementActions.length === 0}
                  >
                    🗑️ Set All to Delete
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      // Set all actions to add
                      const newActions = productManagementActions.map(action => ({
                        ...action,
                        action: 'add'
                      }));
                      setProductManagementActions(newActions);
                    }}
                    disabled={productManagementActions.length === 0}
                  >
                    ➕ Set All to Add
                  </Button>
                  <Button
                    variant="destructive"
                    onClick={async () => {
                      if (productManagementActions.length === 0) {
                        alert('No actions to execute');
                        return;
                      }

                      const deleteCount = productManagementActions.filter(a => a.action === 'delete').length;
                      const addCount = productManagementActions.filter(a => a.action === 'add').length;

                      if (!confirm(`Execute ${productManagementActions.length} actions?\n\n${deleteCount} deletions, ${addCount} additions`)) {
                        return;
                      }

                      setLoading(true);
                      try {
                        const response = await fetch(`${API_URL}/pricing/product-actions`, {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ actions: productManagementActions })
                        });

                        const result = await response.json();

                        if (result.error) {
                          alert(`Error: ${result.error}`);
                        } else {
                          alert(`Success: ${result.message || 'Actions executed'}`);
                          setProductManagementActions([]);
                          fetchItems(); // Refresh items list
                        }
                      } catch (err) {
                        alert(`Failed to execute actions: ${err.message}`);
                      } finally {
                        setLoading(false);
                      }
                    }}
                    disabled={productManagementActions.length === 0}
                  >
                    Execute Actions ({productManagementActions.length})
                  </Button>
                </div>

                {/* Instructions */}
                <div className="bg-slate-50 p-4 rounded-lg text-sm text-slate-600">
                  <p className="font-semibold mb-2">How to use:</p>
                  <ul className="list-disc list-inside space-y-1">
                    <li><strong>Bulk Operations:</strong> Paste variant IDs (one per line) in the blue box above</li>
                    <li><strong>Delete (Default):</strong> Click "🗑️ Add X for Delete" to queue bulk deletions</li>
                    <li><strong>Add Products:</strong> Click "➕ Add X for Creation" (then fill product details in table)</li>
                    <li><strong>Mass Update:</strong> Use "Set All to Delete" or "Set All to Add" to change all actions at once</li>
                    <li><strong>Execute:</strong> Click "Execute Actions" to push changes to Shopify</li>
                  </ul>
                </div>

                {/* Actions Table */}
                {productManagementActions.length === 0 ? (
                  <div className="text-center py-12 text-slate-500 border-2 border-dashed border-slate-200 rounded-lg">
                    <Package className="h-12 w-12 mx-auto mb-4 text-slate-400" />
                    <p className="text-sm">No product actions yet</p>
                    <p className="text-sm">Click "+ Add Product Row" to begin</p>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="w-[40px] text-center"></TableHead>
                          <TableHead className="text-center">Action</TableHead>
                          <TableHead className="text-center">Variant ID</TableHead>
                          <TableHead className="text-center">Title</TableHead>
                          <TableHead className="text-center">Price</TableHead>
                          <TableHead className="text-center">SKU</TableHead>
                          <TableHead className="text-center">Inventory</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {productManagementActions.map((action, idx) => (
                          <TableRow key={idx}>
                            <TableCell className="text-center">
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-6 w-6 p-0 text-red-600 hover:text-red-700 hover:bg-red-50"
                                onClick={() => {
                                  setProductManagementActions(productManagementActions.filter((_, i) => i !== idx));
                                }}
                              >
                                ×
                              </Button>
                            </TableCell>
                            <TableCell className="text-center">
                              <Select
                                value={action.action}
                                onValueChange={(value) => {
                                  const newActions = [...productManagementActions];
                                  newActions[idx].action = value;
                                  setProductManagementActions(newActions);
                                }}
                              >
                                <SelectTrigger className="h-8 w-[100px]">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem value="delete">🗑️ Delete</SelectItem>
                                  <SelectItem value="add">➕ Add</SelectItem>
                                </SelectContent>
                              </Select>
                            </TableCell>
                            <TableCell className="text-center">
                              <Input
                                className="font-mono text-sm h-8 text-center"
                                value={action.variant_id}
                                onChange={(e) => {
                                  const newActions = [...productManagementActions];
                                  newActions[idx].variant_id = e.target.value;
                                  setProductManagementActions(newActions);
                                }}
                                placeholder="Variant ID"
                              />
                            </TableCell>
                            <TableCell className="text-center">
                              <Input
                                className="text-sm h-8 text-center"
                                value={action.title}
                                onChange={(e) => {
                                  const newActions = [...productManagementActions];
                                  newActions[idx].title = e.target.value;
                                  setProductManagementActions(newActions);
                                }}
                                placeholder="Product Title"
                                disabled={action.action === 'delete'}
                              />
                            </TableCell>
                            <TableCell className="text-center">
                              <Input
                                type="number"
                                step="0.01"
                                className="text-center h-8 w-[100px]"
                                value={action.price}
                                onChange={(e) => {
                                  const newActions = [...productManagementActions];
                                  newActions[idx].price = parseFloat(e.target.value) || 0;
                                  setProductManagementActions(newActions);
                                }}
                                disabled={action.action === 'delete'}
                              />
                            </TableCell>
                            <TableCell className="text-center">
                              <Input
                                className="text-sm h-8 w-[120px] text-center"
                                value={action.sku}
                                onChange={(e) => {
                                  const newActions = [...productManagementActions];
                                  newActions[idx].sku = e.target.value;
                                  setProductManagementActions(newActions);
                                }}
                                placeholder="SKU"
                                disabled={action.action === 'delete'}
                              />
                            </TableCell>
                            <TableCell className="text-center">
                              <Input
                                type="number"
                                className="text-center h-8 w-[80px]"
                                value={action.inventory}
                                onChange={(e) => {
                                  const newActions = [...productManagementActions];
                                  newActions[idx].inventory = parseInt(e.target.value) || 0;
                                  setProductManagementActions(newActions);
                                }}
                                disabled={action.action === 'delete'}
                              />
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
