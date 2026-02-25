import React, { useState, useEffect, useMemo } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { useToast } from '@/components/ui/use-toast';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Switch } from '@/components/ui/switch';
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
  DialogFooter,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Target,
  TrendingUp,
  TrendingDown,
  DollarSign,
  MousePointer,
  ShoppingCart,
  Eye,
  Play,
  Pause,
  RefreshCw,
  Plus,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  CheckCircle,
  Clock,
  Zap,
  BarChart3,
  Activity,
  ArrowUpRight,
  ArrowDownRight,
  Lightbulb,
  Settings,
  Users,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import AgentActivityPanel from '@/components/AgentActivityPanel';

// Meta Ads API - use proxy routes in production, direct in development
const API_URL = import.meta.env.DEV ? 'http://localhost:8080' : '/api';

// Health score color helper
const getHealthColor = (score) => {
  if (score >= 70) return 'text-green-600 bg-green-100';
  if (score >= 50) return 'text-yellow-600 bg-yellow-100';
  return 'text-red-600 bg-red-100';
};

// Status badge helper
const getStatusBadge = (status) => {
  const statusMap = {
    'ACTIVE': { color: 'bg-green-100 text-green-700', label: 'Active' },
    'PAUSED': { color: 'bg-yellow-100 text-yellow-700', label: 'Paused' },
    'LEARNING': { color: 'bg-blue-100 text-blue-700', label: 'Learning' },
    'DELETED': { color: 'bg-gray-100 text-gray-700', label: 'Deleted' },
  };
  const config = statusMap[status] || { color: 'bg-gray-100 text-gray-700', label: status };
  return <Badge className={cn(config.color, 'font-medium')}>{config.label}</Badge>;
};

// Decision type badge
const getDecisionBadge = (type) => {
  const typeMap = {
    'SCALE': { color: 'bg-green-100 text-green-700 border-green-300', icon: TrendingUp },
    'PAUSE': { color: 'bg-red-100 text-red-700 border-red-300', icon: Pause },
    'MAINTAIN': { color: 'bg-blue-100 text-blue-700 border-blue-300', icon: CheckCircle },
    'LEARNING': { color: 'bg-purple-100 text-purple-700 border-purple-300', icon: Clock },
    'ALERT': { color: 'bg-yellow-100 text-yellow-700 border-yellow-300', icon: AlertTriangle },
  };
  const config = typeMap[type] || typeMap['MAINTAIN'];
  const Icon = config.icon;
  return (
    <Badge className={cn(config.color, 'border font-medium flex items-center gap-1')}>
      <Icon className="w-3 h-3" />
      {type}
    </Badge>
  );
};

