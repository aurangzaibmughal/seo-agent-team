import json
import asyncio
import random
import httpx
from typing import List, Dict, Any, Tuple, Optional
from app.core.config import settings
from app.models.agent_schemas import ResearchAgentReport, ResearchOpportunity

class ResearchAgent:
    """Research Agent: Transforms search analytics & crawl content gap data into prioritized opportunities."""

    @classmethod
    async def run(
        cls,
        snapshot_id: str,
        snapshot_data: Dict[str, Any],
        force_fallback: bool = False
    ) -> Tuple[ResearchAgentReport, str, float, Optional[str], Optional[str]]:
        """Returns (report, mode, cost_usd, failure_reason, model_used)."""
        if force_fallback:
            failure_reason = "Cost cap exceeded; deterministic fallback forced"
            report = cls._run_deterministic(snapshot_id, snapshot_data)
            return report, "fallback_cost_cap", 0.0, failure_reason, None

        if settings.GEMINI_API_KEY:
            models = settings.gemini_model_list
            errors_by_model = []
            for model_name in models:
                try:
                    report, cost, p_tokens, c_tokens = await cls._run_with_single_model(
                        snapshot_id, snapshot_data, model_name
                    )
                    report.tokens_prompt = p_tokens
                    report.tokens_completion = c_tokens
                    return report, "llm", cost, None, model_name
                except Exception as e:
                    err_msg = f"[{model_name}: {e}]"
                    print(f"ResearchAgent model {model_name} failed: {e}. Trying next...")
                    errors_by_model.append(err_msg)

            failure_reason = "All models failed -> " + "; ".join(errors_by_model)
        else:
            failure_reason = "GEMINI_API_KEY is not configured in .env"

        print(f"ResearchAgent falling back to deterministic synthesizer: {failure_reason}")
        report = cls._run_deterministic(snapshot_id, snapshot_data)
        return report, "fallback", 0.0, failure_reason, None

    @classmethod
    def _run_deterministic(cls, snapshot_id: str, data: Dict[str, Any]) -> ResearchAgentReport:
        opportunities: List[ResearchOpportunity] = []
        opp_idx = 1

        # 1. Content Gaps
        for gap in data.get("content_gaps", [])[:5]:
            head = gap.get("head_term", "")
            imp = gap.get("impressions", 0)
            opportunities.append(ResearchOpportunity(
                id=f"R-{opp_idx:03d}",
                type="gap",
                headline=f"Content Gap Opportunity: Target '{head}' ({imp} impressions)",
                explanation=f"The query cluster '{head}' generates {imp} organic impressions, but no existing page includes this term in its title or H1.",
                metrics_used=[
                    {"snapshot_id": snapshot_id, "field": "content_gaps.impressions", "value": float(imp)}
                ],
                confidence=0.95
            ))
            opp_idx += 1

        # 2. Cannibalization
        for cann in data.get("cannibalization", [])[:3]:
            q = cann.get("query", "")
            imp = cann.get("total_impressions", 0)
            u_count = cann.get("urls_count", 2)
            opportunities.append(ResearchOpportunity(
                id=f"R-{opp_idx:03d}",
                type="cannibalization",
                headline=f"Keyword Cannibalization: '{q}' split across {u_count} URLs",
                explanation=f"Query '{q}' with {imp} total impressions is being split across {u_count} distinct URLs, diluting authority.",
                metrics_used=[
                    {"snapshot_id": snapshot_id, "field": "cannibalization.total_impressions", "value": float(imp)},
                    {"snapshot_id": snapshot_id, "field": "cannibalization.urls_count", "value": float(u_count)}
                ],
                confidence=0.95
            ))
            opp_idx += 1

        # 3. Mismatch
        for mis in data.get("mismatch", [])[:3]:
            head = mis.get("head_term", "")
            imp = mis.get("impressions", 0)
            opportunities.append(ResearchOpportunity(
                id=f"R-{opp_idx:03d}",
                type="mismatch",
                headline=f"Search Intent Mismatch for '{head}'",
                explanation=f"Cluster '{head}' ({imp} impressions) lands on a page that lacks the keyword in its title or headings.",
                metrics_used=[
                    {"snapshot_id": snapshot_id, "field": "mismatch.impressions", "value": float(imp)}
                ],
                confidence=0.90
            ))
            opp_idx += 1

        # 4. Competitor Topics (if any)
        comp_data = data.get("competitor_comparison", {})
        for ct in comp_data.get("topics_competitors_cover", [])[:3]:
            comp = ct.get("competitor", "")
            top = ct.get("topic", "")
            opportunities.append(ResearchOpportunity(
                id=f"R-{opp_idx:03d}",
                type="competitor_topic",
                headline=f"Competitor Topic Gap: '{top}' (covered by {comp})",
                explanation=f"Competitor {comp} covers '{top}' in their on-page headings while this site does not. (On-page comparison only — no traffic or backlink data)",
                metrics_used=[],
                confidence=0.85
            ))
            opp_idx += 1

        # 5. Question Queries
        for qq in data.get("question_queries", [])[:3]:
            q = qq.get("query", "")
            imp = qq.get("impressions", 0)
            opportunities.append(ResearchOpportunity(
                id=f"R-{opp_idx:03d}",
                type="question",
                headline=f"User Query Intent: '{q}' ({imp} impressions)",
                explanation=f"Real user question '{q}' has {imp} impressions, representing prime informational brief opportunity.",
                metrics_used=[
                    {"snapshot_id": snapshot_id, "field": "question_queries.impressions", "value": float(imp)}
                ],
                confidence=0.95
            ))
            opp_idx += 1

        summary = (
            f"Research analysis evaluated {data.get('total_queries_analyzed', 0)} queries and identified "
            f"{len(opportunities)} strategic opportunities across content gaps, intent mismatches, keyword cannibalization, "
            f"and competitor on-page coverage. Addressing content gaps is recommended for priority organic reach."
        )

        return ResearchAgentReport(summary=summary, opportunities=opportunities)

    @classmethod
    async def _run_with_single_model(
        cls,
        snapshot_id: str,
        data: Dict[str, Any],
        model_name: str
    ) -> Tuple[ResearchAgentReport, float, int, int]:
        prompt = f"""
        You are an elite SEO Research Agent. Analyze the following validated keyword clusters and crawl research metrics.
        Rules:
        - NEVER invent search volume, keyword difficulty, or traffic forecasts.
        - You MUST cite the exact metrics_used array for every claim from the input snapshot data.
        - Produce prioritized strategic opportunities across gap, cannibalization, mismatch, competitor_topic, and question types.

        Research Metrics:
        {json.dumps(data, indent=2)[:4000]}

        Return JSON matching this schema:
        {{
          "summary": "3-5 sentences strategic overview",
          "opportunities": [
            {{
              "id": "R-001",
              "type": "gap|cannibalization|mismatch|competitor_topic|question",
              "headline": "Actionable headline",
              "explanation": "Clear SEO explanation citing real metrics",
              "metrics_used": [
                {{"snapshot_id": "{snapshot_id}", "field": "field_name", "value": 123.0}}
              ],
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
                        res_json = resp.json()
                        usage = res_json.get("usageMetadata", {})
                        p_tokens = usage.get("promptTokenCount", 0)
                        c_tokens = usage.get("candidatesTokenCount", 0)
                        cost = (p_tokens * 0.000000075) + (c_tokens * 0.00000030)

                        raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
                        parsed = json.loads(raw_text)
                        return ResearchAgentReport.model_validate(parsed), round(cost, 6), p_tokens, c_tokens

                    error_snippet = resp.text[:200]
                    last_error = f"Gemini API HTTP {resp.status_code}: {error_snippet}"

                    if resp.status_code in (429, 503) and attempt_idx < max_attempts:
                        jitter = random.uniform(0.1, 1.0)
                        wait_time = base_delay + jitter
                        print(f"[{model_name}] HTTP {resp.status_code} in ResearchAgent (attempt {attempt_idx}/{max_attempts}). Retrying in {wait_time:.1f}s...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        raise Exception(last_error)

                except (httpx.TimeoutException, httpx.NetworkError) as net_err:
                    last_error = f"Gemini API connection error: {type(net_err).__name__} - {net_err}"
                    if attempt_idx < max_attempts:
                        jitter = random.uniform(0.1, 1.0)
                        wait_time = base_delay + jitter
                        print(f"[{model_name}] Network error in ResearchAgent. Retrying in {wait_time:.1f}s...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        raise Exception(last_error)

        raise Exception(last_error or f"[{model_name}] Retries exhausted in ResearchAgent.")
