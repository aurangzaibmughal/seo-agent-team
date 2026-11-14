import pytest
import re
import io
import json
import uuid
from uuid import uuid4

from app.agents.issue_rules import detect_issues_from_data
from app.agents.technical_agent import get_deterministic_severity
from app.agents.strategist_agent import HUMAN_ISSUE_LABELS
from app.agents.code_agent import CodeGeneratorAgent
from app.core.db import DBManager, get_sqlite_conn, init_db
from app.services.comparator import JobComparator
from app.code_generator.packager import CodePackager
from app.code_generator.templates import CodeTemplateEngine
from app.models.agent_schemas import (
    TechnicalIssue, GeneratedArtifact
)

def test_brand_repeated_in_title_detection_and_escalation():
    brand = "AcmeCorp"
    crawl_pages = [
        {
            "url": "https://demo-site.example.com/",
            "title": "AcmeCorp — Digital Agency & Web Solutions",
            "meta_desc": "Digital agency",
            "indexable": True,
            "status_code": 200,
            "links_out": 5
        },
        {
            "url": "https://demo-site.example.com/services",
            "title": "Our Services | AcmeCorp — Digital Agency & Web Solutions | AcmeCorp",
            "meta_desc": "Services description",
            "indexable": True,
            "status_code": 200,
            "links_out": 5
        },
        {
            "url": "https://demo-site.example.com/portfolio",
            "title": "Portfolio | AcmeCorp — Digital Agency & Web Solutions | AcmeCorp",
            "meta_desc": "Portfolio description",
            "indexable": True,
            "status_code": 200,
            "links_out": 5
        }
    ]
    detected = detect_issues_from_data(crawl_pages, [], {}, brand_name=brand)
    brand_rep_issues = [iss for iss in detected if iss.get("type") == "brand_repeated_in_title"]
    assert len(brand_rep_issues) == 2
    affected_urls = [u for iss in brand_rep_issues for u in iss["urls"]]
    assert "https://demo-site.example.com/services" in affected_urls
    assert "https://demo-site.example.com/portfolio" in affected_urls

    # Ratio is 2/3 = 66.7% (>= 30%), so severity escalates from medium to high
    sev = get_deterministic_severity("brand_repeated_in_title", len(affected_urls), len(crawl_pages))
    assert sev == "high"

    # Verify label in Strategist
    assert "brand_repeated_in_title" in HUMAN_ISSUE_LABELS
    assert "brand" in HUMAN_ISSUE_LABELS["brand_repeated_in_title"].lower()

def test_review_items_and_events_flow():
    init_db()

    job_id = f"test-job-m6-review-{uuid.uuid4().hex[:8]}"
    with get_sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO jobs (id, target_url, status, created_at, updated_at) VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            (job_id, "https://example.com", "completed")
        )
        conn.execute(
            "INSERT INTO crawl_pages (id, job_id, url, status_code, title, meta_desc, created_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
            (str(uuid.uuid4()), job_id, "https://example.com/about", 200, "About Us", "About page description")
        )

    # Populate review items via save_content_output
    DBManager.save_content_output(job_id, {
        "rewrites": [
            {
                "url": "https://example.com/about",
                "current_title": "About Us",
                "suggested_title": "About Our Agency | Leading Digital Team",
                "current_meta": "About page description",
                "suggested_meta": "Learn more about our agency mission and expert digital team.",
                "status": "needs human review"
            }
        ]
    })
    count = DBManager.populate_review_items_for_job(job_id)
    assert count >= 1

    items = DBManager.get_review_items(job_id)
    assert len(items) >= 1
    item = items[0]
    assert item["status"] == "pending"

    # Test approve
    updated_item = DBManager.update_review_item_status(item["id"], "approved", "Looks good")
    assert updated_item is not None
    assert updated_item["status"] == "approved"

    # Test valid edit
    edited_item = DBManager.edit_review_item(
        job_id=job_id,
        item_id=item["id"],
        edited_payload={"suggested_title": "Custom Clean Title", "suggested_meta": "Custom clean meta description within bounds."},
        reviewer_note="Shortened for clarity"
    )
    assert edited_item["status"] == "edited"
    assert edited_item["edited_payload"]["suggested_title"] == "Custom Clean Title"

    # Test invalid edit (> 60 chars title) raises ValueError
    with pytest.raises(ValueError) as excinfo:
        DBManager.edit_review_item(
            job_id=job_id,
            item_id=item["id"],
            edited_payload={"suggested_title": "A" * 75, "suggested_meta": "Valid meta"},
            reviewer_note="Too long"
        )
    assert "maximum 60" in str(excinfo.value)

    # Test review events log
    events = DBManager.get_review_events(job_id)
    assert len(events) >= 2
    actions = [e["action"] for e in events]
    assert "status_change_to_approved" in actions
    assert "edit" in actions

