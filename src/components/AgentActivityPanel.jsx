import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { useToast } from '@/components/ui/use-toast';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import {
  Bot, Brain, Palette, Share2, Target, ThumbsUp, ThumbsDown,
  ChevronDown, ChevronRight, Clock, Zap, ArrowRight, ExternalLink,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Link } from 'react-router-dom';

const API_URL = import.meta.env.DEV ? 'http://localhost:8080' : '/api';

const CONTEXT_AGENTS = {
  marketing: ['cmo', 'acquisition'],
  social: ['social'],
  blog: ['content'],
};

const AGENT_STYLES = {
  cmo:         { color: 'bg-violet-100 text-violet-700', icon: Brain },
  content:     { color: 'bg-pink-100 text-pink-700', icon: Palette },
  social:      { color: 'bg-sky-100 text-sky-700', icon: Share2 },
  acquisition: { color: 'bg-amber-100 text-amber-700', icon: Target },
};

const STATUS_STYLES = {
  pending_approval: 'bg-amber-100 text-amber-700',
  approved:         'bg-green-100 text-green-700',
  rejected:         'bg-red-100 text-red-700',
  auto_approved:    'bg-slate-100 text-slate-600',
  in_progress:      'bg-blue-100 text-blue-700',
  completed:        'bg-green-100 text-green-700',
  failed:           'bg-red-100 text-red-700',
};

const deriveStatus = (d) => {
  if (d.status) return d.status;
  if (d.rejected_at) return 'rejected';
  if (d.approved_at) return 'approved';
  if (d.requires_approval) return 'pending_approval';
  return 'auto_approved';
};

const AgentBadge = ({ agent }) => {
  const config = AGENT_STYLES[agent] || { color: 'bg-slate-100 text-slate-600', icon: Zap };
  const Icon = config.icon;
  return (
    <Badge className={cn(config.color, 'font-medium border-0 capitalize flex items-center gap-1 text-xs')}>
      <Icon className="w-3 h-3" />
      {agent}
    </Badge>
  );
};

const StatusBadge = ({ status }) => (
  <Badge className={cn(STATUS_STYLES[status] || 'bg-slate-100 text-slate-600', 'border-0 capitalize text-xs')}>
    {(status || 'unknown').replace(/_/g, ' ')}
  </Badge>
);

const timeAgo = (ts) => {
  if (!ts) return '';
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
};

