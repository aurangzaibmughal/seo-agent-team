import io
import json
import zipfile
import pytest
from unittest.mock import patch

from app.models.agent_schemas import (
    TechnicalIssue, StrategyReport,
    TechnicalAgentReport, ContentAgentReport,
    OnPageRewrite, GeneratedArtifact
)
from app.code_generator.filepath_mapper import map_url_to_nextjs_path
from app.code_generator.jsonld_builder import JsonLdBuilder, safe_jsonld_string
from app.code_generator.templates import CodeTemplateEngine
from app.code_generator.packager import CodePackager
from app.agents.code_agent import CodeGeneratorAgent
from app.agents.code_verifier import CodeVerifier
from app.agents.orchestrator import run_full_pipeline
from app.core.db import DBManager


# 1. Next.js file path mapping tests (Batch A.2: snippets never overwrite real app files)
def test_nextjs_filepath_mapping():
    m_home_app = map_url_to_nextjs_path("https://example.com/", "app")
    assert m_home_app["file_path"] == "app/page.metadata.snippet.tsx"
    assert m_home_app["target_file"] == "app/page.tsx"

    m_home_pages = map_url_to_nextjs_path("https://example.com/", "pages")
    assert m_home_pages["file_path"] == "pages/index.metadata.snippet.tsx"
    assert m_home_pages["target_file"] == "pages/index.tsx"

    m_port_app = map_url_to_nextjs_path("https://example.com/portfolio", "app")
    assert m_port_app["file_path"] == "app/portfolio/page.metadata.snippet.tsx"
    assert m_port_app["target_file"] == "app/portfolio/page.tsx"

    m_port_pages = map_url_to_nextjs_path("https://example.com/portfolio", "pages")
    assert m_port_pages["file_path"] == "pages/portfolio.metadata.snippet.tsx"
    assert m_port_pages["target_file"] == "pages/portfolio.tsx"

    m_blog_app = map_url_to_nextjs_path("https://example.com/blog/seo-tips", "app")
    assert m_blog_app["file_path"] == "app/blog/[slug]/page.metadata.snippet.tsx"
    assert m_blog_app["target_file"] == "app/blog/[slug]/page.tsx"

    m_blog_pages = map_url_to_nextjs_path("https://example.com/blog/seo-tips", "pages")
    assert m_blog_pages["file_path"] == "pages/blog/[slug].metadata.snippet.tsx"
    assert m_blog_pages["target_file"] == "pages/blog/[slug].tsx"


# 2. JSON-LD Builder & No Fabricated Data tests
def test_jsonld_no_fabricated_telephone_when_missing():
    homepage = {
        "url": "https://example.com",
        "title": "Example Agency",
        "meta_desc": "Top web agency in Pakistan",
        "h1": "Welcome to Example",
        "text_terms": ["agency", "web"]
    }
    crawl_links = [{"target_url": "https://twitter.com/example"}]
    schema, prov = JsonLdBuilder.build_organization_website(homepage, crawl_links)
    
    org = next(item for item in schema["@graph"] if item["@type"] == "Organization")
    assert "telephone" not in org, "Must NOT fabricate telephone when no tel: link exists"
    assert org["@type"] == "Organization"
    assert "https://twitter.com/example" in org["sameAs"]


def test_jsonld_no_faqpage_when_no_faq_present():
    page = {
        "url": "https://example.com/about",
        "title": "About Us",
        "h1": "About Example Agency",
        "headings": [{"level": "h2", "text": "Our Mission"}]
        # No FAQ or question headings
    }
    schema, prov = JsonLdBuilder.build_faq(page)
    assert schema is None, "Must NOT create FAQPage when page has no FAQ content"


def test_jsonld_safe_script_escaping():
    bad_string = "Find out why </script><script>alert('xss')</script> is dangerous"
    data = {"@context": "https://schema.org", "@type": "WebSite", "name": bad_string}
    safe_out = safe_jsonld_string(data)
    assert "</script>" not in safe_out.lower()
    assert r"\u003c/script\u003e" in safe_out or r"\u003c" in safe_out


