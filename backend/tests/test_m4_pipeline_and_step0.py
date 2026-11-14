import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from app.core.config import settings
from app.core.security import encrypt_token, decrypt_token
from app.core.db import DBManager
from app.agents.issue_rules import detect_issues_from_data
from app.agents.research_metrics import compute_research_metrics, classify_intent
from app.agents.content_agent import compute_internal_link_suggestions
from app.crawler.competitor_crawler import CompetitorCrawler
from app.models.agent_schemas import (
    TechnicalIssue, StrategyTask, StrategyTaskSourceRef,
    ContentAgentReport, ContentBrief, OnPageRewrite, InternalLinkSuggestion
)
from app.agents.verifier import Verifier
from app.services.reporter import ReportExporter
from app.services.keyword_provider import NullProvider

# ---------------------------------------------------------------------------
# 1. Cluster, Intent & Gap Detection (including empty data & tiny samples)
# ---------------------------------------------------------------------------
def test_research_metrics_empty_data():
    """Empty data should not crash and should return valid empty collections."""
    res = compute_research_metrics(gsc_rows=[], crawl_pages=[], competitor_pages=[])
    assert res["query_clusters"] == []
    assert res["content_gaps"] == []
    assert res["cannibalization"] == []
    assert res["mismatch"] == []
    assert res["question_queries"] == []
    assert res["total_queries_analyzed"] == 0

def test_intent_classification():
    assert classify_intent("how to do seo audit") == "informational"
    assert classify_intent("best seo tool 2026") == "commercial"
    assert classify_intent("buy seo services agency near me") == "transactional"
    assert classify_intent("mybrand portal login", brand_name="mybrand") == "navigational"

def test_content_gaps_and_clusters_detection():
    gsc_rows = [
        {"query": "nextjs seo optimization", "page": "https://example.com/other", "clicks": 50, "impressions": 1000, "position": 8.0},
        {"query": "nextjs performance guide", "page": "https://example.com/other", "clicks": 20, "impressions": 400, "position": 11.0},
        {"query": "how to speed up react", "page": "https://example.com/react", "clicks": 5, "impressions": 200, "position": 14.0},
    ]
    crawl_pages = [
        {"url": "https://example.com/other", "title": "About Us", "h1": "Company Information", "status_code": 200},
        {"url": "https://example.com/react", "title": "React Overview", "h1": "React Lib", "status_code": 200},
    ]
    res = compute_research_metrics(gsc_rows, crawl_pages, min_impressions=50)
    
    assert len(res["query_clusters"]) >= 1
    # "nextjs seo optimization" has 1000 impressions but no page has it in title/H1
    gap_heads = [g["head_term"] for g in res["content_gaps"]]
    assert any("nextjs" in h for h in gap_heads)
    # Question query
    assert any("how to" in q["query"] for q in res["question_queries"])

# ---------------------------------------------------------------------------
# 2. Cannibalization & Mismatch Detection
# ---------------------------------------------------------------------------
def test_cannibalization_detection():
    gsc_rows = [
        {"query": "enterprise seo audit", "page": "https://example.com/services", "clicks": 60, "impressions": 1200, "position": 6.0},
        {"query": "enterprise seo audit", "page": "https://example.com/blog/seo-audit", "clicks": 45, "impressions": 1100, "position": 7.5},
    ]
    crawl_pages = [
        {"url": "https://example.com/services", "title": "Enterprise SEO Services", "h1": "SEO Services", "status_code": 200},
        {"url": "https://example.com/blog/seo-audit", "title": "What is an Enterprise SEO Audit", "h1": "SEO Audit Guide", "status_code": 200},
    ]
    res = compute_research_metrics(gsc_rows, crawl_pages, min_impressions=10)
    assert len(res["cannibalization"]) == 1
    assert res["cannibalization"][0]["query"] == "enterprise seo audit"
    assert len(res["cannibalization"][0]["competing_pages"]) == 2

# ---------------------------------------------------------------------------
# 3. Competitor Crawler (Robots, Rate Limit, Cap)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_competitor_crawler_cap_and_robots():
    crawler = CompetitorCrawler("job-test", "competitor.com", max_pages=30)
    assert crawler.max_pages == 30
    assert crawler.parsed_domain == "competitor.com"
    # NullProvider check: never invents volume or KD
    null_p = NullProvider()
    metrics = await null_p.get_metrics(["seo"])
    assert metrics[0].search_volume is None
    assert "unknown" in metrics[0].source

# ---------------------------------------------------------------------------
# 4. Deterministic Internal Link Engine Rules
# ---------------------------------------------------------------------------
def test_internal_link_engine_rules():
    crawl_pages = [
        {"url": "https://example.com/source-1", "status_code": 200, "title": "Source One", "word_count": 500, "inlinks_count": 5},
        {"url": "https://example.com/orphan-target", "status_code": 200, "title": "SEO Consulting Guide", "word_count": 800, "inlinks_count": 0},
        {"url": "https://example.com/page-3", "status_code": 200, "title": "Page Three", "word_count": 400, "inlinks_count": 3},
    ]
    crawl_links = [
        {"source_url": "https://example.com/source-1", "target_url": "https://example.com/page-3"}
    ]
    suggestions = compute_internal_link_suggestions(crawl_pages, crawl_links, max_per_source=3)

    for s in suggestions:
        # Rule 1: No self links
        assert s.source_url != s.target_url
        # Rule 2: Both URLs exist in crawl
        assert s.source_url in [p["url"] for p in crawl_pages]
        assert s.target_url in [p["url"] for p in crawl_pages]
        # Rule 3: Never suggests an existing link
        assert not (s.source_url == "https://example.com/source-1" and s.target_url == "https://example.com/page-3")

# ---------------------------------------------------------------------------
# 5. Verifier Rejections (Forecasts, Missing Sources, Character Limits)
# ---------------------------------------------------------------------------
def test_verifier_rejects_unbacked_and_forecast_strategy_tasks():
    # Task with NO source
    task_no_source = StrategyTask(
        id="S-001",
        title="Unbacked Task",
        category="technical",
        week=1,
        impact=4,
        effort=2,
        priority_score=4.0,
        depends_on=[],
        source_refs=[],  # EMPTY
        expected_outcome="Qualitative outcome",
        done_when="Done"
    )

    # Task with forbidden numeric forecast
    task_forecast = StrategyTask(
        id="S-002",
        title="Forecast Task",
        category="content",
        week=2,
        impact=5,
        effort=3,
        priority_score=3.3,
        depends_on=[],
        source_refs=[StrategyTaskSourceRef(kind="tech_issue", id="T-001")],
        expected_outcome="This will increase traffic by 40% and reach rank #1",  # FORBIDDEN
        done_when="Done"
    )

    rep = Verifier.verify_strategy_tasks(
        tasks=[task_no_source, task_forecast],
        verified_source_ids={"T-001"}
    )
    assert rep.verified_count == 0
    assert rep.rejected_count == 2
    reasons = [r["reason"] for r in rep.rejected_tasks]
    assert any("no source_refs" in r for r in reasons)
    assert any("Numeric forecast detected" in r for r in reasons)

