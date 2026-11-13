import pytest
from app.core.classification import classify_page_type, is_admin_page
from app.agents.issue_rules import detect_issues_from_data
from app.agents.content_agent import compute_internal_link_suggestions, ContentAgent
from app.agents.verifier import Verifier
from app.services.comparator import JobComparator
from app.core.db import DBManager

def test_classify_page_type():
    # Content pages
    assert classify_page_type("https://example.com/") == "content"
    assert classify_page_type("https://example.com") == "content"
    assert classify_page_type("https://example.com/services") == "content"
    assert classify_page_type("https://example.com/blog/seo-tips") == "content"
    assert classify_page_type("https://example.com/pricing") == "content"
    assert classify_page_type("https://example.com/portfolio") == "content"
    
    # Utility pages
    assert classify_page_type("https://example.com/login") == "utility"
    assert classify_page_type("https://example.com/signup") == "utility"
    assert classify_page_type("https://example.com/admin") == "utility"
    assert classify_page_type("https://example.com/admin/dashboard") == "utility"
    assert classify_page_type("https://example.com/account/settings") == "utility"
    assert classify_page_type("https://example.com/cart") == "utility"
    assert classify_page_type("https://example.com/checkout") == "utility"

    assert is_admin_page("https://example.com/admin") is True
    assert is_admin_page("https://example.com/login") is False

def test_noindex_page_rules_classification():
    # Case A: Content page with noindex -> High severity issue
    crawl_pages = [
        {
            "id": "p1",
            "url": "https://example.com/pricing",
            "status_code": 200,
            "title": "Pricing Plans",
            "meta_desc": "Our affordable pricing tiers.",
            "h1": "Transparent Pricing",
            "indexable": False,
            "indexability_status": "noindex_meta"
        },
        # Case B: Utility pages with noindex -> NOT an issue (positive)
        {
            "id": "p2",
            "url": "https://example.com/login",
            "status_code": 200,
            "title": "Sign In",
            "meta_desc": "User sign in portal.",
            "h1": "Login to Your Account",
            "indexable": False,
            "indexability_status": "noindex_meta"
        },
        {
            "id": "p3",
            "url": "https://example.com/admin",
            "status_code": 200,
            "title": "Admin Gateway",
            "meta_desc": "Administrator portal.",
            "h1": "Admin Portal",
            "indexable": False,
            "indexability_status": "noindex_meta"
        }
    ]

    candidates = detect_issues_from_data(crawl_pages, [], [])
    c_types = [c["type"] for c in candidates]

    # Exactly 1 noindex_page for /pricing
    assert c_types.count("noindex_page") == 1
    noindex_cand = next(c for c in candidates if c["type"] == "noindex_page")
    assert noindex_cand["urls"] == ["https://example.com/pricing"]
    
    # /login and /admin must NOT produce any noindex_page or indexable errors
    assert not any(c["type"] == "noindex_page" and "login" in c["urls"][0] for c in candidates)
    assert not any(c["type"] == "noindex_page" and "admin" in c["urls"][0] for c in candidates)

def test_indexable_private_pages_detected():
    # When utility pages are indexable (lacking noindex), they should be flagged
    crawl_pages = [
        {
            "id": "p1",
            "url": "https://example.com/admin",
            "status_code": 200,
            "title": "Admin Gateway",
            "meta_desc": "Admin portal",
            "h1": "Admin",
            "indexable": True,
            "indexability_status": "indexable"
        },
        {
            "id": "p2",
            "url": "https://example.com/signup",
            "status_code": 200,
            "title": "Create Account",
            "meta_desc": "Sign up here",
            "h1": "Sign Up",
            "indexable": True,
            "indexability_status": "indexable"
        }
    ]
    candidates = detect_issues_from_data(crawl_pages, [], [])
    c_types = [c["type"] for c in candidates]
    
    assert "indexable_admin_page" in c_types
    assert "indexable_private_page" in c_types

def test_never_suggest_internal_links_to_utility_or_noindex():
    crawl_pages = [
        {
            "url": "https://example.com/",
            "status_code": 200,
            "title": "Home - Agency Services",
            "h1": "Premier Agency Solutions",
            "indexable": True,
            "indexability_status": "indexable",
            "text_terms": ["agency", "solutions", "premier", "consulting"]
        },
        {
            "url": "https://example.com/services",
            "status_code": 200,
            "title": "Agency Consulting Services",
            "h1": "Consulting Services for Modern Businesses",
            "indexable": True,
            "indexability_status": "indexable",
            "text_terms": ["consulting", "services", "solutions", "modern"]
        },
        {
            "url": "https://example.com/login",
            "status_code": 200,
            "title": "Login Portal",
            "h1": "Login to Agency Portal",
            "indexable": False,
            "indexability_status": "noindex_meta",
            "text_terms": ["agency", "portal", "login", "solutions"]
        },
        {
            "url": "https://example.com/admin",
            "status_code": 200,
            "title": "Admin Dashboard",
            "h1": "Administrative Security Gateway",
            "indexable": False,
            "indexability_status": "noindex_meta",
            "text_terms": ["administrative", "security", "gateway", "agency"]
        }
    ]

    links = compute_internal_link_suggestions(crawl_pages, [])
    for l in links:
        assert "login" not in l.source_url
        assert "login" not in l.target_url
        assert "admin" not in l.source_url
        assert "admin" not in l.target_url

