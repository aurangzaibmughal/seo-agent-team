import json
from typing import List, Dict, Any, Optional
from app.services.pagespeed import check_metric_consistency
from app.crawler.url_utils import canonical_url_key

class ReportLintGateError(Exception):
    """Raised when an audit report fails pre-export QA lint gate invariants."""
    def __init__(self, warnings: List[str]):
        self.warnings = warnings
        super().__init__(f"Report QA Lint Gate failed with {len(warnings)} issue(s): {', '.join(warnings[:3])}")

def lint_audit_report(
    job: Dict[str, Any],
    tech_issues: List[Dict[str, Any]],
    strategy_tasks: List[Dict[str, Any]],
    rewrites: List[Dict[str, Any]],
    psi_results: List[Dict[str, Any]],
    code_bundle: Optional[Dict[str, Any]] = None
) -> List[str]:
    """Pre-export QA lint gate for SEO Audit Reports.
    Checks evidence completeness, metric plausibility, speed issue count consistency,
    source-table presence, section completeness, and platform alignment.
    """
    warnings: List[str] = []

    # 1. Section Completeness: Tech Issues vs Strategy Tasks
    if not strategy_tasks:
        warnings.append("QA Warning: 30-day action plan has 0 strategy tasks.")
    elif tech_issues and not strategy_tasks:
        warnings.append("QA Warning: 30-day action plan has 0 strategy tasks despite verified technical issues.")

    # 2. Metric Plausibility (PageSpeed & Core Web Vitals)
    for res in psi_results:
        score = res.get("score") if res.get("score") is not None else res.get("performance_score")
        lcp_ms = res.get("lcp_ms")
        cls = res.get("cls")
        if score is not None:
            consistency = check_metric_consistency(score, lcp_ms, cls)
            if not consistency.get("is_consistent", True):
                warnings.append(
                    f"QA Warning: Implausible metric on {res.get('url')} - {consistency.get('reason')}"
                )

    # 3. Speed Issue Count derived from dataset vs PSI table
    psi_urls_norm = {canonical_url_key(p.get("url", "")) for p in psi_results if p.get("url")}
    if psi_results:
        expected_low_score_urls = {canonical_url_key(p.get("url", "")) for p in psi_results if (p.get("score") or p.get("performance_score") or 100) < 50}
        expected_slow_lcp_urls = {canonical_url_key(p.get("url", "")) for p in psi_results if (p.get("lcp_ms") or 0) > 4000}
        expected_poor_cls_urls = {canonical_url_key(p.get("url", "")) for p in psi_results if (p.get("cls") or 0) > 0.25}

        actual_low_score_urls = {canonical_url_key(u) for i in tech_issues if i.get("type") == "low_performance_score" for u in i.get("urls", [])}
        actual_slow_lcp_urls = {canonical_url_key(u) for i in tech_issues if i.get("type") == "slow_lcp" for u in i.get("urls", [])}
        actual_poor_cls_urls = {canonical_url_key(u) for i in tech_issues if i.get("type") == "poor_cls" for u in i.get("urls", [])}

        if actual_low_score_urls != expected_low_score_urls:
            warnings.append(
                f"QA Warning: Speed count mismatch for low_performance_score: issues table has {len(actual_low_score_urls)}, but PSI table has {len(expected_low_score_urls)}."
            )
        if actual_slow_lcp_urls != expected_slow_lcp_urls:
            warnings.append(
                f"QA Warning: Speed count mismatch for slow_lcp: issues table has {len(actual_slow_lcp_urls)}, but PSI table has {len(expected_slow_lcp_urls)}."
            )
        if actual_poor_cls_urls != expected_poor_cls_urls:
            warnings.append(
                f"QA Warning: Speed count mismatch for poor_cls: issues table has {len(actual_poor_cls_urls)}, but PSI table has {len(expected_poor_cls_urls)}."
            )

    # Source-Table Invariant: every finding must have an entry in its source table
    for iss in tech_issues:
        i_type = iss.get("type", "")
        if i_type in ("slow_lcp", "poor_cls", "low_performance_score"):
            for u in iss.get("urls", []):
                if u and canonical_url_key(u) not in psi_urls_norm:
                    warnings.append(
                        f"QA Warning: Finding {iss.get('id', 'unknown')} ({i_type}) cites URL {u} which has no entry in the PageSpeed source table."
                    )

    # 4. Evidence completeness
    for iss in tech_issues:
        urls = iss.get("urls") or []
        if not urls:
            warnings.append(f"QA Warning: Issue {iss.get('id', 'unknown')} ({iss.get('type')}) has no affected URLs.")

    # 5. Code Bundle Completeness
    if tech_issues:
        artifacts = (code_bundle.get("artifacts", []) if code_bundle else [])
        if not artifacts:
            warnings.append("QA Warning: 0 code artifacts generated despite verified technical issues.")

    # 6. Platform consistency
    detected_plat = job.get("platform") or job.get("detected_platform")
    if detected_plat == "wordpress" and code_bundle:
        bundle_plat = str(code_bundle.get("platform", "")).lower()
        if bundle_plat == "nextjs":
            warnings.append("QA Warning: Target site is WordPress but code bundle targeted Next.js.")

    # 7. Sitemap crawl numbers consistency cross-check
    sitemap_entries = []
    if job.get("sitemap_entries_json"):
        try:
            sitemap_entries = json.loads(job["sitemap_entries_json"])
        except Exception:
            sitemap_entries = []
    if sitemap_entries:
        s_count = len(sitemap_entries)
        in_sitemap_not_crawled = job.get("in_sitemap_not_crawled")
        crawled_not_in_sitemap = job.get("crawled_not_in_sitemap")
        pages_crawled = job.get("pages_crawled")
        if in_sitemap_not_crawled is not None and pages_crawled is not None and crawled_not_in_sitemap is not None:
            crawled_overlap = pages_crawled - crawled_not_in_sitemap
            if crawled_overlap < 0 or (in_sitemap_not_crawled + crawled_overlap) != s_count:
                warnings.append(
                    f"QA Warning: Sitemap crawl numbers inconsistent: {s_count} sitemap URLs, {in_sitemap_not_crawled} not crawled, {pages_crawled} crawled ({crawled_not_in_sitemap} not in sitemap)."
                )

    return warnings
