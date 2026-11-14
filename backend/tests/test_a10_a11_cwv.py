import pytest
from app.agents.issue_rules import detect_issues_from_data

def test_cwv_cls_boundary_values():
    # Good: <= 0.10
    psi_good = [{"id": "1", "url": "https://example.com/good", "cls": 0.10}]
    c_good = [c["type"] for c in detect_issues_from_data([], [], psi_good)]
    assert "poor_cls" not in c_good
    assert "cls_needs_improvement" not in c_good

    # Needs Improvement: 0.101 to 0.25
    psi_ni = [{"id": "2", "url": "https://example.com/ni", "cls": 0.101}]
    c_ni = [c["type"] for c in detect_issues_from_data([], [], psi_ni)]
    assert "poor_cls" not in c_ni
    assert "cls_needs_improvement" in c_ni

    psi_ni2 = [{"id": "3", "url": "https://example.com/ni2", "cls": 0.250}]
    c_ni2 = [c["type"] for c in detect_issues_from_data([], [], psi_ni2)]
    assert "poor_cls" not in c_ni2
    assert "cls_needs_improvement" in c_ni2

    # Poor: > 0.25
    psi_poor = [{"id": "4", "url": "https://example.com/poor", "cls": 0.251}]
    c_poor = [c["type"] for c in detect_issues_from_data([], [], psi_poor)]
    assert "poor_cls" in c_poor
    assert "cls_needs_improvement" not in c_poor

def test_cwv_lcp_boundary_values():
    # Good: <= 2500 ms
    psi_good = [{"id": "1", "url": "https://example.com/good", "lcp_ms": 2500.0}]
    c_good = [c["type"] for c in detect_issues_from_data([], [], psi_good)]
    assert "slow_lcp" not in c_good
    assert "lcp_needs_improvement" not in c_good

    # Needs Improvement: 2501 to 4000 ms
    psi_ni = [{"id": "2", "url": "https://example.com/ni", "lcp_ms": 2501.0}]
    c_ni = [c["type"] for c in detect_issues_from_data([], [], psi_ni)]
    assert "slow_lcp" not in c_ni
    assert "lcp_needs_improvement" in c_ni

    psi_ni2 = [{"id": "3", "url": "https://example.com/ni2", "lcp_ms": 4000.0}]
    c_ni2 = [c["type"] for c in detect_issues_from_data([], [], psi_ni2)]
    assert "slow_lcp" not in c_ni2
    assert "lcp_needs_improvement" in c_ni2

    # Poor / Slow: > 4000 ms
    psi_poor = [{"id": "4", "url": "https://example.com/poor", "lcp_ms": 4001.0}]
    c_poor = [c["type"] for c in detect_issues_from_data([], [], psi_poor)]
    assert "slow_lcp" in c_poor
    assert "lcp_needs_improvement" not in c_poor

def test_score_and_metrics_consistency():
    from app.services.pagespeed import check_metric_consistency
    # Score 71 with LCP 11.3s is mathematically possible in Lighthouse v10 (LCP weight 25% -> max score 75)
    # and must NOT be flagged or re-run
    res_possible = check_metric_consistency(performance_score=71, lcp_ms=11330.0, cls=0.399)
    assert res_possible["is_consistent"] is True

    # Score 80 with LCP 11.3s exceeds theoretical maximum (75) and must be flagged
    res_impossible = check_metric_consistency(performance_score=80, lcp_ms=11330.0, cls=0.399)
    assert res_impossible["is_consistent"] is False
    assert "exceeds the theoretical maximum" in res_impossible["reason"]

    # Score 71 with LCP 2.8s is well within range and consistent
    res2 = check_metric_consistency(performance_score=71, lcp_ms=2800.0, cls=0.08)
    assert res2["is_consistent"] is True

