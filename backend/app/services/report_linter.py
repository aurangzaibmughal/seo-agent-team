from typing import List, Dict, Any, Optional
from app.services.pagespeed import check_metric_consistency

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
    section completeness, and platform alignment.
    """
    warnings: List[str] = []

    # 1. Section Completeness: Tech Issues vs Strategy Tasks
    if tech_issues and not strategy_tasks:
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
    if psi_results:
        expected_low_score = sum(1 for p in psi_results if (p.get("score") or p.get("performance_score") or 100) < 50)
        expected_slow_lcp = sum(1 for p in psi_results if (p.get("lcp_ms") or 0) > 4000)
        expected_poor_cls = sum(1 for p in psi_results if (p.get("cls") or 0) > 0.25)

        actual_low_score = sum(1 for i in tech_issues if i.get("type") == "low_performance_score")
        actual_slow_lcp = sum(1 for i in tech_issues if i.get("type") == "slow_lcp")
        actual_poor_cls = sum(1 for i in tech_issues if i.get("type") == "poor_cls")

        if actual_low_score != expected_low_score:
            warnings.append(
                f"QA Warning: Speed count mismatch for low_performance_score: issues table has {actual_low_score}, but PSI table has {expected_low_score}."
            )
        if actual_slow_lcp != expected_slow_lcp:
            warnings.append(
                f"QA Warning: Speed count mismatch for slow_lcp: issues table has {actual_slow_lcp}, but PSI table has {expected_slow_lcp}."
            )
        if actual_poor_cls != expected_poor_cls:
            warnings.append(
                f"QA Warning: Speed count mismatch for poor_cls: issues table has {actual_poor_cls}, but PSI table has {expected_poor_cls}."
            )

    # 4. Evidence completeness
    for iss in tech_issues:
        urls = iss.get("urls") or []
        if not urls:
            warnings.append(f"QA Warning: Issue {iss.get('id', 'unknown')} ({iss.get('type')}) has no affected URLs.")

    # 5. Platform consistency
    detected_plat = job.get("platform") or job.get("detected_platform")
    if detected_plat == "wordpress" and code_bundle:
        bundle_plat = str(code_bundle.get("platform", "")).lower()
        if bundle_plat == "nextjs":
            warnings.append("QA Warning: Target site is WordPress but code bundle targeted Next.js.")

    return warnings
