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
  ArrowRight,
  BarChart3,
  Timer,
  Inbox,
  ChevronRight
} from 'lucide-react';
import { format, formatDistanceToNow } from 'date-fns';
import { cn } from '@/lib/utils';

const API_URL = '/api';

export default function Support() {
  const [emails, setEmails] = useState([]);
  const [stats, setStats] = useState({ pending: 0, draft_ready: 0, approved: 0, sent: 0, total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('all');
  const [search, setSearch] = useState('');
  const [selectedEmail, setSelectedEmail] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [editDraft, setEditDraft] = useState('');
  const [manualResponse, setManualResponse] = useState('');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isSending, setIsSending] = useState(false);

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

  // Send manual response (for pending emails without draft)
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
      pending: { variant: 'secondary', icon: Clock, label: 'Pending', color: 'text-yellow-600 bg-yellow-50' },
      draft_ready: { variant: 'default', icon: Bot, label: 'AI Draft Ready', color: 'text-blue-600 bg-blue-50' },
      approved: { variant: 'outline', icon: CheckCircle, label: 'Approved', color: 'text-green-600 bg-green-50' },
      sent: { variant: 'default', icon: Send, label: 'Sent', color: 'text-indigo-600 bg-indigo-50' },
      rejected: { variant: 'destructive', icon: XCircle, label: 'Rejected', color: 'text-red-600 bg-red-50' }
    };
    const config = variants[status] || variants.pending;
    const Icon = config.icon;
    return (
      <Badge className={cn("flex items-center gap-1", config.color)}>
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

  // Check if email has AI draft
  const hasAIDraft = (email) => {
    return email?.messages?.some(m => m.ai_draft);
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

      {/* Workflow Guide */}
      <Card className="bg-gradient-to-r from-blue-50 to-indigo-50 border-blue-200">
        <CardContent className="p-4">
          <div className="flex items-center gap-6 text-sm">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-yellow-500 text-white flex items-center justify-center font-bold">1</div>
              <span className="font-medium">Email Arrives</span>
            </div>
            <ChevronRight className="h-4 w-4 text-slate-400" />
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-blue-500 text-white flex items-center justify-center font-bold">2</div>
              <span className="font-medium">AI Classifies & Drafts</span>
            </div>
            <ChevronRight className="h-4 w-4 text-slate-400" />
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-green-500 text-white flex items-center justify-center font-bold">3</div>
              <span className="font-medium">You Review & Approve</span>
            </div>
            <ChevronRight className="h-4 w-4 text-slate-400" />
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-indigo-500 text-white flex items-center justify-center font-bold">4</div>
              <span className="font-medium">Response Sent</span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Stats Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <Card
          className={cn("cursor-pointer hover:shadow-md transition-shadow", activeTab === 'pending' && "ring-2 ring-yellow-500")}
          onClick={() => setActiveTab('pending')}
        >
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-500">Needs Review</p>
                <p className="text-2xl font-bold text-yellow-600">{stats.pending || 0}</p>
              </div>
              <div className="h-12 w-12 rounded-full bg-yellow-100 flex items-center justify-center">
                <Clock className="h-6 w-6 text-yellow-600" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card
          className={cn("cursor-pointer hover:shadow-md transition-shadow", activeTab === 'draft_ready' && "ring-2 ring-blue-500")}
          onClick={() => setActiveTab('draft_ready')}
        >
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-500">AI Drafts Ready</p>
                <p className="text-2xl font-bold text-blue-600">{stats.draft_ready || 0}</p>
              </div>
              <div className="h-12 w-12 rounded-full bg-blue-100 flex items-center justify-center">
                <Bot className="h-6 w-6 text-blue-600" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card
          className={cn("cursor-pointer hover:shadow-md transition-shadow", activeTab === 'approved' && "ring-2 ring-green-500")}
          onClick={() => setActiveTab('approved')}
        >
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-500">Approved</p>
                <p className="text-2xl font-bold text-green-600">{stats.approved || 0}</p>
              </div>
              <div className="h-12 w-12 rounded-full bg-green-100 flex items-center justify-center">
                <CheckCircle className="h-6 w-6 text-green-600" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card
          className={cn("cursor-pointer hover:shadow-md transition-shadow", activeTab === 'sent' && "ring-2 ring-indigo-500")}
          onClick={() => setActiveTab('sent')}
        >
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-500">Sent</p>
                <p className="text-2xl font-bold text-indigo-600">{stats.sent || 0}</p>
              </div>
              <div className="h-12 w-12 rounded-full bg-indigo-100 flex items-center justify-center">
                <Send className="h-6 w-6 text-indigo-600" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card
          className={cn("cursor-pointer hover:shadow-md transition-shadow", activeTab === 'all' && "ring-2 ring-slate-500")}
          onClick={() => setActiveTab('all')}
        >
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-500">Total</p>
                <p className="text-2xl font-bold">{stats.total || 0}</p>
              </div>
              <div className="h-12 w-12 rounded-full bg-slate-100 flex items-center justify-center">
                <Inbox className="h-6 w-6 text-slate-600" />
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Email List */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Mail className="h-5 w-5" />
                Email Queue
              </CardTitle>
              <CardDescription>
                {filteredEmails.length} emails {activeTab !== 'all' ? `in ${activeTab.replace('_', ' ')} status` : 'total'}
              </CardDescription>
            </div>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
              <Input
                placeholder="Search emails..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-[250px] pl-9"
              />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">
              {[1, 2, 3].map(i => <Skeleton key={i} className="h-20 w-full" />)}
            </div>
          ) : filteredEmails.length === 0 ? (
            <div className="text-center py-12 text-slate-500">
              <Inbox className="h-16 w-16 mx-auto mb-4 opacity-30" />
              <p className="text-lg font-medium">No emails here</p>
              <p className="text-sm mt-1">Emails will appear when customers contact you</p>
            </div>
          ) : (
            <div className="space-y-2">
              {filteredEmails.map((email) => (
                <div
                  key={email.id}
                  className="p-4 rounded-lg border hover:bg-slate-50 cursor-pointer transition-colors"
                  onClick={() => openEmailDetail(email)}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-semibold truncate">{email.customer_name || 'Unknown'}</span>
                        <span className="text-slate-400 text-sm truncate">&lt;{email.customer_email}&gt;</span>
                      </div>
                      <div className="font-medium text-slate-900 truncate">{email.subject}</div>
                      <div className="text-sm text-slate-500 mt-1 flex items-center gap-3">
                        <span>{email.received_at ? formatDistanceToNow(new Date(email.received_at), { addSuffix: true }) : '-'}</span>
                        {getClassificationBadge(email.classification)}
                        {getPriorityBadge(email.priority)}
                        {email.sales_opportunity && (
                          <Badge className="bg-amber-100 text-amber-800 text-xs">
                            <TrendingUp className="h-3 w-3 mr-1" />
                            Sales
                          </Badge>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {getStatusBadge(email.status)}
                      <Button variant="ghost" size="sm">
                        <Eye className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
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
            <DialogDescription className="flex items-center gap-2">
              From: <span className="font-medium">{selectedEmail?.customer_name || 'Unknown'}</span>
              <span className="text-slate-400">({selectedEmail?.customer_email})</span>
              {selectedEmail?.received_at && (
                <span className="text-slate-400">
                  • {format(new Date(selectedEmail.received_at), 'MMM d, yyyy h:mm a')}
                </span>
              )}
            </DialogDescription>
          </DialogHeader>

          {selectedEmail && (
            <div className="space-y-6">
              {/* Status & Classification */}
              <div className="flex items-center gap-2 flex-wrap p-3 bg-slate-50 rounded-lg">
                {getStatusBadge(selectedEmail.status)}
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
                    Review the AI-generated draft above. You can approve it as-is, edit it, or reject it.
                  </p>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Edit draft before sending (optional):</label>
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
                    The AI is processing this email. You can wait for the draft or write a manual response.
                  </p>
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Write manual response:</label>
                    <Textarea
                      value={manualResponse}
                      onChange={(e) => setManualResponse(e.target.value)}
                      rows={6}
                      placeholder="Type your response here..."
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
