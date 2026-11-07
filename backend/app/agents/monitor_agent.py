import json
import random
import asyncio
import httpx
from typing import Dict, Any, List, Tuple, Optional
from app.core.config import settings
from app.models.agent_schemas import MonitorReport, MonitorFinding

class MonitorAgent:
    """Thin interface for Monitor Agent. Explains GSC & GA4 performance trends."""

    @classmethod
    async def run(
        cls,
        snapshot_id: str,
        snapshot: Dict[str, Any]
    ) -> Tuple[MonitorReport, str, float, Optional[str], Optional[str]]:
        """Returns (report, mode, cost_usd, failure_reason, model_used)."""
        if not snapshot or "summary_totals" not in snapshot:
            return MonitorReport(
                summary="No performance snapshot metrics are available to analyze.",
                findings=[]
            ), "fallback", 0.0, None, None

        if settings.GEMINI_API_KEY:
            models = settings.gemini_model_list
            errors_by_model = []
            for model_name in models:
                try:
                    report, cost, p_tokens, c_tokens = await cls._run_with_single_model(snapshot_id, snapshot, model_name)
                    report.tokens_prompt = p_tokens
                    report.tokens_completion = c_tokens
                    return report, "llm", cost, None, model_name
                except Exception as e:
                    err_msg = f"[{model_name}: {e}]"
                    print(f"MonitorAgent model {model_name} failed: {e}. Trying next...")
                    errors_by_model.append(err_msg)

            failure_reason = "All models failed -> " + "; ".join(errors_by_model)
        else:
            failure_reason = "GEMINI_API_KEY is not configured in .env"

        print(f"MonitorAgent falling back to deterministic synthesizer: {failure_reason}")
        report = cls._run_deterministic(snapshot_id, snapshot)
        return report, "fallback", 0.0, failure_reason, None

    @classmethod
    def _run_deterministic(cls, snapshot_id: str, snapshot: Dict[str, Any]) -> MonitorReport:
        totals = snapshot.get("summary_totals", {})
        findings: List[MonitorFinding] = []
        idx = 1

        clicks_pct = totals.get("clicks_change_pct", 0.0)
        curr_clicks = totals.get("clicks", 0)
        prev_clicks = totals.get("previous_clicks", 0)

        # 1. Traffic trend (gain or drop)
        if clicks_pct < 0:
            findings.append(MonitorFinding(
                id=f"P-{idx:03d}",
                type="traffic_drop",
                headline=f"Organic clicks declined by {abs(clicks_pct)}%",
                explanation=f"Search Console organic clicks dropped by {abs(clicks_pct)}% from {prev_clicks} to {curr_clicks} over the last 90-day period.",
                metrics_used=[{"snapshot_id": snapshot_id, "field": "clicks_change_pct", "value": clicks_pct}],
                recommended_action="Investigate declining landing pages and technical regressions across recently modified URLs.",
                confidence=0.95
            ))
            idx += 1
        elif clicks_pct > 0:
            findings.append(MonitorFinding(
                id=f"P-{idx:03d}",
                type="traffic_gain",
                headline=f"Organic clicks increased by {clicks_pct}%",
                explanation=f"Organic search traffic grew {clicks_pct}% period-over-period from {prev_clicks} to {curr_clicks} clicks.",
                metrics_used=[{"snapshot_id": snapshot_id, "field": "clicks_change_pct", "value": clicks_pct}],
                recommended_action="Double down on top-performing search queries and refresh related internal linking hubs.",
                confidence=0.95
            ))
            idx += 1

        # 2. Striking distance query
        sd_queries = snapshot.get("striking_distance_queries", [])
        if sd_queries:
            top_sd = sd_queries[0]
            findings.append(MonitorFinding(
                id=f"P-{idx:03d}",
                type="striking_distance",
                headline=f"High-potential query '{top_sd['query']}' ranking at position {top_sd['position']}",
                explanation=f"The query '{top_sd['query']}' received {top_sd['impressions']} impressions while ranking on Page 2 (position {top_sd['position']}).",
                metrics_used=[{"snapshot_id": snapshot_id, "field": "striking_distance_queries.0.position", "value": top_sd['position']}],
                recommended_action="Enhance on-page content relevance and add targeted internal links with matching anchor text.",
                confidence=0.95
            ))
            idx += 1

        # 3. Low CTR query
        low_ctrs = snapshot.get("low_ctr_opportunities", [])
        if low_ctrs:
            top_ctr = low_ctrs[0]
            findings.append(MonitorFinding(
                id=f"P-{idx:03d}",
                type="low_ctr",
                headline=f"Sub-optimal CTR ({top_ctr['ctr']}%) on top-10 query '{top_ctr['query']}'",
                explanation=f"Query '{top_ctr['query']}' ranks at position {top_ctr['position']} with {top_ctr['impressions']} impressions but only achieves a {top_ctr['ctr']}% CTR.",
                metrics_used=[{"snapshot_id": snapshot_id, "field": "low_ctr_opportunities.0.ctr", "value": top_ctr['ctr']}],
                recommended_action="Rewrite SERP title and meta description to be more compelling and improve click engagement.",
                confidence=0.95
            ))
            idx += 1

        # 4. Declining page
        declining = snapshot.get("declining_pages", [])
        if declining:
            top_dec = declining[0]
            findings.append(MonitorFinding(
                id=f"P-{idx:03d}",
                type="declining_page",
                headline=f"Page traffic decline of {abs(top_dec['change_pct'])}% detected",
                explanation=f"URL '{top_dec['url']}' saw clicks drop {abs(top_dec['change_pct'])}% from {top_dec['previous_clicks']} to {top_dec['current_clicks']}.",
                metrics_used=[{"snapshot_id": snapshot_id, "field": "declining_pages.0.change_pct", "value": top_dec['change_pct']}],
                recommended_action="Audit content freshness, search intent shifts, and check whether competing pages have refreshed their content.",
                confidence=0.95
            ))
            idx += 1

        summary = (
            f"Over the last 90 days, organic search performance showed a {clicks_pct}% change in total clicks "
            f"with {curr_clicks} clicks recorded across {totals.get('impressions', 0)} impressions. "
            f"Average SERP position stood at {totals.get('avg_position', 0.0)}. "
            f"Key opportunities exist in striking-distance rankings and CTR snippet optimization."
        )

        return MonitorReport(summary=summary, findings=findings)

    @classmethod
    async def _run_with_single_model(
        cls,
        snapshot_id: str,
        snapshot: Dict[str, Any],
        model_name: str
    ) -> Tuple[MonitorReport, float, int, int]:
        prompt = f"""
        You are an elite SEO Monitor Agent. Explain the following computed performance metrics.
        Rules:
        - Never invent numbers or metrics. Every number you mention in text MUST come from the computed data.
        - Every finding must include metrics_used referencing snapshot_id '{snapshot_id}', field, and exact value.
        - Types allowed: traffic_drop, traffic_gain, striking_distance, low_ctr, declining_page.

        Computed Snapshot:
        {json.dumps(snapshot, indent=2)}

        Return JSON matching this schema:
        {{
          "summary": "4-6 sentences",
          "findings": [
            {{
              "id": "P-001",
              "type": "traffic_drop|traffic_gain|striking_distance|low_ctr|declining_page",
              "headline": "short headline",
              "explanation": "concise explanation",
              "metrics_used": [{{"snapshot_id": "{snapshot_id}", "field": "...", "value": 0.0}}],
              "recommended_action": "concrete next step",
              "confidence": 0.95
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
                        data = resp.json()
                        usage = data.get("usageMetadata", {})
                        prompt_tokens = usage.get("promptTokenCount", 0)
                        cand_tokens = usage.get("candidatesTokenCount", 0)
                        cost = (prompt_tokens * 0.000000075) + (cand_tokens * 0.00000030)
                        raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                        parsed = json.loads(raw_text)
                        return MonitorReport.model_validate(parsed), round(cost, 6), prompt_tokens, cand_tokens

                    error_snippet = resp.text[:200]
                    last_error = f"Gemini API HTTP {resp.status_code}: {error_snippet}"

                    if resp.status_code in (429, 503) and attempt_idx < max_attempts:
                        jitter = random.uniform(0.1, 1.0)
                        wait_time = base_delay + jitter
                        print(f"[{model_name}] MonitorAgent HTTP {resp.status_code} on attempt {attempt_idx}. Retrying in {wait_time:.1f}s...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        raise Exception(last_error)

                except (httpx.TimeoutException, httpx.NetworkError) as net_err:
                    last_error = f"Gemini connection error: {type(net_err).__name__} - {net_err}"
                    if attempt_idx < max_attempts:
                        jitter = random.uniform(0.1, 1.0)
                        wait_time = base_delay + jitter
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        raise Exception(last_error)

        raise Exception(last_error or f"[{model_name}] Monitor retries exhausted.")
