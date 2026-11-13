import json
import asyncio
import random
import httpx
from typing import List, Dict, Any, Tuple, Optional
from app.core.config import settings
from app.models.agent_schemas import TechnicalAgentReport, TechnicalIssue, DismissedCandidate

ISSUE_METADATA = {
    "broken_link_4xx": {
        "severity": "high",
        "effort": "low",
        "impact": "Broken 4xx links drain crawl budget, degrade user experience, and result in immediate loss of link equity.",
        "fix_hint": "Update the referencing source links to valid targets or implement 301 redirects to relevant live pages."
    },
    "server_error_5xx": {
        "severity": "high",
        "effort": "high",
        "impact": "5xx server errors prevent search engines from crawling content and cause rankings to drop drastically.",
        "fix_hint": "Check server error logs, backend application health, and database connection pools for unhandled crashes."
    },
    "sitemap_lists_non_existent_url": {
        "severity": "high",
        "effort": "low",
        "impact": "Sitemap declares URLs that return HTTP 404/5xx or are not crawlable, wasting search engine crawl budget and causing indexation dropouts.",
        "fix_hint": "Remove non-existent 404 URLs from sitemap or publish the missing pages."
    },
    "sitemap_missing": {
        "severity": "medium",
        "effort": "low",
        "impact": "Search engines cannot efficiently discover all indexable pages because no XML sitemap was found in robots.txt or standard paths.",
        "fix_hint": "Generate an XML sitemap and reference it in robots.txt via 'Sitemap: https://domain/sitemap.xml'."
    },
    "sitemap_unreadable": {
        "severity": "medium",
        "effort": "low",
        "impact": "XML sitemap returned HTTP 200 but contains invalid or malformed XML syntax, preventing search engines from parsing it.",
        "fix_hint": "Validate XML syntax against the sitemaps.org schema and ensure all special characters in URLs are properly escaped."
    },
    "crawled_page_missing_from_sitemap": {
        "severity": "medium",
        "effort": "low",
        "impact": "Crawled 200 indexable canonical pages are omitted from sitemap.xml, impairing search engine discovery and indexation.",
        "fix_hint": "Add all 200 OK indexable canonical pages to sitemap.xml or app/sitemap.ts."
    },
    "missing_title": {
        "severity": "high",
        "effort": "low",
        "impact": "Title tags are one of the strongest on-page ranking factors. Missing titles prevent search engines from understanding the page topic.",
        "fix_hint": "Add a unique, descriptive <title> tag between 30 and 60 characters containing primary keywords."
    },
    "missing_meta_description": {
        "severity": "medium",
        "effort": "low",
        "impact": "Meta descriptions directly influence organic Click-Through-Rate (CTR) from SERPs even though not a direct ranking signal.",
        "fix_hint": "Craft a persuasive meta description between 70 and 155 characters with a compelling call-to-action."
    },
    "missing_h1": {
        "severity": "medium",
        "effort": "low",
        "impact": "Missing H1 tags weaken document semantic hierarchy and topical relevance for primary target queries.",
        "fix_hint": "Add exactly one prominent H1 tag representing the primary topic of the page."
    },
    "missing_canonical": {
        "severity": "medium",
        "effort": "low",
        "impact": "Without canonical tags, search engines may index duplicate URL parameters or alternate protocols unintentionally.",
        "fix_hint": "Add a self-referential <link rel='canonical' href='...'> tag to establish indexing authority."
    },
    "canonical_to_other": {
        "severity": "medium",
        "effort": "low",
        "impact": "Page explicitly signals to search engines not to index itself, passing ranking equity to another canonical target.",
        "fix_hint": "Ensure canonical tags accurately reflect the preferred indexable URL. If this page is unique and intended to rank independently, make its canonical tag self-referential. Never remove self-referencing canonicals, as self-referential canonicals are an essential SEO best practice."
    },
    "canonical_mass_misconfiguration": {
        "severity": "high",
        "effort": "low",
        "impact": "Over 30% of crawled pages canonicalize to a single target URL (often the homepage), stripping ranking and indexation from unique pages across the website.",
        "fix_hint": "Correct site-wide template header to generate self-referential canonical tags for unique URLs instead of a global static canonical target."
    },
    "noindex_page": {
        "severity": "high",
        "effort": "low",
        "impact": "Important content page (home, service, blog, pricing) is blocked from search engine indexing by robots meta or X-Robots-Tag directive.",
        "fix_hint": "Remove 'noindex' directive from this content page to allow search engine indexing."
    },
    "indexable_admin_page": {
        "severity": "high",
        "effort": "low",
        "impact": "Administrative portal is indexable by search engines, exposing private gateway access in search results.",
        "fix_hint": "Add <meta name='robots' content='noindex, nofollow'> to protect administrative gateway from indexing."
    },
    "indexable_private_page": {
        "severity": "medium",
        "effort": "low",
        "impact": "Private or utility authentication page (login, signup, cart, account) is indexable by search engines, causing thin content in SERPs.",
        "fix_hint": "Add <meta name='robots' content='noindex, follow'> to prevent search indexing of utility and authentication forms."
    },
    "duplicate_title": {
        "severity": "medium",
        "effort": "medium",
        "impact": "Multiple pages with identical title tags cause keyword cannibalization and split indexing equity.",
        "fix_hint": "Rewrite title tags to reflect the unique value proposition of each distinct page."
    },
    "duplicate_meta_description": {
        "severity": "low",
        "effort": "medium",
        "impact": "Duplicate meta descriptions reduce SERP snippet diversity and lower click-through rates.",
        "fix_hint": "Customize snippet copy tailored to the unique intent of each page."
    },
    "title_borderline": {
        "severity": "low",
        "effort": "low",
        "impact": "Title is borderline long (61-65 characters) and may truncate on some mobile screens.",
        "fix_hint": "Consider tightening title to under 60 characters."
    },
    "title_too_long": {
        "severity": "low",
        "effort": "low",
        "impact": "Title exceeds 65 characters and will be truncated with an ellipsis in desktop and mobile SERPs.",
        "fix_hint": "Shorten title to between 30 and 60 characters while keeping important keywords at the beginning."
    },
    "title_too_short": {
        "severity": "low",
        "effort": "low",
        "impact": "Title under 30 characters fails to fully capitalize on keyword ranking opportunities.",
        "fix_hint": "Expand title to provide more topical context and secondary brand/intent keywords."
    },
    "meta_borderline": {
        "severity": "low",
        "effort": "low",
        "impact": "Meta description is borderline long (161-170 characters) and may truncate in search snippets.",
        "fix_hint": "Tighten meta description to under 155 characters."
    },
    "meta_too_long": {
        "severity": "low",
        "effort": "low",
        "impact": "Meta description exceeds 170 characters and will be cut off in search snippets.",
        "fix_hint": "Condense meta description to under 155 characters."
    },
    "orphan_page": {
        "severity": "medium",
        "effort": "medium",
        "impact": "Pages with 0 internal links are difficult for search engine bots to discover and receive minimal internal PageRank.",
        "fix_hint": "Add contextual internal links from relevant parent or topically related pages."
    },
    "redirect_chain": {
        "severity": "medium",
        "effort": "low",
        "impact": "Redirects slow down page loading and consume crawl budget.",
        "fix_hint": "Update internal links to point directly to the destination URL."
    },
    "low_performance_score": {
        "severity": "high",
        "effort": "high",
        "impact": "Lighthouse performance score below 50 negatively impacts Core Web Vitals and organic rankings.",
        "fix_hint": "Optimize render-blocking resources, defer non-critical JS, and leverage modern image formats."
    },
    "slow_lcp": {
        "severity": "high",
        "effort": "high",
        "impact": "Largest Contentful Paint above 2.5s fails Google's Core Web Vitals threshold, directly penalizing mobile ranking.",
        "fix_hint": "Preload hero images, optimize server response times (TTFB), and implement CDN caching."
    },
    "poor_cls": {
        "severity": "medium",
        "effort": "medium",
        "impact": "Cumulative Layout Shift above 0.1 creates visual instability for users during page load.",
        "fix_hint": "Specify explicit width and height attributes on images/videos and avoid injecting dynamic DOM elements above the fold."
    },
    "brand_repeated_in_title": {
        "severity": "medium",
        "effort": "low",
        "impact": "Brand name is repeated 2 or more times in the title tag, creating redundant snippets in search results.",
        "fix_hint": "If the layout adds a brand suffix via a title template, remove the brand from this page's own title."
    }
}

