import pytest
from unittest.mock import AsyncMock, patch
from app.agents.issue_rules import detect_issues_from_data
from app.agents.verifier import Verifier
from app.models.agent_schemas import TechnicalIssue
from app.core.db import DBManager
from app.services.pagespeed import run_psi_for_url

def test_on_page_rules_only_run_on_200_ok():
    """A 404/5xx page must never produce missing_title or missing_meta_description."""
    mock_pages = [
        {
            "id": "p-404",
            "url": "https://example.com/not-found",
            "status_code": 404,
            "title": None,
            "meta_desc": None,
            "h1": None,
            "indexable": False,
            "indexability_status": "http_error",
        },
        {
            "id": "p-500",
            "url": "https://example.com/server-error",
            "status_code": 500,
            "title": "",
            "meta_desc": "",
            "h1": "",
            "indexable": False,
            "indexability_status": "http_error",
        }
    ]
    candidates = detect_issues_from_data(crawl_pages=mock_pages, crawl_links=[], psi_results=[])
    types = [c["type"] for c in candidates]
    
    assert "missing_title" not in types
    assert "missing_meta_description" not in types
    assert "missing_h1" not in types
    assert "broken_link_4xx" in types
    assert "server_error_5xx" in types

def test_missing_elements_on_200_ok():
    mock_pages = [
        {
            "id": "p-200-missing",
            "url": "https://example.com/page-1",
            "status_code": 200,
            "title": None,
            "meta_desc": "",
            "h1": "",
            "canonical": None,
            "indexable": True,
            "indexability_status": "indexable",
        }
    ]
    candidates = detect_issues_from_data(crawl_pages=mock_pages, crawl_links=[], psi_results=[])
    types = [c["type"] for c in candidates]
    
    assert "missing_title" in types
    assert "missing_meta_description" in types
    assert "missing_h1" in types
    assert "missing_canonical" in types

def test_title_and_meta_length_rules():
    mock_pages = [
        {
            "id": "p-long",
            "url": "https://example.com/long-title",
            "status_code": 200,
            "title": "A" * 75,
            "meta_desc": "B" * 180,
            "h1": "Heading",
            "canonical": "https://example.com/long-title",
            "indexable": True,
            "indexability_status": "indexable",
        },
        {
            "id": "p-short",
            "url": "https://example.com/short-title",
            "status_code": 200,
            "title": "Short",
            "meta_desc": "Normal description here",
            "h1": "Heading",
            "canonical": "https://example.com/short-title",
            "indexable": True,
            "indexability_status": "indexable",
        }
    ]
    candidates = detect_issues_from_data(crawl_pages=mock_pages, crawl_links=[], psi_results=[])
    types = [c["type"] for c in candidates]
    
    assert "title_too_long" in types
    assert "meta_too_long" in types
    assert "title_too_short" in types

def test_psi_rules_detector():
    mock_psi = [
        {
            "id": "psi-1",
            "url": "https://example.com/slow",
            "strategy": "mobile",
            "performance_score": 42,
            "lcp_ms": 4500.0,
            "cls": 0.35,
        }
    ]
    candidates = detect_issues_from_data(crawl_pages=[], crawl_links=[], psi_results=mock_psi)
    types = [c["type"] for c in candidates]
    
    assert "low_performance_score" in types
    assert "slow_lcp" in types
    assert "poor_cls" in types

def test_verifier_rejects_empty_evidence():
    job = DBManager.create_job("https://example.com", max_pages=10)
    issue = TechnicalIssue(
        id="T-001",
        type="missing_title",
        severity="high",
        impact="Bad",
        effort="low",
        urls=["https://example.com/page"],
        evidence=[],  # EMPTY EVIDENCE
        fix_hint="Fix it"
    )
    report = Verifier.verify_issues(job["id"], [issue])
    assert report.verified_count == 0
    assert report.rejected_count == 1
    assert "Evidence list is empty" in report.rejected_issues[0]["reason"]