export default function AgentActivityPanel({ context }) {
  const { getAuthHeader } = useAuth();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [decisions, setDecisions] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(null);

  const headers = useCallback(
    () => ({ ...getAuthHeader(), 'Content-Type': 'application/json' }),
    [getAuthHeader],
  );

  const agentFilters = CONTEXT_AGENTS[context] || [];

  const fetchData = useCallback(async () => {
    try {
      const opts = { headers: headers() };

      // Fetch decisions for each agent filter, then merge
      const decisionResults = await Promise.all(
        agentFilters.map((agent) =>
          fetch(`${API_URL}/agents/decisions?agent=${agent}&limit=10`, opts)
            .then((r) => (r.ok ? r.json() : { decisions: [] })),
        ),
      );
      const allDecisions = decisionResults.flatMap((r) => r.decisions || []);
      // Dedupe by uuid and derive status
      const seen = new Set();
      const deduped = allDecisions.filter((d) => {
        if (seen.has(d.uuid)) return false;
        seen.add(d.uuid);
        return true;
      }).map((d) => ({ ...d, _status: deriveStatus(d) }));
      setDecisions(deduped);

      // Fetch tasks
      const taskResults = await Promise.all(
        agentFilters.map((agent) =>
          fetch(`${API_URL}/agents/tasks?agent=${agent}&limit=5`, opts)
            .then((r) => (r.ok ? r.json() : { tasks: [] })),
        ),
      );
      const allTasks = taskResults.flatMap((r) => r.tasks || []);
      const seenTasks = new Set();
      setTasks(
        allTasks.filter((t) => {
          const key = t.uuid || t.id;
          if (seenTasks.has(key)) return false;
          seenTasks.add(key);
          return true;
        }),
      );
    } catch (err) {
      console.error('AgentActivityPanel fetch error:', err);
    } finally {
      setLoading(false);
    }
  }, [agentFilters.join(','), headers]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const handleAction = async (uuid, action) => {
    setActionLoading(uuid);
    try {
      const res = await fetch(`${API_URL}/agents/decisions/${uuid}/${action}`, {
        method: 'POST',
        headers: headers(),
      });
      if (!res.ok) throw new Error(`Failed to ${action}`);
      toast({ title: `Decision ${action}d`, description: `Successfully ${action}d the decision.` });
      fetchData();
    } catch (err) {
      toast({ title: 'Error', description: err.message, variant: 'destructive' });
    } finally {
      setActionLoading(null);
    }
  };

  const pending = decisions.filter((d) => d._status === 'pending_approval');
  const pendingCount = pending.length;

  // Hide panel entirely when nothing to show
  if (!loading && decisions.length === 0 && tasks.length === 0) return null;

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Card className="border-slate-200 shadow-sm">
        <CollapsibleTrigger asChild>
          <CardHeader className="cursor-pointer select-none py-3 px-4 flex flex-row items-center justify-between hover:bg-slate-50/60 transition-colors">
            <div className="flex items-center gap-2">
              <Bot className="w-4 h-4 text-slate-500" />
              <span className="text-sm font-semibold text-slate-700">Agent Activity</span>
              {pendingCount > 0 && (
                <Badge className="bg-amber-100 text-amber-700 border-0 text-xs ml-1">
                  {pendingCount} pending
                </Badge>
              )}
            </div>
            {open ? (
              <ChevronDown className="w-4 h-4 text-slate-400" />
            ) : (
              <ChevronRight className="w-4 h-4 text-slate-400" />
            )}
          </CardHeader>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <CardContent className="pt-0 pb-4 px-4 space-y-4">
            {loading ? (
              <div className="space-y-2">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-10 bg-slate-100 rounded animate-pulse" />
                ))}
              </div>
            ) : (
              <>
                {/* Pending Approvals */}
                {pending.length > 0 && (
                  <div className="space-y-2">
                    <p className="text-xs font-semibold uppercase tracking-wider text-amber-700">
                      Pending Approvals
                    </p>
                    <div className="space-y-2">
                      {pending.map((d) => (
                        <div
                          key={d.uuid}
                          className="flex items-center gap-3 bg-amber-50/60 border border-amber-100 rounded-lg px-3 py-2"
                        >
                          <AgentBadge agent={d.agent} />
                          <span className="text-xs font-medium text-slate-700 shrink-0">
                            {d.decision_type || d.type || '-'}
                          </span>
                          <span className="text-xs text-slate-500 truncate flex-1 min-w-0">
                            {d.reasoning || ''}
                          </span>
                          {d.confidence != null && (
                            <Progress
                              value={d.confidence * 100}
                              className="w-16 h-1.5 shrink-0"
                            />
                          )}
                          <div className="flex items-center gap-1 shrink-0">
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-7 px-2 text-green-600 hover:bg-green-50 hover:text-green-700"
                              disabled={actionLoading === d.uuid}
                              onClick={(e) => { e.stopPropagation(); handleAction(d.uuid, 'approve'); }}
                            >
                              <ThumbsUp className="w-3.5 h-3.5" />
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-7 px-2 text-red-500 hover:bg-red-50 hover:text-red-600"
                              disabled={actionLoading === d.uuid}
                              onClick={(e) => { e.stopPropagation(); handleAction(d.uuid, 'reject'); }}
                            >
                              <ThumbsDown className="w-3.5 h-3.5" />
                            </Button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Recent Tasks */}
                {tasks.length > 0 && (
                  <div className="space-y-2">
                    <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                      Recent Tasks
                    </p>
                    <div className="space-y-1.5">
                      {tasks.map((t, i) => (
                        <div
                          key={t.uuid || t.id || i}
                          className="flex items-center gap-3 text-xs bg-slate-50/60 rounded-lg px-3 py-2"
                        >
                          <span className="font-medium text-slate-700">
                            {t.task_type || t.type || '-'}
                          </span>
                          {t.target_agent && (
                            <>
                              <ArrowRight className="w-3 h-3 text-slate-400 shrink-0" />
                              <AgentBadge agent={t.target_agent} />
                            </>
                          )}
                          <StatusBadge status={t.status} />
                          <span className="text-slate-400 ml-auto shrink-0 flex items-center gap-1">
                            <Clock className="w-3 h-3" />
                            {timeAgo(t.created_at || t.updated_at)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Footer link */}
                <div className="pt-1">
                  <Link to="/agentdashboard">
                    <Button variant="ghost" size="sm" className="text-xs text-slate-500 hover:text-slate-700 px-0 h-auto">
                      View All in Agent Dashboard
                      <ExternalLink className="w-3 h-3 ml-1" />
                    </Button>
                  </Link>
                </div>
              </>
            )}
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  );
}
