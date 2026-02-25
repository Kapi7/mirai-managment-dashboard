import React, { useState, useEffect, useCallback } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { useToast } from "@/components/ui/use-toast";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  FileText,
  RefreshCw,
  Sparkles,
  Send,
  Eye,
  Edit3,
  Trash2,
  ExternalLink,
  Clock,
  CheckCircle,
  XCircle,
  RotateCw,
  BookOpen,
  TrendingUp,
  Lightbulb,
  Search,
  Zap,
  Target,
  ArrowRight,
  Brain
} from "lucide-react";
import AgentActivityPanel from '@/components/AgentActivityPanel';

// Blog API - use proxy routes in production, direct in development
const API_URL = import.meta.env.DEV ? 'http://localhost:8080' : '/api';

const CATEGORY_COLORS = {
  lifestyle: "bg-pink-100 text-pink-700",
  reviews: "bg-blue-100 text-blue-700",
  skin_concerns: "bg-green-100 text-green-700",
  ingredients: "bg-purple-100 text-purple-700"
};

const CATEGORY_NAMES = {
  lifestyle: "The Mirai Blog",
  reviews: "Mirai Skin Reviews",
  skin_concerns: "Skin Concerns",
  ingredients: "Ingredients"
};

export default function BlogCreator() {
  const { getAuthHeader } = useAuth();
  const { toast } = useToast();

  // State
  const [activeTab, setActiveTab] = useState("suggestions");
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);

  // Categories and blogs
  const [categories, setCategories] = useState({});
  const [shopifyBlogs, setShopifyBlogs] = useState([]);

  // Generator form
  const [formCategory, setFormCategory] = useState("");
  const [formTopic, setFormTopic] = useState("");
  const [formKeywords, setFormKeywords] = useState("");
  const [formWordCount, setFormWordCount] = useState(1000);
  const [suggestedKeywords, setSuggestedKeywords] = useState([]);

  // Drafts
  const [drafts, setDrafts] = useState([]);
  const [selectedDraft, setSelectedDraft] = useState(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [regenerateOpen, setRegenerateOpen] = useState(false);
  const [approveOpen, setApproveOpen] = useState(false);
  const [regenerateHints, setRegenerateHints] = useState("");
  const [editedDraft, setEditedDraft] = useState({});
  const [selectedBlogId, setSelectedBlogId] = useState("");

  // Published
  const [published, setPublished] = useState([]);

  // AI Suggestions
  const [suggestions, setSuggestions] = useState([]);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);
  const [generatingSuggestion, setGeneratingSuggestion] = useState(null);

  // Fetch initial data
  useEffect(() => {
    fetchCategories();
    fetchShopifyBlogs();
    fetchDrafts();
    fetchPublished();
    fetchSuggestions();
  }, []);

  // Fetch SEO keywords when category changes
  useEffect(() => {
    if (formCategory) {
      fetchSeoKeywords(formCategory);
    }
  }, [formCategory]);

  const fetchCategories = async () => {
    try {
      const res = await fetch(`${API_URL}/blog/categories`, {
        headers: getAuthHeader()
      });
      const data = await res.json();
      setCategories(data.categories || {});
    } catch (error) {
      console.error("Failed to fetch categories:", error);
    } finally {
      setLoading(false);
    }
  };

  const fetchShopifyBlogs = async () => {
    try {
      const res = await fetch(`${API_URL}/blog/shopify-blogs`, {
        headers: getAuthHeader()
      });
      const data = await res.json();
      setShopifyBlogs(data.blogs || []);
      if (data.blogs?.length > 0) {
        setSelectedBlogId(data.blogs[0].id);
      }
    } catch (error) {
      console.error("Failed to fetch Shopify blogs:", error);
    }
  };

  const fetchSeoKeywords = async (category) => {
    try {
      const res = await fetch(`${API_URL}/blog/seo-keywords/${category}`, {
        headers: getAuthHeader()
      });
      const data = await res.json();
      setSuggestedKeywords(data.keywords || []);
    } catch (error) {
      console.error("Failed to fetch SEO keywords:", error);
    }
  };

  const fetchDrafts = async () => {
    try {
      const res = await fetch(`${API_URL}/blog/drafts`, {
        headers: getAuthHeader()
      });
      const data = await res.json();
      setDrafts(data.drafts || []);
    } catch (error) {
      console.error("Failed to fetch drafts:", error);
    }
  };

  const fetchPublished = async () => {
    try {
      const res = await fetch(`${API_URL}/blog/published`, {
        headers: getAuthHeader()
      });
      const data = await res.json();
      setPublished(data.articles || []);
    } catch (error) {
      console.error("Failed to fetch published:", error);
    }
  };

  const fetchSuggestions = async (forceRefresh = false) => {
    setLoadingSuggestions(true);
    try {
      const res = await fetch(
        `${API_URL}/blog/seo-agent/suggestions?force_refresh=${forceRefresh}&count=5`,
        { headers: getAuthHeader() }
      );
      const data = await res.json();
      setSuggestions(data.suggestions || []);
    } catch (error) {
      console.error("Failed to fetch suggestions:", error);
    } finally {
      setLoadingSuggestions(false);
    }
  };

  const handleGenerateFromSuggestion = async (suggestionId) => {
    setGeneratingSuggestion(suggestionId);
    try {
      const res = await fetch(`${API_URL}/blog/seo-agent/generate/${suggestionId}`, {
        method: "POST",
        headers: {
          ...getAuthHeader(),
          "Content-Type": "application/json"
        }
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to generate");

      toast({
        title: "Article Generated!",
        description: `"${data.title}" is ready for review in Drafts`
      });

      // Refresh drafts and suggestions
      fetchDrafts();
      fetchSuggestions();
      setActiveTab("drafts");
    } catch (error) {
      toast({
        title: "Generation failed",
        description: error.message,
        variant: "destructive"
      });
    } finally {
      setGeneratingSuggestion(null);
    }
  };

  const handleDismissSuggestion = async (suggestionId) => {
    try {
      await fetch(`${API_URL}/blog/seo-agent/dismiss/${suggestionId}`, {
        method: "POST",
        headers: getAuthHeader()
      });
      setSuggestions(suggestions.filter(s => s.id !== suggestionId));
    } catch (error) {
      console.error("Failed to dismiss:", error);
    }
  };

  const handleGenerate = async () => {
    if (!formCategory || !formTopic) {
      toast({
        title: "Missing fields",
        description: "Please select a category and enter a topic",
        variant: "destructive"
      });
      return;
    }

    const keywords = formKeywords.split(",").map(k => k.trim()).filter(k => k);
    if (keywords.length === 0) {
      toast({
        title: "Missing keywords",
        description: "Please enter at least one SEO keyword",
        variant: "destructive"
      });
      return;
    }

    setGenerating(true);
    try {
      const res = await fetch(`${API_URL}/blog/generate`, {
        method: "POST",
        headers: {
          ...getAuthHeader(),
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          category: formCategory,
          topic: formTopic,
          keywords,
          word_count: formWordCount
        })
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to generate");

      toast({
        title: "Article Generated!",
        description: `"${data.title}" is ready for review`
      });

      // Reset form and switch to drafts
      setFormTopic("");
      setFormKeywords("");
      setActiveTab("drafts");
      fetchDrafts();
    } catch (error) {
      toast({
        title: "Generation failed",
        description: error.message,
        variant: "destructive"
      });
    } finally {
      setGenerating(false);
    }
  };

  const handleRegenerate = async () => {
    if (!selectedDraft || !regenerateHints) return;

    setGenerating(true);
    try {
      const res = await fetch(`${API_URL}/blog/regenerate/${selectedDraft.id}`, {
        method: "POST",
        headers: {
          ...getAuthHeader(),
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          hints: regenerateHints,
          keep_keywords: true
        })
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to regenerate");

      toast({
        title: "Article Regenerated!",
        description: `Regeneration ${data.regeneration_count}/5 complete`
      });

      setRegenerateOpen(false);
      setRegenerateHints("");
      fetchDrafts();
    } catch (error) {
      toast({
        title: "Regeneration failed",
        description: error.message,
        variant: "destructive"
      });
    } finally {
      setGenerating(false);
    }
  };

  const handleUpdateDraft = async () => {
    if (!selectedDraft) return;

    try {
      const res = await fetch(`${API_URL}/blog/draft/${selectedDraft.id}`, {
        method: "PUT",
        headers: {
          ...getAuthHeader(),
          "Content-Type": "application/json"
        },
        body: JSON.stringify(editedDraft)
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to update");

      toast({ title: "Draft Updated!" });
      setEditOpen(false);
      fetchDrafts();
    } catch (error) {
      toast({
        title: "Update failed",
        description: error.message,
        variant: "destructive"
      });
    }
  };

  const handleApprove = async () => {
    if (!selectedDraft || !selectedBlogId) return;

    setGenerating(true);
    try {
      const res = await fetch(`${API_URL}/blog/approve/${selectedDraft.id}`, {
        method: "POST",
        headers: {
          ...getAuthHeader(),
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          blog_id: selectedBlogId,
          publish_immediately: true
        })
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to publish");

      toast({
        title: "Article Published!",
        description: `"${data.title}" is now live on your Shopify store`
      });

      setApproveOpen(false);
      fetchDrafts();
      fetchPublished();
    } catch (error) {
      toast({
        title: "Publish failed",
        description: error.message,
        variant: "destructive"
      });
    } finally {
      setGenerating(false);
    }
  };

  const handleReject = async (draftId) => {
    try {
      const res = await fetch(`${API_URL}/blog/reject/${draftId}`, {
        method: "POST",
        headers: getAuthHeader()
      });

      if (!res.ok) throw new Error("Failed to delete");

      toast({ title: "Draft Deleted" });
      fetchDrafts();
    } catch (error) {
      toast({
        title: "Delete failed",
        description: error.message,
        variant: "destructive"
      });
    }
  };

  const openPreview = (draft) => {
    setSelectedDraft(draft);
    setPreviewOpen(true);
  };

  const openEdit = (draft) => {
    setSelectedDraft(draft);
    setEditedDraft({
      title: draft.title,
      body: draft.body,
      meta_description: draft.meta_description,
      excerpt: draft.excerpt
    });
    setEditOpen(true);
  };

  const openRegenerate = (draft) => {
    setSelectedDraft(draft);
    setRegenerateHints("");
    setRegenerateOpen(true);
  };

  const openApprove = (draft) => {
    setSelectedDraft(draft);
    setApproveOpen(true);
  };

  const addKeyword = (keyword) => {
    const current = formKeywords.split(",").map(k => k.trim()).filter(k => k);
    if (!current.includes(keyword)) {
      setFormKeywords([...current, keyword].join(", "));
    }
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return "";
    return new Date(dateStr).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric"
    });
  };

  const estimateReadTime = (wordCount) => {
    const minutes = Math.ceil(wordCount / 200);
    return `${minutes} min read`;
  };

  if (loading) {
    return (
      <div className="p-6 space-y-6">
        <Skeleton className="h-8 w-64" />
        <div className="grid grid-cols-3 gap-4">
          {[1, 2, 3].map(i => <Skeleton key={i} className="h-32" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Agent Activity Panel */}
      <AgentActivityPanel context="blog" />

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Blog Creator</h1>
          <p className="text-slate-500">AI-powered SEO content for your Shopify store</p>
        </div>
        <Button
          variant="outline"
          onClick={() => { fetchDrafts(); fetchPublished(); }}
        >
          <RefreshCw className="w-4 h-4 mr-2" />
          Refresh
        </Button>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-4 flex items-center gap-4">
            <div className="p-3 bg-amber-100 rounded-lg">
              <Clock className="w-6 h-6 text-amber-600" />
            </div>
            <div>
              <p className="text-2xl font-bold">{drafts.length}</p>
              <p className="text-sm text-slate-500">Pending Drafts</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 flex items-center gap-4">
            <div className="p-3 bg-green-100 rounded-lg">
              <CheckCircle className="w-6 h-6 text-green-600" />
            </div>
            <div>
              <p className="text-2xl font-bold">{published.length}</p>
              <p className="text-sm text-slate-500">Published Articles</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 flex items-center gap-4">
            <div className="p-3 bg-blue-100 rounded-lg">
              <BookOpen className="w-6 h-6 text-blue-600" />
            </div>
            <div>
              <p className="text-2xl font-bold">{shopifyBlogs.length}</p>
              <p className="text-sm text-slate-500">Shopify Blogs</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Main Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid w-full grid-cols-4 max-w-xl">
          <TabsTrigger value="suggestions" className="flex items-center gap-2">
            <Brain className="w-4 h-4" />
            AI Ideas
            {suggestions.length > 0 && (
              <Badge variant="secondary" className="ml-1 bg-indigo-100 text-indigo-700">{suggestions.length}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="generator" className="flex items-center gap-2">
            <Sparkles className="w-4 h-4" />
            Manual
          </TabsTrigger>
          <TabsTrigger value="drafts" className="flex items-center gap-2">
            <FileText className="w-4 h-4" />
            Drafts
            {drafts.length > 0 && (
              <Badge variant="secondary" className="ml-1">{drafts.length}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="published" className="flex items-center gap-2">
            <CheckCircle className="w-4 h-4" />
            Published
          </TabsTrigger>
        </TabsList>

        {/* AI Suggestions Tab */}
        <TabsContent value="suggestions" className="space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-900 flex items-center gap-2">
                <Brain className="w-5 h-5 text-indigo-600" />
                AI-Powered Content Ideas
              </h2>
              <p className="text-sm text-slate-500">
                Smart suggestions based on content gaps, trending topics, and seasonal opportunities
              </p>
            </div>
            <Button
              variant="outline"
              onClick={() => fetchSuggestions(true)}
              disabled={loadingSuggestions}
            >
              {loadingSuggestions ? (
                <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <RefreshCw className="w-4 h-4 mr-2" />
              )}
              Refresh Ideas
            </Button>
          </div>

          {loadingSuggestions && suggestions.length === 0 ? (
            <div className="space-y-4">
              {[1, 2, 3].map(i => (
                <Card key={i} className="animate-pulse">
                  <CardContent className="p-6">
                    <div className="h-4 bg-slate-200 rounded w-3/4 mb-3"></div>
                    <div className="h-3 bg-slate-100 rounded w-1/2 mb-2"></div>
                    <div className="h-3 bg-slate-100 rounded w-1/4"></div>
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : suggestions.length === 0 ? (
            <Card>
              <CardContent className="p-12 text-center">
                <Brain className="w-12 h-12 mx-auto text-slate-300 mb-4" />
                <h3 className="text-lg font-medium text-slate-600">No suggestions yet</h3>
                <p className="text-slate-400 mb-4">Click "Refresh Ideas" to generate AI content suggestions</p>
                <Button onClick={() => fetchSuggestions(true)}>
                  <Zap className="w-4 h-4 mr-2" />
                  Generate Ideas
                </Button>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-4">
              {suggestions.map((suggestion) => (
                <Card key={suggestion.id} className="hover:shadow-md transition-shadow border-l-4 border-l-indigo-500">
                  <CardContent className="p-5">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-2">
                          <Badge className={CATEGORY_COLORS[suggestion.category]}>
                            {CATEGORY_NAMES[suggestion.category]}
                          </Badge>
                          <Badge
                            variant="outline"
                            className={
                              suggestion.priority === "high"
                                ? "border-red-300 text-red-700 bg-red-50"
                                : suggestion.priority === "medium"
                                ? "border-yellow-300 text-yellow-700 bg-yellow-50"
                                : "border-slate-300"
                            }
                          >
                            {suggestion.priority} priority
                          </Badge>
                          <Badge variant="outline" className="border-green-300 text-green-700 bg-green-50">
                            <Target className="w-3 h-3 mr-1" />
                            {suggestion.estimated_traffic} traffic
                          </Badge>
                        </div>
                        <h3 className="font-semibold text-slate-900 text-lg mb-1">
                          {suggestion.title}
                        </h3>
                        <p className="text-sm text-slate-600 mb-3">
                          {suggestion.topic}
                        </p>
                        <div className="flex items-center gap-4 text-xs text-slate-500 mb-3">
                          <span className="flex items-center gap-1">
                            <FileText className="w-3 h-3" />
                            {suggestion.word_count} words
                          </span>
                          <span>{suggestion.keywords?.join(", ")}</span>
                        </div>
                        <div className="p-3 bg-indigo-50 rounded-lg">
                          <p className="text-sm text-indigo-700">
                            <Lightbulb className="w-4 h-4 inline mr-1" />
                            <strong>Why this topic:</strong> {suggestion.reason}
                          </p>
                        </div>
                      </div>
                      <div className="flex flex-col gap-2">
                        <Button
                          onClick={() => handleGenerateFromSuggestion(suggestion.id)}
                          disabled={generatingSuggestion === suggestion.id}
                          className="bg-indigo-600 hover:bg-indigo-700"
                        >
                          {generatingSuggestion === suggestion.id ? (
                            <>
                              <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                              Generating...
                            </>
                          ) : (
                            <>
                              <Zap className="w-4 h-4 mr-2" />
                              Generate
                            </>
                          )}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-slate-400 hover:text-slate-600"
                          onClick={() => handleDismissSuggestion(suggestion.id)}
                        >
                          <XCircle className="w-4 h-4 mr-1" />
                          Dismiss
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          {/* Info box */}
          <Card className="bg-slate-50 border-slate-200">
            <CardContent className="p-4">
              <h4 className="font-medium text-slate-700 flex items-center gap-2 mb-2">
                <Lightbulb className="w-4 h-4 text-amber-500" />
                How AI Ideas Work
              </h4>
              <ul className="text-sm text-slate-600 space-y-1">
                <li>The AI analyzes your existing content to find gaps</li>
                <li>It considers seasonal trends and current month relevance</li>
                <li>Topics are optimized for SEO and match your brand voice</li>
                <li>Click "Generate" to create a full article ready for review</li>
              </ul>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Generator Tab */}
        <TabsContent value="generator" className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Main Form */}
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Sparkles className="w-5 h-5 text-indigo-600" />
                  Generate New Article
                </CardTitle>
                <CardDescription>
                  AI will create SEO-optimized content based on your inputs
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label>Category</Label>
                  <Select value={formCategory} onValueChange={setFormCategory}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select a blog category" />
                    </SelectTrigger>
                    <SelectContent>
                      {Object.entries(categories).map(([key, cat]) => (
                        <SelectItem key={key} value={key}>
                          <div className="flex items-center gap-2">
                            <span className={`px-2 py-0.5 rounded text-xs ${CATEGORY_COLORS[key]}`}>
                              {cat.name}
                            </span>
                          </div>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {formCategory && categories[formCategory] && (
                    <p className="text-xs text-slate-500">
                      {categories[formCategory].description}
                    </p>
                  )}
                </div>

                <div className="space-y-2">
                  <Label>Topic / Article Title Idea</Label>
                  <Input
                    placeholder="e.g., The benefits of Snail Mucin for hydration"
                    value={formTopic}
                    onChange={(e) => setFormTopic(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label>SEO Keywords (comma-separated)</Label>
                  <Textarea
                    placeholder="e.g., snail mucin, hydration, K-beauty skincare"
                    value={formKeywords}
                    onChange={(e) => setFormKeywords(e.target.value)}
                    rows={2}
                  />
                  {suggestedKeywords.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-2">
                      <span className="text-xs text-slate-500 mr-2">Suggestions:</span>
                      {suggestedKeywords.slice(0, 8).map((kw, i) => (
                        <Badge
                          key={i}
                          variant="outline"
                          className="cursor-pointer hover:bg-indigo-50"
                          onClick={() => addKeyword(kw)}
                        >
                          + {kw}
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>

                <div className="space-y-2">
                  <Label>Target Word Count</Label>
                  <Select
                    value={formWordCount.toString()}
                    onValueChange={(v) => setFormWordCount(parseInt(v))}
                  >
                    <SelectTrigger className="w-40">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="500">500 words</SelectItem>
                      <SelectItem value="800">800 words</SelectItem>
                      <SelectItem value="1000">1000 words</SelectItem>
                      <SelectItem value="1500">1500 words</SelectItem>
                      <SelectItem value="2000">2000 words</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <Button
                  className="w-full"
                  onClick={handleGenerate}
                  disabled={generating || !formCategory || !formTopic}
                >
                  {generating ? (
                    <>
                      <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                      Generating with GPT-4o...
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-4 h-4 mr-2" />
                      Generate Article
                    </>
                  )}
                </Button>
              </CardContent>
            </Card>

            {/* Category Info Panel */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Lightbulb className="w-5 h-5 text-amber-500" />
                  Writing Tips
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4 text-sm">
                {formCategory && categories[formCategory] ? (
                  <>
                    <div>
                      <p className="font-medium text-slate-700">Style:</p>
                      <p className="text-slate-500">{categories[formCategory].tone}</p>
                    </div>
                    <div>
                      <p className="font-medium text-slate-700">Structure:</p>
                      <p className="text-slate-500">{categories[formCategory].structure}</p>
                    </div>
                    <div>
                      <p className="font-medium text-slate-700">Example Topics:</p>
                      <ul className="list-disc list-inside text-slate-500 space-y-1">
                        {categories[formCategory].example_topics?.map((t, i) => (
                          <li key={i} className="text-xs">{t}</li>
                        ))}
                      </ul>
                    </div>
                  </>
                ) : (
                  <p className="text-slate-500">Select a category to see writing tips</p>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* Drafts Tab */}
        <TabsContent value="drafts" className="space-y-4">
          {drafts.length === 0 ? (
            <Card>
              <CardContent className="p-12 text-center">
                <FileText className="w-12 h-12 mx-auto text-slate-300 mb-4" />
                <h3 className="text-lg font-medium text-slate-600">No drafts yet</h3>
                <p className="text-slate-400 mb-4">Generate your first article to see it here</p>
                <Button variant="outline" onClick={() => setActiveTab("generator")}>
                  <Sparkles className="w-4 h-4 mr-2" />
                  Create Article
                </Button>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-4">
              {drafts.map((draft) => (
                <Card key={draft.id} className="hover:shadow-md transition-shadow">
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-2">
                          <Badge className={CATEGORY_COLORS[draft.category]}>
                            {CATEGORY_NAMES[draft.category]}
                          </Badge>
                          <span className="text-xs text-slate-400">
                            {formatDate(draft.created_at)}
                          </span>
                          {draft.regeneration_count > 0 && (
                            <Badge variant="outline" className="text-xs">
                              <RotateCw className="w-3 h-3 mr-1" />
                              Regen {draft.regeneration_count}/5
                            </Badge>
                          )}
                        </div>
                        <h3 className="font-semibold text-slate-900 mb-1 truncate">
                          {draft.title}
                        </h3>
                        <p className="text-sm text-slate-500 line-clamp-2">
                          {draft.excerpt}
                        </p>
                        <div className="flex items-center gap-4 mt-2 text-xs text-slate-400">
                          <span>{draft.word_count} words</span>
                          <span>{estimateReadTime(draft.word_count)}</span>
                          <span>{draft.keywords?.join(", ")}</span>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <Button size="sm" variant="ghost" onClick={() => openPreview(draft)}>
                          <Eye className="w-4 h-4" />
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => openEdit(draft)}>
                          <Edit3 className="w-4 h-4" />
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => openRegenerate(draft)}>
                          <RotateCw className="w-4 h-4" />
                        </Button>
                        <Button size="sm" variant="ghost" className="text-red-500" onClick={() => handleReject(draft.id)}>
                          <Trash2 className="w-4 h-4" />
                        </Button>
                        <Button size="sm" onClick={() => openApprove(draft)}>
                          <Send className="w-4 h-4 mr-1" />
                          Publish
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        {/* Published Tab */}
        <TabsContent value="published" className="space-y-4">
          {published.length === 0 ? (
            <Card>
              <CardContent className="p-12 text-center">
                <CheckCircle className="w-12 h-12 mx-auto text-slate-300 mb-4" />
                <h3 className="text-lg font-medium text-slate-600">No published articles yet</h3>
                <p className="text-slate-400">Articles you publish will appear here</p>
              </CardContent>
            </Card>
          ) : (
            <Card>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Title</TableHead>
                    <TableHead>Category</TableHead>
                    <TableHead>Published</TableHead>
                    <TableHead>Link</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {published.map((article) => (
                    <TableRow key={article.id}>
                      <TableCell className="font-medium">{article.title}</TableCell>
                      <TableCell>
                        <Badge className={CATEGORY_COLORS[article.category]}>
                          {CATEGORY_NAMES[article.category]}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-slate-500">
                        {formatDate(article.published_at)}
                      </TableCell>
                      <TableCell>
                        {article.shopify_url ? (
                          <a
                            href={article.shopify_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-indigo-600 hover:underline flex items-center gap-1"
                          >
                            View <ExternalLink className="w-3 h-3" />
                          </a>
                        ) : (
                          <span className="text-slate-400">No URL</span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Card>
          )}
        </TabsContent>
      </Tabs>

      {/* Preview Dialog */}
      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="max-w-4xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{selectedDraft?.title}</DialogTitle>
            <DialogDescription>
              <Badge className={CATEGORY_COLORS[selectedDraft?.category]}>
                {CATEGORY_NAMES[selectedDraft?.category]}
              </Badge>
              <span className="ml-2 text-slate-500">
                {selectedDraft?.word_count} words
              </span>
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="p-3 bg-slate-50 rounded-lg">
              <p className="text-sm font-medium text-slate-600">Meta Description:</p>
              <p className="text-sm text-slate-500">{selectedDraft?.meta_description}</p>
            </div>
            <div className="p-3 bg-slate-50 rounded-lg">
              <p className="text-sm font-medium text-slate-600">Excerpt:</p>
              <p className="text-sm text-slate-500">{selectedDraft?.excerpt}</p>
            </div>
            <div
              className="prose prose-sm max-w-none"
              dangerouslySetInnerHTML={{ __html: selectedDraft?.body }}
            />
            <div className="flex flex-wrap gap-1">
              <span className="text-sm text-slate-500 mr-2">Tags:</span>
              {selectedDraft?.suggested_tags?.map((tag, i) => (
                <Badge key={i} variant="outline">{tag}</Badge>
              ))}
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="max-w-4xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Edit Draft</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Title</Label>
              <Input
                value={editedDraft.title || ""}
                onChange={(e) => setEditedDraft({ ...editedDraft, title: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>Meta Description</Label>
              <Textarea
                value={editedDraft.meta_description || ""}
                onChange={(e) => setEditedDraft({ ...editedDraft, meta_description: e.target.value })}
                rows={2}
              />
            </div>
            <div className="space-y-2">
              <Label>Excerpt</Label>
              <Textarea
                value={editedDraft.excerpt || ""}
                onChange={(e) => setEditedDraft({ ...editedDraft, excerpt: e.target.value })}
                rows={2}
              />
            </div>
            <div className="space-y-2">
              <Label>Body (HTML)</Label>
              <Textarea
                value={editedDraft.body || ""}
                onChange={(e) => setEditedDraft({ ...editedDraft, body: e.target.value })}
                rows={15}
                className="font-mono text-xs"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleUpdateDraft}>
              Save Changes
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Regenerate Dialog */}
      <Dialog open={regenerateOpen} onOpenChange={setRegenerateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Regenerate with Hints</DialogTitle>
            <DialogDescription>
              Tell the AI what to change or improve
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <p className="text-sm text-slate-600">
              Current article: <strong>{selectedDraft?.title}</strong>
            </p>
            <div className="space-y-2">
              <Label>Your Feedback / Hints</Label>
              <Textarea
                placeholder="e.g., Make it more casual, add a section about combining with hyaluronic acid, include more product recommendations..."
                value={regenerateHints}
                onChange={(e) => setRegenerateHints(e.target.value)}
                rows={4}
              />
            </div>
            <p className="text-xs text-slate-500">
              Regenerations used: {selectedDraft?.regeneration_count || 0}/5
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRegenerateOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleRegenerate}
              disabled={generating || !regenerateHints || (selectedDraft?.regeneration_count >= 5)}
            >
              {generating ? (
                <>
                  <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                  Regenerating...
                </>
              ) : (
                <>
                  <RotateCw className="w-4 h-4 mr-2" />
                  Regenerate
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Approve/Publish Dialog */}
      <Dialog open={approveOpen} onOpenChange={setApproveOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Publish to Shopify</DialogTitle>
            <DialogDescription>
              This will create a new article in your Shopify store
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <p className="text-sm text-slate-600">
              Publishing: <strong>{selectedDraft?.title}</strong>
            </p>
            <div className="space-y-2">
              <Label>Select Blog</Label>
              <Select value={selectedBlogId} onValueChange={setSelectedBlogId}>
                <SelectTrigger>
                  <SelectValue placeholder="Choose a blog" />
                </SelectTrigger>
                <SelectContent>
                  {shopifyBlogs.map((blog) => (
                    <SelectItem key={blog.id} value={blog.id}>
                      {blog.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setApproveOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleApprove}
              disabled={generating || !selectedBlogId}
            >
              {generating ? (
                <>
                  <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                  Publishing...
                </>
              ) : (
                <>
                  <Send className="w-4 h-4 mr-2" />
                  Publish Now
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
