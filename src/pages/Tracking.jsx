import React, { useState, useEffect, useMemo } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Package,
  Truck,
  Clock,
  CheckCircle,
  AlertTriangle,
  RefreshCw,
  Search,
  MapPin,
  Calendar,
  User,
  Mail,
  ExternalLink,
  Play,
  Send,
  TrendingUp,
  AlertCircle,
  Timer,
  Globe,
  Box
} from 'lucide-react';
import { format, formatDistanceToNow } from 'date-fns';
import { cn } from '@/lib/utils';

const API_URL = '/api';

export default function Tracking() {
  const { getAuthHeader } = useAuth();
  const [shipments, setShipments] = useState([]);
  const [stats, setStats] = useState({
    total: 0,
    pending: 0,
    in_transit: 0,
    out_for_delivery: 0,
    delivered: 0,
    exception: 0,
    delayed: 0,
    followup_pending: 0,
    avg_delivery_days: null,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [statusFilter, setStatusFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [selectedShipment, setSelectedShipment] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [isChecking, setIsChecking] = useState(false);
  const [isCheckingSelected, setIsCheckingSelected] = useState(false);
  const [checkingId, setCheckingId] = useState(null);
  const [selectedIds, setSelectedIds] = useState(new Set());

  // Followup state
  const [followupPreview, setFollowupPreview] = useState(null);
  const [isSendingFollowup, setIsSendingFollowup] = useState(false);
  const [isSendingAllFollowups, setIsSendingAllFollowups] = useState(false);
  const [followupDialogOpen, setFollowupDialogOpen] = useState(false);

  // Fetch shipments
  const fetchShipments = async () => {
    try {
      const params = new URLSearchParams();
      if (statusFilter && statusFilter !== 'all') {
        if (statusFilter === 'delayed') {
          params.append('delayed_only', 'true');
        } else if (statusFilter === 'followup') {
          params.append('followup_pending', 'true');
        } else {
          params.append('status', statusFilter);
        }
      }
      params.append('limit', '200');

      const response = await fetch(`${API_URL}/tracking/shipments?${params}`, {
        headers: getAuthHeader()
      });
      if (!response.ok) throw new Error('Failed to fetch shipments');
      const data = await response.json();
      setShipments(data.shipments || []);
    } catch (err) {
      console.error('Failed to fetch shipments:', err);
      setError(err.message);
    }
  };

  // Fetch stats
  const fetchStats = async () => {
    try {
      const response = await fetch(`${API_URL}/tracking/stats`, {
        headers: getAuthHeader()
      });
      if (!response.ok) throw new Error('Failed to fetch stats');
      const data = await response.json();
      setStats(data);
    } catch (err) {
      console.error('Failed to fetch stats:', err);
    }
  };

  // Initial load
  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      await Promise.all([fetchShipments(), fetchStats()]);
      setLoading(false);
    };
    loadData();
  }, [statusFilter]);

  // Sync from Shopify
  const handleSync = async () => {
    setIsSyncing(true);
    try {
      const response = await fetch(`${API_URL}/tracking/sync`, {
        method: 'POST',
        headers: getAuthHeader()
      });
      const data = await response.json();
      if (data.success) {
        await fetchShipments();
        await fetchStats();
      }
    } catch (err) {
      console.error('Sync error:', err);
      setError(err.message);
    } finally {
      setIsSyncing(false);
    }
  };

  // Check all active trackings
  const handleCheckAll = async () => {
    setIsChecking(true);
    try {
      const response = await fetch(`${API_URL}/tracking/check-all`, {
        method: 'POST',
        headers: getAuthHeader()
      });
      const data = await response.json();
      if (data.success) {
        // Refresh after a delay to let background task run
        setTimeout(async () => {
          await fetchShipments();
          await fetchStats();
          setIsChecking(false);
        }, 3000);
      }
    } catch (err) {
      console.error('Check all error:', err);
      setError(err.message);
      setIsChecking(false);
    }
  };

  // Toggle selection for a single shipment
  const toggleSelection = (trackingNumber) => {
    setSelectedIds(prev => {
      const newSet = new Set(prev);
      if (newSet.has(trackingNumber)) {
        newSet.delete(trackingNumber);
      } else {
        newSet.add(trackingNumber);
      }
      return newSet;
    });
  };

  // Select/deselect all visible shipments
  const toggleSelectAll = () => {
    if (selectedIds.size === filteredShipments.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredShipments.map(s => s.tracking_number)));
    }
  };

  // Check selected trackings
  const handleCheckSelected = async () => {
    if (selectedIds.size === 0) return;

    setIsCheckingSelected(true);
    try {
      // Check each selected tracking sequentially
      for (const trackingNumber of selectedIds) {
        setCheckingId(trackingNumber);
        try {
          await fetch(`${API_URL}/tracking/check/${trackingNumber}`, {
            method: 'POST',
            headers: getAuthHeader()
          });
        } catch (err) {
          console.error(`Check error for ${trackingNumber}:`, err);
        }
      }
      // Refresh data after all checks
      await fetchShipments();
      await fetchStats();
      setSelectedIds(new Set());
    } catch (err) {
      console.error('Check selected error:', err);
      setError(err.message);
    } finally {
      setIsCheckingSelected(false);
      setCheckingId(null);
    }
  };

  // Check single tracking
  const handleCheckSingle = async (trackingNumber) => {
    setCheckingId(trackingNumber);
    try {
      const response = await fetch(`${API_URL}/tracking/check/${trackingNumber}`, {
        method: 'POST',
        headers: getAuthHeader()
      });
      const data = await response.json();
      if (data.success) {
        await fetchShipments();
        if (selectedShipment?.tracking_number === trackingNumber) {
          setSelectedShipment(prev => ({
            ...prev,
            status: data.status,
            status_detail: data.status_detail,
            last_checkpoint: data.last_checkpoint,
          }));
        }
      }
    } catch (err) {
      console.error('Check error:', err);
    } finally {
      setCheckingId(null);
    }
  };

  // Mark followup sent
  const handleMarkFollowup = async (trackingId) => {
    try {
      const response = await fetch(`${API_URL}/tracking/mark-followup-sent/${trackingId}`, {
        method: 'POST',
        headers: getAuthHeader()
      });
      if (response.ok) {
        await fetchShipments();
        await fetchStats();
      }
    } catch (err) {
      console.error('Mark followup error:', err);
    }
  };

  // Preview followup email
  const handlePreviewFollowup = async (shipment) => {
    setIsSendingFollowup(true);
    setFollowupPreview(null);
    try {
      const response = await fetch(`${API_URL}/tracking/followup/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getAuthHeader() },
        body: JSON.stringify({
          customer_email: shipment.customer_email,
          customer_name: shipment.customer_name,
          order_number: shipment.order_number,
          ordered_items: shipment.line_items || ['Skincare product'],
        }),
      });
      const data = await response.json();
      if (data.success) {
        setFollowupPreview({
          ...data,
          shipment: shipment,
        });
        setFollowupDialogOpen(true);
      }
    } catch (err) {
      console.error('Preview followup error:', err);
    } finally {
      setIsSendingFollowup(false);
    }
  };

  // Send followup for single shipment
  const handleSendFollowup = async (trackingId) => {
    setIsSendingFollowup(true);
    try {
      const response = await fetch(`${API_URL}/tracking/followup/send/${trackingId}`, {
        method: 'POST',
        headers: getAuthHeader()
      });
      const data = await response.json();
      if (data.success) {
        setFollowupDialogOpen(false);
        setFollowupPreview(null);
        await fetchShipments();
        await fetchStats();
        // Update selected shipment if open
        if (selectedShipment?.id === trackingId) {
          setSelectedShipment(prev => ({ ...prev, delivery_followup_sent: true }));
        }
      }
    } catch (err) {
      console.error('Send followup error:', err);
    } finally {
      setIsSendingFollowup(false);
    }
  };

  // Send all pending followups
  const handleSendAllFollowups = async () => {
    setIsSendingAllFollowups(true);
    try {
      const response = await fetch(`${API_URL}/tracking/followup/send-all`, {
        method: 'POST',
        headers: getAuthHeader()
      });
      const data = await response.json();
      if (data.success) {
        // Refresh after a delay to let background task complete
        setTimeout(async () => {
          await fetchShipments();
          await fetchStats();
          setIsSendingAllFollowups(false);
        }, 3000);
      }
    } catch (err) {
      console.error('Send all followups error:', err);
      setIsSendingAllFollowups(false);
    }
  };

  // Filter shipments by search
  const filteredShipments = useMemo(() => {
    if (!search) return shipments;
    const s = search.toLowerCase();
    return shipments.filter(shipment =>
      shipment.order_number?.toLowerCase().includes(s) ||
      shipment.customer_name?.toLowerCase().includes(s) ||
      shipment.customer_email?.toLowerCase().includes(s) ||
      shipment.tracking_number?.toLowerCase().includes(s)
    );
  }, [shipments, search]);

  // Status badge helper
  const getStatusBadge = (status, delayDetected = false) => {
    if (delayDetected) {
      return <Badge className="bg-red-100 text-red-800"><AlertTriangle className="h-3 w-3 mr-1" />Delayed</Badge>;
    }

    const statusConfig = {
      pending: { color: 'bg-gray-100 text-gray-800', icon: Clock, label: 'Pending' },
      in_transit: { color: 'bg-blue-100 text-blue-800', icon: Truck, label: 'In Transit' },
      out_for_delivery: { color: 'bg-purple-100 text-purple-800', icon: Package, label: 'Out for Delivery' },
      delivered: { color: 'bg-green-100 text-green-800', icon: CheckCircle, label: 'Delivered' },
      exception: { color: 'bg-red-100 text-red-800', icon: AlertTriangle, label: 'Exception' },
      expired: { color: 'bg-gray-100 text-gray-800', icon: Clock, label: 'Expired' },
    };

    const config = statusConfig[status] || statusConfig.pending;
    const Icon = config.icon;

    return (
      <Badge className={config.color}>
        <Icon className="h-3 w-3 mr-1" />
        {config.label}
      </Badge>
    );
  };

  // Open shipment detail
  const openDetail = (shipment) => {
    setSelectedShipment(shipment);
    setDetailOpen(true);
  };

  // Generate tracking URL
  const getTrackingUrl = (trackingNumber, carrier) => {
    const carrierLower = (carrier || '').toLowerCase();
    if (carrierLower.includes('korea') || carrierLower.includes('k-packet')) {
      return `https://service.epost.go.kr/trace.RetrieveEmsRi498TraceList.comm?POST_CODE=${trackingNumber}`;
    }
    if (carrierLower.includes('usps')) {
      return `https://tools.usps.com/go/TrackConfirmAction?tLabels=${trackingNumber}`;
    }
    if (carrierLower.includes('dhl')) {
      return `https://www.dhl.com/en/express/tracking.html?AWB=${trackingNumber}`;
    }
    return `https://track.aftership.com/${trackingNumber}`;
  };

  if (loading) {
    return (
      <div className="p-6 space-y-6">
        <Skeleton className="h-8 w-64" />
        <div className="grid grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <Skeleton className="h-96" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">Tracking Dashboard</h1>
          <p className="text-slate-500 mt-1">
            Monitor shipments and delivery status
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={handleSync} disabled={isSyncing} variant="outline">
            <RefreshCw className={cn("h-4 w-4 mr-2", isSyncing && "animate-spin")} />
            {isSyncing ? 'Syncing...' : 'Sync Shopify'}
          </Button>
          {selectedIds.size > 0 && (
            <Button onClick={handleCheckSelected} disabled={isCheckingSelected} variant="default">
              <Play className={cn("h-4 w-4 mr-2", isCheckingSelected && "animate-pulse")} />
              {isCheckingSelected ? `Checking ${selectedIds.size}...` : `Check Selected (${selectedIds.size})`}
            </Button>
          )}
          <Button onClick={handleCheckAll} disabled={isChecking} variant="outline">
            <Play className={cn("h-4 w-4 mr-2", isChecking && "animate-pulse")} />
            {isChecking ? 'Checking...' : 'Check All'}
          </Button>
          {stats.followup_pending > 0 && (
            <Button
              onClick={handleSendAllFollowups}
              disabled={isSendingAllFollowups}
              className="bg-amber-600 hover:bg-amber-700"
            >
              <Send className={cn("h-4 w-4 mr-2", isSendingAllFollowups && "animate-pulse")} />
              {isSendingAllFollowups ? 'Sending...' : `Send ${stats.followup_pending} Followups`}
            </Button>
          )}
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-4">
        <Card className="cursor-pointer hover:shadow-md" onClick={() => setStatusFilter('all')}>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <Box className="h-5 w-5 text-slate-600" />
              <span className="text-2xl font-bold">{stats.total}</span>
            </div>
            <p className="text-xs text-slate-500 mt-1">Total</p>
          </CardContent>
        </Card>

        <Card className="cursor-pointer hover:shadow-md" onClick={() => setStatusFilter('in_transit')}>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <Truck className="h-5 w-5 text-blue-600" />
              <span className="text-2xl font-bold text-blue-600">{stats.in_transit}</span>
            </div>
            <p className="text-xs text-slate-500 mt-1">In Transit</p>
          </CardContent>
        </Card>

        <Card className="cursor-pointer hover:shadow-md" onClick={() => setStatusFilter('out_for_delivery')}>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <Package className="h-5 w-5 text-purple-600" />
              <span className="text-2xl font-bold text-purple-600">{stats.out_for_delivery}</span>
            </div>
            <p className="text-xs text-slate-500 mt-1">Out for Delivery</p>
          </CardContent>
        </Card>

        <Card className="cursor-pointer hover:shadow-md" onClick={() => setStatusFilter('delivered')}>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <CheckCircle className="h-5 w-5 text-green-600" />
              <span className="text-2xl font-bold text-green-600">{stats.delivered}</span>
            </div>
            <p className="text-xs text-slate-500 mt-1">Delivered</p>
          </CardContent>
        </Card>

        <Card className={cn("cursor-pointer hover:shadow-md", stats.delayed > 0 && "border-red-200 bg-red-50")} onClick={() => setStatusFilter('delayed')}>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <AlertTriangle className="h-5 w-5 text-red-600" />
              <span className={cn("text-2xl font-bold", stats.delayed > 0 ? "text-red-600" : "")}>{stats.delayed}</span>
            </div>
            <p className="text-xs text-slate-500 mt-1">Delayed</p>
          </CardContent>
        </Card>

        <Card className="cursor-pointer hover:shadow-md" onClick={() => setStatusFilter('exception')}>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <AlertCircle className="h-5 w-5 text-orange-600" />
              <span className="text-2xl font-bold text-orange-600">{stats.exception}</span>
            </div>
            <p className="text-xs text-slate-500 mt-1">Exception</p>
          </CardContent>
        </Card>

        <Card className={cn("cursor-pointer hover:shadow-md", stats.followup_pending > 0 && "border-amber-200 bg-amber-50")} onClick={() => setStatusFilter('followup')}>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <Send className="h-5 w-5 text-amber-600" />
              <span className={cn("text-2xl font-bold", stats.followup_pending > 0 ? "text-amber-600" : "")}>{stats.followup_pending}</span>
            </div>
            <p className="text-xs text-slate-500 mt-1">Need Followup</p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-4 pb-3">
            <div className="flex items-center justify-between">
              <Timer className="h-5 w-5 text-slate-600" />
              <span className="text-2xl font-bold">{stats.avg_delivery_days || '-'}</span>
            </div>
            <p className="text-xs text-slate-500 mt-1">Avg Days</p>
          </CardContent>
        </Card>
      </div>

      {/* Search and Filter */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg">Shipments</CardTitle>
            <div className="flex items-center gap-4">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                <Input
                  placeholder="Search order, customer, tracking..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="pl-10 w-64"
                />
              </div>
              <Tabs value={statusFilter} onValueChange={setStatusFilter}>
                <TabsList className="h-8">
                  <TabsTrigger value="all" className="text-xs px-2">All</TabsTrigger>
                  <TabsTrigger value="in_transit" className="text-xs px-2">Transit</TabsTrigger>
                  <TabsTrigger value="delivered" className="text-xs px-2">Delivered</TabsTrigger>
                  <TabsTrigger value="delayed" className="text-xs px-2">Delayed</TabsTrigger>
                  <TabsTrigger value="followup" className="text-xs px-2">Followup</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {filteredShipments.length === 0 ? (
            <div className="text-center py-12 text-slate-500">
              <Package className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p>No shipments found</p>
              <p className="text-sm mt-2">Try syncing from Shopify to import shipments</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="bg-slate-50">
                  <TableHead className="w-[40px]">
                    <Checkbox
                      checked={filteredShipments.length > 0 && selectedIds.size === filteredShipments.length}
                      onCheckedChange={toggleSelectAll}
                    />
                  </TableHead>
                  <TableHead className="w-[100px]">Order</TableHead>
                  <TableHead>Customer</TableHead>
                  <TableHead>Tracking</TableHead>
                  <TableHead className="w-[130px]">Status</TableHead>
                  <TableHead>Current Location</TableHead>
                  <TableHead className="w-[110px]">Timeline</TableHead>
                  <TableHead className="w-[80px]"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredShipments.map((shipment) => {
                  // Calculate days in transit
                  const shippedDate = shipment.shipped_at ? new Date(shipment.shipped_at) : null;
                  const daysInTransit = shippedDate ? Math.floor((new Date() - shippedDate) / (1000 * 60 * 60 * 24)) : null;

                  return (
                    <TableRow
                      key={shipment.id}
                      className={cn(
                        "cursor-pointer hover:bg-slate-50",
                        shipment.delay_detected && "bg-red-50 hover:bg-red-100",
                        selectedIds.has(shipment.tracking_number) && "bg-blue-50 hover:bg-blue-100"
                      )}
                      onClick={() => openDetail(shipment)}
                    >
                      <TableCell onClick={(e) => e.stopPropagation()}>
                        <Checkbox
                          checked={selectedIds.has(shipment.tracking_number)}
                          onCheckedChange={() => toggleSelection(shipment.tracking_number)}
                        />
                      </TableCell>
                      <TableCell>
                        <span className="font-medium">#{shipment.order_number}</span>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col">
                          <span className="font-medium truncate max-w-[140px]">{shipment.customer_name || '-'}</span>
                          <span className="text-xs text-slate-500 flex items-center gap-1">
                            <Globe className="h-3 w-3" />
                            {shipment.delivery_address_country || 'Unknown'}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col">
                          <span className="font-mono text-xs">{shipment.tracking_number?.substring(0, 18)}...</span>
                          <span className="text-xs text-slate-500">{shipment.carrier || 'Korea Post'}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-1">
                          {getStatusBadge(shipment.status, shipment.delay_detected)}
                          {shipment.status === 'delivered' && shipment.delivery_followup_sent && (
                            <Badge className="bg-amber-100 text-amber-700 text-xs w-fit">
                              <Mail className="h-2.5 w-2.5 mr-0.5" />
                              Followup
                            </Badge>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col">
                          <span className="text-sm truncate max-w-[200px] flex items-center gap-1">
                            <MapPin className="h-3 w-3 text-slate-400 flex-shrink-0" />
                            {shipment.last_checkpoint || 'Awaiting scan'}
                          </span>
                          {shipment.last_checkpoint_time && (
                            <span className="text-xs text-slate-500">
                              {formatDistanceToNow(new Date(shipment.last_checkpoint_time), { addSuffix: true })}
                            </span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col">
                          {daysInTransit !== null && (
                            <span className={cn(
                              "text-sm font-medium",
                              daysInTransit > 14 ? "text-red-600" : daysInTransit > 7 ? "text-amber-600" : "text-slate-600"
                            )}>
                              {shipment.status === 'delivered' ? (
                                <span className="text-green-600">Delivered</span>
                              ) : (
                                `${daysInTransit}d in transit`
                              )}
                            </span>
                          )}
                          {shipment.estimated_delivery && shipment.status !== 'delivered' && (
                            <span className="text-xs text-slate-500">
                              ETA: {format(new Date(shipment.estimated_delivery), 'MMM d')}
                            </span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleCheckSingle(shipment.tracking_number);
                            }}
                            disabled={checkingId === shipment.tracking_number}
                          >
                            <RefreshCw className={cn(
                              "h-4 w-4",
                              checkingId === shipment.tracking_number && "animate-spin"
                            )} />
                          </Button>
                          <a
                            href={getTrackingUrl(shipment.tracking_number, shipment.carrier)}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <Button variant="ghost" size="sm">
                              <ExternalLink className="h-4 w-4" />
                            </Button>
                          </a>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Shipment Detail Dialog */}
      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Package className="h-5 w-5" />
              Order #{selectedShipment?.order_number}
            </DialogTitle>
            <DialogDescription>
              Tracking: {selectedShipment?.tracking_number}
            </DialogDescription>
          </DialogHeader>

          {selectedShipment && (
            <div className="space-y-6">
              {/* Status Header */}
              <div className="flex items-center justify-between p-4 bg-slate-50 rounded-lg">
                <div className="flex items-center gap-3">
                  {getStatusBadge(selectedShipment.status, selectedShipment.delay_detected)}
                  {selectedShipment.delay_detected && selectedShipment.delay_days > 0 && (
                    <span className="text-sm text-red-600">
                      {selectedShipment.delay_days} days delayed
                    </span>
                  )}
                  {selectedShipment.shipped_at && (
                    <span className="text-sm text-slate-600">
                      {Math.floor((new Date() - new Date(selectedShipment.shipped_at)) / (1000 * 60 * 60 * 24))} days in transit
                    </span>
                  )}
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleCheckSingle(selectedShipment.tracking_number)}
                  disabled={checkingId === selectedShipment.tracking_number}
                >
                  <RefreshCw className={cn(
                    "h-4 w-4 mr-2",
                    checkingId === selectedShipment.tracking_number && "animate-spin"
                  )} />
                  Refresh Status
                </Button>
              </div>

              {/* Journey Progress */}
              <div className="p-4 bg-gradient-to-r from-blue-50 to-green-50 rounded-lg border">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs text-slate-600 font-medium">Shipment Journey</span>
                  {selectedShipment.estimated_delivery && selectedShipment.status !== 'delivered' && (
                    <span className="text-xs text-slate-500">
                      ETA: {format(new Date(selectedShipment.estimated_delivery), 'MMM d, yyyy')}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <div className="flex flex-col items-center">
                    <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center">
                      <Package className="h-4 w-4 text-white" />
                    </div>
                    <span className="text-xs text-slate-500 mt-1">Shipped</span>
                  </div>
                  <div className={cn(
                    "flex-1 h-1 rounded",
                    ['in_transit', 'out_for_delivery', 'delivered'].includes(selectedShipment.status)
                      ? "bg-blue-500"
                      : "bg-slate-200"
                  )} />
                  <div className="flex flex-col items-center">
                    <div className={cn(
                      "w-8 h-8 rounded-full flex items-center justify-center",
                      ['in_transit', 'out_for_delivery', 'delivered'].includes(selectedShipment.status)
                        ? "bg-blue-600"
                        : "bg-slate-200"
                    )}>
                      <Truck className={cn(
                        "h-4 w-4",
                        ['in_transit', 'out_for_delivery', 'delivered'].includes(selectedShipment.status)
                          ? "text-white"
                          : "text-slate-400"
                      )} />
                    </div>
                    <span className="text-xs text-slate-500 mt-1">In Transit</span>
                  </div>
                  <div className={cn(
                    "flex-1 h-1 rounded",
                    ['out_for_delivery', 'delivered'].includes(selectedShipment.status)
                      ? "bg-green-500"
                      : "bg-slate-200"
                  )} />
                  <div className="flex flex-col items-center">
                    <div className={cn(
                      "w-8 h-8 rounded-full flex items-center justify-center",
                      selectedShipment.status === 'delivered'
                        ? "bg-green-600"
                        : "bg-slate-200"
                    )}>
                      <CheckCircle className={cn(
                        "h-4 w-4",
                        selectedShipment.status === 'delivered' ? "text-white" : "text-slate-400"
                      )} />
                    </div>
                    <span className="text-xs text-slate-500 mt-1">Delivered</span>
                  </div>
                </div>
              </div>

              {/* Details Grid */}
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <div className="text-xs text-slate-500 flex items-center gap-1">
                    <User className="h-3 w-3" /> Customer
                  </div>
                  <div className="font-medium">{selectedShipment.customer_name || '-'}</div>
                </div>

                <div className="space-y-1">
                  <div className="text-xs text-slate-500 flex items-center gap-1">
                    <Mail className="h-3 w-3" /> Email
                  </div>
                  <div className="font-medium text-sm">{selectedShipment.customer_email}</div>
                </div>

                <div className="space-y-1">
                  <div className="text-xs text-slate-500 flex items-center gap-1">
                    <Truck className="h-3 w-3" /> Carrier
                  </div>
                  <div className="font-medium">{selectedShipment.carrier || 'Korea Post'}</div>
                </div>

                <div className="space-y-1">
                  <div className="text-xs text-slate-500 flex items-center gap-1">
                    <Globe className="h-3 w-3" /> Destination
                  </div>
                  <div className="font-medium">
                    {selectedShipment.delivery_address_city && `${selectedShipment.delivery_address_city}, `}
                    {selectedShipment.delivery_address_country || '-'}
                  </div>
                </div>

                <div className="space-y-1">
                  <div className="text-xs text-slate-500 flex items-center gap-1">
                    <Calendar className="h-3 w-3" /> Shipped
                  </div>
                  <div className="font-medium">
                    {selectedShipment.shipped_at
                      ? format(new Date(selectedShipment.shipped_at), 'MMM d, yyyy')
                      : '-'
                    }
                  </div>
                </div>

                <div className="space-y-1">
                  <div className="text-xs text-slate-500 flex items-center gap-1">
                    <Timer className="h-3 w-3" /> Delivered At
                  </div>
                  <div className="font-medium">
                    {selectedShipment.delivered_at
                      ? format(new Date(selectedShipment.delivered_at), 'MMM d, yyyy')
                      : selectedShipment.estimated_delivery
                        ? `ETA: ${format(new Date(selectedShipment.estimated_delivery), 'MMM d')}`
                        : '-'
                    }
                  </div>
                </div>
              </div>

              {/* Last Checkpoint */}
              {selectedShipment.last_checkpoint && (
                <div className="p-4 bg-blue-50 rounded-lg border border-blue-200">
                  <div className="text-xs text-blue-600 mb-1 flex items-center gap-1">
                    <MapPin className="h-3 w-3" /> Current Location
                  </div>
                  <div className="font-medium text-blue-900">{selectedShipment.last_checkpoint}</div>
                  {selectedShipment.last_checkpoint_time && (
                    <div className="text-sm text-blue-700 mt-1">
                      {format(new Date(selectedShipment.last_checkpoint_time), 'MMM d, yyyy h:mm a')} ({formatDistanceToNow(new Date(selectedShipment.last_checkpoint_time), { addSuffix: true })})
                    </div>
                  )}
                </div>
              )}

              {/* Items shipped */}
              {selectedShipment.line_items && (
                <div className="p-4 bg-slate-50 rounded-lg border">
                  <div className="text-xs text-slate-600 mb-2 flex items-center gap-1">
                    <Box className="h-3 w-3" /> Items in Shipment
                  </div>
                  <div className="text-sm text-slate-700">
                    {typeof selectedShipment.line_items === 'string'
                      ? selectedShipment.line_items.split(',').map((item, i) => (
                          <div key={i} className="flex items-center gap-2 py-1">
                            <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />
                            {item.trim()}
                          </div>
                        ))
                      : Array.isArray(selectedShipment.line_items)
                        ? selectedShipment.line_items.map((item, i) => (
                            <div key={i} className="flex items-center gap-2 py-1">
                              <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />
                              {item}
                            </div>
                          ))
                        : '-'
                    }
                  </div>
                </div>
              )}

              {/* Actions */}
              <div className="flex justify-between items-center pt-4 border-t">
                <a
                  href={getTrackingUrl(selectedShipment.tracking_number, selectedShipment.carrier)}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Button variant="outline">
                    <ExternalLink className="h-4 w-4 mr-2" />
                    Track on Carrier Site
                  </Button>
                </a>

                {selectedShipment.status === 'delivered' && !selectedShipment.delivery_followup_sent && (
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      onClick={() => handleMarkFollowup(selectedShipment.id)}
                    >
                      <CheckCircle className="h-4 w-4 mr-2" />
                      Mark Sent
                    </Button>
                    <Button
                      onClick={() => handlePreviewFollowup(selectedShipment)}
                      disabled={isSendingFollowup}
                      className="bg-amber-600 hover:bg-amber-700"
                    >
                      <Mail className={cn("h-4 w-4 mr-2", isSendingFollowup && "animate-pulse")} />
                      {isSendingFollowup ? 'Loading...' : 'Preview & Send Followup'}
                    </Button>
                  </div>
                )}

                {selectedShipment.delivery_followup_sent && (
                  <Badge className="bg-green-100 text-green-800">
                    <CheckCircle className="h-3 w-3 mr-1" />
                    Followup Sent
                  </Badge>
                )}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Followup Preview Dialog */}
      <Dialog open={followupDialogOpen} onOpenChange={setFollowupDialogOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Mail className="h-5 w-5 text-amber-600" />
              Preview Followup Email
            </DialogTitle>
            <DialogDescription>
              Review the email before sending to {followupPreview?.shipment?.customer_email}
            </DialogDescription>
          </DialogHeader>

          {followupPreview && (
            <div className="space-y-4">
              {/* To/From */}
              <div className="grid grid-cols-2 gap-4 p-3 bg-slate-50 rounded-lg text-sm">
                <div>
                  <span className="text-slate-500">To:</span>{' '}
                  <span className="font-medium">{followupPreview.shipment?.customer_email}</span>
                </div>
                <div>
                  <span className="text-slate-500">From:</span>{' '}
                  <span className="font-medium">Emma (emma@miraiskin.co)</span>
                </div>
              </div>

              {/* Subject */}
              <div className="p-3 bg-slate-50 rounded-lg">
                <div className="text-xs text-slate-500 mb-1">Subject</div>
                <div className="font-medium">{followupPreview.subject}</div>
              </div>

              {/* Body */}
              <div className="p-4 bg-white border border-slate-200 rounded-lg">
                <div className="whitespace-pre-wrap text-sm leading-relaxed">
                  {followupPreview.body}
                </div>
              </div>

              {/* Recommendations */}
              {followupPreview.recommendations && followupPreview.recommendations.length > 0 && (
                <div className="p-3 bg-amber-50 rounded-lg border border-amber-200">
                  <div className="text-xs text-amber-700 mb-2 font-medium">
                    Product Recommendations Mentioned
                  </div>
                  <div className="space-y-1">
                    {followupPreview.recommendations.map((rec, i) => (
                      <div key={i} className="text-sm flex items-center gap-2">
                        <Package className="h-3 w-3 text-amber-600" />
                        <span>{rec.name}</span>
                        <Badge variant="outline" className="text-xs">{rec.concern}</Badge>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Actions */}
              <div className="flex justify-end gap-3 pt-4 border-t">
                <Button
                  variant="outline"
                  onClick={() => setFollowupDialogOpen(false)}
                >
                  Cancel
                </Button>
                <Button
                  onClick={() => handleSendFollowup(followupPreview.shipment?.id)}
                  disabled={isSendingFollowup}
                  className="bg-amber-600 hover:bg-amber-700"
                >
                  <Send className={cn("h-4 w-4 mr-2", isSendingFollowup && "animate-pulse")} />
                  {isSendingFollowup ? 'Sending...' : 'Send Email'}
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