def test_comparator_later_crawl_has_fewer_pages_marks_not_rechecked():
    """Verify Rule 3:
    - Compare only URLs crawled in BOTH jobs.
    - Issues on URLs missing from later crawl are 'not re-checked', NEVER 'fixed'.
    - If pages drop by >= 20% or issues are not re-checked, mark comparison 'incomplete'.
    - Do NOT generate a narrative claiming issues were resolved.
    """
    init_db()

    job1 = f"job-before-comp-{uuid.uuid4().hex[:8]}"
    job2 = f"job-after-comp-{uuid.uuid4().hex[:8]}"

    with get_sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO jobs (id, target_url, status, pages_crawled, created_at, updated_at) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
            (job1, "https://example.com", "completed", 3)
        )
        conn.execute(
            "INSERT INTO jobs (id, target_url, status, pages_crawled, created_at, updated_at) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
            (job2, "https://example.com", "completed", 2)
        )
        # Job 1 crawled /p1, /p2, and /p3
        for p in ["/p1", "/p2", "/p3"]:
            conn.execute(
                "INSERT INTO crawl_pages (id, job_id, url, status_code, title, meta_desc, created_at) VALUES (?, ?, ?, 200, ?, ?, datetime('now'))",
                (str(uuid.uuid4()), job1, f"https://example.com{p}", f"Page {p}", "meta")
            )
        # Job 2 ONLY crawled /p1 and /p2 (omitted /p3!)
        for p in ["/p1", "/p2"]:
            conn.execute(
                "INSERT INTO crawl_pages (id, job_id, url, status_code, title, meta_desc, created_at) VALUES (?, ?, ?, 200, ?, ?, datetime('now'))",
                (str(uuid.uuid4()), job2, f"https://example.com{p}", f"Page {p}", "meta")
            )

    # Job 1 issues:
    # - missing_h1 on /p1 (resolved in job 2 -> FIXED)
    # - duplicate_title on /p2 (persists in job 2 -> UNCHANGED)
    # - title_too_long on /p3 (URL omitted from job 2 -> MUST BE 'not_rechecked', NEVER 'fixed'!)
    DBManager.save_agent_run({
        "job_id": job1,
        "agent": "verifier",
        "status": "done",
        "output_json": json.dumps({
            "verified_issues": [
                {"id": "I-1", "type": "missing_h1", "severity": "high", "impact": "Missing H1", "effort": "low", "urls": ["https://example.com/p1"], "evidence": [], "fix_hint": "Add H1", "confidence": 1.0},
                {"id": "I-2", "type": "duplicate_title", "severity": "medium", "impact": "Dup title", "effort": "low", "urls": ["https://example.com/p2"], "evidence": [], "fix_hint": "Unique title", "confidence": 1.0},
                {"id": "I-3", "type": "title_too_long", "severity": "medium", "impact": "Title long", "effort": "low", "urls": ["https://example.com/p3"], "evidence": [], "fix_hint": "Shorten title", "confidence": 1.0}
            ]
        })
    })

    # Job 2 issues:
    # - duplicate_title persists on /p2
    # - new issue on /p1: missing_meta_description
    DBManager.save_agent_run({
        "job_id": job2,
        "agent": "verifier",
        "status": "done",
        "output_json": json.dumps({
            "verified_issues": [
                {"id": "I-4", "type": "duplicate_title", "severity": "medium", "impact": "Dup title", "effort": "low", "urls": ["https://example.com/p2"], "evidence": [], "fix_hint": "Unique title", "confidence": 1.0},
                {"id": "I-5", "type": "missing_meta_description", "severity": "low", "impact": "Missing meta", "effort": "low", "urls": ["https://example.com/p1"], "evidence": [], "fix_hint": "Add meta", "confidence": 1.0}
            ]
        })
    })

    comp = JobComparator.compare(job1, job2)

    # 1. /p3 was not crawled -> must be in not_rechecked, NEVER in fixed
    assert comp["issues"]["not_rechecked_count"] == 1
    assert comp["issues"]["not_rechecked"][0]["url"] == "https://example.com/p3"
    assert comp["issues"]["not_rechecked"][0]["type"] == "title_too_long"

    # 2. Only /p1 (missing_h1) was crawled in both and no longer present -> fixed
    assert comp["issues"]["fixed_count"] == 1
    assert comp["issues"]["fixed"][0]["type"] == "missing_h1"

    # 3. /p2 (duplicate_title) crawled in both and still present -> unchanged
    assert comp["issues"]["unchanged_count"] == 1
    assert comp["issues"]["unchanged"][0]["type"] == "duplicate_title"

    # 4. /p1 (missing_meta_description) is new -> new
    assert comp["issues"]["new_count"] == 1
    assert comp["issues"]["new"][0]["type"] == "missing_meta_description"

    # 5. Incomplete flag and cautious narrative
    assert comp["is_incomplete"] is True
    assert "INCOMPLETE" in comp["narrative"]
    assert "no conclusive fix claims can be verified" in comp["narrative"].lower()