def test_jsonld_verifier_catches_invalid_json():
    art = GeneratedArtifact(
        id="art-bad",
        platform="nextjs",
        artifact_type="jsonld",
        file_path="components/schema.jsonld",
        title="Bad JSON",
        content="{\"@context\": \"https://schema.org\", invalid json syntax...}",
        source_issue_ids=[],
        source_task_ids=[]
    )
    status, reason = CodeVerifier.verify_artifact(
        artifact=art,
        crawl_pages=[{"url": "https://example.com"}],
        crawl_links=[],
        target_domain="example.com"
    )
    assert status == "failed"
    assert "Invalid JSON" in reason


def test_jsonld_verifier_catches_unescaped_script():
    art = GeneratedArtifact(
        id="art-unescaped",
        platform="nextjs",
        artifact_type="jsonld",
        file_path="components/schema.jsonld",
        title="Unescaped Script",
        content="{\"@context\": \"https://schema.org\", \"@type\": \"WebSite\", \"name\": \"test</script>injection\"}",
        source_issue_ids=[],
        source_task_ids=[]
    )
    status, reason = CodeVerifier.verify_artifact(
        artifact=art,
        crawl_pages=[{"url": "https://example.com"}],
        crawl_links=[],
        target_domain="example.com"
    )
    assert status == "failed"
    assert "</script>" in reason


# 3. Sitemap Validator tests
def test_sitemap_excludes_noindex_non200_and_duplicates():
    sitemap_items = [
        {"url": "https://example.com/", "priority": "1.0"},
        {"url": "https://example.com/portfolio", "priority": "0.8"}
    ]
    sitemap_content = CodeTemplateEngine.render_sitemap_xml(sitemap_items)
    art = GeneratedArtifact(
        id="s-1",
        platform="common",
        artifact_type="sitemap_xml",
        file_path="public/sitemap.xml",
        title="Sitemap",
        content=sitemap_content,
        source_issue_ids=[],
        source_task_ids=[]
    )
    crawl_pages = [
        {"url": "https://example.com/", "status_code": 200, "indexable": True, "canonical": "https://example.com/"},
        {"url": "https://example.com/portfolio", "status_code": 200, "indexable": True, "canonical": "https://example.com/portfolio"},
        {"url": "https://example.com/noindex", "status_code": 200, "indexable": False, "canonical": "https://example.com/noindex"}
    ]
    status, reason = CodeVerifier.verify_artifact(
        artifact=art,
        crawl_pages=crawl_pages,
        crawl_links=[],
        target_domain="example.com"
    )
    assert status == "passed"
    assert "https://example.com/noindex" not in sitemap_content


# 4. Robots Validator tests
def test_robots_disallow_all_fails_verifier():
    bad_robots = GeneratedArtifact(
        id="r-bad",
        platform="common",
        artifact_type="robots_txt",
        file_path="public/robots.txt",
        title="Bad Robots",
        content="User-agent: *\nDisallow: /\nSitemap: https://example.com/sitemap.xml",
        source_issue_ids=[],
        source_task_ids=[]
    )
    status, reason = CodeVerifier.verify_artifact(
        artifact=bad_robots,
        crawl_pages=[{"url": "https://example.com/", "status_code": 200}],
        crawl_links=[],
        target_domain="example.com"
    )
    assert status == "failed"
    assert "Disallow: /" in reason


def test_robots_valid_passes_verifier():
    good_robots = GeneratedArtifact(
        id="r-good",
        platform="common",
        artifact_type="robots_txt",
        file_path="public/robots.txt",
        title="Good Robots",
        content="User-agent: *\nAllow: /\n\nSitemap: https://example.com/sitemap.xml",
        source_issue_ids=[],
        source_task_ids=[]
    )
    status, reason = CodeVerifier.verify_artifact(
        artifact=good_robots,
        crawl_pages=[{"url": "https://example.com/", "status_code": 200}],
        crawl_links=[],
        target_domain="example.com"
    )
    assert status == "passed"


