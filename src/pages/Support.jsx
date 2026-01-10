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
  Eye
} from 'lucide-react';
import { format } from 'date-fns';
import { cn } from '@/lib/utils';

const API_URL = '/api';

export default function Support() {
  const [emails, setEmails] = useState([]);
  const [stats, setStats] = useState({ pending: 0, draft_ready: 0, approved: 0, sent: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('pending');
  const [search, setSearch] = useState('');
  const [selectedEmail, setSelectedEmail] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [editDraft, setEditDraft] = useState('');
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Fetch emails
  const fetchEmails = async (status = null) => {
    try {
      const params = new URLSearchParams();
      if (status && status !== 'all') params.append('status', status);
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
      await Promise.all([fetchEmails(activeTab), fetchStats()]);
      setLoading(false);
    };
    loadData();
  }, []);

  // Reload when tab changes
  useEffect(() => {
    fetchEmails(activeTab);
  }, [activeTab]);

  // Refresh
  const handleRefresh = async () => {
    setIsRefreshing(true);
    await Promise.all([fetchEmails(activeTab), fetchStats()]);
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
      setDetailOpen(true);
    } catch (err) {
      console.error('Failed to fetch email:', err);
    }
  };

  // Approve email
  const handleApprove = async () => {
    if (!selectedEmail) return;
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
  };

  // Approve with edits
  const handleApproveWithEdits = async () => {
    if (!selectedEmail || !editDraft) return;
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
      pending: { variant: 'secondary', icon: Clock, label: 'Pending' },
      draft_ready: { variant: 'default', icon: Bot, label: 'AI Draft Ready' },
      approved: { variant: 'outline', icon: CheckCircle, label: 'Approved' },
      sent: { variant: 'default', icon: Send, label: 'Sent' },
      rejected: { variant: 'destructive', icon: XCircle, label: 'Rejected' }
    };
    const config = variants[status] || variants.pending;
    const Icon = config.icon;
    return (
      <Badge variant={config.variant} className="flex items-center gap-1">
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
        {classification === 'support_sales' ? 'Support + Sales' : classification}
      </Badge>
    );
  };

  // Priority badge
  const getPriorityBadge = (priority) => {
    if (!priority || priority === 'medium') return null;
    return (
      <Badge variant={priority === 'high' ? 'destructive' : 'outline'} className="text-xs">
        {priority}
      </Badge>
    );
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">Support Inbox</h1>
          <p className="text-slate-500 mt-1">AI-powered customer support management</p>
        </div>
        <Button onClick={handleRefresh} disabled={isRefreshing}>
          <RefreshCw className={cn("h-4 w-4 mr-2", isRefreshing && "animate-spin")} />
          Refresh
        </Button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
        <Card className="cursor-pointer hover:shadow-md transition-shadow" onClick={() => setActiveTab('pending')}>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-500">Pending Review</p>
                <p className="text-2xl font-bold">{stats.pending}</p>
              </div>
              <Clock className="h-8 w-8 text-yellow-500" />
            </div>
          </CardContent>
        </Card>

        <Card className="cursor-pointer hover:shadow-md transition-shadow" onClick={() => setActiveTab('draft_ready')}>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-500">AI Drafts Ready</p>
                <p className="text-2xl font-bold">{stats.draft_ready}</p>
              </div>
              <Bot className="h-8 w-8 text-blue-500" />
            </div>
          </CardContent>
        </Card>

        <Card className="cursor-pointer hover:shadow-md transition-shadow" onClick={() => setActiveTab('approved')}>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-500">Approved</p>
                <p className="text-2xl font-bold">{stats.approved}</p>
              </div>
              <CheckCircle className="h-8 w-8 text-green-500" />
            </div>
          </CardContent>
        </Card>

        <Card className="cursor-pointer hover:shadow-md transition-shadow" onClick={() => setActiveTab('sent')}>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-500">Sent</p>
                <p className="text-2xl font-bold">{stats.sent}</p>
              </div>
              <Send className="h-8 w-8 text-indigo-500" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-500">Total</p>
                <p className="text-2xl font-bold">{stats.total || 0}</p>
              </div>
              <Mail className="h-8 w-8 text-slate-400" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Email List */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Email Queue</CardTitle>
              <CardDescription>
                {filteredEmails.length} emails in {activeTab} status
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <Input
                placeholder="Search emails..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-[250px]"
              />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList>
              <TabsTrigger value="pending">Pending ({stats.pending})</TabsTrigger>
              <TabsTrigger value="draft_ready">AI Ready ({stats.draft_ready})</TabsTrigger>
              <TabsTrigger value="approved">Approved ({stats.approved})</TabsTrigger>
              <TabsTrigger value="sent">Sent ({stats.sent})</TabsTrigger>
              <TabsTrigger value="all">All</TabsTrigger>
            </TabsList>

            <TabsContent value={activeTab} className="mt-4">
              {loading ? (
                <div className="space-y-2">
                  {[1, 2, 3].map(i => <Skeleton key={i} className="h-16 w-full" />)}
                </div>
              ) : filteredEmails.length === 0 ? (
                <div className="text-center py-12 text-slate-500">
                  <Mail className="h-12 w-12 mx-auto mb-4 opacity-50" />
                  <p>No emails in this queue</p>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Customer</TableHead>
                      <TableHead>Subject</TableHead>
                      <TableHead>Type</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Received</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredEmails.map((email) => (
                      <TableRow key={email.id} className="cursor-pointer hover:bg-slate-50" onClick={() => openEmailDetail(email)}>
                        <TableCell>
                          <div>
                            <div className="font-medium">{email.customer_name || 'Unknown'}</div>
                            <div className="text-sm text-slate-500">{email.customer_email}</div>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="max-w-[300px] truncate">{email.subject}</div>
                          {email.latest_message && (
                            <div className="text-sm text-slate-500 truncate max-w-[300px]">
                              {email.latest_message}
                            </div>
                          )}
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-col gap-1">
                            {getClassificationBadge(email.classification)}
                            {getPriorityBadge(email.priority)}
                            {email.sales_opportunity && (
                              <Badge className="bg-amber-100 text-amber-800 text-xs">
                                <TrendingUp className="h-3 w-3 mr-1" />
                                Sales Opp
                              </Badge>
                            )}
                          </div>
                        </TableCell>
                        <TableCell>{getStatusBadge(email.status)}</TableCell>
                        <TableCell>
                          {email.received_at ? format(new Date(email.received_at), 'MMM d, h:mm a') : '-'}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); openEmailDetail(email); }}>
                            <Eye className="h-4 w-4" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </TabsContent>
          </Tabs>
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
            <DialogDescription>
              From: {selectedEmail?.customer_name} ({selectedEmail?.customer_email})
            </DialogDescription>
          </DialogHeader>

          {selectedEmail && (
            <div className="space-y-4">
              {/* Classification & Status */}
              <div className="flex items-center gap-2 flex-wrap">
                {getStatusBadge(selectedEmail.status)}
                {getClassificationBadge(selectedEmail.classification)}
                {selectedEmail.intent && (
                  <Badge variant="outline">{selectedEmail.intent}</Badge>
                )}
                {selectedEmail.sales_opportunity && (
                  <Badge className="bg-amber-100 text-amber-800">
                    <TrendingUp className="h-3 w-3 mr-1" />
                    Sales Opportunity
                  </Badge>
                )}
              </div>

              {/* Messages */}
              <div className="space-y-4">
                <h4 className="font-semibold">Conversation</h4>
                {selectedEmail.messages?.map((msg, idx) => (
                  <div
                    key={idx}
                    className={cn(
                      "p-4 rounded-lg",
                      msg.direction === 'inbound' ? 'bg-slate-100' : 'bg-blue-50 ml-8'
                    )}
                  >
                    <div className="flex items-center gap-2 mb-2">
                      {msg.direction === 'inbound' ? (
                        <User className="h-4 w-4" />
                      ) : (
                        <Bot className="h-4 w-4" />
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
                      <div className="mt-4 p-3 bg-white rounded border border-blue-200">
                        <div className="flex items-center gap-2 mb-2 text-blue-600">
                          <Bot className="h-4 w-4" />
                          <span className="font-medium text-sm">AI Generated Draft</span>
                        </div>
                        <div className="whitespace-pre-wrap text-sm">{msg.ai_draft}</div>
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {/* Edit Draft */}
              {selectedEmail.status === 'draft_ready' && (
                <div className="space-y-2">
                  <h4 className="font-semibold flex items-center gap-2">
                    <Edit className="h-4 w-4" />
                    Edit Response (optional)
                  </h4>
                  <Textarea
                    value={editDraft}
                    onChange={(e) => setEditDraft(e.target.value)}
                    rows={6}
                    placeholder="Edit the AI draft or leave as-is to approve"
                  />
                </div>
              )}
            </div>
          )}

          <DialogFooter className="flex gap-2">
            <Button variant="outline" onClick={() => setDetailOpen(false)}>
              Close
            </Button>
            {selectedEmail?.status === 'draft_ready' && (
              <>
                <Button variant="destructive" onClick={handleReject}>
                  <XCircle className="h-4 w-4 mr-2" />
                  Reject
                </Button>
                <Button variant="secondary" onClick={handleApproveWithEdits}>
                  <Edit className="h-4 w-4 mr-2" />
                  Approve with Edits
                </Button>
                <Button onClick={handleApprove}>
                  <CheckCircle className="h-4 w-4 mr-2" />
                  Approve AI Draft
                </Button>
              </>
            )}
            {selectedEmail?.status === 'pending' && (
              <Button variant="destructive" onClick={handleReject}>
                <XCircle className="h-4 w-4 mr-2" />
                Reject
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