@pytest.mark.asyncio
async def test_code_generator_short_page_titles_and_next_config():
    """Verify Rule 6:
    - When title template is generated, page titles must be short ('Our Services'),
      without repeating brand name.
    - next.config.js is always generated for Next.js.
    - Emits snippet files (*.metadata.snippet.tsx) that do not overwrite app files.
    """
    crawl_pages = [
        {"url": "https://demo-site.example.com/", "status_code": 200, "indexable": True, "title": "AcmeCorp — Ideas to Impact", "meta_desc": "Agency", "h1": "Web Agency"},
        {"url": "https://demo-site.example.com/services", "status_code": 200, "indexable": True, "title": "Our Services | AcmeCorp — Digital Agency | AcmeCorp", "meta_desc": "Services", "h1": "Our Services"},
        {"url": "https://demo-site.example.com/portfolio", "status_code": 200, "indexable": True, "title": "AcmeCorp — Ideas to Impact | Pakistan's Trusted Agency", "meta_desc": "Portfolio", "h1": "Portfolio"}
    ]
    verified_issues = [
        TechnicalIssue(
            id="T-003",
            type="brand_repeated_in_title",
            severity="high",
            impact="Brand repeated",
            effort="low",
            urls=["https://demo-site.example.com/services"],
            evidence=[],
            fix_hint="Shorten title",
            confidence=1.0
        ),
        TechnicalIssue(
            id="T-004",
            type="canonical_to_other",
            severity="medium",
            impact="Canonical to other",
            effort="low",
            urls=["https://demo-site.example.com/portfolio"],
            evidence=[],
            fix_hint="301 redirect",
            confidence=1.0
        )
    ]

    bundle, mode, cost, err, model = await CodeGeneratorAgent.run(
        platform="nextjs",
        platform_confidence=1.0,
        verified_tech_issues=verified_issues,
        strategy_tasks=[],
        crawl_pages=crawl_pages,
        crawl_links=[],
        verified_rewrites=[],
        internal_links=[]
    )

    art_map = {a.file_path: a for a in bundle.artifacts}

    # 1. next.config.js must be present
    assert "next.config.js" in art_map
    assert "async redirects()" in art_map["next.config.js"].content

    # 2. app/services/page.metadata.snippet.tsx must have short title 'Our Services'
    assert "app/services/page.metadata.snippet.tsx" in art_map
    serv_content = art_map["app/services/page.metadata.snippet.tsx"].content
    assert "title: 'Our Services'" in serv_content
    assert "AcmeCorp" not in serv_content.split("title:")[1].split(",")[0]
    assert "MERGE into your existing" in serv_content
    assert "export default function Page" not in serv_content

    # 3. app/portfolio/page.metadata.snippet.tsx must have short title 'Portfolio'
    assert "app/portfolio/page.metadata.snippet.tsx" in art_map
    port_content = art_map["app/portfolio/page.metadata.snippet.tsx"].content
    assert "title: 'Portfolio'" in port_content
    assert "AcmeCorp" not in port_content.split("title:")[1].split(",")[0]
    assert "MERGE into your existing" in port_content
    assert "export default function Page" not in port_content

def test_text_extraction_nested_spans():
    """Batch A.2 Item 2: Text extraction must join adjacent tags with a space."""
    from app.crawler.parser import extract_page_data

    html_1 = "<html><body><h1>Built to<span>Grow</span></h1></body></html>"
    p1 = extract_page_data(html_1, "https://example.com/test1")
    assert p1["h1"] == "Built to Grow"

    html_2 = "<html><body><h1>Our Creative <span>Work</span></h1></body></html>"
    p2 = extract_page_data(html_2, "https://example.com/test2")
    assert p2["h1"] == "Our Creative Work"

    html_3 = "<html><head><title>Page<span>Title</span> | Brand</title></head><body><a href='/link'>Click<span>Here</span>Now</a></body></html>"
    p3 = extract_page_data(html_3, "https://example.com/test3")
    assert p3["title"] == "Page Title | Brand"
    assert p3["links_with_anchors"][0]["anchor_text"] == "Click Here Now"

