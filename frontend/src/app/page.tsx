"use client";

import React, { useState, useEffect, useMemo } from "react";
import {
  Search,
  Globe,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  ExternalLink,
  RefreshCw,
  FileText,
  ArrowUpRight,
  Layers,
  Info,
  ShieldCheck,
  Zap,
  Smartphone,
  Monitor,
  Flame,
  Wrench,
  GitCommit,
  Check,
  Download,
  TrendingUp,
  TrendingDown,
  BarChart3,
  Link2,
  LogOut,
  Bug,
  Sparkles,
  Target,
  Calendar,
  Compass,
  FileEdit,
  Copy,
  Users,
  HelpCircle,
  Split,
  Tag
} from "lucide-react";

interface CrawlPage {
  id: string;
  job_id: string;
  url: string;
  status_code: number;
  title: string | null;
  meta_desc: string | null;
  h1: string | null;
  canonical: string | null;
  word_count: number;
  links_out: number;
  inlinks_count: number;
  indexable: boolean;
  indexability_status: string;
  redirect_url: string | null;
  content_type: string;
  response_time_ms: number;
  outlinks_list: string[];
  headings?: Array<{ level: string; text: string }>;
  text_terms?: string[];
  created_at: string;
}

interface TechnicalIssue {
  id: string;
  type: string;
  severity: "high" | "medium" | "low";
  impact: string;
  effort: "low" | "medium" | "high";
  urls: string[];
  evidence: Array<{ table: string; id: string; field: string; value?: any }>;
  fix_hint: string;
  confidence: number;
}

interface VerifierReport {
  verified_issues: TechnicalIssue[];
  rejected_issues: Array<{ issue_id?: string; id?: string; type: string; reason: string; issue_dump?: any }>;
  total_checked: number;
  verified_count: number;
  rejected_count: number;
  dismissed_candidates?: Array<{ type: string; urls: string[]; reason: string }>;
}

interface MonitorFinding {
  id: string;
  type: string;
  headline: string;
  explanation: string;
  metrics_used: Array<{ snapshot_id: string; field: string; value: number }>;
  recommended_action: string;
  confidence: number;
}

interface ResearchOpportunity {
  id: string;
  type: "gap" | "cannibalization" | "mismatch" | "competitor_topic" | "question";
  headline: string;
  explanation: string;
  metrics_used: Array<{ snapshot_id: string; field: string; value?: any }>;
  confidence: number;
}

interface StrategyTask {
  id: string;
  title: string;
  category: "technical" | "on_page" | "content" | "internal_linking" | "monitoring";
  week: number;
  impact: number;
  effort: number;
  priority_score: number;
  depends_on: string[];
  source_refs: Array<{ kind: string; id: string }>;
  expected_outcome: string;
  done_when: string;
}

interface ContentBrief {
  target_cluster: string;
  intent: string;
  suggested_title: string;
  suggested_meta: string;
  h1: string;
  outline: string[];
  questions_to_answer: string[];
  schema_suggestion: string;
  internal_links: string[];
  competitor_notes?: string;
  notes?: string;
}

interface OnPageRewrite {
  url: string;
  current_title: string;
  suggested_title: string;
  current_meta: string;
  suggested_meta: string;
  status?: string;
}

interface InternalLinkSuggestion {
  source_url: string;
  target_url: string;
  anchor_text: string;
  reason: string;
}

interface InlinkItem {
  source_url: string;
  anchor_text: string;
}

interface JobStats {
  total_pages: number;
  status_200: number;
  status_3xx: number;
  status_4xx: number;
  status_5xx: number;
  missing_title: number;
  missing_meta: number;
  missing_h1: number;
  duplicate_titles: number;
  non_indexable: number;
  avg_response_time_ms: number;
  sitemap_found: boolean;
  in_sitemap_not_crawled: number;
  crawled_not_in_sitemap: number;
  psi_status?: string;
  is_demo?: boolean;
  psi_mobile_score: number | null;
  psi_desktop_score: number | null;
  issues_high: number;
  issues_medium: number;
  issues_low: number;
  crawl_incomplete?: boolean;
  failed_fetches?: Array<{ url: string; reason: string; timestamp: string }>;
  current_step: string;
  status: string;
  cost_usd: number;
  mode: string;
  has_performance: boolean;
  has_research?: boolean;
  has_strategy?: boolean;
  has_code?: boolean;
  strategy_tasks_count?: number;
  briefs_count?: number;
  competitor_pages_count?: number;
  platform?: string;
  detected_platform?: string;
  detected_platform_confidence?: number;
  router_type?: string;
  title_borderline_count?: number;
  title_too_long_count?: number;
  meta_borderline_count?: number;
  meta_too_long_count?: number;
  title_borderline_urls?: string[];
  title_too_long_urls?: string[];
  meta_borderline_urls?: string[];
  meta_too_long_urls?: string[];
}

interface GeneratedArtifact {
  id: string;
  platform: string;
  artifact_type: string;
  file_path: string;
  title: string;
  content: string;
  source_issue_ids: string[];
  source_task_ids: string[];
  validation_status: "passed" | "failed" | "skipped";
  validation_reason?: string;
}

interface FixCoverageItem {
  issue_id: string;
  issue_type: string;
  severity: string;
  fixability: string;
  artifact_names: string[];
}

interface CodeBundleData {
  bundle?: {
    platform: string;
    platform_confidence: number;
    router_type: string;
    artifacts: GeneratedArtifact[];
    summary: string;
    fix_coverage: FixCoverageItem[];
  };
  verifier?: {
    total_artifacts: number;
    passed_count: number;
    failed_count: number;
    skipped_count: number;
    summary: string;
    results: Array<{ file_path: string; artifact_type: string; status: string; reason?: string }>;
  };
}

interface Job {
  id: string;
  target_url: string;
  status: string;
  current_step: string;
  cost_usd: number;
  is_demo?: number;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

const PIPELINE_STEPS = [
  { key: "crawling", label: "Crawl" },
  { key: "pagespeed", label: "PageSpeed" },
  { key: "analysing_technical", label: "Technical" },
  { key: "verifying_technical", label: "Verify Tech" },
  { key: "fetching_google_data", label: "Google Data" },
  { key: "analysing_performance", label: "Performance" },
  { key: "researching", label: "Research" },
  { key: "strategizing", label: "Strategist" },
  { key: "content_generation", label: "Content" },
  { key: "code_generation", label: "Code Gen" },
  { key: "reporting", label: "Report" },
  { key: "completed", label: "Done" },
];

export default function Home() {
  const [targetUrl, setTargetUrl] = useState("https://webspire-agency.vercel.app");
  const [maxPages, setMaxPages] = useState(30);
  const [competitorsInput, setCompetitorsInput] = useState("");
  const [isDemoMode, setIsDemoMode] = useState(false);

  const [currentJob, setCurrentJob] = useState<Job | null>(null);
  const [pages, setPages] = useState<CrawlPage[]>([]);
  const [stats, setStats] = useState<JobStats | null>(null);
  const [verifierData, setVerifierData] = useState<VerifierReport | null>(null);
  const [techSummary, setTechSummary] = useState<string | null>(null);
  const [agentMode, setAgentMode] = useState<string>("fallback");
  const [modelUsed, setModelUsed] = useState<string | null>(null);
  const [failureReason, setFailureReason] = useState<string | null>(null);

  // Performance data
  const [performanceData, setPerformanceData] = useState<any>(null);
  const [monitorFindings, setMonitorFindings] = useState<MonitorFinding[]>([]);
  const [monitorSummary, setMonitorSummary] = useState<string | null>(null);
  const [googleConnected, setGoogleConnected] = useState(false);
  const [googleEmail, setGoogleEmail] = useState<string | null>(null);

  // Research data (M4)
  const [researchSnapshot, setResearchSnapshot] = useState<any>(null);
  const [researchOpportunities, setResearchOpportunities] = useState<ResearchOpportunity[]>([]);
  const [researchSummary, setResearchSummary] = useState<string | null>(null);

  // Strategy data (M4)
  const [strategyTasks, setStrategyTasks] = useState<StrategyTask[]>([]);
  const [strategySummary, setStrategySummary] = useState<string | null>(null);
  const [selectedStrategyCategory, setSelectedStrategyCategory] = useState<string>("all");

  // Content data (M4)
  const [contentBriefs, setContentBriefs] = useState<ContentBrief[]>([]);
  const [contentRewrites, setContentRewrites] = useState<OnPageRewrite[]>([]);
  const [internalLinks, setInternalLinks] = useState<InternalLinkSuggestion[]>([]);
  const [contentSummary, setContentSummary] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  // Code Generator data (M5)
  const [codeBundleData, setCodeBundleData] = useState<CodeBundleData | null>(null);
  const [selectedPlatform, setSelectedPlatform] = useState<string>("nextjs");
  const [selectedRouterType, setSelectedRouterType] = useState<string>("app");
  const [selectedArtifact, setSelectedArtifact] = useState<GeneratedArtifact | null>(null);
  const [isUpdatingPlatform, setIsUpdatingPlatform] = useState(false);

  // Competitor data
  const [competitorPages, setCompetitorPages] = useState<any[]>([]);

  // Agent runs for Debug panel
  const [agentRuns, setAgentRuns] = useState<any[]>([]);

  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<
    "issues_view" | "research" | "strategy" | "content" | "code" | "performance" | "all" | "404" | "missing_meta" | "non_indexable"
  >("issues_view");
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedPage, setSelectedPage] = useState<CrawlPage | null>(null);
  const [pageInlinks, setPageInlinks] = useState<InlinkItem[]>([]);
  const [loadingInlinks, setLoadingInlinks] = useState(false);
  const [evidenceModalData, setEvidenceModalData] = useState<any | null>(null);

