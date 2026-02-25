import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { useToast } from '@/components/ui/use-toast';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Progress } from '@/components/ui/progress';
import { Separator } from '@/components/ui/separator';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Tooltip, TooltipContent, TooltipProvider, TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  Brain,
  Palette,
  Share2,
  Target,
  TrendingUp,
  Users,
  BarChart3,
  Zap,
  Clock,
  CheckCircle,
  XCircle,
  AlertCircle,
  Loader2,
  RefreshCw,
  Play,
  Calendar,
  Image,
  FileText,
  Eye,
  MousePointer,
  ThumbsUp,
  ThumbsDown,
  Plus,
  Instagram,
  Facebook,
  Video,
  ArrowRight,
} from 'lucide-react';
import { cn } from '@/lib/utils';

const API_URL = import.meta.env.DEV ? 'http://localhost:8080' : '/api';

// --- Badge helpers ---

const statusBadge = (status) => {
  const map = {
    active:      'bg-green-100 text-green-700',
    idle:        'bg-slate-100 text-slate-600',
    pending:             'bg-yellow-100 text-yellow-700',
    awaiting_approval:   'bg-amber-100 text-amber-700',
    pending_approval:    'bg-amber-100 text-amber-700',
    auto_approved:       'bg-slate-100 text-slate-600',
    in_progress:         'bg-blue-100 text-blue-700',
    completed:   'bg-green-100 text-green-700',
    failed:      'bg-red-100 text-red-700',
    approved:    'bg-green-100 text-green-700',
    rejected:    'bg-red-100 text-red-700',
    draft:       'bg-slate-100 text-slate-600',
    ready:       'bg-blue-100 text-blue-700',
    archived:    'bg-slate-200 text-slate-500',
    planned:     'bg-slate-100 text-slate-600',
    asset_ready: 'bg-blue-100 text-blue-700',
    published:   'bg-green-100 text-green-700',
    cancelled:   'bg-red-100 text-red-700',
  };
  const color = map[status] || 'bg-slate-100 text-slate-600';
  return (
    <Badge className={cn(color, 'font-medium border-0 capitalize')}>
      {(status || 'unknown').replace(/_/g, ' ')}
    </Badge>
  );
};

const priorityBadge = (priority) => {
  const map = {
    critical: 'bg-red-100 text-red-700 border-red-300',
    high:     'bg-orange-100 text-orange-700 border-orange-300',
    medium:   'bg-yellow-100 text-yellow-700 border-yellow-300',
    low:      'bg-slate-100 text-slate-600 border-slate-300',
  };
  const color = map[priority] || map.medium;
  return (
    <Badge className={cn(color, 'border font-medium capitalize')}>
      {priority || 'medium'}
    </Badge>
  );
};

const agentBadge = (agent) => {
  const map = {
    cmo:         { color: 'bg-violet-100 text-violet-700', icon: Brain },
    content:     { color: 'bg-pink-100 text-pink-700', icon: Palette },
    social:      { color: 'bg-sky-100 text-sky-700', icon: Share2 },
    acquisition: { color: 'bg-amber-100 text-amber-700', icon: Target },
  };
  const config = map[agent] || { color: 'bg-slate-100 text-slate-600', icon: Zap };
  const Icon = config.icon;
  return (
    <Badge className={cn(config.color, 'font-medium border-0 capitalize flex items-center gap-1')}>
      <Icon className="w-3 h-3" />
      {agent || 'agent'}
    </Badge>
  );
};

const channelIcon = (channel) => {
  switch (channel?.toLowerCase()) {
    case 'instagram': case 'ig': return <Instagram className="w-4 h-4 text-pink-500" />;
    case 'facebook': case 'fb': return <Facebook className="w-4 h-4 text-blue-600" />;
    case 'tiktok': return <Video className="w-4 h-4 text-slate-800" />;
    default: return <Share2 className="w-4 h-4 text-slate-400" />;
  }
};

const pillarBadge = (pillar) => {
  const map = {
    educational:   'bg-blue-100 text-blue-700',
    promotional:   'bg-green-100 text-green-700',
    engagement:    'bg-purple-100 text-purple-700',
    behind_scenes: 'bg-amber-100 text-amber-700',
    ugc:           'bg-pink-100 text-pink-700',
  };
  const color = map[pillar] || 'bg-slate-100 text-slate-600';
  return (
    <Badge className={cn(color, 'border-0 font-medium capitalize text-xs')}>
      {(pillar || 'general').replace(/_/g, ' ')}
    </Badge>
  );
};

// --- Helpers ---