@pytest.mark.asyncio
async def test_portfolio_meta_uniqueness_and_similarity():
    """Batch A.2 Item 3: /portfolio title must be 'Portfolio'; meta must describe portfolio
    and have pairwise similarity below 0.60 across all generated metas.
    """
    import difflib

    crawl_pages = [
        {"url": "https://demo-site.example.com/", "status_code": 200, "indexable": True, "title": "AcmeCorp — Ideas to Impact", "meta_desc": "AcmeCorp is a full-service web engineering agency providing custom application development.", "h1": "Web Agency"},
        {"url": "https://demo-site.example.com/services", "status_code": 200, "indexable": True, "title": "Services", "meta_desc": "Full cycle web development, UI/UX architecture, cloud solutions, and organic search optimization.", "h1": "Our Services"},
        {"url": "https://demo-site.example.com/portfolio", "status_code": 200, "indexable": True, "title": "Portfolio", "meta_desc": "Our Creative Work", "h1": "Our Creative Work"}
    ]

    bundle, mode, cost, err, model = await CodeGeneratorAgent.run(
        platform="nextjs",
        platform_confidence=1.0,
        verified_tech_issues=[],
        strategy_tasks=[],
        crawl_pages=crawl_pages,
        crawl_links=[],
        verified_rewrites=[],
        internal_links=[]
    )

    art_map = {a.file_path: a for a in bundle.artifacts}
    port_art = art_map.get("app/portfolio/page.metadata.snippet.tsx")
    assert port_art is not None
    assert "title: 'Portfolio'" in port_art.content

    # Extract all descriptions from snippet artifacts
    metas = []
    for art in bundle.artifacts:
        if art.file_path.endswith(".metadata.snippet.tsx"):
            desc_match = re.search(r"description:\s*'([^']+)'", art.content)
            if desc_match:
                metas.append((art.file_path, desc_match.group(1)))

    assert len(metas) >= 2
    # Verify pairwise similarity < 0.60
    for i in range(len(metas)):
        for j in range(i + 1, len(metas)):
            f1, m1 = metas[i]
            f2, m2 = metas[j]
            ratio = difflib.SequenceMatcher(None, m1, m2).ratio()
            assert ratio < 0.60, f"Meta similarity between {f1} and {f2} is {ratio:.2f} (>= 0.60)"

@pytest.mark.asyncio
async def test_opengraph_type_and_real_characters():
    """Batch A.2 Item 4: openGraph.type = 'website' for normal pages, 'article' only for blog posts.
    Use real characters instead of \\u escapes.
    """
    crawl_pages = [
        {"url": "https://demo-site.example.com/", "status_code": 200, "indexable": True, "title": "AcmeCorp — Ideas & Innovation", "meta_desc": "Digital agency & web design.", "h1": "Home"},
        {"url": "https://demo-site.example.com/services", "status_code": 200, "indexable": True, "title": "Services — Custom Development", "meta_desc": "Next.js & React engineering.", "h1": "Services"},
        {"url": "https://demo-site.example.com/blog/seo-guide", "status_code": 200, "indexable": True, "title": "Guide to Modern SEO", "meta_desc": "SEO insights & tips.", "h1": "SEO Guide"}
    ]

    bundle, mode, cost, err, model = await CodeGeneratorAgent.run(
        platform="nextjs",
        platform_confidence=1.0,
        verified_tech_issues=[],
        strategy_tasks=[],
        crawl_pages=crawl_pages,
        crawl_links=[],
        verified_rewrites=[],
        internal_links=[]
    )

    art_map = {a.file_path: a for a in bundle.artifacts}

    # Normal page: type = 'website'
    serv_art = art_map.get("app/services/page.metadata.snippet.tsx")
    assert serv_art is not None
    assert "type: 'website'" in serv_art.content

    # Dynamic blog skeleton: type = 'article'
    blog_art = art_map.get("app/blog/[slug]/page.metadata.snippet.tsx")
    assert blog_art is not None
    assert "type: 'article'" in blog_art.content

    # Real characters check: Root layout should retain '—' and not have '\\u2014'
    root_art = art_map.get("app/layout.metadata.snippet.tsx")
    assert root_art is not None
    assert "\\u2014" not in root_art.content
    assert "\\u0026" not in root_art.content

@pytest.mark.asyncio
async def test_root_layout_metadata_title_and_og():
    """Batch A.2 Item 5: Root layout metadata: title.default <= 60 chars, template '%s | Brand', OG title matching."""
    crawl_pages = [
        {"url": "https://demo-site.example.com/", "status_code": 200, "indexable": True, "title": "AcmeCorp — Ideas to Impact | Pakistan's Leading Full-Stack Web Development Agency", "meta_desc": "Description", "h1": "Home"}
    ]

    bundle, mode, cost, err, model = await CodeGeneratorAgent.run(
        platform="nextjs",
        platform_confidence=1.0,
        verified_tech_issues=[],
        strategy_tasks=[],
        crawl_pages=crawl_pages,
        crawl_links=[],
        verified_rewrites=[],
        internal_links=[]
    )

    art_map = {a.file_path: a for a in bundle.artifacts}
    root_art = art_map.get("app/layout.metadata.snippet.tsx")
    assert root_art is not None
    assert "MERGE into your existing app/layout.tsx" in root_art.content
    assert "export default function RootLayout" not in root_art.content

    default_match = re.search(r"default:\s*'([^']+)'", root_art.content)
    assert default_match is not None
    def_title = default_match.group(1)
    assert len(def_title) <= 60

    og_match = re.search(r"openGraph:\s*\{[^}]*title:\s*'([^']+)'", root_art.content)
    assert og_match is not None
    og_title = og_match.group(1)
    assert og_title == def_title
    assert "template: '%s | AcmeCorp'" in root_art.content

