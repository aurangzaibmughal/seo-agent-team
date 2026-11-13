from typing import List, Dict, Any, Optional

def lint_audit_report(
    job: Dict[str, Any],
    tech_issues: List[Dict[str, Any]],
    strategy_tasks: List[Dict[str, Any]],
    rewrites: List[Dict[str, Any]],
    psi_results: List[Dict[str, Any]],
    code_bundle: Optional[Dict[str, Any]] = None
) -> List[str]:
    """Pre-export QA lint gate for SEO Audit Reports.
    Checks evidence completeness, metric plausibility, section completeness,
    and platform alignment.
    """
    warnings: List[str] = []

    # 1. Section Completeness: Tech Issues vs Strategy Tasks
    if tech_issues and not strategy_tasks:
        warnings.append("QA Warning: 30-day action plan has 0 strategy tasks despite verified technical issues.")

    # 2. Metric Plausibility (PageSpeed & CWV)
    for res in psi_results:
        score = res.get("score")
        lcp_ms = res.get("lcp_ms")
        if score is not None and lcp_ms is not None:
            if lcp_ms > 4000 and score > 80:
                warnings.append(
                    f"QA Warning: PageSpeed score ({score}) is implausibly high for poor LCP ({lcp_ms}ms) on {res.get('url')}."
                )

    # 3. Evidence completeness
    for iss in tech_issues:
        urls = iss.get("urls") or []
        if not urls:
            warnings.append(f"QA Warning: Issue {iss.get('id', 'unknown')} ({iss.get('type')}) has no affected URLs.")

    # 4. Platform consistency
    detected_plat = job.get("platform") or job.get("detected_platform")
    if detected_plat == "wordpress" and code_bundle:
        bundle_plat = str(code_bundle.get("platform", "")).lower()
        if bundle_plat == "nextjs":
            warnings.append("QA Warning: Target site is WordPress but code bundle targeted Next.js.")

    return warnings
