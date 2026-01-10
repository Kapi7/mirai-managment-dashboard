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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
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
  ShoppingCart
} from 'lucide-react';
import { format, formatDistanceToNow } from 'date-fns';
import { cn } from '@/lib/utils';

const API_URL = '/api';

export default function Support() {
  const [emails, setEmails] = useState([]);
  const [stats, setStats] = useState({
    pending: 0, draft_ready: 0, approved: 0, sent: 0, total: 0,
    classification_breakdown: {}, priority_breakdown: {}, intent_breakdown: {},
    sales_opportunities: 0, today_count: 0, yesterday_count: 0, week_count: 0,
    avg_confidence: null, resolution_rate: 0, ai_draft_rate: 0
  });
  const [loading, setLoading] = useState(true);
  const [showAnalytics, setShowAnalytics] = useState(false);
  const [error, setError] = useState(null);
  const [activeInbox, setActiveInbox] = useState('all'); // 'all', 'emma', 'support'
  const [statusFilter, setStatusFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [selectedEmail, setSelectedEmail] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [editDraft, setEditDraft] = useState('');
  const [manualResponse, setManualResponse] = useState('');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isSending, setIsSending] = useState(false);

  // Fetch emails
  const fetchEmails = async () => {
    try {
      const params = new URLSearchParams();
      if (statusFilter && statusFilter !== 'all') params.append('status', statusFilter);
      if (activeInbox && activeInbox !== 'all') params.append('inbox_type', activeInbox);
      params.append('limit', '100');

      const response = await fetch(`${API_URL}/support/emails?${params}`);
      if (!response.ok) throw new Error('Failed to fetch emails');
      const data = await response.json();
      setEmails(data.emails || []);
    } catch (err) {
      console.error('Failed to fetch emails:', err);
      setError(err.message);
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

  // Initial load
  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      await Promise.all([fetchEmails(), fetchStats()]);
      setLoading(false);
    };
    loadData();
  }, []);

  // Reload when filters change
  useEffect(() => {
    fetchEmails();
  }, [activeInbox, statusFilter]);

  // Refresh
  const handleRefresh = async () => {
    setIsRefreshing(true);
    await Promise.all([fetchEmails(), fetchStats()]);
    setIsRefreshing(false);
  };

  // Open email detail
  const openEmailDetail = async (email) => {
    try {
      const response = await fetch(`${API_URL}/support/emails/${email.id}`);
      if (!response.ok) throw new Error('Failed to fetch email details');
      const data = await response.json();
      setSelectedEmail(data);
      setEditDraft(data.messages?.find(m => m.ai_draft)?.ai_draft || '');
      setManualResponse('');
      setDetailOpen(true);
    } catch (err) {
      console.error('Failed to fetch email:', err);
    }
  };

  // Approve email (send AI draft)
  const handleApprove = async () => {
    if (!selectedEmail) return;
    setIsSending(true);
    try {
      const response = await fetch(`${API_URL}/support/emails/${selectedEmail.id}/approve`, {
        method: 'POST'
      });
      if (!response.ok) throw new Error('Failed to approve');
      setDetailOpen(false);
      handleRefresh();
    } catch (err) {
      console.error('Failed to approve:', err);
    }
    setIsSending(false);
  };

  // Approve with edits
  const handleApproveWithEdits = async () => {
    if (!selectedEmail || !editDraft) return;
    setIsSending(true);
    try {
      const response = await fetch(`${API_URL}/support/emails/${selectedEmail.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ final_content: editDraft })
      });
      if (!response.ok) throw new Error('Failed to update');
      setDetailOpen(false);
      handleRefresh();
    } catch (err) {
      console.error('Failed to update:', err);
    }
    setIsSending(false);
  };

  // Send manual response
  const handleSendManual = async () => {
    if (!selectedEmail || !manualResponse.trim()) return;
    setIsSending(true);
    try {
      const response = await fetch(`${API_URL}/support/emails/${selectedEmail.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ final_content: manualResponse, status: 'approved' })
      });
      if (!response.ok) throw new Error('Failed to send');
      setDetailOpen(false);
      handleRefresh();
    } catch (err) {
      console.error('Failed to send:', err);
    }
    setIsSending(false);
  };

  // Reject email
  const handleReject = async () => {
    if (!selectedEmail) return;
    try {
      const response = await fetch(`${API_URL}/support/emails/${selectedEmail.id}/reject`, {
        method: 'POST'
      });
      if (!response.ok) throw new Error('Failed to reject');
      setDetailOpen(false);
      handleRefresh();
    } catch (err) {
      console.error('Failed to reject:', err);
    }
  };

  // Filter emails by search
  const filteredEmails = useMemo(() => {
    if (!search.trim()) return emails;
    const s = search.toLowerCase();
    return emails.filter(e =>
      e.customer_email?.toLowerCase().includes(s) ||
      e.customer_name?.toLowerCase().includes(s) ||
      e.subject?.toLowerCase().includes(s)
    );
  }, [emails, search]);

  // Status badge
  const getStatusBadge = (status) => {
    const variants = {
      pending: { icon: Clock, label: 'Pending', color: 'text-yellow-600 bg-yellow-50' },
      draft_ready: { icon: Bot, label: 'AI Ready', color: 'text-blue-600 bg-blue-50' },
      approved: { icon: CheckCircle, label: 'Approved', color: 'text-green-600 bg-green-50' },
      sent: { icon: Send, label: 'Sent', color: 'text-indigo-600 bg-indigo-50' },
      rejected: { icon: XCircle, label: 'Rejected', color: 'text-red-600 bg-red-50' }
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

  // Classification badge
  const getClassificationBadge = (classification) => {
    if (!classification) return null;
    const colors = {
      support: 'bg-blue-100 text-blue-800',
      sales: 'bg-green-100 text-green-800',
      support_sales: 'bg-purple-100 text-purple-800'
    };
    return (
      <Badge className={cn('text-xs', colors[classification] || 'bg-gray-100')}>
        {classification === 'support_sales' ? 'Support+Sales' : classification}
      </Badge>
    );
  };

  // Priority badge
  const getPriorityBadge = (priority) => {
    if (!priority) return null;
    const colors = {
      high: 'bg-red-100 text-red-800',
      medium: 'bg-yellow-100 text-yellow-800',
      low: 'bg-gray-100 text-gray-800'
    };
    return (
      <Badge className={cn('text-xs', colors[priority] || 'bg-gray-100')}>
        {priority}
      </Badge>
    );
  };

  // Inbox badge
  const getInboxBadge = (inboxType) => {
    if (!inboxType) return null;
    return (
      <Badge className={cn('text-xs', inboxType === 'emma' ? 'bg-pink-100 text-pink-800' : 'bg-slate-100 text-slate-800')}>
        {inboxType === 'emma' ? 'Emma' : 'Support'}
      </Badge>
    );
  };

  // Check if email has AI draft
  const hasAIDraft = (email) => {
    return email?.messages?.some(m => m.ai_draft);
  };

  // Count emails by inbox
  const inboxCounts = useMemo(() => {
    const all = emails.length;
    // Since we're fetching filtered, we need to estimate from stats or just show totals
    return { all, emma: 0, support: 0 };
  }, [emails]);

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">Email Inbox</h1>
          <p className="text-slate-500 mt-1">Manage Emma Sales and Support emails</p>
        </div>
        <Button onClick={handleRefresh} disabled={isRefreshing}>
          <RefreshCw className={cn("h-4 w-4 mr-2", isRefreshing && "animate-spin")} />
          Refresh
        </Button>
      </div>

      {/* Inbox Selector Tabs */}
      <div className="flex items-center gap-4 border-b border-slate-200 pb-4">
        <Tabs value={activeInbox} onValueChange={setActiveInbox} className="w-full">
          <TabsList className="grid w-full max-w-md grid-cols-3">
            <TabsTrigger value="all" className="flex items-center gap-2">
              <Inbox className="h-4 w-4" />
              All Emails
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

      {/* Quick Stats Row */}
      <div className="grid grid-cols-5 gap-3">
        {[
          { key: 'all', label: 'Total', value: stats.total, color: 'slate', icon: Inbox },
          { key: 'pending', label: 'Pending', value: stats.pending, color: 'yellow', icon: Clock },
          { key: 'draft_ready', label: 'AI Ready', value: stats.draft_ready, color: 'blue', icon: Bot },
          { key: 'approved', label: 'Approved', value: stats.approved, color: 'green', icon: CheckCircle },
          { key: 'sent', label: 'Sent', value: stats.sent, color: 'indigo', icon: Send },
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

      {/* Email Table */}
      <Card>
        <CardHeader className="py-3">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base">
              <Mail className="h-4 w-4" />
              {activeInbox === 'emma' ? 'Emma Sales' : activeInbox === 'support' ? 'Support' : 'All'} Emails
              <Badge variant="secondary">{filteredEmails.length}</Badge>
            </CardTitle>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
              <Input
                placeholder="Search..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-[200px] pl-9 h-8"
              />
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-4 space-y-2">
              {[1, 2, 3].map(i => <Skeleton key={i} className="h-12 w-full" />)}
            </div>
          ) : filteredEmails.length === 0 ? (
            <div className="text-center py-12 text-slate-500">
              <Inbox className="h-12 w-12 mx-auto mb-3 opacity-30" />
              <p className="font-medium">No emails found</p>
              <p className="text-sm">Emails will appear when customers contact you</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="bg-slate-50">
                  <TableHead className="w-[200px]">From</TableHead>
                  <TableHead>Subject</TableHead>
                  <TableHead className="w-[80px]">Inbox</TableHead>
                  <TableHead className="w-[80px]">Type</TableHead>
                  <TableHead className="w-[80px]">Priority</TableHead>
                  <TableHead className="w-[100px]">Status</TableHead>
                  <TableHead className="w-[100px]">Received</TableHead>
                  <TableHead className="w-[60px]"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredEmails.map((email) => (
                  <TableRow
                    key={email.id}
                    className="cursor-pointer hover:bg-slate-50"
                    onClick={() => openEmailDetail(email)}
                  >
                    <TableCell>
                      <div className="flex flex-col">
                        <span className="font-medium truncate max-w-[180px]">{email.customer_name || 'Unknown'}</span>
                        <span className="text-xs text-slate-500 truncate max-w-[180px]">{email.customer_email}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col">
                        <span className="font-medium truncate max-w-[300px]">{email.subject}</span>
                        {email.latest_message && (
                          <span className="text-xs text-slate-500 truncate max-w-[300px]">{email.latest_message}</span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>{getInboxBadge(email.inbox_type)}</TableCell>
                    <TableCell>{getClassificationBadge(email.classification)}</TableCell>
                    <TableCell>{getPriorityBadge(email.priority)}</TableCell>
                    <TableCell>{getStatusBadge(email.status)}</TableCell>
                    <TableCell>
                      <span className="text-xs text-slate-500">
                        {email.received_at ? formatDistanceToNow(new Date(email.received_at), { addSuffix: true }) : '-'}
                      </span>
                    </TableCell>
                    <TableCell>
                      <Button variant="ghost" size="sm">
                        <Eye className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Email Detail Dialog */}
      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Mail className="h-5 w-5" />
              {selectedEmail?.subject || 'Email Details'}
            </DialogTitle>
            <DialogDescription className="flex items-center gap-2 flex-wrap">
              From: <span className="font-medium">{selectedEmail?.customer_name || 'Unknown'}</span>
              <span className="text-slate-400">({selectedEmail?.customer_email})</span>
              {selectedEmail?.received_at && (
                <span className="text-slate-400">
                  - {format(new Date(selectedEmail.received_at), 'MMM d, yyyy h:mm a')}
                </span>
              )}
            </DialogDescription>
          </DialogHeader>

          {selectedEmail && (
            <div className="space-y-6">
              {/* Status & Classification */}
              <div className="flex items-center gap-2 flex-wrap p-3 bg-slate-50 rounded-lg">
                {getStatusBadge(selectedEmail.status)}
                {getInboxBadge(selectedEmail.inbox_type)}
                {getClassificationBadge(selectedEmail.classification)}
                {selectedEmail.intent && (
                  <Badge variant="outline">{selectedEmail.intent}</Badge>
                )}
                {getPriorityBadge(selectedEmail.priority)}
                {selectedEmail.sales_opportunity && (
                  <Badge className="bg-amber-100 text-amber-800">
                    <TrendingUp className="h-3 w-3 mr-1" />
                    Sales Opportunity
                  </Badge>
                )}
              </div>

              {/* Messages */}
              <div className="space-y-4">
                <h4 className="font-semibold flex items-center gap-2">
                  <MessageSquare className="h-4 w-4" />
                  Conversation
                </h4>
                {selectedEmail.messages?.map((msg, idx) => (
                  <div
                    key={idx}
                    className={cn(
                      "p-4 rounded-lg border",
                      msg.direction === 'inbound' ? 'bg-slate-50 border-slate-200' : 'bg-blue-50 border-blue-200 ml-8'
                    )}
                  >
                    <div className="flex items-center gap-2 mb-2">
                      {msg.direction === 'inbound' ? (
                        <User className="h-4 w-4 text-slate-600" />
                      ) : (
                        <Bot className="h-4 w-4 text-blue-600" />
                      )}
                      <span className="font-medium text-sm">
                        {msg.direction === 'inbound' ? msg.sender_name || 'Customer' : 'Mirai Support'}
                      </span>
                      <span className="text-xs text-slate-500">
                        {msg.created_at ? format(new Date(msg.created_at), 'MMM d, h:mm a') : ''}
                      </span>
                    </div>
                    <div className="whitespace-pre-wrap text-sm">{msg.content}</div>

                    {/* AI Draft */}
                    {msg.ai_draft && (
                      <div className="mt-4 p-4 bg-white rounded-lg border-2 border-blue-300">
                        <div className="flex items-center gap-2 mb-3 text-blue-600">
                          <Sparkles className="h-4 w-4" />
                          <span className="font-semibold text-sm">AI Generated Draft</span>
                          <Badge className="bg-blue-100 text-blue-700 text-xs">Ready to send</Badge>
                        </div>
                        <div className="whitespace-pre-wrap text-sm bg-blue-50 p-3 rounded">{msg.ai_draft}</div>
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {/* Action Section based on status */}
              {selectedEmail.status === 'draft_ready' && (
                <div className="space-y-4 p-4 bg-green-50 rounded-lg border border-green-200">
                  <h4 className="font-semibold flex items-center gap-2 text-green-800">
                    <CheckCircle className="h-4 w-4" />
                    Ready to Send
                  </h4>
                  <p className="text-sm text-green-700">
                    Review the AI draft above. You can approve it, edit it, or reject it.
                  </p>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Edit draft (optional):</label>
                    <Textarea
                      value={editDraft}
                      onChange={(e) => setEditDraft(e.target.value)}
                      rows={6}
                      placeholder="Edit the AI draft here..."
                      className="bg-white"
                    />
                  </div>
                </div>
              )}

              {selectedEmail.status === 'pending' && !hasAIDraft(selectedEmail) && (
                <div className="space-y-4 p-4 bg-yellow-50 rounded-lg border border-yellow-200">
                  <h4 className="font-semibold flex items-center gap-2 text-yellow-800">
                    <AlertCircle className="h-4 w-4" />
                    Awaiting AI Draft
                  </h4>
                  <p className="text-sm text-yellow-700">
                    AI is processing. You can wait or write a manual response.
                  </p>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Manual response:</label>
                    <Textarea
                      value={manualResponse}
                      onChange={(e) => setManualResponse(e.target.value)}
                      rows={6}
                      placeholder="Type your response..."
                      className="bg-white"
                    />
                  </div>
                </div>
              )}
            </div>
          )}

          <DialogFooter className="flex gap-2 mt-4">
            <Button variant="outline" onClick={() => setDetailOpen(false)}>
              Close
            </Button>

            {selectedEmail?.status === 'draft_ready' && (
              <>
                <Button variant="destructive" onClick={handleReject} disabled={isSending}>
                  <XCircle className="h-4 w-4 mr-2" />
                  Reject
                </Button>
                <Button variant="secondary" onClick={handleApproveWithEdits} disabled={isSending || !editDraft}>
                  <Edit className="h-4 w-4 mr-2" />
                  {isSending ? 'Sending...' : 'Send Edited'}
                </Button>
                <Button onClick={handleApprove} disabled={isSending} className="bg-green-600 hover:bg-green-700">
                  <Send className="h-4 w-4 mr-2" />
                  {isSending ? 'Sending...' : 'Send AI Draft'}
                </Button>
              </>
            )}

            {selectedEmail?.status === 'pending' && (
              <>
                <Button variant="destructive" onClick={handleReject} disabled={isSending}>
                  <XCircle className="h-4 w-4 mr-2" />
                  Reject
                </Button>
                {manualResponse.trim() && (
                  <Button onClick={handleSendManual} disabled={isSending} className="bg-green-600 hover:bg-green-700">
                    <Send className="h-4 w-4 mr-2" />
                    {isSending ? 'Sending...' : 'Send Response'}
                  </Button>
                )}
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