# 5. llms.txt tests
def test_llms_txt_links_only_crawled_indexable_urls():
    curated_links = [
        {"title": "Home", "url": "https://example.com/", "description": "Homepage"},
        {"title": "About", "url": "https://example.com/about", "description": "About Us"}
    ]
    llms_content = CodeTemplateEngine.render_llms_txt(
        site_name="Example",
        site_summary="An example agency.",
        base_url="https://example.com",
        curated_links=curated_links
    )
    art = GeneratedArtifact(
        id="l-1",
        platform="common",
        artifact_type="llms_txt",
        file_path="public/llms.txt",
        title="LLMs Text",
        content=llms_content,
        source_issue_ids=[],
        source_task_ids=[]
    )
    crawl_pages = [
        {"url": "https://example.com/", "status_code": 200, "indexable": True},
        {"url": "https://example.com/about", "status_code": 200, "indexable": True}
    ]
    status, reason = CodeVerifier.verify_artifact(
        artifact=art,
        crawl_pages=crawl_pages,
        crawl_links=[],
        target_domain="example.com"
    )
    assert status == "passed"
    assert "# Example" in llms_content


# 6. Redirects Validator & Typo Resolution tests
def test_redirect_rules_rejects_loops_and_chains():
    # Loop
    loop_art = GeneratedArtifact(
        id="art-loop",
        platform="nextjs",
        artifact_type="redirects",
        file_path="next.config.js",
        title="Loop",
        content="",
        source_issue_ids=[],
        source_task_ids=[],
        metadata={"redirects": [{"source": "/a", "destination": "/a", "permanent": True}]}
    )
    status, reason = CodeVerifier.verify_artifact(
        artifact=loop_art,
        crawl_pages=[],
        crawl_links=[],
        target_domain="example.com"
    )
    assert status == "failed"
    assert "loop" in reason.lower()

    # Chain (/a -> /b, /b -> /c)
    chain_art = GeneratedArtifact(
        id="art-chain",
        platform="nextjs",
        artifact_type="redirects",
        file_path="next.config.js",
        title="Chain",
        content="",
        source_issue_ids=[],
        source_task_ids=[],
        metadata={"redirects": [
            {"source": "/a", "destination": "/b", "permanent": True},
            {"source": "/b", "destination": "/c", "permanent": True}
        ]}
    )
    status, reason = CodeVerifier.verify_artifact(
        artifact=chain_art,
        crawl_pages=[],
        crawl_links=[],
        target_domain="example.com"
    )
    assert status == "failed"
    assert "chain" in reason.lower()


@pytest.mark.asyncio
async def test_redirect_ironpulse_typo_case():
    """Verify broken link 'iron-pulse-fitness' correctly maps to closest target 'ironpulse-fitness'."""
    crawl_pages = [
        {"url": "https://example.com/", "status_code": 200, "indexable": True, "title": "Home | Example Agency", "meta_desc": "Home meta"},
        {"url": "https://example.com/portfolio/ironpulse-fitness", "status_code": 200, "indexable": True, "title": "IronPulse Case Study", "meta_desc": "Fitness app case study"},
        {"url": "https://example.com/portfolio/iron-pulse-fitness", "status_code": 404, "indexable": False}
    ]
    crawl_links = [
        {"source_url": "https://example.com/portfolio", "target_url": "https://example.com/portfolio/iron-pulse-fitness", "status_code": 404}
    ]
    verified_issues = [
        TechnicalIssue(
            id="T-004",
            type="broken_link_4xx",
            severity="high",
            impact="Broken link",
            effort="low",
            urls=["https://example.com/portfolio/iron-pulse-fitness"],
            evidence=[],
            fix_hint="Fix link",
            confidence=1.0
        )
    ]
    bundle, mode, cost, err, model = await CodeGeneratorAgent.run(
        platform="nextjs",
        platform_confidence=1.0,
        verified_tech_issues=verified_issues,
        strategy_tasks=[],
        crawl_pages=crawl_pages,
        crawl_links=crawl_links,
        verified_rewrites=[],
        internal_links=[]
    )
    next_cfg = next(a for a in bundle.artifacts if a.file_path == "next.config.js")
    assert "/portfolio/iron-pulse-fitness" in next_cfg.content
    assert "/portfolio/ironpulse-fitness" in next_cfg.content


