import pytest
import asyncio
import os
import csv
import openpyxl
from reportlab.pdfgen import canvas
import httpx

from app.core.db import DBManager
from app.services.pagespeed import run_psi_for_url, run_pagespeed_pipeline
from app.services.reporter import ReportExporter
from app.agents.content_agent import (
    clean_anchor_text,
    extract_candidate_anchor,
    is_standalone_meaningful_phrase,
    compute_internal_link_suggestions,
    rewrite_natural_meta,
    fix_term_capitalization,
    ContentAgent
)
from app.models.agent_schemas import OnPageRewrite

@pytest.mark.asyncio
async def test_psi_retry_on_failed_document_request_after_5_seconds(monkeypatch):
    """Verifies PSI retries once after 5s on FAILED_DOCUMENT_REQUEST and records error."""
    attempts = 0
    sleep_calls = []

    async def mock_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", mock_sleep)
    monkeypatch.setattr(DBManager, "get_psi_cached", lambda *a, **kw: None)

    class MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(
                status_code=500,
                text='{"error": {"code": 500, "message": "Lighthouse returned error: FAILED_DOCUMENT_REQUEST."}}',
                request=request
            )

    job = DBManager.create_job(target_url="https://example.com", max_pages=5)
    job_id = job["id"]

    async with httpx.AsyncClient(transport=MockTransport()) as client:
        res = await run_psi_for_url(client, job_id=job_id, url="https://example.com", strategy="mobile", max_retries=1)

    assert attempts == 2, f"Expected 2 attempts (initial + 1 retry), got {attempts}"
    assert 5.0 in sleep_calls, f"Expected 5.0s sleep call in retry, got {sleep_calls}"
    assert res.get("error") == "FAILED_DOCUMENT_REQUEST"

@pytest.mark.asyncio
async def test_psi_status_set_to_partial_with_url_and_reason(monkeypatch):
    """Verifies PSI status is set to 'partial (<url>: <reason>)' when a call fails."""
    async def fast_sleep(s):
        pass

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    class MockFDRTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=500,
                text='{"error": {"message": "FAILED_DOCUMENT_REQUEST"}}',
                request=request
            )

    job = DBManager.create_job(target_url="https://example.com/target", max_pages=5)
    job_id = job["id"]

    # Pre-populate crawl page
    DBManager.save_crawl_page({
        "job_id": job_id,
        "url": "https://example.com/target",
        "status_code": 200,
        "title": "Target Page",
        "content_type": "text/html",
        "inlinks_count": 5
    })

    # Run pipeline with transport returning FAILED_DOCUMENT_REQUEST
    import app.services.pagespeed as psi_mod
    orig_client = httpx.AsyncClient

    def get_test_client(*args, **kwargs):
        return orig_client(transport=MockFDRTransport())

    monkeypatch.setattr(httpx, "AsyncClient", get_test_client)

    await run_pagespeed_pipeline(job_id, "https://example.com/target")
    updated = DBManager.get_job(job_id)
    status = updated.get("psi_status") or ""

    assert status.startswith("partial"), f"Expected status starting with 'partial', got '{status}'"
    assert "https://example.com/target" in status
    assert "FAILED_DOCUMENT_REQUEST" in status

def test_lab_data_lighthouse_label_in_reports():
    """Verifies that PDF, CSV, and XLSX reports explicitly label PSI scores as 'lab data (Lighthouse)'."""
    job_id = "test-job-psi-label"
    target_url = "https://example.com"
    v_issues = []
    psi_data = [
        {
            "job_id": job_id,
            "url": "https://example.com",
            "strategy": "mobile",
            "performance_score": 88,
            "lcp_ms": 2200,
            "cls": 0.04,
            "fcp_ms": 1400,
            "ttfb_ms": 350
        }
    ]

    # 1. PDF
    pdf_path = ReportExporter.generate_pdf(
        job_id=job_id,
        target_url=target_url,
        verified_issues=v_issues,
        psi_data=psi_data
    )
    assert os.path.exists(pdf_path)

    # 2. CSV
    csv_path = ReportExporter.generate_csv(
        job_id=job_id,
        verified_issues=v_issues,
        psi_data=psi_data
    )
    assert os.path.exists(csv_path)
    with open(csv_path, "r", encoding="utf-8") as f:
        content = f.read()
        assert "lab data (Lighthouse)" in content

    # 3. XLSX
    xlsx_path = ReportExporter.generate_xlsx(
        job_id=job_id,
        target_url=target_url,
        verified_issues=v_issues,
        psi_data=psi_data
    )
    assert os.path.exists(xlsx_path)
    wb = openpyxl.load_workbook(xlsx_path)
    assert "PageSpeed (lab data)" in wb.sheetnames
    sheet = wb["PageSpeed (lab data)"]
    found_label = any("lab data (Lighthouse)" in str(cell.value) for row in sheet.rows for cell in row)
    assert found_label

