import json
import asyncio
import random
import re
import httpx
from typing import List, Dict, Any, Tuple, Optional
from app.core.config import settings
from app.models.agent_schemas import (
    TechnicalIssue, MonitorFinding, ResearchOpportunity,
    StrategyReport, StrategyTask, StrategyTaskSourceRef
)

HUMAN_ISSUE_LABELS: Dict[str, str] = {
    "broken_link_4xx": "Fix broken link",
    "missing_h1": "Add missing H1",
    "canonical_to_other": "Fix canonical tags: canonical_to_other",
    "canonical_mass_misconfiguration": "Resolve mass canonical misconfiguration",
    "duplicate_title": "Rewrite duplicate page titles",
    "duplicate_meta_description": "Rewrite duplicate meta descriptions",
    "title_borderline": "Review borderline title tags (61-65 chars)",
    "title_too_long": "Optimize long title tags (>65 chars)",
    "title_too_short": "Expand short title tags",
    "meta_borderline": "Review borderline meta descriptions (161-170 chars)",
    "meta_too_long": "Shorten long meta descriptions (>170 chars)",
    "missing_title": "Add missing page titles",
    "missing_meta_description": "Add missing meta descriptions",
    "missing_canonical": "Add self-referencing canonical tags",
    "server_error_5xx": "Resolve 5xx server errors",
    "redirect_chain": "Fix redirect chains",
    "orphan_page": "Link orphaned pages",
    "low_performance_score": "Improve Core Web Vitals performance score",
    "slow_lcp": "Optimize Largest Contentful Paint (LCP)",
    "poor_cls": "Fix Cumulative Layout Shift (CLS)",
    "brand_repeated_in_title": "Deduplicate brand occurrences in title tags",
    "sitemap_lists_non_existent_url": "Remove 404 URLs from sitemap",
    "crawled_page_missing_from_sitemap": "Add missing crawled pages to sitemap",
}

def format_human_task_title(issue_type: str, url: str) -> str:
    """Format single URL human label, e.g. 'Fix broken link: /portfolio/iron-pulse-fitness'."""
    parsed_path = url.split("://")[-1].split("/", 1)[-1]
    url_path = f"/{parsed_path}" if parsed_path else "/"
    prefix = HUMAN_ISSUE_LABELS.get(issue_type, issue_type.replace("_", " ").title())
    return f"{prefix}: {url_path}"

def format_group_task_title(issue_type: str, url_count: int, preview_count: int = 3) -> str:
    """Format group task title showing real total and preview count.
    Example: 'Shorten long meta descriptions (17 pages, start with these 3)'.
    """
    label = HUMAN_ISSUE_LABELS.get(issue_type, issue_type.replace("_", " ").title())
    if url_count <= preview_count:
        return f"{label} ({url_count} page{'s' if url_count != 1 else ''})"
    return f"{label} ({url_count} pages, start with these {preview_count})"

def format_task_title(base_action: str, issue_type: str, urls: List[str]) -> str:
    """Creates a human-readable task title."""
    if not urls:
        return f"{base_action}: {HUMAN_ISSUE_LABELS.get(issue_type, issue_type.replace('_', ' ').title())}"
    if issue_type in ("broken_link_4xx", "missing_h1"):
        return format_human_task_title(issue_type, urls[0])
    return format_group_task_title(issue_type, len(urls))

def deduplicate_strategy_tasks(tasks: List[StrategyTask]) -> List[StrategyTask]:
    """Deduplicates tasks: unique by title and URL set.
    No two tasks share the same title and URL set.
    """
    seen = set()
    deduped: List[StrategyTask] = []
    for t in tasks:
        # Extract URLs from done_when, title, or outcome
        urls = tuple(sorted(re.findall(r"https?://[^\s,\)]+", f"{t.title} {t.done_when} {t.expected_outcome}")))
        norm_title = re.sub(r"\s+", " ", t.title.strip().lower())
        key = (norm_title, urls) if urls else (norm_title,)
        if key not in seen:
            seen.add(key)
            deduped.append(t)

    # Renumber sequentially
    for idx, t in enumerate(deduped, 1):
        t.id = f"S-{idx:03d}"
    if len(tasks) != len(deduped):
        print(f"[Strategist] Deduplicated tasks: {len(tasks)} -> {len(deduped)} unique tasks (removed {len(tasks) - len(deduped)} duplicates).")
    return deduped

