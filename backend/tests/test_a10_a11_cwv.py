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
    # LCP 11.3s with score 71 is inconsistent!
    res = check_metric_consistency(performance_score=71, lcp_ms=11330.0, cls=0.399)
    assert res["is_consistent"] is False
    assert "inconsistent" in res["reason"].lower()

    # Score 71 with LCP 2.8s is consistent
    res2 = check_metric_consistency(performance_score=71, lcp_ms=2800.0, cls=0.08)
    assert res2["is_consistent"] is True