def test_rewrites_marked_needs_human_review_and_preserves_ai_search_opt():
    """Tests that rewrites are marked 'needs human review', capitalize 'AI', preserve 'AI search optimization',
    and avoid keyword stuffing.
    """
    real_meta = (
        "WebSpire is Pakistan's premier web agency engineering custom Next.js websites, "
        "e-commerce stores, UI/UX design, and AI search optimization for clients in Pakistan, UK, USA & UAE."
    )
    assert len(real_meta) == 178

    rewritten = rewrite_natural_meta(
        current_m=real_meta,
        h1="We Build Modern Websites",
        curr_markets={"pakistan", "uk", "usa", "uae"},
        curr_services={"next.js", "e-commerce", "ui/ux", "ai search optimization"},
        url="https://webspire-agency.vercel.app/"
    )

    # 1. Length within Google 155-158 limit
    assert len(rewritten) <= 155, f"Length {len(rewritten)} exceeds 155 chars: {rewritten}"

    # 2. Preserves AI search optimization with correct capitalization
    assert "AI search optimization" in rewritten
    assert "Ai" not in rewritten  # Must never be 'Ai'

    # 3. Preserves all service and market terms
    assert "Next.js" in rewritten
    assert "e-commerce" in rewritten
    assert "UI/UX" in rewritten
    assert "Pakistan" in rewritten
    assert "UK" in rewritten
    assert "USA" in rewritten
    assert "UAE" in rewritten

    # 4. Check schema default status
    rw = OnPageRewrite(
        url="https://webspire-agency.vercel.app/",
        current_title="WebSpire – Ideas to Impact | Pakistan's Trusted Digital & Web Agency",
        suggested_title="WebSpire | Pakistan's Trusted Digital & Web Agency",
        current_meta=real_meta,
        suggested_meta=rewritten
    )
    assert rw.status == "needs human review"

def test_anchors_standalone_phrases_and_drop_invalid():
    """Tests that anchors must make sense on their own and links without good phrases are dropped."""
    # Standalone phrase validations
    assert is_standalone_meaningful_phrase("Capital Plumbing Services") is True
    assert is_standalone_meaningful_phrase("Website Speed Optimization") is True
    assert is_standalone_meaningful_phrase("Custom Next.js Web Development") is True
    assert is_standalone_meaningful_phrase("Small Business Professional Website") is True

    # Bad phrases (dangling, ending with verb/stopword, or command)
    assert is_standalone_meaningful_phrase("Why Every Small Business Needs") is False
    assert is_standalone_meaningful_phrase("Why Every Small Business") is False  # Begins with 'why'
    assert is_standalone_meaningful_phrase("Click Here To View") is False
    assert is_standalone_meaningful_phrase("Explore Design") is False  # Generic command
    assert is_standalone_meaningful_phrase("Solutions We Offer") is False  # Ends in verb

    # Verify link suggestion engine drops target with only invalid anchors
    pages = [
        {"url": "https://example.com/src", "status_code": 200, "inlinks_count": 5, "title": "Source Page", "h1": "Source", "text_terms": ["business", "development", "web"]},
        {"url": "https://example.com/bad-target", "status_code": 200, "inlinks_count": 0, "title": "Why", "h1": "Why", "text_terms": ["business", "development", "web"]}
    ]
    # compute_internal_link_suggestions with bad target anchor
    links = compute_internal_link_suggestions(pages, [])
    assert not any(l.target_url == "https://example.com/bad-target" for l in links)
