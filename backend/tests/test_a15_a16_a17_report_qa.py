from pathlib import Path
from app.services.report_linter import lint_audit_report
from app.services.reporter import ReportExporter

def test_a16_lint_gate_failure_empty_strategy_tasks():
    issues = [{"id": "T-001", "type": "missing_canonical", "severity": "high", "urls": ["https://example.com/test"]}]
    warnings = lint_audit_report(
        job={"id": "job1", "pages_crawled": 5},
        tech_issues=issues,
        strategy_tasks=[],  # Empty tasks
        rewrites=[],
        psi_results=[],
    )
    assert any("30-day action plan has 0 strategy tasks" in w for w in warnings)

def test_a16_lint_gate_failure_implausible_metric_score_exceeds_max():
    # Score 80 with LCP 11.3s is impossible (max 75)
    psi_bad = [{"url": "https://example.com/", "score": 80, "lcp_ms": 11330.0, "cls": 0.05}]
    warnings = lint_audit_report(
        job={"id": "job1"},
        tech_issues=[],
        strategy_tasks=[],
        rewrites=[],
        psi_results=psi_bad,
    )
    assert any("Implausible metric" in w for w in warnings)

def test_a16_lint_gate_failure_speed_count_mismatch_vs_table():
    # Table has 1 poor LCP, but tech issues list has 0 slow_lcp issues
    psi_table = [{"url": "https://example.com/", "score": 40, "lcp_ms": 5000.0, "cls": 0.35}]
    warnings = lint_audit_report(
        job={"id": "job1"},
        tech_issues=[],  # Missing slow_lcp, poor_cls, low_performance_score
        strategy_tasks=[],
        rewrites=[],
        psi_results=psi_table,
    )
    assert any("Speed count mismatch" in w for w in warnings)

def test_a16_lint_gate_failure_missing_evidence_urls():
    issues = [{"id": "T-002", "type": "duplicate_title", "severity": "medium", "urls": []}]
    warnings = lint_audit_report(
        job={"id": "job1"},
        tech_issues=issues,
        strategy_tasks=[],
        rewrites=[],
        psi_results=[],
    )
    assert any("has no affected URLs" in w for w in warnings)

def test_a16_lint_gate_failure_platform_mismatch():
    warnings = lint_audit_report(
        job={"id": "job1", "platform": "wordpress"},
        tech_issues=[],
        strategy_tasks=[],
        rewrites=[],
        psi_results=[],
        code_bundle={"platform": "nextjs"}
    )
    assert any("Target site is WordPress but code bundle targeted Next.js" in w for w in warnings)

def test_a15_crawl_notice_lists_dropped_pages_with_reasons(monkeypatch):
    from unittest.mock import MagicMock
    from app.services import reporter
    import json
    import pypdf

    mock_db = MagicMock()
    mock_db.get_job.return_value = {
        "id": "job-dropped-test",
        "pages_crawled": 5,
        "max_pages": 100,
        "completeness_status": "complete",
        "dropped_pages_json": json.dumps([
            {"url": "https://example.com/broken-page", "reason": "HTTP 404"},
            {"url": "https://example.com/image.png", "reason": "non-HTML asset extension (.png)"}
        ])
    }
    mock_db.get_review_items.return_value = []
    monkeypatch.setattr(reporter, "DBManager", mock_db)

    pdf_path = ReportExporter.generate_pdf(
        job_id="job-dropped-test",
        target_url="https://example.com",
        verified_issues=[],
    )
    assert Path(pdf_path).exists()

    reader = pypdf.PdfReader(pdf_path)
    full_text = " ".join([page.extract_text() for page in reader.pages])
    assert "Dropped / Excluded Pages" in full_text
    assert "HTTP 404" in full_text
    assert "non-HTML asset extension" in full_text

def test_a17_contiguous_section_numbering_without_competitors():
    exporter = ReportExporter()
    pdf_bytes = exporter.export_pdf(
        job_id="test-job-id-1234",
        target_url="https://example.com/",
        verified_issues=[{"id": "T-001", "type": "missing_canonical", "severity": "high", "urls": ["https://example.com/test"], "evidence": []}],
        performance_data={},
        strategy_data={"tasks": [{"id": "S-001", "title": "Fix canonical", "week": 1, "priority_score": 10.0, "effort": 2, "impact": 5}]},
        content_data={"rewrites": []},
        research_data={},  # NO COMPETITORS
        psi_data=[],
        code_data={"bundle": {"platform": "wordpress", "artifacts": [{"file_path": "functions.php"}]}},
        crawl_pages=[{"url": "https://example.com/", "status_code": 200, "title": "Home", "meta_desc": "Meta", "canonical": "https://example.com/", "indexable": True}]
    )
    assert len(pdf_bytes) > 1000
    # PDF should not have jumped numbers