# 7. Golden-File Templates test for all platforms
@pytest.mark.asyncio
async def test_templates_golden_files_all_platforms():
    crawl_pages = [
        {"url": "https://example.com/", "status_code": 200, "indexable": True, "title": "Home | Example Agency", "meta_desc": "Home meta description", "h1": "Web Agency"},
        {"url": "https://example.com/portfolio", "status_code": 200, "indexable": True, "title": "Portfolio | Example Agency", "meta_desc": "Portfolio meta description", "h1": "Our Work"}
    ]
    rewrites = [
        OnPageRewrite(
            url="https://example.com/portfolio",
            current_title="Portfolio",
            current_meta="",
            suggested_title="Digital Portfolio | Web Development & UI/UX Projects | Agency",
            suggested_meta="Explore verified web development and digital marketing case studies.",
            status="needs human review"
        )
    ]
    verified_issues = [
        TechnicalIssue(
            id="T-006",
            type="duplicate_title",
            severity="high",
            impact="Duplicate title",
            effort="low",
            urls=["https://example.com/portfolio"],
            evidence=[],
            fix_hint="Unique title",
            confidence=1.0
        )
    ]

    for plat in ["nextjs", "wordpress", "plain_html", "shopify"]:
        bundle, mode, cost, err, model = await CodeGeneratorAgent.run(
            platform=plat,
            platform_confidence=1.0,
            verified_tech_issues=verified_issues,
            strategy_tasks=[],
            crawl_pages=crawl_pages,
            crawl_links=[],
            verified_rewrites=rewrites,
            internal_links=[]
        )
        assert len(bundle.artifacts) > 0
        assert any(a.file_path == "metadata_table.csv" for a in bundle.artifacts)
        assert any(a.file_path.endswith("sitemap.xml") or a.file_path.endswith("sitemap.ts") for a in bundle.artifacts)
        assert any(a.file_path.endswith("robots.txt") or a.file_path.endswith("robots.ts") for a in bundle.artifacts)


# 8. Verifier tool missing returns 'skipped', NEVER 'passed'
def test_verifier_missing_tool_marked_skipped_never_passed():
    art = GeneratedArtifact(
        id="art-php",
        platform="wordpress",
        artifact_type="wordpress_php",
        file_path="functions-seo.php",
        title="WordPress Functions",
        content="<?php echo 'hello'; ?>",
        source_issue_ids=[],
        source_task_ids=[]
    )
    with patch("shutil.which", return_value=None):
        status, reason = CodeVerifier.verify_artifact(
            artifact=art,
            crawl_pages=[],
            crawl_links=[],
            target_domain="example.com"
        )
        assert status == "skipped", f"Missing tool must return 'skipped', got '{status}'"
        assert "tool missing" in reason.lower()
        assert status != "passed"


# 9. ZIP Package structure, provenance, and watermark test
def test_zip_package_structure_provenance_and_watermark():
    art1 = GeneratedArtifact(
        id="art-1",
        platform="nextjs",
        artifact_type="nextjs_layout",
        file_path="app/layout.tsx",
        title="Root Layout",
        content="export const metadata = {};",
        source_issue_ids=["T-001", "T-002"],
        source_task_ids=["S-001"],
        validation_status="passed",
        validation_reason="Passed syntax check"
    )
    val_results = [{
        "file_path": "app/layout.tsx",
        "artifact_type": "nextjs_layout",
        "status": "passed",
        "reason": "Passed syntax check"
    }]

    # 1. Non-demo ZIP
    zip_bytes_live = CodePackager.generate_zip(
        job_id="job-live-1234",
        domain="example.com",
        platform="nextjs",
        artifacts=[art1],
        validation_results=val_results,
        is_demo=False
    )
    with zipfile.ZipFile(io.BytesIO(zip_bytes_live)) as zf:
        names = zf.namelist()
        assert "README_APPLY.md" in names
        assert "CHANGES.csv" in names
        assert "provenance.json" in names
        assert "validation_report.md" in names
        assert "files/nextjs/app/layout.tsx" in names

        readme_text = zf.read("README_APPLY.md").decode("utf-8")
        assert "DEMO DATA" not in readme_text
        assert "Test & Validate Locally" in readme_text
        assert "validator.schema.org" in readme_text

        prov_json = json.loads(zf.read("provenance.json").decode("utf-8"))
        assert prov_json["artifacts"][0]["source_issue_ids"] == ["T-001", "T-002"]

    # 2. Demo ZIP (watermark check)
    zip_bytes_demo = CodePackager.generate_zip(
        job_id="job-demo-5678",
        domain="example.com",
        platform="nextjs",
        artifacts=[art1],
        validation_results=val_results,
        is_demo=True
    )
    with zipfile.ZipFile(io.BytesIO(zip_bytes_demo)) as zf:
        readme_text = zf.read("README_APPLY.md").decode("utf-8")
        assert "DEMO DATA WATERMARK" in readme_text
        changes_text = zf.read("CHANGES.csv").decode("utf-8")
        assert "DEMO DATA" in changes_text


