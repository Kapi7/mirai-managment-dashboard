import React, { useState, useEffect, useMemo } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
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
  const [checkingId, setCheckingId] = useState(null);

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

      const response = await fetch(`${API_URL}/tracking/shipments?${params}`);
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
      const response = await fetch(`${API_URL}/tracking/stats`);
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

  // Check single tracking
  const handleCheckSingle = async (trackingNumber) => {
    setCheckingId(trackingNumber);
    try {
      const response = await fetch(`${API_URL}/tracking/check/${trackingNumber}`, {
        method: 'POST',
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
      });
      if (response.ok) {
        await fetchShipments();
        await fetchStats();
      }
    } catch (err) {
      console.error('Mark followup error:', err);
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
          <Button onClick={handleCheckAll} disabled={isChecking}>
            <Play className={cn("h-4 w-4 mr-2", isChecking && "animate-pulse")} />
            {isChecking ? 'Checking...' : 'Check All'}
          </Button>
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
                  <TableHead className="w-[100px]">Order</TableHead>
                  <TableHead>Customer</TableHead>
                  <TableHead>Tracking</TableHead>
                  <TableHead className="w-[120px]">Status</TableHead>
                  <TableHead>Last Update</TableHead>
                  <TableHead className="w-[100px]">Shipped</TableHead>
                  <TableHead className="w-[80px]"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredShipments.map((shipment) => (
                  <TableRow
                    key={shipment.id}
                    className={cn(
                      "cursor-pointer hover:bg-slate-50",
                      shipment.delay_detected && "bg-red-50 hover:bg-red-100"
                    )}
                    onClick={() => openDetail(shipment)}
                  >
                    <TableCell>
                      <span className="font-medium">#{shipment.order_number}</span>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col">
                        <span className="font-medium truncate max-w-[150px]">{shipment.customer_name || '-'}</span>
                        <span className="text-xs text-slate-500 truncate max-w-[150px]">{shipment.customer_email}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col">
                        <span className="font-mono text-xs">{shipment.tracking_number?.substring(0, 20)}...</span>
                        <span className="text-xs text-slate-500">{shipment.carrier || 'Korea Post'}</span>
                      </div>
                    </TableCell>
                    <TableCell>{getStatusBadge(shipment.status, shipment.delay_detected)}</TableCell>
                    <TableCell>
                      <div className="flex flex-col">
                        <span className="text-sm truncate max-w-[200px]">{shipment.last_checkpoint || '-'}</span>
                        {shipment.last_checkpoint_time && (
                          <span className="text-xs text-slate-500">
                            {formatDistanceToNow(new Date(shipment.last_checkpoint_time), { addSuffix: true })}
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <span className="text-xs text-slate-500">
                        {shipment.shipped_at ? formatDistanceToNow(new Date(shipment.shipped_at), { addSuffix: true }) : '-'}
                      </span>
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
                ))}
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
              {/* Status */}
              <div className="flex items-center justify-between p-4 bg-slate-50 rounded-lg">
                <div className="flex items-center gap-3">
                  {getStatusBadge(selectedShipment.status, selectedShipment.delay_detected)}
                  {selectedShipment.delay_detected && selectedShipment.delay_days > 0 && (
                    <span className="text-sm text-red-600">
                      {selectedShipment.delay_days} days delayed
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
                    <Timer className="h-3 w-3" /> ETA
                  </div>
                  <div className="font-medium">
                    {selectedShipment.estimated_delivery
                      ? format(new Date(selectedShipment.estimated_delivery), 'MMM d, yyyy')
                      : '-'
                    }
                  </div>
                </div>
              </div>

              {/* Last Checkpoint */}
              {selectedShipment.last_checkpoint && (
                <div className="p-4 bg-blue-50 rounded-lg border border-blue-200">
                  <div className="text-xs text-blue-600 mb-1 flex items-center gap-1">
                    <MapPin className="h-3 w-3" /> Last Checkpoint
                  </div>
                  <div className="font-medium text-blue-900">{selectedShipment.last_checkpoint}</div>
                  {selectedShipment.last_checkpoint_time && (
                    <div className="text-sm text-blue-700 mt-1">
                      {format(new Date(selectedShipment.last_checkpoint_time), 'MMM d, yyyy h:mm a')}
                    </div>
                  )}
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
                  <Button
                    onClick={() => handleMarkFollowup(selectedShipment.id)}
                    className="bg-amber-600 hover:bg-amber-700"
                  >
                    <Send className="h-4 w-4 mr-2" />
                    Mark Followup Sent
                  </Button>
                )}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