@pytest.mark.asyncio
async def test_dynamic_routes_and_metadata_csv():
    """Batch A.2 Item 6: Dynamic routes emit generateMetadata skeleton for app/blog/[slug],
    and per-post titles/metas in metadata_table.csv.
    """
    crawl_pages = [
        {"url": "https://demo-site.example.com/", "status_code": 200, "indexable": True, "title": "AcmeCorp", "meta_desc": "Agency", "h1": "Home"},
        {"url": "https://demo-site.example.com/blog/nextjs-15-tips", "status_code": 200, "indexable": True, "title": "Next.js 15 Tips | AcmeCorp", "meta_desc": "Learn top Next.js tips.", "h1": "Next.js 15 Tips"},
        {"url": "https://demo-site.example.com/blog/seo-best-practices", "status_code": 200, "indexable": True, "title": "SEO Best Practices | AcmeCorp", "meta_desc": "SEO strategies for developers.", "h1": "SEO Best Practices"}
    ]

    bundle, mode, cost, err, model = await CodeGeneratorAgent.run(
        platform="nextjs",
        platform_confidence=1.0,
        verified_tech_issues=[],
        strategy_tasks=[],
        crawl_pages=crawl_pages,
        crawl_links=[],
        verified_rewrites=[],
        internal_links=[]
    )

    art_map = {a.file_path: a for a in bundle.artifacts}

    # Should have dynamic skeleton
    assert "app/blog/[slug]/page.metadata.snippet.tsx" in art_map
    skeleton = art_map["app/blog/[slug]/page.metadata.snippet.tsx"].content
    assert "export async function generateMetadata" in skeleton
    assert "params: Promise<{ slug: string }>" in skeleton

    # Should NOT have individual static files for each post
    assert "app/blog/nextjs-15-tips/page.tsx" not in art_map
    assert "app/blog/nextjs-15-tips/page.metadata.snippet.tsx" not in art_map

    # metadata_table.csv must list each post
    csv_art = art_map.get("metadata_table.csv")
    assert csv_art is not None
    assert "/blog/nextjs-15-tips" in csv_art.content
    assert "/blog/seo-best-practices" in csv_art.content

def test_llms_txt_clean_standard_format():
    """Batch A.2 Item 7: llms.txt valid format only (# H1, > summary, ## sections, - [Title](URL): desc),
    nothing before H1, descriptions cut at word boundaries.
    """
    content = CodeTemplateEngine.render_llms_txt(
        site_name="AcmeCorp",
        site_summary="AcmeCorp is a digital agency providing custom software engineering and growth solutions.",
        base_url="https://demo-site.example.com",
        curated_links=[
            {"title": "Our Services", "url": "https://demo-site.example.com/services", "description": "Custom Next.js engineering and design architecture."},
            {"title": "Portfolio", "url": "https://demo-site.example.com/portfolio", "description": "Showcase of high-converting web applications and digital platforms."}
        ]
    )

    # First character must be '#'
    assert content.startswith("# AcmeCorp\n")
    # No comment header at top of file
    assert not any(l.strip().startswith(("//", "/*")) for l in content.splitlines())
    assert "# Generated by" not in content

    # Structure
    assert "\n> " in content
    assert "\n## Key Resources\n" in content
    assert "- [Our Services](https://demo-site.example.com/services):" in content
    assert "- [Portfolio](https://demo-site.example.com/portfolio):" in content
    assert "\n## Contact & Organization\n" in content

