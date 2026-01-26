import React, { useState, useEffect, useCallback, useMemo } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { useToast } from "@/components/ui/use-toast";
import {
  Card, CardContent, CardDescription, CardHeader, CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Progress } from "@/components/ui/progress";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Tabs, TabsContent, TabsList, TabsTrigger,
} from "@/components/ui/tabs";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Share2, Sparkles, Eye, Edit3, Trash2, CheckCircle, XCircle,
  RotateCw, Calendar, Clock, Send, Image, Video, BarChart3,
  Target, TrendingUp, Heart, MessageCircle, Bookmark, Users,
  ExternalLink, RefreshCw, ChevronLeft, ChevronRight, Layers,
  Zap, Globe, Plus, Filter, ArrowUpRight, ArrowDownRight, Minus,
  MousePointer, UserPlus, Settings, Link, Unlink, Shield, AlertTriangle, Copy,
} from "lucide-react";
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, BarChart, Bar, Legend,
} from "recharts";

const API_URL = import.meta.env.DEV ? "http://localhost:8080" : "/api";

const STATUS_COLORS = {
  draft: "bg-gray-100 text-gray-700",
  pending_review: "bg-yellow-100 text-yellow-700",
  approved: "bg-green-100 text-green-700",
  rejected: "bg-red-100 text-red-700",
  active: "bg-blue-100 text-blue-700",
  completed: "bg-indigo-100 text-indigo-700",
  scheduled: "bg-cyan-100 text-cyan-700",
  publishing: "bg-orange-100 text-orange-700",
  published: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
};

const POST_TYPE_COLORS = {
  photo: "bg-blue-500",
  reel: "bg-purple-500",
  carousel: "bg-pink-500",
  product_feature: "bg-green-500",
  story: "bg-orange-500",
};

const POST_TYPE_ICONS = {
  photo: Image,
  reel: Video,
  carousel: Layers,
  product_feature: Target,
  story: Clock,
};

const CONTENT_CATEGORY_COLORS = {
  "how-to": "bg-blue-100 text-blue-700",
  "before-after": "bg-purple-100 text-purple-700",
  "product-feature": "bg-green-100 text-green-700",
  "lifestyle": "bg-pink-100 text-pink-700",
  "educational": "bg-indigo-100 text-indigo-700",
  "testimonial": "bg-yellow-100 text-yellow-700",
  "behind-the-scenes": "bg-orange-100 text-orange-700",
};

function StatusBadge({ status }) {
  return (
    <Badge className={`${STATUS_COLORS[status] || "bg-gray-100 text-gray-700"} border-0 text-xs`}>
      {status?.replace(/_/g, " ")}
    </Badge>
  );
}

function PostTypeIcon({ type, className = "h-4 w-4" }) {
  const Icon = POST_TYPE_ICONS[type] || Image;
  return <Icon className={className} />;
}