def test_verifier_rejects_invalid_content_briefs():
    crawl_pages = [{"url": "https://example.com/test", "title": "Test Title", "meta_desc": "Test Meta", "status_code": 200}]
    crawl_links = []
    research_snapshot = {"query_clusters": [{"head_term": "valid cluster"}], "question_queries": [{"query": "valid question"}]}

    # Brief with title > 60 chars
    long_title_brief = ContentBrief(
        target_cluster="valid cluster",
        intent="informational",
        suggested_title="This is an extremely long title that exceeds the strict sixty character limit for sure",
        suggested_meta="Short meta",
        h1="Heading",
        outline=["H2"],
        questions_to_answer=["valid question"],
        schema_suggestion="Article",
        internal_links=[]
    )

    # Brief with fabricated question
    fake_question_brief = ContentBrief(
        target_cluster="valid cluster",
        intent="informational",
        suggested_title="Short Title",
        suggested_meta="Short meta",
        h1="Heading",
        outline=["H2"],
        questions_to_answer=["invented question not in GSC"],  # NOT IN GSC
        schema_suggestion="Article",
        internal_links=[]
    )

    agent_rep = ContentAgentReport(
        briefs=[long_title_brief, fake_question_brief],
        rewrites=[],
        internal_links=[],
        summary="Test"
    )
    ver_rep = Verifier.verify_content_outputs(agent_rep, crawl_pages, crawl_links, research_snapshot)
    assert ver_rep.verified_count == 0
    assert len(ver_rep.rejected_briefs) == 2

# ---------------------------------------------------------------------------
# 6. Step 0 Coverage Check: Silently Dropped Candidates
# ---------------------------------------------------------------------------
def test_verifier_candidate_coverage_check():
    candidates = [
        {"type": "missing_title", "urls": ["https://example.com/p1"], "evidence": [{"table": "crawl_pages", "id": "1", "field": "title"}]},
        {"type": "broken_link_4xx", "urls": ["https://example.com/p2"], "evidence": [{"table": "crawl_pages", "id": "2", "field": "status_code"}]},
    ]
    # Technical agent only includes missing_title, drops broken_link_4xx without putting in dismissed
    partial_issues = [
        TechnicalIssue(
            id="T-001",
            type="missing_title",
            severity="high",
            impact="Missing title tag",
            effort="low",
            urls=["https://example.com/p1"],
            evidence=[{"table": "crawl_pages", "id": "1", "field": "title"}],
            fix_hint="Add title"
        )
    ]
    rep = Verifier.verify_issues(
        job_id="coverage-test",
        issues=partial_issues,
        candidates=candidates,
        dismissed=[]  # Did not dismiss broken_link_4xx!
    )
    assert rep.coverage_status == "failed"
    assert rep.total_checked > 0

# ---------------------------------------------------------------------------
# 7. Canonical Mass-Misconfiguration Rule
# ---------------------------------------------------------------------------
def test_canonical_mass_misconfiguration_rule():
    pages = [
        {"id": f"p-{i}", "url": f"https://example.com/page-{i}", "status_code": 200, "canonical": "https://example.com/", "indexable": True}
        for i in range(1, 11)
    ]
    candidates = detect_issues_from_data(crawl_pages=pages, crawl_links=[], psi_results=[])
    types = [c["type"] for c in candidates]
    assert "canonical_mass_misconfiguration" in types
    # Check common target is preserved
    mass_cand = next(c for c in candidates if c["type"] == "canonical_mass_misconfiguration")
    assert mass_cand.get("target_canonical").rstrip("/") == "https://example.com"

# ---------------------------------------------------------------------------
# 8. DEMO DATA Watermark on Exports
# ---------------------------------------------------------------------------
def test_demo_watermark_in_exports(tmp_path):
    job_id = "demo-test-job-1234"
    target_url = "https://example.com"
    verified_issues = [{
        "id": "T-001", "type": "missing_title", "severity": "high", "effort": "low",
        "urls": ["https://example.com/"], "impact": "Test impact", "fix_hint": "Add title"
    }]

    pdf_path = ReportExporter.generate_pdf(job_id, target_url, verified_issues, is_demo=True)
    csv_path = ReportExporter.generate_csv(job_id, verified_issues, is_demo=True)
    xlsx_path = ReportExporter.generate_xlsx(job_id, target_url, verified_issues, is_demo=True)

    assert os.path.exists(pdf_path)
    assert os.path.exists(csv_path)
    assert os.path.exists(xlsx_path)

    # Check CSV first row contains watermark
    with open(csv_path, "r", encoding="utf-8") as f:
        first_line = f.readline()
        assert "### DEMO DATA ###" in first_line

# ---------------------------------------------------------------------------
# 9. Secrets Hygiene & Production Key Enforcement
# ---------------------------------------------------------------------------
def test_production_refuses_auto_generated_key():
    import app.core.security as sec
    sec._cipher = None
    with patch.object(settings, "ENVIRONMENT", "production"):
        with patch.object(settings, "TOKEN_ENCRYPTION_KEY", None):
            with pytest.raises(RuntimeError, match="Production mode requires TOKEN_ENCRYPTION_KEY"):
                sec.get_cipher()
    sec._cipher = None

