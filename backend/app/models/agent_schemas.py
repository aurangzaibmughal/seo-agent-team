from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Literal

class EvidenceItem(BaseModel):
    table: str
    id: Optional[str] = None
    field: str
    value: Optional[Any] = None

class TechnicalIssue(BaseModel):
    id: str
    type: str
    severity: Literal["high", "medium", "low"]
    impact: str
    effort: Literal["low", "medium", "high"]
    urls: List[str] = Field(default_factory=list)
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    fix_hint: str
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    candidate_ids: List[str] = Field(default_factory=list)
    source: str = "llm"  # "llm" or "fallback_rule"

class DismissedCandidate(BaseModel):
    candidate_ids: List[str] = Field(default_factory=list)
    type: Optional[str] = None
    urls: List[str] = Field(default_factory=list)
    reason: str

class TechnicalAgentReport(BaseModel):
    issues: List[TechnicalIssue] = Field(default_factory=list)
    dismissed: List[DismissedCandidate] = Field(default_factory=list)
    summary: str
    tokens_prompt: int = 0
    tokens_completion: int = 0

class VerificationResult(BaseModel):
    issue_id: str
    status: Literal["verified", "rejected"]
    reason: str
    issue: TechnicalIssue

class VerifierReport(BaseModel):
    verified_issues: List[TechnicalIssue]
    rejected_issues: List[Dict[str, Any]]
    dismissed_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    coverage_status: str = "pass"
    total_checked: int
    verified_count: int
    rejected_count: int

# Monitor Agent (M3)
class MetricReference(BaseModel):
    snapshot_id: str
    field: str
    value: float

class MonitorFinding(BaseModel):
    id: str
    type: Literal["traffic_drop", "traffic_gain", "striking_distance", "low_ctr", "declining_page"]
    headline: str
    explanation: str
    metrics_used: List[Dict[str, Any]]
    recommended_action: str
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)

class MonitorReport(BaseModel):
    summary: str
    findings: List[MonitorFinding]
    tokens_prompt: int = 0
    tokens_completion: int = 0

class MonitorVerifierReport(BaseModel):
    verified_findings: List[MonitorFinding]
    rejected_findings: List[Dict[str, Any]]
    total_checked: int
    verified_count: int
    rejected_count: int

# Research Agent (M4)
class ResearchOpportunity(BaseModel):
    id: str
    type: Literal["gap", "cannibalization", "mismatch", "competitor_topic", "question"]
    headline: str
    explanation: str
    metrics_used: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)

class ResearchAgentReport(BaseModel):
    summary: str
    opportunities: List[ResearchOpportunity] = Field(default_factory=list)
    tokens_prompt: int = 0
    tokens_completion: int = 0

class ResearchVerifierReport(BaseModel):
    verified_opportunities: List[ResearchOpportunity]
    rejected_opportunities: List[Dict[str, Any]]
    total_checked: int
    verified_count: int
    rejected_count: int

# Strategist Agent (M4)
class StrategyTaskSourceRef(BaseModel):
    kind: Literal["tech_issue", "perf_finding", "research_opportunity"]
    id: str

class StrategyTask(BaseModel):
    id: str
    title: str
    category: Literal["technical", "on_page", "content", "internal_linking", "monitoring"]
    week: int = Field(ge=1, le=4)
    impact: int = Field(ge=1, le=5)
    effort: int = Field(ge=1, le=5)
    priority_score: float = 0.0
    depends_on: List[str] = Field(default_factory=list)
    source_refs: List[StrategyTaskSourceRef]
    expected_outcome: str
    done_when: str

class StrategyReport(BaseModel):
    summary: str
    tasks: List[StrategyTask] = Field(default_factory=list)
    tokens_prompt: int = 0
    tokens_completion: int = 0

class StrategyVerifierReport(BaseModel):
    verified_tasks: List[StrategyTask]
    rejected_tasks: List[Dict[str, Any]]
    total_checked: int
    verified_count: int
    rejected_count: int

# Content Agent (M4)
class ContentBrief(BaseModel):
    target_cluster: str
    intent: str
    suggested_title: str
    suggested_meta: str
    h1: str
    outline: List[str] = Field(default_factory=list)
    questions_to_answer: List[str] = Field(default_factory=list)
    schema_suggestion: Optional[str] = None
    internal_links: List[str] = Field(default_factory=list)
    competitor_notes: Optional[str] = None
    notes: Optional[str] = None
    target_url: Optional[str] = None
    current_title: Optional[str] = None
    current_meta: Optional[str] = None
    current_h1: Optional[str] = None
    source: str = "llm"

class OnPageRewrite(BaseModel):
    url: str
    current_title: Optional[str] = None
    suggested_title: str
    current_meta: Optional[str] = None
    suggested_meta: str
    current_h1: Optional[str] = None
    suggested_h1: Optional[str] = None
    source: str = "llm"
    status: str = "needs human review"

class InternalLinkSuggestion(BaseModel):
    source_url: str
    target_url: str
    anchor_text: str
    reason: str
    status: str = "needs human review"

class ContentAgentReport(BaseModel):
    summary: str
    briefs: List[ContentBrief] = Field(default_factory=list)
    rewrites: List[OnPageRewrite] = Field(default_factory=list)
    internal_links: List[InternalLinkSuggestion] = Field(default_factory=list)
    tokens_prompt: int = 0
    tokens_completion: int = 0

class ContentVerifierReport(BaseModel):
    verified_briefs: List[ContentBrief] = Field(default_factory=list)
    rejected_briefs: List[Dict[str, Any]] = Field(default_factory=list)
    verified_rewrites: List[OnPageRewrite] = Field(default_factory=list)
    rejected_rewrites: List[Dict[str, Any]] = Field(default_factory=list)
    kept_rewrites: List[OnPageRewrite] = Field(default_factory=list)
    verified_internal_links: List[InternalLinkSuggestion] = Field(default_factory=list)
    rejected_internal_links: List[Dict[str, Any]] = Field(default_factory=list)
    total_checked: int = 0
    verified_count: int = 0
    rejected_count: int = 0

class GeneratedArtifact(BaseModel):
    artifact_type: str
    file_path: str
    platform: str
    title: str
    content: str
    source_issue_ids: List[str] = Field(default_factory=list)
    source_task_ids: List[str] = Field(default_factory=list)
    validation_status: str = "pending"  # "passed" | "failed" | "skipped"
    validation_reason: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    status: str = "needs human review"

class CodeBundleReport(BaseModel):
    platform: str = "plain_html"
    platform_confidence: float = 1.0
    router_type: Optional[str] = "app"
    artifacts: List[GeneratedArtifact] = Field(default_factory=list)
    summary: str = ""
    fix_coverage: List[Dict[str, Any]] = Field(default_factory=list)
    cost_usd: float = 0.0
    mode: str = "deterministic"
    model_used: Optional[str] = None
    failure_reason: Optional[str] = None
    tokens_prompt: int = 0
    tokens_completion: int = 0

class CodeVerifierReport(BaseModel):
    total_artifacts: int = 0
    passed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    results: List[Dict[str, Any]] = Field(default_factory=list)
    summary: str = ""
