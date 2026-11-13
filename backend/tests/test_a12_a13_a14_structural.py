import pytest
from pathlib import Path
from app.crawler.parser import parse_html_page
from app.agents.issue_rules import detect_issues_from_data
from app.agents.content_agent import compute_internal_link_suggestions

# 1. Multiple and Zero H1
def test_a12_subdetector_multiple_and_zero_h1():
    html_multi = "<html><body><h1>First</h1><h1>Second</h1></body></html>"
    p_multi = parse_html_page(html_multi, "https://example.com/p1", 200)
    issues_multi = [i["type"] for i in detect_issues_from_data([p_multi], [], [])]
    assert "multiple_h1" in issues_multi

    html_zero = "<html><body><h2>No H1 Here</h2></body></html>"
    p_zero = parse_html_page(html_zero, "https://example.com/p2", 200)
    issues_zero = [i["type"] for i in detect_issues_from_data([p_zero], [], [])]
    assert "missing_h1" in issues_zero

# 2. Href="#" Placeholder Links
def test_a12_subdetector_href_hash_placeholder_links():
    html = '<html><body><footer><a href="#">Privacy Policy</a><a href="javascript:void(0)">Terms and Conditions</a></footer></body></html>'
    p = parse_html_page(html, "https://example.com/", 200)
    issues = [i["type"] for i in detect_issues_from_data([p], [], [])]
    assert "broken_hash_link" in issues

# 3. Image Alt + Format + Missing Width/Height
def test_a12_subdetector_image_alt_format_dimensions():
    html = """<html><body>
        <img src="/banner.png"> <!-- Missing alt, missing width/height, non-modern png -->
        <img src="/photo.webp" alt="Photo" width="800" height="600"> <!-- Good -->
    </body></html>"""
    p = parse_html_page(html, "https://example.com/", 200)
    issues = [i["type"] for i in detect_issues_from_data([p], [], [])]
    assert "missing_image_alt" in issues
    assert "missing_image_dimensions" in issues
    assert "non_modern_image_format" in issues

# 4. JSON-LD Schema
def test_a12_subdetector_jsonld_schema():
    html_no_schema = "<html><body><h1>Page</h1></body></html>"
    p_no = parse_html_page(html_no_schema, "https://example.com/", 200)
    issues_no = [i["type"] for i in detect_issues_from_data([p_no], [], [])]
    assert "missing_schema" in issues_no

    html_with_schema = '<html><head><script type="application/ld+json">{"@context": "https://schema.org"}</script></head><body><h1>Page</h1></body></html>'
    p_yes = parse_html_page(html_with_schema, "https://example.com/", 200)
    issues_yes = [i["type"] for i in detect_issues_from_data([p_yes], [], [])]
    assert "missing_schema" not in issues_yes

# 5. Open Graph & Twitter Cards
def test_a12_subdetector_open_graph_and_twitter_cards():
    html_missing = "<html><body><h1>Page</h1></body></html>"
    p_missing = parse_html_page(html_missing, "https://example.com/", 200)
    issues_missing = [i["type"] for i in detect_issues_from_data([p_missing], [], [])]
    assert "missing_open_graph" in issues_missing
    assert "missing_twitter_card" in issues_missing

    html_present = '<html><head><meta property="og:title" content="Title"><meta name="twitter:card" content="summary"></head><body><h1>Page</h1></body></html>'
    p_present = parse_html_page(html_present, "https://example.com/", 200)
    issues_present = [i["type"] for i in detect_issues_from_data([p_present], [], [])]
    assert "missing_open_graph" not in issues_present
    assert "missing_twitter_card" not in issues_present

# 6. Redirect Hygiene & Insecure HTTP
def test_a12_subdetector_redirect_hygiene_and_insecure_http():
    html = "<html><head><link rel=\"canonical\" href=\"https://example.com/about\"></head><body><h1>Insecure</h1></body></html>"
    p_http = parse_html_page(html, "http://example.com/about/", 200)
    issues = [i["type"] for i in detect_issues_from_data([p_http], [], [])]
    assert "insecure_http_url" in issues
    assert "trailing_slash_inconsistency" in issues