const formatTimestamp = (ts) => {
  if (!ts) return '-';
  try {
    const d = new Date(ts);
    const now = new Date();
    const diffMs = now - d;
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHrs = Math.floor(diffMins / 60);
    if (diffHrs < 24) return `${diffHrs}h ago`;
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch {
    return ts;
  }
};

const formatDuration = (seconds) => {
  if (!seconds) return '-';
  if (seconds < 60) return `${seconds}s`;
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (mins < 60) return `${mins}m ${secs}s`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ${mins % 60}m`;
};

const truncate = (str, len = 80) => {
  if (!str) return '-';
  return str.length > len ? str.slice(0, len) + '...' : str;
};

const formatNumber = (n) => {
  if (n == null) return '0';
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
  return n.toLocaleString();
};

// --- Component ---

export default function AgentDashboard() {
  const { getAuthHeader } = useAuth();
  const { toast } = useToast();

  const [activeTab, setActiveTab] = useState('overview');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  // Overview data
  const [agents, setAgents] = useState([]);
  const [kpis, setKpis] = useState(null);

  // Tasks
  const [tasks, setTasks] = useState([]);
  const [taskStatusFilter, setTaskStatusFilter] = useState('all');
  const [taskAgentFilter, setTaskAgentFilter] = useState('all');
  const [selectedTask, setSelectedTask] = useState(null);

  // Decisions
  const [decisions, setDecisions] = useState([]);
  const [selectedDecision, setSelectedDecision] = useState(null);

  // Content assets
  const [assets, setAssets] = useState([]);
  const [assetPillarFilter, setAssetPillarFilter] = useState('all');
  const [assetStatusFilter, setAssetStatusFilter] = useState('all');
  const [showNewAssetDialog, setShowNewAssetDialog] = useState(false);
  const [newAssetType, setNewAssetType] = useState('social_post');

  // Calendar
  const [calendarSlots, setCalendarSlots] = useState([]);

  // --- Fetch helpers ---

  const headers = useCallback(() => {
    const auth = getAuthHeader();
    return { ...auth, 'Content-Type': 'application/json' };
  }, [getAuthHeader]);

  const fetchAgents = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/agents/orchestrator/status`, { headers: headers() });
      if (!res.ok) throw new Error('Failed to fetch agents');
      const data = await res.json();
      setAgents(data.agents || []);
    } catch (err) {
      console.error('Agents fetch error:', err);
    }
  }, [headers]);

  const fetchKpis = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/agents/cmo/kpis`, { headers: headers() });
      if (!res.ok) throw new Error('Failed to fetch KPIs');
      const data = await res.json();
      setKpis(data);
    } catch (err) {
      console.error('KPIs fetch error:', err);
    }
  }, [headers]);

  const fetchTasks = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (taskStatusFilter !== 'all') params.set('status', taskStatusFilter);
      if (taskAgentFilter !== 'all') params.set('agent', taskAgentFilter);
      const res = await fetch(`${API_URL}/agents/tasks?${params}`, { headers: headers() });
      if (!res.ok) throw new Error('Failed to fetch tasks');
      const data = await res.json();
      setTasks(data.tasks || []);
    } catch (err) {
      console.error('Tasks fetch error:', err);
    }
  }, [headers, taskStatusFilter, taskAgentFilter]);

  const fetchDecisions = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/agents/decisions?cleanup=true`, { headers: headers() });
      if (!res.ok) throw new Error('Failed to fetch decisions');
      const data = await res.json();
      // Derive status from raw fields if backend doesn't include it
      const deriveStatus = (d) => {
        if (d.status) return d.status;
        if (d.rejected_at) return 'rejected';
        if (d.approved_at) return 'approved';
        if (d.requires_approval) return 'pending_approval';
        return 'auto_approved';
      };
      const withStatus = (data.decisions || data || []).map(d => ({ ...d, status: deriveStatus(d) }));
      setDecisions(withStatus);
    } catch (err) {
      console.error('Decisions fetch error:', err);
    }
  }, [headers]);

  const fetchAssets = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (assetPillarFilter !== 'all') params.set('pillar', assetPillarFilter);
      if (assetStatusFilter !== 'all') params.set('status', assetStatusFilter);
      const res = await fetch(`${API_URL}/agents/content-assets?${params}`, { headers: headers() });
      if (!res.ok) throw new Error('Failed to fetch assets');
      const data = await res.json();
      setAssets(Array.isArray(data) ? data : (data.assets || []));
    } catch (err) {
      console.error('Assets fetch error:', err);
    }
  }, [headers, assetPillarFilter, assetStatusFilter]);

  const fetchCalendar = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/agents/calendar?days=7`, { headers: headers() });
      if (!res.ok) throw new Error('Failed to fetch calendar');
      const data = await res.json();
      setCalendarSlots(data.slots || []);
    } catch (err) {
      console.error('Calendar fetch error:', err);
    }
  }, [headers]);

  // --- Initial load ---

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      await Promise.all([fetchAgents(), fetchKpis()]);
      setLoading(false);
    };
    load();
  }, []);

  // Reload data when switching tabs
  useEffect(() => {
    if (loading) return;
    const loaders = {
      overview: () => Promise.all([fetchAgents(), fetchKpis()]),
      tasks: fetchTasks,
      decisions: fetchDecisions,
      assets: fetchAssets,
      calendar: fetchCalendar,
    };
    loaders[activeTab]?.();
  }, [activeTab]);

  // Reload tasks on filter change
  useEffect(() => {
    if (!loading && activeTab === 'tasks') fetchTasks();
  }, [taskStatusFilter, taskAgentFilter]);

  // Reload assets on filter change
  useEffect(() => {
    if (!loading && activeTab === 'assets') fetchAssets();
  }, [assetPillarFilter, assetStatusFilter]);

  // --- Actions ---

  const handleRefresh = async () => {
    setRefreshing(true);
    const loaders = {
      overview: () => Promise.all([fetchAgents(), fetchKpis()]),
      tasks: fetchTasks,
      decisions: fetchDecisions,
      assets: fetchAssets,
      calendar: fetchCalendar,
    };
    await loaders[activeTab]?.();
    setRefreshing(false);
  };

  const handleDecisionAction = async (uuid, action) => {
    try {
      const res = await fetch(`${API_URL}/agents/decisions/${uuid}/${action}`, {
        method: 'POST',
        headers: headers(),
      });
      if (!res.ok) throw new Error(`Failed to ${action} decision`);
      toast({ title: 'Success', description: `Decision ${action}d successfully` });
      fetchDecisions();
    } catch (err) {
      toast({ title: 'Error', description: err.message, variant: 'destructive' });
    }
  };

  const handleQuickAction = async (action) => {
    const actionMap = {
      'plan-week':          `${API_URL}/agents/calendar/plan-week`,
      'force-orchestrator': `${API_URL}/agents/orchestrator/run`,
    };
    const url = actionMap[action];
    if (!url) {
      toast({ title: 'Error', description: `Unknown action: ${action}`, variant: 'destructive' });
      return;
    }
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: headers(),
      });
      if (!res.ok) throw new Error(`Failed to execute ${action}`);
      const data = await res.json();
      toast({ title: 'Action Triggered', description: data.message || `${action} initiated` });
      // Refresh overview immediately
      fetchAgents();
      fetchKpis();
      // Refresh again after 5s to catch orchestrator results
      setTimeout(() => {
        fetchAgents();
        fetchKpis();
        fetchTasks();
        fetchDecisions();
        fetchCalendar();
      }, 5000);
    } catch (err) {
      toast({ title: 'Error', description: err.message, variant: 'destructive' });
    }
  };

  const handleCreateAsset = async () => {
    try {
      const res = await fetch(`${API_URL}/agents/content-assets/generate`, {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ asset_type: newAssetType }),
      });
      if (!res.ok) throw new Error('Failed to start asset creation');
      const data = await res.json();
      toast({ title: 'Started', description: data.message || 'Content generation started' });
      setShowNewAssetDialog(false);
      fetchAssets();
      fetchTasks();
      // Refresh again after 5s to catch results
      setTimeout(() => { fetchAssets(); fetchTasks(); }, 5000);
    } catch (err) {
      toast({ title: 'Error', description: err.message, variant: 'destructive' });
    }
  };

  // --- Derived data ---

  const agentCards = useMemo(() => {
    const defaults = [
      { key: 'cmo', label: 'CMO Agent', desc: 'Strategic Planning & Coordination', icon: Brain, color: 'text-violet-600' },
      { key: 'content', label: 'Content Agent', desc: 'Content Creation (Text, Image, Video)', icon: Palette, color: 'text-pink-600' },
      { key: 'social', label: 'Social Agent', desc: 'Publishing & Engagement', icon: Share2, color: 'text-sky-600' },
      { key: 'acquisition', label: 'Acquisition Agent', desc: 'Paid Ads & Optimization', icon: Target, color: 'text-amber-600' },
    ];
    return defaults.map((d) => {
      const live = agents.find((a) => a.key === d.key || a.name?.toLowerCase().includes(d.key));
      return {
        ...d,
        status: live?.status || 'idle',
        lastActivity: live?.last_activity || null,
        pendingTasks: live?.pending_tasks ?? 0,
      };
    });
  }, [agents]);

  // Calendar week view
  const calendarWeek = useMemo(() => {
    const days = [];
    const now = new Date();
    for (let i = 0; i < 7; i++) {
      const d = new Date(now);
      d.setDate(now.getDate() + i);
      const dateStr = d.toISOString().split('T')[0];
      const daySlots = calendarSlots.filter((s) => s.date === dateStr || s.scheduled_at?.startsWith(dateStr));
      days.push({
        date: d,
        label: d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }),
        isToday: i === 0,
        slots: daySlots,
      });
    }
    return days;
  }, [calendarSlots]);

  // --- Loading state ---

  if (loading) {
    return (
      <div className="p-6 space-y-6">
        <Skeleton className="h-8 w-72" />
        <div className="grid grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-36" />)}
        </div>
        <div className="grid grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-24" />)}
        </div>
        <Skeleton className="h-96" />
      </div>
    );
  }

  // ===================== RENDER =====================

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <Brain className="w-7 h-7 text-violet-600" />
            Agent Dashboard
          </h1>
          <p className="text-slate-500 mt-1">CMO agent hierarchy, tasks, decisions & content pipeline</p>
        </div>
        <Button variant="outline" size="sm" onClick={handleRefresh} disabled={refreshing}>
          <RefreshCw className={cn('w-4 h-4 mr-2', refreshing && 'animate-spin')} />
          Refresh
        </Button>
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <TabsList className="bg-slate-100">
          <TabsTrigger value="overview">
            <BarChart3 className="w-4 h-4 mr-2" />
            Overview
          </TabsTrigger>
          <TabsTrigger value="tasks">
            <Zap className="w-4 h-4 mr-2" />
            Tasks
          </TabsTrigger>
          <TabsTrigger value="decisions">
            <AlertCircle className="w-4 h-4 mr-2" />
            Decisions
          </TabsTrigger>
          <TabsTrigger value="assets">
            <Image className="w-4 h-4 mr-2" />
            Content Assets
          </TabsTrigger>
          <TabsTrigger value="calendar">
            <Calendar className="w-4 h-4 mr-2" />
            Calendar
          </TabsTrigger>
        </TabsList>

        {/* ==================== OVERVIEW TAB ==================== */}
        <TabsContent value="overview" className="space-y-6">
          {/* Agent hierarchy cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {agentCards.map((agent) => {
              const Icon = agent.icon;
              return (
                <Card key={agent.key} className="relative overflow-hidden">
                  <div className={cn(
                    'absolute top-0 left-0 w-1 h-full',
                    agent.status === 'active' ? 'bg-green-500' : 'bg-slate-300'
                  )} />
                  <CardHeader className="pb-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Icon className={cn('w-5 h-5', agent.color)} />
                        <CardTitle className="text-sm font-semibold">{agent.label}</CardTitle>
                      </div>
                      {statusBadge(agent.status)}
                    </div>
                    <CardDescription className="text-xs">{agent.desc}</CardDescription>
                  </CardHeader>
                  <CardContent className="pt-0">
                    <div className="flex items-center justify-between text-xs text-slate-500">
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {formatTimestamp(agent.lastActivity)}
                      </span>
                      <span className="flex items-center gap-1">
                        <FileText className="w-3 h-3" />
                        {agent.pendingTasks} pending
                      </span>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>

          {/* KPI cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center gap-2 text-slate-500 mb-1">
                  <Users className="w-4 h-4" />
                  <span className="text-xs font-medium uppercase tracking-wider">Follower Growth</span>
                </div>
                <p className="text-2xl font-bold">{kpis?.follower_growth != null ? `+${formatNumber(kpis.follower_growth)}` : '-'}</p>
                <p className="text-xs text-slate-400 mt-1">Last 7 days</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center gap-2 text-slate-500 mb-1">
                  <TrendingUp className="w-4 h-4" />
                  <span className="text-xs font-medium uppercase tracking-wider">Engagement Rate</span>
                </div>
                <p className="text-2xl font-bold">{kpis?.engagement_rate != null ? `${kpis.engagement_rate.toFixed(2)}%` : '-'}</p>
                <p className="text-xs text-slate-400 mt-1">Avg across channels</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center gap-2 text-slate-500 mb-1">
                  <Target className="w-4 h-4" />
                  <span className="text-xs font-medium uppercase tracking-wider">ROAS</span>
                </div>
                <p className="text-2xl font-bold">{kpis?.roas != null ? `${kpis.roas.toFixed(2)}x` : '-'}</p>
                <p className="text-xs text-slate-400 mt-1">Return on ad spend</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center gap-2 text-slate-500 mb-1">
                  <Palette className="w-4 h-4" />
                  <span className="text-xs font-medium uppercase tracking-wider">Assets Created</span>
                </div>
                <p className="text-2xl font-bold">{kpis?.content_assets_created ?? '-'}</p>
                <p className="text-xs text-slate-400 mt-1">This week</p>
              </CardContent>
            </Card>
          </div>

          {/* Quick actions */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium">Quick Actions</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-3">
                <Button onClick={() => handleQuickAction('plan-week')} className="gap-2">
                  <Calendar className="w-4 h-4" />
                  Plan This Week
                </Button>
                <Button variant="outline" onClick={() => handleQuickAction('force-orchestrator')} className="gap-2">
                  <Play className="w-4 h-4" />
                  Force Orchestrator Run
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Onboarding guidance - shown when all agents are idle */}
          {(!agents?.length || agents.every(a => a.status === 'idle' || !a.status)) && (
            <div className="bg-blue-50 dark:bg-blue-950/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
              <h4 className="font-medium text-blue-900 dark:text-blue-100 mb-1">👋 Get Started</h4>
              <p className="text-sm text-blue-700 dark:text-blue-300">
                Click <strong>"Plan This Week"</strong> above to have the CMO agent create your weekly content calendar.
                The agent will analyze your products and generate content tasks for Instagram, TikTok, and ads.
                After planning, check the <strong>Tasks</strong> and <strong>Calendar</strong> tabs to see the results.
              </p>
            </div>
          )}
        </TabsContent>

        {/* ==================== TASKS TAB ==================== */}
        <TabsContent value="tasks" className="space-y-4">
          {/* Filters */}
          <div className="flex items-center gap-4">
            <Select value={taskStatusFilter} onValueChange={setTaskStatusFilter}>
              <SelectTrigger className="w-[160px]">
                <SelectValue placeholder="Status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Statuses</SelectItem>
                <SelectItem value="awaiting_approval">Awaiting Approval</SelectItem>
                <SelectItem value="pending">Pending</SelectItem>
                <SelectItem value="in_progress">In Progress</SelectItem>
                <SelectItem value="completed">Completed</SelectItem>
                <SelectItem value="failed">Failed</SelectItem>
              </SelectContent>
            </Select>
            <Select value={taskAgentFilter} onValueChange={setTaskAgentFilter}>
              <SelectTrigger className="w-[160px]">
                <SelectValue placeholder="Agent" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Agents</SelectItem>
                <SelectItem value="cmo">CMO</SelectItem>
                <SelectItem value="content">Content</SelectItem>
                <SelectItem value="social">Social</SelectItem>
                <SelectItem value="acquisition">Acquisition</SelectItem>
              </SelectContent>
            </Select>
            <Badge variant="outline" className="ml-auto">{tasks.length} tasks</Badge>
          </div>

          {/* Tasks table */}
          <Card>
            <CardContent className="pt-6">
              {tasks.length === 0 ? (
                <div className="text-center py-12 text-slate-500">
                  <Zap className="w-10 h-10 mx-auto mb-3 text-slate-300" />
                  <p>No tasks found for the selected filters</p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Task Type</TableHead>
                        <TableHead>Source / Target</TableHead>
                        <TableHead>Priority</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Created</TableHead>
                        <TableHead>Duration</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {tasks.map((task) => (
                        <TableRow
                          key={task.uuid || task.id}
                          className="cursor-pointer hover:bg-slate-50"
                          onClick={() => setSelectedTask(task)}
                        >
                          <TableCell className="font-medium">{task.task_type || task.type || '-'}</TableCell>
                          <TableCell className="text-sm text-slate-600">
                            <span className="flex items-center gap-1">
                              {task.source_agent || '-'}
                              <ArrowRight className="w-3 h-3 text-slate-400" />
                              {task.target_agent || '-'}
                            </span>
                          </TableCell>
                          <TableCell>{priorityBadge(task.priority)}</TableCell>
                          <TableCell>{statusBadge(task.status)}</TableCell>
                          <TableCell className="text-sm text-slate-500">{formatTimestamp(task.created_at)}</TableCell>
                          <TableCell className="text-sm text-slate-500">{formatDuration(task.duration_seconds)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Task detail dialog */}
          <Dialog open={!!selectedTask} onOpenChange={() => setSelectedTask(null)}>
            <DialogContent className="max-w-lg">
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <Zap className="w-5 h-5" />
                  Task Details
                </DialogTitle>
              </DialogHeader>
              {selectedTask && (
                <ScrollArea className="max-h-[60vh]">
                  <div className="space-y-4 pr-4">
                    <div className="flex items-center gap-2">
                      {statusBadge(selectedTask.status)}
                      {priorityBadge(selectedTask.priority)}
                    </div>
                    <div>
                      <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">Type</p>
                      <p className="text-sm font-medium">{selectedTask.task_type || selectedTask.type}</p>
                    </div>
                    <div>
                      <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">Route</p>
                      <p className="text-sm">{selectedTask.source_agent} &rarr; {selectedTask.target_agent}</p>
                    </div>
                    {selectedTask.params && (
                      <div>
                        <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">Parameters</p>
                        <pre className="text-xs bg-slate-50 p-3 rounded-lg overflow-x-auto border">
                          {JSON.stringify(selectedTask.params, null, 2)}
                        </pre>
                      </div>
                    )}
                    {selectedTask.result && (
                      <div>
                        <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">Result</p>
                        <pre className="text-xs bg-green-50 p-3 rounded-lg overflow-x-auto border border-green-200">
                          {typeof selectedTask.result === 'string'
                            ? selectedTask.result
                            : JSON.stringify(selectedTask.result, null, 2)}
                        </pre>
                      </div>
                    )}
                    {selectedTask.error && (
                      <div>
                        <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">Error</p>
                        <pre className="text-xs bg-red-50 p-3 rounded-lg overflow-x-auto border border-red-200 text-red-700">
                          {selectedTask.error}
                        </pre>
                      </div>
                    )}
                    <Separator />
                    <div className="grid grid-cols-2 gap-4 text-sm">
                      <div>
                        <p className="text-xs text-slate-500">Created</p>
                        <p>{formatTimestamp(selectedTask.created_at)}</p>
                      </div>
                      <div>
                        <p className="text-xs text-slate-500">Duration</p>
                        <p>{formatDuration(selectedTask.duration_seconds)}</p>
                      </div>
                    </div>
                  </div>
                </ScrollArea>
              )}
            </DialogContent>
          </Dialog>
        </TabsContent>

        {/* ==================== DECISIONS TAB ==================== */}
        <TabsContent value="decisions" className="space-y-4">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="flex items-center gap-2 text-lg">
                  <AlertCircle className="w-5 h-5 text-amber-600" />
                  Pending & Recent Decisions
                </CardTitle>
                <Badge variant="outline">{decisions.length} total</Badge>
              </div>
            </CardHeader>
            <CardContent>
              {decisions.length === 0 ? (
                <div className="text-center py-12 text-slate-500">
                  <CheckCircle className="w-10 h-10 mx-auto mb-3 text-slate-300" />
                  <p>No decisions to review</p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Agent</TableHead>
                        <TableHead>Decision Type</TableHead>
                        <TableHead>Reasoning</TableHead>
                        <TableHead>Confidence</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead className="text-right">Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {decisions.map((decision) => (
                        <TableRow
                          key={decision.uuid || decision.id}
                          className="cursor-pointer hover:bg-slate-50"
                          onClick={() => setSelectedDecision(decision)}
                        >
                          <TableCell>{agentBadge(decision.agent)}</TableCell>
                          <TableCell className="font-medium text-sm">{decision.decision_type || decision.type || '-'}</TableCell>
                          <TableCell className="text-sm text-slate-600 max-w-[200px]">
                            <TooltipProvider>
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <span className="truncate block">{truncate(decision.reasoning, 60)}</span>
                                </TooltipTrigger>
                                <TooltipContent className="max-w-sm">
                                  <p>{decision.reasoning}</p>
                                </TooltipContent>
                              </Tooltip>
                            </TooltipProvider>
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-2 min-w-[100px]">
                              <Progress value={(decision.confidence || 0) * 100} className="h-2 flex-1" />
                              <span className="text-xs text-slate-500 w-10 text-right">
                                {((decision.confidence || 0) * 100).toFixed(0)}%
                              </span>
                            </div>
                          </TableCell>
                          <TableCell>
                            {decision.status === 'pending_approval' || decision.status === 'pending' ? (
                              <Badge className="bg-amber-100 text-amber-700 border-0 font-medium">Pending Approval</Badge>
                            ) : decision.status === 'approved' ? (
                              <Badge className="bg-green-100 text-green-700 border-0 font-medium">Approved</Badge>
                            ) : decision.status === 'rejected' ? (
                              <Badge className="bg-red-100 text-red-700 border-0 font-medium">Rejected</Badge>
                            ) : (
                              statusBadge(decision.status)
                            )}
                          </TableCell>
                          <TableCell className="text-right">
                            {(decision.status === 'pending_approval' || decision.status === 'pending') && (
                              <div className="flex items-center justify-end gap-2" onClick={(e) => e.stopPropagation()}>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="text-green-700 border-green-300 hover:bg-green-50"
                                  onClick={() => handleDecisionAction(decision.uuid, 'approve')}
                                >
                                  <ThumbsUp className="w-3 h-3 mr-1" />
                                  Approve
                                </Button>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="text-red-700 border-red-300 hover:bg-red-50"
                                  onClick={() => handleDecisionAction(decision.uuid, 'reject')}
                                >
                                  <ThumbsDown className="w-3 h-3 mr-1" />
                                  Reject
                                </Button>
                              </div>
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Decision detail dialog */}
          <Dialog open={!!selectedDecision} onOpenChange={() => setSelectedDecision(null)}>
            <DialogContent className="max-w-lg">
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <AlertCircle className="w-5 h-5 text-amber-600" />
                  Decision Detail
                </DialogTitle>
              </DialogHeader>
              {selectedDecision && (
                <ScrollArea className="max-h-[60vh]">
                  <div className="space-y-4 pr-4">
                    <div className="flex items-center gap-2 flex-wrap">
                      {agentBadge(selectedDecision.agent)}
                      <Badge variant="outline" className="font-medium">{selectedDecision.decision_type || selectedDecision.type}</Badge>
                    </div>
                    <div>
                      <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">Reasoning</p>
                      <p className="text-sm text-slate-700 bg-slate-50 p-3 rounded-lg border">{selectedDecision.reasoning || '-'}</p>
                    </div>
                    <div>
                      <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">Confidence</p>
                      <div className="flex items-center gap-3">
                        <Progress value={(selectedDecision.confidence || 0) * 100} className="h-3 flex-1" />
                        <span className="text-sm font-medium">{((selectedDecision.confidence || 0) * 100).toFixed(0)}%</span>
                      </div>
                    </div>
                    {selectedDecision.context && (
                      <div>
                        <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">Context</p>
                        <pre className="text-xs bg-slate-50 p-3 rounded-lg overflow-x-auto border">
                          {JSON.stringify(selectedDecision.context, null, 2)}
                        </pre>
                      </div>
                    )}
                    {selectedDecision.decision_data && (
                      <div>
                        <p className="text-xs text-slate-500 uppercase tracking-wider mb-1">Decision JSON</p>
                        <pre className="text-xs bg-slate-50 p-3 rounded-lg overflow-x-auto border">
                          {JSON.stringify(selectedDecision.decision_data, null, 2)}
                        </pre>
                      </div>
                    )}
                    <Separator />
                    <div className="grid grid-cols-2 gap-4 text-sm">
                      <div>
                        <p className="text-xs text-slate-500">Created</p>
                        <p>{formatTimestamp(selectedDecision.created_at)}</p>
                      </div>
                      <div>
                        <p className="text-xs text-slate-500">Status</p>
                        <p className="capitalize">{selectedDecision.status?.replace(/_/g, ' ')}</p>
                      </div>
                    </div>
                  </div>
                </ScrollArea>
              )}
            </DialogContent>
          </Dialog>
        </TabsContent>

        {/* ==================== CONTENT ASSETS TAB ==================== */}
        <TabsContent value="assets" className="space-y-4">
          {/* Filters + action */}
          <div className="flex items-center gap-4">
            <Select value={assetPillarFilter} onValueChange={setAssetPillarFilter}>
              <SelectTrigger className="w-[160px]">
                <SelectValue placeholder="Pillar" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Pillars</SelectItem>
                <SelectItem value="educational">Educational</SelectItem>
                <SelectItem value="promotional">Promotional</SelectItem>
                <SelectItem value="engagement">Engagement</SelectItem>
                <SelectItem value="behind_scenes">Behind the Scenes</SelectItem>
                <SelectItem value="ugc">UGC</SelectItem>
              </SelectContent>
            </Select>
            <Select value={assetStatusFilter} onValueChange={setAssetStatusFilter}>
              <SelectTrigger className="w-[140px]">
                <SelectValue placeholder="Status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Statuses</SelectItem>
                <SelectItem value="draft">Draft</SelectItem>
                <SelectItem value="ready">Ready</SelectItem>
                <SelectItem value="approved">Approved</SelectItem>
                <SelectItem value="archived">Archived</SelectItem>
              </SelectContent>
            </Select>
            <div className="ml-auto flex items-center gap-2">
              <Badge variant="outline">{assets.length} assets</Badge>
              <Button size="sm" onClick={() => setShowNewAssetDialog(true)} className="gap-2">
                <Plus className="w-4 h-4" />
                Generate New Asset
              </Button>
            </div>
          </div>

          {/* Asset grid */}
          {assets.length === 0 ? (
            <Card>
              <CardContent className="py-12">
                <div className="text-center text-slate-500">
                  <Image className="w-10 h-10 mx-auto mb-3 text-slate-300" />
                  <p>No content assets found for the selected filters</p>
                </div>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {assets.map((asset) => (
                <Card key={asset.uuid || asset.id} className="overflow-hidden">
                  {/* Thumbnail */}
                  <div className="h-40 bg-slate-100 flex items-center justify-center">
                    {asset.thumbnail_url ? (
                      <img
                        src={asset.thumbnail_url}
                        alt={asset.title || 'Asset thumbnail'}
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <Image className="w-12 h-12 text-slate-300" />
                    )}
                  </div>
                  <CardContent className="pt-4 space-y-3">
                    {/* Title + status */}
                    <div className="flex items-start justify-between gap-2">
                      <p className="font-medium text-sm line-clamp-2">{asset.title || 'Untitled Asset'}</p>
                      {statusBadge(asset.status)}
                    </div>
                    {/* Pillar + usage */}
                    <div className="flex flex-wrap items-center gap-1.5">
                      {pillarBadge(asset.content_pillar)}
                      {asset.usage?.map((u) => (
                        <Badge key={u} variant="outline" className="text-xs capitalize">{u}</Badge>
                      ))}
                    </div>
                    {/* Mini stats */}
                    <div className="flex items-center gap-4 text-xs text-slate-500 pt-1 border-t">
                      <span className="flex items-center gap-1">
                        <Eye className="w-3 h-3" />
                        {formatNumber(asset.impressions)}
                      </span>
                      <span className="flex items-center gap-1">
                        <TrendingUp className="w-3 h-3" />
                        {formatNumber(asset.engagement)}
                      </span>
                      <span className="flex items-center gap-1">
                        <MousePointer className="w-3 h-3" />
                        {formatNumber(asset.clicks)}
                      </span>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          {/* New asset dialog */}
          <Dialog open={showNewAssetDialog} onOpenChange={setShowNewAssetDialog}>
            <DialogContent className="max-w-sm">
              <DialogHeader>
                <DialogTitle>Generate New Asset</DialogTitle>
              </DialogHeader>
              <div className="space-y-4">
                <div>
                  <p className="text-sm text-slate-600 mb-2">Select asset type to queue for generation:</p>
                  <Select value={newAssetType} onValueChange={setNewAssetType}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="social_post">Social Post</SelectItem>
                      <SelectItem value="story">Story</SelectItem>
                      <SelectItem value="reel">Reel / Short Video</SelectItem>
                      <SelectItem value="carousel">Carousel</SelectItem>
                      <SelectItem value="blog_post">Blog Post</SelectItem>
                      <SelectItem value="ad_creative">Ad Creative</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex justify-end gap-2">
                  <Button variant="outline" onClick={() => setShowNewAssetDialog(false)}>Cancel</Button>
                  <Button onClick={handleCreateAsset} className="gap-2">
                    <Plus className="w-4 h-4" />
                    Queue Generation
                  </Button>
                </div>
              </div>
            </DialogContent>
          </Dialog>
        </TabsContent>

        {/* ==================== CALENDAR TAB ==================== */}
        <TabsContent value="calendar" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <Calendar className="w-5 h-5 text-indigo-600" />
                Weekly Publishing Schedule
              </CardTitle>
              <CardDescription>Next 7 days content calendar</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-7 gap-3">
                {calendarWeek.map((day) => (
                  <div
                    key={day.label}
                    className={cn(
                      'border rounded-lg min-h-[200px]',
                      day.isToday ? 'border-indigo-400 bg-indigo-50/30' : 'border-slate-200'
                    )}
                  >
                    {/* Day header */}
                    <div className={cn(
                      'px-2 py-1.5 text-xs font-semibold border-b text-center',
                      day.isToday ? 'bg-indigo-100 text-indigo-700 border-indigo-200' : 'bg-slate-50 text-slate-600'
                    )}>
                      {day.label}
                    </div>
                    {/* Slots */}
                    <div className="p-1.5 space-y-1.5">
                      {day.slots.length === 0 ? (
                        <p className="text-xs text-slate-400 text-center py-4">No posts</p>
                      ) : (
                        day.slots.map((slot, i) => {
                          const slotColorMap = {
                            planned:     'bg-slate-50 border-slate-200',
                            asset_ready: 'bg-blue-50 border-blue-200',
                            published:   'bg-green-50 border-green-200',
                            cancelled:   'bg-red-50 border-red-200',
                          };
                          const slotColor = slotColorMap[slot.status] || slotColorMap.planned;
                          return (
                            <div key={slot.id || i} className={cn('p-1.5 rounded border text-xs', slotColor)}>
                              <div className="flex items-center gap-1 mb-0.5">
                                {channelIcon(slot.channel)}
                                <span className="text-slate-500 font-medium">
                                  {slot.time || (slot.scheduled_at ? new Date(slot.scheduled_at).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }) : '')}
                                </span>
                              </div>
                              <p className="text-slate-700 font-medium truncate">{slot.post_type || slot.title || 'Post'}</p>
                              <div className="mt-0.5">
                                {statusBadge(slot.status)}
                              </div>
                            </div>
                          );
                        })
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