CANONICAL_TO_OTHER_FIX_HINT = (
    "Ensure canonical tags accurately reflect the preferred indexable URL. If this page is unique and "
    "intended to rank independently, make its canonical tag self-referential. Never remove self-referencing "
    "canonicals, as self-referential canonicals are an essential SEO best practice."
)

# Canonical severity lookup matching the exact rule names produced by issue_rules.py
DETERMINISTIC_SEVERITY_TABLE: Dict[str, str] = {
    # High base severity
    "server_error_5xx": "high",
    "broken_link_4xx": "high",
    "canonical_mass_misconfiguration": "high",
    "missing_title": "high",
    "low_performance_score": "high",
    "slow_lcp": "high",
    "noindex_page": "high",
    "indexable_admin_page": "high",

    # Medium base severity
    "redirect_chain": "medium",
    "canonical_to_other": "medium",
    "indexable_private_page": "medium",
    "missing_canonical": "medium",
    "duplicate_title": "medium",
    "missing_h1": "medium",
    "poor_cls": "medium",
    "orphan_page": "medium",
    "brand_repeated_in_title": "medium",
    "sitemap_lists_non_existent_url": "medium",
    "sitemap_missing": "medium",
    "sitemap_unreadable": "medium",
    "crawled_page_missing_from_sitemap": "medium",

    # Low base severity
    "title_borderline": "low",
    "title_too_long": "low",
    "title_too_short": "low",
    "missing_meta_description": "low",
    "meta_borderline": "low",
    "meta_too_long": "low",
    "duplicate_meta_description": "low",
}

