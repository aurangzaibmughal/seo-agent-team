from app.crawler.parser import normalize_url, is_internal_url, parse_html_page

def test_normalize_url():
    # Relative URL resolution
    assert normalize_url("/blog/post-1", base_url="https://example.com") == "https://example.com/blog/post-1"
    assert normalize_url("post-2", base_url="https://example.com/blog/") == "https://example.com/blog/post-2"
    
    # Strip fragments
    assert normalize_url("https://example.com/about#team") == "https://example.com/about"
    
    # Trailing slash normalization
    assert normalize_url("https://example.com/contact/") == "https://example.com/contact"
    assert normalize_url("https://example.com/") == "https://example.com/"
    
    # Reject javascript/mailto
    assert normalize_url("javascript:void(0)") is None
    assert normalize_url("mailto:info@example.com") is None
    assert normalize_url("#top") is None

def test_is_internal_url():
    base = "example.com"
    assert is_internal_url("https://example.com/about", base) is True
    assert is_internal_url("https://sub.example.com/page", base) is True
    assert is_internal_url("https://google.com", base) is False
    assert is_internal_url("https://notexample.com", base) is False

def test_parse_html_page_full_metadata():
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <title>Best AI SEO Services 2026</title>
        <meta name="description" content="Discover automated multi-agent SEO workflows that 10x your organic search results.">
        <link rel="canonical" href="https://example.com/services">
    </head>
    <body>
        <h1>Revolutionary Multi-Agent SEO</h1>
        <p>This is a paragraph with several keywords explaining how our autonomous agent team audits technical issues, generates briefs, and writes optimized schema.</p>
        <a href="/pricing">Pricing Plans</a>
        <a href="https://twitter.com/example">Twitter</a>
    </body>
    </html>
    """
    data = parse_html_page(html, current_url="https://example.com/services", status_code=200, response_time_ms=120)
    
    assert data["status_code"] == 200
    assert data["title"] == "Best AI SEO Services 2026"
    assert "Discover automated multi-agent" in data["meta_desc"]
    assert data["h1"] == "Revolutionary Multi-Agent SEO"
    assert data["canonical"] == "https://example.com/services"
    assert data["indexable"] is True
    assert data["indexability_status"] == "indexable"
    assert data["word_count"] > 15
    assert "https://example.com/pricing" in data["outlinks_list"]
    assert data["links_out"] == 2

def test_parse_html_page_missing_elements():
    html = "<html><body><p>Just plain text without title, h1, or meta</p></body></html>"
    data = parse_html_page(html, current_url="https://example.com/bare", status_code=200)
    
    assert data["title"] is None
    assert data["meta_desc"] is None
    assert data["h1"] is None
    assert data["canonical"] is None
    assert data["indexable"] is True

def test_parse_html_page_noindex():
    html = """
    <html>
    <head>
        <title>Admin Dashboard</title>
        <meta name="robots" content="noindex, nofollow">
    </head>
    <body><h1>Admin Area</h1></body>
    </html>
    """
    data = parse_html_page(html, current_url="https://example.com/admin", status_code=200)
    assert data["indexable"] is False
    assert data["indexability_status"] == "noindex_meta"

def test_parse_html_page_canonical_mismatch():
    html = """
    <html>
    <head>
        <title>Duplicate Page</title>
        <link rel="canonical" href="https://example.com/original-page">
    </head>
    <body><h1>Duplicate Content</h1></body>
    </html>
    """
    data = parse_html_page(html, current_url="https://example.com/duplicate-page", status_code=200)
    assert data["indexable"] is False
    assert data["indexability_status"] == "canonical_to_other"

def test_parse_html_page_http_error():
    data = parse_html_page("<html>Not Found</html>", current_url="https://example.com/404-page", status_code=404)
    assert data["indexable"] is False
    assert data["indexability_status"] == "http_error"