  // Check Google connection status
  const checkGoogleStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/google/status`);
      if (res.ok) {
        const data = await res.json();
        setGoogleConnected(data.connected);
        setGoogleEmail(data.email);
      }
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    checkGoogleStatus();
    window.addEventListener("focus", checkGoogleStatus);
    return () => window.removeEventListener("focus", checkGoogleStatus);
  }, []);

  const handleConnectGoogle = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/google/auth-url`);
      const data = await res.json();
      if (data.auth_url) window.open(data.auth_url, "_blank");
    } catch (e) {
      alert("Google OAuth setup requires GOOGLE_CLIENT_ID in backend .env");
    }
  };

  const handleDisconnectGoogle = async () => {
    await fetch(`${API_BASE}/api/google/disconnect`, { method: "POST" });
    setGoogleConnected(false);
    setGoogleEmail(null);
  };

  const handleCopy = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  // Start crawl
  const handleStartCrawl = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!targetUrl.trim()) return;

    setLoading(true);
    setPages([]);
    setStats(null);
    setVerifierData(null);
    setFailureReason(null);
    setModelUsed(null);
    setTechSummary(null);
    setPerformanceData(null);
    setMonitorFindings([]);
    setResearchSnapshot(null);
    setResearchOpportunities([]);
    setStrategyTasks([]);
    setContentBriefs([]);
    setContentRewrites([]);
    setInternalLinks([]);
    setCodeBundleData(null);
    setSelectedArtifact(null);
    setSelectedPage(null);

    const compList = competitorsInput
      .split(/[\n,]+/)
      .map((s) => s.trim())
      .filter((s) => s.length > 0)
      .slice(0, 3);

    try {
      const res = await fetch(`${API_BASE}/api/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: targetUrl.trim(),
          max_pages: Number(maxPages),
          competitor_domains: compList,
          is_demo: isDemoMode,
        }),
      });

      if (!res.ok) throw new Error("Failed to start audit job");
      const data = await res.json();
      setCurrentJob(data.job);
    } catch (err: any) {
      alert("Error: " + (err.message || "Could not reach FastAPI server"));
    } finally {
      setLoading(false);
    }
  };

  // Trigger Demo Seed
  const handleSeedDemo = async () => {
    if (!currentJob?.id) return;
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/api/jobs/${currentJob.id}/seed-demo`, { method: "POST" });
      if (res.ok) {
        alert("Seeded Demo Data pipeline triggered. Refreshing data...");
      }
    } catch (e: any) {
      alert("Demo seed error: " + e.message);
    } finally {
      setLoading(false);
    }
  };

  // Poll status & pipeline data
  useEffect(() => {
    if (!currentJob?.id) return;
    if (currentJob.status === "completed" || currentJob.status === "failed") return;

    const interval = setInterval(async () => {
      try {
        const jobRes = await fetch(`${API_BASE}/api/jobs/${currentJob.id}`);
        if (!jobRes.ok) return;
        const updatedJob: Job = await jobRes.json();
        setCurrentJob(updatedJob);

        const [pagesRes, statsRes, issuesRes, perfRes, resRes, stratRes, contRes, compRes, runsRes, codeRes] = await Promise.all([
          fetch(`${API_BASE}/api/jobs/${currentJob.id}/pages`),
          fetch(`${API_BASE}/api/jobs/${currentJob.id}/stats`),
          fetch(`${API_BASE}/api/jobs/${currentJob.id}/issues`),
          fetch(`${API_BASE}/api/jobs/${currentJob.id}/performance`),
          fetch(`${API_BASE}/api/jobs/${currentJob.id}/research`),
          fetch(`${API_BASE}/api/jobs/${currentJob.id}/strategy`),
          fetch(`${API_BASE}/api/jobs/${currentJob.id}/content`),
          fetch(`${API_BASE}/api/jobs/${currentJob.id}/competitors`),
          fetch(`${API_BASE}/api/jobs/${currentJob.id}/agent-runs`),
          fetch(`${API_BASE}/api/jobs/${currentJob.id}/code-artifacts`),
        ]);

        if (pagesRes.ok) setPages(await pagesRes.json());
        if (statsRes.ok) setStats(await statsRes.json());
        if (issuesRes.ok) {
          const payload = await issuesRes.json();
          if (payload.verifier) setVerifierData(payload.verifier);
          if (payload.technical_agent) setTechSummary(payload.technical_agent.summary);
          if (payload.mode) setAgentMode(payload.mode);
          if (payload.model !== undefined) setModelUsed(payload.model);
          if (payload.failure_reason !== undefined) setFailureReason(payload.failure_reason);
        }
        if (perfRes.ok) {
          const payload = await perfRes.json();
          if (payload.snapshot) setPerformanceData(payload.snapshot);
          if (payload.monitor_agent) {
            setMonitorFindings(payload.monitor_agent.findings || []);
            setMonitorSummary(payload.monitor_agent.summary || null);
          }
        }
        if (resRes.ok) {
          const payload = await resRes.json();
          if (payload.snapshot) setResearchSnapshot(payload.snapshot);
          if (payload.research_agent) {
            setResearchOpportunities(payload.research_agent.opportunities || []);
            setResearchSummary(payload.research_agent.summary || null);
          }
        }
        if (stratRes.ok) {
          const payload = await stratRes.json();
          if (payload.plan) {
            setStrategyTasks(payload.plan.tasks || []);
            setStrategySummary(payload.plan.summary || null);
          }
        }
        if (contRes.ok) {
          const payload = await contRes.json();
          if (payload.content) {
            setContentBriefs(payload.content.briefs || []);
            setContentRewrites(payload.content.rewrites || []);
            setInternalLinks(payload.content.internal_links || []);
            setContentSummary(payload.content.summary || null);
          }
        }
        if (compRes.ok) {
          const payload = await compRes.json();
          setCompetitorPages(payload.competitor_pages || []);
        }
        if (runsRes.ok) {
          const payload = await runsRes.json();
          setAgentRuns(payload.runs || []);
        }
        if (codeRes.ok) {
          const cData = await codeRes.json();
          if (cData && cData.bundle) {
            setCodeBundleData(cData);
            if (cData.bundle.platform) setSelectedPlatform(cData.bundle.platform);
            if (cData.bundle.router_type) setSelectedRouterType(cData.bundle.router_type);
            setSelectedArtifact((prev) => prev || cData.bundle.artifacts?.[0] || null);
          }
        }
      } catch (err) {
        console.error("Polling error:", err);
      }
    }, 1500);

    return () => clearInterval(interval);
  }, [currentJob]);

  // Final fetch on completion
  useEffect(() => {
    if (currentJob?.status === "completed" && currentJob.id) {
      Promise.all([
        fetch(`${API_BASE}/api/jobs/${currentJob.id}/pages`).then((r) => r.json()),
        fetch(`${API_BASE}/api/jobs/${currentJob.id}/stats`).then((r) => r.json()),
        fetch(`${API_BASE}/api/jobs/${currentJob.id}/issues`).then((r) => r.json()),
        fetch(`${API_BASE}/api/jobs/${currentJob.id}/performance`).then((r) => r.json()),
        fetch(`${API_BASE}/api/jobs/${currentJob.id}/research`).then((r) => r.json()),
        fetch(`${API_BASE}/api/jobs/${currentJob.id}/strategy`).then((r) => r.json()),
        fetch(`${API_BASE}/api/jobs/${currentJob.id}/content`).then((r) => r.json()),
        fetch(`${API_BASE}/api/jobs/${currentJob.id}/competitors`).then((r) => r.json()),
        fetch(`${API_BASE}/api/jobs/${currentJob.id}/agent-runs`).then((r) => r.json()),
        fetch(`${API_BASE}/api/jobs/${currentJob.id}/code-artifacts`).then((r) => r.json()),
      ]).then(([p, s, i, perf, res, strat, cont, comp, runs, cData]) => {
        setPages(p);
        setStats(s);
        if (i.verifier) setVerifierData(i.verifier);
        if (i.technical_agent) setTechSummary(i.technical_agent.summary);
        if (i.mode) setAgentMode(i.mode);
        if (i.model !== undefined) setModelUsed(i.model);
        if (i.failure_reason !== undefined) setFailureReason(i.failure_reason);
        if (perf.snapshot) setPerformanceData(perf.snapshot);
        if (perf.monitor_agent) {
          setMonitorFindings(perf.monitor_agent.findings || []);
          setMonitorSummary(perf.monitor_agent.summary || null);
        }
        if (res.snapshot) setResearchSnapshot(res.snapshot);
        if (res.research_agent) {
          setResearchOpportunities(res.research_agent.opportunities || []);
          setResearchSummary(res.research_agent.summary || null);
        }
        if (strat.plan) {
          setStrategyTasks(strat.plan.tasks || []);
          setStrategySummary(strat.plan.summary || null);
        }
        if (cont.content) {
          setContentBriefs(cont.content.briefs || []);
          setContentRewrites(cont.content.rewrites || []);
          setInternalLinks(cont.content.internal_links || []);
          setContentSummary(cont.content.summary || null);
        }
        if (comp.competitor_pages) setCompetitorPages(comp.competitor_pages);
        if (runs.runs) setAgentRuns(runs.runs);
        if (cData && cData.bundle) {
          setCodeBundleData(cData);
          if (cData.bundle.platform) setSelectedPlatform(cData.bundle.platform);
          if (cData.bundle.router_type) setSelectedRouterType(cData.bundle.router_type);
          setSelectedArtifact((prev) => prev || cData.bundle.artifacts?.[0] || null);
        }
      });
    }
  }, [currentJob?.status, currentJob?.id]);

  const handleUpdatePlatform = async (newPlatform: string, newRouter: string) => {
    if (!currentJob?.id) return;
    setIsUpdatingPlatform(true);
    try {
      const res = await fetch(`${API_BASE}/api/jobs/${currentJob.id}/platform`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platform: newPlatform, router_type: newRouter }),
      });
      if (res.ok) {
        const data = await res.json();
        setCodeBundleData({ bundle: data.bundle, verifier: data.verifier });
        setSelectedPlatform(data.platform);
        setSelectedRouterType(data.router_type);
        if (data.bundle?.artifacts?.length) {
          setSelectedArtifact(data.bundle.artifacts[0]);
        }
      }
    } catch (e: any) {
      alert("Failed to update platform: " + e.message);
    } finally {
      setIsUpdatingPlatform(false);
    }
  };

  // Fetch inlinks for Page Inspector
  useEffect(() => {
    if (!selectedPage || !currentJob?.id) return;
    setLoadingInlinks(true);
    fetch(`${API_BASE}/api/jobs/${currentJob.id}/pages/${selectedPage.id}/inlinks`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data && data.found_on) setPageInlinks(data.found_on);
        else setPageInlinks([]);
      })
      .catch(() => setPageInlinks([]))
      .finally(() => setLoadingInlinks(false));
  }, [selectedPage, currentJob?.id]);

  // Filtered pages for table
  const filteredPages = useMemo(() => {
    return pages.filter((p) => {
      const matchSearch =
        p.url.toLowerCase().includes(searchTerm.toLowerCase()) ||
        (p.title && p.title.toLowerCase().includes(searchTerm.toLowerCase()));
      if (!matchSearch) return false;

      if (activeTab === "all") return true;
      if (activeTab === "404") return p.status_code >= 400;
      if (activeTab === "missing_meta") {
        return p.status_code === 200 && (!p.meta_desc || p.meta_desc.trim() === "");
      }
      if (activeTab === "non_indexable") {
        return !p.indexable;
      }
      return true;
    });
  }, [pages, activeTab, searchTerm]);

  // Filtered strategy tasks
  const filteredStrategyTasks = useMemo(() => {
    if (selectedStrategyCategory === "all") return strategyTasks;
    return strategyTasks.filter((t) => t.category === selectedStrategyCategory);
  }, [strategyTasks, selectedStrategyCategory]);

  const getStepStatus = (stepKey: string) => {
    if (!currentJob) return "inactive";
    const order = [
      "crawling",
      "pagespeed",
      "analysing_technical",
      "verifying_technical",
      "fetching_google_data",
      "analysing_performance",
      "researching",
      "strategizing",
      "content_generation",
      "completed",
    ];
    const currentIndex = order.indexOf(currentJob.current_step);
    const stepIndex = order.indexOf(stepKey);
    if (currentIndex > stepIndex) return "done";
    if (currentIndex === stepIndex) return "active";
    return "inactive";
  };

  return (
    <div className="min-h-screen flex flex-col bg-[#070b14] text-slate-200">
      {/* DEMO DATA Watermark Banner */}
      {stats?.is_demo && (
        <div className="bg-gradient-to-r from-rose-900 via-red-800 to-rose-900 text-white text-xs font-bold py-1.5 px-4 text-center tracking-widest uppercase border-b border-rose-700/80 shadow-md">
          ⚠️ DEMO DATA WATERMARK — THIS AUDIT WAS GENERATED USING SEEDED DEMONSTRATION DATA
        </div>
      )}

      {/* Header */}
      <header className="border-b border-slate-800/80 bg-[#0c1220]/80 backdrop-blur-md sticky top-0 z-40 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-600 to-cyan-400 flex items-center justify-center shadow-lg shadow-indigo-500/20">
              <Layers className="w-5 h-5 text-white" />
            </div>
            <div>
              <span className="font-bold text-lg tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">
                SEO Agent Team
              </span>
              <span className="ml-2.5 text-xs font-semibold px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                Milestone 4 — Research + Strategy + Content
              </span>
            </div>
          </div>

          {/* Right Header: Google Connection, PSI & Mode */}
          <div className="flex items-center space-x-3 text-xs">
            {stats?.psi_status && (
              <span
                className={`px-2 py-1 rounded-md border font-mono text-[11px] ${
                  stats.psi_status === "ran"
                    ? "bg-emerald-950/60 border-emerald-800/80 text-emerald-300"
                    : stats.psi_status === "partial"
                    ? "bg-amber-950/60 border-amber-800/80 text-amber-300"
                    : "bg-rose-950/60 border-rose-800/80 text-rose-300"
                }`}
              >
                PSI: {stats.psi_status}
              </span>
            )}

            {googleConnected ? (
              <div className="flex items-center space-x-2 bg-emerald-950/60 border border-emerald-800/80 px-2.5 py-1.5 rounded-lg text-emerald-300">
                <CheckCircle2 className="w-3.5 h-3.5" />
                <span>GSC/GA4: {googleEmail}</span>
                <button onClick={handleDisconnectGoogle} title="Disconnect" className="hover:text-rose-400 ml-1">
                  <LogOut className="w-3 h-3" />
                </button>
              </div>
            ) : (
              <button
                onClick={handleConnectGoogle}
                className="flex items-center space-x-1.5 bg-slate-900 hover:bg-slate-800 border border-slate-700 px-3 py-1.5 rounded-lg text-slate-300 transition"
              >
                <Link2 className="w-3.5 h-3.5 text-indigo-400" />
                <span>Connect Google</span>
              </button>
            )}

            <span className="text-slate-500">|</span>
            <span className="flex items-center text-slate-400 font-mono">
              Cost: <strong className="ml-1 text-emerald-400">${stats?.cost_usd ? stats.cost_usd.toFixed(4) : "0.0000"}</strong>
            </span>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto w-full px-6 py-8 flex-1 space-y-8">
        {/* Launcher Card */}
        <section className="bg-gradient-to-b from-[#111827] to-[#0d1424] border border-slate-800 rounded-2xl p-6 shadow-xl relative overflow-hidden">
          <div className="relative z-10 space-y-4">
            <div>
              <h1 className="text-xl font-semibold text-white tracking-tight flex items-center gap-2">
                <Globe className="w-5 h-5 text-indigo-400" />
                Autonomous Multi-Agent SEO Engine
              </h1>
              <p className="text-xs text-slate-400 mt-1">
                Deterministic Code Crawls &rarr; Technical & Monitor Agents &rarr; Research, Strategist & Content Agents &rarr; Empirical Verifier Validates &rarr; Multi-Format Exports.
              </p>
            </div>

            <form onSubmit={handleStartCrawl} className="grid grid-cols-1 md:grid-cols-12 gap-3 pt-2">
              <div className="md:col-span-5 relative">
                <Globe className="w-4 h-4 text-slate-500 absolute left-3.5 top-3" />
                <input
                  type="text"
                  required
                  placeholder="https://example.com"
                  value={targetUrl}
                  onChange={(e) => setTargetUrl(e.target.value)}
                  className="w-full pl-10 pr-4 py-2 bg-slate-900/90 border border-slate-700/80 rounded-xl text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition"
                />
              </div>

              <div className="md:col-span-4 relative">
                <Users className="w-4 h-4 text-slate-500 absolute left-3.5 top-3" />
                <input
                  type="text"
                  placeholder="Competitors (up to 3, e.g. comp1.com, comp2.com)"
                  value={competitorsInput}
                  onChange={(e) => setCompetitorsInput(e.target.value)}
                  className="w-full pl-10 pr-4 py-2 bg-slate-900/90 border border-slate-700/80 rounded-xl text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition"
                />
              </div>

              <div className="md:col-span-1">
                <select
                  value={maxPages}
                  onChange={(e) => setMaxPages(Number(e.target.value))}
                  className="w-full px-2 py-2 bg-slate-900/90 border border-slate-700/80 rounded-xl text-xs text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 transition"
                >
                  <option value={10}>10 pgs</option>
                  <option value={30}>30 pgs</option>
                  <option value={50}>50 pgs</option>
                  <option value={100}>100 pgs</option>
                </select>
              </div>

              <div className="md:col-span-2 flex items-center space-x-2">
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-medium text-xs rounded-xl shadow-lg shadow-indigo-600/30 flex items-center justify-center space-x-2 transition"
                >
                  {loading ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      <span>Auditing...</span>
                    </>
                  ) : (
                    <>
                      <Zap className="w-3.5 h-3.5" />
                      <span>Run Audit</span>
                    </>
                  )}
                </button>
              </div>

              <div className="col-span-12 flex items-center justify-between text-xs text-slate-400 pt-1">
                <label className="flex items-center space-x-2 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={isDemoMode}
                    onChange={(e) => setIsDemoMode(e.target.checked)}
                    className="rounded border-slate-700 bg-slate-900 text-indigo-600 focus:ring-indigo-500"
                  />
                  <span>Run in <strong>Demo Mode</strong> (auto-seeds GSC/GA4 test data with prominent DEMO DATA watermark)</span>
                </label>

                {currentJob && (
                  <button
                    type="button"
                    onClick={handleSeedDemo}
                    className="text-amber-400 hover:text-amber-300 underline font-mono text-[11px]"
                  >
                    Seed Demo Data on current job
                  </button>
                )}
              </div>
            </form>
          </div>
        </section>

        {/* Progress Pipeline */}
        {currentJob && (
          <section className="bg-slate-900/40 border border-slate-800/80 rounded-2xl p-5 shadow-lg">
            <div className="flex items-center justify-between mb-4">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 flex items-center space-x-2">
                <GitCommit className="w-4 h-4 text-indigo-400" />
                <span>Pipeline Stage: <strong className="text-white">{currentJob.current_step}</strong></span>
              </span>
              <span className="text-xs text-slate-400 font-mono">Job ID: {currentJob.id.slice(0, 8)}...</span>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-5 md:grid-cols-10 gap-1.5">
              {PIPELINE_STEPS.map((step) => {
                const status = getStepStatus(step.key);
                return (
                  <div
                    key={step.key}
                    className={`flex flex-col items-center justify-center p-2 rounded-xl border text-center transition ${
                      status === "done"
                        ? "bg-emerald-950/20 border-emerald-800/50 text-emerald-400"
                        : status === "active"
                        ? "bg-indigo-950/40 border-indigo-500/80 text-indigo-300 ring-2 ring-indigo-500/20 animate-pulse"
                        : "bg-slate-900/40 border-slate-800 text-slate-500"
                    }`}
                  >
                    <span className="text-[10px] font-semibold tracking-tight">{step.label}</span>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* Crawl Incomplete / Failed Fetches Banner */}
        {stats && (stats.crawl_incomplete || (stats.failed_fetches && stats.failed_fetches.length > 0)) && (
          <section className="bg-amber-950/40 border border-amber-600/50 rounded-xl p-4 text-xs text-amber-200">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2 font-semibold text-amber-300 text-sm">
                <span>⚠️ Crawl Incomplete</span>
                <span className="text-[11px] bg-amber-900/60 text-amber-300 px-2 py-0.5 rounded border border-amber-700/50">
                  {stats.failed_fetches?.length || 0} URL(s) failed after retry
                </span>
              </div>
            </div>
            <p className="text-amber-200/80 mb-2">
              The following URL(s) failed on initial fetch and also failed upon automatic retry:
            </p>
            <div className="space-y-1.5 max-h-40 overflow-y-auto font-mono text-[11px] bg-slate-950/60 p-2.5 rounded-lg border border-amber-900/40">
              {stats.failed_fetches && stats.failed_fetches.length > 0 ? (
                stats.failed_fetches.map((f, idx) => (
                  <div key={idx} className="flex items-center justify-between gap-2 text-slate-300">
                    <span className="truncate">{f.url}</span>
                    <span className="text-rose-400 bg-rose-950/50 px-1.5 py-0.5 rounded text-[10px] whitespace-nowrap">
                      {f.reason}
                    </span>
                  </div>
                ))
              ) : (
                <div className="text-slate-400">Fetch failure logged in crawl engine.</div>
              )}
            </div>
          </section>
        )}

        {/* Stats Cards */}
        {stats && (
          <section className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3">
            <div className="bg-slate-900/40 border border-slate-800/80 rounded-xl p-4">
              <span className="text-xs text-slate-400">Pages Crawled</span>
              <div className="text-xl font-bold text-white mt-1">{stats.total_pages}</div>
              <span className="text-[11px] text-emerald-400 font-medium">200 OK: {stats.status_200}</span>
              {stats.crawl_incomplete && (
                <span className="block text-[10px] text-amber-400 font-medium mt-0.5">⚠️ Incomplete ({stats.failed_fetches?.length || 1} failed)</span>
              )}
            </div>

            <div className="bg-slate-900/40 border border-slate-800/80 rounded-xl p-4">
              <span className="text-xs text-slate-400">Verified Issues</span>
              <div className="text-xl font-bold text-rose-400 mt-1">{stats.issues_high + stats.issues_medium + stats.issues_low}</div>
              <span className="text-[11px] text-rose-400 font-medium">High: {stats.issues_high} | Med: {stats.issues_medium}</span>
            </div>

            <div className="bg-slate-900/40 border border-slate-800/80 rounded-xl p-4">
              <span className="text-xs text-slate-400">30-Day Tasks</span>
              <div className="text-xl font-bold text-indigo-400 mt-1">{stats.strategy_tasks_count || strategyTasks.length}</div>
              <span className="text-[11px] text-indigo-300 font-medium">Prioritized by code</span>
            </div>

            <div className="bg-slate-900/40 border border-slate-800/80 rounded-xl p-4">
              <span className="text-xs text-slate-400">Content Briefs</span>
              <div className="text-xl font-bold text-cyan-400 mt-1">{stats.briefs_count || contentBriefs.length}</div>
              <span className="text-[11px] text-cyan-300 font-medium">
                {(stats.briefs_count || contentBriefs.length) > 0 ? `Rewrites: ${contentRewrites.length}` : "n/a - requires Search Console data"}
              </span>
            </div>

            <div className="bg-slate-900/40 border border-slate-800/80 rounded-xl p-4">
              <span className="text-xs text-slate-400">lab data (Lighthouse)</span>
              <div className="text-xl font-bold text-amber-400 mt-1">
                {stats.psi_mobile_score !== null ? stats.psi_mobile_score : "—"}
              </div>
              <span className="text-[11px] text-slate-400 font-mono">
                Desktop: {stats.psi_desktop_score !== null ? stats.psi_desktop_score : "—"}
              </span>
            </div>

            <div className="bg-slate-900/40 border border-slate-800/80 rounded-xl p-4">
              <span className="text-xs text-slate-400">Competitor Pages</span>
              <div className="text-xl font-bold text-purple-400 mt-1">{stats.competitor_pages_count || competitorPages.length}</div>
              <span className="text-[11px] text-purple-300 font-medium">On-page only</span>
            </div>

            {/* Length Tiers Breakdown (M4 carry-over & M5) */}
            <div className="bg-slate-900/40 border border-slate-800/80 rounded-xl p-4 col-span-2 sm:col-span-3 md:col-span-6 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center space-x-2">
                <Tag className="w-4 h-4 text-amber-400" />
                <span className="text-xs font-semibold text-slate-300">Length Tiers Audit:</span>
              </div>
              <div className="flex flex-wrap items-center gap-3 text-xs">
                <span className="bg-slate-950/80 px-2.5 py-1 rounded border border-slate-800">
                  Title Borderline (61-65c): <strong className="text-amber-400">{stats.title_borderline_count ?? 0}</strong>
                </span>
                <span className="bg-slate-950/80 px-2.5 py-1 rounded border border-slate-800">
                  Title Too Long (&gt;65c): <strong className="text-rose-400">{stats.title_too_long_count ?? 0}</strong>
                </span>
                <span className="bg-slate-950/80 px-2.5 py-1 rounded border border-slate-800">
                  Meta Borderline (161-170c): <strong className="text-amber-400">{stats.meta_borderline_count ?? 0}</strong>
                </span>
                <span className="bg-slate-950/80 px-2.5 py-1 rounded border border-slate-800">
                  Meta Too Long (&gt;170c): <strong className="text-rose-400">{stats.meta_too_long_count ?? 0}</strong>
                </span>
                <span className="bg-slate-950/80 px-2.5 py-1 rounded border border-indigo-900/60 text-indigo-300">
                  Platform: <strong>{stats.platform?.toUpperCase() || stats.detected_platform?.toUpperCase() || "NEXTJS"}</strong>
                </span>
              </div>
            </div>
          </section>
        )}

        {/* Export Buttons */}
        {currentJob?.id && (
          <section className="flex flex-wrap items-center justify-between gap-3 bg-slate-900/40 border border-slate-800 rounded-xl p-3.5 text-xs">
            <span className="text-slate-400 font-medium flex items-center gap-1.5">
              <Download className="w-4 h-4 text-indigo-400" />
              Download Audit Reports & Code Fixes:
            </span>
            <div className="flex items-center space-x-2">
              <a
                href={`${API_BASE}/api/jobs/${currentJob.id}/code-zip`}
                target="_blank"
                rel="noreferrer"
                className="px-3 py-1.5 bg-indigo-600/30 hover:bg-indigo-600/40 border border-indigo-500/40 text-indigo-200 font-medium rounded-lg flex items-center space-x-1.5 transition"
              >
                <Download className="w-3.5 h-3.5 text-indigo-300" />
                <span>Download ZIP (Code Fixes)</span>
              </a>
              <a
                href={`${API_BASE}/api/jobs/${currentJob.id}/export/pdf`}
                target="_blank"
                rel="noreferrer"
                className="px-3 py-1.5 bg-rose-600/20 hover:bg-rose-600/30 border border-rose-500/30 text-rose-300 font-medium rounded-lg flex items-center space-x-1.5 transition"
              >
                <span>Download PDF</span>
              </a>
              <a
                href={`${API_BASE}/api/jobs/${currentJob.id}/export/xlsx`}
                target="_blank"
                rel="noreferrer"
                className="px-3 py-1.5 bg-emerald-600/20 hover:bg-emerald-600/30 border border-emerald-500/30 text-emerald-300 font-medium rounded-lg flex items-center space-x-1.5 transition"
              >
                <span>Export XLSX</span>
              </a>
              <a
                href={`${API_BASE}/api/jobs/${currentJob.id}/export/csv`}
                target="_blank"
                rel="noreferrer"
                className="px-3 py-1.5 bg-indigo-600/20 hover:bg-indigo-600/30 border border-indigo-500/30 text-indigo-300 font-medium rounded-lg flex items-center space-x-1.5 transition"
              >
                <span>Export CSV</span>
              </a>
            </div>
          </section>
        )}

        {/* Verifier Audit & Debug Panel */}
        {verifierData && (
          <section className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 flex flex-col gap-2.5 text-xs">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-3">
                <ShieldCheck className="w-5 h-5 text-emerald-400" />
                <div>
                  <span className="font-semibold text-white">Empirical Verifier Audit Summary:</span>
                  <span className="ml-2 text-slate-300">
                    <strong className="text-emerald-400">{verifierData.verified_count}</strong> Verified claims,{" "}
                    <strong className="text-rose-400">{verifierData.rejected_count}</strong> Rejected false claims.
                  </span>
                </div>
              </div>
              <div className="font-mono text-[11px] text-slate-400">
                Mode: <strong className={agentMode === "llm" ? "text-indigo-400" : "text-amber-400"}>{agentMode}</strong>
                {modelUsed ? ` • ${modelUsed}` : ""}
              </div>
            </div>

            {/* Candidate Coverage & Dismissed Candidates */}
            {verifierData.dismissed_candidates && verifierData.dismissed_candidates.length > 0 && (
              <div className="bg-slate-950/60 border border-slate-800/80 rounded-lg p-2.5 text-[11px] text-slate-300">
                <span className="font-semibold text-indigo-300">Candidate Coverage (Explicitly Dismissed Items):</span>
                <ul className="list-disc pl-4 mt-1 space-y-0.5 text-slate-400">
                  {verifierData.dismissed_candidates.map((d, i) => (
                    <li key={i}>
                      <strong className="text-slate-300 font-mono">{d.type}</strong>: {d.reason} ({d.urls?.length || 0} URLs)
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {verifierData.rejected_issues && verifierData.rejected_issues.length > 0 && (
              <div className="bg-rose-950/30 border border-rose-900/50 rounded-lg p-2.5 text-[11px] text-rose-300">
                <span className="font-semibold text-rose-400">Rejected False Claims (Caught & Discarded):</span>
                <ul className="list-disc pl-4 mt-1 space-y-0.5">
                  {verifierData.rejected_issues.map((r, i) => (
                    <li key={i}>
                      <span className="font-mono">{r.type}</span>: {r.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {agentMode === "fallback" && failureReason && (
              <div className="text-[11px] text-amber-300/90 flex items-start space-x-2 bg-amber-950/20 p-2.5 rounded-lg border border-amber-900/40">
                <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                <div>
                  <span className="font-semibold text-amber-300">Technical Agent Fallback Reason (Debug):</span>
                  <p className="font-mono text-[10.5px] mt-0.5 text-amber-200/90 break-all">{failureReason}</p>
                </div>
              </div>
            )}
          </section>
        )}

        {/* Main Tabs Navigation */}
        <section className="bg-[#0c1220] border border-slate-800/80 rounded-2xl shadow-xl overflow-hidden flex flex-col">
          <div className="p-3 border-b border-slate-800/80 flex flex-wrap items-center justify-between gap-2 bg-slate-900/40">
            <div className="flex items-center space-x-1 text-xs overflow-x-auto pb-1 sm:pb-0">
              <button
                onClick={() => setActiveTab("issues_view")}
                className={`px-3 py-1.5 rounded-lg transition font-medium flex items-center space-x-1.5 ${
                  activeTab === "issues_view" ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-white hover:bg-slate-800"
                }`}
              >
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                <span>Technical ({verifierData ? verifierData.verified_count : 0})</span>
              </button>

              <button
                onClick={() => setActiveTab("research")}
                className={`px-3 py-1.5 rounded-lg transition font-medium flex items-center space-x-1.5 ${
                  activeTab === "research" ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-white hover:bg-slate-800"
                }`}
              >
                <Compass className="w-3.5 h-3.5 text-cyan-400" />
                <span>Research & Gaps</span>
              </button>

              <button
                onClick={() => setActiveTab("strategy")}
                className={`px-3 py-1.5 rounded-lg transition font-medium flex items-center space-x-1.5 ${
                  activeTab === "strategy" ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-white hover:bg-slate-800"
                }`}
              >
                <Calendar className="w-3.5 h-3.5 text-amber-400" />
                <span>30-Day Strategy ({strategyTasks.length})</span>
              </button>

              <button
                onClick={() => setActiveTab("content")}
                className={`px-3 py-1.5 rounded-lg transition font-medium flex items-center space-x-1.5 ${
                  activeTab === "content" ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-white hover:bg-slate-800"
                }`}
              >
                <FileEdit className="w-3.5 h-3.5 text-purple-400" />
                <span>Content & Rewrites ({contentBriefs.length})</span>
              </button>

              <button
                onClick={() => setActiveTab("code")}
                className={`px-3 py-1.5 rounded-lg transition font-medium flex items-center space-x-1.5 ${
                  activeTab === "code" ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-white hover:bg-slate-800"
                }`}
              >
                <Layers className="w-3.5 h-3.5 text-indigo-400" />
                <span>Code Generator ({codeBundleData?.bundle?.artifacts?.length || 0})</span>
              </button>

              <button
                onClick={() => setActiveTab("performance")}
                className={`px-3 py-1.5 rounded-lg transition font-medium flex items-center space-x-1.5 ${
                  activeTab === "performance" ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-white hover:bg-slate-800"
                }`}
              >
                <BarChart3 className="w-3.5 h-3.5 text-emerald-400" />
                <span>Performance</span>
              </button>

              <button
                onClick={() => setActiveTab("all")}
                className={`px-3 py-1.5 rounded-lg transition font-medium ${
                  activeTab === "all" ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-white hover:bg-slate-800"
                }`}
              >
                Pages ({pages.length})
              </button>

              <button
                onClick={() => setActiveTab("404")}
                className={`px-3 py-1.5 rounded-lg transition font-medium flex items-center space-x-1.5 ${
                  activeTab === "404" ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-white hover:bg-slate-800"
                }`}
              >
                <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />
                <span>Errors ({stats?.status_4xx || 0})</span>
              </button>

              <button
                onClick={() => setActiveTab("missing_meta")}
                className={`px-3 py-1.5 rounded-lg transition font-medium ${
                  activeTab === "missing_meta" ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-white hover:bg-slate-800"
                }`}
              >
                Missing Meta ({stats?.missing_meta || 0})
              </button>

              <button
                onClick={() => setActiveTab("non_indexable")}
                className={`px-3 py-1.5 rounded-lg transition font-medium ${
                  activeTab === "non_indexable" ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-white hover:bg-slate-800"
                }`}
              >
                Non-Indexable ({stats?.non_indexable || 0})
              </button>
            </div>

            <div className="relative text-xs w-48">
              <Search className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 top-2" />
              <input
                type="text"
                placeholder="Filter results..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full pl-8 pr-3 py-1 bg-slate-900 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-500 focus:outline-none"
              />
            </div>
          </div>

          {/* TAB 1: Technical Issues */}
          {activeTab === "issues_view" && (
            <div className="p-5 space-y-4">
              {stats?.psi_status && stats.psi_status.startsWith("failed") && (
                <div className="bg-amber-950/20 border border-amber-800/40 p-3 rounded-xl text-xs text-amber-300 flex items-center space-x-2">
                  <Info className="w-4 h-4 text-amber-400 shrink-0" />
                  <span>
                    <strong>PageSpeed Insights Notice:</strong> PSI did not run or encountered an error ({stats.psi_status}). Speed issues are not shown.
                  </span>
                </div>
              )}

              {techSummary && (
                <div className="bg-slate-900/60 border border-slate-800 p-4 rounded-xl text-xs text-slate-300">
                  <span className="font-semibold text-white">Technical Agent Executive Synthesis:</span>
                  <p className="mt-1 leading-relaxed text-slate-300">{techSummary}</p>
                </div>
              )}

              {verifierData?.verified_issues && verifierData.verified_issues.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
                  {verifierData.verified_issues.map((issue) => (
                    <div key={issue.id} className="bg-slate-900/40 border border-slate-800/80 rounded-xl p-4 flex flex-col justify-between space-y-3">
                      <div>
                        <div className="flex items-center justify-between">
                          <span className="font-mono text-xs font-bold text-slate-400">{issue.id}</span>
                          <span
                            className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ${
                              issue.severity === "high"
                                ? "bg-rose-950/80 text-rose-300 border border-rose-800/50"
                                : issue.severity === "medium"
                                ? "bg-amber-950/80 text-amber-300 border border-amber-800/50"
                                : "bg-blue-950/80 text-blue-300 border border-blue-800/50"
                            }`}
                          >
                            {issue.severity}
                          </span>
                        </div>
                        <h4 className="font-semibold text-sm text-white mt-1 capitalize">{issue.type.replace(/_/g, " ")}</h4>
                        <p className="text-xs text-slate-300 mt-1 leading-relaxed">{issue.impact}</p>
                      </div>

                      <div className="pt-2 border-t border-slate-800/80 space-y-2">
                        <div className="text-[11px] text-emerald-400 bg-emerald-950/20 p-2 rounded-lg border border-emerald-900/30">
                          <strong>Fix Hint:</strong> {issue.fix_hint}
                        </div>

                        <div className="flex items-center justify-between text-[11px] text-slate-400 pt-1">
                          <span>Affected URLs: <strong>{issue.urls.length}</strong></span>
                          <button
                            onClick={() => setEvidenceModalData({ title: issue.type, evidence: issue.evidence, urls: issue.urls })}
                            className="text-indigo-400 hover:text-indigo-300 flex items-center space-x-1"
                          >
                            <span>Inspect Evidence</span>
                            <ExternalLink className="w-3 h-3" />
                          </button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="py-12 text-center text-slate-500 text-xs">No technical issues verified.</div>
              )}
            </div>
          )}

          {/* TAB 2: Research & Gaps (M4) */}
          {activeTab === "research" && (
            <div className="p-5 space-y-6">
              {researchSummary && (
                <div className="bg-slate-900/60 border border-slate-800 p-4 rounded-xl text-xs text-slate-300">
                  <span className="font-semibold text-white flex items-center gap-1.5">
                    <Compass className="w-4 h-4 text-cyan-400" />
                    Research Agent Findings & Gap Summary:
                  </span>
                  <p className="mt-1 leading-relaxed text-slate-300">{researchSummary}</p>
                </div>
              )}

              {/* Research Opportunities */}
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                  <Target className="w-4 h-4 text-cyan-400" />
                  Identified Research Opportunities ({researchOpportunities.length})
                </h3>

                {researchOpportunities.length > 0 ? (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
                    {researchOpportunities.map((opp) => (
                      <div key={opp.id} className="bg-slate-900/40 border border-slate-800/80 rounded-xl p-4 space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="font-mono text-xs text-slate-400">{opp.id}</span>
                          <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded-full bg-cyan-950 text-cyan-300 border border-cyan-800/50">
                            {opp.type}
                          </span>
                        </div>
                        <h4 className="font-semibold text-sm text-white">{opp.headline}</h4>
                        <p className="text-xs text-slate-300 leading-relaxed">{opp.explanation}</p>
                        <div className="pt-2 text-[11px] text-slate-400 font-mono">
                          Trace: {opp.metrics_used.map((m) => `${m.field}=${m.value}`).join(", ")}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="py-6 text-center text-slate-500 text-xs">
                    n/a - requires Search Console data
                  </div>
                )}
              </div>

              {/* Query Clusters & Intent */}
              {researchSnapshot?.query_clusters && (
                <div className="space-y-3 pt-2">
                  <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                    <Split className="w-4 h-4 text-indigo-400" />
                    Empirical Query Clusters & Intent
                  </h3>
                  <div className="overflow-x-auto border border-slate-800 rounded-xl">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-slate-900/80 text-slate-400 border-b border-slate-800">
                        <tr>
                          <th className="p-3">Head Query</th>
                          <th className="p-3">Intent</th>
                          <th className="p-3">Total Impressions</th>
                          <th className="p-3">Total Clicks</th>
                          <th className="p-3">Avg Position</th>
                          <th className="p-3">Search Volume</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/60">
                        {researchSnapshot.query_clusters.map((cl: any, i: number) => (
                          <tr key={i} className="hover:bg-slate-900/40">
                            <td className="p-3 font-medium text-white">{cl.head_term}</td>
                            <td className="p-3">
                              <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase bg-slate-800 text-slate-300">
                                {cl.intent}
                              </span>
                            </td>
                            <td className="p-3 text-slate-300">{cl.total_impressions}</td>
                            <td className="p-3 text-slate-300">{cl.total_clicks}</td>
                            <td className="p-3 text-slate-300">{cl.avg_position}</td>
                            <td className="p-3 text-slate-500 italic">n/a — requires keyword data provider</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Competitor Comparison */}
              {researchSnapshot?.competitor_comparison && (
                <div className="space-y-3 pt-2">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                      <Users className="w-4 h-4 text-purple-400" />
                      Competitor On-Page Analysis
                    </h3>
                    <span className="text-[11px] text-purple-400 italic">on-page comparison only — no traffic or backlink data</span>
                  </div>

                  <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-4 space-y-3 text-xs">
                    <div>
                      <span className="font-semibold text-slate-300">Missing Topics Competitors Cover (from competitor headings):</span>
                      <div className="flex flex-wrap gap-2 mt-2">
                        {researchSnapshot.competitor_comparison.topics_competitors_cover?.map((t: any, i: number) => (
                          <span key={i} className="px-2.5 py-1 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 text-[11px]">
                            <strong className="text-purple-300 font-mono text-[10px]">{t.competitor}:</strong> {t.topic}
                          </span>
                        )) || <span className="text-slate-500">None detected.</span>}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* TAB 3: 30-Day Strategy (M4) */}
          {activeTab === "strategy" && (
            <div className="p-5 space-y-5">
              {strategySummary && (
                <div className="bg-slate-900/60 border border-slate-800 p-4 rounded-xl text-xs text-slate-300">
                  <span className="font-semibold text-white flex items-center gap-1.5">
                    <Calendar className="w-4 h-4 text-amber-400" />
                    Strategist Agent 30-Day Executive Roadmap:
                  </span>
                  <p className="mt-1 leading-relaxed text-slate-300">{strategySummary}</p>
                </div>
              )}

              {/* Category Filter Pills */}
              <div className="flex items-center space-x-2 text-xs">
                {["all", "technical", "on_page", "content", "internal_linking", "monitoring"].map((cat) => (
                  <button
                    key={cat}
                    onClick={() => setSelectedStrategyCategory(cat)}
                    className={`px-3 py-1 rounded-lg font-medium capitalize transition ${
                      selectedStrategyCategory === cat ? "bg-amber-600 text-white" : "bg-slate-800 text-slate-400 hover:text-white"
                    }`}
                  >
                    {cat.replace("_", " ")}
                  </button>
                ))}
              </div>

              {/* Tasks Grouped by Week */}
              {[1, 2, 3, 4].map((weekNum) => {
                const weekTasks = filteredStrategyTasks.filter((t) => t.week === weekNum);
                if (weekTasks.length === 0) return null;

                return (
                  <div key={weekNum} className="space-y-3">
                    <div className="flex items-center space-x-2 border-b border-slate-800 pb-2">
                      <span className="px-2.5 py-1 rounded-lg bg-amber-950/80 border border-amber-800/80 text-amber-300 font-bold text-xs">
                        WEEK {weekNum}
                      </span>
                      <span className="text-xs text-slate-400 font-medium">
                        {weekNum === 1
                          ? "Critical Technical Blockers & Canonical Directives"
                          : weekNum === 2
                          ? "On-Page Metadata Rewrites & Title Fixes"
                          : weekNum === 3
                          ? "Content Expansion & High-Impact Gap Targeting"
                          : "Internal Link Hubs & Search Trend Monitoring"}
                      </span>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
                      {weekTasks.map((task) => (
                        <div key={task.id} className="bg-slate-900/40 border border-slate-800/80 rounded-xl p-4 flex flex-col justify-between space-y-3">
                          <div>
                            <div className="flex items-center justify-between">
                              <span className="font-mono text-xs font-bold text-slate-400">{task.id}</span>
                              <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase bg-slate-800 text-amber-400 border border-amber-500/20">
                                Priority Score: {task.priority_score.toFixed(1)}
                              </span>
                            </div>
                            <h4 className="font-semibold text-sm text-white mt-1">{task.title}</h4>
                            <p className="text-xs text-slate-300 mt-1 leading-relaxed">
                              <strong>Expected Outcome:</strong> {task.expected_outcome}
                            </p>
                          </div>

                          <div className="pt-2 border-t border-slate-800/80 space-y-1 text-xs">
                            <div className="text-[11px] text-emerald-400 bg-emerald-950/20 p-2 rounded-lg border border-emerald-900/30">
                              <strong>Done When:</strong> {task.done_when}
                            </div>
                            <div className="flex items-center justify-between text-[11px] text-slate-400 pt-1">
                              <span>Impact: <strong>{task.impact}/5</strong> • Effort: <strong>{task.effort}/5</strong></span>
                              <span className="font-mono text-[10px]">Sources: {task.source_refs.map((s) => s.id).join(", ")}</span>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* TAB 4: Content & Rewrites (M4) */}
          {activeTab === "content" && (
            <div className="p-5 space-y-6">
              {contentSummary && (
                <div className="bg-slate-900/60 border border-slate-800 p-4 rounded-xl text-xs text-slate-300">
                  <span className="font-semibold text-white flex items-center gap-1.5">
                    <FileEdit className="w-4 h-4 text-purple-400" />
                    Content Agent Production Summary:
                  </span>
                  <p className="mt-1 leading-relaxed text-slate-300">{contentSummary}</p>
                </div>
              )}

              {/* Content Briefs */}
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                  <FileText className="w-4 h-4 text-purple-400" />
                  Target Content Briefs ({contentBriefs.length})
                </h3>

                {contentBriefs.length > 0 ? (
                  <div className="space-y-4">
                    {contentBriefs.map((brief, i) => (
                      <div key={i} className="bg-slate-900/40 border border-slate-800/80 rounded-xl p-4 space-y-3">
                        <div className="flex items-center justify-between">
                          <span className="font-bold text-sm text-purple-300">{brief.target_cluster}</span>
                          <div className="flex items-center space-x-2">
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase bg-slate-800 text-slate-300">
                              Intent: {brief.intent}
                            </span>
                            <button
                              onClick={() => handleCopy(JSON.stringify(brief, null, 2), `brief-${i}`)}
                              className="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs flex items-center space-x-1"
                            >
                              {copiedKey === `brief-${i}` ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                              <span>Copy Brief</span>
                            </button>
                          </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                          <div className="bg-slate-950/60 p-3 rounded-lg border border-slate-800">
                            <span className="text-slate-400 font-semibold">Suggested Title (≤ 60 chars):</span>
                            <p className="text-white font-medium mt-0.5">{brief.suggested_title}</p>
                            <span className="text-[10px] text-slate-500 font-mono">Length: {brief.suggested_title.length} chars</span>
                          </div>

                          <div className="bg-slate-950/60 p-3 rounded-lg border border-slate-800">
                            <span className="text-slate-400 font-semibold">Suggested Meta (≤ 155 chars):</span>
                            <p className="text-white font-medium mt-0.5">{brief.suggested_meta}</p>
                            <span className="text-[10px] text-slate-500 font-mono">Length: {brief.suggested_meta.length} chars</span>
                          </div>
                        </div>

                        <div className="text-xs bg-slate-950/40 p-3 rounded-lg border border-slate-800/80 space-y-1.5">
                          <p><strong>Primary H1:</strong> {brief.h1}</p>
                          <p><strong>Outline:</strong> {brief.outline.join(" ➔ ")}</p>
                          {brief.questions_to_answer.length > 0 && (
                            <div className="pt-1">
                              <span className="font-semibold text-slate-400">Questions to Answer (from GSC questions):</span>
                              <ul className="list-disc pl-4 mt-0.5 text-slate-300">
                                {brief.questions_to_answer.map((q, qi) => (
                                  <li key={qi}>{q}</li>
                                ))}
                              </ul>
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="py-6 text-center text-slate-500 text-xs">
                    n/a - requires Search Console data
                  </div>
                )}
              </div>

              {/* On-Page Title/Meta Rewrites */}
              <div className="space-y-3 pt-3">
                <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                  <FileEdit className="w-4 h-4 text-emerald-400" />
                  On-Page Metadata Rewrites ({contentRewrites.length})
                </h3>

                <div className="overflow-x-auto border border-slate-800 rounded-xl">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-900/80 text-slate-400 border-b border-slate-800">
                      <tr>
                        <th className="p-3">Page URL</th>
                        <th className="p-3">Current Metadata</th>
                        <th className="p-3">Suggested Rewrite (Code Enforced Bounds)</th>
                        <th className="p-3">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60">
                      {contentRewrites.map((rw, i) => (
                        <tr key={i} className="hover:bg-slate-900/40">
                          <td className="p-3 font-mono text-[11px] text-slate-300 max-w-xs truncate">{rw.url}</td>
                          <td className="p-3 space-y-1">
                            <p className="text-slate-400"><strong>Title:</strong> {rw.current_title}</p>
                            <p className="text-slate-500"><strong>Meta:</strong> {rw.current_meta || "—"}</p>
                          </td>
                          <td className="p-3 space-y-1">
                            <div className="flex items-center gap-1.5 pb-0.5">
                              <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20">
                                {rw.status || "needs human review"}
                              </span>
                            </div>
                            <p className="text-white font-medium"><strong>Title ({rw.suggested_title.length}c):</strong> {rw.suggested_title}</p>
                            <p className="text-slate-300"><strong>Meta ({rw.suggested_meta.length}c):</strong> {rw.suggested_meta}</p>
                          </td>
                          <td className="p-3">
                            <button
                              onClick={() => handleCopy(`Title: ${rw.suggested_title}\nMeta: ${rw.suggested_meta}`, `rw-${i}`)}
                              className="px-2 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs flex items-center space-x-1"
                            >
                              {copiedKey === `rw-${i}` ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                              <span>Copy</span>
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Internal Link Suggestions */}
              <div className="space-y-3 pt-3">
                <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                  <Link2 className="w-4 h-4 text-cyan-400" />
                  Deterministic Internal Link Suggestions ({internalLinks.length})
                </h3>

                <div className="overflow-x-auto border border-slate-800 rounded-xl">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-slate-900/80 text-slate-400 border-b border-slate-800">
                      <tr>
                        <th className="p-3">Source URL</th>
                        <th className="p-3">Target URL (Equity Target)</th>
                        <th className="p-3">Anchor Text</th>
                        <th className="p-3">Reason</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60">
                      {internalLinks.map((l, i) => (
                        <tr key={i} className="hover:bg-slate-900/40">
                          <td className="p-3 font-mono text-[11px] text-slate-300 max-w-xs truncate">{l.source_url}</td>
                          <td className="p-3 font-mono text-[11px] text-cyan-300 max-w-xs truncate">{l.target_url}</td>
                          <td className="p-3 font-semibold text-white">{l.anchor_text}</td>
                          <td className="p-3 text-slate-400">{l.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* TAB: Code Generator (M5) */}
          {activeTab === "code" && (
            <div className="p-5 space-y-6">
              {/* Header and Controls */}
              <div className="flex flex-wrap items-center justify-between gap-4 bg-slate-900/60 border border-slate-800 p-4 rounded-xl">
                <div>
                  <h2 className="text-base font-semibold text-white flex items-center gap-2">
                    <Layers className="w-4 h-4 text-indigo-400" />
                    Platform-Specific SEO Code Generator
                  </h2>
                  <p className="text-xs text-slate-400 mt-1">
                    Deterministic code & configs rendered via Jinja2 templates. Validated before packaging.
                  </p>
                </div>

                <div className="flex flex-wrap items-center gap-2.5">
                  <div className="flex items-center space-x-1.5 bg-slate-950 px-2.5 py-1.5 rounded-lg border border-slate-800">
                    <span className="text-[11px] text-slate-400">Platform:</span>
                    <select
                      value={selectedPlatform}
                      onChange={(e) => {
                        const newP = e.target.value;
                        setSelectedPlatform(newP);
                        handleUpdatePlatform(newP, selectedRouterType);
                      }}
                      disabled={isUpdatingPlatform}
                      className="bg-transparent text-xs font-semibold text-white focus:outline-none cursor-pointer"
                    >
                      <option value="nextjs" className="bg-slate-900">Next.js</option>
                      <option value="wordpress" className="bg-slate-900">WordPress</option>
                      <option value="plain_html" className="bg-slate-900">Plain HTML</option>
                      <option value="shopify" className="bg-slate-900">Shopify</option>
                    </select>
                  </div>

                  {selectedPlatform === "nextjs" && (
                    <div className="flex items-center space-x-1.5 bg-slate-950 px-2.5 py-1.5 rounded-lg border border-slate-800">
                      <span className="text-[11px] text-slate-400">Router:</span>
                      <select
                        value={selectedRouterType}
                        onChange={(e) => {
                          const newR = e.target.value;
                          setSelectedRouterType(newR);
                          handleUpdatePlatform(selectedPlatform, newR);
                        }}
                        disabled={isUpdatingPlatform}
                        className="bg-transparent text-xs font-semibold text-white focus:outline-none cursor-pointer"
                      >
                        <option value="app" className="bg-slate-900">App Router (app/)</option>
                        <option value="pages" className="bg-slate-900">Pages Router (pages/)</option>
                      </select>
                    </div>
                  )}

                  {currentJob?.id && (
                    <a
                      href={`${API_BASE}/api/jobs/${currentJob.id}/code-zip`}
                      target="_blank"
                      rel="noreferrer"
                      className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white font-medium rounded-lg text-xs flex items-center space-x-1.5 shadow-lg shadow-indigo-600/30 transition"
                    >
                      <Download className="w-3.5 h-3.5" />
                      <span>Download ZIP</span>
                    </a>
                  )}
                </div>
              </div>

              {/* Watermark / Human Review Alert */}
              <div className="bg-amber-950/20 border border-amber-900/40 rounded-xl p-3.5 text-xs text-amber-200/90 flex items-start gap-2.5">
                <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                <div>
                  <span className="font-semibold text-amber-300">Needs Human Review:</span>
                  <p className="mt-0.5 text-amber-200/80 leading-relaxed">
                    Always review generated code, redirects, and metadata templates on a staging branch before applying to production.
                    {codeBundleData?.verifier?.skipped_count ? (
                      <span className="block mt-1 text-amber-300 font-medium">
                        ⚠️ Note: {codeBundleData.verifier.skipped_count} artifact(s) skipped automated validator execution because runtime tools (e.g. PHP CLI or TypeScript compiler) are not installed on the system.
                      </span>
                    ) : null}
                  </p>
                </div>
              </div>

              {codeBundleData?.bundle ? (
                <>
                  {/* Two Column Layout: File Explorer & Code Preview */}
                  <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
                    {/* Left Column: Artifacts list */}
                    <div className="lg:col-span-5 bg-slate-900/40 border border-slate-800 rounded-xl p-3.5 space-y-2">
                      <div className="flex items-center justify-between pb-2 border-b border-slate-800">
                        <span className="text-xs font-semibold text-white">
                          Generated Artifacts ({codeBundleData.bundle.artifacts.length})
                        </span>
                        <div className="flex items-center gap-1.5 text-[10px]">
                          <span className="px-1.5 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-800">
                            {codeBundleData.verifier?.passed_count || 0} passed
                          </span>
                          {Boolean(codeBundleData.verifier?.skipped_count) && (
                            <span className="px-1.5 py-0.5 rounded bg-amber-950 text-amber-400 border border-amber-800">
                              {codeBundleData.verifier?.skipped_count} skipped
                            </span>
                          )}
                          {Boolean(codeBundleData.verifier?.failed_count) && (
                            <span className="px-1.5 py-0.5 rounded bg-rose-950 text-rose-400 border border-rose-800">
                              {codeBundleData.verifier?.failed_count} failed
                            </span>
                          )}
                        </div>
                      </div>

                      <div className="space-y-1.5 max-h-[500px] overflow-y-auto pr-1">
                        {codeBundleData.bundle.artifacts.map((art) => {
                          const isSelected = selectedArtifact?.id === art.id;
                          return (
                            <button
                              key={art.id}
                              onClick={() => setSelectedArtifact(art)}
                              className={`w-full text-left p-2.5 rounded-lg border transition flex flex-col gap-1 text-xs ${
                                isSelected
                                  ? "bg-indigo-950/40 border-indigo-500/80 text-white shadow-sm"
                                  : "bg-slate-950/40 border-slate-800/80 text-slate-300 hover:bg-slate-900/60"
                              }`}
                            >
                              <div className="flex items-center justify-between gap-2">
                                <span className="font-mono text-[11px] font-semibold truncate text-slate-200">
                                  {art.file_path}
                                </span>
                                <span
                                  className={`px-1.5 py-0.5 rounded text-[10px] uppercase font-bold shrink-0 ${
                                    art.validation_status === "passed"
                                      ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                                      : art.validation_status === "skipped"
                                      ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                                      : "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                                  }`}
                                >
                                  {art.validation_status}
                                </span>
                              </div>
                              <span className="text-[11px] text-slate-400 truncate">{art.title}</span>
                              <div className="flex flex-wrap items-center gap-1 mt-0.5">
                                {art.source_issue_ids.map((id) => (
                                  <span key={id} className="px-1 py-0.2 rounded bg-slate-800 text-slate-300 text-[9px] font-mono">
                                    {id}
                                  </span>
                                ))}
                                {art.source_task_ids.map((id) => (
                                  <span key={id} className="px-1 py-0.2 rounded bg-indigo-950 text-indigo-300 text-[9px] font-mono">
                                    {id}
                                  </span>
                                ))}
                              </div>
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    {/* Right Column: Code Preview */}
                    <div className="lg:col-span-7 bg-slate-900/40 border border-slate-800 rounded-xl p-3.5 flex flex-col space-y-3">
                      {selectedArtifact ? (
                        <>
                          <div className="flex items-center justify-between pb-2 border-b border-slate-800">
                            <div>
                              <span className="font-mono text-xs font-bold text-white">
                                {selectedArtifact.file_path}
                              </span>
                              <span className="ml-2 text-[10px] text-slate-400 font-sans">
                                ({selectedArtifact.artifact_type})
                              </span>
                            </div>
                            <button
                              onClick={() => handleCopy(selectedArtifact.content, `art-${selectedArtifact.id}`)}
                              className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs flex items-center space-x-1.5 transition"
                            >
                              {copiedKey === `art-${selectedArtifact.id}` ? (
                                <>
                                  <Check className="w-3.5 h-3.5 text-emerald-400" />
                                  <span className="text-emerald-400">Copied</span>
                                </>
                              ) : (
                                <>
                                  <Copy className="w-3.5 h-3.5" />
                                  <span>Copy File</span>
                                </>
                              )}
                            </button>
                          </div>

                          {selectedArtifact.validation_reason && (
                            <div className="text-[11px] bg-slate-950/70 p-2 rounded border border-slate-800/80 text-slate-300 flex items-center gap-2">
                              <Info className="w-3.5 h-3.5 text-indigo-400 shrink-0" />
                              <span>{selectedArtifact.validation_reason}</span>
                            </div>
                          )}

                          <div className="relative flex-1">
                            <pre className="bg-[#0b0f19] p-3.5 rounded-lg border border-slate-800 font-mono text-xs text-slate-200 overflow-x-auto max-h-[460px] leading-relaxed select-all">
                              {selectedArtifact.content}
                            </pre>
                          </div>
                        </>
                      ) : (
                        <div className="h-64 flex items-center justify-center text-slate-500 text-xs">
                          Select an artifact from the list to preview code and config.
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Fix Coverage Table */}
                  <div className="space-y-3 pt-2">
                    <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                      <ShieldCheck className="w-4 h-4 text-emerald-400" />
                      Issue Fixability & Automated Coverage
                    </h3>
                    <div className="overflow-x-auto border border-slate-800 rounded-xl">
                      <table className="w-full text-left text-xs">
                        <thead className="bg-slate-900/80 text-slate-400 border-b border-slate-800">
                          <tr>
                            <th className="p-3">Issue ID</th>
                            <th className="p-3">Issue Type</th>
                            <th className="p-3">Severity</th>
                            <th className="p-3">Fixability</th>
                            <th className="p-3">Resolving Artifact(s)</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800/60">
                          {(codeBundleData.bundle.fix_coverage || []).map((fc, i) => (
                            <tr key={i} className="hover:bg-slate-900/40">
                              <td className="p-3 font-mono font-semibold text-slate-300">{fc.issue_id}</td>
                              <td className="p-3 font-mono text-[11px] text-slate-400">{fc.issue_type}</td>
                              <td className="p-3 uppercase text-[10px] font-bold">
                                <span
                                  className={
                                    fc.severity === "high"
                                      ? "text-rose-400"
                                      : fc.severity === "medium"
                                      ? "text-amber-400"
                                      : "text-slate-400"
                                  }
                                >
                                  {fc.severity}
                                </span>
                              </td>
                              <td className="p-3">
                                <span
                                  className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                                    fc.fixability === "auto-fixable by generated code"
                                      ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                                      : fc.fixability === "partially (needs manual step)"
                                      ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                                      : "bg-slate-800 text-slate-400"
                                  }`}
                                >
                                  {fc.fixability}
                                </span>
                              </td>
                              <td className="p-3 font-mono text-[11px] text-indigo-300">
                                {fc.artifact_names.join(", ")}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </>
              ) : (
                <div className="py-12 text-center text-slate-500 text-xs bg-slate-900/20 border border-slate-800/50 rounded-xl">
                  No code artifacts generated yet. Run a crawl or seed demo data to generate ready-to-apply files.
                </div>
              )}
            </div>
          )}

          {/* TAB 5: Performance (GSC & GA4) */}
          {activeTab === "performance" && (
            <div className="p-5 space-y-6">
              {performanceData ? (
                <>
                  {monitorSummary && (
                    <div className="bg-slate-900/60 border border-slate-800 p-4 rounded-xl text-xs text-slate-300">
                      <span className="font-semibold text-white">Monitor Agent Trend Analysis:</span>
                      <p className="mt-1 leading-relaxed text-slate-300">{monitorSummary}</p>
                    </div>
                  )}

                  {/* Summary Totals Comparison */}
                  {performanceData.summary_totals && (
                    <div className="overflow-x-auto border border-slate-800 rounded-xl">
                      <table className="w-full text-left text-xs">
                        <thead className="bg-slate-900/80 text-slate-400 border-b border-slate-800">
                          <tr>
                            <th className="p-3">Metric</th>
                            <th className="p-3">Current 90 Days</th>
                            <th className="p-3">Previous 90 Days</th>
                            <th className="p-3">Period Change</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800/60">
                          <tr>
                            <td className="p-3 font-medium text-white">Organic Clicks</td>
                            <td className="p-3 text-slate-300">{performanceData.summary_totals.clicks}</td>
                            <td className="p-3 text-slate-400">{performanceData.summary_totals.previous_clicks}</td>
                            <td className={`p-3 font-bold ${performanceData.summary_totals.clicks_change_pct >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                              {performanceData.summary_totals.clicks_change_pct}%
                            </td>
                          </tr>
                          <tr>
                            <td className="p-3 font-medium text-white">Organic Impressions</td>
                            <td className="p-3 text-slate-300">{performanceData.summary_totals.impressions}</td>
                            <td className="p-3 text-slate-400">{performanceData.summary_totals.previous_impressions}</td>
                            <td className={`p-3 font-bold ${performanceData.summary_totals.impressions_change_pct >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                              {performanceData.summary_totals.impressions_change_pct}%
                            </td>
                          </tr>
                          <tr>
                            <td className="p-3 font-medium text-white">Average CTR</td>
                            <td className="p-3 text-slate-300">{performanceData.summary_totals.ctr}%</td>
                            <td className="p-3 text-slate-400">{performanceData.summary_totals.previous_ctr}%</td>
                            <td className="p-3 text-slate-300">{performanceData.summary_totals.ctr_change_abs}%</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  )}
                </>
              ) : (
                <div className="py-12 text-center text-slate-500 text-xs">
                  Performance data not connected. Connect Google Search Console or run with Demo Mode.
                </div>
              )}
            </div>
          )}

          {/* TAB 6: All Crawled Pages & Inspector */}
          {["all", "404", "missing_meta", "non_indexable"].includes(activeTab) && (
            <div className="grid grid-cols-1 lg:grid-cols-12 divide-y lg:divide-y-0 lg:divide-x divide-slate-800/80">
              <div className="lg:col-span-8 overflow-x-auto max-h-[600px] overflow-y-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-900/80 text-slate-400 border-b border-slate-800 sticky top-0 z-10">
                    <tr>
                      <th className="p-3">Status</th>
                      <th className="p-3">URL</th>
                      <th className="p-3">Inlinks</th>
                      <th className="p-3">Title</th>
                      <th className="p-3">Indexable</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {filteredPages.map((page) => (
                      <tr
                        key={page.id}
                        onClick={() => setSelectedPage(page)}
                        className={`cursor-pointer transition ${
                          selectedPage?.id === page.id ? "bg-indigo-950/40" : "hover:bg-slate-900/40"
                        }`}
                      >
                        <td className="p-3">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                              page.status_code === 200
                                ? "bg-emerald-950 text-emerald-400"
                                : page.status_code >= 400
                                ? "bg-rose-950 text-rose-400"
                                : "bg-amber-950 text-amber-400"
                            }`}
                          >
                            {page.status_code}
                          </span>
                        </td>
                        <td className="p-3 font-mono text-[11px] text-white max-w-xs truncate">{page.url}</td>
                        <td className="p-3 text-slate-300 font-mono">Found on ({page.inlinks_count || 0})</td>
                        <td className="p-3 text-slate-400 max-w-xs truncate">{page.title || "—"}</td>
                        <td className="p-3">
                          <span className={`text-[10px] font-bold uppercase ${page.indexable ? "text-emerald-400" : "text-amber-400"}`}>
                            {page.indexability_status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Page Inspector Sidebar */}
              <div className="lg:col-span-4 p-4 text-xs space-y-4 max-h-[600px] overflow-y-auto bg-slate-950/20">
                {selectedPage ? (
                  <div className="space-y-3">
                    <h3 className="font-semibold text-white">Page Technical Inspector</h3>
                    <div className="space-y-1.5 font-mono text-[11px] break-all">
                      <p><span className="text-slate-500">URL:</span> {selectedPage.url}</p>
                      <p><span className="text-slate-500">Status:</span> {selectedPage.status_code}</p>
                      <p><span className="text-slate-500">Indexable:</span> {selectedPage.indexability_status}</p>
                      {selectedPage.canonical && <p><span className="text-slate-500">Canonical:</span> {selectedPage.canonical}</p>}
                      <p><span className="text-slate-500">Title:</span> {selectedPage.title || "Missing"}</p>
                      <p><span className="text-slate-500">Meta:</span> {selectedPage.meta_desc || "Missing"}</p>
                      <p><span className="text-slate-500">Word Count:</span> {selectedPage.word_count}</p>
                    </div>

                    <div className="pt-2 border-t border-slate-800">
                      <span className="font-semibold text-white">Found on ({pageInlinks.length} inlinks):</span>
                      <ul className="mt-1 space-y-1 text-slate-400">
                        {loadingInlinks ? (
                          <li>Loading inlinks...</li>
                        ) : pageInlinks.length > 0 ? (
                          pageInlinks.map((link, idx) => (
                            <li key={idx} className="break-all font-mono text-[10px] bg-slate-900 p-1.5 rounded">
                              {link.source_url} {link.anchor_text && `[${link.anchor_text}]`}
                            </li>
                          ))
                        ) : (
                          <li className="italic text-slate-500">No incoming links found (Orphan).</li>
                        )}
                      </ul>
                    </div>
                  </div>
                ) : (
                  <div className="text-center py-12 text-slate-500">Select any row to inspect technical details and inlinks.</div>
                )}
              </div>
            </div>
          )}
        </section>
      </main>

      {/* Evidence Modal */}
      {evidenceModalData && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-[#0e1628] border border-slate-800 rounded-2xl max-w-xl w-full p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold text-white capitalize">{evidenceModalData.title.replace(/_/g, " ")} — Evidence</h3>
              <button onClick={() => setEvidenceModalData(null)} className="text-slate-400 hover:text-white">
                <XCircle className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-2 text-xs">
              <span className="font-semibold text-slate-400">Underlying Database Proof (Audit Trail):</span>
              <pre className="bg-slate-950 p-3 rounded-lg border border-slate-800 overflow-x-auto text-emerald-400 font-mono text-[11px]">
                {JSON.stringify(evidenceModalData.evidence, null, 2)}
              </pre>

              <span className="font-semibold text-slate-400 block pt-2">Affected URLs ({evidenceModalData.urls.length}):</span>
              <ul className="max-h-36 overflow-y-auto space-y-1 font-mono text-[11px] text-slate-300">
                {evidenceModalData.urls.map((u: string, idx: number) => (
                  <li key={idx} className="bg-slate-900/60 p-1 rounded truncate">{u}</li>
                ))}
              </ul>
            </div>

            <div className="pt-2 text-right">
              <button
                onClick={() => setEvidenceModalData(null)}
                className="px-4 py-1.5 bg-slate-800 hover:bg-slate-700 text-white rounded-lg text-xs"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