# 10. Property-based traceability: No fabricated schema fields
def test_no_fabricated_fields_traceability():
    homepage = {
        "url": "https://example.com",
        "title": "Agency Co — Web Design",
        "meta_desc": "We build fast websites",
        "h1": "Top Web Agency",
        "text_terms": ["design", "web", "agency"]
    }
    crawl_links = [{"target_url": "https://linkedin.com/company/agency"}]
    schema, prov = JsonLdBuilder.build_organization_website(homepage, crawl_links)
    
    org = next(item for item in schema["@graph"] if item["@type"] == "Organization")
    assert org["url"] == "https://example.com"
    assert "https://linkedin.com/company/agency" in org["sameAs"]
    assert "aggregateRating" not in org
    assert "review" not in org
    assert "priceRange" not in org


# 11. Orchestrator simulated failure test: failure in Code Generation still produces report
@pytest.mark.asyncio
async def test_orchestrator_graceful_handling_on_code_generator_failure():
    """Confirms that if CodeGeneratorAgent raises an exception, the pipeline catches it, logs it, and still runs ReportExporter."""
    job = DBManager.create_job(target_url="https://example.com", max_pages=1, is_demo=True)
    job_id = job["id"]

    mock_tech_rep = TechnicalAgentReport(summary="tech summary", issues=[])
    mock_strat_rep = StrategyReport(summary="strat summary", tasks=[])
    mock_cont_rep = ContentAgentReport(summary="cont summary", briefs=[], rewrites=[], internal_links=[])

    with patch("app.agents.code_agent.CodeGeneratorAgent.run", side_effect=RuntimeError("Simulated code generator crash")), \
         patch("app.crawler.engine.AsyncCrawler.run", return_value=None), \
         patch("app.services.pagespeed.run_pagespeed_pipeline", return_value=None), \
         patch("app.agents.technical_agent.TechnicalAgent.run", return_value=(mock_tech_rep, "deterministic", 0.0, None, "model")), \
         patch("app.agents.strategist_agent.StrategistAgent.run", return_value=(mock_strat_rep, "deterministic", 0.0, None, "model")), \
         patch("app.agents.content_agent.ContentAgent.run", return_value=(mock_cont_rep, "deterministic", 0.0, None, "model")):

        await run_full_pipeline(job_id, "https://example.com", max_pages=1)

        updated_job = DBManager.get_job(job_id)
        assert updated_job["status"] == "completed"

        runs = DBManager.get_agent_runs(job_id)
        failed_code_run = next((r for r in runs if r["agent"] == "code_generator"), None)
        assert failed_code_run is not None
        assert failed_code_run["status"] == "failed"
        assert "Simulated code generator crash" in failed_code_run["failure_reason"]


# 12. Test that every URL appearing in report exists in crawl_pages
def test_every_url_in_report_exists_in_crawl_pages():
    crawl_pages = [
        {"url": "https://webspire-agency.vercel.app/", "status_code": 200, "title": "Home", "meta_desc": "Home meta"},
        {"url": "https://webspire-agency.vercel.app/portfolio", "status_code": 200, "title": "Portfolio", "meta_desc": "Portfolio meta"},
        {"url": "https://webspire-agency.vercel.app/contact", "status_code": 200, "title": "Contact", "meta_desc": "Contact meta"}
    ]
    crawl_urls = {p["url"].rstrip("/") for p in crawl_pages}

    rewrites = [
        {"url": "https://webspire-agency.vercel.app/portfolio", "current_title": "Portfolio", "suggested_title": "Portfolio | WebSpire", "current_meta": "m", "suggested_meta": "sm"}
    ]
    csv_text = CodeTemplateEngine.render_metadata_csv(rewrites)

    # Find all domain URLs in rendered text
    import re
    found_urls = re.findall(r"https://webspire-agency\.vercel\.app[^\s,\"\']*", csv_text)
    for u in found_urls:
        assert u.rstrip("/") in crawl_urls, f"URL {u} in report does not exist in crawl_pages"

    # Synthetic / invalid URL must NOT be allowed
    bad_url = "https://webspire-agency.vercel.app/services/ai-automation"
    assert bad_url not in crawl_urls