def test_content_briefs_gsc_gated():
    # Crawl with NO Search Console data
    empty_research = {
        "has_gsc_data": False,
        "total_queries_analyzed": 0,
        "question_queries": [],
        "query_clusters": []
    }
    crawl_pages = [
        {
            "url": "https://example.com/",
            "status_code": 200,
            "title": "Home Page",
            "meta_desc": "Welcome to our platform.",
            "h1": "Platform"
        }
    ]
    report = ContentAgent._run_deterministic(
        verified_research=[],
        crawl_pages=crawl_pages,
        internal_links=[],
        research_snapshot=empty_research,
        competitor_pages=[]
    )
    # Must generate exactly 0 briefs when no GSC data is present
    assert len(report.briefs) == 0

    # Running the same crawl twice gives the same 0 briefs (deterministic)
    report2 = ContentAgent._run_deterministic(
        verified_research=[],
        crawl_pages=crawl_pages,
        internal_links=[],
        research_snapshot=empty_research,
        competitor_pages=[]
    )
    assert len(report2.briefs) == 0

def test_comparator_noindex_on_private_pages_is_improvement():
    # Create mock jobs in SQLite DB
    job1 = DBManager.create_job(target_url="https://example.com", max_pages=10)
    job2 = DBManager.create_job(target_url="https://example.com", max_pages=10)

    # Job 1 (Before): /login and /admin were indexable
    conn = DBManager.get_sqlite_conn() if hasattr(DBManager, "get_sqlite_conn") else None
    from app.core.db import get_sqlite_conn
    from datetime import datetime, timezone
    from uuid import uuid4
    conn = get_sqlite_conn()
    cursor = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()

    try:
        pages_j1 = [
            (str(uuid4()), job1["id"], "https://example.com/", 200, "Home", "Home meta", "Home H1", "https://example.com/", 100, 5, 5, 1, "indexable", now),
            (str(uuid4()), job1["id"], "https://example.com/admin", 200, "Admin", "Admin meta", "Admin H1", "https://example.com/admin", 50, 1, 1, 1, "indexable", now),
            (str(uuid4()), job1["id"], "https://example.com/login", 200, "Login", "Login meta", "Login H1", "https://example.com/login", 50, 1, 1, 1, "indexable", now)
        ]
        cursor.executemany("""
            INSERT INTO crawl_pages (id, job_id, url, status_code, title, meta_desc, h1, canonical, word_count, links_out, inlinks_count, indexable, indexability_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, pages_j1)

        # Job 2 (After): /login and /admin now have noindex!
        pages_j2 = [
            (str(uuid4()), job2["id"], "https://example.com/", 200, "Home", "Home meta", "Home H1", "https://example.com/", 100, 5, 5, 1, "indexable", now),
            (str(uuid4()), job2["id"], "https://example.com/admin", 200, "Admin", "Admin meta", "Admin H1", "https://example.com/admin", 50, 1, 1, 0, "noindex_meta", now),
            (str(uuid4()), job2["id"], "https://example.com/login", 200, "Login", "Login meta", "Login H1", "https://example.com/login", 50, 1, 1, 0, "noindex_meta", now)
        ]
        cursor.executemany("""
            INSERT INTO crawl_pages (id, job_id, url, status_code, title, meta_desc, h1, canonical, word_count, links_out, inlinks_count, indexable, indexability_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, pages_j2)

        cursor.execute("UPDATE jobs SET status = 'completed', pages_crawled = 3 WHERE id IN (?, ?)", (job1["id"], job2["id"]))
        conn.commit()
    finally:
        conn.close()

    result = JobComparator.compare(job1["id"], job2["id"])

    # Must NOT report noindex_page as a new issue on /login or /admin
    new_issue_urls = [item.get("url") for item in result["issues"]["new"]]
    assert "https://example.com/admin" not in new_issue_urls
    assert "https://example.com/login" not in new_issue_urls

    # Must list them under improvements
    improvements = result["issues"].get("improvements", [])
    imp_urls = [item["url"] for item in improvements]
    assert "https://example.com/admin" in imp_urls
    assert "https://example.com/login" in imp_urls
