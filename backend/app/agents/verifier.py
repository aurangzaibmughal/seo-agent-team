import re
import difflib
from typing import List, Dict, Any, Optional, Tuple, Set
from datetime import datetime, timezone
from collections import defaultdict
from app.core.db import DBManager
from app.models.agent_schemas import (
    TechnicalIssue, VerifierReport,
    MonitorFinding, MonitorVerifierReport,
    ResearchOpportunity, ResearchVerifierReport,
    StrategyTask, StrategyVerifierReport,
    ContentAgentReport, ContentVerifierReport, ContentBrief, OnPageRewrite, InternalLinkSuggestion
)
from app.agents.content_agent import (
    extract_preserved_entities,
    GENERIC_LINK_TERMS,
    STOPWORDS_TRAILING
)
from app.agents.technical_agent import (
    ISSUE_METADATA,
    CANONICAL_TO_OTHER_FIX_HINT,
    get_deterministic_severity
)
from app.core.classification import classify_page_type, is_admin_page

def extract_numbers_from_text(text: str) -> List[float]:
    """Extracts numeric values from a narrative string, ignoring dates, timeframes, and compound rank labels."""
    # 1. Strip ISO and slash dates (e.g. 2026-11-05, 2026/11/05, 05/11/2026, 05-11-2026)
    cleaned = re.sub(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b", " ", text)
    cleaned = re.sub(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b", " ", cleaned)
    # Strip verbal dates like "Nov 5, 2026", "November 5th, 2026"
    cleaned = re.sub(
        r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b",
        " ",
        cleaned,
        flags=re.IGNORECASE
    )

    # 2. Strip compound timeframe words (e.g. 30-day, 7-day, 14-days, 24-hour, 12-month)
    cleaned = re.sub(r"\b\d+-(?:day|days|hour|hours|week|weeks|month|months|year|years)\b", " ", cleaned, flags=re.IGNORECASE)

    # 3. Strip compound rank/page/step words (e.g. top-10, top-3, top-5, page-2, step-1)
    cleaned = re.sub(r"\b(?:top|page|step)-\d+\b", " ", cleaned, flags=re.IGNORECASE)

    # 4. Strip model and version names (e.g. gemini-3.5, gemini-3.1, gpt-4)
    cleaned = re.sub(r"\b(?:gemini|gpt|claude|model|v|version)[- ]?\d+(?:\.\d+)?\b", " ", cleaned, flags=re.IGNORECASE)

    # Extract all remaining numbers (avoiding treating hyphens in compound words as negative signs)
    raw_nums = re.findall(r"(?<![\w\-])[-+]?\b\d+(?:\.\d+)?\b", cleaned)
    res = []
    for n in raw_nums:
        try:
            res.append(float(n))
        except ValueError:
            pass
    return res

def collect_all_snapshot_numbers(snapshot: Dict[str, Any]) -> Set[float]:
    """Flattens all numeric values from snapshot data for traceability verification."""
    nums = set()
    
    def _walk(obj):
        if isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)
        elif isinstance(obj, (int, float)):
            val = float(obj)
            nums.add(round(val, 1))
            nums.add(round(abs(val), 1))
            nums.add(round(val, 2))
            nums.add(round(abs(val), 2))
            nums.add(float(int(val)))
            nums.add(float(abs(int(val))))
            # Ratio to percentage conversion: e.g. 0.012 -> 1.2
            if 0 < abs(val) <= 1.0:
                pct = val * 100.0
                nums.add(round(pct, 1))
                nums.add(round(pct, 2))
                nums.add(round(pct, 3))
            # Percentage to ratio conversion: e.g. 1.2 -> 0.012
            if abs(val) > 0:
                ratio = val / 100.0
                nums.add(round(ratio, 2))
                nums.add(round(ratio, 3))
                nums.add(round(ratio, 4))

    _walk(snapshot)
    return nums

EXPLICIT_SUPERLATIVES = {
    "best", "greatest", "fastest", "quickest", "highest", "lowest",
    "largest", "smallest", "cheapest", "costliest", "finest", "easiest",
    "hardest", "smartest", "strongest", "cleanest", "safest", "brightest",
    "purest", "smoothest", "sharpest", "simplest", "richest", "poorest",
    "leading", "premier", "unmatched", "unrivaled", "world-class",
    "industry-leading", "market-leading", "top-rated", "best-selling",
    "award-winning", "award-winner", "guaranteed", "certified", "#1"
}

LIST_COUNT_NOUNS = {
    "tip", "tips", "way", "ways", "step", "steps", "question", "questions",
    "strategy", "strategies", "idea", "ideas", "practice", "practices",
    "example", "examples", "tool", "tools", "reason", "reasons", "mistake",
    "mistakes", "factor", "factors", "secret", "secrets", "rule", "rules",
    "method", "methods", "lesson", "lessons", "insight", "insights",
    "trend", "trends", "solution", "solutions", "feature", "features",
    "benefit", "benefits", "technique", "techniques", "option", "options",
    "recommendation", "recommendations", "pointer", "pointers", "hack", "hacks"
}

LIST_COUNT_REGEX = re.compile(
    r"\b([1-9]|1\d|20)\s+(?:best\s+|top\s+|essential\s+|key\s+|proven\s+|actionable\s+|effective\s+|simple\s+|easy\s+)?(?:" +
    "|".join(LIST_COUNT_NOUNS) + r")\b",
    re.IGNORECASE
)

COMMON_TITLE_WORDS = {
    "a", "an", "the", "and", "or", "but", "nor", "for", "yet", "so", "as",
    "at", "by", "from", "in", "into", "of", "off", "on", "onto", "out",
    "over", "to", "up", "with", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "can", "could", "shall", "should",
    "will", "would", "may", "might", "must", "how", "what", "why", "when", "where",
    "who", "which", "guide", "tips", "ways", "strategies", "best", "top", "free",
    "ultimate", "complete", "checklist", "review", "pricing", "services", "agency",
    "solutions", "tools", "trends", "ideas", "examples", "case", "study", "studies",
    "insights", "overview", "basics", "advanced", "step", "steps", "simple", "easy",
    "seo", "audit", "marketing", "digital", "business", "online", "growth", "strategy",
    "expert", "experts", "consultant", "consultants", "management", "report", "reports"
}

def normalize_text_for_claims(text: str) -> str:
    if not text:
        return ""
    t = text.replace("’", "'").replace("‘", "'").replace("‚", "'").replace("‛", "'")
    t = t.replace("“", '"').replace("”", '"').replace("„", '"').replace("‟", '"')
    t = t.replace("–", "-").replace("—", "-").replace("‐", "-").replace("‑", "-")
    t = t.replace("\u00a0", " ")
    return t

class Verifier:
    """Deterministic Verifier Agent. Audits both Technical SEO issues and Monitor findings."""

    @classmethod
    def verify_issues(
        cls,
        job_id: str,
        issues: List[TechnicalIssue],
        candidates: Optional[List[Dict[str, Any]]] = None,
        dismissed: Optional[List[Any]] = None
    ) -> VerifierReport:
        verified_issues: List[TechnicalIssue] = []
        rejected_issues: List[Dict[str, Any]] = []

        crawl_pages = DBManager.get_crawl_pages(job_id, limit=2000)
        psi_results = DBManager.get_psi_results(job_id)

        pages_by_id = {p["id"]: p for p in crawl_pages}
        pages_by_url = {p["url"]: p for p in crawl_pages}
        psi_by_id = {p["id"]: p for p in psi_results}
        all_crawled_urls = set(pages_by_url.keys()).union({p["url"] for p in psi_results})

        # 1. Validate each issue
        for issue in issues:
            is_valid, reason = cls._validate_single_issue(
                issue=issue,
                pages_by_id=pages_by_id,
                psi_by_id=psi_by_id,
                all_crawled_urls=all_crawled_urls
            )

            if is_valid:
                total_crawled = max(len(crawl_pages), 1)
                issue.severity = get_deterministic_severity(issue.type, len(issue.urls), total_crawled)
                if issue.type == "canonical_to_other":
                    issue.fix_hint = CANONICAL_TO_OTHER_FIX_HINT
                verified_issues.append(issue)
            else:
                rejected_issues.append({
                    "issue_id": issue.id,
                    "type": issue.type,
                    "reason": reason,
                    "issue_dump": issue.model_dump()
                })

        # 2. Verifier Coverage Check & Fallback Replacement (Step 0 & Requirement 3)
        coverage_status = "pass"
        dismissed_items: List[Dict[str, Any]] = []
        if dismissed:
            for d in dismissed:
                if hasattr(d, "model_dump"):
                    dismissed_items.append(d.model_dump())
                elif isinstance(d, dict):
                    dismissed_items.append(d)

        if candidates:
            # Ensure each candidate has an ID
            for idx, c in enumerate(candidates, start=1):
                if "id" not in c:
                    c["id"] = f"C-{idx:03d}"

            # Identify candidates covered by verified issues
            verified_cids: Set[str] = set()
            for iss in verified_issues:
                for cid in getattr(iss, "candidate_ids", []):
                    verified_cids.add(cid)
                # Match candidates by type, urls, or evidence id
                iss_urls = set(iss.urls)
                iss_ev_ids = {ev.get("id") for ev in iss.evidence if ev.get("id")}
                for c in candidates:
                    if c.get("type") == iss.type:
                        c_urls = set(c.get("urls", []))
                        c_ev_ids = {ev.get("id") for ev in c.get("evidence", []) if ev.get("id")}
                        if (c_urls & iss_urls) or (c_ev_ids & iss_ev_ids) or (not c_urls and not iss_urls):
                            verified_cids.add(c["id"])

            # Identify candidates in dismissed list
            dismissed_cids: Set[str] = set()
            for dis in dismissed_items:
                for cid in dis.get("candidate_ids", []):
                    dismissed_cids.add(cid)
                dis_urls = set(dis.get("urls", []))
                dis_type = dis.get("type")
                if dis.get("reason"):
                    for c in candidates:
                        if not dis_type or c.get("type") == dis_type:
                            c_urls = set(c.get("urls", []))
                            if not c_urls or (c_urls & dis_urls) or not dis_urls:
                                dismissed_cids.add(c["id"])

            # Find candidates that are NOT verified and NOT dismissed
            uncovered_candidates = [
                c for c in candidates
                if c["id"] not in verified_cids and c["id"] not in dismissed_cids
            ]

            # Check for silent drops vs rejected issues
            rejected_cids = set()
            for r in rejected_issues:
                dump = r.get("issue_dump", {})
                for cid in dump.get("candidate_ids", []):
                    rejected_cids.add(cid)

            for c in uncovered_candidates:
                cid = c["id"]
                c_type = c["type"]
                # If this candidate wasn't part of an explicit rejected LLM issue, it's a silent drop
                if cid not in rejected_cids:
                    coverage_status = "failed"
                    rejected_issues.append({
                        "issue_id": f"COV-DROP-{c_type}",
                        "type": "coverage_violation",
                        "reason": f"Candidate of type '{c_type}' for URLs {c.get('urls')} was dropped without being in dismissed list.",
                        "issue_dump": c
                    })

            # Requirement 3: If an issue is rejected, or a candidate is not covered,
            # include the deterministic version of that candidate (marked source=fallback_rule)
            # so real problems never disappear from the report.
            if uncovered_candidates:
                uncovered_grouped: Dict[str, Dict[str, Any]] = {}
                for c in uncovered_candidates:
                    ctype = c["type"]
                    if ctype not in uncovered_grouped:
                        meta = ISSUE_METADATA.get(ctype, {
                            "severity": "medium",
                            "effort": "medium",
                            "impact": f"Detected technical SEO issue of type {ctype}.",
                            "fix_hint": "Review and correct according to SEO best practices."
                        })
                        uncovered_grouped[ctype] = {
                            "type": ctype,
                            "severity": meta["severity"],
                            "effort": meta["effort"],
                            "impact": meta["impact"],
                            "fix_hint": meta["fix_hint"],
                            "urls": set(),
                            "evidence": [],
                            "candidate_ids": set()
                        }
                    uncovered_grouped[ctype]["candidate_ids"].add(c["id"])
                    for u in c.get("urls", []):
                        uncovered_grouped[ctype]["urls"].add(u)
                    for ev in c.get("evidence", []):
                        if ev not in uncovered_grouped[ctype]["evidence"]:
                            uncovered_grouped[ctype]["evidence"].append(ev)

                fb_idx = len(verified_issues) + 1
                total_crawled = max(len(crawl_pages), 1)
                for ctype, g in uncovered_grouped.items():
                    sev = get_deterministic_severity(ctype, len(g["urls"]), total_crawled)
                    hint = CANONICAL_TO_OTHER_FIX_HINT if ctype == "canonical_to_other" else g["fix_hint"]
                    verified_issues.append(TechnicalIssue(
                        id=f"T-{fb_idx:03d}",
                        type=ctype,
                        severity=sev,
                        impact=g["impact"],
                        effort=g["effort"],
                        urls=sorted(list(g["urls"])),
                        evidence=g["evidence"],
                        fix_hint=hint,
                        confidence=1.0,
                        candidate_ids=sorted(list(g["candidate_ids"])),
                        source="fallback_rule"
                    ))
                    fb_idx += 1

        # Renumber all verified issues strictly sequentially T-001, T-002... without any FB in ID
        for idx, iss in enumerate(verified_issues, 1):
            iss.id = f"T-{idx:03d}"

        total_checked = len(issues) + len([r for r in rejected_issues if r.get("issue_id") not in [i.id for i in issues]])

        return VerifierReport(
            verified_issues=verified_issues,
            rejected_issues=rejected_issues,
            dismissed_candidates=dismissed_items,
            coverage_status=coverage_status,
            total_checked=total_checked,
            verified_count=len(verified_issues),
            rejected_count=len(rejected_issues)
        )

    @classmethod
    def _validate_single_issue(
        cls,
        issue: TechnicalIssue,
        pages_by_id: Dict[str, Any],
        psi_by_id: Dict[str, Any],
        all_crawled_urls: set
    ) -> Tuple[bool, str]:
        if not issue.evidence or len(issue.evidence) == 0:
            return False, "Evidence list is empty. Every claim must carry verifiable evidence."

        if issue.severity not in ("high", "medium", "low"):
            return False, f"Invalid severity '{issue.severity}'. Must be high, medium, or low."
        if issue.effort not in ("low", "medium", "high"):
            return False, f"Invalid effort '{issue.effort}'. Must be low, medium, or high."

        for u in issue.urls:
            if u not in all_crawled_urls:
                return False, f"URL '{u}' does not exist in crawl records for this job."

        for ev in issue.evidence:
            table = ev.get("table")
            row_id = ev.get("id")

            if table == "crawl_pages":
                row = pages_by_id.get(row_id)
                if not row:
                    return False, f"Referenced row '{row_id}' in crawl_pages does not exist in database."
                
                status = row.get("status_code", 0)
                title = row.get("title")
                meta_desc = row.get("meta_desc")
                h1 = row.get("h1")
                canonical = row.get("canonical")

                if issue.type == "missing_title":
                    if status != 200 or (title and len(title.strip()) > 0):
                        return False, f"Claim false: Page status is {status} and title is '{title}'."
                elif issue.type == "missing_meta_description":
                    if status != 200 or (meta_desc and len(meta_desc.strip()) > 0):
                        return False, f"Claim false: Page status is {status} and meta_desc is '{meta_desc}'."
                elif issue.type == "missing_h1":
                    if status != 200 or (h1 and len(h1.strip()) > 0):
                        return False, f"Claim false: Page status is {status} and H1 is '{h1}'."
                elif issue.type == "title_borderline":
                    if not title or not (61 <= len(title.strip()) <= 65):
                        return False, f"Claim false: Title length is {len(title or '')} (not 61-65 chars)."
                elif issue.type == "title_too_long":
                    if not title or len(title.strip()) <= 65:
                        return False, f"Claim false: Title length is {len(title or '')} (<= 65 chars)."
                elif issue.type == "title_too_short":
                    if not title or len(title.strip()) >= 30:
                        return False, f"Claim false: Title length is {len(title or '')} (>= 30 chars)."
                elif issue.type == "meta_borderline":
                    if not meta_desc or not (161 <= len(meta_desc.strip()) <= 170):
                        return False, f"Claim false: Meta description length is {len(meta_desc or '')} (not 161-170 chars)."
                elif issue.type == "meta_too_long":
                    if not meta_desc or len(meta_desc.strip()) <= 170:
                        return False, f"Claim false: Meta description length is {len(meta_desc or '')} (<= 170 chars)."
                elif issue.type == "broken_link_4xx":
                    if not (400 <= status < 500):
                        return False, f"Claim false: Status code is {status}, not 4xx."
                elif issue.type == "server_error_5xx":
                    if status < 500:
                        return False, f"Claim false: Status code is {status}, not 5xx."
                elif issue.type == "noindex_page":
                    if row.get("indexability_status") not in ("noindex_meta", "noindex_header"):
                        return False, f"Claim false: Indexability status is '{row.get('indexability_status')}'."
                    if classify_page_type(row.get("url")) == "utility":
                        return False, "Claim false: Utility/private pages (login, signup, admin, cart) SHOULD be noindex; not an issue."
                elif issue.type == "indexable_admin_page":
                    if row.get("indexability_status") in ("noindex_meta", "noindex_header"):
                        return False, f"Claim false: Admin page is properly noindexed."
                    if not is_admin_page(row.get("url")):
                        return False, f"Claim false: URL '{row.get('url')}' is not an admin portal."
                elif issue.type == "indexable_private_page":
                    if row.get("indexability_status") in ("noindex_meta", "noindex_header"):
                        return False, f"Claim false: Private page is properly noindexed."
                    if classify_page_type(row.get("url")) != "utility":
                        return False, f"Claim false: URL '{row.get('url')}' is a content page."
                elif issue.type == "canonical_to_other":
                    if not canonical or canonical.rstrip('/') == row.get("url", "").rstrip('/'):
                        return False, f"Claim false: Canonical is self-referential or empty ('{canonical}')."
                elif issue.type == "canonical_mass_misconfiguration":
                    if not canonical or canonical.rstrip('/') == row.get("url", "").rstrip('/'):
                        return False, f"Claim false: Canonical is self-referential or empty ('{canonical}')."
                elif issue.type == "orphan_page":
                    if row.get("inlinks_count", 0) > 0:
                        return False, f"Claim false: Page has {row.get('inlinks_count')} inlinks, not orphan."

            elif table == "psi_results":
                row = psi_by_id.get(row_id)
                if not row:
                    return False, f"Referenced row '{row_id}' in psi_results does not exist in database."
                if issue.type == "low_performance_score":
                    score = row.get("performance_score")
                    if score is None or score >= 50:
                        return False, f"Claim false: Performance score is {score} (>= 50)."
                elif issue.type == "slow_lcp":
                    lcp = row.get("lcp_ms")
                    if lcp is None or lcp <= 2500:
                        return False, f"Claim false: LCP is {lcp} ms (<= 2500 ms)."
                elif issue.type == "poor_cls":
                    cls_val = row.get("cls")
                    if cls_val is None or cls_val <= 0.1:
                        return False, f"Claim false: CLS is {cls_val} (<= 0.1)."
            else:
                return False, f"Unknown evidence table '{table}'."

        return True, "Verified"

    # M3 Verifier Extension for Monitor Agent Findings
    @classmethod
    def verify_monitor_findings(
        cls,
        snapshot_id: str,
        snapshot: Dict[str, Any],
        findings: List[MonitorFinding],
        summary: str = ""
    ) -> MonitorVerifierReport:
        verified: List[MonitorFinding] = []
        rejected: List[Dict[str, Any]] = []

        known_numbers = collect_all_snapshot_numbers(snapshot)
        # Also allow standard small integers, model versions/ratings, periods, and benchmarks
        known_numbers.update({0.0, 1.0, 2.0, 3.0, 3.1, 3.5, 3.6, 4.0, 5.0, 7.0, 8.0, 9.0, 10.0, 14.0, 20.0, 28.0, 30.0, 60.0, 90.0, 100.0})

        for finding in findings:
            valid, reason = cls._validate_single_finding(finding, snapshot_id, snapshot, known_numbers)
            if valid:
                verified.append(finding)
            else:
                rejected.append({
                    "finding_id": finding.id,
                    "type": finding.type,
                    "reason": reason,
                    "finding_dump": finding.model_dump()
                })

        return MonitorVerifierReport(
            verified_findings=verified,
            rejected_findings=rejected,
            total_checked=len(findings),
            verified_count=len(verified),
            rejected_count=len(rejected)
        )

    @classmethod
    def _validate_single_finding(
        cls,
        finding: MonitorFinding,
        snapshot_id: str,
        snapshot: Dict[str, Any],
        known_numbers: Set[float]
    ) -> Tuple[bool, str]:
        # 1. metrics_used is non-empty
        if not finding.metrics_used or len(finding.metrics_used) == 0:
            return False, "metrics_used is empty. Every finding must trace to a computed metric."

        # 2. Check each metric reference
        for m in finding.metrics_used:
            ref_snap = m.get("snapshot_id")
            field = m.get("field")
            val = m.get("value")

            if ref_snap != snapshot_id:
                return False, f"Referenced snapshot '{ref_snap}' does not match current snapshot '{snapshot_id}'."

            # Check value match against snapshot data
            stored_val = cls._lookup_field_value(snapshot, field)
            if stored_val is None:
                return False, f"Field '{field}' does not exist in snapshot."
            
            try:
                if abs(float(val) - float(stored_val)) > 0.15:
                    return False, f"Value mismatch for field '{field}': claimed {val}, stored is {stored_val}."
            except (ValueError, TypeError):
                return False, f"Non-numeric metric value encountered for '{field}'."

        # 3. Finding type matches the data
        first_metric_val = float(finding.metrics_used[0].get("value", 0.0))
        if finding.type == "traffic_drop" and first_metric_val >= 0:
            return False, f"Claim false: 'traffic_drop' requires negative change, but metric is {first_metric_val}."
        if finding.type == "traffic_gain" and first_metric_val <= 0:
            return False, f"Claim false: 'traffic_gain' requires positive change, but metric is {first_metric_val}."
        if finding.type == "declining_page" and first_metric_val > -20.0:
            return False, f"Claim false: 'declining_page' requires drop > 20%, but metric is {first_metric_val}."

        # 4. Any number written inside headline or explanation must match a computed metric
        headline_numbers = extract_numbers_from_text(finding.headline)
        explanation_numbers = extract_numbers_from_text(finding.explanation)

        for num in headline_numbers + explanation_numbers:
            # Check if num is close to any known number
            is_traced = any(abs(num - k) < 0.15 for k in known_numbers)
            if not is_traced:
                return False, f"Untraceable number {num} written in narrative. Not found in computed metrics."

        return True, "Verified"

    @classmethod
    def _lookup_field_value(cls, data: Dict[str, Any], path: str) -> Optional[Any]:
        """Looks up nested path like 'summary_totals.clicks_change_pct' or 'striking_distance_queries.0.position'."""
        parts = path.split(".")
        curr = data
        for p in parts:
            if isinstance(curr, dict) and p in curr:
                curr = curr[p]
            elif isinstance(curr, list) and p.isdigit() and int(p) < len(curr):
                curr = curr[int(p)]
            elif isinstance(curr, dict) and p in curr.get("summary_totals", {}):
                curr = curr["summary_totals"][p]
            else:
                return None
        return curr

    # M4 Verifier Extension for Research Agent
    @classmethod
    def verify_research_opportunities(
        cls,
        snapshot_id: str,
        snapshot: Dict[str, Any],
        opportunities: List[ResearchOpportunity]
    ) -> ResearchVerifierReport:
        verified: List[ResearchOpportunity] = []
        rejected: List[Dict[str, Any]] = []
        known_numbers = collect_all_snapshot_numbers(snapshot)
        known_numbers.update({0.0, 1.0, 2.0, 3.0, 3.1, 3.5, 3.6, 4.0, 5.0, 7.0, 8.0, 9.0, 10.0, 14.0, 20.0, 28.0, 30.0, 60.0, 90.0, 100.0})

        for opp in opportunities:
            # 1. Type validation
            if opp.type not in ("gap", "cannibalization", "mismatch", "competitor_topic", "question"):
                rejected.append({"id": opp.id, "reason": f"Invalid type '{opp.type}'."})
                continue

            # 2. Metric references (unless competitor topic)
            if opp.type != "competitor_topic":
                if not opp.metrics_used:
                    rejected.append({"id": opp.id, "reason": f"metrics_used is empty for type '{opp.type}'."})
                    continue
                mismatch = False
                for m in opp.metrics_used:
                    val = m.get("value")
                    if val is not None:
                        is_traced = any(abs(float(val) - k) < 0.2 for k in known_numbers)
                        if not is_traced:
                            mismatch = True
                            rejected.append({"id": opp.id, "reason": f"Claimed metric {val} for '{m.get('field')}' is not found in research snapshot."})
                            break
                if mismatch:
                    continue

            # 3. No untraceable numbers in narrative
            headline_nums = extract_numbers_from_text(opp.headline)
            exp_nums = extract_numbers_from_text(opp.explanation)
            has_untraced = False
            for num in headline_nums + exp_nums:
                if not any(abs(num - k) < 0.2 for k in known_numbers):
                    has_untraced = True
                    rejected.append({"id": opp.id, "reason": f"Untraceable number {num} in research narrative."})
                    break
            if has_untraced:
                continue

            verified.append(opp)

        return ResearchVerifierReport(
            verified_opportunities=verified,
            rejected_opportunities=rejected,
            total_checked=len(opportunities),
            verified_count=len(verified),
            rejected_count=len(rejected)
        )

    # M4 Verifier Extension for Strategist Agent
    @classmethod
    def verify_strategy_tasks(
        cls,
        tasks: List[StrategyTask],
        verified_source_ids: Set[str],
        rejected_source_ids: Set[str] = None
    ) -> StrategyVerifierReport:
        rejected_source_ids = rejected_source_ids or set()
        verified: List[StrategyTask] = []
        rejected: List[Dict[str, Any]] = []

        # Strip self-dependencies and build dependency graph
        for t in tasks:
            t.depends_on = [d for d in (t.depends_on or []) if d != t.id]
        graph = {t.id: t.depends_on for t in tasks}
        def has_cycle(node, visited, rec_stack):
            visited.add(node)
            rec_stack.add(node)
            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    if has_cycle(neighbor, visited, rec_stack):
                        return True
                elif neighbor in rec_stack:
                    return True
            rec_stack.remove(node)
            return False

        visited_nodes, rec_stack = set(), set()
        cyclic_nodes = set()
        for t_id in graph:
            if t_id not in visited_nodes:
                if has_cycle(t_id, visited_nodes, rec_stack):
                    cyclic_nodes.add(t_id)

        for task in tasks:
            # 1. Dependency cycle
            if task.id in cyclic_nodes:
                rejected.append({"id": task.id, "reason": "Task is part of a circular dependency cycle."})
                continue

            # 2. Week and scales
            if not (1 <= task.week <= 4):
                rejected.append({"id": task.id, "reason": f"Week {task.week} is out of 1-4 range."})
                continue
            if not (1 <= task.impact <= 5) or not (1 <= task.effort <= 5):
                rejected.append({"id": task.id, "reason": "Impact and effort must be integers between 1 and 5."})
                continue

            # 3. Source references
            if not task.source_refs:
                rejected.append({"id": task.id, "reason": "Task has no source_refs. Every task must cite a verified source."})
                continue

            invalid_ref = False
            for s in task.source_refs:
                if s.id in rejected_source_ids:
                    invalid_ref = True
                    rejected.append({"id": task.id, "reason": f"Task cites rejected source '{s.id}'."})
                    break
                if s.id not in verified_source_ids:
                    invalid_ref = True
                    rejected.append({"id": task.id, "reason": f"Source reference '{s.id}' was not verified or does not exist."})
                    break
            if invalid_ref:
                continue

            # 4. Strict NO numeric forecasts (reject predictions like 'increase traffic by 30%')
            combined_text = f"{task.title} {task.expected_outcome} {task.done_when}".lower()
            if re.search(r"(?:increase|grow|boost|gain)\s+(?:traffic|clicks|revenue|sales)\s+by\s+\d+", combined_text) or \
               re.search(r"reach\s+(?:rank|position)\s+#?\d+", combined_text) or \
               re.search(r"\b\d+%\s+(?:increase|traffic|revenue|growth)", combined_text):
                rejected.append({"id": task.id, "reason": "Numeric forecast detected. LLM must never invent numeric traffic/ranking predictions."})
                continue

            verified.append(task)

        return StrategyVerifierReport(
            verified_tasks=verified,
            rejected_tasks=rejected,
            total_checked=len(tasks),
            verified_count=len(verified),
            rejected_count=len(rejected)
        )

    @classmethod
    def _extract_page_corpus(cls, page: Dict[str, Any], project_name: Optional[str] = None) -> str:
        content_parts = []
        for field in ("title", "h1", "meta_desc", "body_text", "text_content", "content", "headings", "h2", "h3"):
            val = page.get(field)
            if val:
                if isinstance(val, list):
                    content_parts.extend([str(item) for item in val if item])
                elif isinstance(val, dict):
                    content_parts.extend([str(item) for item in val.values() if item])
                elif str(val).strip():
                    content_parts.append(str(val).strip())

        # If page has no content text at all, corpus is empty -> unverifiable
        if not content_parts:
            return ""

        parts = []
        if project_name and project_name.strip():
            parts.append(str(project_name).strip())

        url = page.get("url", "")
        if url:
            parts.append(url)
            path = url.split("://")[-1].split("/", 1)[-1]
            slug_words = re.sub(r"[-_/.]", " ", path)
            parts.append(slug_words)

        parts.extend(content_parts)
        raw_corpus = " ".join(parts)
        return normalize_text_for_claims(raw_corpus).lower()

    @classmethod
    def _check_claims(cls, texts: List[str], corpus: str) -> Tuple[bool, Optional[str]]:
        if not corpus or not corpus.strip():
            return False, "unverifiable: Target page has no extractable text corpus."

        corpus_norm = normalize_text_for_claims(corpus).lower()
        corpus_space_variant = corpus_norm.replace("-", " ")
        corpus_hyphen_variant = corpus_norm.replace(" ", "-")

        for raw_text in texts:
            if not raw_text:
                continue
            text = normalize_text_for_claims(raw_text)

            # 1. Superlatives from explicit list
            for sup in EXPLICIT_SUPERLATIVES:
                sup_norm = sup.lower()
                sup_variants = [sup_norm, sup_norm.replace("-", " "), sup_norm.replace(" ", "-")]
                pat = r"\b" + re.escape(sup_norm).replace(r"\-", r"[- ]") + r"\b"
                if sup_norm == "#1":
                    pat = r"#\s*1\b|\bno\.?\s*1\b|\bnumber\s+(?:one|1)\b"

                m = re.search(pat, text, flags=re.IGNORECASE)
                if m:
                    in_corpus = any(v in corpus_norm or v in corpus_space_variant or v in corpus_hyphen_variant for v in sup_variants)
                    if not in_corpus:
                        return False, f"Superlative '{m.group(0)}' not found in page text or project name."

            # 2. Years (invented year check: 19xx, 20xx)
            years = re.findall(r"\b(19\d\d|20\d\d)\b", text)
            for yr in years:
                if yr not in corpus_norm:
                    return False, f"Invented year '{yr}' not found in page text or project name."

            # 3. Ranks (#1, #2, etc.)
            ranks = re.findall(r"#\d+\b", text)
            for rk in ranks:
                rk_low = rk.lower()
                digit = rk.replace("#", "")
                variants = [rk_low, f"no. {digit}", f"no {digit}", f"number {digit}", digit]
                if not any(v in corpus_norm for v in variants):
                    return False, f"Rank/number '{rk}' not found in page text or project name."

            # 4. Percentages
            percentages = re.findall(r"\b\d+(?:\.\d+)?%", text)
            for pct in percentages:
                if pct.lower() not in corpus_norm:
                    return False, f"Percentage '{pct}' not found in page text or project name."

            # 5. List-count numbers check
            # Mask allowed list-counts (e.g. '7 tips', '5 ways', '10 questions') and percentages
            masked_text = LIST_COUNT_REGEX.sub("ALLOWED_LIST_COUNT", text)
            masked_text = re.sub(r"\b\d+(?:\.\d+)?%", "ALLOWED_PERCENT", masked_text)

            # Check remaining raw numbers > 20 or not in list count
            raw_nums = re.findall(r"\b\d+\b", masked_text)
            for num in raw_nums:
                if num not in corpus_norm:
                    return False, f"Number '{num}' not found in page text or project name."

            # 6. Proper Nouns: CamelCase / internal capitalization (e.g. Next.js, WordPress)
            raw_words = re.findall(r"\b[a-zA-Z0-9#\-\.]+\b", text)
            for w in raw_words:
                clean_w = w.strip(".,;:!?\"'()[]{}")
                w_low = clean_w.lower()
                if w_low in EXPLICIT_SUPERLATIVES or w_low.replace("-", " ") in EXPLICIT_SUPERLATIVES:
                    continue
                if len(clean_w) >= 2 and any(c.isupper() for c in clean_w[1:]) and any(c.islower() for c in clean_w):
                    variants = [w_low, w_low.replace("-", " "), w_low.replace(" ", "-")]
                    if not any(v in corpus_norm or v in corpus_space_variant or v in corpus_hyphen_variant for v in variants):
                        return False, f"Proper noun '{clean_w}' not found in page text or project name."

        return True, None

    # M4 Verifier Extension for Content Agent
    @classmethod
    def verify_content_outputs(
        cls,
        report: ContentAgentReport,
        crawl_pages: List[Dict[str, Any]],
        crawl_links: List[Dict[str, Any]],
        research_snapshot: Dict[str, Any],
        project_name: Optional[str] = None
    ) -> ContentVerifierReport:
        verified_b, rejected_b = [], []
        verified_r, rejected_r = [], []
        kept_r: List[OnPageRewrite] = []
        verified_l, rejected_l = [], []

        page_by_url = {p["url"].rstrip("/"): p for p in crawl_pages}
        all_crawled_urls = set(page_by_url.keys())
        existing_links = {(l.get("source_url", "").rstrip("/"), l.get("target_url", "").rstrip("/")) for l in crawl_links}
        real_gsc_questions = {q.get("query", "").strip().lower() for q in research_snapshot.get("question_queries", []) if q.get("query")}
        cluster_head_terms = {cl.get("head_term", "").strip().lower() for cl in research_snapshot.get("query_clusters", []) if cl.get("head_term")}

        # Determine active project name
        inferred_project_name = ""
        if crawl_pages and crawl_pages[0].get("url"):
            first_url = crawl_pages[0]["url"]
            domain_part = first_url.split("://")[-1].split("/")[0].split(":")[0]
            domain_sub = domain_part.split(".")[0]
            if domain_sub and domain_sub != "www":
                inferred_project_name = domain_sub
            elif "." in domain_part:
                inferred_project_name = domain_part.split(".")[1]
        active_project_name = project_name or inferred_project_name

        # 1. Content Briefs
        for b in report.briefs:
            # Recheck character lengths
            if len(b.suggested_title) > 60:
                rejected_b.append({"target_cluster": b.target_cluster, "reason": f"suggested_title length is {len(b.suggested_title)} (> 60 chars)."})
                continue
            if len(b.suggested_meta) > 155:
                rejected_b.append({"target_cluster": b.target_cluster, "reason": f"suggested_meta length is {len(b.suggested_meta)} (> 155 chars)."})
                continue

            # Target cluster exists
            if cluster_head_terms and b.target_cluster.lower() not in cluster_head_terms:
                # Allow partial match
                if not any(b.target_cluster.lower() in ct or ct in b.target_cluster.lower() for ct in cluster_head_terms):
                    rejected_b.append({"target_cluster": b.target_cluster, "reason": f"Target cluster '{b.target_cluster}' not found in research snapshot."})
                    continue

            # Questions must exist in real GSC queries
            invalid_q = False
            for q in b.questions_to_answer:
                if real_gsc_questions and q.lower() not in real_gsc_questions:
                    rejected_b.append({"target_cluster": b.target_cluster, "reason": f"Question '{q}' does not exist in real Search Console queries."})
                    invalid_q = True
                    break
            if invalid_q:
                continue

            # Disallow search volume or keyword difficulty numbers anywhere in brief
            combined_b = f"{b.suggested_title} {b.suggested_meta} {b.notes or ''}".lower()
            if re.search(r"\b(?:search volume|volume|sv|kd|difficulty)\s*[:=]\s*\d+", combined_b):
                rejected_b.append({"target_cluster": b.target_cluster, "reason": "Invented search volume or keyword difficulty detected."})
                continue

            # Claims Check for Content Briefs
            target_p = None
            if getattr(b, "target_url", None) and b.target_url.rstrip("/") in page_by_url:
                target_p = page_by_url[b.target_url.rstrip("/")]
            else:
                cluster_low = b.target_cluster.lower()
                for p in crawl_pages:
                    p_text = f"{p.get('url', '')} {p.get('title', '')} {p.get('h1', '')}".lower()
                    if cluster_low in p_text:
                        target_p = p
                        break

            if target_p:
                brief_corpus = cls._extract_page_corpus(target_p, active_project_name)
            else:
                all_corp = [active_project_name or ""]
                for p in crawl_pages:
                    all_corp.append(cls._extract_page_corpus(p, project_name=""))
                brief_corpus = " ".join(all_corp).lower()

            brief_texts = [b.suggested_title, b.suggested_meta, b.h1]
            b_claims_ok, b_fail_reason = cls._check_claims(brief_texts, brief_corpus)
            if not b_claims_ok:
                current_bt = target_p.get("title", "") if target_p else getattr(b, "current_title", "")
                current_bm = target_p.get("meta_desc", "") if target_p else getattr(b, "current_meta", "")
                current_bh = target_p.get("h1", "") if target_p else getattr(b, "current_h1", "")
                status = "unverifiable" if "unverifiable" in b_fail_reason.lower() else "rejected"
                rejected_b.append({
                    "target_cluster": b.target_cluster,
                    "status": status,
                    "reason": f"Claims check failed: {b_fail_reason}" if status == "rejected" else f"Claims check unverifiable: {b_fail_reason}",
                    "kept_title": current_bt,
                    "kept_meta": current_bm,
                    "kept_h1": current_bh
                })
                continue

            verified_b.append(b)

        # 2. On-Page Rewrites
        for r in report.rewrites:
            norm_u = r.url.rstrip("/")
            if norm_u not in all_crawled_urls:
                rejected_r.append({"url": r.url, "reason": f"URL '{r.url}' does not exist in crawl records."})
                continue
            p = page_by_url[norm_u]
            if r.suggested_title != "no change needed" and len(r.suggested_title) > 60:
                rejected_r.append({"url": r.url, "reason": f"suggested_title is {len(r.suggested_title)} chars (> 60)."})
                continue
            if r.suggested_meta != "no change needed" and len(r.suggested_meta) > 155:
                rejected_r.append({"url": r.url, "reason": f"suggested_meta is {len(r.suggested_meta)} chars (> 155)."})
                continue
            # Match current_*
            if r.current_title and p.get("title") and r.current_title != p.get("title"):
                rejected_r.append({"url": r.url, "reason": "current_title does not match database crawl record."})
                continue

            # Claims Check for On-Page Rewrites
            current_t = p.get("title") or r.current_title or ""
            current_m = p.get("meta_desc") or r.current_meta or ""
            current_h = p.get("h1") or getattr(r, "current_h1", "") or ""

            page_corpus = cls._extract_page_corpus(p, active_project_name)

            texts_to_check = [r.suggested_title, r.suggested_meta]
            if getattr(r, "suggested_h1", None):
                texts_to_check.append(r.suggested_h1)

            claims_ok, failure_reason = cls._check_claims(texts_to_check, page_corpus)
            if not claims_ok:
                status = "unverifiable" if "unverifiable" in failure_reason.lower() else "rejected"
                rejected_r.append({
                    "url": r.url,
                    "status": status,
                    "reason": f"Claims check failed: {failure_reason}" if status == "rejected" else f"Claims check unverifiable: {failure_reason}",
                    "kept_title": current_t,
                    "kept_meta": current_m,
                    "kept_h1": current_h
                })
                kept_r.append(OnPageRewrite(
                    url=r.url,
                    current_title=current_t,
                    suggested_title=current_t,
                    current_meta=current_m,
                    suggested_meta=current_m,
                    current_h1=current_h,
                    suggested_h1=current_h,
                    source="kept_current"
                ))
                continue

            # Requirement 4: Check preservation of key service terms and target markets
            if current_m:
                curr_markets, curr_services = extract_preserved_entities(current_m)
                combined_suggested = f"{r.suggested_title} {r.suggested_meta}".lower()
                sugg_markets, sugg_services = extract_preserved_entities(combined_suggested)

                dropped_markets = curr_markets - sugg_markets
                if dropped_markets:
                    reason = f"Key target market(s) {sorted(list(dropped_markets))} from current meta were silently dropped."
                    rejected_r.append({
                        "url": r.url,
                        "status": "rejected",
                        "reason": f"Claims check failed: {reason}",
                        "kept_title": current_t,
                        "kept_meta": current_m,
                        "kept_h1": current_h
                    })
                    kept_r.append(OnPageRewrite(
                        url=r.url,
                        current_title=current_t,
                        suggested_title=current_t,
                        current_meta=current_m,
                        suggested_meta=current_m,
                        current_h1=current_h,
                        suggested_h1=current_h,
                        source="kept_current"
                    ))
                    continue

                dropped_services = curr_services - sugg_services
                if curr_services and len(sugg_services) == 0 and len(curr_services) > 0:
                    reason = f"Key service term(s) {sorted(list(dropped_services))} from current meta were silently dropped."
                    rejected_r.append({
                        "url": r.url,
                        "status": "rejected",
                        "reason": f"Claims check failed: {reason}",
                        "kept_title": current_t,
                        "kept_meta": current_m,
                        "kept_h1": current_h
                    })
                    kept_r.append(OnPageRewrite(
                        url=r.url,
                        current_title=current_t,
                        suggested_title=current_t,
                        current_meta=current_m,
                        suggested_meta=current_m,
                        current_h1=current_h,
                        suggested_h1=current_h,
                        source="kept_current"
                    ))
                    continue

            # Check preservation of "SEO-Friendly" meaning
            if "seo-friendly" in current_m.lower() and r.suggested_meta != "no change needed":
                if "seo-friendly" not in r.suggested_meta.lower():
                    reason = "Key service term 'SEO-Friendly' from current meta was altered or dropped."
                    rejected_r.append({
                        "url": r.url,
                        "status": "rejected",
                        "reason": f"Claims check failed: {reason}",
                        "kept_title": current_t,
                        "kept_meta": current_m,
                        "kept_h1": current_h
                    })
                    kept_r.append(OnPageRewrite(
                        url=r.url,
                        current_title=current_t,
                        suggested_title=current_t,
                        current_meta=current_m,
                        suggested_meta=current_m,
                        source="kept_current"
                    ))
                    continue

            # Check near-duplicate meta description (similarity > 0.60)
            if r.suggested_meta and r.suggested_meta != "no change needed":
                is_near_dup = False
                for prev_vr in verified_r:
                    if prev_vr.suggested_meta and prev_vr.suggested_meta != "no change needed":
                        sim = difflib.SequenceMatcher(None, r.suggested_meta.lower(), prev_vr.suggested_meta.lower()).ratio()
                        if sim > 0.60:
                            is_near_dup = True
                            break
                if is_near_dup:
                    reason = "Suggested meta description is a near-duplicate (similarity above 0.60) of another page's meta."
                    rejected_r.append({
                        "url": r.url,
                        "status": "rejected",
                        "reason": f"Claims check failed: {reason}",
                        "kept_title": current_t,
                        "kept_meta": current_m,
                        "kept_h1": current_h
                    })
                    kept_r.append(OnPageRewrite(
                        url=r.url,
                        current_title=current_t,
                        suggested_title=current_t,
                        current_meta=current_m,
                        suggested_meta=current_m,
                        source="kept_current"
                    ))
                    continue

            verified_r.append(r)

        # 3. Internal Links (Requirement 3)
        src_counts = {}
        tgt_counts = {}
        used_anchors_by_target: Dict[str, Set[str]] = defaultdict(set)

        for l in report.internal_links:
            s_norm = l.source_url.rstrip("/")
            t_norm = l.target_url.rstrip("/")
            if s_norm not in all_crawled_urls or t_norm not in all_crawled_urls:
                rejected_l.append({"link": f"{l.source_url} -> {l.target_url}", "reason": "Source or target URL does not exist in crawl."})
                continue
            if s_norm == t_norm:
                rejected_l.append({"link": f"{l.source_url} -> {l.target_url}", "reason": "Self-links are disallowed."})
                continue
            if (s_norm, t_norm) in existing_links:
                rejected_l.append({"link": f"{l.source_url} -> {l.target_url}", "reason": "Link already exists on the live website."})
                continue

            # Never suggest internal links to or from noindex pages or utility pages
            src_p = page_by_url.get(s_norm, {})
            tgt_p = page_by_url.get(t_norm, {})
            if classify_page_type(s_norm) == "utility" or src_p.get("indexability_status") in ("noindex_meta", "noindex_header"):
                rejected_l.append({"link": f"{l.source_url} -> {l.target_url}", "reason": "Source page is a utility or noindex page; cannot suggest internal links from utility/noindex pages."})
                continue
            if classify_page_type(t_norm) == "utility" or tgt_p.get("indexability_status") in ("noindex_meta", "noindex_header"):
                rejected_l.append({"link": f"{l.source_url} -> {l.target_url}", "reason": "Target page is a utility or noindex page; cannot suggest internal links to utility/noindex pages."})
                continue

            src_counts[s_norm] = src_counts.get(s_norm, 0) + 1
            if src_counts[s_norm] > 3:
                rejected_l.append({"link": f"{l.source_url} -> {l.target_url}", "reason": "Exceeded maximum cap of 3 new internal links per source page."})
                continue

            # Max 2 new links per target page per run
            tgt_counts[t_norm] = tgt_counts.get(t_norm, 0) + 1
            if tgt_counts[t_norm] > 2:
                rejected_l.append({"link": f"{l.source_url} -> {l.target_url}", "reason": "Exceeded maximum cap of 2 new internal links per target page."})
                continue

            # Vary anchors check
            anchor_clean = l.anchor_text.strip().lower()
            if anchor_clean in used_anchors_by_target[t_norm]:
                rejected_l.append({"link": f"{l.source_url} -> {l.target_url}", "reason": f"Duplicate anchor text '{l.anchor_text}' for target page; anchors must be varied."})
                continue

            # Anchor text format: 2-6 words, no '/', no trailing stopwords
            anchor_words = [w.strip(" ,.-'\"()[]{}") for w in l.anchor_text.split() if w.strip(" ,.-'\"()[]{}")]
            if "/" in l.anchor_text:
                rejected_l.append({"link": f"{l.source_url} -> {l.target_url}", "reason": f"Anchor text '{l.anchor_text}' contains invalid '/' or path character."})
                continue
            if len(anchor_words) < 2 or len(anchor_words) > 6:
                rejected_l.append({"link": f"{l.source_url} -> {l.target_url}", "reason": f"Anchor text '{l.anchor_text}' has {len(anchor_words)} words (must be 2-6 words)."})
                continue
            if anchor_words[-1].lower() in STOPWORDS_TRAILING:
                rejected_l.append({"link": f"{l.source_url} -> {l.target_url}", "reason": f"Anchor text '{l.anchor_text}' ends in trailing stopword '{anchor_words[-1]}'."})
                continue

            used_anchors_by_target[t_norm].add(anchor_clean)

            # Check for shared meaningful terms if terms exist
            src_p = page_by_url.get(s_norm, {})
            tgt_p = page_by_url.get(t_norm, {})
            src_meaningful = {
                t.lower().strip(" ,.") for t in src_p.get("text_terms", [])
                if t.lower().strip(" ,.") not in GENERIC_LINK_TERMS and len(t.strip(" ,.")) > 2
            }
            tgt_meaningful = {
                t.lower().strip(" ,.") for t in tgt_p.get("text_terms", [])
                if t.lower().strip(" ,.") not in GENERIC_LINK_TERMS and len(t.strip(" ,.")) > 2
            }
            if src_meaningful and tgt_meaningful and len(src_meaningful & tgt_meaningful) < 2:
                rejected_l.append({"link": f"{l.source_url} -> {l.target_url}", "reason": f"Insufficient shared meaningful terms ({len(src_meaningful & tgt_meaningful)} < 2) between source and target."})
                continue

            verified_l.append(l)

        total_checked = len(report.briefs) + len(report.rewrites) + len(report.internal_links)
        verified_count = len(verified_b) + len(verified_r) + len(verified_l)
        rejected_count = len(rejected_b) + len(rejected_r) + len(rejected_l)

        return ContentVerifierReport(
            verified_briefs=verified_b,
            rejected_briefs=rejected_b,
            verified_rewrites=verified_r,
            rejected_rewrites=rejected_r,
            kept_rewrites=kept_r,
            verified_internal_links=verified_l,
            rejected_internal_links=rejected_l,
            total_checked=total_checked,
            verified_count=verified_count,
            rejected_count=rejected_count
        )