def test_verifier_rejects_non_existent_evidence_id():
    job = DBManager.create_job("https://example.com", max_pages=10)
    # Save legitimate page in crawl so URL validation passes
    DBManager.save_crawl_page({
        "job_id": job["id"],
        "url": "https://example.com/page",
        "status_code": 200,
        "title": "Title",
        "indexable": True,
        "indexability_status": "indexable"
    })
    issue = TechnicalIssue(
        id="T-002",
        type="missing_title",
        severity="high",
        impact="Bad",
        effort="low",
        urls=["https://example.com/page"],
        evidence=[{"table": "crawl_pages", "id": "non-existent-uuid", "field": "title"}],
        fix_hint="Fix it"
    )
    report = Verifier.verify_issues(job["id"], [issue])
    assert report.verified_count == 0
    assert report.rejected_count == 1
    assert "does not exist in database" in report.rejected_issues[0]["reason"]

def test_verifier_rejects_false_claim_against_data():
    job = DBManager.create_job("https://example.com", max_pages=10)
    # Save a page that DOES have a title
    pid = DBManager.save_crawl_page({
        "job_id": job["id"],
        "url": "https://example.com/has-title",
        "status_code": 200,
        "title": "Legitimate Title Present",
        "meta_desc": "Meta description",
        "h1": "H1",
        "indexable": True,
        "indexability_status": "indexable"
    })
    
    # Claim that this page is missing a title (FALSE CLAIM)
    issue = TechnicalIssue(
        id="T-003",
        type="missing_title",
        severity="high",
        impact="Bad",
        effort="low",
        urls=["https://example.com/has-title"],
        evidence=[{"table": "crawl_pages", "id": pid, "field": "title"}],
        fix_hint="Add title"
    )
    report = Verifier.verify_issues(job["id"], [issue])
    assert report.verified_count == 0
    assert report.rejected_count == 1
    assert "Claim false" in report.rejected_issues[0]["reason"]

def test_verifier_accepts_valid_evidence():
    job = DBManager.create_job("https://example.com", max_pages=10)
    # Save a page that genuinely lacks a title
    pid = DBManager.save_crawl_page({
        "job_id": job["id"],
        "url": "https://example.com/missing-title-page",
        "status_code": 200,
        "title": None,
        "meta_desc": "Some description",
        "h1": "H1",
        "indexable": True,
        "indexability_status": "indexable"
    })
    
    valid_issue = TechnicalIssue(
        id="T-004",
        type="missing_title",
        severity="high",
        impact="SEO damage",
        effort="low",
        urls=["https://example.com/missing-title-page"],
        evidence=[{"table": "crawl_pages", "id": pid, "field": "title"}],
        fix_hint="Add descriptive title"
    )
    report = Verifier.verify_issues(job["id"], [valid_issue])
    assert report.verified_count == 1
    assert report.rejected_count == 0

@pytest.mark.asyncio
async def test_psi_simulated_timeout_does_not_break_job(monkeypatch):
    monkeypatch.setattr(DBManager, "get_psi_cached", lambda *a, **kw: None)
    job = DBManager.create_job("https://example-timeout.com", max_pages=5)
    
    # Mock client to raise timeout
    mock_client = AsyncMock()
    mock_client.get.side_effect = Exception("Simulated Timeout Error")
    
    result = await run_psi_for_url(mock_client, job["id"], "https://example-timeout.com", "mobile")
    assert result["performance_score"] is None
    assert "PSI unavailable" in result["error"] or "Timeout" in result["error"]

@pytest.mark.asyncio
async def test_technical_agent_fallback_on_503_retries(monkeypatch):
    from app.agents.technical_agent import TechnicalAgent
    from unittest.mock import MagicMock

    candidates = [{
        "type": "broken_link_4xx",
        "urls": ["https://example.com/broken"],
        "evidence": [{"table": "crawl_pages", "id": "1", "field": "status_code"}]
    }]

    call_count = 0
    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.status_code = 503
        resp.text = '{"error": {"code": 503, "message": "High demand"}}'
        return resp

    # Speed up backoff in tests
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    monkeypatch.setattr("app.core.config.settings.GEMINI_API_KEY", "test-key-mock")
    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        report, mode, cost, failure_reason, model_used = await TechnicalAgent.run(candidates)
        assert mode == "fallback"
        assert cost == 0.0
        assert model_used is None
        assert "503" in failure_reason
        assert len(report.issues) == 1