def test_readme_and_review_gating():
    """Batch A.2 Items 8 & 9: README_APPLY single approach, rollback commands, search console,
    and review gating filtering unreviewed items by default.
    """
    init_db()
    job_id = f"test-job-gating-{uuid.uuid4().hex[:8]}"

    with get_sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO jobs (id, target_url, status, created_at, updated_at) VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            (job_id, "https://demo-site.example.com", "completed")
        )

    artifacts = [
        GeneratedArtifact(
            artifact_type="nextjs_root_layout",
            file_path="app/layout.metadata.snippet.tsx",
            platform="nextjs",
            title="Root Layout",
            content="// snippet",
            validation_status="passed"
        ),
        GeneratedArtifact(
            artifact_type="nextjs_page_metadata",
            file_path="app/services/page.metadata.snippet.tsx",
            platform="nextjs",
            title="Services Metadata",
            content="// snippet",
            validation_status="passed"
        ),
        GeneratedArtifact(
            artifact_type="nextjs_page_metadata",
            file_path="app/portfolio/page.metadata.snippet.tsx",
            platform="nextjs",
            title="Portfolio Metadata",
            content="// snippet",
            validation_status="passed"
        ),
        GeneratedArtifact(
            artifact_type="nextjs_redirects",
            file_path="next.config.js",
            platform="nextjs",
            title="Redirects",
            content="// config",
            validation_status="passed"
        )
    ]

    # Save to review items table
    for art in artifacts:
        DBManager.save_review_item({
            "id": str(uuid4()),
            "job_id": job_id,
            "item_type": "code_artifact",
            "item_ref": art.file_path,
            "title": art.title,
            "status": "pending",
            "reviewer_note": "",
            "original_payload_json": json.dumps({"file_path": art.file_path, "content": art.content}),
            "edited_payload_json": "{}"
        })

    # Approve 3 items, leave 1 pending
    items = DBManager.get_review_items(job_id)
    assert len(items) == 4
    for it in items[:3]:
        DBManager.update_review_item_status(it["id"], "approved")

    # 1. Gated ZIP (default: include_unreviewed=False) -> exactly 3 approved code files
    zip_gated_bytes = CodePackager.generate_zip(
        job_id=job_id,
        domain="demo-site.example.com",
        platform="nextjs",
        artifacts=artifacts,
        validation_results=[],
        is_demo=False,
        include_unreviewed=False
    )

    import zipfile
    with zipfile.ZipFile(io.BytesIO(zip_gated_bytes)) as zf:
        file_list = zf.namelist()
        code_files = [f for f in file_list if f.startswith("files/")]
        assert len(code_files) == 3
        readme = zf.read("README_APPLY.md").decode("utf-8")
        assert "git checkout main" in readme
        assert "git branch -D chore/seo-meta-and-schema-fixes" in readme
        assert "Google Search Console" in readme
        assert "MERGE" in readme

    # 2. Ungated ZIP (include_unreviewed=True) -> all 4 code files, 4th marked with [UNREVIEWED]
    zip_ungated_bytes = CodePackager.generate_zip(
        job_id=job_id,
        domain="demo-site.example.com",
        platform="nextjs",
        artifacts=artifacts,
        validation_results=[],
        is_demo=False,
        include_unreviewed=True
    )
    with zipfile.ZipFile(io.BytesIO(zip_ungated_bytes)) as zf:
        file_list = zf.namelist()
        code_files = [f for f in file_list if f.startswith("files/")]
        assert len(code_files) == 4
        changes_csv = zf.read("CHANGES.csv").decode("utf-8")
        assert "[UNREVIEWED]" in changes_csv


def test_sitemap_rules_and_severity_escalation():
    """Tests sitemap_lists_non_existent_url (<5 is medium, >=5 is high) and crawled_page_missing_from_sitemap."""
    from app.agents.issue_rules import detect_issues_from_data
    from app.agents.technical_agent import get_deterministic_severity

    crawl_pages = [
        {"id": "p-1", "url": "https://example.com/", "status_code": 200, "indexable": 1, "canonical": "https://example.com/"},
        {"id": "p-2", "url": "https://example.com/about", "status_code": 200, "indexable": 1, "canonical": "https://example.com/about"},
        {"id": "p-3", "url": "https://example.com/services", "status_code": 200, "indexable": 1, "canonical": "https://example.com/services"},
        {"id": "p-4", "url": "https://example.com/blog/missing-1", "status_code": 200, "indexable": 1, "canonical": "https://example.com/blog/missing-1"},
        {"id": "p-5", "url": "https://example.com/blog/missing-2", "status_code": 200, "indexable": 1, "canonical": "https://example.com/blog/missing-2"},
        # Non-indexable or non-200 pages should NOT be flagged as missing from sitemap
        {"id": "p-6", "url": "https://example.com/404-page", "status_code": 404, "indexable": 0, "canonical": None},
        {"id": "p-7", "url": "https://example.com/noindex", "status_code": 200, "indexable": 0, "canonical": None},
    ]

    # Case A: 6 stale sitemap entries (>= 5 -> High severity)
    stale_sitemap_entries = [
        {"url": "https://example.com/old-1", "status_code": 404, "in_crawl": False},
        {"url": "https://example.com/old-2", "status_code": 404, "in_crawl": False},
        {"url": "https://example.com/old-3", "status_code": 404, "in_crawl": False},
        {"url": "https://example.com/old-4", "status_code": 404, "in_crawl": False},
        {"url": "https://example.com/old-5", "status_code": 404, "in_crawl": False},
        {"url": "https://example.com/old-6", "status_code": 500, "in_crawl": False},
        {"url": "https://example.com/", "status_code": 200, "in_crawl": True},
        {"url": "https://example.com/about", "status_code": 200, "in_crawl": True},
        {"url": "https://example.com/services", "status_code": 200, "in_crawl": True},
    ]

    candidates = detect_issues_from_data(
        crawl_pages=crawl_pages,
        crawl_links=[],
        psi_results=[],
        sitemap_entries=stale_sitemap_entries
    )

    types = {c["type"]: c for c in candidates}
    assert "sitemap_lists_non_existent_url" in types
    stale_issue = types["sitemap_lists_non_existent_url"]
    assert len(stale_issue["urls"]) == 6
    assert stale_issue["severity"] == "high"
    assert get_deterministic_severity("sitemap_lists_non_existent_url", url_count=6) == "high"

    # Case B: Crawled pages missing from sitemap (p-4 and p-5 are 200 OK indexable canonical self)
    assert "crawled_page_missing_from_sitemap" in types
    missing_issue = types["crawled_page_missing_from_sitemap"]
    assert len(missing_issue["urls"]) == 2
    assert "https://example.com/blog/missing-1" in missing_issue["urls"]
    assert "https://example.com/blog/missing-2" in missing_issue["urls"]
    # Ensure non-indexable or 404 pages are not included
    assert "https://example.com/404-page" not in missing_issue["urls"]
    assert "https://example.com/noindex" not in missing_issue["urls"]
    assert missing_issue["severity"] == "medium"
    assert get_deterministic_severity("crawled_page_missing_from_sitemap", url_count=2) == "medium"

    # Case C: 2 stale entries (< 5 -> Medium severity)
    few_stale_entries = [
        {"url": "https://example.com/stale-1", "status_code": 404, "in_crawl": False},
        {"url": "https://example.com/stale-2", "status_code": 404, "in_crawl": False},
    ]
    candidates_few = detect_issues_from_data(
        crawl_pages=crawl_pages,
        crawl_links=[],
        psi_results=[],
        sitemap_entries=few_stale_entries
    )
    types_few = {c["type"]: c for c in candidates_few}
    assert types_few["sitemap_lists_non_existent_url"]["severity"] == "medium"
    assert get_deterministic_severity("sitemap_lists_non_existent_url", url_count=2) == "medium"