class StrategistAgent:
    """Strategist Agent: Synthesizes verified technical, performance, and research findings into a 30-day roadmap."""

    @classmethod
    async def run(
        cls,
        verified_tech: List[TechnicalIssue],
        verified_perf: List[MonitorFinding],
        verified_research: List[ResearchOpportunity],
        force_fallback: bool = False
    ) -> Tuple[StrategyReport, str, float, Optional[str], Optional[str]]:
        """Returns (report, mode, cost_usd, failure_reason, model_used)."""
        if not force_fallback and settings.GEMINI_API_KEY:
            models = settings.gemini_model_list
            errors_by_model = []
            for model_name in models:
                try:
                    report, cost, p_tokens, c_tokens = await cls._run_with_single_model(
                        verified_tech, verified_perf, verified_research, model_name
                    )
                    report.tokens_prompt = p_tokens
                    report.tokens_completion = c_tokens
                    # Enforce code computation of priority scores and sorting
                    cls._compute_priority_scores_and_sort(report)
                    return report, "llm", cost, None, model_name
                except Exception as e:
                    err_msg = f"[{model_name}: {e}]"
                    print(f"StrategistAgent model {model_name} failed: {e}. Trying next...")
                    errors_by_model.append(err_msg)

            failure_reason = "All models failed -> " + "; ".join(errors_by_model)
        elif force_fallback:
            failure_reason = "Cost cap reached; deterministic fallback invoked."
        else:
            failure_reason = "GEMINI_API_KEY is not configured in .env"

        mode = "fallback_cost_cap" if force_fallback else "fallback"
        print(f"StrategistAgent falling back to deterministic synthesizer: {failure_reason}")
        report = cls._run_deterministic(verified_tech, verified_perf, verified_research)
        cls._compute_priority_scores_and_sort(report)
        return report, mode, 0.0, failure_reason, None

    @classmethod
    def _compute_priority_scores_and_sort(cls, report: StrategyReport):
        """Code computes priority_score = (impact * 1.0) / max(effort, 1), deduplicates, and sorts tasks descending."""
        # Deduplicate tasks so no two tasks share the same title and URL set
        report.tasks = deduplicate_strategy_tasks(report.tasks)

        for task in report.tasks:
            eff = max(1, min(5, task.effort))
            imp = max(1, min(5, task.impact))
            task.priority_score = round((imp * 2.0) / eff, 2)
            # Remove any self-dependencies to prevent circular dependency cycles
            task.depends_on = [d for d in (task.depends_on or []) if d != task.id]

        # Sort: Week 1 technical blockers first, then highest priority score
        report.tasks.sort(key=lambda t: (t.week, -t.priority_score))

        # Re-index consecutive IDs S-001, S-002, ... cleanly preserving dependency references
        old_to_new = {t.id: f"S-{idx:03d}" for idx, t in enumerate(report.tasks, 1)}
        for idx, task in enumerate(report.tasks, 1):
            new_id = f"S-{idx:03d}"
            task.depends_on = [old_to_new[d] for d in (task.depends_on or []) if d in old_to_new and old_to_new[d] != new_id]
            task.id = new_id

    @classmethod
    def _run_deterministic(
        cls,
        tech_issues: List[TechnicalIssue],
        perf_findings: List[MonitorFinding],
        research_opps: List[ResearchOpportunity]
    ) -> StrategyReport:
        tasks: List[StrategyTask] = []
        task_idx = 1

        # Build tasks from technical issues:
        # Rule: Per-URL tasks ONLY for broken links (broken_link_4xx) and missing H1 (missing_h1).
        # One task per issue type for all others, with URL list in task details.
        for iss in tech_issues:
            if iss.type in ("broken_link_4xx", "missing_h1"):
                for u in iss.urls:
                    parsed_path = u.split("://")[-1].split("/", 1)[-1]
                    url_path = f"/{parsed_path}" if parsed_path else "/"
                    tasks.append(StrategyTask(
                        id=f"S-{task_idx:03d}",
                        title=format_human_task_title(iss.type, u),
                        category="technical" if iss.type == "broken_link_4xx" else "on_page",
                        week=1 if iss.type == "broken_link_4xx" else 2,
                        impact=5 if iss.type == "broken_link_4xx" else 4,
                        effort=2,
                        depends_on=[],
                        source_refs=[StrategyTaskSourceRef(kind="tech_issue", id=iss.id)],
                        expected_outcome=f"Eliminates {iss.type.replace('_', ' ')} error on {url_path}.",
                        done_when=f"Fix verified for {url_path} returning valid 200 OK content."
                    ))
                    task_idx += 1
            else:
                urls_str = ", ".join(iss.urls[:3]) + (f" (+{len(iss.urls)-3} more)" if len(iss.urls) > 3 else "")
                tasks.append(StrategyTask(
                    id=f"S-{task_idx:03d}",
                    title=format_group_task_title(iss.type, len(iss.urls)),
                    category="technical" if iss.severity == "high" or "canonical" in iss.type else "on_page",
                    week=1 if iss.severity == "high" else 2,
                    impact=5 if iss.severity == "high" else 3,
                    effort=3 if len(iss.urls) > 5 else 2,
                    depends_on=[tasks[0].id] if tasks else [],
                    source_refs=[StrategyTaskSourceRef(kind="tech_issue", id=iss.id)],
                    expected_outcome=f"Standardizes {iss.type.replace('_', ' ')} across {len(iss.urls)} pages.",
                    done_when=f"Resolved across {len(iss.urls)} URLs: {urls_str}."
                ))
                task_idx += 1

        # Week 3: Content Opportunities & Striking Distance (Performance & Research)
        for opp in research_opps:
            if opp.type in ("gap", "cannibalization", "question"):
                tasks.append(StrategyTask(
                    id=f"S-{task_idx:03d}",
                    title=f"Action Research Opportunity: {opp.headline[:50]}",
                    category="content",
                    week=3,
                    impact=4,
                    effort=3,
                    depends_on=[],
                    source_refs=[StrategyTaskSourceRef(kind="research_opportunity", id=opp.id)],
                    expected_outcome="Captures qualified topical search demand and eliminates search ambiguity.",
                    done_when=f"New targeted content brief is drafted and deployed for {opp.type}."
                ))
                task_idx += 1
                if len(tasks) >= 14:
                    break

        # Week 4: Internal Linking & Monitoring
        for find in perf_findings:
            tasks.append(StrategyTask(
                id=f"S-{task_idx:03d}",
                title=f"Execute action on performance finding: {find.headline[:45]}",
                category="monitoring" if "traffic" in find.type else "internal_linking",
                week=4,
                impact=3,
                effort=2,
                depends_on=[],
                source_refs=[StrategyTaskSourceRef(kind="perf_finding", id=find.id)],
                expected_outcome="Supports page equity consolidation and capitalizes on organic visibility momentum.",
                done_when=f"Recommendations for finding {find.id} implemented."
            ))
            task_idx += 1
            if len(tasks) >= 20:
                break

        summary = (
            f"The 30-day SEO Strategy establishes a phased roadmap prioritizing urgent technical indexation blockers in Week 1, "
            f"on-page optimization in Week 2, target content gap expansion in Week 3, and internal link equity distribution in Week 4. "
            f"All {len(tasks)} tasks map directly to verified empirical audit data."
        )

        return StrategyReport(summary=summary, tasks=tasks[:20])

    @classmethod
    async def _run_with_single_model(
        cls,
        tech_issues: List[TechnicalIssue],
        perf_findings: List[MonitorFinding],
        research_opps: List[ResearchOpportunity],
        model_name: str
    ) -> Tuple[StrategyReport, float, int, int]:
        inputs = {
            "verified_technical_issues": [i.model_dump() for i in tech_issues[:15]],
            "verified_performance_findings": [f.model_dump() for f in perf_findings[:10]],
            "verified_research_opportunities": [o.model_dump() for o in research_opps[:10]]
        }

        prompt = f"""
        You are an elite SEO Strategist Agent. Create a prioritised 30-day action plan with at most 20 tasks.
        Rules:
        - Every task MUST reference at least one verified source (kind: tech_issue, perf_finding, or research_opportunity) with exact matching ID.
        - Fix technical blockers (indexing, canonicals, broken links) in Week 1 before content tasks.
        - Task title MUST specify the real URL/page path from the cited issue evidence (e.g. 'Resolve Broken Link 4Xx on /services'). Never use generic free text.
        - Schedule weeks between 1 and 4.
        - Impact and effort MUST be integers between 1 and 5.
        - NO numeric forecasts (e.g. do NOT predict 'will increase traffic by 30%' or 'reach rank #1').
        - Expected outcome must be purely qualitative.

        Verified Inputs:
        {json.dumps(inputs, indent=2)}

        Return JSON matching this schema:
        {{
          "summary": "3-5 sentences strategic roadmap overview",
          "tasks": [
            {{
              "id": "S-001",
              "title": "Clear task title citing exact page URL path",
              "category": "technical|on_page|content|internal_linking|monitoring",
              "week": 1,
              "impact": 5,
              "effort": 2,
              "depends_on": [],
              "source_refs": [{{"kind": "tech_issue", "id": "T-001"}}],
              "expected_outcome": "Qualitative outcome explanation",
              "done_when": "Clear acceptance criteria"
            }}
          ]
        }}
        """

        base_delays = [2.0, 5.0, 15.0, 30.0]
        max_attempts = len(base_delays)
        last_error = ""

        async with httpx.AsyncClient() as client:
            for attempt_idx, base_delay in enumerate(base_delays, start=1):
                try:
                    resp = await client.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={settings.GEMINI_API_KEY}",
                        json={
                            "contents": [{"parts": [{"text": prompt}]}],
                            "generationConfig": {"response_mime_type": "application/json"}
                        },
                        timeout=45.0
                    )
                    if resp.status_code == 200:
                        res_json = resp.json()
                        usage = res_json.get("usageMetadata", {})
                        p_tokens = usage.get("promptTokenCount", 0)
                        c_tokens = usage.get("candidatesTokenCount", 0)
                        cost = (p_tokens * 0.000000075) + (c_tokens * 0.00000030)

                        raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
                        parsed = json.loads(raw_text)

                        # Enforce real URL and human labels in task titles & deduplicate by issue type + URL set
                        tech_map = {i.id: i for i in tech_issues}
                        seen_group_issues = set()
                        valid_task_dicts = []

                        for task_dict in parsed.get("tasks", []):
                            drop_task = False
                            for ref in task_dict.get("source_refs", []):
                                ref_kind = ref.get("kind")
                                ref_id = ref.get("id")
                                if ref_kind == "tech_issue" and ref_id in tech_map:
                                    iss = tech_map[ref_id]
                                    if iss.type in ("broken_link_4xx", "missing_h1"):
                                        if iss.urls:
                                            task_dict["title"] = format_human_task_title(iss.type, iss.urls[0])
                                    else:
                                        if iss.type in seen_group_issues:
                                            drop_task = True
                                            break
                                        seen_group_issues.add(iss.type)
                                        task_dict["title"] = format_group_task_title(iss.type, len(iss.urls))
                                        urls_str = ", ".join(iss.urls[:3]) + (f" (+{len(iss.urls)-3} more)" if len(iss.urls) > 3 else "")
                                        task_dict["done_when"] = f"Resolved across {len(iss.urls)} URLs: {urls_str}."
                                    break
                            if not drop_task:
                                valid_task_dicts.append(task_dict)

                        parsed["tasks"] = valid_task_dicts
                        rep = StrategyReport.model_validate(parsed)
                        rep.tasks = deduplicate_strategy_tasks(rep.tasks)
                        for t in rep.tasks:
                            t.depends_on = [d for d in (t.depends_on or []) if d != t.id]
                        return rep, round(cost, 6), p_tokens, c_tokens

                    error_snippet = resp.text[:200]
                    last_error = f"Gemini API HTTP {resp.status_code}: {error_snippet}"

                    if resp.status_code in (429, 503) and attempt_idx < max_attempts:
                        jitter = random.uniform(0.1, 1.0)
                        wait_time = base_delay + jitter
                        print(f"[{model_name}] HTTP {resp.status_code} in StrategistAgent. Retrying in {wait_time:.1f}s...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        raise Exception(last_error)

                except (httpx.TimeoutException, httpx.NetworkError) as net_err:
                    last_error = f"Gemini connection error: {type(net_err).__name__} - {net_err}"
                    if attempt_idx < max_attempts:
                        jitter = random.uniform(0.1, 1.0)
                        wait_time = base_delay + jitter
                        print(f"[{model_name}] Network error in StrategistAgent. Retrying in {wait_time:.1f}s...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        raise Exception(last_error)

        raise Exception(last_error or f"[{model_name}] Retries exhausted in StrategistAgent.")