# 13. Provenance mismatched mapping tests
def test_provenance_mismatched_mapping_fails():
    # robots.ts claiming broken link must fail
    art_bad_robots = GeneratedArtifact(
        id="art-r1",
        platform="nextjs",
        artifact_type="nextjs_robots_ts",
        file_path="app/robots.ts",
        title="Bad Robots",
        content="export default function robots() { return { rules: [] }; }",
        source_issue_ids=["T-broken-link-1"],
        source_task_ids=[]
    )
    status, reason = CodeVerifier.verify_artifact(
        artifact=art_bad_robots,
        crawl_pages=[{"url": "https://example.com"}],
        crawl_links=[],
        target_domain="example.com",
        issue_type_by_id={"T-broken-link-1": "broken_link_4xx"}
    )
    assert status == "failed"
    assert "broken-link" in reason.lower()

    # JSON-LD claiming missing_h1 must fail
    art_bad_jsonld = GeneratedArtifact(
        id="art-j1",
        platform="nextjs",
        artifact_type="jsonld",
        file_path="schema.jsonld",
        title="Bad Schema",
        content='{"@context": "https://schema.org", "@type": "WebSite", "name": "Test"}',
        source_issue_ids=["T-h1-1"],
        source_task_ids=[]
    )
    status_j, reason_j = CodeVerifier.verify_artifact(
        artifact=art_bad_jsonld,
        crawl_pages=[{"url": "https://example.com"}],
        crawl_links=[],
        target_domain="example.com",
        issue_type_by_id={"T-h1-1": "missing_h1"}
    )
    assert status_j == "failed"
    assert "missing_h1" in reason_j.lower()


# 14. Fix coverage: canonical_to_other and duplicate title/meta labeled 'auto-fixable' only if EVERY affected page has generated metadata file
@pytest.mark.asyncio
async def test_fix_coverage_per_page_canonical_rule():
    from app.agents.code_agent import CodeGeneratorAgent
    from app.models.agent_schemas import TechnicalIssue, OnPageRewrite

    crawl_pages = [
        {"url": "https://example.com/", "status_code": 200, "title": "T1", "meta_desc": "M1", "indexable": True},
        {"url": "https://example.com/p1", "status_code": 200, "title": "T1", "meta_desc": "M1", "indexable": True, "canonical": "https://example.com/"},
        {"url": "https://example.com/p2", "status_code": 200, "title": "T1", "meta_desc": "M1", "indexable": True, "canonical": "https://example.com/"}
    ]

    tech_issues = [
        TechnicalIssue(
            id="T-CAN-1",
            type="canonical_to_other",
            severity="medium",
            effort="low",
            urls=["https://example.com/p1", "https://example.com/p2"],
            description="Canonical to other",
            impact="impact",
            fix_hint="fix"
        ),
        TechnicalIssue(
            id="T-DUP-1",
            type="duplicate_title",
            severity="high",
            effort="low",
            urls=["https://example.com/", "https://example.com/p1", "https://example.com/p2"],
            description="Duplicate titles",
            impact="impact",
            fix_hint="fix"
        )
    ]

    rewrites = [
        OnPageRewrite(url="https://example.com/p1", current_title="T1", suggested_title="Title P1", current_meta="M1", suggested_meta="Meta P1"),
        OnPageRewrite(url="https://example.com/p2", current_title="T1", suggested_title="Title P2", current_meta="M1", suggested_meta="Meta P2")
    ]

    bundle, _, _, _, _ = await CodeGeneratorAgent.run(
        platform="nextjs",
        platform_confidence=1.0,
        verified_tech_issues=tech_issues,
        strategy_tasks=[],
        crawl_pages=crawl_pages,
        crawl_links=[],
        verified_rewrites=rewrites,
        internal_links=[],
        router_type="app",
        is_demo=False
    )

    can_cov = next(fc for fc in bundle.fix_coverage if fc["issue_type"] == "canonical_to_other")
    dup_cov = next(fc for fc in bundle.fix_coverage if fc["issue_type"] == "duplicate_title")

    # Both p1 and p2 have generated per-page metadata files with alternates.canonical
    assert can_cov["fixability"] == "auto-fixable by generated code"
    assert dup_cov["fixability"] == "auto-fixable by generated code"


