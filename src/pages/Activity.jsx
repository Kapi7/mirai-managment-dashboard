import React, { useState, useEffect, useMemo } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  CheckCircle,
  Send,
  RefreshCw,
  Search,
  Clock,
  User,
  Mail,
  Package,
  TrendingUp,
  TrendingDown,
  BarChart3,
  FileCheck,
  ArrowRight,
  Calendar,
  Timer,
  Users,
  Gift
} from 'lucide-react';
import { format, formatDistanceToNow } from 'date-fns';
import { cn } from '@/lib/utils';

const API_URL = '/api';

export default function Activity() {
  const { getAuthHeader } = useAuth();
  const [activeTab, setActiveTab] = useState('log');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Activity Log state
  const [activities, setActivities] = useState([]);
  const [activitySummary, setActivitySummary] = useState({});
  const [activityDays, setActivityDays] = useState('7');
  const [activityFilter, setActivityFilter] = useState('all');
  const [activitySearch, setActivitySearch] = useState('');

  // Resolution stats state
  const [resolutionStats, setResolutionStats] = useState(null);
  const [resolutionDays, setResolutionDays] = useState('30');

  // Sent emails state
  const [sentEmails, setSentEmails] = useState([]);
  const [sentEmailStats, setSentEmailStats] = useState({});
  const [emailDays, setEmailDays] = useState('7');
  const [emailFilter, setEmailFilter] = useState('all');
  const [emailSearch, setEmailSearch] = useState('');

  // Fetch activity log
  const fetchActivityLog = async () => {
    try {
      const response = await fetch(
        `${API_URL}/support/activity-log?days=${activityDays}&activity_type=${activityFilter}`,
        { headers: getAuthHeader() }
      );
      if (!response.ok) throw new Error('Failed to fetch activity log');
      const data = await response.json();
      setActivities(data.activities || []);
      setActivitySummary(data.summary || {});
    } catch (err) {
      console.error('Activity log error:', err);
      setError(err.message);
    }
  };

  // Fetch resolution stats
  const fetchResolutionStats = async () => {
    try {
      const response = await fetch(
        `${API_URL}/support/resolution-stats?days=${resolutionDays}`,
        { headers: getAuthHeader() }
      );
      if (!response.ok) throw new Error('Failed to fetch resolution stats');
      const data = await response.json();
      setResolutionStats(data);
    } catch (err) {
      console.error('Resolution stats error:', err);
      setError(err.message);
    }
  };

  // Fetch sent emails
  const fetchSentEmails = async () => {
    try {
      const response = await fetch(
        `${API_URL}/support/sent-emails?days=${emailDays}&email_type=${emailFilter}`,
        { headers: getAuthHeader() }
      );
      if (!response.ok) throw new Error('Failed to fetch sent emails');
      const data = await response.json();
      setSentEmails(data.emails || []);
      setSentEmailStats(data.by_type || {});
    } catch (err) {
      console.error('Sent emails error:', err);
      setError(err.message);
    }
  };

  // Initial load
  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      await Promise.all([
        fetchActivityLog(),
        fetchResolutionStats(),
        fetchSentEmails()
      ]);
      setLoading(false);
    };
    loadData();
  }, []);

  // Reload on filter changes
  useEffect(() => {
    if (!loading) fetchActivityLog();
  }, [activityDays, activityFilter]);

  useEffect(() => {
    if (!loading) fetchResolutionStats();
  }, [resolutionDays]);

  useEffect(() => {
    if (!loading) fetchSentEmails();
  }, [emailDays, emailFilter]);

  // Refresh all data
  const handleRefresh = async () => {
    setIsRefreshing(true);
    await Promise.all([
      fetchActivityLog(),
      fetchResolutionStats(),
      fetchSentEmails()
    ]);
    setIsRefreshing(false);
  };

  // Filter activities by search
  const filteredActivities = useMemo(() => {
    if (!activitySearch.trim()) return activities;
    const search = activitySearch.toLowerCase();
    return activities.filter(a =>
      a.customer_email?.toLowerCase().includes(search) ||
      a.customer_name?.toLowerCase().includes(search) ||
      a.subject?.toLowerCase().includes(search) ||
      a.order_number?.toLowerCase().includes(search)
    );
  }, [activities, activitySearch]);

  // Filter emails by search
  const filteredEmails = useMemo(() => {
    if (!emailSearch.trim()) return sentEmails;
    const search = emailSearch.toLowerCase();
    return sentEmails.filter(e =>
      e.to_email?.toLowerCase().includes(search) ||
      e.to_name?.toLowerCase().includes(search) ||
      e.subject?.toLowerCase().includes(search)
    );
  }, [sentEmails, emailSearch]);

  // Helper to format time
  const formatTime = (timestamp) => {
    if (!timestamp) return 'Unknown';
    try {
      return formatDistanceToNow(new Date(timestamp), { addSuffix: true });
    } catch {
      return timestamp;
    }
  };

  // Helper to format duration in minutes
  const formatDuration = (minutes) => {
    if (!minutes) return '-';
    if (minutes < 60) return `${minutes}m`;
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    if (hours < 24) return `${hours}h ${mins}m`;
    const days = Math.floor(hours / 24);
    return `${days}d ${hours % 24}h`;
  };

  // Activity type badge
  const getActivityBadge = (type) => {
    switch (type) {
      case 'resolved':
        return <Badge className="bg-green-100 text-green-800 border-0">Resolved</Badge>;
      case 'sent_reply':
        return <Badge className="bg-blue-100 text-blue-800 border-0">Reply Sent</Badge>;
      case 'followup_sent':
        return <Badge className="bg-purple-100 text-purple-800 border-0">Followup Sent</Badge>;
      default:
        return <Badge variant="outline">{type}</Badge>;
    }
  };

  // Resolution badge
  const getResolutionBadge = (resolution) => {
    const variants = {
      resolved: 'bg-green-100 text-green-800',
      refunded: 'bg-yellow-100 text-yellow-800',
      replaced: 'bg-orange-100 text-orange-800',
      escalated: 'bg-red-100 text-red-800',
      waiting_customer: 'bg-slate-100 text-slate-800',
      closed: 'bg-slate-100 text-slate-800',
      no_action_needed: 'bg-slate-100 text-slate-800'
    };
    return (
      <Badge className={cn(variants[resolution] || 'bg-slate-100 text-slate-800', 'border-0')}>
        {resolution?.replace(/_/g, ' ') || 'Unknown'}
      </Badge>
    );
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">Activity Center</h1>
          <p className="text-slate-500 mt-1">Review completed work and team performance</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleRefresh}
          disabled={isRefreshing}
        >
          <RefreshCw className={cn("h-4 w-4 mr-2", isRefreshing && "animate-spin")} />
          Refresh
        </Button>
      </div>

      {/* Error State */}
      {error && (
        <Card className="border-red-200 bg-red-50">
          <CardContent className="pt-6">
            <p className="text-red-700">{error}</p>
          </CardContent>
        </Card>
      )}

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <TabsList>
          <TabsTrigger value="log">
            <Clock className="h-4 w-4 mr-2" />
            Activity Log
          </TabsTrigger>
          <TabsTrigger value="resolutions">
            <BarChart3 className="h-4 w-4 mr-2" />
            Resolutions
          </TabsTrigger>
          <TabsTrigger value="emails">
            <Mail className="h-4 w-4 mr-2" />
            Sent Emails
          </TabsTrigger>
        </TabsList>

        {/* ACTIVITY LOG TAB */}
        <TabsContent value="log" className="space-y-4">
          {/* Summary Cards */}
          <div className="grid gap-4 md:grid-cols-4">
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-2xl font-bold text-green-600">{activitySummary.resolved_today || 0}</div>
                    <p className="text-xs text-muted-foreground">Resolved Today</p>
                  </div>
                  <CheckCircle className="h-8 w-8 text-green-200" />
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-2xl font-bold text-blue-600">{activitySummary.sent_today || 0}</div>
                    <p className="text-xs text-muted-foreground">Emails Sent Today</p>
                  </div>
                  <Send className="h-8 w-8 text-blue-200" />
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-2xl font-bold text-purple-600">{activitySummary.followups_today || 0}</div>
                    <p className="text-xs text-muted-foreground">Followups Today</p>
                  </div>
                  <Gift className="h-8 w-8 text-purple-200" />
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-2xl font-bold text-slate-700">{filteredActivities.length}</div>
                    <p className="text-xs text-muted-foreground">Total Activities</p>
                  </div>
                  <FileCheck className="h-8 w-8 text-slate-200" />
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Filters */}
          <div className="flex items-center gap-4">
            <Select value={activityFilter} onValueChange={setActivityFilter}>
              <SelectTrigger className="w-[150px]">
                <SelectValue placeholder="All Types" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Types</SelectItem>
                <SelectItem value="resolved">Resolved</SelectItem>
                <SelectItem value="sent">Sent Replies</SelectItem>
                <SelectItem value="followup">Followups</SelectItem>
              </SelectContent>
            </Select>
            <Select value={activityDays} onValueChange={setActivityDays}>
              <SelectTrigger className="w-[150px]">
                <SelectValue placeholder="Time Period" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="1">Today</SelectItem>
                <SelectItem value="7">Last 7 Days</SelectItem>
                <SelectItem value="30">Last 30 Days</SelectItem>
                <SelectItem value="90">Last 90 Days</SelectItem>
              </SelectContent>
            </Select>
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-slate-400" />
              <Input
                placeholder="Search activities..."
                value={activitySearch}
                onChange={(e) => setActivitySearch(e.target.value)}
                className="pl-10"
              />
            </div>
          </div>

          {/* Activity Feed */}
          <Card>
            <CardContent className="pt-6">
              {loading ? (
                <div className="space-y-4">
                  {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-20 w-full" />)}
                </div>
              ) : filteredActivities.length === 0 ? (
                <div className="text-center py-12 text-slate-500">
                  <Clock className="h-12 w-12 mx-auto mb-4 text-slate-300" />
                  <p>No activities found for the selected period</p>
                </div>
              ) : (
                <div className="space-y-4">
                  {filteredActivities.map((activity) => (
                    <div
                      key={activity.id}
                      className="flex items-start gap-4 p-4 rounded-lg border bg-white hover:bg-slate-50 transition-colors"
                    >
                      <div className="flex-shrink-0 mt-1">
                        {activity.type === 'resolved' && <CheckCircle className="h-5 w-5 text-green-500" />}
                        {activity.type === 'sent_reply' && <Send className="h-5 w-5 text-blue-500" />}
                        {activity.type === 'followup_sent' && <Gift className="h-5 w-5 text-purple-500" />}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          {getActivityBadge(activity.type)}
                          <span className="text-sm text-slate-500">{formatTime(activity.timestamp)}</span>
                        </div>
                        <div className="font-medium text-slate-900">
                          {activity.customer_name || activity.customer_email}
                        </div>
                        <div className="text-sm text-slate-600 truncate">{activity.subject}</div>
                        {activity.details && (
                          <div className="text-sm text-slate-500 mt-1 line-clamp-2">
                            {activity.type === 'resolved' ? (
                              <span className="flex items-center gap-2">
                                {getResolutionBadge(activity.action)}
                                {activity.details}
                              </span>
                            ) : (
                              activity.details
                            )}
                          </div>
                        )}
                        <div className="flex items-center gap-4 mt-2 text-xs text-slate-500">
                          {activity.agent && (
                            <span className="flex items-center gap-1">
                              <User className="h-3 w-3" />
                              {activity.agent}
                            </span>
                          )}
                          {activity.order_number && (
                            <span className="flex items-center gap-1">
                              <Package className="h-3 w-3" />
                              {activity.order_number}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* RESOLUTIONS TAB */}
        <TabsContent value="resolutions" className="space-y-4">
          {/* Period selector */}
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-slate-700">Period:</span>
            <Select value={resolutionDays} onValueChange={setResolutionDays}>
              <SelectTrigger className="w-[150px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="7">Last 7 Days</SelectItem>
                <SelectItem value="30">Last 30 Days</SelectItem>
                <SelectItem value="90">Last 90 Days</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {loading || !resolutionStats ? (
            <div className="grid gap-4 md:grid-cols-4">
              {[1, 2, 3, 4].map((i) => (
                <Card key={i}>
                  <CardContent className="pt-6">
                    <Skeleton className="h-8 w-20" />
                    <Skeleton className="h-4 w-24 mt-2" />
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : (
            <>
              {/* Summary Cards */}
              <div className="grid gap-4 md:grid-cols-4">
                <Card>
                  <CardContent className="pt-6">
                    <div className="text-2xl font-bold">{resolutionStats.total_resolved}</div>
                    <p className="text-xs text-muted-foreground">Total Resolved</p>
                    <p className="text-xs text-slate-500 mt-1">
                      of {resolutionStats.total_tickets} tickets
                    </p>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="pt-6">
                    <div className="text-2xl font-bold text-green-600">
                      {(resolutionStats.resolution_rate * 100).toFixed(0)}%
                    </div>
                    <p className="text-xs text-muted-foreground">Resolution Rate</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="pt-6">
                    <div className="text-2xl font-bold">
                      {formatDuration(resolutionStats.avg_resolution_time_minutes)}
                    </div>
                    <p className="text-xs text-muted-foreground">Avg Resolution Time</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="pt-6">
                    <div className="text-2xl font-bold">
                      {formatDuration(resolutionStats.avg_first_response_minutes)}
                    </div>
                    <p className="text-xs text-muted-foreground">Avg First Response</p>
                  </CardContent>
                </Card>
              </div>

              {/* Trend Card */}
              {resolutionStats.trend && (
                <Card>
                  <CardContent className="pt-6">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-sm font-medium text-slate-700">Week over Week</p>
                        <div className="flex items-center gap-2 mt-1">
                          <span className="text-2xl font-bold">{resolutionStats.trend.this_week}</span>
                          <span className="text-slate-500">vs</span>
                          <span className="text-lg text-slate-600">{resolutionStats.trend.last_week}</span>
                        </div>
                      </div>
                      <div className={cn(
                        "flex items-center gap-1 text-lg font-semibold",
                        resolutionStats.trend.change_pct >= 0 ? "text-green-600" : "text-red-600"
                      )}>
                        {resolutionStats.trend.change_pct >= 0 ? (
                          <TrendingUp className="h-5 w-5" />
                        ) : (
                          <TrendingDown className="h-5 w-5" />
                        )}
                        {Math.abs(resolutionStats.trend.change_pct)}%
                      </div>
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Resolution Type Breakdown */}
              <div className="grid gap-4 md:grid-cols-2">
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm font-medium">Resolution Types</CardTitle>
                  </CardHeader>
                  <CardContent>
                    {Object.keys(resolutionStats.by_resolution_type || {}).length === 0 ? (
                      <p className="text-sm text-slate-500">No resolutions in this period</p>
                    ) : (
                      <div className="space-y-3">
                        {Object.entries(resolutionStats.by_resolution_type)
                          .sort((a, b) => b[1] - a[1])
                          .map(([type, count]) => (
                            <div key={type} className="flex items-center justify-between">
                              {getResolutionBadge(type)}
                              <div className="flex items-center gap-2">
                                <div className="w-24 h-2 bg-slate-100 rounded-full overflow-hidden">
                                  <div
                                    className="h-full bg-indigo-500 rounded-full"
                                    style={{
                                      width: `${(count / resolutionStats.total_resolved) * 100}%`
                                    }}
                                  />
                                </div>
                                <span className="text-sm font-medium w-8 text-right">{count}</span>
                              </div>
                            </div>
                          ))}
                      </div>
                    )}
                  </CardContent>
                </Card>

                {/* Agent Performance */}
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm font-medium flex items-center gap-2">
                      <Users className="h-4 w-4" />
                      Agent Performance
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    {(resolutionStats.by_agent || []).length === 0 ? (
                      <p className="text-sm text-slate-500">No agent data available</p>
                    ) : (
                      <div className="overflow-x-auto">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>Agent</TableHead>
                              <TableHead className="text-right">Resolved</TableHead>
                              <TableHead className="text-right">Avg Time</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {resolutionStats.by_agent.map((agent) => (
                              <TableRow key={agent.agent_id}>
                                <TableCell className="font-medium">{agent.agent_name}</TableCell>
                                <TableCell className="text-right">{agent.resolved}</TableCell>
                                <TableCell className="text-right">{formatDuration(agent.avg_time)}</TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </div>
            </>
          )}
        </TabsContent>

        {/* SENT EMAILS TAB */}
        <TabsContent value="emails" className="space-y-4">
          {/* Stats Cards */}
          <div className="grid gap-4 md:grid-cols-3">
            <Card>
              <CardContent className="pt-6">
                <div className="text-2xl font-bold">{sentEmails.length}</div>
                <p className="text-xs text-muted-foreground">Total Sent</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="text-2xl font-bold text-blue-600">{sentEmailStats.support_reply || 0}</div>
                <p className="text-xs text-muted-foreground">Support Replies</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="text-2xl font-bold text-purple-600">{sentEmailStats.delivery_followup || 0}</div>
                <p className="text-xs text-muted-foreground">Delivery Followups</p>
              </CardContent>
            </Card>
          </div>

          {/* Filters */}
          <div className="flex items-center gap-4">
            <Select value={emailFilter} onValueChange={setEmailFilter}>
              <SelectTrigger className="w-[150px]">
                <SelectValue placeholder="All Types" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Types</SelectItem>
                <SelectItem value="support">Support Replies</SelectItem>
                <SelectItem value="followup">Followups</SelectItem>
              </SelectContent>
            </Select>
            <Select value={emailDays} onValueChange={setEmailDays}>
              <SelectTrigger className="w-[150px]">
                <SelectValue placeholder="Time Period" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="1">Today</SelectItem>
                <SelectItem value="7">Last 7 Days</SelectItem>
                <SelectItem value="30">Last 30 Days</SelectItem>
                <SelectItem value="90">Last 90 Days</SelectItem>
              </SelectContent>
            </Select>
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-slate-400" />
              <Input
                placeholder="Search emails..."
                value={emailSearch}
                onChange={(e) => setEmailSearch(e.target.value)}
                className="pl-10"
              />
            </div>
          </div>

          {/* Emails Table */}
          <Card>
            <CardContent className="pt-6">
              {loading ? (
                <div className="space-y-2">
                  {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
                </div>
              ) : filteredEmails.length === 0 ? (
                <div className="text-center py-12 text-slate-500">
                  <Mail className="h-12 w-12 mx-auto mb-4 text-slate-300" />
                  <p>No sent emails found for the selected period</p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Date</TableHead>
                        <TableHead>Type</TableHead>
                        <TableHead>To</TableHead>
                        <TableHead>Subject</TableHead>
                        <TableHead>Approved By</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {filteredEmails.map((email) => (
                        <TableRow key={`${email.type}-${email.id}`}>
                          <TableCell className="whitespace-nowrap">
                            {email.sent_at ? format(new Date(email.sent_at), 'MMM d, HH:mm') : '-'}
                          </TableCell>
                          <TableCell>
                            {email.type === 'support_reply' ? (
                              <Badge className="bg-blue-100 text-blue-800 border-0">Reply</Badge>
                            ) : (
                              <Badge className="bg-purple-100 text-purple-800 border-0">Followup</Badge>
                            )}
                          </TableCell>
                          <TableCell>
                            <div className="font-medium">{email.to_name || '-'}</div>
                            <div className="text-xs text-slate-500">{email.to_email}</div>
                          </TableCell>
                          <TableCell>
                            <div className="max-w-xs truncate font-medium">{email.subject}</div>
                            <div className="text-xs text-slate-500 truncate max-w-xs">{email.preview}</div>
                          </TableCell>
                          <TableCell>
                            {email.approved_by || (email.type === 'delivery_followup' ? 'System' : '-')}
                          </TableCell>
                        </TableRow>
                      ))}
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