export default function Marketing() {
  const { getAuthHeader } = useAuth();
  const { toast } = useToast();

  // State
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [campaigns, setCampaigns] = useState([]);
  const [creatives, setCreatives] = useState([]);
  const [audiences, setAudiences] = useState([]);
  const [targetingPresets, setTargetingPresets] = useState([]);
  const [expandedCampaigns, setExpandedCampaigns] = useState(new Set());
  const [dateRange, setDateRange] = useState('today');

  // Create campaign dialog state
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [createStep, setCreateStep] = useState(1);
  const [newCampaign, setNewCampaign] = useState({
    name: '',
    objective: 'OUTCOME_SALES',
    dailyBudget: 2500,
    targetingPreset: '',
    creativeId: '',
  });
  const [isCreating, setIsCreating] = useState(false);

  // Fetch status
  const fetchStatus = async () => {
    try {
      const response = await fetch(`${API_URL}/meta-ads/status?date_range=${dateRange}`, {
        headers: getAuthHeader()
      });
      if (!response.ok) throw new Error('Failed to fetch status');
      const data = await response.json();
      setStatus(data);
    } catch (err) {
      console.error('Failed to fetch status:', err);
      toast({ title: 'Error', description: err.message, variant: 'destructive' });
    }
  };

  // Fetch analysis
  const fetchAnalysis = async () => {
    try {
      const response = await fetch(`${API_URL}/meta-ads/analysis?date_range=${dateRange}`, {
        headers: getAuthHeader()
      });
      if (!response.ok) throw new Error('Failed to fetch analysis');
      const data = await response.json();
      setAnalysis(data);
    } catch (err) {
      console.error('Failed to fetch analysis:', err);
    }
  };

  // Fetch campaigns
  const fetchCampaigns = async () => {
    try {
      const response = await fetch(`${API_URL}/meta-ads/campaigns`, {
        headers: getAuthHeader()
      });
      if (!response.ok) throw new Error('Failed to fetch campaigns');
      const data = await response.json();
      setCampaigns(data.campaigns || []);
    } catch (err) {
      console.error('Failed to fetch campaigns:', err);
    }
  };

  // Fetch creatives
  const fetchCreatives = async () => {
    try {
      const response = await fetch(`${API_URL}/meta-ads/creatives`, {
        headers: getAuthHeader()
      });
      if (!response.ok) throw new Error('Failed to fetch creatives');
      const data = await response.json();
      setCreatives(data.creatives || []);
    } catch (err) {
      console.error('Failed to fetch creatives:', err);
    }
  };

  // Fetch targeting presets
  const fetchTargetingPresets = async () => {
    try {
      const response = await fetch(`${API_URL}/meta-ads/targeting-presets`, {
        headers: getAuthHeader()
      });
      if (!response.ok) throw new Error('Failed to fetch presets');
      const data = await response.json();
      setTargetingPresets(data.presets || []);
    } catch (err) {
      console.error('Failed to fetch presets:', err);
    }
  };

  // Fetch audiences
  const fetchAudiences = async () => {
    try {
      const response = await fetch(`${API_URL}/meta-ads/audiences`, {
        headers: getAuthHeader()
      });
      if (!response.ok) throw new Error('Failed to fetch audiences');
      const data = await response.json();
      setAudiences(data.audiences || []);
    } catch (err) {
      console.error('Failed to fetch audiences:', err);
    }
  };

  // Initial load
  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      await Promise.all([
        fetchStatus(),
        fetchAnalysis(),
        fetchCampaigns(),
        fetchCreatives(),
        fetchTargetingPresets(),
        fetchAudiences(),
      ]);
      setLoading(false);
    };
    loadData();
  }, [dateRange]);

  // Toggle campaign status
  const toggleStatus = async (entityId, currentStatus) => {
    const newStatus = currentStatus === 'ACTIVE' ? 'PAUSED' : 'ACTIVE';
    try {
      const response = await fetch(`${API_URL}/meta-ads/execute-decision?entity_id=${entityId}&action=${newStatus}`, {
        method: 'POST',
        headers: getAuthHeader()
      });
      if (!response.ok) throw new Error('Failed to update status');
      toast({ title: 'Success', description: `Status updated to ${newStatus}` });
      fetchCampaigns();
    } catch (err) {
      toast({ title: 'Error', description: err.message, variant: 'destructive' });
    }
  };

  // Execute decision
  const executeDecision = async (entityId, action) => {
    try {
      const response = await fetch(`${API_URL}/meta-ads/execute-decision?entity_id=${entityId}&action=${action}`, {
        method: 'POST',
        headers: getAuthHeader()
      });
      if (!response.ok) throw new Error('Failed to execute decision');
      toast({ title: 'Success', description: `Action ${action} executed successfully` });
      fetchCampaigns();
      fetchAnalysis();
    } catch (err) {
      toast({ title: 'Error', description: err.message, variant: 'destructive' });
    }
  };

  // Create campaign
  const createCampaign = async () => {
    setIsCreating(true);
    try {
      // Step 1: Create campaign
      const campaignRes = await fetch(`${API_URL}/meta-ads/campaigns/create`, {
        method: 'POST',
        headers: { ...getAuthHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newCampaign.name,
          objective: newCampaign.objective,
          status: 'PAUSED'
        })
      });
      if (!campaignRes.ok) {
        const err = await campaignRes.json();
        throw new Error(err.detail || 'Failed to create campaign');
      }
      const campaignData = await campaignRes.json();

      // Step 2: Create ad set
      const selectedPreset = targetingPresets.find(p => p.name === newCampaign.targetingPreset);
      const targeting = selectedPreset?.targeting || targetingPresets[0]?.targeting;

      const adsetRes = await fetch(`${API_URL}/meta-ads/adsets/create`, {
        method: 'POST',
        headers: { ...getAuthHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          campaign_id: campaignData.campaign_id,
          name: `${newCampaign.name} - Ad Set`,
          daily_budget: newCampaign.dailyBudget,
          targeting: targeting,
          optimization_goal: 'OFFSITE_CONVERSIONS',
          status: 'PAUSED'
        })
      });
      if (!adsetRes.ok) {
        const err = await adsetRes.json();
        throw new Error(err.detail || 'Failed to create ad set');
      }
      const adsetData = await adsetRes.json();

      // Step 3: Create ad (if creative selected)
      if (newCampaign.creativeId) {
        const adRes = await fetch(`${API_URL}/meta-ads/ads/create`, {
          method: 'POST',
          headers: { ...getAuthHeader(), 'Content-Type': 'application/json' },
          body: JSON.stringify({
            adset_id: adsetData.adset_id,
            creative_id: newCampaign.creativeId,
            name: `${newCampaign.name} - Ad`,
            status: 'PAUSED'
          })
        });
        if (!adRes.ok) {
          const err = await adRes.json();
          throw new Error(err.detail || 'Failed to create ad');
        }
      }

      toast({ title: 'Campaign Created', description: `"${newCampaign.name}" created successfully (PAUSED)` });
      setCreateDialogOpen(false);
      setCreateStep(1);
      setNewCampaign({ name: '', objective: 'OUTCOME_SALES', dailyBudget: 2500, targetingPreset: '', creativeId: '' });
      fetchCampaigns();

    } catch (err) {
      toast({ title: 'Error', description: err.message, variant: 'destructive' });
    } finally {
      setIsCreating(false);
    }
  };

  // Toggle expanded campaign
  const toggleExpanded = (campaignId) => {
    setExpandedCampaigns(prev => {
      const next = new Set(prev);
      if (next.has(campaignId)) {
        next.delete(campaignId);
      } else {
        next.add(campaignId);
      }
      return next;
    });
  };

  // Loading state
  if (loading) {
    return (
      <div className="p-6 space-y-6">
        <Skeleton className="h-8 w-64" />
        <div className="grid grid-cols-4 gap-4">
          {[1,2,3,4].map(i => <Skeleton key={i} className="h-32" />)}
        </div>
        <Skeleton className="h-96" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Agent Activity Panel */}
      <AgentActivityPanel context="marketing" />

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <Target className="w-7 h-7 text-indigo-600" />
            Meta Ads Marketing
          </h1>
          <p className="text-slate-500 mt-1">Campaign management and AI optimization</p>
        </div>
        <div className="flex items-center gap-3">
          <Select value={dateRange} onValueChange={setDateRange}>
            <SelectTrigger className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="today">Today</SelectItem>
              <SelectItem value="yesterday">Yesterday</SelectItem>
              <SelectItem value="last_7d">Last 7 Days</SelectItem>
              <SelectItem value="last_30d">Last 30 Days</SelectItem>
              <SelectItem value="this_month">This Month</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="outline" onClick={() => { fetchStatus(); fetchAnalysis(); fetchCampaigns(); }}>
            <RefreshCw className="w-4 h-4 mr-2" />
            Refresh
          </Button>
          <Button onClick={() => setCreateDialogOpen(true)}>
            <Plus className="w-4 h-4 mr-2" />
            Create Campaign
          </Button>
        </div>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList className="bg-slate-100">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="campaigns">Campaigns</TabsTrigger>
          <TabsTrigger value="optimization">Optimization</TabsTrigger>
          <TabsTrigger value="analytics">Analytics</TabsTrigger>
        </TabsList>

        {/* Overview Tab */}
        <TabsContent value="overview" className="space-y-4">
          {/* Health Score & Metrics */}
          <div className="grid grid-cols-5 gap-4">
            {/* Health Score */}
            <Card className="col-span-1">
              <CardContent className="pt-6">
                <div className="text-center">
                  <div className={cn(
                    "inline-flex items-center justify-center w-20 h-20 rounded-full text-3xl font-bold",
                    getHealthColor(status?.health_score || 0)
                  )}>
                    {status?.health_score || 0}
                  </div>
                  <p className="text-sm text-slate-500 mt-2">Health Score</p>
                  <Badge className={cn(
                    "mt-1",
                    status?.status === 'HEALTHY' ? 'bg-green-100 text-green-700' : 'bg-yellow-100 text-yellow-700'
                  )}>
                    {status?.status || 'Unknown'}
                  </Badge>
                </div>
              </CardContent>
            </Card>

            {/* Spend */}
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center gap-2 text-slate-500">
                  <DollarSign className="w-4 h-4" />
                  <span className="text-sm">Spend</span>
                </div>
                <p className="text-2xl font-bold mt-1">{status?.spend || '€0.00'}</p>
                <p className="text-xs text-slate-400 mt-1">{dateRange === 'today' ? 'Today' : dateRange}</p>
              </CardContent>
            </Card>

            {/* CTR */}
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center gap-2 text-slate-500">
                  <MousePointer className="w-4 h-4" />
                  <span className="text-sm">CTR</span>
                </div>
                <p className="text-2xl font-bold mt-1">{status?.ctr || '0.00%'}</p>
                <p className="text-xs text-slate-400 mt-1">{status?.clicks || 0} clicks</p>
              </CardContent>
            </Card>

            {/* CPA */}
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center gap-2 text-slate-500">
                  <ShoppingCart className="w-4 h-4" />
                  <span className="text-sm">CPA</span>
                </div>
                <p className="text-2xl font-bold mt-1">{status?.cpa || 'N/A'}</p>
                <p className="text-xs text-slate-400 mt-1">{status?.purchases || 0} purchases</p>
              </CardContent>
            </Card>

            {/* ROAS */}
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center gap-2 text-slate-500">
                  <TrendingUp className="w-4 h-4" />
                  <span className="text-sm">ROAS</span>
                </div>
                <p className="text-2xl font-bold mt-1">{status?.roas || 'N/A'}</p>
                <p className="text-xs text-slate-400 mt-1">Return on ad spend</p>
              </CardContent>
            </Card>
          </div>

          {/* Alerts & Recommendations */}
          <div className="grid grid-cols-2 gap-4">
            {/* Alerts */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <AlertTriangle className="w-5 h-5 text-yellow-600" />
                  Alerts
                </CardTitle>
              </CardHeader>
              <CardContent>
                {analysis?.alerts?.length > 0 ? (
                  <div className="space-y-3">
                    {analysis.alerts.map((alert, i) => (
                      <div key={i} className={cn(
                        "p-3 rounded-lg border",
                        alert.severity === 'CRITICAL' ? 'bg-red-50 border-red-200' : 'bg-yellow-50 border-yellow-200'
                      )}>
                        <div className="flex items-center gap-2">
                          <Badge variant="outline" className={alert.severity === 'CRITICAL' ? 'border-red-300 text-red-700' : 'border-yellow-300 text-yellow-700'}>
                            {alert.severity}
                          </Badge>
                          <span className="font-medium text-sm">{alert.type}</span>
                        </div>
                        <p className="text-sm text-slate-600 mt-1">{alert.message}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-slate-400 text-sm">No alerts at this time</p>
                )}
              </CardContent>
            </Card>

            {/* Recommendations */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <Lightbulb className="w-5 h-5 text-blue-600" />
                  Recommendations
                </CardTitle>
              </CardHeader>
              <CardContent>
                {analysis?.recommendations?.length > 0 ? (
                  <div className="space-y-3">
                    {analysis.recommendations.map((rec, i) => (
                      <div key={i} className="p-3 rounded-lg bg-slate-50 border border-slate-200">
                        <div className="flex items-center gap-2">
                          <Badge className={cn(
                            rec.priority === 'HIGH' ? 'bg-red-100 text-red-700' :
                            rec.priority === 'MEDIUM' ? 'bg-yellow-100 text-yellow-700' :
                            'bg-slate-100 text-slate-700'
                          )}>
                            {rec.priority}
                          </Badge>
                          <span className="font-medium text-sm">{rec.title}</span>
                        </div>
                        <p className="text-sm text-slate-600 mt-1">{rec.description}</p>
                        {rec.potential_impact && (
                          <p className="text-xs text-slate-400 mt-1">Impact: {rec.potential_impact}</p>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-slate-400 text-sm">No recommendations available</p>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Active Campaigns Quick View */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <Activity className="w-5 h-5 text-indigo-600" />
                Active Campaigns
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {campaigns.filter(c => c.status === 'ACTIVE').length > 0 ? (
                  campaigns.filter(c => c.status === 'ACTIVE').map(campaign => (
                    <div key={campaign.id} className="flex items-center justify-between p-3 bg-slate-50 rounded-lg">
                      <div className="flex items-center gap-3">
                        <div className="w-2 h-2 rounded-full bg-green-500"></div>
                        <span className="font-medium">{campaign.name}</span>
                        <Badge variant="outline">{campaign.adsets?.length || 0} ad sets</Badge>
                      </div>
                      <Button variant="ghost" size="sm" onClick={() => toggleStatus(campaign.id, 'ACTIVE')}>
                        <Pause className="w-4 h-4 mr-1" />
                        Pause
                      </Button>
                    </div>
                  ))
                ) : (
                  <p className="text-slate-400 text-sm">No active campaigns</p>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Campaigns Tab */}
        <TabsContent value="campaigns" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span className="flex items-center gap-2">
                  <Target className="w-5 h-5" />
                  All Campaigns
                </span>
                <Badge variant="outline">{campaigns.length} total</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-8"></TableHead>
                    <TableHead>Campaign</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Objective</TableHead>
                    <TableHead>Ad Sets</TableHead>
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {campaigns.map(campaign => (
                    <React.Fragment key={campaign.id}>
                      <TableRow className="cursor-pointer hover:bg-slate-50" onClick={() => toggleExpanded(campaign.id)}>
                        <TableCell>
                          {campaign.adsets?.length > 0 && (
                            expandedCampaigns.has(campaign.id) ?
                              <ChevronDown className="w-4 h-4 text-slate-400" /> :
                              <ChevronRight className="w-4 h-4 text-slate-400" />
                          )}
                        </TableCell>
                        <TableCell className="font-medium">{campaign.name}</TableCell>
                        <TableCell>{getStatusBadge(campaign.status)}</TableCell>
                        <TableCell className="text-sm text-slate-500">{campaign.objective}</TableCell>
                        <TableCell>{campaign.adsets?.length || 0}</TableCell>
                        <TableCell>
                          <div className="flex gap-2" onClick={e => e.stopPropagation()}>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => toggleStatus(campaign.id, campaign.status)}
                            >
                              {campaign.status === 'ACTIVE' ? (
                                <><Pause className="w-3 h-3 mr-1" /> Pause</>
                              ) : (
                                <><Play className="w-3 h-3 mr-1" /> Activate</>
                              )}
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                      {/* Expanded ad sets */}
                      {expandedCampaigns.has(campaign.id) && campaign.adsets?.map(adset => (
                        <React.Fragment key={adset.id}>
                          <TableRow className="bg-slate-50">
                            <TableCell></TableCell>
                            <TableCell className="pl-8">
                              <span className="text-slate-600">↳ {adset.name}</span>
                            </TableCell>
                            <TableCell>{getStatusBadge(adset.status)}</TableCell>
                            <TableCell className="text-sm text-slate-400">Ad Set</TableCell>
                            <TableCell>{adset.ads?.length || 0} ads</TableCell>
                            <TableCell>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => toggleStatus(adset.id, adset.status)}
                              >
                                {adset.status === 'ACTIVE' ? <Pause className="w-3 h-3" /> : <Play className="w-3 h-3" />}
                              </Button>
                            </TableCell>
                          </TableRow>
                          {/* Ads */}
                          {adset.ads?.map(ad => (
                            <TableRow key={ad.id} className="bg-slate-100/50">
                              <TableCell></TableCell>
                              <TableCell className="pl-16">
                                <span className="text-slate-500">↳ {ad.name}</span>
                              </TableCell>
                              <TableCell>{getStatusBadge(ad.status)}</TableCell>
                              <TableCell className="text-sm text-slate-400">Ad</TableCell>
                              <TableCell></TableCell>
                              <TableCell>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => toggleStatus(ad.id, ad.status)}
                                >
                                  {ad.status === 'ACTIVE' ? <Pause className="w-3 h-3" /> : <Play className="w-3 h-3" />}
                                </Button>
                              </TableCell>
                            </TableRow>
                          ))}
                        </React.Fragment>
                      ))}
                    </React.Fragment>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Optimization Tab */}
        <TabsContent value="optimization" className="space-y-4">
          {/* Config */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Settings className="w-5 h-5" />
                Optimization Thresholds
              </CardTitle>
              <CardDescription>Current AI decision engine configuration</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-4 gap-4">
                <div className="p-3 bg-slate-50 rounded-lg">
                  <p className="text-xs text-slate-500">Target CPA</p>
                  <p className="text-lg font-bold">€{analysis?.config?.target_cpa || 25}</p>
                </div>
                <div className="p-3 bg-slate-50 rounded-lg">
                  <p className="text-xs text-slate-500">Max CPA</p>
                  <p className="text-lg font-bold">€{analysis?.config?.max_cpa || 32}</p>
                </div>
                <div className="p-3 bg-slate-50 rounded-lg">
                  <p className="text-xs text-slate-500">Min CTR</p>
                  <p className="text-lg font-bold">{analysis?.config?.min_ctr || 0.8}%</p>
                </div>
                <div className="p-3 bg-slate-50 rounded-lg">
                  <p className="text-xs text-slate-500">Learning Phase</p>
                  <p className="text-lg font-bold">{analysis?.config?.learning_phase_hours || 48}h</p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Decisions */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Zap className="w-5 h-5 text-yellow-600" />
                AI Decisions
              </CardTitle>
              <CardDescription>{analysis?.decisions?.length || 0} optimization decisions</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {analysis?.decisions?.length > 0 ? (
                  analysis.decisions.map((decision, i) => (
                    <div key={i} className="p-4 border rounded-lg">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          {getDecisionBadge(decision.decision_type)}
                          <span className="font-medium">{decision.entity_name}</span>
                          <Badge variant="outline" className="text-xs">{decision.entity_type}</Badge>
                        </div>
                        {decision.decision_type === 'PAUSE' && (
                          <Button
                            size="sm"
                            variant="destructive"
                            onClick={() => executeDecision(decision.entity_id, 'PAUSED')}
                          >
                            Execute Pause
                          </Button>
                        )}
                        {decision.decision_type === 'SCALE' && (
                          <Badge className="bg-green-100 text-green-700">Recommended: Scale Up</Badge>
                        )}
                      </div>
                      <p className="text-sm text-slate-600 mt-2">{decision.reason}</p>
                      <p className="text-xs text-slate-400 mt-1">{decision.recommended_action}</p>
                    </div>
                  ))
                ) : (
                  <p className="text-slate-400 text-sm">No decisions available. Run analysis to generate optimization decisions.</p>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Analytics Tab */}
        <TabsContent value="analytics" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <BarChart3 className="w-5 h-5" />
                Performance Analytics
              </CardTitle>
              <CardDescription>Account-level metrics for {dateRange}</CardDescription>
            </CardHeader>
            <CardContent>
              {analysis?.account_summary ? (
                <div className="grid grid-cols-4 gap-4">
                  <div className="p-4 bg-slate-50 rounded-lg">
                    <p className="text-xs text-slate-500 uppercase tracking-wider">Impressions</p>
                    <p className="text-2xl font-bold">{analysis.account_summary.impressions?.toLocaleString() || 0}</p>
                  </div>
                  <div className="p-4 bg-slate-50 rounded-lg">
                    <p className="text-xs text-slate-500 uppercase tracking-wider">Reach</p>
                    <p className="text-2xl font-bold">{analysis.account_summary.reach?.toLocaleString() || 0}</p>
                  </div>
                  <div className="p-4 bg-slate-50 rounded-lg">
                    <p className="text-xs text-slate-500 uppercase tracking-wider">Clicks</p>
                    <p className="text-2xl font-bold">{analysis.account_summary.clicks?.toLocaleString() || 0}</p>
                  </div>
                  <div className="p-4 bg-slate-50 rounded-lg">
                    <p className="text-xs text-slate-500 uppercase tracking-wider">Spend</p>
                    <p className="text-2xl font-bold">€{analysis.account_summary.spend?.toFixed(2) || '0.00'}</p>
                  </div>
                  <div className="p-4 bg-slate-50 rounded-lg">
                    <p className="text-xs text-slate-500 uppercase tracking-wider">CTR</p>
                    <p className="text-2xl font-bold">{analysis.account_summary.ctr?.toFixed(2) || 0}%</p>
                  </div>
                  <div className="p-4 bg-slate-50 rounded-lg">
                    <p className="text-xs text-slate-500 uppercase tracking-wider">CPC</p>
                    <p className="text-2xl font-bold">€{analysis.account_summary.cpc?.toFixed(2) || '0.00'}</p>
                  </div>
                  <div className="p-4 bg-slate-50 rounded-lg">
                    <p className="text-xs text-slate-500 uppercase tracking-wider">CPM</p>
                    <p className="text-2xl font-bold">€{analysis.account_summary.cpm?.toFixed(2) || '0.00'}</p>
                  </div>
                  <div className="p-4 bg-slate-50 rounded-lg">
                    <p className="text-xs text-slate-500 uppercase tracking-wider">Frequency</p>
                    <p className="text-2xl font-bold">{analysis.account_summary.frequency?.toFixed(2) || 0}</p>
                  </div>
                </div>
              ) : (
                <p className="text-slate-400">No analytics data available</p>
              )}

              {/* Conversion Funnel */}
              <div className="mt-6">
                <h3 className="text-sm font-medium text-slate-700 mb-3">Conversion Funnel</h3>
                <div className="flex items-center justify-between gap-2">
                  {[
                    { label: 'Clicks', value: analysis?.account_summary?.clicks || 0, icon: MousePointer },
                    { label: 'View Content', value: analysis?.account_summary?.quiz_completes || 0, icon: Eye },
                    { label: 'Add to Cart', value: analysis?.account_summary?.add_to_carts || 0, icon: ShoppingCart },
                    { label: 'Purchases', value: analysis?.account_summary?.purchases || 0, icon: CheckCircle },
                  ].map((step, i, arr) => (
                    <React.Fragment key={step.label}>
                      <div className="flex-1 text-center p-4 bg-slate-50 rounded-lg">
                        <step.icon className="w-5 h-5 mx-auto text-slate-400 mb-2" />
                        <p className="text-2xl font-bold">{step.value}</p>
                        <p className="text-xs text-slate-500">{step.label}</p>
                      </div>
                      {i < arr.length - 1 && (
                        <div className="text-slate-300">→</div>
                      )}
                    </React.Fragment>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Audiences */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Users className="w-5 h-5" />
                Custom Audiences
              </CardTitle>
              <CardDescription>Available for targeting</CardDescription>
            </CardHeader>
            <CardContent>
              {audiences.length > 0 ? (
                <div className="grid grid-cols-3 gap-3">
                  {audiences.map(audience => (
                    <div key={audience.id} className="p-3 border rounded-lg">
                      <p className="font-medium text-sm">{audience.name}</p>
                      <p className="text-xs text-slate-400 mt-1">
                        {audience.approximate_count?.toLocaleString() || 'N/A'} people
                      </p>
                      <Badge variant="outline" className="mt-2 text-xs">{audience.subtype}</Badge>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-slate-400 text-sm">No custom audiences found</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Create Campaign Dialog */}
      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Create New Campaign</DialogTitle>
            <DialogDescription>
              Step {createStep} of 3 - {createStep === 1 ? 'Campaign Details' : createStep === 2 ? 'Targeting' : 'Creative'}
            </DialogDescription>
          </DialogHeader>

          {createStep === 1 && (
            <div className="space-y-4">
              <div>
                <Label>Campaign Name</Label>
                <Input
                  value={newCampaign.name}
                  onChange={e => setNewCampaign(prev => ({ ...prev, name: e.target.value }))}
                  placeholder="e.g., Q1 2026 Skincare Promo"
                />
              </div>
              <div>
                <Label>Objective</Label>
                <Select
                  value={newCampaign.objective}
                  onValueChange={v => setNewCampaign(prev => ({ ...prev, objective: v }))}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="OUTCOME_SALES">Sales (Conversions)</SelectItem>
                    <SelectItem value="OUTCOME_LEADS">Lead Generation</SelectItem>
                    <SelectItem value="OUTCOME_AWARENESS">Brand Awareness</SelectItem>
                    <SelectItem value="OUTCOME_TRAFFIC">Traffic</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>Daily Budget (cents)</Label>
                <Input
                  type="number"
                  value={newCampaign.dailyBudget}
                  onChange={e => setNewCampaign(prev => ({ ...prev, dailyBudget: parseInt(e.target.value) || 0 }))}
                />
                <p className="text-xs text-slate-400 mt-1">€{(newCampaign.dailyBudget / 100).toFixed(2)}/day</p>
              </div>
            </div>
          )}

          {createStep === 2 && (
            <div className="space-y-4">
              <div>
                <Label>Targeting Preset</Label>
                <Select
                  value={newCampaign.targetingPreset}
                  onValueChange={v => setNewCampaign(prev => ({ ...prev, targetingPreset: v }))}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select targeting..." />
                  </SelectTrigger>
                  <SelectContent>
                    {targetingPresets.map(preset => (
                      <SelectItem key={preset.name} value={preset.name}>
                        {preset.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {newCampaign.targetingPreset && (
                  <p className="text-xs text-slate-400 mt-1">
                    {targetingPresets.find(p => p.name === newCampaign.targetingPreset)?.description}
                  </p>
                )}
              </div>
            </div>
          )}

          {createStep === 3 && (
            <div className="space-y-4">
              <div>
                <Label>Select Creative (optional)</Label>
                <Select
                  value={newCampaign.creativeId}
                  onValueChange={v => setNewCampaign(prev => ({ ...prev, creativeId: v }))}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select creative..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="">No creative (add later)</SelectItem>
                    {creatives.map(creative => (
                      <SelectItem key={creative.id} value={creative.id}>
                        {creative.name || `Creative ${creative.id}`}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
                <p className="text-sm text-yellow-800">
                  Campaign will be created in <strong>PAUSED</strong> status. Review and activate manually.
                </p>
              </div>
            </div>
          )}

          <DialogFooter className="flex justify-between">
            <div>
              {createStep > 1 && (
                <Button variant="outline" onClick={() => setCreateStep(s => s - 1)}>
                  Back
                </Button>
              )}
            </div>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => { setCreateDialogOpen(false); setCreateStep(1); }}>
                Cancel
              </Button>
              {createStep < 3 ? (
                <Button onClick={() => setCreateStep(s => s + 1)} disabled={createStep === 1 && !newCampaign.name}>
                  Next
                </Button>
              ) : (
                <Button onClick={createCampaign} disabled={isCreating}>
                  {isCreating ? 'Creating...' : 'Create Campaign'}
                </Button>
              )}
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