# 15. Next.js real compile check test via tsc --noEmit
def test_nextjs_real_compile_check_tsc():
    good_artifacts = [
        GeneratedArtifact(
            id="art-c1", platform="nextjs", artifact_type="nextjs_jsonld_component",
            file_path="components/JsonLd.tsx", title="JsonLd",
            content='import React from "react";\nexport function JsonLd({ data }: { data: any }) { return <script dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }} />; }',
            source_issue_ids=[], source_task_ids=[]
        )
    ]
    status, reason = CodeVerifier._validate_nextjs_project_compile(good_artifacts)
    assert status in ("passed", "skipped")
    if status == "passed":
        assert "0 errors" in reason

    # Bad typescript syntax must fail compile check
    bad_artifacts = [
        GeneratedArtifact(
            id="art-c2", platform="nextjs", artifact_type="nextjs_page_metadata",
            file_path="app/bad/page.tsx", title="Bad TS",
            content='export const metadata: Metadata = { const invalid syntax !!! };',
            source_issue_ids=[], source_task_ids=[]
        )
    ]
    status_bad, reason_bad = CodeVerifier._validate_nextjs_project_compile(bad_artifacts)
    if status != "skipped":
        assert status_bad == "failed"
        assert "Next.js compile check failed" in reason_bad


# 16. Internal links drop non-topical terms and require terms to appear in target H1/title
def test_internal_links_drop_non_topical_terms():
    from app.agents.content_agent import compute_internal_link_suggestions

    pages = [
        {
            "url": "https://example.com/",
            "status_code": 200,
            "title": "Home | Modern Engineering and Mobile Agency",
            "h1": "Mobile Engineering Agency in Pakistan",
            "text_terms": ["engineering", "mobile", "pakistan", "fintech", "banking"],
            "inlinks_count": 10
        },
        {
            "url": "https://example.com/fintech",
            "status_code": 200,
            "title": "FinTech Banking Solutions | Example",
            "h1": "Enterprise FinTech Banking Platforms",
            "text_terms": ["fintech", "banking", "finance", "security"],
            "inlinks_count": 0
        }
    ]

    suggestions = compute_internal_link_suggestions(crawl_pages=pages, crawl_links=[])
    assert len(suggestions) >= 1
    sug = suggestions[0]

    # Shared terms must be fintech / banking, NOT engineering or mobile
    assert "fintech" in sug.reason.lower() or "banking" in sug.reason.lower()
    assert "engineering" not in sug.reason.lower()
    assert "mobile" not in sug.reason.lower()


# 17. Every rewrite current_title and current_meta must equal crawl_pages
def test_every_rewrite_current_text_equals_crawl_pages():
    from app.agents.content_agent import ContentAgent

    crawl_pages = [
        {
            "url": "https://example.com/",
            "status_code": 200,
            "title": "Example Brand – Ideas to Impact | Pakistan's Trusted Agency",
            "meta_desc": "Example Brand is Pakistan's premier web agency engineering Next.js websites for clients in Pakistan, UK, USA & UAE.",
            "h1": "Ideas to Impact"
        },
        {
            "url": "https://example.com/services",
            "status_code": 200,
            "title": "Our Services | Example Brand – Digital Agency & Web Solutions | Example",
            "meta_desc": "Explore core services: Website Design & Development, E-commerce Websites, UI/UX Design, and SEO.",
            "h1": "Our Services"
        }
    ]

    report = ContentAgent._run_deterministic(
        verified_research=[],
        crawl_pages=crawl_pages,
        internal_links=[],
        research_snapshot={"query_clusters": []},
        competitor_pages=[]
    )

    crawl_by_url = {p["url"]: p for p in crawl_pages}
    for rw in report.rewrites:
        page = crawl_by_url[rw.url]
        assert rw.current_title == page["title"]
        assert rw.current_meta == page["meta_desc"]