def get_deterministic_severity(issue_type: str, url_count: int = 1, total_pages: int = 1) -> str:
    """Computes deterministic severity based on the exact rule names from issue_rules.py and scale."""
    base = DETERMINISTIC_SEVERITY_TABLE.get(issue_type, "low")
    ratio = (url_count / total_pages) if total_pages > 0 else 0

    if base == "high":
        return "high"

    if base == "medium":
        # Escalate to high if scale is significant
        if issue_type == "sitemap_lists_non_existent_url":
            return "high" if url_count >= 5 else "medium"
        if issue_type == "crawled_page_missing_from_sitemap":
            return "medium"
        if issue_type == "brand_repeated_in_title" and ratio >= 0.30:
            return "high"
        if issue_type in ("duplicate_title", "missing_h1") and (url_count >= 3 or ratio >= 0.15):
            return "high"
        if issue_type == "canonical_to_other" and (url_count >= 5 or ratio >= 0.20):
            return "high"
        if url_count >= 10 or ratio >= 0.25:
            return "high"
        return "medium"

    if base == "low":
        # Escalate to medium if widespread
        if issue_type == "duplicate_meta_description" and (url_count >= 3 or ratio >= 0.15):
            return "medium"
        if url_count >= 10 or ratio >= 0.25:
            return "medium"
        return "low"

    return base

