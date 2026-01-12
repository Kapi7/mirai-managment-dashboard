import React, { useState, useEffect, useMemo } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Mail,
  MessageSquare,
  Clock,
  CheckCircle,
  XCircle,
  Send,
  RefreshCw,
  Search,
  AlertCircle,
  TrendingUp,
  User,
  Bot,
  Edit,
  Eye,
  Sparkles,
  BarChart3,
  Inbox,
  ChevronRight,
  ChevronDown,
  Target,
  Zap,
  Tag,
  Calendar,
  ShoppingCart,
  Package,
  Timer,
  FileCheck,
  Truck,
  DollarSign,
  RotateCcw,
  Archive,
  Flag,
  Users,
  MessageCircle,
  History,
  AlertTriangle,
  MapPin,
  ExternalLink
} from 'lucide-react';
import { format, formatDistanceToNow } from 'date-fns';
import { cn } from '@/lib/utils';

const API_URL = '/api';

export default function Support() {
  const [tickets, setTickets] = useState([]);
  const [selectedCustomer, setSelectedCustomer] = useState(null);
  const [customerDetails, setCustomerDetails] = useState(null);
  const [recentTrackings, setRecentTrackings] = useState([]);
  const [stats, setStats] = useState({
    pending: 0, draft_ready: 0, approved: 0, sent: 0, total: 0,
    classification_breakdown: {}, priority_breakdown: {}, intent_breakdown: {},
    sales_opportunities: 0, today_count: 0, yesterday_count: 0, week_count: 0,
    avg_confidence: null, resolution_rate: 0, ai_draft_rate: 0
  });
  const [loading, setLoading] = useState(true);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [showAnalytics, setShowAnalytics] = useState(false);
  const [showTrackings, setShowTrackings] = useState(false);
  const [error, setError] = useState(null);
  const [activeInbox, setActiveInbox] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [detailOpen, setDetailOpen] = useState(false);
  const [editDraft, setEditDraft] = useState('');
  const [manualResponse, setManualResponse] = useState('');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isSending, setIsSending] = useState(false);

  // Ticket resolution state
  const [resolution, setResolution] = useState('');
  const [resolutionNotes, setResolutionNotes] = useState('');
  const [isResolving, setIsResolving] = useState(false);

  // Regenerate state
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [userHints, setUserHints] = useState('');

  // Resolution options
  const resolutionOptions = [
    { value: 'resolved', label: 'Resolved', icon: CheckCircle, color: 'green' },
    { value: 'refunded', label: 'Refunded', icon: DollarSign, color: 'blue' },
    { value: 'replaced', label: 'Replaced', icon: RotateCcw, color: 'purple' },
    { value: 'waiting_customer', label: 'Waiting on Customer', icon: Clock, color: 'yellow' },
    { value: 'escalated', label: 'Escalated', icon: Flag, color: 'red' },
    { value: 'no_action_needed', label: 'No Action Needed', icon: Archive, color: 'slate' },
  ];

  // Fetch tickets (grouped by customer)
  const fetchTickets = async () => {
    try {
      const params = new URLSearchParams();
      if (activeInbox && activeInbox !== 'all') params.append('inbox_type', activeInbox);
      params.append('limit', '100');

      const response = await fetch(`${API_URL}/support/tickets?${params}`);
      if (!response.ok) throw new Error('Failed to fetch tickets');
      const data = await response.json();
      setTickets(data.tickets || []);
    } catch (err) {
      console.error('Failed to fetch tickets:', err);
      setError(err.message);
    }
  };

  // Fetch recent trackings
  const fetchRecentTrackings = async () => {
    try {
      const response = await fetch(`${API_URL}/support/recent-trackings?limit=10`);
      if (!response.ok) throw new Error('Failed to fetch trackings');
      const data = await response.json();
      setRecentTrackings(data.trackings || []);
    } catch (err) {
      console.error('Failed to fetch trackings:', err);
    }
  };

  // Fetch stats
  const fetchStats = async () => {
    try {
      const response = await fetch(`${API_URL}/support/stats`);
      if (!response.ok) throw new Error('Failed to fetch stats');
      const data = await response.json();
      setStats(data);
    } catch (err) {
      console.error('Failed to fetch stats:', err);
    }
  };

  // Fetch customer details
  const fetchCustomerDetails = async (email) => {
    setDetailsLoading(true);
    try {
      const response = await fetch(`${API_URL}/support/customer/${encodeURIComponent(email)}/details`);
      if (!response.ok) throw new Error('Failed to fetch customer details');
      const data = await response.json();
      setCustomerDetails(data);
      // Set the AI draft from the latest pending message
      const pendingDraft = data.summary?.pending_draft;
      if (pendingDraft) {
        setEditDraft(pendingDraft);
      } else {
        setEditDraft('');
      }
    } catch (err) {
      console.error('Failed to fetch customer details:', err);
      setError(err.message);
    } finally {
      setDetailsLoading(false);
    }
  };

  // Initial load
  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      await Promise.all([fetchTickets(), fetchStats(), fetchRecentTrackings()]);
      setLoading(false);
    };
    loadData();
  }, []);

  // Reload when filters change
  useEffect(() => {
    fetchTickets();
  }, [activeInbox]);

  // Refresh
  const handleRefresh = async () => {
    setIsRefreshing(true);
    await Promise.all([fetchTickets(), fetchStats(), fetchRecentTrackings()]);
    setIsRefreshing(false);
  };

  // Open customer detail view
  const openCustomerDetail = async (ticket) => {
    setSelectedCustomer(ticket);
    setManualResponse('');
    setUserHints('');
    setDetailOpen(true);
    await fetchCustomerDetails(ticket.customer_email);
  };

  // Approve email (send AI draft)
  const handleApprove = async () => {
    if (!customerDetails?.current_email_id) return;
    setIsSending(true);
    try {
      const response = await fetch(`${API_URL}/support/emails/${customerDetails.current_email_id}/approve`, {
        method: 'POST'
      });
      if (!response.ok) throw new Error('Failed to approve');
      await fetchCustomerDetails(selectedCustomer.customer_email);
      handleRefresh();
    } catch (err) {
      console.error('Failed to approve:', err);
    }
    setIsSending(false);
  };

  // Approve with edits
  const handleApproveWithEdits = async () => {
    if (!customerDetails?.current_email_id || !editDraft) return;
    setIsSending(true);
    try {
      const response = await fetch(`${API_URL}/support/emails/${customerDetails.current_email_id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ final_content: editDraft })
      });
      if (!response.ok) throw new Error('Failed to update');
      await fetchCustomerDetails(selectedCustomer.customer_email);
      handleRefresh();
    } catch (err) {
      console.error('Failed to update:', err);
    }
    setIsSending(false);
  };

  // Send manual response
  const handleSendManual = async () => {
    if (!customerDetails?.current_email_id || !manualResponse.trim()) return;
    setIsSending(true);
    try {
      const response = await fetch(`${API_URL}/support/emails/${customerDetails.current_email_id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ final_content: manualResponse, status: 'approved' })
      });
      if (!response.ok) throw new Error('Failed to send');
      await fetchCustomerDetails(selectedCustomer.customer_email);
      handleRefresh();
    } catch (err) {
      console.error('Failed to send:', err);
    }
    setIsSending(false);
  };

  // Reject email
  const handleReject = async () => {
    if (!customerDetails?.current_email_id) return;
    try {
      const response = await fetch(`${API_URL}/support/emails/${customerDetails.current_email_id}/reject`, {
        method: 'POST'
      });
      if (!response.ok) throw new Error('Failed to reject');
      await fetchCustomerDetails(selectedCustomer.customer_email);
      handleRefresh();
    } catch (err) {
      console.error('Failed to reject:', err);
    }
  };

  // Resolve ticket
  const handleResolveTicket = async (resolutionType) => {
    if (!customerDetails?.current_email_id) return;
    setIsResolving(true);
    try {
      const response = await fetch(`${API_URL}/support/emails/${customerDetails.current_email_id}/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          resolution: resolutionType,
          resolution_notes: resolutionNotes,
        }),
      });
      if (!response.ok) throw new Error('Failed to resolve ticket');
      await fetchCustomerDetails(selectedCustomer.customer_email);
      await fetchTickets();
    } catch (err) {
      console.error('Failed to resolve ticket:', err);
      setError(err.message);
    } finally {
      setIsResolving(false);
    }
  };

  // Regenerate AI response
  const handleRegenerateAI = async (withHints = false) => {
    if (!customerDetails?.current_email_id) return;
    setIsRegenerating(true);
    try {
      const requestBody = withHints && userHints.trim()
        ? { user_hints: userHints.trim() }
        : {};

      const response = await fetch(`${API_URL}/support/emails/${customerDetails.current_email_id}/regenerate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody)
      });
      const data = await response.json();
      if (data.success) {
        if (withHints) setUserHints('');
        setTimeout(() => {
          fetchCustomerDetails(selectedCustomer.customer_email);
          handleRefresh();
        }, 2000);
      } else {
        console.error('Failed to regenerate:', data.error);
        alert(`Failed to generate AI response: ${data.error || 'Unknown error'}`);
      }
    } catch (err) {
      console.error('Failed to regenerate:', err);
      alert('Failed to generate AI response. Please try again.');
    }
    setIsRegenerating(false);
  };

  // Parse email content to extract the latest message
  const parseEmailContent = (content) => {
    if (!content) return '';

    let cleaned = content
      .replace(/<[^>]*>/g, '')
      .replace(/\r\n/g, '\n')
      .replace(/\n{3,}/g, '\n\n');

    // Extract just the latest message (before quotes)
    const onWroteMatch = cleaned.match(/^([\s\S]*?)(?=On .{10,80}wrote:)/i);
    if (onWroteMatch && onWroteMatch[1].trim().length > 10) {
      return onWroteMatch[1].trim();
    }

    // Truncate if too long
    if (cleaned.length > 500) {
      return cleaned.substring(0, 500) + '...';
    }

    return cleaned;
  };

  // Status badge for tickets
  const getTicketStatusBadge = (status) => {
    const variants = {
      needs_attention: { icon: AlertCircle, label: 'Needs Attention', color: 'text-red-600 bg-red-50' },
      pending: { icon: Clock, label: 'Pending', color: 'text-yellow-600 bg-yellow-50' },
      draft_ready: { icon: Bot, label: 'Draft Ready', color: 'text-blue-600 bg-blue-50' },
      resolved: { icon: CheckCircle, label: 'Resolved', color: 'text-green-600 bg-green-50' },
      sent: { icon: Send, label: 'Sent', color: 'text-indigo-600 bg-indigo-50' },
    };
    const config = variants[status] || variants.pending;
    const Icon = config.icon;
    return (
      <Badge className={cn("flex items-center gap-1 text-xs", config.color)}>
        <Icon className="h-3 w-3" />
        {config.label}
      </Badge>
    );
  };

  // Tracking status badge
  const getTrackingStatusBadge = (status) => {
    const variants = {
      pending: { color: 'bg-gray-100 text-gray-700', label: 'Pending' },
      in_transit: { color: 'bg-blue-100 text-blue-700', label: 'In Transit' },
      out_for_delivery: { color: 'bg-purple-100 text-purple-700', label: 'Out for Delivery' },
      delivered: { color: 'bg-green-100 text-green-700', label: 'Delivered' },
      exception: { color: 'bg-red-100 text-red-700', label: 'Exception' },
      expired: { color: 'bg-orange-100 text-orange-700', label: 'Expired' },
    };
    const config = variants[status] || { color: 'bg-gray-100', label: status };
    return <Badge className={cn('text-xs', config.color)}>{config.label}</Badge>;
  };

  // Filter tickets
  const filteredTickets = useMemo(() => {
    let result = tickets;

    // Filter by search
    if (search.trim()) {
      const s = search.toLowerCase();
      result = result.filter(t =>
        t.customer_email?.toLowerCase().includes(s) ||
        t.customer_name?.toLowerCase().includes(s) ||
        t.latest_subject?.toLowerCase().includes(s) ||
        t.order_number?.toLowerCase().includes(s)
      );
    }

    // Filter by status
    if (statusFilter && statusFilter !== 'all') {
      if (statusFilter === 'pending' || statusFilter === 'draft_ready') {
        result = result.filter(t => t.ticket_status === 'needs_attention' || t.latest_status === statusFilter);
      } else {
        result = result.filter(t => t.latest_status === statusFilter);
      }
    }

    return result;
  }, [tickets, search, statusFilter]);

  // Count tickets needing attention
  const needsAttentionCount = useMemo(() => {
    return tickets.filter(t => t.ticket_status === 'needs_attention').length;
  }, [tickets]);

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">Support Tickets</h1>
          <p className="text-slate-500 mt-1">
            Customer cases grouped by conversation
            {needsAttentionCount > 0 && (
              <Badge className="ml-2 bg-red-100 text-red-700">
                {needsAttentionCount} need attention
              </Badge>
            )}
          </p>
        </div>
        <Button onClick={handleRefresh} disabled={isRefreshing}>
          <RefreshCw className={cn("h-4 w-4 mr-2", isRefreshing && "animate-spin")} />
          Refresh
        </Button>
      </div>

      {/* Inbox Tabs */}
      <div className="flex items-center gap-4 border-b border-slate-200 pb-4">
        <Tabs value={activeInbox} onValueChange={setActiveInbox} className="w-full">
          <TabsList className="grid w-full max-w-md grid-cols-3">
            <TabsTrigger value="all" className="flex items-center gap-2">
              <Inbox className="h-4 w-4" />
              All Tickets
            </TabsTrigger>
            <TabsTrigger value="emma" className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-pink-500" />
              Emma (Sales)
            </TabsTrigger>
            <TabsTrigger value="support" className="flex items-center gap-2">
              <MessageSquare className="h-4 w-4 text-blue-500" />
              Support
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-5 gap-3">
        {[
          { key: 'all', label: 'Total Tickets', value: tickets.length, color: 'slate', icon: Users },
          { key: 'pending', label: 'Pending', value: stats.pending, color: 'yellow', icon: Clock },
          { key: 'draft_ready', label: 'Draft Ready', value: stats.draft_ready, color: 'blue', icon: Bot },
          { key: 'sent', label: 'Sent', value: stats.sent, color: 'green', icon: Send },
          { key: 'today', label: 'Today', value: stats.today_count, color: 'indigo', icon: Calendar },
        ].map(({ key, label, value, color, icon: Icon }) => (
          <Card
            key={key}
            className={cn(
              "cursor-pointer hover:shadow-md transition-shadow",
              statusFilter === key && `ring-2 ring-${color}-500`
            )}
            onClick={() => setStatusFilter(statusFilter === key ? 'all' : key)}
          >
            <CardContent className="p-3">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-slate-500">{label}</p>
                  <p className={`text-xl font-bold text-${color}-600`}>{value || 0}</p>
                </div>
                <Icon className={`h-5 w-5 text-${color}-500`} />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Recent Trackings Collapse */}
      <Card>
        <CardHeader
          className="cursor-pointer hover:bg-slate-50 transition-colors py-3"
          onClick={() => setShowTrackings(!showTrackings)}
        >
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base">
              <Truck className="h-4 w-4" />
              Recent Shipment Tracking
              <Badge variant="secondary">{recentTrackings.length}</Badge>
            </CardTitle>
            <Button variant="ghost" size="sm">
              {showTrackings ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            </Button>
          </div>
        </CardHeader>
        {showTrackings && (
          <CardContent className="pt-0">
            {recentTrackings.length === 0 ? (
              <p className="text-sm text-slate-500 text-center py-4">No recent trackings</p>
            ) : (
              <div className="space-y-2">
                {recentTrackings.map((tracking) => (
                  <div key={tracking.id} className="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
                    <div className="flex items-center gap-3">
                      <Truck className="h-4 w-4 text-slate-400" />
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-sm">{tracking.tracking_number}</span>
                          {getTrackingStatusBadge(tracking.status)}
                          {tracking.delay_detected && (
                            <Badge className="bg-red-100 text-red-700 text-xs">
                              <AlertTriangle className="h-3 w-3 mr-1" />
                              Delayed
                            </Badge>
                          )}
                        </div>
                        <div className="text-xs text-slate-500 mt-1">
                          {tracking.customer_name || tracking.customer_email}
                          {tracking.order_number && ` • Order ${tracking.order_number}`}
                        </div>
                      </div>
                    </div>
                    <div className="text-right text-xs text-slate-500">
                      {tracking.last_checkpoint && (
                        <div className="flex items-center gap-1 mb-1">
                          <MapPin className="h-3 w-3" />
                          {tracking.last_checkpoint.substring(0, 40)}
                        </div>
                      )}
                      {tracking.last_checked && (
                        <div>Updated {formatDistanceToNow(new Date(tracking.last_checked), { addSuffix: true })}</div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        )}
      </Card>

      {/* Analytics Collapse */}
      <Card>
        <CardHeader
          className="cursor-pointer hover:bg-slate-50 transition-colors py-3"
          onClick={() => setShowAnalytics(!showAnalytics)}
        >
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base">
              <BarChart3 className="h-4 w-4" />
              Analytics & Insights
            </CardTitle>
            <Button variant="ghost" size="sm">
              {showAnalytics ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            </Button>
          </div>
        </CardHeader>
        {showAnalytics && (
          <CardContent className="pt-0">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              {/* Activity */}
              <div className="p-3 bg-slate-50 rounded-lg">
                <div className="flex items-center gap-2 mb-2">
                  <Calendar className="h-4 w-4 text-slate-600" />
                  <span className="font-semibold text-sm">Activity</span>
                </div>
                <div className="space-y-1 text-sm">
                  <div className="flex justify-between">
                    <span className="text-slate-600">Today</span>
                    <span className="font-bold">{stats.today_count}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-600">Yesterday</span>
                    <span>{stats.yesterday_count}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-600">Last 7 days</span>
                    <span>{stats.week_count}</span>
                  </div>
                </div>
              </div>

              {/* Classification */}
              <div className="p-3 bg-slate-50 rounded-lg">
                <div className="flex items-center gap-2 mb-2">
                  <Tag className="h-4 w-4 text-slate-600" />
                  <span className="font-semibold text-sm">Classification</span>
                </div>
                <div className="space-y-1 text-sm">
                  {Object.entries(stats.classification_breakdown || {}).map(([key, value]) => (
                    <div key={key} className="flex justify-between items-center">
                      <span className="text-slate-600 capitalize">{key === 'support_sales' ? 'Support+Sales' : key}</span>
                      <Badge className="text-xs">{value}</Badge>
                    </div>
                  ))}
                </div>
              </div>

              {/* Performance */}
              <div className="p-3 bg-slate-50 rounded-lg">
                <div className="flex items-center gap-2 mb-2">
                  <Zap className="h-4 w-4 text-slate-600" />
                  <span className="font-semibold text-sm">Performance</span>
                </div>
                <div className="space-y-1 text-sm">
                  <div className="flex justify-between">
                    <span className="text-slate-600">Resolution Rate</span>
                    <span className="font-bold text-green-600">{stats.resolution_rate}%</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-600">AI Draft Rate</span>
                    <span>{stats.ai_draft_rate}%</span>
                  </div>
                </div>
              </div>

              {/* Intents */}
              <div className="p-3 bg-slate-50 rounded-lg">
                <div className="flex items-center gap-2 mb-2">
                  <Target className="h-4 w-4 text-slate-600" />
                  <span className="font-semibold text-sm">Top Intents</span>
                </div>
                <div className="space-y-1 text-sm">
                  {Object.entries(stats.intent_breakdown || {}).slice(0, 3).map(([key, value]) => (
                    <div key={key} className="flex justify-between">
                      <span className="text-slate-600 capitalize truncate">{key.replace('_', ' ')}</span>
                      <span>{value}</span>
                    </div>
                  ))}
                  {stats.sales_opportunities > 0 && (
                    <div className="flex justify-between pt-1 border-t">
                      <span className="text-amber-700 flex items-center gap-1">
                        <ShoppingCart className="h-3 w-3" />
                        Sales Opps
                      </span>
                      <Badge className="bg-amber-100 text-amber-800 text-xs">{stats.sales_opportunities}</Badge>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </CardContent>
        )}
      </Card>

      {/* Customer Tickets List */}
      <Card>
        <CardHeader className="py-3">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base">
              <Users className="h-4 w-4" />
              Customer Tickets
              <Badge variant="secondary">{filteredTickets.length}</Badge>
            </CardTitle>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
              <Input
                placeholder="Search customers, orders..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-[250px] pl-9 h-8"
              />
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-4 space-y-2">
              {[1, 2, 3].map(i => <Skeleton key={i} className="h-16 w-full" />)}
            </div>
          ) : filteredTickets.length === 0 ? (
            <div className="text-center py-12 text-slate-500">
              <Users className="h-12 w-12 mx-auto mb-3 opacity-30" />
              <p className="font-medium">No tickets found</p>
              <p className="text-sm">Customer inquiries will appear here</p>
            </div>
          ) : (
            <div className="divide-y">
              {filteredTickets.map((ticket) => (
                <div
                  key={ticket.customer_email}
                  className="p-4 hover:bg-slate-50 cursor-pointer transition-colors"
                  onClick={() => openCustomerDetail(ticket)}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      {/* Customer info row */}
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-semibold text-slate-900">
                          {ticket.customer_name}
                        </span>
                        {getTicketStatusBadge(ticket.ticket_status)}
                        {ticket.has_pending_draft && (
                          <Badge className="bg-purple-100 text-purple-700 text-xs">
                            <Sparkles className="h-3 w-3 mr-1" />
                            AI Draft
                          </Badge>
                        )}
                      </div>
                      <p className="text-sm text-slate-500 mb-2">{ticket.customer_email}</p>

                      {/* Latest subject */}
                      <p className="text-sm text-slate-700 truncate max-w-[500px]">
                        {ticket.latest_subject}
                      </p>

                      {/* Meta info */}
                      <div className="flex items-center gap-4 mt-2 text-xs text-slate-500">
                        <span className="flex items-center gap-1">
                          <MessageCircle className="h-3 w-3" />
                          {ticket.message_count} message{ticket.message_count !== 1 ? 's' : ''}
                        </span>
                        {ticket.order_number && (
                          <span className="flex items-center gap-1">
                            <ShoppingCart className="h-3 w-3" />
                            Order {ticket.order_number}
                          </span>
                        )}
                        {ticket.tracking_status && (
                          <span className="flex items-center gap-1">
                            <Truck className="h-3 w-3" />
                            {ticket.tracking_status}
                          </span>
                        )}
                        {ticket.intents && ticket.intents.length > 0 && (
                          <span className="flex items-center gap-1">
                            <Target className="h-3 w-3" />
                            {ticket.intents.join(', ')}
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="text-right ml-4">
                      <div className="text-xs text-slate-500">
                        {ticket.last_activity && formatDistanceToNow(new Date(ticket.last_activity), { addSuffix: true })}
                      </div>
                      <Button variant="ghost" size="sm" className="mt-2">
                        <Eye className="h-4 w-4 mr-1" />
                        View
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Customer Detail Dialog */}
      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="max-w-5xl max-h-[90vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <User className="h-5 w-5" />
              {selectedCustomer?.customer_name || selectedCustomer?.customer_email}
            </DialogTitle>
            <DialogDescription>
              {selectedCustomer?.customer_email}
              {customerDetails && (
                <span className="ml-2">
                  • {customerDetails.total_messages} messages across {customerDetails.total_threads} thread{customerDetails.total_threads !== 1 ? 's' : ''}
                </span>
              )}
            </DialogDescription>
          </DialogHeader>

          {detailsLoading ? (
            <div className="flex-1 flex items-center justify-center">
              <RefreshCw className="h-8 w-8 animate-spin text-slate-400" />
            </div>
          ) : customerDetails ? (
            <div className="flex-1 overflow-hidden flex gap-4">
              {/* Left side: Conversation */}
              <div className="flex-1 flex flex-col overflow-hidden">
                {/* Quick Info Bar */}
                <div className="grid grid-cols-4 gap-2 mb-4">
                  <div className="p-2 bg-slate-50 rounded-lg">
                    <div className="text-xs text-slate-500">Status</div>
                    <div className="font-medium text-sm">{getTicketStatusBadge(customerDetails.current_status)}</div>
                  </div>
                  <div className="p-2 bg-slate-50 rounded-lg">
                    <div className="text-xs text-slate-500">Orders</div>
                    <div className="font-medium text-sm">
                      {customerDetails.summary?.order_numbers?.join(', ') || 'None'}
                    </div>
                  </div>
                  <div className="p-2 bg-slate-50 rounded-lg">
                    <div className="text-xs text-slate-500">First Contact</div>
                    <div className="font-medium text-sm">
                      {customerDetails.first_contact ? format(new Date(customerDetails.first_contact), 'MMM d, yyyy') : '-'}
                    </div>
                  </div>
                  <div className="p-2 bg-slate-50 rounded-lg">
                    <div className="text-xs text-slate-500">Tracking</div>
                    <div className="font-medium text-sm">
                      {customerDetails.trackings?.length > 0
                        ? getTrackingStatusBadge(customerDetails.trackings[0].status)
                        : <span className="text-slate-400">No tracking</span>
                      }
                    </div>
                  </div>
                </div>

                {/* Conversation Timeline */}
                <div className="flex-1 overflow-y-auto space-y-3 pr-2">
                  <h4 className="font-semibold flex items-center gap-2 text-slate-700 sticky top-0 bg-white py-2">
                    <History className="h-4 w-4" />
                    Full Conversation Timeline
                  </h4>
                  {customerDetails.all_messages?.map((msg, idx) => (
                    <div
                      key={idx}
                      className={cn(
                        "p-3 rounded-lg",
                        msg.direction === 'inbound'
                          ? 'bg-white border border-slate-200 mr-8'
                          : 'bg-blue-50 border border-blue-200 ml-8'
                      )}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <div className={cn(
                            "w-6 h-6 rounded-full flex items-center justify-center text-xs",
                            msg.direction === 'inbound' ? 'bg-slate-200' : 'bg-blue-200'
                          )}>
                            {msg.direction === 'inbound' ? (
                              <User className="h-3 w-3 text-slate-600" />
                            ) : (
                              <Bot className="h-3 w-3 text-blue-600" />
                            )}
                          </div>
                          <span className="font-medium text-sm">
                            {msg.direction === 'inbound'
                              ? (msg.sender_name || customerDetails.customer_name || 'Customer')
                              : 'Emma (Mirai Support)'
                            }
                          </span>
                          {msg.thread_subject && (
                            <span className="text-xs text-slate-400 truncate max-w-[200px]">
                              Re: {msg.thread_subject}
                            </span>
                          )}
                        </div>
                        <span className="text-xs text-slate-400">
                          {msg.created_at ? format(new Date(msg.created_at), 'MMM d, h:mm a') : ''}
                        </span>
                      </div>
                      <div className="text-sm text-slate-700 whitespace-pre-wrap leading-relaxed">
                        {parseEmailContent(msg.content)}
                      </div>

                      {/* AI Draft */}
                      {msg.ai_draft && !msg.sent_at && (
                        <div className="mt-3 p-3 bg-gradient-to-r from-purple-50 to-blue-50 rounded-lg border border-purple-200">
                          <div className="flex items-center gap-2 mb-2">
                            <Sparkles className="h-4 w-4 text-purple-600" />
                            <span className="font-medium text-sm text-purple-700">Emma's Draft</span>
                            <Badge className="bg-purple-100 text-purple-700 text-xs">Ready for Review</Badge>
                          </div>
                          <div className="text-sm whitespace-pre-wrap">{msg.ai_draft}</div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {/* Right side: Actions & Tracking */}
              <div className="w-80 flex flex-col space-y-4 overflow-y-auto">
                {/* Tracking Info */}
                {customerDetails.trackings && customerDetails.trackings.length > 0 && (
                  <Card>
                    <CardHeader className="py-2 px-3">
                      <CardTitle className="text-sm flex items-center gap-2">
                        <Truck className="h-4 w-4" />
                        Shipment Tracking
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="px-3 pb-3 space-y-2">
                      {customerDetails.trackings.slice(0, 3).map((t) => (
                        <div key={t.id} className="p-2 bg-slate-50 rounded text-xs">
                          <div className="flex items-center justify-between mb-1">
                            <span className="font-mono">{t.tracking_number.substring(0, 20)}...</span>
                            {getTrackingStatusBadge(t.status)}
                          </div>
                          {t.last_checkpoint && (
                            <div className="text-slate-500 truncate">{t.last_checkpoint}</div>
                          )}
                          {t.estimated_delivery && (
                            <div className="text-slate-500 mt-1">
                              Est. delivery: {format(new Date(t.estimated_delivery), 'MMM d')}
                            </div>
                          )}
                        </div>
                      ))}
                    </CardContent>
                  </Card>
                )}

                {/* Action Section */}
                {customerDetails.summary?.has_pending_response && (
                  <Card className="border-green-200 bg-green-50">
                    <CardHeader className="py-3 px-4">
                      <CardTitle className="text-base flex items-center gap-2 text-green-800">
                        <CheckCircle className="h-5 w-5" />
                        Ready to Respond
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="px-4 pb-4 space-y-4">
                      {/* Regenerate with hints - More prominent */}
                      <div className="space-y-2 p-3 bg-purple-50 rounded-lg border border-purple-200">
                        <label className="text-sm font-medium text-purple-800 flex items-center gap-2">
                          <Sparkles className="h-4 w-4" />
                          Regenerate with guidance:
                        </label>
                        <Textarea
                          value={userHints}
                          onChange={(e) => setUserHints(e.target.value)}
                          placeholder="e.g., 'Process the refund immediately', 'Be more apologetic', 'Don't try to sell anything'"
                          className="bg-white text-sm min-h-[80px]"
                          rows={3}
                        />
                        <Button
                          onClick={() => handleRegenerateAI(userHints.trim() ? true : false)}
                          disabled={isRegenerating}
                          variant="outline"
                          className="w-full border-purple-400 text-purple-700 hover:bg-purple-100"
                        >
                          <Sparkles className="h-4 w-4 mr-2" />
                          {isRegenerating ? 'Regenerating...' : 'Regenerate AI Response'}
                        </Button>
                      </div>

                      {/* Edit draft - Larger */}
                      <div className="space-y-2">
                        <label className="text-sm font-medium text-green-800">Edit draft before sending:</label>
                        <Textarea
                          value={editDraft}
                          onChange={(e) => setEditDraft(e.target.value)}
                          rows={10}
                          placeholder="Edit the AI draft..."
                          className="bg-white text-sm min-h-[200px]"
                        />
                      </div>

                      {/* Action buttons */}
                      <div className="flex gap-3 pt-2">
                        <Button
                          variant="destructive"
                          onClick={handleReject}
                          disabled={isSending}
                          className="flex-1"
                        >
                          <XCircle className="h-4 w-4 mr-2" />
                          Reject
                        </Button>
                        <Button
                          onClick={editDraft !== customerDetails.summary?.pending_draft ? handleApproveWithEdits : handleApprove}
                          disabled={isSending}
                          className="flex-1 bg-green-600 hover:bg-green-700"
                        >
                          <Send className="h-4 w-4 mr-2" />
                          {isSending ? 'Sending...' : 'Send Response'}
                        </Button>
                      </div>
                    </CardContent>
                  </Card>
                )}

                {/* Manual response if no draft */}
                {!customerDetails.summary?.has_pending_response && customerDetails.current_status !== 'resolved' && (
                  <Card>
                    <CardHeader className="py-3 px-4">
                      <CardTitle className="text-base flex items-center gap-2">
                        <Edit className="h-5 w-5" />
                        Write Response
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="px-4 pb-4 space-y-4">
                      {/* Generate AI option */}
                      <div className="space-y-2 p-3 bg-purple-50 rounded-lg border border-purple-200">
                        <label className="text-sm font-medium text-purple-800 flex items-center gap-2">
                          <Sparkles className="h-4 w-4" />
                          Generate AI Response with guidance:
                        </label>
                        <Textarea
                          value={userHints}
                          onChange={(e) => setUserHints(e.target.value)}
                          placeholder="e.g., 'Process refund', 'Be apologetic', 'Check tracking status'"
                          className="bg-white text-sm min-h-[60px]"
                          rows={2}
                        />
                        <Button
                          onClick={() => handleRegenerateAI(userHints.trim() ? true : false)}
                          disabled={isRegenerating}
                          variant="outline"
                          className="w-full border-purple-400 text-purple-700 hover:bg-purple-100"
                        >
                          <Sparkles className="h-4 w-4 mr-2" />
                          {isRegenerating ? 'Generating...' : 'Generate AI Response'}
                        </Button>
                      </div>

                      {/* Manual response */}
                      <div className="space-y-2">
                        <label className="text-sm font-medium">Or write manually:</label>
                        <Textarea
                          value={manualResponse}
                          onChange={(e) => setManualResponse(e.target.value)}
                          rows={8}
                          placeholder="Type your response..."
                          className="text-sm min-h-[150px]"
                        />
                      </div>
                      {manualResponse.trim() && (
                        <Button
                          onClick={handleSendManual}
                          disabled={isSending}
                          className="w-full"
                        >
                          <Send className="h-4 w-4 mr-2" />
                          Send Response
                        </Button>
                      )}
                    </CardContent>
                  </Card>
                )}

                {/* Resolve Ticket */}
                <Card>
                  <CardHeader className="py-2 px-3">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <FileCheck className="h-4 w-4" />
                      Resolve Ticket
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="px-3 pb-3 space-y-2">
                    <div className="grid grid-cols-2 gap-1">
                      {resolutionOptions.map((opt) => (
                        <Button
                          key={opt.value}
                          variant="outline"
                          size="sm"
                          onClick={() => handleResolveTicket(opt.value)}
                          disabled={isResolving}
                          className="justify-start h-auto py-1.5 px-2 text-xs"
                        >
                          <opt.icon className={`h-3 w-3 mr-1 text-${opt.color}-600`} />
                          {opt.label}
                        </Button>
                      ))}
                    </div>
                    <Input
                      value={resolutionNotes}
                      onChange={(e) => setResolutionNotes(e.target.value)}
                      placeholder="Resolution notes..."
                      className="text-xs h-8"
                    />
                  </CardContent>
                </Card>
              </div>
            </div>
          ) : null}

          <DialogFooter className="mt-4">
            <Button variant="outline" onClick={() => setDetailOpen(false)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