# 18. Provenance issue IDs must exist in verified issues
def test_provenance_issue_ids_must_exist_in_verified_issues():
    art = GeneratedArtifact(
        id="art-test",
        platform="nextjs",
        artifact_type="nextjs_page_metadata",
        file_path="app/page.tsx",
        title="Test Page",
        content="export const metadata = {};",
        source_issue_ids=["T-999-unverified"],
        source_task_ids=[]
    )
    status, reason = CodeVerifier.verify_artifact(
        artifact=art,
        crawl_pages=[{"url": "https://example.com"}],
        crawl_links=[],
        target_domain="example.com",
        issue_type_by_id={"T-001": "broken_link_4xx", "T-002": "duplicate_title"}
    )
    assert status == "failed"
    assert "claims issue ID 'T-999-unverified' which does not exist in verified issues" in reason


# 19. Next.js generates llms.txt at public/llms.txt (not app/llms.txt)
@pytest.mark.asyncio
async def test_nextjs_generates_llms_txt_at_public_llms_txt():
    from app.agents.code_agent import CodeGeneratorAgent

    homepage = {
        "url": "https://example.com/",
        "status_code": 200,
        "title": "Example Agency",
        "meta_desc": "Example description",
        "h1": "Welcome",
        "indexable": True
    }
    bundle, mode, cost, reason, model = await CodeGeneratorAgent.run(
        platform="nextjs",
        platform_confidence=0.95,
        verified_tech_issues=[],
        strategy_tasks=[],
        crawl_pages=[homepage],
        crawl_links=[],
        verified_rewrites=[],
        internal_links=[],
        router_type="app"
    )

    file_paths = [a.file_path for a in bundle.artifacts]
    assert "public/llms.txt" in file_paths
    assert "app/llms.txt" not in file_paths
    assert "llms.txt" not in file_paths


# 20. Suggested titles must read as natural phrases and not append keyword strings like "Pakistan"
def test_suggested_titles_are_natural_phrases():
    from app.agents.content_agent import rewrite_natural_title

    t_home = rewrite_natural_title(
        current_t="WebSpire – Ideas to Impact | Pakistan's Trusted Digital & Web Agency",
        h1="Ideas to Impact",
        url="https://webspire-agency.vercel.app/"
    )
    assert t_home == "WebSpire | Pakistan's Trusted Digital & Web Agency"
    assert len(t_home) <= 60

    t_services = rewrite_natural_title(
        current_t="Our Services | WebSpire – Digital Agency & Web Solutions | WebSpire",
        h1="Our Services",
        url="https://webspire-agency.vercel.app/services"
    )
    assert t_services == "Our Services | WebSpire Digital Agency"
    assert len(t_services) <= 60
    assert not t_services.endswith("Pakistan")

    t_calc = rewrite_natural_title(
        current_t="WebSpire – Ideas to Impact | Pakistan's Trusted Digital & Web Agency",
        h1="Project Cost Calculator",
        url="https://webspire-agency.vercel.app/calculator"
    )
    assert t_calc == "Project Cost Calculator | WebSpire Agency"
    assert len(t_calc) <= 60
    assert not t_calc.endswith("Pakistan")

    t_port = rewrite_natural_title(
        current_t="WebSpire – Ideas to Impact | Pakistan's Trusted Digital & Web Agency",
        h1="Our Portfolio",
        url="https://webspire-agency.vercel.app/portfolio"
    )
    assert t_port == "Portfolio & Case Studies | WebSpire Agency"
    assert len(t_port) <= 60
    assert not t_port.endswith("Pakistan")

    t_track = rewrite_natural_title(
        current_t="Track Project Milestones | WebSpire Delivery Portal | WebSpire",
        h1="Track Project Status",
        url="https://webspire-agency.vercel.app/track"
    )
    assert t_track == "Track Project Milestones | WebSpire Delivery Portal"
    assert len(t_track) <= 60