def test_nextjs_sitemap_ts_and_readme_recommendation():
    """Tests app/sitemap.ts generation from crawl and README data source recommendation."""
    from app.code_generator.templates import CodeTemplateEngine
    from app.code_generator.packager import CodePackager

    sitemap_items = [
        {"url": "https://demo-site.example.com/", "lastmod": "2026-03-01", "priority": "1.0"},
        {"url": "https://demo-site.example.com/services", "lastmod": "2026-03-01", "priority": "0.8"},
        {"url": "https://demo-site.example.com/portfolio", "lastmod": "2026-03-01", "priority": "0.8"},
    ]

    rendered_ts = CodeTemplateEngine.render_nextjs_sitemap_ts(sitemap_items)
    assert "export default function sitemap(): MetadataRoute.Sitemap" in rendered_ts
    assert "https://demo-site.example.com/" in rendered_ts
    assert "https://demo-site.example.com/services" in rendered_ts
    assert "generate this sitemap directly from your site's own data source" in rendered_ts.lower()

    instructions = CodePackager._get_platform_specific_instructions("nextjs")
    assert "generating this sitemap directly from your site's own data source" in instructions
    assert "app/sitemap.ts" in instructions


def test_snippet_title_and_meta_length_constraints():
    """Verify that root layout and page snippets enforce title <= 60 and meta <= 155."""
    # Root layout snippet
    long_home_title = "AcmeCorp - Premier Full-Stack Digital Agency in Pakistan for Web and Mobile Development"
    long_home_desc = "We craft exceptional high-performance digital products, scalable web apps, and bespoke branding for global enterprises and ambitious startups across the world."

    root_snippet = CodeTemplateEngine.render_nextjs_root_layout(
        base_url="https://demo-site.example.com",
        default_title=long_home_title,
        default_description=long_home_desc,
        brand_name="AcmeCorp",
        is_demo=False
    )
    # Check title.default length
    match_title = re.search(r"default:\s*['\"]([^'\"]+)['\"]", root_snippet)
    assert match_title is not None
    title_default = match_title.group(1)
    assert len(title_default) <= 60
    assert "AcmeCorp" in title_default
    assert "Digital" in title_default or "Agency" in title_default

    # Check description length
    match_desc = re.search(r"description:\s*['\"]([^'\"]+)['\"]", root_snippet)
    assert match_desc is not None
    desc = match_desc.group(1)
    assert len(desc) <= 155

    # Page metadata snippet
    page_snippet = CodeTemplateEngine.render_nextjs_page_metadata(
        title="Comprehensive Enterprise Software Development and Cloud Architecture Services | AcmeCorp",
        description="Explore our comprehensive enterprise software development services, cloud infrastructure management, UI/UX product design, and digital acceleration strategies for modern enterprises.",
        canonical_url="https://demo-site.example.com/services",
        target_file="app/services/page.tsx",
        is_demo=False
    )
    match_p_title = re.search(r"title:\s*['\"]([^'\"]+)['\"]", page_snippet)
    assert match_p_title is not None
    assert len(match_p_title.group(1)) <= 60

    match_p_desc = re.search(r"description:\s*['\"]([^'\"]+)['\"]", page_snippet)
    assert match_p_desc is not None
    assert len(match_p_desc.group(1)) <= 155