def test_gitignore_contains_critical_secrets():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    for gi_path in [os.path.join(root_dir, ".gitignore"), os.path.join(backend_dir, ".gitignore")]:
        assert os.path.exists(gi_path)
        with open(gi_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert ".env" in content
            assert "*.secret.key" in content or ".secret.key" in content
            assert "*.sqlite" in content or "*.db" in content

# ---------------------------------------------------------------------------
# 10. Missing M3 Tests: OAuth Scenarios & Tokens Never in Logs
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_oauth_callback_scenarios_and_tokens_never_logged(caplog):
    import logging
    # Test 1: Token encryption never logs raw tokens
    raw_secret_token = "secret-oauth-refresh-token-xyz-12345"
    with caplog.at_level(logging.DEBUG):
        encrypted = encrypt_token(raw_secret_token)
        decrypted = decrypt_token(encrypted)
    assert decrypted == raw_secret_token
    # Assert token string NEVER appears anywhere in captured logs
    assert raw_secret_token not in caplog.text

    # Test 2: User connection isolation & saving encrypted
    DBManager.save_google_connection(
        user_id="test-user-oauth",
        email="test@agency.com",
        encrypted_refresh_token=encrypted,
        scopes=["https://www.googleapis.com/auth/webmasters.readonly"]
    )
    conn = DBManager.get_google_connection("test-user-oauth")
    assert conn is not None
    assert conn["google_email"] == "test@agency.com"
    assert conn["encrypted_refresh_token"] == encrypted
    assert conn["encrypted_refresh_token"] != raw_secret_token

# ---------------------------------------------------------------------------
# 11. No-GSC Crawl-Only Research Test
# ---------------------------------------------------------------------------
def test_no_gsc_crawl_only_research():
    crawl_pages = [
        {"url": "https://example.com/", "title": "Home", "h1": "Welcome", "status_code": 200, "word_count": 300},
        {"url": "https://example.com/about", "title": "About", "h1": "About Us", "status_code": 200, "word_count": 500},
    ]
    # 0 GSC rows (not connected)
    metrics = compute_research_metrics(gsc_rows=[], crawl_pages=crawl_pages)
    assert metrics["total_queries_analyzed"] == 0
    assert metrics["content_gaps"] == []
    assert metrics["cannibalization"] == []

# ---------------------------------------------------------------------------
# 12. Regression Tests: Descriptors/Dates Not Untraceable & Fallback Replacement
# ---------------------------------------------------------------------------
def test_untraceable_numbers_regression():
    from app.agents.verifier import extract_numbers_from_text
    from app.models.agent_schemas import MonitorFinding

    narrative = (
        "During the 30-day analysis ending on 2026-11-05, pages in the top-10 rankings "
        "showed an average position score of 3.5 with a 1.2% CTR improvement."
    )
    extracted = extract_numbers_from_text(narrative)
    # "30-day", "2026-11-05", and "top-10" MUST NOT produce raw 30, 2026, 11, 5, 10
    assert 2026.0 not in extracted
    assert -10.0 not in extracted
    assert 10.0 not in extracted
    assert 30.0 not in extracted

    # "3.5" and "1.2%" must be cleanly extracted for traceability checks
    assert 3.5 in extracted
    assert 1.2 in extracted

    # Verify that a monitor finding with these terms passes verification without being rejected
    snapshot_id = "snap-test-123"
    snapshot = {
        "summary_totals": {
            "clicks_change_pct": 1.2,
            "impressions_change_pct": 5.0,
            "avg_position": 3.5
        }
    }
    finding = MonitorFinding(
        id="MF-001",
        type="traffic_gain",
        headline="Top-10 ranking gain over 30-day window",
        explanation="On 2026-11-05, position reached 3.5 with 1.2% clicks increase.",
        metrics_used=[{"snapshot_id": snapshot_id, "field": "summary_totals.clicks_change_pct", "value": 1.2}],
        recommended_action="Maintain on-page optimization.",
        confidence=0.95
    )
    rep = Verifier.verify_monitor_findings(snapshot_id, snapshot, [finding])
    assert rep.verified_count == 1
    assert rep.rejected_count == 0

def test_rejected_llm_issue_replaced_by_fallback_rule():
    # 1. Setup a job in the database with a page that has missing title
    job = DBManager.create_job("https://example.com/test-page")
    page_id = DBManager.save_crawl_page({
        "job_id": job["id"],
        "url": "https://example.com/test-page",
        "status_code": 200,
        "title": "",  # missing title
        "meta_desc": "Some description",
        "h1": "Heading",
        "canonical": "https://example.com/test-page",
        "indexable": True,
        "indexability_status": "indexable"
    })

    candidate = {
        "id": "C-001",
        "type": "missing_title",
        "urls": ["https://example.com/test-page"],
        "evidence": [{"table": "crawl_pages", "id": page_id, "field": "title", "value": None}]
    }

    # 2. LLM returns an invalid issue (e.g. unknown evidence table or missing ID)
    bad_llm_issue = TechnicalIssue(
        id="T-001",
        type="missing_title",
        severity="high",
        impact="Missing title tag",
        effort="low",
        urls=["https://example.com/test-page"],
        evidence=[{"table": "non_existent_table", "id": "unknown-id", "field": "title", "value": None}],
        fix_hint="Add title",
        candidate_ids=["C-001"],
        source="llm"
    )

    # 3. Verifier audits issues
    rep = Verifier.verify_issues(
        job_id=job["id"],
        issues=[bad_llm_issue],
        candidates=[candidate],
        dismissed=[]
    )

    # The bad LLM issue MUST be rejected
    assert rep.rejected_count == 1
    assert rep.rejected_issues[0]["issue_id"] == "T-001"

    # BUT the candidate MUST NOT disappear! It must be replaced by its deterministic version with source="fallback_rule"
    assert rep.verified_count == 1
    fallback_issue = rep.verified_issues[0]
    assert fallback_issue.type == "missing_title"
    assert fallback_issue.source == "fallback_rule"
    assert fallback_issue.urls == ["https://example.com/test-page"]
    assert fallback_issue.evidence == candidate["evidence"]

# ---------------------------------------------------------------------------
# 13. Claims Check Tests: "award-winning", "#1", invented year & Keep Current
# ---------------------------------------------------------------------------
def test_claims_check_rejects_award_winning_and_keeps_current_text():
    crawl_pages = [{
        "url": "https://example.com/services",
        "title": "Web Development Services",
        "meta_desc": "We build custom web applications for businesses.",
        "h1": "Our Services",
        "status_code": 200
    }]
    crawl_links = []
    research_snapshot = {"query_clusters": [], "question_queries": []}

    # Rewrite invents "award-winning" (not present on page)
    rewrite = OnPageRewrite(
        url="https://example.com/services",
        current_title="Web Development Services",
        suggested_title="Award-Winning Web Development Services",
        current_meta="We build custom web applications for businesses.",
        suggested_meta="Work with our award-winning agency for digital solutions."
    )

    agent_rep = ContentAgentReport(briefs=[], rewrites=[rewrite], internal_links=[], summary="Test")
    rep = Verifier.verify_content_outputs(agent_rep, crawl_pages, crawl_links, research_snapshot)

    assert rep.rejected_count == 1
    assert rep.verified_count == 0
    assert len(rep.rejected_rewrites) == 1
    assert "award-winning" in rep.rejected_rewrites[0]["reason"].lower()
    
    # Must keep current text
    assert rep.rejected_rewrites[0]["kept_title"] == "Web Development Services"
    assert rep.rejected_rewrites[0]["kept_meta"] == "We build custom web applications for businesses."
    assert len(rep.kept_rewrites) == 1
    assert rep.kept_rewrites[0].suggested_title == "Web Development Services"
    assert rep.kept_rewrites[0].suggested_meta == "We build custom web applications for businesses."

def test_claims_check_rejects_number_one_rank_and_keeps_current_text():
    crawl_pages = [{
        "url": "https://example.com/services",
        "title": "Web Development Services",
        "meta_desc": "We build custom web applications for businesses.",
        "h1": "Our Services",
        "status_code": 200
    }]
    crawl_links = []
    research_snapshot = {"query_clusters": [], "question_queries": []}

    # Rewrite invents "#1"
    rewrite = OnPageRewrite(
        url="https://example.com/services",
        current_title="Web Development Services",
        suggested_title="#1 Web Development Services in the Region",
        current_meta="We build custom web applications for businesses.",
        suggested_meta="Ranked #1 for full-stack software and web design."
    )

    agent_rep = ContentAgentReport(briefs=[], rewrites=[rewrite], internal_links=[], summary="Test")
    rep = Verifier.verify_content_outputs(agent_rep, crawl_pages, crawl_links, research_snapshot)

    assert rep.rejected_count == 1
    assert rep.verified_count == 0
    assert len(rep.rejected_rewrites) == 1
    assert "#1" in rep.rejected_rewrites[0]["reason"]
    
    # Must keep current text
    assert rep.rejected_rewrites[0]["kept_title"] == "Web Development Services"
    assert rep.kept_rewrites[0].suggested_title == "Web Development Services"

def test_claims_check_rejects_invented_year_and_keeps_current_text():
    crawl_pages = [{
        "url": "https://example.com/services",
        "title": "Web Development Services",
        "meta_desc": "We build custom web applications for businesses.",
        "h1": "Our Services",
        "status_code": 200
    }]
    crawl_links = []
    research_snapshot = {"query_clusters": [], "question_queries": []}

    # Rewrite invents future year 2028 (not on page)
    rewrite = OnPageRewrite(
        url="https://example.com/services",
        current_title="Web Development Services",
        suggested_title="Web Development Trends and Strategies 2028",
        current_meta="We build custom web applications for businesses.",
        suggested_meta="Explore the most effective web frameworks for 2028."
    )

    agent_rep = ContentAgentReport(briefs=[], rewrites=[rewrite], internal_links=[], summary="Test")
    rep = Verifier.verify_content_outputs(agent_rep, crawl_pages, crawl_links, research_snapshot)

    assert rep.rejected_count == 1
    assert rep.verified_count == 0
    assert len(rep.rejected_rewrites) == 1
    assert "2028" in rep.rejected_rewrites[0]["reason"]
    
    # Must keep current text
    assert rep.rejected_rewrites[0]["kept_title"] == "Web Development Services"
    assert rep.kept_rewrites[0].suggested_title == "Web Development Services"

def test_claims_check_on_content_brief_with_unsubstantiated_claims():
    crawl_pages = [{
        "url": "https://example.com/seo-audit",
        "title": "SEO Audit Services",
        "meta_desc": "Professional SEO audits for websites.",
        "h1": "Comprehensive SEO Audit",
        "status_code": 200
    }]
    crawl_links = []
    research_snapshot = {
        "query_clusters": [{"head_term": "seo audit"}],
        "question_queries": [{"query": "how to do an seo audit"}]
    }

    # Content brief invents award-winning, #1 and 2028
    brief = ContentBrief(
        target_cluster="seo audit",
        intent="informational",
        suggested_title="#1 Award-Winning SEO Audit Guide 2028",
        suggested_meta="The top guide for digital website audits.",
        h1="Why We Are The #1 Agency in 2028",
        outline=["Overview"],
        questions_to_answer=["how to do an seo audit"],
        schema_suggestion="Article",
        internal_links=[]
    )

    agent_rep = ContentAgentReport(briefs=[brief], rewrites=[], internal_links=[], summary="Test")
    rep = Verifier.verify_content_outputs(agent_rep, crawl_pages, crawl_links, research_snapshot)

    assert rep.rejected_count == 1
    assert rep.verified_count == 0
    assert len(rep.rejected_briefs) == 1
    assert "Claims check failed" in rep.rejected_briefs[0]["reason"]

def test_claims_check_accepts_valid_claims_present_on_target_page():
    crawl_pages = [{
        "url": "https://example.com/services",
        "title": "Web Development Services",
        "meta_desc": "We build custom web applications for businesses.",
        "h1": "Our Services",
        "body_text": "Our award-winning team was established in 2020 and ranked #1 in client reviews.",
        "status_code": 200
    }]
    crawl_links = []
    research_snapshot = {"query_clusters": [], "question_queries": []}

    # Rewrite uses claims that ARE present on the page
    rewrite = OnPageRewrite(
        url="https://example.com/services",
        current_title="Web Development Services",
        suggested_title="Award-Winning Web Services Since 2020",
        current_meta="We build custom web applications for businesses.",
        suggested_meta="Ranked #1 in client reviews for custom web applications."
    )

    agent_rep = ContentAgentReport(briefs=[], rewrites=[rewrite], internal_links=[], summary="Test")
    rep = Verifier.verify_content_outputs(agent_rep, crawl_pages, crawl_links, research_snapshot)

    assert rep.rejected_count == 0
    assert rep.verified_count == 1
    assert len(rep.verified_rewrites) == 1
    assert rep.verified_rewrites[0].suggested_title == "Award-Winning Web Services Since 2020"

# ---------------------------------------------------------------------------
# 14. Hardened Claims Check: Bounded Text, Unverifiable, Superlatives & List Counts
# ---------------------------------------------------------------------------
def test_bounded_body_text_storage_and_crawl():
    from app.crawler.parser import extract_page_data

    # Generate HTML with > 25,000 chars of body text
    long_body = "word " * 6000  # 30,000 chars
    html = f"<html><head><title>Test Page</title></head><body><p>{long_body}</p></body></html>"
    
    parsed = extract_page_data(
        html=html,
        current_url="https://example.com/long-page",
        status_code=200
    )
    assert "body_text" in parsed
    assert len(parsed["body_text"]) <= 20000
    assert len(parsed["body_text"]) > 1000

    # Test saving into DB
    job = DBManager.create_job("https://example.com/long-page")
    page_id = DBManager.save_crawl_page({
        "job_id": job["id"],
        "url": "https://example.com/long-page",
        "status_code": 200,
        "title": "Test Page",
        "body_text": parsed["body_text"]
    })
    crawled = DBManager.get_crawl_pages(job["id"])
    saved_page = next(p for p in crawled if p["id"] == page_id)
    assert len(saved_page.get("body_text", "")) <= 20000
    assert len(saved_page.get("body_text", "")) > 1000

def test_empty_corpus_marked_unverifiable():
    # Page with completely empty corpus (no title, meta, h1, body_text, headings)
    crawl_pages = [{
        "url": "https://example.com/blank",
        "title": "",
        "meta_desc": "",
        "h1": "",
        "body_text": "",
        "status_code": 200
    }]
    rewrite = OnPageRewrite(
        url="https://example.com/blank",
        current_title="",
        suggested_title="Modern Solutions for Web Services",
        current_meta="",
        suggested_meta="Discover verified solutions for web services."
    )
    agent_rep = ContentAgentReport(briefs=[], rewrites=[rewrite], internal_links=[], summary="Test")
    rep = Verifier.verify_content_outputs(agent_rep, crawl_pages, [], {}, project_name="")

    assert rep.rejected_count == 1
    assert rep.verified_count == 0
    assert rep.rejected_rewrites[0]["status"] == "unverifiable"
    assert "unverifiable" in rep.rejected_rewrites[0]["reason"].lower()

def test_explicit_superlatives_reduces_false_positives():
    # Words like "request", "interest", "contest", "forest", "digest" must NOT be flagged as superlatives
    crawl_pages = [{
        "url": "https://example.com/info",
        "title": "Information Page",
        "meta_desc": "Request details regarding our forest contest and digest interest.",
        "h1": "Request Information",
        "body_text": "Submit your request for our annual forest contest and monthly digest interest.",
        "status_code": 200
    }]
    rewrite = OnPageRewrite(
        url="https://example.com/info",
        current_title="Information Page",
        suggested_title="Request Details: Forest Contest & Digest",
        current_meta="Request details regarding our forest contest and digest interest.",
        suggested_meta="Learn how to request information about the contest and digest."
    )
    agent_rep = ContentAgentReport(briefs=[], rewrites=[rewrite], internal_links=[], summary="Test")
    rep = Verifier.verify_content_outputs(agent_rep, crawl_pages, [], {})

    assert rep.rejected_count == 0
    assert rep.verified_count == 1
    assert len(rep.verified_rewrites) == 1

def test_award_winning_hyphen_space_normalization():
    # Target page has "award winning" without hyphen
    crawl_pages = [{
        "url": "https://example.com/agency",
        "title": "Digital Agency",
        "meta_desc": "An award winning digital agency.",
        "h1": "Welcome",
        "body_text": "We are an award winning agency with trusted services.",
        "status_code": 200
    }]
    # Rewrite has "Award-Winning" with hyphen
    rewrite = OnPageRewrite(
        url="https://example.com/agency",
        current_title="Digital Agency",
        suggested_title="Award-Winning Digital Agency",
        current_meta="An award winning digital agency.",
        suggested_meta="Partner with our award-winning digital agency for solutions."
    )
    agent_rep = ContentAgentReport(briefs=[], rewrites=[rewrite], internal_links=[], summary="Test")
    rep = Verifier.verify_content_outputs(agent_rep, crawl_pages, [], {})

    assert rep.rejected_count == 0
    assert rep.verified_count == 1
    assert rep.verified_rewrites[0].suggested_title == "Award-Winning Digital Agency"

def test_smart_quotes_and_dashes_normalization():
    # Suggested text contains smart quotes “ ” and en-dash –
    crawl_pages = [{
        "url": "https://example.com/guide",
        "title": "Web Guide",
        "meta_desc": "Complete web guide.",
        "h1": "Web Guide",
        "body_text": 'Our team published the "Modern Web" - Complete Guide.',
        "status_code": 200
    }]
    rewrite = OnPageRewrite(
        url="https://example.com/guide",
        current_title="Web Guide",
        suggested_title="“Modern Web” – Complete Guide",
        current_meta="Complete web guide.",
        suggested_meta="Explore our “Modern Web” – Essential strategies and insights."
    )
    agent_rep = ContentAgentReport(briefs=[], rewrites=[rewrite], internal_links=[], summary="Test")
    rep = Verifier.verify_content_outputs(agent_rep, crawl_pages, [], {})

    assert rep.rejected_count == 0
    assert rep.verified_count == 1

def test_small_list_count_numbers_allowed():
    # Patterns like "7 tips", "5 ways", "10 questions" are allowed
    crawl_pages = [{
        "url": "https://example.com/tips",
        "title": "SEO Advice",
        "meta_desc": "Helpful SEO advice.",
        "h1": "SEO Advice",
        "body_text": "Read our comprehensive advice and tips for SEO optimization.",
        "status_code": 200
    }]
    rewrite_7tips = OnPageRewrite(
        url="https://example.com/tips",
        current_title="SEO Advice",
        suggested_title="7 Tips for SEO Optimization",
        current_meta="Helpful SEO advice.",
        suggested_meta="Explore 5 ways and 10 questions to ask for better search ranking."
    )
    agent_rep = ContentAgentReport(briefs=[], rewrites=[rewrite_7tips], internal_links=[], summary="Test")
    rep = Verifier.verify_content_outputs(agent_rep, crawl_pages, [], {})

    assert rep.rejected_count == 0
    assert rep.verified_count == 1
    assert rep.verified_rewrites[0].suggested_title == "7 Tips for SEO Optimization"

def test_unsubstantiated_percentage_and_ranks_still_rejected():
    crawl_pages = [{
        "url": "https://example.com/services",
        "title": "Web Services",
        "meta_desc": "Reliable web services.",
        "h1": "Our Services",
        "body_text": "We offer reliable web solutions for growing companies.",
        "status_code": 200
    }]
    # Rewrite invents 99.9% and #1
    rewrite_fake = OnPageRewrite(
        url="https://example.com/services",
        current_title="Web Services",
        suggested_title="Web Services with 99.9% Uptime",
        current_meta="Reliable web services.",
        suggested_meta="Ranked #1 for client satisfaction and speed."
    )
    agent_rep = ContentAgentReport(briefs=[], rewrites=[rewrite_fake], internal_links=[], summary="Test")
    rep = Verifier.verify_content_outputs(agent_rep, crawl_pages, [], {})

    assert rep.rejected_count == 1
    assert rep.verified_count == 0
    assert len(rep.rejected_rewrites) == 1
    assert any(x in rep.rejected_rewrites[0]["reason"] for x in ["99.9%", "#1"])


# ---------------------------------------------------------------------------
# 15. New Report Issue Fixes: Canonicals, Deterministic Severity, Links, Markets, Exports, URLs
# ---------------------------------------------------------------------------

def test_canonical_to_other_fixed_hint_template():
    from app.agents.technical_agent import CANONICAL_TO_OTHER_FIX_HINT, TechnicalAgent
    # Must not advise removing self-referencing canonicals
    assert "Never remove self-referencing canonicals" in CANONICAL_TO_OTHER_FIX_HINT
    assert "standard SEO recommendation" in CANONICAL_TO_OTHER_FIX_HINT

    # TechnicalAgent must apply this fixed hint template
    candidate = [{
        "id": "C-CAN-01",
        "type": "canonical_to_other",
        "urls": ["https://example.com/page-dup"],
        "evidence": [{"table": "crawl_pages", "id": "p1", "field": "canonical", "value": "https://example.com/page-orig"}]
    }]
    rep = TechnicalAgent._run_deterministic(candidate)
    assert len(rep.issues) == 1
    assert rep.issues[0].fix_hint == CANONICAL_TO_OTHER_FIX_HINT


def test_deterministic_severity_by_issue_type_and_scale():
    from app.agents.technical_agent import get_deterministic_severity

    # High by nature
    assert get_deterministic_severity("broken_link_4xx", url_count=1, total_pages=10) == "high"
    assert get_deterministic_severity("server_error_5xx", url_count=1, total_pages=10) == "high"

    # Medium by nature, escalates to high if >= 10 pages or >= 25%
    assert get_deterministic_severity("missing_h1", url_count=1, total_pages=50) == "medium"
    assert get_deterministic_severity("missing_h1", url_count=15, total_pages=50) == "high"

    # Low by nature, escalates to medium if >= 15 pages or >= 30%
    assert get_deterministic_severity("title_too_long", url_count=2, total_pages=50) == "low"
    assert get_deterministic_severity("title_too_long", url_count=20, total_pages=50) == "medium"


def test_internal_links_never_truncated_and_requires_two_meaningful_terms_and_max_two_per_target():
    from app.agents.content_agent import compute_internal_link_suggestions, clean_anchor_text

    # 1. clean_anchor_text cuts at word boundary
    long_anchor = "Comprehensive enterprise nextjs web design and custom application development"
    cleaned = clean_anchor_text(long_anchor, max_len=40)
    assert len(cleaned) <= 40
    # Must not be cut mid-word (no partial words like 'developm')
    assert cleaned.endswith(("web", "design", "nextjs", "enterprise"))

    # 2. Shared meaningful terms: generic words ignored
    crawl_pages = [
        {
            "url": "https://example.com/src",
            "title": "Source Page",
            "status_code": 200,
            "inlinks_count": 5,
            "word_count": 600,
            # Only generic words shared ("digital", "services")
            "text_terms": ["digital", "services", "unique_source_term"]
        },
        {
            "url": "https://example.com/tgt",
            "title": "Target Page",
            "h1": "Target Page Topic",
            "status_code": 200,
            "inlinks_count": 0,
            "word_count": 400,
            "text_terms": ["digital", "services", "unique_target_term"]
        }
    ]
    # No link should be generated because only generic terms are shared
    links = compute_internal_link_suggestions(crawl_pages, [], max_per_target=2)
    assert len(links) == 0

    # Now add 2 real meaningful terms (with overlap in target's H1)
    crawl_pages[0]["text_terms"].extend(["cloud_migration", "kubernetes"])
    crawl_pages[1]["text_terms"].extend(["cloud_migration", "kubernetes"])
    crawl_pages[1]["h1"] = "Target Page Cloud Migration"

    links = compute_internal_link_suggestions(crawl_pages, [], max_per_target=2)
    assert len(links) >= 1
    assert any(l.target_url == "https://example.com/tgt" for l in links)
    assert any("cloud_migration" in l.reason for l in links)


def test_rewrites_preserve_key_services_and_target_markets():
    crawl_pages = [{
        "url": "https://example.com/agency",
        "title": "Web Agency",
        "meta_desc": "Premier agency engineering Next.js websites and UI/UX design for clients in Pakistan, UK and USA.",
        "h1": "Web Agency",
        "body_text": "We are a digital agency engineering Next.js websites and UI/UX design for clients in Pakistan, UK and USA.",
        "status_code": 200
    }]

    # Rewrite 1: Silently drops target markets "Pakistan, UK, USA" -> must be rejected
    rewrite_dropped_markets = OnPageRewrite(
        url="https://example.com/agency",
        current_title="Web Agency",
        suggested_title="Web Agency | Next.js & UI/UX Design",
        current_meta="Premier agency engineering Next.js websites and UI/UX design for clients in Pakistan, UK and USA.",
        suggested_meta="Premier web agency engineering custom websites and UI/UX design for global brands."
    )
    rep1 = Verifier.verify_content_outputs(
        ContentAgentReport(briefs=[], rewrites=[rewrite_dropped_markets], internal_links=[], summary="Test"),
        crawl_pages, [], {}
    )
    assert rep1.rejected_count == 1
    assert "target market" in rep1.rejected_rewrites[0]["reason"].lower()

    # Rewrite 2: Preserves target markets and services -> must pass
    rewrite_preserved = OnPageRewrite(
        url="https://example.com/agency",
        current_title="Web Agency",
        suggested_title="Web Agency | Next.js & UI/UX Design",
        current_meta="Premier agency engineering Next.js websites and UI/UX design for clients in Pakistan, UK and USA.",
        suggested_meta="Premier agency engineering Next.js websites and UI/UX design for clients in Pakistan, UK and USA."
    )
    rep2 = Verifier.verify_content_outputs(
        ContentAgentReport(briefs=[], rewrites=[rewrite_preserved], internal_links=[], summary="Test"),
        crawl_pages, [], {}
    )
    assert rep2.verified_count == 1
    assert rep2.rejected_count == 0


def test_empty_sections_output_na_requires_search_console_data_in_exports(tmp_path):
    from app.services.reporter import ReportExporter
    import openpyxl
    import csv

    job_id = "test-export-job"
    verified_issues = []
    strategy_data = {"tasks": []}
    content_data = {"briefs": [], "rewrites": [], "internal_links": []}
    research_data = {}

    # 1. Test CSV
    csv_file = ReportExporter.generate_csv(
        job_id=job_id,
        verified_issues=verified_issues,
        strategy_data=strategy_data,
        content_data=content_data,
        research_data=research_data
    )
    with open(csv_file, mode="r", encoding="utf-8") as f:
        reader = csv.reader(f)
        csv_rows = list(reader)
    # Must contain "n/a - requires Search Console data" for content briefs and research
    flat_csv = " ".join([" ".join(r) for r in csv_rows])
    assert "n/a - requires Search Console data" in flat_csv

    # 2. Test XLSX
    xlsx_file = ReportExporter.generate_xlsx(
        job_id=job_id,
        target_url="https://example.com",
        verified_issues=verified_issues,
        strategy_data=strategy_data,
        content_data=content_data,
        research_data=research_data
    )
    wb = openpyxl.load_workbook(xlsx_file)
    ws_cont = wb["Content & Rewrites"]
    all_cells = [str(cell.value) for row in ws_cont.iter_rows() for cell in row if cell.value]
    assert any("n/a - requires Search Console data" in c for c in all_cells)


def test_strategist_task_titles_use_real_urls_from_evidence():
    from app.agents.strategist_agent import StrategistAgent, format_task_title

    # 1. Check title formatter
    formatted = format_task_title("Resolve", "broken_link_4xx", ["https://example.com/services/pricing"])
    assert "/services/pricing" in formatted

    # Multiple URLs for group issue type (e.g. duplicate_title)
    formatted_mult = format_task_title("Optimize", "duplicate_title", ["https://example.com/about", "https://example.com/contact"])
    assert "2 pages" in formatted_mult

    # 2. Strategist agent execution
    tech_issue = TechnicalIssue(
        id="T-001",
        type="broken_link_4xx",
        severity="high",
        impact="Broken links waste crawl equity.",
        effort="low",
        urls=["https://example.com/broken-page"],
        evidence=[],
        fix_hint="Fix link."
    )
    rep = StrategistAgent._run_deterministic([tech_issue], [], [])
    assert len(rep.tasks) >= 1
    assert "/broken-page" in rep.tasks[0].title




def test_all_issue_rule_types_covered_in_severity_table():
    """Fails if any rule type from issue_rules.py is missing from DETERMINISTIC_SEVERITY_TABLE."""
    import inspect
    import re
    from app.agents import issue_rules
    from app.agents.technical_agent import DETERMINISTIC_SEVERITY_TABLE

    src = inspect.getsource(issue_rules.detect_issues_from_data)
    rule_types = set(re.findall(r'["\']type["\']\s*:\s*["\']([a-zA-Z0-9_]+)["\']', src))
    assert len(rule_types) >= 15

    for r_type in rule_types:
        assert r_type in DETERMINISTIC_SEVERITY_TABLE, f"Rule type '{r_type}' from issue_rules.py is missing in DETERMINISTIC_SEVERITY_TABLE!"
    
    # Specific rules explicitly required
    for required in ["redirect_chain", "noindex_page", "orphan_page", "low_performance_score", "slow_lcp", "poor_cls", "canonical_mass_misconfiguration"]:
        assert required in DETERMINISTIC_SEVERITY_TABLE


def test_broken_link_closest_slug_did_you_mean():
    """Tests that 4xx targets match closest crawled 200 URL (e.g. iron-pulse-fitness vs ironpulse-fitness)."""
    from app.agents.issue_rules import find_closest_slug, detect_issues_from_data

    valid_urls = [
        "https://example.com/about",
        "https://example.com/services",
        "https://example.com/portfolio/ironpulse-fitness"
    ]
    broken_url = "https://example.com/portfolio/iron-pulse-fitness"
    match = find_closest_slug(broken_url, valid_urls)
    assert match == "/portfolio/ironpulse-fitness"

    # Test candidate generation
    crawl_pages = [
        {"id": "p1", "url": "https://example.com/portfolio/ironpulse-fitness", "status_code": 200},
        {"id": "p2", "url": "https://example.com/portfolio/iron-pulse-fitness", "status_code": 404}
    ]
    candidates = detect_issues_from_data(crawl_pages, [], [])
    b_cand = [c for c in candidates if c["type"] == "broken_link_4xx"][0]
    assert b_cand.get("did_you_mean") == "/portfolio/ironpulse-fitness"


def test_internal_links_natural_phrases_and_stopwords_and_term_frequency():
    """Tests anchors: 2-5 words, no trailing stopwords, no '/', >40% page terms ignored, overlap with target title/H1."""
    from app.agents.content_agent import clean_anchor_text, compute_internal_link_suggestions

    # 1. Anchor cleaning
    clean = clean_anchor_text("Website Speed Optimization: A Practical")
    assert clean == "Website Speed Optimization"
    assert not any(clean.endswith(" " + sw) for sw in ["a", "practical", "the", "for", "your"])

    clean2 = clean_anchor_text("Why Every Small Business Needs a")
    assert clean2 == "Why Every Small Business"
    assert not any(clean2.lower().endswith(" " + vw) for vw in ["needs", "a", "is", "for", "get"])

    # 2. IDF / >40% page frequency ignored
    p1 = {"url": "https://example.com/page1", "status_code": 200, "inlinks_count": 0, "title": "Plumbing Services Master", "h1": "Plumbing Experts", "text_terms": ["design", "plumbing", "residential"]}
    p2 = {"url": "https://example.com/page2", "status_code": 200, "inlinks_count": 3, "title": "Home Page", "h1": "Welcome", "text_terms": ["design", "agency", "general"]}
    p3 = {"url": "https://example.com/page3", "status_code": 200, "inlinks_count": 3, "title": "About Us", "h1": "About", "text_terms": ["design", "team", "history"]}
    p4 = {"url": "https://example.com/page4", "status_code": 200, "inlinks_count": 3, "title": "Contact", "h1": "Contact Us", "text_terms": ["design", "plumbing", "residential"]}

    links = compute_internal_link_suggestions([p1, p2, p3, p4], [])
    for l in links:
        assert "/" not in l.anchor_text
        words = l.anchor_text.split()
        assert 2 <= len(words) <= 5
        assert words[-1].lower() not in ["for", "your", "practical", "a", "the", "should"]


def test_rewrites_near_duplicate_and_no_change_needed_and_seo_friendly():
    """Tests rewrites near-duplicate >0.6 rejected/differentiated, fine text gets 'no change needed', SEO-Friendly kept."""
    from app.agents.content_agent import ContentAgent
    from app.models.agent_schemas import OnPageRewrite, ContentAgentReport
    from app.agents.verifier import Verifier

    fine_page = {
        "url": "https://example.com/fine",
        "status_code": 200,
        "title": "Professional Web Design Services And Digital Transformation Solutions Agency | AcmeAgency", # >60 chars
        "meta_desc": "Explore AcmeAgency's certified digital services: custom web design, SEO-Friendly setup, and responsive web development for business clients worldwide." # 151 chars (fine)
    }
    rep = ContentAgent._run_deterministic([], [fine_page], [], {}, [])
    assert len(rep.rewrites) >= 1
    rw = rep.rewrites[0]
    assert rw.suggested_title != "no change needed"
    assert rw.suggested_meta == "no change needed"

    rw1 = OnPageRewrite(
        url="https://example.com/page1",
        current_title="Page 1",
        suggested_title="Page 1 | AcmeAgency",
        current_meta="Custom Next.js engineering for clients in Pakistan and UK.",
        suggested_meta="AcmeAgency is agency engineering custom Next.js websites for clients in Pakistan and UK."
    )
    rw2 = OnPageRewrite(
        url="https://example.com/page2",
        current_title="Page 2",
        suggested_title="Page 2 | AcmeAgency",
        current_meta="Custom Next.js engineering for clients in USA and UAE.",
        suggested_meta="AcmeAgency is agency engineering custom Next.js websites for clients in Pakistan and UK."
    )
    c_rep = ContentAgentReport(summary="test", briefs=[], rewrites=[rw1, rw2], internal_links=[])
    v_rep = Verifier.verify_content_outputs(c_rep, [fine_page, {"url": "https://example.com/page1", "title": "Page 1", "meta_desc": "meta", "status_code": 200}, {"url": "https://example.com/page2", "title": "Page 2", "meta_desc": "meta", "status_code": 200}], [], {}, project_name="AcmeAgency")
    assert len(v_rep.rejected_rewrites) >= 1
    assert "near-duplicate" in v_rep.rejected_rewrites[0]["reason"].lower()


def test_strategist_per_url_only_for_broken_links_and_missing_h1():
    """Tests that Strategist creates per-URL tasks only for broken links and missing H1, one per issue type for others."""
    from app.agents.strategist_agent import StrategistAgent
    from app.models.agent_schemas import TechnicalIssue

    b_link_iss = TechnicalIssue(
        id="T-001",
        type="broken_link_4xx",
        severity="high",
        impact="Broken links waste equity.",
        effort="low",
        urls=["https://example.com/portfolio/iron-pulse-fitness", "https://example.com/services/broken-service"],
        evidence=[],
        fix_hint="Fix link."
    )
    h1_iss = TechnicalIssue(
        id="T-002",
        type="missing_h1",
        severity="medium",
        impact="Missing H1 weakens semantics.",
        effort="low",
        urls=["https://example.com/track"],
        evidence=[],
        fix_hint="Add H1."
    )
    canon_iss = TechnicalIssue(
        id="T-003",
        type="canonical_to_other",
        severity="medium",
        impact="Canonicals point away.",
        effort="low",
        urls=["https://example.com/page1", "https://example.com/page2", "https://example.com/page3"],
        evidence=[],
        fix_hint="Fix canonicals."
    )

    rep = StrategistAgent._run_deterministic([b_link_iss, h1_iss, canon_iss], [], [])
    
    b_tasks = [t for t in rep.tasks if "Fix broken link" in t.title]
    assert len(b_tasks) == 2
    assert "Fix broken link: /portfolio/iron-pulse-fitness" in [t.title for t in b_tasks]

    h1_tasks = [t for t in rep.tasks if "Add missing H1" in t.title]
    assert len(h1_tasks) == 1
    assert "Add missing H1: /track" in h1_tasks[0].title

    canon_tasks = [t for t in rep.tasks if "canonical_to_other" in t.title]
    assert len(canon_tasks) == 1
    assert "3 pages" in canon_tasks[0].title
    assert "page1" in canon_tasks[0].done_when and "page2" in canon_tasks[0].done_when


def test_strategist_group_tasks_show_real_totals_and_preview():
    """Tests that group tasks show the real total (e.g. 17 pages, start with these 3)."""
    from app.agents.strategist_agent import format_group_task_title, StrategistAgent
    from app.models.agent_schemas import TechnicalIssue

    # When count <= 3
    t3 = format_group_task_title("title_too_long", 3)
    assert "3 pages" in t3
    assert "start with" not in t3

    # When count > 3 (e.g. 17 pages)
    t17 = format_group_task_title("title_too_long", 17)
    assert "17 pages, start with these 3" in t17

    t17_meta = format_group_task_title("meta_too_long", 17)
    assert "17 pages, start with these 3" in t17_meta

    # Check that deterministic strategist formats 17 urls properly
    urls_17 = [f"https://example.com/page-{i}" for i in range(1, 18)]
    iss = TechnicalIssue(
        id="T-010",
        type="title_too_long",
        severity="low",
        impact="Titles exceed 60 chars.",
        effort="low",
        urls=urls_17,
        evidence=[],
        fix_hint="Shorten titles."
    )
    rep = StrategistAgent._run_deterministic([iss], [], [])
    assert len(rep.tasks) == 1
    assert "17 pages, start with these 3" in rep.tasks[0].title
    assert "page-1" in rep.tasks[0].done_when and "page-3" in rep.tasks[0].done_when


def test_anchors_full_h1_title_when_six_words_or_fewer():
    """Tests that anchor uses full H1/title when <= 6 words, avoids mid-sentence cuts, and verifier allows up to 6 words."""
    from app.agents.content_agent import clean_anchor_text, extract_candidate_anchor
    from app.agents.verifier import Verifier
    from app.models.agent_schemas import ContentAgentReport

    # 4-word title used in full
    cand = extract_candidate_anchor("Custom Next.js Web Development")
    assert cand == "Custom Next.js Web Development"
    assert clean_anchor_text(cand) == "Custom Next.js Web Development"

    # 6-word title used in full
    cand6 = extract_candidate_anchor("Full Stack Web Design Agency Services")
    assert cand6 == "Full Stack Web Design Agency Services"
    assert clean_anchor_text(cand6) == "Full Stack Web Design Agency Services"

    # > 6 words extracts first coherent phrase/clause without mid-sentence cuts
    cand_long = extract_candidate_anchor("Complete E-commerce Solutions for High Growth Businesses in 2026")
    words_long = cand_long.split()
    assert len(words_long) <= 6
    assert words_long[-1].lower() not in {"for", "in", "to", "and", "the", "a"}

    # Verifier accepts 6-word anchor
    link = InternalLinkSuggestion(
        source_url="https://example.com/about",
        target_url="https://example.com/services",
        anchor_text="Full Stack Web Design Agency Services",
        reason="Relevant topical terms"
    )
    crawl_pages = [
        {"url": "https://example.com/about", "status_code": 200, "text_terms": ["stack", "development", "services"]},
        {"url": "https://example.com/services", "status_code": 200, "text_terms": ["stack", "development", "services"], "title": "Full Stack Web Design Agency Services"}
    ]
    agent_rep = ContentAgentReport(briefs=[], rewrites=[], internal_links=[link], summary="Test")
    rep = Verifier.verify_content_outputs(agent_rep, crawl_pages, [], {})
    assert rep.verified_count == 1
    assert rep.rejected_count == 0


@pytest.mark.asyncio
async def test_crawler_failed_fetch_retry_and_incomplete_logging():
    """Tests that crawler retries failed fetches once, logs persistent failures, and marks crawl_incomplete."""
    from unittest.mock import patch
    from app.crawler.engine import AsyncCrawler

    crawler = AsyncCrawler("job-test-fail", "https://example.com", max_pages=5)

    # Mock client.get to simulate a 500 error that fails both initial and retry
    mock_resp_500 = AsyncMock()
    mock_resp_500.status_code = 500
    mock_resp_500.headers = {}
    mock_resp_500.url = "https://example.com/failing-page"
    mock_resp_500.text = "Server Error"

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp_500

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await crawler._crawl_page(mock_client, "https://example.com/failing-page")

    # Both initial and retry should have been attempted (get called twice)
    assert mock_client.get.call_count == 2
    # Failed fetch should be recorded in failed_fetches
    assert len(crawler.failed_fetches) == 1
    assert crawler.failed_fetches[0]["url"] == "https://example.com/failing-page"
    assert crawler.failed_fetches[0]["reason"] == "HTTP 500"


@pytest.mark.asyncio
async def test_psi_key_missing_reports_exact_error_and_status():
    """Tests that when PSI_API_KEY is missing, PSI reports 'key missing' exact error."""
    from unittest.mock import patch
    from app.services.pagespeed import run_psi_for_url
    from app.core.config import settings

    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    mock_resp_429.text = '{"error": {"code": 429, "message": "Quota exceeded"}}'

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp_429

    with patch.object(settings, "PSI_API_KEY", None), \
         patch("app.core.db.DBManager.get_psi_cached", return_value=None), \
         patch("app.core.db.DBManager.save_psi_result"), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        res = await run_psi_for_url(mock_client, "job-psi-1", "https://example.com", "mobile", max_retries=1)

    assert res["performance_score"] is None
    assert "key missing" in res["error"]


@pytest.mark.asyncio
async def test_psi_429_retries_with_backoff_and_succeeds():
    """Tests that on 429/5xx, PSI retries with backoff and populates results on success."""
    from unittest.mock import patch
    from app.services.pagespeed import run_psi_for_url
    from app.core.config import settings

    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    mock_resp_429.text = '{"error": {"code": 429, "message": "Rate limited"}}'

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = {
        "lighthouseResult": {
            "categories": {"performance": {"score": 0.95}},
            "audits": {
                "largest-contentful-paint": {"numericValue": 1200},
                "cumulative-layout-shift": {"numericValue": 0.02},
                "total-blocking-time": {"numericValue": 50},
                "first-contentful-paint": {"numericValue": 800},
                "server-response-time": {"numericValue": 120}
            }
        }
    }

    mock_client = AsyncMock()
    # 429 on attempt 0, 200 on attempt 1
    mock_client.get.side_effect = [mock_resp_429, mock_resp_200]

    with patch.object(settings, "PSI_API_KEY", "test-key"), \
         patch("app.core.db.DBManager.get_psi_cached", return_value=None), \
         patch("app.core.db.DBManager.save_psi_result"), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await run_psi_for_url(mock_client, "job-psi-2", "https://example.com", "desktop", max_retries=3)

    assert mock_client.get.call_count == 2
    assert mock_sleep.call_count == 1
    assert res["performance_score"] == 95
    assert res["error"] is None
    assert res["lcp_ms"] == 1200.0


@pytest.mark.asyncio
async def test_psi_429_exhausted_retries_reports_quota_exceeded():
    """Tests that when PSI retries are exhausted with an API key, it reports 'quota exceeded'."""
    from unittest.mock import patch
    from app.services.pagespeed import run_psi_for_url
    from app.core.config import settings

    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    mock_resp_429.text = '{"error": {"code": 429, "message": "Quota exceeded"}}'

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp_429

    with patch.object(settings, "PSI_API_KEY", "real-valid-key"), \
         patch("app.core.db.DBManager.get_psi_cached", return_value=None), \
         patch("app.core.db.DBManager.save_psi_result"), \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await run_psi_for_url(mock_client, "job-psi-3", "https://example.com", "mobile", max_retries=3)

    # 1 initial + 3 retries = 4 calls
    assert mock_client.get.call_count == 4
    assert mock_sleep.call_count == 3
    assert res["performance_score"] is None
    assert "quota exceeded" in res["error"]


def test_never_cache_failed_psi_results():
    """Tests that DBManager.get_psi_cached never returns failed PSI results."""
    from app.core.db import DBManager
    import uuid

    test_url = f"https://example.com/test-cache-{uuid.uuid4().hex[:6]}"
    now_iso = datetime.now(timezone.utc).isoformat()

    # Save a failed PSI result
    failed_data = {
        "job_id": "test-job-fail",
        "url": test_url,
        "strategy": "mobile",
        "performance_score": None,
        "lcp_ms": None,
        "cls": None,
        "inp_or_tbt_ms": None,
        "fcp_ms": None,
        "ttfb_ms": None,
        "raw_json": None,
        "error": "PSI quota exceeded / rate limited",
        "fetched_at": now_iso
    }
    DBManager.save_psi_result(failed_data)

    # get_psi_cached must return None for failed results
    cached = DBManager.get_psi_cached(test_url, "mobile")
    assert cached is None, "Failed PSI results must NEVER be returned from cache"

    # Save a successful PSI result
    success_data = {
        "job_id": "test-job-success",
        "url": test_url,
        "strategy": "mobile",
        "performance_score": 98,
        "lcp_ms": 1100.0,
        "cls": 0.01,
        "inp_or_tbt_ms": 40.0,
        "fcp_ms": 750.0,
        "ttfb_ms": 100.0,
        "raw_json": {"test": True},
        "error": None,
        "fetched_at": now_iso
    }
    DBManager.save_psi_result(success_data)

    # get_psi_cached must now return the successful result
    cached_ok = DBManager.get_psi_cached(test_url, "mobile")
    assert cached_ok is not None
    assert cached_ok["performance_score"] == 98
    assert cached_ok["error"] is None