export default function SocialMedia() {
  const { getAuthHeader } = useAuth();
  const { toast } = useToast();

  const [activeTab, setActiveTab] = useState("strategy");
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);

  // Strategy state
  const [strategies, setStrategies] = useState([]);
  const [selectedStrategy, setSelectedStrategy] = useState(null);
  const [strategyDetailOpen, setStrategyDetailOpen] = useState(false);
  const [strategyFormOpen, setStrategyFormOpen] = useState(false);
  const [strategyGoals, setStrategyGoals] = useState("audience_growth,engagement");
  const [strategyStartDate, setStrategyStartDate] = useState("");
  const [strategyEndDate, setStrategyEndDate] = useState("");

  // Posts state
  const [posts, setPosts] = useState([]);
  const [selectedPost, setSelectedPost] = useState(null);
  const [postDetailOpen, setPostDetailOpen] = useState(false);
  const [postEditOpen, setPostEditOpen] = useState(false);
  const [editedPost, setEditedPost] = useState({});
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [regenerateOpen, setRegenerateOpen] = useState(false);
  const [regenerateHints, setRegenerateHints] = useState("");
  const [postGenerateOpen, setPostGenerateOpen] = useState(false);
  const [newPostType, setNewPostType] = useState("photo");
  const [newPostTopicHint, setNewPostTopicHint] = useState("");
  const [newPostStrategyId, setNewPostStrategyId] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");

  // Calendar state
  const [calendarView, setCalendarView] = useState("timeline");
  const [calendarMonth, setCalendarMonth] = useState(new Date());

  // Analytics state
  const [insights, setInsights] = useState(null);
  const [profileData, setProfileData] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [analyticsPeriod, setAnalyticsPeriod] = useState(7);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const [syncingAnalytics, setSyncingAnalytics] = useState(false);
  const [analyticsMetric, setAnalyticsMetric] = useState("impressions");

  // Media generation state
  const [generatingMedia, setGeneratingMedia] = useState(false);

  // Profile/voice state
  const [analyzingVoice, setAnalyzingVoice] = useState(false);

  // Account connection state
  const [accountStatus, setAccountStatus] = useState(null);
  const [accountLoading, setAccountLoading] = useState(false);
  const [connectFormOpen, setConnectFormOpen] = useState(false);
  const [connectToken, setConnectToken] = useState("");
  const [connectPageId, setConnectPageId] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [refreshingToken, setRefreshingToken] = useState(false);

  // Initial load
  useEffect(() => {
    Promise.all([
      fetchStrategies(),
      fetchPosts(),
      fetchProfile(),
      fetchInsights(),
    ]).finally(() => setLoading(false));
  }, []);

  // ============================================================
  // API CALLS
  // ============================================================

  const apiFetch = useCallback(async (path, options = {}) => {
    const res = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: { ...getAuthHeader(), "Content-Type": "application/json", ...options.headers },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "Request failed");
    }
    return res.json();
  }, [getAuthHeader]);

  const fetchStrategies = async () => {
    try {
      const data = await apiFetch("/social-media/strategies");
      setStrategies(data.strategies || []);
    } catch (e) { console.error("Failed to fetch strategies:", e); }
  };

  const fetchPosts = async () => {
    try {
      const data = await apiFetch("/social-media/posts");
      setPosts(data.posts || []);
    } catch (e) { console.error("Failed to fetch posts:", e); }
  };

  const fetchProfile = async () => {
    try {
      const data = await apiFetch("/social-media/profile");
      setProfileData(data.profile);
    } catch (e) { console.error("Failed to fetch profile:", e); }
  };

  const fetchInsights = async () => {
    try {
      const data = await apiFetch("/social-media/insights");
      setInsights(data);
    } catch (e) { console.error("Failed to fetch insights:", e); }
  };

  // Strategy actions
  const generateStrategy = async () => {
    setGenerating(true);
    try {
      const goals = strategyGoals.split(",").map(g => g.trim()).filter(Boolean);
      const data = await apiFetch("/social-media/strategy/generate", {
        method: "POST",
        body: JSON.stringify({
          goals,
          date_range_start: strategyStartDate,
          date_range_end: strategyEndDate,
        }),
      });
      toast({ title: "Strategy Generated", description: data.strategy.title });
      setStrategyFormOpen(false);
      fetchStrategies();
    } catch (e) {
      toast({ title: "Error", description: e.message, variant: "destructive" });
    } finally {
      setGenerating(false);
    }
  };

  const approveStrategy = async (uuid) => {
    try {
      await apiFetch(`/social-media/strategy/${uuid}/approve`, { method: "POST" });
      toast({ title: "Strategy Approved" });
      fetchStrategies();
      setStrategyDetailOpen(false);
    } catch (e) {
      toast({ title: "Error", description: e.message, variant: "destructive" });
    }
  };

  const rejectStrategy = async (uuid, reason) => {
    try {
      await apiFetch(`/social-media/strategy/${uuid}/reject`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      });
      toast({ title: "Strategy Rejected" });
      fetchStrategies();
      setStrategyDetailOpen(false);
    } catch (e) {
      toast({ title: "Error", description: e.message, variant: "destructive" });
    }
  };

  const generateBatchPosts = async (strategyId) => {
    setGenerating(true);
    try {
      const data = await apiFetch(`/social-media/post/generate-batch?strategy_id=${strategyId}`, {
        method: "POST",
      });
      toast({ title: "Posts Generated", description: `${data.count} posts created` });
      fetchPosts();
    } catch (e) {
      toast({ title: "Error", description: e.message, variant: "destructive" });
    } finally {
      setGenerating(false);
    }
  };

  // Post actions
  const generatePost = async () => {
    setGenerating(true);
    try {
      const data = await apiFetch("/social-media/post/generate", {
        method: "POST",
        body: JSON.stringify({
          post_type: newPostType,
          strategy_id: newPostStrategyId || null,
          topic_hint: newPostTopicHint || null,
        }),
      });
      toast({ title: "Post Generated", description: "New post draft created" });
      setPostGenerateOpen(false);
      setNewPostTopicHint("");
      fetchPosts();
    } catch (e) {
      toast({ title: "Error", description: e.message, variant: "destructive" });
    } finally {
      setGenerating(false);
    }
  };

  const approvePost = async (uuid) => {
    try {
      await apiFetch(`/social-media/post/${uuid}/approve`, { method: "POST" });
      toast({ title: "Post Approved" });
      fetchPosts();
      setPostDetailOpen(false);
    } catch (e) {
      toast({ title: "Error", description: e.message, variant: "destructive" });
    }
  };

  const rejectPost = async (uuid) => {
    try {
      await apiFetch(`/social-media/post/${uuid}/reject`, {
        method: "POST",
        body: JSON.stringify({ reason: rejectReason }),
      });
      toast({ title: "Post Rejected" });
      setRejectOpen(false);
      setRejectReason("");
      fetchPosts();
    } catch (e) {
      toast({ title: "Error", description: e.message, variant: "destructive" });
    }
  };

  const regeneratePost = async (uuid) => {
    setGenerating(true);
    try {
      const data = await apiFetch(`/social-media/post/${uuid}/regenerate`, {
        method: "POST",
        body: JSON.stringify({ hints: regenerateHints }),
      });
      toast({ title: "Post Regenerated" });
      setRegenerateOpen(false);
      setRegenerateHints("");
      fetchPosts();
      if (postDetailOpen) {
        setSelectedPost(data.post);
      }
    } catch (e) {
      toast({ title: "Error", description: e.message, variant: "destructive" });
    } finally {
      setGenerating(false);
    }
  };

  const publishPost = async (uuid) => {
    try {
      const data = await apiFetch(`/social-media/post/${uuid}/publish`, { method: "POST" });
      if (data.post.status === "published") {
        toast({ title: "Published!", description: "Post is live on Instagram" });
      } else {
        toast({ title: "Publishing Failed", description: data.post.rejection_reason, variant: "destructive" });
      }
      fetchPosts();
      setPostDetailOpen(false);
    } catch (e) {
      toast({ title: "Error", description: e.message, variant: "destructive" });
    }
  };

  const updatePost = async (uuid) => {
    try {
      await apiFetch(`/social-media/post/${uuid}`, {
        method: "PUT",
        body: JSON.stringify(editedPost),
      });
      toast({ title: "Post Updated" });
      setPostEditOpen(false);
      fetchPosts();
    } catch (e) {
      toast({ title: "Error", description: e.message, variant: "destructive" });
    }
  };

  const deletePost = async (uuid) => {
    try {
      await apiFetch(`/social-media/post/${uuid}`, { method: "DELETE" });
      toast({ title: "Post Deleted" });
      fetchPosts();
    } catch (e) {
      toast({ title: "Error", description: e.message, variant: "destructive" });
    }
  };

  const analyzeVoice = async () => {
    setAnalyzingVoice(true);
    try {
      await apiFetch("/social-media/analyze-voice", { method: "POST" });
      toast({ title: "Voice Analysis Complete" });
      fetchProfile();
    } catch (e) {
      toast({ title: "Error", description: e.message, variant: "destructive" });
    } finally {
      setAnalyzingVoice(false);
    }
  };

  const syncInsights = async () => {
    try {
      const data = await apiFetch("/social-media/insights/sync", { method: "POST" });
      toast({ title: "Insights Synced", description: `${data.synced} posts updated` });
      fetchInsights();
    } catch (e) {
      toast({ title: "Error", description: e.message, variant: "destructive" });
    }
  };

  const fetchAnalytics = useCallback(async (period) => {
    setAnalyticsLoading(true);
    try {
      const data = await apiFetch(`/social-media/analytics?period=${period || analyticsPeriod}`);
      setAnalytics(data);
    } catch (e) {
      console.error("Failed to fetch analytics:", e);
    } finally {
      setAnalyticsLoading(false);
    }
  }, [apiFetch, analyticsPeriod]);

  const syncAnalytics = async () => {
    setSyncingAnalytics(true);
    try {
      const data = await apiFetch("/social-media/analytics/sync", { method: "POST" });
      toast({
        title: "Analytics Synced",
        description: `${data.account_days_synced} days + ${data.post_insights_synced} posts synced`,
      });
      fetchAnalytics(analyticsPeriod);
    } catch (e) {
      toast({ title: "Error", description: e.message, variant: "destructive" });
    } finally {
      setSyncingAnalytics(false);
    }
  };

  // Fetch analytics when period changes
  useEffect(() => {
    if (activeTab === "analytics") {
      fetchAnalytics(analyticsPeriod);
    }
  }, [analyticsPeriod, activeTab]);

  const generateMediaForPost = async (uuid) => {
    setGeneratingMedia(true);
    try {
      const data = await apiFetch(`/social-media/post/${uuid}/generate-media`, { method: "POST" });
      toast({ title: "Image Generated", description: "AI image created successfully" });
      fetchPosts();
      if (postDetailOpen && selectedPost?.id === uuid) {
        setSelectedPost(data.post);
      }
    } catch (e) {
      toast({ title: "Error", description: e.message, variant: "destructive" });
    } finally {
      setGeneratingMedia(false);
    }
  };

  // Account connection functions
  const fetchAccountStatus = useCallback(async () => {
    setAccountLoading(true);
    try {
      const data = await apiFetch("/social-media/account/status");
      setAccountStatus(data);
    } catch (e) {
      console.error("Failed to fetch account status:", e);
      setAccountStatus({ connected: false });
    } finally {
      setAccountLoading(false);
    }
  }, [apiFetch]);

  const connectAccount = async () => {
    const isIgToken = connectToken.trim().startsWith("IGAA");
    if (!connectToken.trim() || (!isIgToken && !connectPageId.trim())) {
      toast({ title: "Error", description: isIgToken ? "Access token is required" : "Both access token and Page ID are required", variant: "destructive" });
      return;
    }
    setConnecting(true);
    try {
      const data = await apiFetch("/social-media/account/connect", {
        method: "POST",
        body: JSON.stringify({ access_token: connectToken.trim(), page_id: connectPageId.trim() }),
      });
      toast({
        title: "Account Connected",
        description: `Connected to @${data.ig_username} (${data.ig_followers?.toLocaleString()} followers)`,
      });
      setConnectFormOpen(false);
      setConnectToken("");
      setConnectPageId("");
      fetchAccountStatus();
    } catch (e) {
      toast({ title: "Connection Failed", description: e.message, variant: "destructive" });
    } finally {
      setConnecting(false);
    }
  };

  const refreshAccountToken = async () => {
    setRefreshingToken(true);
    try {
      const data = await apiFetch("/social-media/account/refresh", { method: "POST" });
      toast({ title: "Token Refreshed", description: `New token valid for ~60 days` });
      fetchAccountStatus();
    } catch (e) {
      toast({ title: "Refresh Failed", description: e.message, variant: "destructive" });
    } finally {
      setRefreshingToken(false);
    }
  };

  const disconnectAccount = async () => {
    if (!confirm("Are you sure you want to disconnect this Instagram account?")) return;
    try {
      await apiFetch("/social-media/account/disconnect", { method: "POST" });
      toast({ title: "Disconnected", description: "Instagram account disconnected" });
      setAccountStatus({ connected: false });
    } catch (e) {
      toast({ title: "Error", description: e.message, variant: "destructive" });
    }
  };

  // Fetch account status when Account tab is active
  useEffect(() => {
    if (activeTab === "account") {
      fetchAccountStatus();
    }
  }, [activeTab]);

  // Filtered posts
  const filteredPosts = posts.filter(p => {
    if (statusFilter !== "all" && p.status !== statusFilter) return false;
    if (typeFilter !== "all" && p.post_type !== typeFilter) return false;
    return true;
  });

  // Calendar helpers
  const getCalendarDays = () => {
    const year = calendarMonth.getFullYear();
    const month = calendarMonth.getMonth();
    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);
    const startPad = firstDay.getDay();
    const days = [];

    for (let i = 0; i < startPad; i++) {
      days.push(null);
    }
    for (let d = 1; d <= lastDay.getDate(); d++) {
      days.push(new Date(year, month, d));
    }
    return days;
  };

  const getPostsForDate = (date) => {
    if (!date) return [];
    const dateStr = date.toISOString().slice(0, 10);
    return posts.filter(p => p.scheduled_at && p.scheduled_at.slice(0, 10) === dateStr);
  };

  if (loading) {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-8 w-[300px]" />
        <Skeleton className="h-[500px] w-full" />
      </div>
    );
  }

  // ============================================================
  // RENDER
  // ============================================================

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Share2 className="h-6 w-6 text-pink-600" />
            Social Media Manager
          </h1>
          <p className="text-gray-500 text-sm mt-1">
            Instagram content calendar, AI generation, approval workflow & publishing
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={analyzeVoice} disabled={analyzingVoice}>
            {analyzingVoice ? <RotateCw className="h-4 w-4 animate-spin mr-1" /> : <Zap className="h-4 w-4 mr-1" />}
            {analyzingVoice ? "Analyzing..." : "Analyze Voice"}
          </Button>
        </div>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="mb-4">
          <TabsTrigger value="strategy" className="gap-1"><Target className="h-4 w-4" /> Strategy</TabsTrigger>
          <TabsTrigger value="calendar" className="gap-1"><Calendar className="h-4 w-4" /> Calendar</TabsTrigger>
          <TabsTrigger value="queue" className="gap-1"><Layers className="h-4 w-4" /> Post Queue</TabsTrigger>
          <TabsTrigger value="analytics" className="gap-1"><BarChart3 className="h-4 w-4" /> Analytics</TabsTrigger>
          <TabsTrigger value="account" className="gap-1"><Settings className="h-4 w-4" /> Account</TabsTrigger>
        </TabsList>

        {/* ==================== STRATEGY TAB ==================== */}
        <TabsContent value="strategy">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">Content Strategies</h2>
            <Button onClick={() => setStrategyFormOpen(true)}>
              <Sparkles className="h-4 w-4 mr-1" /> Generate Strategy
            </Button>
          </div>

          {strategies.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center text-gray-500">
                <Target className="h-12 w-12 mx-auto mb-3 text-gray-300" />
                <p className="font-medium">No strategies yet</p>
                <p className="text-sm mt-1">Generate your first AI content strategy to get started</p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-4">
              {strategies.map(s => (
                <Card key={s.id} className="hover:shadow-md transition-shadow cursor-pointer"
                      onClick={() => { setSelectedStrategy(s); setStrategyDetailOpen(true); }}>
                  <CardContent className="py-4">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <h3 className="font-semibold">{s.title}</h3>
                          <StatusBadge status={s.status} />
                        </div>
                        <p className="text-sm text-gray-600 line-clamp-2">{s.description}</p>
                        <div className="flex items-center gap-4 mt-2 text-xs text-gray-400">
                          <span><Calendar className="h-3 w-3 inline mr-1" />{s.date_range_start} to {s.date_range_end}</span>
                          {s.goals && <span><Target className="h-3 w-3 inline mr-1" />{s.goals.join(", ")}</span>}
                        </div>
                      </div>
                      <div className="flex gap-1 ml-4">
                        {s.status === "pending_review" && (
                          <>
                            <Button size="sm" variant="outline" className="text-green-600"
                                    onClick={e => { e.stopPropagation(); approveStrategy(s.id); }}>
                              <CheckCircle className="h-4 w-4" />
                            </Button>
                            <Button size="sm" variant="outline" className="text-red-600"
                                    onClick={e => { e.stopPropagation(); rejectStrategy(s.id, "Needs revision"); }}>
                              <XCircle className="h-4 w-4" />
                            </Button>
                          </>
                        )}
                        {s.status === "approved" && (
                          <Button size="sm" onClick={e => { e.stopPropagation(); generateBatchPosts(s.id); }}
                                  disabled={generating}>
                            <Sparkles className="h-4 w-4 mr-1" /> Generate Posts
                          </Button>
                        )}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          {/* Strategy Generate Dialog */}
          <Dialog open={strategyFormOpen} onOpenChange={setStrategyFormOpen}>
            <DialogContent className="max-w-md">
              <DialogHeader>
                <DialogTitle>Generate Content Strategy</DialogTitle>
                <DialogDescription>AI will create a content plan based on your goals and date range</DialogDescription>
              </DialogHeader>
              <div className="space-y-4">
                <div>
                  <Label>Goals (comma-separated)</Label>
                  <Input value={strategyGoals} onChange={e => setStrategyGoals(e.target.value)}
                         placeholder="audience_growth, engagement, sales" />
                  <p className="text-xs text-gray-400 mt-1">e.g., audience_growth, engagement, brand_awareness, sales</p>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label>Start Date</Label>
                    <Input type="date" value={strategyStartDate} onChange={e => setStrategyStartDate(e.target.value)} />
                  </div>
                  <div>
                    <Label>End Date</Label>
                    <Input type="date" value={strategyEndDate} onChange={e => setStrategyEndDate(e.target.value)} />
                  </div>
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setStrategyFormOpen(false)}>Cancel</Button>
                <Button onClick={generateStrategy} disabled={generating || !strategyStartDate || !strategyEndDate}>
                  {generating ? <RotateCw className="h-4 w-4 animate-spin mr-1" /> : <Sparkles className="h-4 w-4 mr-1" />}
                  {generating ? "Generating..." : "Generate"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          {/* Strategy Detail Dialog */}
          <Dialog open={strategyDetailOpen} onOpenChange={setStrategyDetailOpen}>
            <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
              {selectedStrategy && (
                <>
                  <DialogHeader>
                    <div className="flex items-center gap-2">
                      <DialogTitle>{selectedStrategy.title}</DialogTitle>
                      <StatusBadge status={selectedStrategy.status} />
                    </div>
                    <DialogDescription>{selectedStrategy.description}</DialogDescription>
                  </DialogHeader>
                  <div className="space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <Label className="text-xs text-gray-500">Date Range</Label>
                        <p className="text-sm">{selectedStrategy.date_range_start} to {selectedStrategy.date_range_end}</p>
                      </div>
                      <div>
                        <Label className="text-xs text-gray-500">Goals</Label>
                        <div className="flex flex-wrap gap-1">
                          {selectedStrategy.goals?.map((g, i) => (
                            <Badge key={i} variant="secondary" className="text-xs">{g}</Badge>
                          ))}
                        </div>
                      </div>
                    </div>

                    {selectedStrategy.content_mix && (
                      <div>
                        <Label className="text-xs text-gray-500 mb-2 block">Content Mix</Label>
                        <div className="flex gap-2">
                          {Object.entries(selectedStrategy.content_mix).map(([type, pct]) => (
                            <div key={type} className="flex-1 text-center">
                              <div className={`h-2 rounded ${POST_TYPE_COLORS[type] || "bg-gray-400"} mb-1`}
                                   style={{ opacity: pct / 100 }} />
                              <p className="text-xs text-gray-600">{type}: {pct}%</p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {selectedStrategy.posting_frequency && (
                      <div>
                        <Label className="text-xs text-gray-500">Posting Frequency</Label>
                        <p className="text-sm">
                          {selectedStrategy.posting_frequency.posts_per_week} posts/week
                          {selectedStrategy.posting_frequency.best_days &&
                            ` on ${selectedStrategy.posting_frequency.best_days.join(", ")}`}
                        </p>
                      </div>
                    )}

                    {selectedStrategy.hashtag_strategy?.core_hashtags && (
                      <div>
                        <Label className="text-xs text-gray-500">Core Hashtags</Label>
                        <p className="text-sm">{selectedStrategy.hashtag_strategy.core_hashtags.join(" ")}</p>
                      </div>
                    )}

                    {selectedStrategy.content_briefs?.length > 0 && (
                      <div>
                        <Label className="text-xs text-gray-500 mb-2 block">Content Briefs ({selectedStrategy.content_briefs.length})</Label>
                        <div className="max-h-64 overflow-y-auto border rounded-lg">
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead className="text-xs py-1.5">Date</TableHead>
                                <TableHead className="text-xs py-1.5">Category</TableHead>
                                <TableHead className="text-xs py-1.5">Type</TableHead>
                                <TableHead className="text-xs py-1.5">Product</TableHead>
                                <TableHead className="text-xs py-1.5">Hook</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {selectedStrategy.content_briefs.map((brief, i) => (
                                <TableRow key={i}>
                                  <TableCell className="text-xs py-1.5 whitespace-nowrap">{brief.date}</TableCell>
                                  <TableCell className="py-1.5">
                                    <Badge className={`${CONTENT_CATEGORY_COLORS[brief.content_category] || "bg-gray-100 text-gray-700"} border-0 text-[10px]`}>
                                      {brief.content_category}
                                    </Badge>
                                  </TableCell>
                                  <TableCell className="py-1.5">
                                    <Badge className={`${POST_TYPE_COLORS[brief.post_type] || "bg-gray-400"} text-white border-0 text-[10px]`}>
                                      {brief.post_type}
                                    </Badge>
                                  </TableCell>
                                  <TableCell className="text-xs py-1.5 max-w-[120px] truncate" title={brief.product_to_feature?.title}>
                                    {brief.product_to_feature?.title || "—"}
                                  </TableCell>
                                  <TableCell className="text-xs py-1.5 max-w-[150px] truncate" title={brief.hook}>
                                    {brief.hook || "—"}
                                  </TableCell>
                                </TableRow>
                              ))}
                            </TableBody>
                          </Table>
                        </div>
                      </div>
                    )}

                    {selectedStrategy.rejection_reason && (
                      <div className="bg-red-50 p-3 rounded-lg">
                        <Label className="text-xs text-red-500">Rejection Reason</Label>
                        <p className="text-sm text-red-700">{selectedStrategy.rejection_reason}</p>
                      </div>
                    )}
                  </div>
                  <DialogFooter>
                    {selectedStrategy.status === "pending_review" && (
                      <>
                        <Button variant="outline" className="text-red-600"
                                onClick={() => rejectStrategy(selectedStrategy.id, "Needs revision")}>
                          <XCircle className="h-4 w-4 mr-1" /> Reject
                        </Button>
                        <Button className="bg-green-600 hover:bg-green-700"
                                onClick={() => approveStrategy(selectedStrategy.id)}>
                          <CheckCircle className="h-4 w-4 mr-1" /> Approve
                        </Button>
                      </>
                    )}
                    {selectedStrategy.status === "approved" && (
                      <Button onClick={() => { generateBatchPosts(selectedStrategy.id); setStrategyDetailOpen(false); }}
                              disabled={generating}>
                        <Sparkles className="h-4 w-4 mr-1" /> Generate Posts
                      </Button>
                    )}
                  </DialogFooter>
                </>
              )}
            </DialogContent>
          </Dialog>
        </TabsContent>

        {/* ==================== CALENDAR TAB ==================== */}
        <TabsContent value="calendar">
          <div className="flex justify-between items-center mb-4">
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold">Content Calendar</h2>
              <div className="flex border rounded-md overflow-hidden ml-3">
                <button
                  className={`px-3 py-1 text-xs ${calendarView === "timeline" ? "bg-indigo-600 text-white" : "bg-white text-gray-600 hover:bg-gray-50"}`}
                  onClick={() => setCalendarView("timeline")}
                >Timeline</button>
                <button
                  className={`px-3 py-1 text-xs ${calendarView === "grid" ? "bg-indigo-600 text-white" : "bg-white text-gray-600 hover:bg-gray-50"}`}
                  onClick={() => setCalendarView("grid")}
                >Monthly</button>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={() =>
                setCalendarMonth(new Date(calendarMonth.getFullYear(), calendarMonth.getMonth() - 1))
              }>
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <span className="text-sm font-medium w-32 text-center">
                {calendarMonth.toLocaleString("default", { month: "long", year: "numeric" })}
              </span>
              <Button variant="outline" size="sm" onClick={() =>
                setCalendarMonth(new Date(calendarMonth.getFullYear(), calendarMonth.getMonth() + 1))
              }>
                <ChevronRight className="h-4 w-4" />
              </Button>
              <Button size="sm" onClick={() => setPostGenerateOpen(true)}>
                <Plus className="h-4 w-4 mr-1" /> New Post
              </Button>
            </div>
          </div>

          {calendarView === "grid" ? (
            /* Monthly Calendar Grid */
            <Card>
              <CardContent className="p-2">
                <div className="grid grid-cols-7 gap-px bg-gray-200">
                  {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map(d => (
                    <div key={d} className="bg-gray-50 p-2 text-center text-xs font-medium text-gray-500">{d}</div>
                  ))}
                  {getCalendarDays().map((day, i) => {
                    const dayPosts = day ? getPostsForDate(day) : [];
                    const isToday = day && day.toDateString() === new Date().toDateString();
                    return (
                      <div key={i} className={`bg-white min-h-[90px] p-1 ${!day ? "bg-gray-50" : ""}`}>
                        {day && (
                          <>
                            <span className={`text-xs font-medium ${isToday ? "bg-indigo-600 text-white rounded-full w-6 h-6 flex items-center justify-center" : "text-gray-700"}`}>
                              {day.getDate()}
                            </span>
                            <div className="mt-1 space-y-0.5">
                              {dayPosts.slice(0, 3).map(p => (
                                <div key={p.id}
                                     className={`text-[10px] px-1 py-0.5 rounded truncate cursor-pointer text-white flex items-center gap-1 ${POST_TYPE_COLORS[p.post_type] || "bg-gray-400"}`}
                                     title={p.caption?.slice(0, 60)}
                                     onClick={() => { setSelectedPost(p); setPostDetailOpen(true); }}>
                                  {p.media_thumbnail && (
                                    <img src={`data:image/jpeg;base64,${p.media_thumbnail}`} alt="" className="w-4 h-4 rounded-sm object-cover shrink-0" />
                                  )}
                                  {p.post_type}
                                </div>
                              ))}
                              {dayPosts.length > 3 && (
                                <span className="text-[10px] text-gray-400">+{dayPosts.length - 3} more</span>
                              )}
                            </div>
                          </>
                        )}
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>
          ) : (
            /* Timeline / Gantt View */
            <Card>
              <CardContent className="p-4">
                {posts.filter(p => p.scheduled_at).length === 0 ? (
                  <div className="text-center py-12 text-gray-500">
                    <Calendar className="h-12 w-12 mx-auto mb-3 text-gray-300" />
                    <p className="font-medium">No scheduled posts</p>
                    <p className="text-sm mt-1">Generate posts from an approved strategy to fill the calendar</p>
                  </div>
                ) : (
                  <div className="space-y-1">
                    {/* Legend */}
                    <div className="flex gap-3 mb-3 pb-3 border-b">
                      {Object.entries(POST_TYPE_COLORS).map(([type, color]) => (
                        <div key={type} className="flex items-center gap-1 text-xs text-gray-500">
                          <div className={`w-3 h-3 rounded ${color}`} />
                          {type.replace("_", " ")}
                        </div>
                      ))}
                    </div>

                    {/* Timeline rows grouped by week */}
                    {(() => {
                      const monthStr = `${calendarMonth.getFullYear()}-${String(calendarMonth.getMonth() + 1).padStart(2, "0")}`;
                      const monthPosts = posts.filter(p =>
                        p.scheduled_at && p.scheduled_at.startsWith(monthStr)
                      ).sort((a, b) => (a.scheduled_at || "").localeCompare(b.scheduled_at || ""));

                      if (monthPosts.length === 0) {
                        return <p className="text-sm text-gray-400 text-center py-6">No posts scheduled this month</p>;
                      }

                      return monthPosts.map(p => (
                        <div key={p.id}
                             className="flex items-center gap-3 py-2 px-3 rounded-lg hover:bg-gray-50 cursor-pointer border-l-4"
                             style={{ borderLeftColor: POST_TYPE_COLORS[p.post_type]?.replace("bg-", "") || "#9CA3AF" }}
                             onClick={() => { setSelectedPost(p); setPostDetailOpen(true); }}>
                          <div className="w-20 text-xs text-gray-500 shrink-0">
                            {p.scheduled_at ? new Date(p.scheduled_at).toLocaleDateString("en", { month: "short", day: "numeric" }) : "—"}
                          </div>
                          <div className="w-16 text-xs text-gray-400 shrink-0">
                            {p.scheduled_at ? new Date(p.scheduled_at).toLocaleTimeString("en", { hour: "2-digit", minute: "2-digit" }) : "—"}
                          </div>
                          {p.media_thumbnail ? (
                            <img src={`data:image/jpeg;base64,${p.media_thumbnail}`} alt="" className="w-8 h-8 rounded object-cover shrink-0" />
                          ) : (
                            <PostTypeIcon type={p.post_type} className="h-4 w-4 text-gray-400 shrink-0" />
                          )}
                          <div className="flex-1 min-w-0">
                            <p className="text-sm truncate">{p.caption?.slice(0, 80) || "No caption"}</p>
                          </div>
                          <StatusBadge status={p.status} />
                        </div>
                      ));
                    })()}
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* ==================== POST QUEUE TAB ==================== */}
        <TabsContent value="queue">
          <div className="flex justify-between items-center mb-4">
            <div className="flex items-center gap-3">
              <h2 className="text-lg font-semibold">Post Queue</h2>
              <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger className="w-[140px] h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Status</SelectItem>
                  <SelectItem value="draft">Draft</SelectItem>
                  <SelectItem value="pending_review">Pending Review</SelectItem>
                  <SelectItem value="approved">Approved</SelectItem>
                  <SelectItem value="published">Published</SelectItem>
                  <SelectItem value="rejected">Rejected</SelectItem>
                </SelectContent>
              </Select>
              <Select value={typeFilter} onValueChange={setTypeFilter}>
                <SelectTrigger className="w-[140px] h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Types</SelectItem>
                  <SelectItem value="photo">Photo</SelectItem>
                  <SelectItem value="reel">Reel</SelectItem>
                  <SelectItem value="carousel">Carousel</SelectItem>
                  <SelectItem value="product_feature">Product Feature</SelectItem>
                  <SelectItem value="story">Story</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button size="sm" onClick={() => setPostGenerateOpen(true)}>
              <Plus className="h-4 w-4 mr-1" /> Generate Post
            </Button>
          </div>

          {filteredPosts.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center text-gray-500">
                <Layers className="h-12 w-12 mx-auto mb-3 text-gray-300" />
                <p className="font-medium">No posts found</p>
                <p className="text-sm mt-1">Generate posts from a strategy or create individual posts</p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-3">
              {filteredPosts.map(p => (
                <Card key={p.id} className="hover:shadow-md transition-shadow">
                  <CardContent className="py-3">
                    <div className="flex items-start gap-3">
                      {/* Thumbnail or type indicator */}
                      {p.media_thumbnail ? (
                        <img
                          src={`data:image/jpeg;base64,${p.media_thumbnail}`}
                          alt=""
                          className="w-16 h-16 rounded-lg object-cover shrink-0 border"
                        />
                      ) : (
                        <div className={`${POST_TYPE_COLORS[p.post_type] || "bg-gray-400"} w-16 h-16 rounded-lg flex flex-col items-center justify-center shrink-0 gap-1`}>
                          <PostTypeIcon type={p.post_type} className="h-5 w-5 text-white" />
                          {p.visual_direction && (
                            <button
                              className="text-[9px] text-white/80 hover:text-white underline"
                              onClick={(e) => { e.stopPropagation(); generateMediaForPost(p.id); }}
                            >
                              {generatingMedia ? "..." : "Gen"}
                            </button>
                          )}
                        </div>
                      )}

                      {/* Content */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-xs font-medium text-gray-500 capitalize">{p.post_type?.replace("_", " ")}</span>
                          {p.content_category && (
                            <Badge className={`${CONTENT_CATEGORY_COLORS[p.content_category] || "bg-gray-100 text-gray-700"} border-0 text-[10px]`}>
                              {p.content_category}
                            </Badge>
                          )}
                          <StatusBadge status={p.status} />
                          {p.scheduled_at && (
                            <span className="text-xs text-gray-400 flex items-center gap-1">
                              <Clock className="h-3 w-3" />
                              {new Date(p.scheduled_at).toLocaleDateString("en", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                            </span>
                          )}
                        </div>
                        <p className="text-sm text-gray-700 line-clamp-2">{p.caption || "No caption generated"}</p>
                        {p.visual_direction && (
                          <p className="text-xs text-gray-400 mt-1 line-clamp-1">
                            <Eye className="h-3 w-3 inline mr-1" />
                            {p.visual_direction}
                          </p>
                        )}
                      </div>

                      {/* Actions */}
                      <div className="flex gap-1 shrink-0">
                        <Button size="sm" variant="ghost" onClick={() => { setSelectedPost(p); setPostDetailOpen(true); }}>
                          <Eye className="h-4 w-4" />
                        </Button>
                        {(p.status === "draft" || p.status === "rejected") && (
                          <>
                            <Button size="sm" variant="ghost" onClick={() => {
                              setSelectedPost(p);
                              setEditedPost({ caption: p.caption, visual_direction: p.visual_direction, media_url: p.media_url, scheduled_at: p.scheduled_at });
                              setPostEditOpen(true);
                            }}>
                              <Edit3 className="h-4 w-4" />
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => { setSelectedPost(p); setRegenerateOpen(true); }}>
                              <RotateCw className="h-4 w-4" />
                            </Button>
                            <Button size="sm" variant="ghost" className="text-red-500" onClick={() => deletePost(p.id)}>
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </>
                        )}
                        {(p.status === "draft" || p.status === "pending_review") && (
                          <Button size="sm" variant="outline" className="text-green-600" onClick={() => approvePost(p.id)}>
                            <CheckCircle className="h-4 w-4" />
                          </Button>
                        )}
                        {p.status === "approved" && (
                          <Button size="sm" className="bg-pink-600 hover:bg-pink-700 text-white" onClick={() => publishPost(p.id)}>
                            <Send className="h-4 w-4 mr-1" /> Publish
                          </Button>
                        )}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        {/* ==================== ANALYTICS TAB ==================== */}
        <TabsContent value="analytics">
          {/* Header with period selector and sync button */}
          <div className="flex justify-between items-center mb-4">
            <div className="flex items-center gap-3">
              <h2 className="text-lg font-semibold">Account Analytics</h2>
              <div className="flex border rounded-md overflow-hidden">
                {[
                  { label: "7D", value: 7 },
                  { label: "14D", value: 14 },
                  { label: "30D", value: 30 },
                  { label: "90D", value: 90 },
                ].map(p => (
                  <button
                    key={p.value}
                    className={`px-3 py-1 text-xs font-medium ${analyticsPeriod === p.value ? "bg-indigo-600 text-white" : "bg-white text-gray-600 hover:bg-gray-50"}`}
                    onClick={() => setAnalyticsPeriod(p.value)}
                  >{p.label}</button>
                ))}
              </div>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={syncAnalytics} disabled={syncingAnalytics}>
                {syncingAnalytics ? <RotateCw className="h-4 w-4 animate-spin mr-1" /> : <RefreshCw className="h-4 w-4 mr-1" />}
                {syncingAnalytics ? "Syncing..." : "Sync from Instagram"}
              </Button>
            </div>
          </div>

          {analytics?.period && (
            <p className="text-xs text-gray-400 mb-4">
              {analytics.period.start} to {analytics.period.end} vs {analytics.period.prev_start} to {analytics.period.prev_end}
            </p>
          )}

          {/* KPI Cards with period comparison */}
          {(() => {
            const c = analytics?.current || {};
            const d = analytics?.deltas || {};
            const live = analytics?.live_profile || {};

            const kpis = [
              { label: "Followers", value: live.followers_count || c.follower_count, delta: d.follower_count, icon: Users, color: "text-indigo-500" },
              { label: "Impressions", value: c.impressions, delta: d.impressions, icon: Eye, color: "text-blue-500" },
              { label: "Reach", value: c.reach, delta: d.reach, icon: TrendingUp, color: "text-green-500" },
              { label: "Profile Views", value: c.profile_views, delta: d.profile_views, icon: MousePointer, color: "text-purple-500" },
              { label: "Website Clicks", value: c.website_clicks, delta: d.website_clicks, icon: ExternalLink, color: "text-cyan-500" },
              { label: "Engagement", value: c.engagement, delta: d.engagement, icon: Heart, color: "text-red-500" },
              { label: "Engagement Rate", value: c.engagement_rate ? `${c.engagement_rate}%` : "—", delta: d.engagement_rate, icon: BarChart3, color: "text-pink-500", isSuffix: "pp" },
              { label: "Net Followers", value: c.net_followers, delta: null, icon: UserPlus, color: "text-emerald-500" },
            ];

            return (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
                {kpis.map((kpi, i) => {
                  const Icon = kpi.icon;
                  const deltaVal = kpi.delta;
                  const isPositive = deltaVal > 0;
                  const isNegative = deltaVal < 0;
                  const isNeutral = !deltaVal || deltaVal === 0;

                  return (
                    <Card key={i} className="hover:shadow-sm transition-shadow">
                      <CardContent className="py-3 px-4">
                        <div className="flex items-center justify-between mb-1">
                          <Icon className={`h-4 w-4 ${kpi.color}`} />
                          {deltaVal !== null && deltaVal !== undefined && (
                            <span className={`text-xs font-medium flex items-center gap-0.5 ${isPositive ? "text-green-600" : isNegative ? "text-red-500" : "text-gray-400"}`}>
                              {isPositive ? <ArrowUpRight className="h-3 w-3" /> : isNegative ? <ArrowDownRight className="h-3 w-3" /> : <Minus className="h-3 w-3" />}
                              {Math.abs(deltaVal)}{kpi.isSuffix || "%"}
                            </span>
                          )}
                        </div>
                        <p className="text-xl font-bold">
                          {typeof kpi.value === "number" ? kpi.value.toLocaleString() : (kpi.value || "—")}
                        </p>
                        <p className="text-xs text-gray-500">{kpi.label}</p>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            );
          })()}

          {/* Daily Metrics Chart */}
          {analytics?.daily && analytics.daily.length > 0 && (
            <Card className="mb-6">
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">Daily Metrics</CardTitle>
                  <div className="flex border rounded-md overflow-hidden">
                    {[
                      { label: "Impressions", value: "impressions" },
                      { label: "Reach", value: "reach" },
                      { label: "Profile Views", value: "profile_views" },
                      { label: "Clicks", value: "website_clicks" },
                    ].map(m => (
                      <button
                        key={m.value}
                        className={`px-2 py-1 text-[10px] font-medium ${analyticsMetric === m.value ? "bg-indigo-600 text-white" : "bg-white text-gray-500 hover:bg-gray-50"}`}
                        onClick={() => setAnalyticsMetric(m.value)}
                      >{m.label}</button>
                    ))}
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="h-[280px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={analytics.daily.map(d => ({
                      ...d,
                      date: d.date?.slice(5), // "MM-DD"
                    }))}>
                      <defs>
                        <linearGradient id="colorMetric" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                          <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                        </linearGradient>
                        <linearGradient id="colorPrev" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#9ca3af" stopOpacity={0.2} />
                          <stop offset="95%" stopColor="#9ca3af" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                      <XAxis dataKey="date" tick={{ fontSize: 10 }} stroke="#9ca3af" />
                      <YAxis tick={{ fontSize: 10 }} stroke="#9ca3af" />
                      <Tooltip
                        contentStyle={{ fontSize: 12, borderRadius: 8 }}
                        formatter={(val) => [val?.toLocaleString(), analyticsMetric.replace("_", " ")]}
                      />
                      <Area type="monotone" dataKey={analyticsMetric} stroke="#6366f1" strokeWidth={2}
                            fill="url(#colorMetric)" name="Current" />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
                {analytics.previous_daily && analytics.previous_daily.length > 0 && (
                  <p className="text-[10px] text-gray-400 mt-1 text-center">
                    Previous period total: {analytics.previous_daily.reduce((acc, d) => acc + (d[analyticsMetric] || 0), 0).toLocaleString()} {analyticsMetric.replace("_", " ")}
                  </p>
                )}
              </CardContent>
            </Card>
          )}

          {/* Content Published + Follower Trend */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
            {/* Content Published Bar Chart */}
            {analytics?.daily && analytics.daily.length > 0 && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Content Published</CardTitle>
                  <CardDescription className="text-xs">
                    {(analytics.current?.posts_published || 0) + (analytics.current?.stories_published || 0) + (analytics.current?.reels_published || 0)} total in period
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="h-[200px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={analytics.daily.map(d => ({
                        date: d.date?.slice(5),
                        Posts: d.posts_published || 0,
                        Stories: d.stories_published || 0,
                        Reels: d.reels_published || 0,
                      }))}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                        <XAxis dataKey="date" tick={{ fontSize: 9 }} stroke="#9ca3af" />
                        <YAxis tick={{ fontSize: 10 }} stroke="#9ca3af" allowDecimals={false} />
                        <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8 }} />
                        <Bar dataKey="Posts" stackId="a" fill="#3b82f6" radius={[0, 0, 0, 0]} />
                        <Bar dataKey="Stories" stackId="a" fill="#f97316" radius={[0, 0, 0, 0]} />
                        <Bar dataKey="Reels" stackId="a" fill="#a855f7" radius={[2, 2, 0, 0]} />
                        <Legend wrapperStyle={{ fontSize: 10 }} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Follower Trend */}
            {analytics?.daily && analytics.daily.some(d => d.follower_count > 0) && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Follower Growth</CardTitle>
                  <CardDescription className="text-xs">
                    {analytics.live_profile?.followers_count?.toLocaleString() || "—"} current followers
                    {analytics.current?.net_followers > 0 ? ` (+${analytics.current.net_followers} this period)` : ""}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="h-[200px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={analytics.daily.filter(d => d.follower_count > 0).map(d => ({
                        date: d.date?.slice(5),
                        Followers: d.follower_count,
                      }))}>
                        <defs>
                          <linearGradient id="colorFollowers" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                            <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                        <XAxis dataKey="date" tick={{ fontSize: 9 }} stroke="#9ca3af" />
                        <YAxis tick={{ fontSize: 10 }} stroke="#9ca3af" domain={["dataMin - 10", "dataMax + 10"]} />
                        <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8 }} />
                        <Area type="monotone" dataKey="Followers" stroke="#10b981" strokeWidth={2}
                              fill="url(#colorFollowers)" />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>

          {/* Post Type Breakdown */}
          {analytics?.type_breakdown && Object.keys(analytics.type_breakdown).length > 0 && (
            <Card className="mb-6">
              <CardHeader>
                <CardTitle className="text-base">Performance by Post Type</CardTitle>
                <CardDescription className="text-xs">Average metrics per post type</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                  {Object.entries(analytics.type_breakdown).map(([type, data]) => (
                    <div key={type} className="border rounded-lg p-3">
                      <div className="flex items-center gap-2 mb-2">
                        <div className={`w-3 h-3 rounded ${POST_TYPE_COLORS[type] || "bg-gray-400"}`} />
                        <span className="text-xs font-medium capitalize">{type.replace("_", " ")}</span>
                        <Badge variant="secondary" className="text-[10px] ml-auto">{data.count}</Badge>
                      </div>
                      <div className="space-y-1 text-xs text-gray-600">
                        <div className="flex justify-between">
                          <span>Avg Reach</span>
                          <span className="font-medium">{data.avg_reach?.toLocaleString()}</span>
                        </div>
                        <div className="flex justify-between">
                          <span>Avg Engagement</span>
                          <span className="font-medium">{data.avg_engagement?.toLocaleString()}</span>
                        </div>
                        <div className="flex justify-between">
                          <span>Total Impressions</span>
                          <span className="font-medium">{data.impressions?.toLocaleString()}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Top Performing Posts */}
          {analytics?.top_posts && analytics.top_posts.length > 0 ? (
            <Card className="mb-6">
              <CardHeader>
                <CardTitle className="text-base">Top Performing Posts</CardTitle>
                <CardDescription className="text-xs">Ranked by total engagement</CardDescription>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-[60px]">Preview</TableHead>
                      <TableHead>Post</TableHead>
                      <TableHead className="text-right">Impressions</TableHead>
                      <TableHead className="text-right">Reach</TableHead>
                      <TableHead className="text-right">Likes</TableHead>
                      <TableHead className="text-right">Comments</TableHead>
                      <TableHead className="text-right">Saves</TableHead>
                      <TableHead className="text-right font-semibold">Engagement</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {analytics.top_posts.map((p, i) => (
                      <TableRow key={i} className="cursor-pointer hover:bg-gray-50"
                                onClick={() => {
                                  const fullPost = posts.find(fp => fp.id === p.id);
                                  if (fullPost) { setSelectedPost(fullPost); setPostDetailOpen(true); }
                                }}>
                        <TableCell>
                          {p.media_thumbnail ? (
                            <img src={`data:image/jpeg;base64,${p.media_thumbnail}`} alt=""
                                 className="w-10 h-10 rounded object-cover" />
                          ) : (
                            <div className={`w-10 h-10 rounded flex items-center justify-center ${POST_TYPE_COLORS[p.post_type] || "bg-gray-400"}`}>
                              <PostTypeIcon type={p.post_type} className="h-4 w-4 text-white" />
                            </div>
                          )}
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <Badge className={`${POST_TYPE_COLORS[p.post_type] || "bg-gray-400"} text-white border-0 text-[10px]`}>
                              {p.post_type}
                            </Badge>
                            <span className="text-xs text-gray-600 truncate max-w-[200px]">{p.caption}</span>
                          </div>
                          {p.published_at && (
                            <p className="text-[10px] text-gray-400 mt-0.5">
                              {new Date(p.published_at).toLocaleDateString("en", { month: "short", day: "numeric" })}
                            </p>
                          )}
                        </TableCell>
                        <TableCell className="text-right text-sm">{p.impressions?.toLocaleString()}</TableCell>
                        <TableCell className="text-right text-sm">{p.reach?.toLocaleString()}</TableCell>
                        <TableCell className="text-right text-sm">{p.likes?.toLocaleString()}</TableCell>
                        <TableCell className="text-right text-sm">{p.comments?.toLocaleString()}</TableCell>
                        <TableCell className="text-right text-sm">{p.saves?.toLocaleString()}</TableCell>
                        <TableCell className="text-right text-sm font-semibold text-indigo-600">{p.engagement?.toLocaleString()}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          ) : (
            <Card className="mb-6">
              <CardContent className="py-12 text-center text-gray-500">
                <BarChart3 className="h-12 w-12 mx-auto mb-3 text-gray-300" />
                <p className="font-medium">No analytics data yet</p>
                <p className="text-sm mt-1">Click "Sync from Instagram" to pull account metrics, then publish posts and sync again for post-level data</p>
              </CardContent>
            </Card>
          )}

          {/* Account Summary Card */}
          {analytics?.current && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
              <Card>
                <CardContent className="py-3 px-4">
                  <p className="text-xs text-gray-500">Posts Published</p>
                  <p className="text-lg font-bold">{analytics.current.posts_published}</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="py-3 px-4">
                  <p className="text-xs text-gray-500">Stories Published</p>
                  <p className="text-lg font-bold">{analytics.current.stories_published}</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="py-3 px-4">
                  <p className="text-xs text-gray-500">Likes</p>
                  <p className="text-lg font-bold">{analytics.current.likes?.toLocaleString()}</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="py-3 px-4">
                  <p className="text-xs text-gray-500">Saves</p>
                  <p className="text-lg font-bold">{analytics.current.saves?.toLocaleString()}</p>
                </CardContent>
              </Card>
            </div>
          )}

          {/* Brand voice analysis preview */}
          {profileData?.brand_voice_analysis && (
            <Card className="mt-2">
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <Zap className="h-4 w-4 text-yellow-500" /> Brand Voice Analysis
                </CardTitle>
              </CardHeader>
              <CardContent>
                {typeof profileData.brand_voice_analysis === "object" ? (
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    {profileData.brand_voice_analysis.tone && (
                      <div>
                        <Label className="text-xs text-gray-500">Tone</Label>
                        <p>{profileData.brand_voice_analysis.tone}</p>
                      </div>
                    )}
                    {profileData.brand_voice_analysis.language_style && (
                      <div>
                        <Label className="text-xs text-gray-500">Language Style</Label>
                        <p>{profileData.brand_voice_analysis.language_style}</p>
                      </div>
                    )}
                    {profileData.brand_voice_analysis.emoji_usage && (
                      <div>
                        <Label className="text-xs text-gray-500">Emoji Usage</Label>
                        <p>{profileData.brand_voice_analysis.emoji_usage}</p>
                      </div>
                    )}
                    {profileData.brand_voice_analysis.cta_patterns && (
                      <div>
                        <Label className="text-xs text-gray-500">CTA Patterns</Label>
                        <p>{profileData.brand_voice_analysis.cta_patterns}</p>
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="text-sm text-gray-600">{String(profileData.brand_voice_analysis)}</p>
                )}
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* ==================== ACCOUNT TAB ==================== */}
        <TabsContent value="account">
          <div className="space-y-6">
            {/* Connection Status Card */}
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="flex items-center gap-2">
                      <Share2 className="h-5 w-5" /> Instagram Connection
                    </CardTitle>
                    <CardDescription>Manage your Instagram Business Account connection</CardDescription>
                  </div>
                  <Button variant="outline" size="sm" onClick={fetchAccountStatus} disabled={accountLoading}>
                    <RefreshCw className={`h-4 w-4 mr-1 ${accountLoading ? "animate-spin" : ""}`} /> Check Status
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                {accountLoading && !accountStatus ? (
                  <div className="space-y-3">
                    <Skeleton className="h-20 w-full" />
                    <Skeleton className="h-4 w-1/2" />
                  </div>
                ) : accountStatus?.connected ? (
                  <div className="space-y-4">
                    {/* Connected Account Info */}
                    <div className="flex items-center gap-4 p-4 bg-green-50 border border-green-200 rounded-lg">
                      <div className="relative">
                        {accountStatus.ig_profile_pic ? (
                          <img src={accountStatus.ig_profile_pic} alt="" className="h-16 w-16 rounded-full object-cover border-2 border-green-400" />
                        ) : (
                          <div className="h-16 w-16 rounded-full bg-green-200 flex items-center justify-center">
                            <Users className="h-8 w-8 text-green-600" />
                          </div>
                        )}
                        <div className="absolute -bottom-1 -right-1 h-5 w-5 bg-green-500 rounded-full flex items-center justify-center">
                          <CheckCircle className="h-3 w-3 text-white" />
                        </div>
                      </div>
                      <div className="flex-1">
                        <h3 className="text-lg font-semibold text-green-800">
                          @{accountStatus.ig_username || "Connected"}
                        </h3>
                        <p className="text-sm text-green-700">
                          {accountStatus.ig_followers?.toLocaleString() || 0} followers
                        </p>
                        <p className="text-xs text-green-600">
                          Source: {accountStatus.source === "database" ? "Saved in app" : "Environment variables"}
                        </p>
                      </div>
                      <Badge className="bg-green-100 text-green-800 border-green-300">Connected</Badge>
                    </div>

                    {/* Token Status */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                      <div className="p-3 rounded-lg border bg-white">
                        <div className="flex items-center gap-2 text-sm font-medium text-gray-600 mb-1">
                          <Shield className="h-4 w-4" /> Token Status
                        </div>
                        <p className={`font-semibold ${accountStatus.token_valid ? "text-green-600" : "text-red-600"}`}>
                          {accountStatus.token_valid ? "Valid" : "Invalid / Expired"}
                        </p>
                      </div>
                      <div className="p-3 rounded-lg border bg-white">
                        <div className="flex items-center gap-2 text-sm font-medium text-gray-600 mb-1">
                          <Clock className="h-4 w-4" /> Expires
                        </div>
                        <p className={`font-semibold ${
                          accountStatus.days_until_expiry === null ? "text-green-600" :
                          accountStatus.days_until_expiry < 7 ? "text-red-600" :
                          accountStatus.days_until_expiry < 30 ? "text-yellow-600" : "text-green-600"
                        }`}>
                          {accountStatus.days_until_expiry === null
                            ? "Never (Page Token)"
                            : accountStatus.days_until_expiry < 0
                            ? "Expired"
                            : `${accountStatus.days_until_expiry} days left`}
                        </p>
                      </div>
                      <div className="p-3 rounded-lg border bg-white">
                        <div className="flex items-center gap-2 text-sm font-medium text-gray-600 mb-1">
                          <Link className="h-4 w-4" /> Account ID
                        </div>
                        <p className="font-semibold text-gray-900 text-sm font-mono">
                          {accountStatus.ig_account_id || accountStatus.page_id || "N/A"}
                        </p>
                      </div>
                    </div>

                    {/* Token Expiry Warning */}
                    {accountStatus.days_until_expiry !== null && accountStatus.days_until_expiry < 14 && (
                      <div className={`flex items-start gap-3 p-3 rounded-lg border ${
                        accountStatus.days_until_expiry < 0 ? "bg-red-50 border-red-200" :
                        accountStatus.days_until_expiry < 7 ? "bg-orange-50 border-orange-200" :
                        "bg-yellow-50 border-yellow-200"
                      }`}>
                        <AlertTriangle className={`h-5 w-5 mt-0.5 ${
                          accountStatus.days_until_expiry < 0 ? "text-red-500" :
                          accountStatus.days_until_expiry < 7 ? "text-orange-500" : "text-yellow-500"
                        }`} />
                        <div>
                          <p className="font-medium text-sm">
                            {accountStatus.days_until_expiry < 0 ? "Token has expired!" : "Token expiring soon!"}
                          </p>
                          <p className="text-xs text-gray-600 mt-1">
                            {accountStatus.days_until_expiry < 0
                              ? "Your access token has expired. Please reconnect your account or refresh the token."
                              : `Your access token expires in ${accountStatus.days_until_expiry} days. Click "Refresh Token" to extend it, or reconnect with a new token.`}
                          </p>
                        </div>
                      </div>
                    )}

                    {/* Scopes */}
                    {accountStatus.scopes?.length > 0 && (
                      <div>
                        <p className="text-sm font-medium text-gray-600 mb-2">Permissions</p>
                        <div className="flex flex-wrap gap-1.5">
                          {accountStatus.scopes.map(scope => (
                            <Badge key={scope} variant="outline" className="text-xs font-mono">{scope}</Badge>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Actions */}
                    <div className="flex gap-2 pt-2 border-t">
                      <Button variant="outline" onClick={refreshAccountToken} disabled={refreshingToken}>
                        <RefreshCw className={`h-4 w-4 mr-1 ${refreshingToken ? "animate-spin" : ""}`} />
                        {refreshingToken ? "Refreshing..." : "Refresh Token"}
                      </Button>
                      <Button variant="outline" onClick={() => setConnectFormOpen(true)}>
                        <Link className="h-4 w-4 mr-1" /> Reconnect
                      </Button>
                      <Button variant="outline" className="text-red-600 hover:text-red-700 hover:bg-red-50" onClick={disconnectAccount}>
                        <Unlink className="h-4 w-4 mr-1" /> Disconnect
                      </Button>
                    </div>
                  </div>
                ) : (
                  /* Not Connected */
                  <div className="text-center py-8">
                    <div className="mx-auto h-16 w-16 bg-gray-100 rounded-full flex items-center justify-center mb-4">
                      <Share2 className="h-8 w-8 text-gray-400" />
                    </div>
                    <h3 className="text-lg font-semibold mb-2">No Instagram Account Connected</h3>
                    <p className="text-sm text-gray-500 mb-4 max-w-md mx-auto">
                      Connect your Instagram Business Account to publish posts, stories, and track analytics.
                    </p>
                    <Button onClick={() => setConnectFormOpen(true)}>
                      <Link className="h-4 w-4 mr-1" /> Connect Instagram
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Connect Form Card */}
            {connectFormOpen && (
              <Card className="border-blue-200 bg-blue-50/30">
                <CardHeader>
                  <CardTitle className="text-lg">Connect Instagram Account</CardTitle>
                  <CardDescription>Enter your Meta access token and Facebook Page ID</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div>
                    <Label className="font-medium">Access Token</Label>
                    <Textarea
                      value={connectToken}
                      onChange={e => setConnectToken(e.target.value)}
                      placeholder="Paste your IG or Meta access token (IGAA... or EAA...)"
                      className="mt-1 font-mono text-xs h-20"
                    />
                    {connectToken.startsWith("IGAA") && (
                      <p className="text-xs text-green-600 mt-1 flex items-center gap-1">
                        <CheckCircle className="h-3 w-3" /> Instagram API token detected — Page ID not required
                      </p>
                    )}
                    {connectToken.startsWith("EAA") && (
                      <p className="text-xs text-blue-600 mt-1 flex items-center gap-1">
                        <Shield className="h-3 w-3" /> Facebook token — Page ID required below
                      </p>
                    )}
                  </div>
                  {!connectToken.startsWith("IGAA") && (
                  <div>
                    <Label className="font-medium">Facebook Page ID</Label>
                    <Input
                      value={connectPageId}
                      onChange={e => setConnectPageId(e.target.value)}
                      placeholder="e.g., 571704329368702"
                      className="mt-1 font-mono"
                    />
                  </div>
                  )}
                  <div className="flex gap-2">
                    <Button onClick={connectAccount} disabled={connecting}>
                      {connecting ? <RotateCw className="h-4 w-4 animate-spin mr-1" /> : <CheckCircle className="h-4 w-4 mr-1" />}
                      {connecting ? "Connecting..." : "Connect"}
                    </Button>
                    <Button variant="outline" onClick={() => { setConnectFormOpen(false); setConnectToken(""); setConnectPageId(""); }}>
                      Cancel
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Setup Guide */}
            <Card>
              <CardHeader>
                <CardTitle className="text-lg flex items-center gap-2">
                  <Zap className="h-5 w-5" /> How to Get Your Access Token
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-4 text-sm">
                  <div className="space-y-3">
                    <h4 className="font-semibold text-gray-900">Prerequisites</h4>
                    <ul className="list-disc list-inside space-y-1 text-gray-600">
                      <li>An Instagram <strong>Professional</strong> account (Business or Creator)</li>
                      <li>A Facebook Page connected to that Instagram account</li>
                      <li>A Meta Developer App (free to create)</li>
                    </ul>
                  </div>

                  <div className="space-y-3">
                    <h4 className="font-semibold text-gray-900">Step-by-Step</h4>
                    <ol className="list-decimal list-inside space-y-2 text-gray-600">
                      <li>
                        Go to{" "}
                        <a href="https://developers.facebook.com/apps/" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
                          Meta for Developers <ExternalLink className="h-3 w-3 inline" />
                        </a>{" "}
                        and create an app (type: "Business") if you haven't already.
                      </li>
                      <li>
                        In your app, go to <strong>Tools → Graph API Explorer</strong>{" "}
                        <a href="https://developers.facebook.com/tools/explorer/" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
                          (direct link) <ExternalLink className="h-3 w-3 inline" />
                        </a>
                      </li>
                      <li>Select your app from the dropdown at the top.</li>
                      <li>
                        Click <strong>"Generate Access Token"</strong> and grant these permissions:
                        <div className="flex flex-wrap gap-1 mt-1">
                          {["pages_show_list", "pages_read_engagement", "pages_manage_posts",
                            "instagram_basic", "instagram_content_publish", "instagram_manage_insights",
                            "business_management"].map(p => (
                            <Badge key={p} variant="outline" className="text-xs font-mono">{p}</Badge>
                          ))}
                        </div>
                      </li>
                      <li>Copy the generated <strong>User Access Token</strong> and paste it above.</li>
                      <li>
                        Find your <strong>Facebook Page ID</strong>: Go to your Page → About → scroll down to "Page ID".
                        Or use the Graph API Explorer: <code className="bg-gray-100 px-1 rounded text-xs">GET /me/accounts</code> to list your pages.
                      </li>
                    </ol>
                  </div>

                  <div className="space-y-3 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                    <h4 className="font-semibold text-amber-800 flex items-center gap-1">
                      <AlertTriangle className="h-4 w-4" /> Important Notes
                    </h4>
                    <ul className="list-disc list-inside space-y-1 text-amber-700 text-xs">
                      <li>Short-lived tokens last ~1 hour. The app will auto-exchange them for long-lived tokens (~60 days).</li>
                      <li>Long-lived tokens can be refreshed before they expire using the "Refresh Token" button.</li>
                      <li>For auto-refresh to work, set <code className="bg-amber-100 px-1 rounded">META_APP_ID</code> and <code className="bg-amber-100 px-1 rounded">META_APP_SECRET</code> in your environment.</li>
                      <li>The Graph API Explorer token is a <strong>short-lived User Token</strong>. The system will exchange it for a long-lived one automatically.</li>
                    </ul>
                  </div>

                  <div className="space-y-3 p-3 bg-blue-50 border border-blue-200 rounded-lg">
                    <h4 className="font-semibold text-blue-800">Quick Method: Get a Long-Lived Token Directly</h4>
                    <ol className="list-decimal list-inside space-y-1 text-blue-700 text-xs">
                      <li>Go to the Graph API Explorer and generate a short-lived token with the permissions above.</li>
                      <li>
                        Visit{" "}
                        <a href="https://developers.facebook.com/tools/accesstoken/" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
                          Access Token Tool <ExternalLink className="h-3 w-3 inline" />
                        </a>{" "}
                        → click <strong>"Debug"</strong> on your User Token → click <strong>"Extend Access Token"</strong>.
                      </li>
                      <li>Copy the extended token (valid ~60 days) and paste it in the form above.</li>
                    </ol>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>

      {/* ==================== SHARED DIALOGS ==================== */}

      {/* Post Detail Dialog */}
      <Dialog open={postDetailOpen} onOpenChange={setPostDetailOpen}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
          {selectedPost && (
            <>
              <DialogHeader>
                <div className="flex items-center gap-2">
                  <PostTypeIcon type={selectedPost.post_type} />
                  <DialogTitle className="capitalize">{selectedPost.post_type?.replace("_", " ")} Post</DialogTitle>
                  <StatusBadge status={selectedPost.status} />
                </div>
              </DialogHeader>
              <div className="space-y-4">
                {/* Image preview */}
                {(() => {
                  const hasGeneratedMedia = !!(selectedPost.media_data_format || selectedPost.media_thumbnail);
                  const mediaApiUrl = `${API_URL}/social-media/media/${selectedPost.id}`;

                  if (hasGeneratedMedia) {
                    return (
                      <div>
                        <Label className="text-xs text-gray-500 mb-2 block">Media Preview</Label>
                        <div className="bg-gray-100 rounded-lg overflow-hidden flex items-center justify-center"
                             style={{ maxHeight: "400px" }}>
                          {selectedPost.media_data_format === "mp4" ? (
                            <video src={mediaApiUrl} controls className="max-h-[400px] rounded-lg" />
                          ) : (
                            <img
                              src={selectedPost.media_thumbnail ? `data:image/jpeg;base64,${selectedPost.media_thumbnail}` : mediaApiUrl}
                              alt="Post preview"
                              className="max-h-[400px] rounded-lg object-contain cursor-pointer"
                              onClick={() => window.open(mediaApiUrl, '_blank')}
                              title="Click to view full resolution"
                            />
                          )}
                        </div>
                        <div className="mt-2 flex gap-2">
                          <Button size="sm" variant="outline" onClick={() => generateMediaForPost(selectedPost.id)}
                                  disabled={generatingMedia}>
                            {generatingMedia ? <RotateCw className="h-4 w-4 animate-spin mr-1" /> : <RefreshCw className="h-4 w-4 mr-1" />}
                            {generatingMedia ? "Generating..." : "Regenerate Image"}
                          </Button>
                          <Button size="sm" variant="ghost" className="text-xs" onClick={() => window.open(mediaApiUrl, '_blank')}>
                            <ExternalLink className="h-3 w-3 mr-1" /> Full Size
                          </Button>
                        </div>
                      </div>
                    );
                  }

                  if (selectedPost.visual_direction) {
                    return (
                      <div>
                        <Label className="text-xs text-gray-500 mb-2 block">Media Preview</Label>
                        <div className="bg-gray-100 rounded-lg p-8 text-center">
                          <Image className="h-12 w-12 mx-auto mb-2 text-gray-300" />
                          <p className="text-sm text-gray-500 mb-3">No image generated yet</p>
                          <Button size="sm" onClick={() => generateMediaForPost(selectedPost.id)}
                                  disabled={generatingMedia}>
                            {generatingMedia ? <RotateCw className="h-4 w-4 animate-spin mr-1" /> : <Sparkles className="h-4 w-4 mr-1" />}
                            {generatingMedia ? "Generating..." : "Generate Image"}
                          </Button>
                        </div>
                      </div>
                    );
                  }

                  return null;
                })()}

                <div>
                  <Label className="text-xs text-gray-500">Caption</Label>
                  <div className="bg-gray-50 rounded-lg p-3 text-sm whitespace-pre-wrap">{selectedPost.caption}</div>
                </div>
                {selectedPost.visual_direction && (
                  <div>
                    <Label className="text-xs text-gray-500">Visual Direction</Label>
                    <div className="bg-blue-50 rounded-lg p-3 text-sm">{selectedPost.visual_direction}</div>
                  </div>
                )}
                <div className="grid grid-cols-2 gap-4 text-sm">
                  {selectedPost.media_url && (
                    <div>
                      <Label className="text-xs text-gray-500">Media URL</Label>
                      <a href={selectedPost.media_url} target="_blank" rel="noopener noreferrer"
                         className="text-blue-600 hover:underline text-xs flex items-center gap-1">
                        <ExternalLink className="h-3 w-3" /> View media
                      </a>
                    </div>
                  )}
                  {selectedPost.link_url && (
                    <div>
                      <Label className="text-xs text-gray-500">UTM Link</Label>
                      <p className="text-xs text-gray-600 break-all">{selectedPost.link_url}</p>
                    </div>
                  )}
                  {selectedPost.scheduled_at && (
                    <div>
                      <Label className="text-xs text-gray-500">Scheduled</Label>
                      <p>{new Date(selectedPost.scheduled_at).toLocaleString()}</p>
                    </div>
                  )}
                  {selectedPost.published_at && (
                    <div>
                      <Label className="text-xs text-gray-500">Published</Label>
                      <p>{new Date(selectedPost.published_at).toLocaleString()}</p>
                    </div>
                  )}
                </div>
                {selectedPost.rejection_reason && (
                  <div className="bg-red-50 p-3 rounded-lg">
                    <Label className="text-xs text-red-500">Rejection Reason</Label>
                    <p className="text-sm text-red-700">{selectedPost.rejection_reason}</p>
                  </div>
                )}
              </div>
              <DialogFooter className="gap-1">
                {(selectedPost.status === "draft" || selectedPost.status === "rejected") && (
                  <>
                    <Button variant="outline" size="sm" onClick={() => {
                      setEditedPost({ caption: selectedPost.caption, visual_direction: selectedPost.visual_direction, media_url: selectedPost.media_url, scheduled_at: selectedPost.scheduled_at });
                      setPostEditOpen(true);
                      setPostDetailOpen(false);
                    }}>
                      <Edit3 className="h-4 w-4 mr-1" /> Edit
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => {
                      setRegenerateOpen(true);
                      setPostDetailOpen(false);
                    }}>
                      <RotateCw className="h-4 w-4 mr-1" /> Regenerate
                    </Button>
                  </>
                )}
                {(selectedPost.status === "draft" || selectedPost.status === "pending_review") && (
                  <>
                    <Button variant="outline" size="sm" className="text-red-600" onClick={() => {
                      setRejectOpen(true);
                      setPostDetailOpen(false);
                    }}>
                      <XCircle className="h-4 w-4 mr-1" /> Reject
                    </Button>
                    <Button size="sm" className="bg-green-600 hover:bg-green-700 text-white"
                            onClick={() => approvePost(selectedPost.id)}>
                      <CheckCircle className="h-4 w-4 mr-1" /> Approve
                    </Button>
                  </>
                )}
                {selectedPost.status === "approved" && (
                  <Button size="sm" className="bg-pink-600 hover:bg-pink-700 text-white"
                          onClick={() => publishPost(selectedPost.id)}>
                    <Send className="h-4 w-4 mr-1" /> Publish Now
                  </Button>
                )}
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* Post Edit Dialog */}
      <Dialog open={postEditOpen} onOpenChange={setPostEditOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Edit Post</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>Caption</Label>
              <Textarea value={editedPost.caption || ""} onChange={e => setEditedPost({...editedPost, caption: e.target.value})}
                        rows={6} />
            </div>
            <div>
              <Label>Visual Direction</Label>
              <Textarea value={editedPost.visual_direction || ""} onChange={e => setEditedPost({...editedPost, visual_direction: e.target.value})}
                        rows={3} />
            </div>
            <div>
              <Label>Media URL</Label>
              <Input value={editedPost.media_url || ""} onChange={e => setEditedPost({...editedPost, media_url: e.target.value})}
                     placeholder="https://..." />
            </div>
            <div>
              <Label>Scheduled At</Label>
              <Input type="datetime-local" value={editedPost.scheduled_at?.slice(0, 16) || ""}
                     onChange={e => setEditedPost({...editedPost, scheduled_at: e.target.value + ":00Z"})} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPostEditOpen(false)}>Cancel</Button>
            <Button onClick={() => updatePost(selectedPost?.id)}>Save Changes</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Reject Dialog */}
      <Dialog open={rejectOpen} onOpenChange={setRejectOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Reject Post</DialogTitle>
            <DialogDescription>Provide correction notes for the content creator</DialogDescription>
          </DialogHeader>
          <Textarea value={rejectReason} onChange={e => setRejectReason(e.target.value)}
                    placeholder="What needs to be changed..." rows={4} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRejectOpen(false)}>Cancel</Button>
            <Button variant="destructive" onClick={() => rejectPost(selectedPost?.id)}>
              <XCircle className="h-4 w-4 mr-1" /> Reject
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Regenerate Dialog */}
      <Dialog open={regenerateOpen} onOpenChange={setRegenerateOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Regenerate Post</DialogTitle>
            <DialogDescription>Provide hints for how the AI should revise this post</DialogDescription>
          </DialogHeader>
          <Textarea value={regenerateHints} onChange={e => setRegenerateHints(e.target.value)}
                    placeholder="Make it more casual, add a CTA, focus on benefits..." rows={4} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRegenerateOpen(false)}>Cancel</Button>
            <Button onClick={() => regeneratePost(selectedPost?.id)} disabled={generating || !regenerateHints}>
              {generating ? <RotateCw className="h-4 w-4 animate-spin mr-1" /> : <Sparkles className="h-4 w-4 mr-1" />}
              {generating ? "Regenerating..." : "Regenerate"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Generate Post Dialog */}
      <Dialog open={postGenerateOpen} onOpenChange={setPostGenerateOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Generate New Post</DialogTitle>
            <DialogDescription>AI will create a post draft based on your preferences</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>Post Type</Label>
              <Select value={newPostType} onValueChange={setNewPostType}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="photo">Photo</SelectItem>
                  <SelectItem value="reel">Reel</SelectItem>
                  <SelectItem value="carousel">Carousel</SelectItem>
                  <SelectItem value="product_feature">Product Feature</SelectItem>
                  <SelectItem value="story">Story</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {strategies.filter(s => s.status === "approved" || s.status === "active").length > 0 && (
              <div>
                <Label>Strategy (optional)</Label>
                <Select value={newPostStrategyId} onValueChange={setNewPostStrategyId}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select a strategy" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="">None</SelectItem>
                    {strategies.filter(s => s.status === "approved" || s.status === "active").map(s => (
                      <SelectItem key={s.id} value={s.id}>{s.title}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <div>
              <Label>Topic Hint (optional)</Label>
              <Input value={newPostTopicHint} onChange={e => setNewPostTopicHint(e.target.value)}
                     placeholder="e.g., Summer moisturizer routine" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPostGenerateOpen(false)}>Cancel</Button>
            <Button onClick={generatePost} disabled={generating}>
              {generating ? <RotateCw className="h-4 w-4 animate-spin mr-1" /> : <Sparkles className="h-4 w-4 mr-1" />}
              {generating ? "Generating..." : "Generate"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