def test_sitemap_post_fix_state_and_no_changefreq():
    """Verify sitemap.xml and app/sitemap.ts omit changefreq/priority, include post-fix canonical fixes, and real dates."""
    sitemap_items = [
        {"url": "https://demo-site.example.com/", "lastmod": "2026-03-01", "has_real_date": True},
        {"url": "https://demo-site.example.com/services", "lastmod": "2026-03-01", "has_real_date": True},
        {
            "url": "https://demo-site.example.com/portfolio",
            "lastmod": "",
            "has_real_date": False,
            "note": "Assumes canonical fix applied"
        },
    ]

    xml = CodeTemplateEngine.render_sitemap_xml(sitemap_items)
    assert "<changefreq>" not in xml
    assert "<priority>" not in xml
    assert "<lastmod>2026-03-01</lastmod>" in xml
    assert "<!-- Assumes canonical fix applied -->" in xml
    assert "<loc>https://demo-site.example.com/portfolio</loc>" in xml

    ts = CodeTemplateEngine.render_nextjs_sitemap_ts(sitemap_items)
    assert "changeFrequency" not in ts
    assert "priority" not in ts
    assert "lastModified: new Date('2026-03-01')" in ts
    assert "// Assumes canonical fix applied" in ts
    assert "https://demo-site.example.com/portfolio" in ts


def test_sequential_issue_ids_and_source_field():
    """Verify that issues are renumbered T-001, T-002... without FB in ID and preserve source."""
    from app.agents.verifier import Verifier
    from app.models.agent_schemas import TechnicalIssue

    job_id = f"test-job-seq-{uuid4().hex[:8]}"
    p1_id = f"p1-{uuid4().hex[:8]}"
    p2_id = f"p2-{uuid4().hex[:8]}"
    raw_issues = [
        TechnicalIssue(
            id="T-LLM-001",
            type="missing_title",
            severity="high",
            impact="Missing title tag",
            effort="low",
            urls=["https://example.com/p1"],
            evidence=[{"table": "crawl_pages", "id": p1_id, "field": "title"}],
            fix_hint="Add title",
            source="llm"
        ),
        TechnicalIssue(
            id="T-FALLBACK-002",
            type="meta_too_long",
            severity="medium",
            impact="Meta too long",
            effort="low",
            urls=["https://example.com/p2"],
            evidence=[{"table": "crawl_pages", "id": p2_id, "field": "meta_desc"}],
            fix_hint="Shorten meta",
            source="fallback_rule"
        )
    ]

    with get_sqlite_conn() as conn:
        conn.execute("INSERT INTO jobs (id, target_url, status, created_at, updated_at) VALUES (?, ?, ?, datetime('now'), datetime('now'))", (job_id, "https://example.com", "completed"))
        conn.execute("INSERT INTO crawl_pages (id, job_id, url, status_code, title, meta_desc, created_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
                     (p1_id, job_id, "https://example.com/p1", 200, "", "Desc 1"))
        conn.execute("INSERT INTO crawl_pages (id, job_id, url, status_code, title, meta_desc, created_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
                     (p2_id, job_id, "https://example.com/p2", 200, "Title 2", "X" * 180))

    report = Verifier.verify_issues(job_id, raw_issues)
    assert len(report.verified_issues) == 2
    assert report.verified_issues[0].id == "T-001"
    assert report.verified_issues[0].source == "llm"
    assert "FB" not in report.verified_issues[0].id

    assert report.verified_issues[1].id == "T-002"
    assert report.verified_issues[1].source == "fallback_rule"
    assert "FB" not in report.verified_issues[1].id


def test_nextjs_14_and_15_dynamic_blog_snippets():
    """Verify both Next.js 14 (sync params) and 15+ (async Promise params) dynamic route outputs."""
    v14_snippet = CodeTemplateEngine.render_nextjs_blog_dynamic_metadata(
        base_url="https://demo-site.example.com",
        brand_name="AcmeCorp",
        target_file="app/blog/[slug]/page.tsx",
        nextjs_version="14"
    )
    assert "params: { slug: string };" in v14_snippet
    assert "const { slug } = params;" in v14_snippet
    assert "await params;" not in v14_snippet
    assert "NOTE: In production, title, description, and canonical must be fetched from your" in v14_snippet

    v15_snippet = CodeTemplateEngine.render_nextjs_blog_dynamic_metadata(
        base_url="https://demo-site.example.com",
        brand_name="AcmeCorp",
        target_file="app/blog/[slug]/page.tsx",
        nextjs_version="15+"
    )
    assert "params: Promise<{ slug: string }>;" in v15_snippet
    assert "const { slug } = await params;" in v15_snippet
    assert "NOTE: In production, title, description, and canonical must be fetched from your" in v15_snippet

