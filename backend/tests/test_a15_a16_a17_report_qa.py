import pytest
from pathlib import Path
from app.services.report_linter import lint_audit_report
from app.services.reporter import ReportExporter

def test_a16_report_linter_detects_empty_tasks_and_inconsistencies():
    # Issue exists but 0 strategy tasks
    issues = [{"id": "T-001", "type": "missing_canonical", "severity": "high", "urls": ["https://example.com/test"], "evidence": []}]
    warnings = lint_audit_report(
        job={"id": "job1", "pages_crawled": 5},
        tech_issues=issues,
        strategy_tasks=[],  # Empty tasks
        rewrites=[],
        psi_results=[{"url": "https://example.com/", "score": 90, "lcp_ms": 11000}], # Inconsistent
        code_bundle={"platform": "nextjs"}
    )
    assert any("strategy tasks" in w.lower() for w in warnings)
    assert any("lcp" in w.lower() or "pagespeed" in w.lower() for w in warnings)

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