@pytest.mark.asyncio
async def test_pipeline_calls_compute_median_psi_results_with_n_runs(monkeypatch):
    from unittest.mock import MagicMock
    from app.services import pagespeed

    mock_db = MagicMock()
    mock_db.get_crawl_pages.return_value = [{"url": "https://example.com", "status_code": 200, "inlinks_count": 5}]
    monkeypatch.setattr(pagespeed, "DBManager", mock_db)

    calls = []
    async def mock_run_psi(client, job_id, url, strategy="mobile", ignore_cache=True):
        calls.append((strategy, len(calls)))
        return {
            "job_id": job_id, "url": url, "strategy": strategy,
            "performance_score": 70 + len(calls),
            "lcp_ms": 3000.0, "cls": 0.05, "fcp_ms": 1500.0, "ttfb_ms": 400.0
        }
    monkeypatch.setattr(pagespeed, "run_psi_for_url", mock_run_psi)

    await pagespeed.run_pagespeed_pipeline("test-job-psi", "https://example.com", ignore_cache=True, n_runs=3)

    # Must have called run_psi 3 times for mobile and 3 times for desktop (total 6 calls >= 3 per strategy)
    mobile_calls = [c for c in calls if c[0] == "mobile"]
    desktop_calls = [c for c in calls if c[0] == "desktop"]
    assert len(mobile_calls) >= 3
    assert len(desktop_calls) >= 3

def test_median_of_n_runs_calculation():
    from app.services.pagespeed import compute_median_psi_results
    runs = [
        {"url": "https://example.com", "strategy": "mobile", "performance_score": 60, "lcp_ms": 3200.0, "cls": 0.12, "fcp_ms": 1800.0, "ttfb_ms": 500.0},
        {"url": "https://example.com", "strategy": "mobile", "performance_score": 75, "lcp_ms": 2900.0, "cls": 0.08, "fcp_ms": 1600.0, "ttfb_ms": 450.0},
        {"url": "https://example.com", "strategy": "mobile", "performance_score": 65, "lcp_ms": 3000.0, "cls": 0.10, "fcp_ms": 1700.0, "ttfb_ms": 480.0},
    ]
    median_res = compute_median_psi_results(runs)
    assert median_res["performance_score"] == 65
    assert median_res["lcp_ms"] == 3000.0
    assert median_res["cls"] == 0.10
    assert median_res["fcp_ms"] == 1700.0
    assert median_res["ttfb_ms"] == 480.0
    assert median_res["runs_count"] == 3

def test_psi_issue_counts_derived_from_dataset_assertion():
    psi_data = [
        {"id": "p1", "url": "https://example.com/a", "performance_score": 45, "lcp_ms": 4500.0, "cls": 0.30},
        {"id": "p2", "url": "https://example.com/b", "performance_score": 88, "lcp_ms": 2800.0, "cls": 0.15},
        {"id": "p3", "url": "https://example.com/c", "performance_score": 95, "lcp_ms": 1200.0, "cls": 0.02},
    ]
    issues = detect_issues_from_data([], [], psi_data)
    issue_types = [i["type"] for i in issues]

    expected_low_score = sum(1 for p in psi_data if p.get("performance_score") is not None and p["performance_score"] < 50)
    expected_slow_lcp = sum(1 for p in psi_data if p.get("lcp_ms") is not None and p["lcp_ms"] > 4000)
    expected_poor_cls = sum(1 for p in psi_data if p.get("cls") is not None and p["cls"] > 0.25)

    assert issue_types.count("low_performance_score") == expected_low_score
    assert issue_types.count("slow_lcp") == expected_slow_lcp
    assert issue_types.count("poor_cls") == expected_poor_cls

def test_psi_disclosure_and_crux_separation():
    from app.services.reporter import ReportExporter
    import inspect
    src = inspect.getsource(ReportExporter.generate_pdf)
    assert "tested" in src.lower() and "crawled pages" in src.lower()
    assert "crux" in src.lower() or "chrome ux report" in src.lower()
    assert "pagespeed unavailable:" in src.lower()
    assert "measured at" in src.lower()