# 7. Robots.txt
def test_a12_subdetector_robots_txt():
    issues = detect_issues_from_data(
        [{"url": "https://example.com/", "status_code": 200}],
        [],
        [],
        robots_found=False
    )
    issue_types = [i["type"] for i in issues]
    assert "missing_robots_txt" in issue_types

# 8. Legal Pages Discovery
def test_a12_subdetector_legal_pages_discovery():
    html_no_legal = "<html><body><h1>Page without footer legal links</h1></body></html>"
    p = parse_html_page(html_no_legal, "https://example.com/", 200)
    issues = [i["type"] for i in detect_issues_from_data([p], [], [])]
    assert "missing_legal_pages" in issues

    html_with_legal = '<html><body><footer><a href="/privacy-policy/">Privacy Policy</a></footer></body></html>'
    p_legal = parse_html_page(html_with_legal, "https://example.com/", 200)
    issues_legal = [i["type"] for i in detect_issues_from_data([p_legal], [], [])]
    assert "missing_legal_pages" not in issues_legal

# 9. Breadcrumbs Sanity
def test_a12_subdetector_breadcrumbs_sanity():
    html_no_bc = "<html><body><h1>Subpage</h1></body></html>"
    p_sub = parse_html_page(html_no_bc, "https://example.com/services/web-dev", 200)
    issues = [i["type"] for i in detect_issues_from_data([p_sub], [], [])]
    assert "missing_breadcrumbs" in issues

    html_with_bc = '<html><body><nav aria-label="breadcrumb"><ol><li>Home</li></ol></nav><h1>Subpage</h1></body></html>'
    p_bc = parse_html_page(html_with_bc, "https://example.com/services/web-dev", 200)
    issues_bc = [i["type"] for i in detect_issues_from_data([p_bc], [], [])]
    assert "missing_breadcrumbs" not in issues_bc

# 10. Noindex vs Canonical Conflicts
def test_a12_subdetector_noindex_canonical_conflicts():
    html = '<html><head><meta name="robots" content="noindex"><link rel="canonical" href="https://example.com/conflict"></head><body><h1>Conflict</h1></body></html>'
    p = parse_html_page(html, "https://example.com/conflict", 200)
    issues = [i["type"] for i in detect_issues_from_data([p], [], [])]
    assert "noindex_canonical_conflict" in issues

# A-13 Advisory checks
def test_a13_content_qa_advisory_rules():
    html = "<html><body><h1>Trip to Morroco and Landon</h1><p>PKR $50,000</p></body></html>"
    page = parse_html_page(html, "https://example.com/trip/kuala-kumpur/", status_code=200)
    issues = detect_issues_from_data([page], [], [])
    advisory_types = [i["type"] for i in issues if i.get("is_advisory")]
    assert "slug_typo" in advisory_types
    assert "content_typo" in advisory_types
    assert "currency_anomaly" in advisory_types

# A-14 Internal link verification
def test_a14_internal_link_engine_never_suggests_existing_links():
    pages = [
        {"url": "https://example.com/source/", "status_code": 200, "title": "Source Page Title", "meta_desc": "Source", "indexable": True, "outlinks_list": ["https://example.com/target/"], "text_terms": ["tour", "travel"], "word_count": 500, "inlinks_count": 5},
        {"url": "https://example.com/target/", "status_code": 200, "title": "Target Page Title", "meta_desc": "Target", "indexable": True, "outlinks_list": [], "text_terms": ["tour", "booking"], "word_count": 600, "inlinks_count": 0}
    ]
    crawl_links = [{"source_url": "https://example.com/source", "target_url": "https://example.com/target"}]
    suggestions = compute_internal_link_suggestions(pages, crawl_links)
    existing = [s for s in suggestions if "source" in s.source_url and "target" in s.target_url]
    assert len(existing) == 0