class TechnicalAgent:
    @classmethod
    async def run(
        cls,
        candidates: List[Dict[str, Any]],
        force_fallback: bool = False
    ) -> Tuple[TechnicalAgentReport, str, float, Optional[str], Optional[str]]:
        """Returns (report, mode, cost_usd, failure_reason, model_used). Mode is 'llm' or 'fallback'."""
        if not candidates:
            return TechnicalAgentReport(
                issues=[],
                summary="No technical SEO issues were identified in the crawl or performance audit."
            ), "fallback", 0.0, None, None

        # Ensure all candidates have stable IDs
        for idx, c in enumerate(candidates, start=1):
            if "id" not in c:
                c["id"] = f"C-{idx:03d}"

        if not force_fallback and settings.GEMINI_API_KEY:
            models = settings.gemini_model_list
            errors_by_model = []
            for model_name in models:
                try:
                    report, cost, p_tokens, c_tokens = await cls._run_with_single_model(candidates, model_name)
                    report.tokens_prompt = p_tokens
                    report.tokens_completion = c_tokens
                    return report, "llm", cost, None, model_name
                except Exception as e:
                    err_msg = f"[{model_name}: {e}]"
                    print(f"Model {model_name} failed in fallback chain: {e}. Trying next model...")
                    errors_by_model.append(err_msg)

            failure_reason = "All models in fallback chain failed -> " + "; ".join(errors_by_model)
        elif force_fallback:
            failure_reason = "Cost cap reached; deterministic fallback invoked."
        else:
            failure_reason = "GEMINI_API_KEY is not configured in .env"

        mode = "fallback_cost_cap" if force_fallback else "fallback"
        print(f"TechnicalAgent falling back to deterministic synthesizer: {failure_reason}")
        report = cls._run_deterministic(candidates)
        return report, mode, 0.0, failure_reason, None

    @classmethod
    def _run_deterministic(cls, candidates: List[Dict[str, Any]]) -> TechnicalAgentReport:
        grouped: Dict[str, Dict[str, Any]] = {}
        for c in candidates:
            itype = c["type"]
            cid = c.get("id")
            if itype not in grouped:
                meta = ISSUE_METADATA.get(itype, {
                    "severity": "medium",
                    "effort": "medium",
                    "impact": f"Detected issue of type {itype}.",
                    "fix_hint": "Review and correct according to SEO best practices."
                })
                grouped[itype] = {
                    "type": itype,
                    "severity": meta["severity"],
                    "effort": meta["effort"],
                    "impact": meta["impact"],
                    "fix_hint": meta["fix_hint"],
                    "urls": set(),
                    "evidence": [],
                    "candidate_ids": set()
                }
            if cid:
                grouped[itype]["candidate_ids"].add(cid)
            for u in c.get("urls", []):
                grouped[itype]["urls"].add(u)
            for ev in c.get("evidence", []):
                if ev not in grouped[itype]["evidence"]:
                    grouped[itype]["evidence"].append(ev)

        severity_order = {"high": 0, "medium": 1, "low": 2}
        sorted_groups = sorted(
            grouped.values(),
            key=lambda x: severity_order.get(x["severity"], 3)
        )

        issues: List[TechnicalIssue] = []
        for idx, g in enumerate(sorted_groups, start=1):
            itype = g["type"]
            sev = get_deterministic_severity(itype, len(g["urls"]), len(candidates))
            hint = CANONICAL_TO_OTHER_FIX_HINT if itype == "canonical_to_other" else g["fix_hint"]
            impact_text = g["impact"]
            if itype == "broken_link_4xx":
                dym = next((c.get("did_you_mean") for c in candidates if c.get("type") == "broken_link_4xx" and c.get("did_you_mean")), None)
                if dym:
                    hint = f"{hint.rstrip('.')} Did you mean {dym}?"
                    impact_text = f"{impact_text.rstrip('.')} Did you mean {dym}?"

            issues.append(TechnicalIssue(
                id=f"T-{idx:03d}",
                type=itype,
                severity=sev,
                impact=impact_text,
                effort=g["effort"],
                urls=sorted(list(g["urls"])),
                evidence=g["evidence"],
                fix_hint=hint,
                confidence=0.95,
                candidate_ids=sorted(list(g["candidate_ids"])),
                source="fallback_rule"
            ))

        high_count = sum(1 for i in issues if i.severity == "high")
        med_count = sum(1 for i in issues if i.severity == "medium")
        low_count = sum(1 for i in issues if i.severity == "low")
        summary = (
            f"The Technical Agent identified {len(issues)} distinct categories of technical SEO issues across "
            f"the crawled pages, comprising {high_count} high-severity, {med_count} medium-severity, and "
            f"{low_count} low-severity items. Immediate focus should be placed on high-priority items such as "
            f"broken links and Core Web Vitals to prevent organic traffic deterioration."
        )

        return TechnicalAgentReport(issues=issues, summary=summary)

    @classmethod
    async def _run_with_single_model(cls, candidates: List[Dict[str, Any]], model_name: str) -> Tuple[TechnicalAgentReport, float, int, int]:
        cand_map = {c["id"]: c for c in candidates}

        # Provide candidate IDs, types, and URLs to the LLM. LLM does NOT get or write raw evidence dictionaries.
        candidates_input = [
            {
                "id": c["id"],
                "type": c["type"],
                "urls": c.get("urls", [])
            }
            for c in candidates
        ]

        prompt = f"""
        You are an elite Technical SEO Agent. Analyze the following detected technical SEO issue candidates.
        Rules:
        - Contract Rule: Return ONLY candidate_ids (from input), severity, effort, impact, and fix_hint.
        - You MUST NOT write evidence or URLs. Code will attach authoritative database evidence and URLs from the referenced candidates.
        - Every candidate MUST either be included in an issue under candidate_ids OR listed under dismissed with a valid reason. Do NOT drop any candidate!
        - You may group candidates of the same issue type together under one issue by including their IDs in candidate_ids.
        - Prioritize by severity (high, medium, low) and effort (low, medium, high).
        - Provide a concise, high-impact explanation and a clear, developer-ready fix hint.

        Issue Candidates:
        {json.dumps(candidates_input[:100], indent=2)}

        Return JSON matching this exact schema:
        {{
          "issues": [
            {{
              "id": "T-001",
              "type": "issue_type",
              "candidate_ids": ["C-001", "C-002"],
              "severity": "high|medium|low",
              "effort": "low|medium|high",
              "impact": "SEO explanation of impact",
              "fix_hint": "Concrete developer fix hint",
              "confidence": 0.95
            }}
          ],
          "dismissed": [
            {{
              "candidate_ids": ["C-005"],
              "reason": "Concrete explanation for dismissal"
            }}
          ],
          "summary": "3-5 sentences"
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

                        # Code attaches evidence and URLs from candidates
                        mapped_issues: List[TechnicalIssue] = []
                        for iss_dict in parsed.get("issues", []):
                            raw_cids = iss_dict.get("candidate_ids", [])
                            valid_cids = [cid for cid in raw_cids if cid in cand_map]
                            if not valid_cids:
                                # Fallback: if LLM didn't return candidate_ids but matched by type
                                fallback_type = iss_dict.get("type")
                                valid_cids = [c["id"] for c in candidates if c.get("type") == fallback_type]

                            agg_urls = []
                            agg_evidence = []
                            types = []
                            for cid in valid_cids:
                                c = cand_map[cid]
                                types.append(c.get("type", "unknown"))
                                for u in c.get("urls", []):
                                    if u not in agg_urls:
                                        agg_urls.append(u)
                                for ev in c.get("evidence", []):
                                    if ev not in agg_evidence:
                                        agg_evidence.append(ev)

                            itype = iss_dict.get("type") or (types[0] if types else "technical_issue")
                            if itype not in ISSUE_METADATA and types:
                                itype = types[0]

                            sev = get_deterministic_severity(itype, len(agg_urls), len(candidates))
                            hint = CANONICAL_TO_OTHER_FIX_HINT if itype == "canonical_to_other" else (iss_dict.get("fix_hint") or ISSUE_METADATA.get(itype, {}).get("fix_hint", "Review and fix."))
                            impact_text = iss_dict.get("impact") or ISSUE_METADATA.get(itype, {}).get("impact", "SEO issue identified.")
                            if itype == "broken_link_4xx":
                                dym = next((cand_map[cid].get("did_you_mean") for cid in valid_cids if cand_map.get(cid, {}).get("did_you_mean")), None)
                                if dym:
                                    hint = f"{hint.rstrip('.')} Did you mean {dym}?"
                                    impact_text = f"{impact_text.rstrip('.')} Did you mean {dym}?"

                            mapped_issues.append(TechnicalIssue(
                                id=iss_dict.get("id", f"T-{len(mapped_issues)+1:03d}"),
                                type=itype,
                                severity=sev,
                                effort=iss_dict.get("effort", "medium"),
                                impact=impact_text,
                                fix_hint=hint,
                                confidence=iss_dict.get("confidence", 0.95),
                                urls=agg_urls,
                                evidence=agg_evidence,
                                candidate_ids=valid_cids,
                                source="llm"
                            ))

                        mapped_dismissed: List[DismissedCandidate] = []
                        for dis_dict in parsed.get("dismissed", []):
                            raw_cids = dis_dict.get("candidate_ids", [])
                            valid_cids = [cid for cid in raw_cids if cid in cand_map]
                            agg_urls = []
                            types = []
                            for cid in valid_cids:
                                c = cand_map[cid]
                                types.append(c.get("type", "unknown"))
                                for u in c.get("urls", []):
                                    if u not in agg_urls:
                                        agg_urls.append(u)

                            mapped_dismissed.append(DismissedCandidate(
                                candidate_ids=valid_cids,
                                type=types[0] if types else dis_dict.get("type", "unknown"),
                                urls=agg_urls,
                                reason=dis_dict.get("reason", "Dismissed by LLM")
                            ))

                        report = TechnicalAgentReport(
                            issues=mapped_issues,
                            dismissed=mapped_dismissed,
                            summary=parsed.get("summary", "Technical audit completed.")
                        )
                        return report, round(cost, 6), prompt_tokens, cand_tokens

                    error_snippet = resp.text[:200]
                    last_error = f"Gemini API HTTP {resp.status_code}: {error_snippet}"

                    # For 429 and 503, retry with backoff and jitter
                    if resp.status_code in (429, 503) and attempt_idx < max_attempts:
                        jitter = random.uniform(0.1, 1.0)
                        wait_time = base_delay + jitter
                        print(f"[{model_name}] HTTP {resp.status_code} on attempt {attempt_idx}/{max_attempts}. Retrying in {wait_time:.1f}s...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        raise Exception(last_error)

                except (httpx.TimeoutException, httpx.NetworkError) as net_err:
                    last_error = f"Gemini API connection error: {type(net_err).__name__} - {net_err}"
                    if attempt_idx < max_attempts:
                        jitter = random.uniform(0.1, 1.0)
                        wait_time = base_delay + jitter
                        print(f"[{model_name}] Network/timeout error on attempt {attempt_idx}/{max_attempts}. Retrying in {wait_time:.1f}s...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        raise Exception(last_error)

        raise Exception(last_error or f"[{model_name}] All retries exhausted.")
