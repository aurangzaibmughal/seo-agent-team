import gzip
import pytest
from unittest.mock import AsyncMock, MagicMock
import httpx
from app.crawler.sitemap_parser import (
    parse_sitemap_xml,
    discover_and_parse_sitemaps,
    SitemapDiscoveryResult
)
from app.agents.issue_rules import detect_issues_from_data
from app.crawler.url_utils import canonical_url_key

HEALTHY_SITEMAP_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://www.example.com/</loc></url>
    <url><loc>https://www.example.com/about/</loc></url>
    <url><loc>https://www.example.com/services/</loc></url>
</urlset>"""

SITEMAP_INDEX_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <sitemap><loc>https://www.example.com/wp-sitemap-posts-page-1.xml</loc></sitemap>
    <sitemap><loc>https://www.example.com/wp-sitemap-posts-post-1.xml</loc></sitemap>
    <sitemap><loc>https://www.example.com/wp-sitemap-taxonomies-category-1.xml</loc></sitemap>
</sitemapindex>"""

WP_POSTS_SITEMAP_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://www.example.com/blog/first-post/</loc></url>
    <url><loc>https://www.example.com/blog/second-post/</loc></url>
</urlset>"""

MALFORMED_XML = b"""<?xml version="1.0" encoding="UTF-8"?><urlset><url><loc>broken"""

def test_parse_healthy_sitemap():
    pages, children = parse_sitemap_xml(HEALTHY_SITEMAP_XML, "https://www.example.com")
    assert len(pages) == 3
    assert len(children) == 0
    assert "https://www.example.com/about/" in pages

def test_parse_sitemap_index_finds_children():
    pages, children = parse_sitemap_xml(SITEMAP_INDEX_XML, "https://www.example.com")
    assert len(pages) == 0
    assert len(children) == 3
    assert "https://www.example.com/wp-sitemap-posts-page-1.xml" in children

def test_parse_gzip_sitemap():
    gz_data = gzip.compress(HEALTHY_SITEMAP_XML)
    pages, children = parse_sitemap_xml(gz_data, "https://www.example.com", is_gz=True)
    assert len(pages) == 3

def test_parse_malformed_xml_returns_empty():
    pages, children = parse_sitemap_xml(MALFORMED_XML, "https://www.example.com")
    assert len(pages) == 0
    assert len(children) == 0

@pytest.mark.asyncio
async def test_sitemap_404_emits_single_finding_and_no_per_page_findings():
    # If sitemap discovery yields missing/404, issue_rules must emit sitemap_missing
    # and ZERO crawled_page_missing_from_sitemap findings!
    crawl_pages = [
        {"id": "p1", "url": "https://www.alghaffar.com.pk/", "status_code": 200, "indexable": True, "title": "Home", "canonical": "https://www.alghaffar.com.pk/"},
        {"id": "p2", "url": "https://www.alghaffar.com.pk/about/", "status_code": 200, "indexable": True, "title": "About", "canonical": "https://www.alghaffar.com.pk/about/"},
        {"id": "p3", "url": "https://www.alghaffar.com.pk/trip/", "status_code": 200, "indexable": True, "title": "Trip", "canonical": "https://www.alghaffar.com.pk/trip/"},
    ]
    
    # Sitemap could not be fetched (missing)
    issues = detect_issues_from_data(
        crawl_pages=crawl_pages,
        crawl_links=[],
        psi_results=[],
        sitemap_status="missing",
        sitemap_urls=set()
    )
    issue_types = [i["type"] for i in issues]
    
    # Must NOT have crawled_page_missing_from_sitemap
    assert "crawled_page_missing_from_sitemap" not in issue_types
    # Must have single sitemap_missing finding
    assert "sitemap_missing" in issue_types

def test_trailing_slash_difference_causes_zero_false_missing():
    # Crawl visited with trailing slash: https://www.alghaffar.com.pk/about/
    # Sitemap had without trailing slash: https://www.alghaffar.com.pk/about
    crawl_pages = [
        {"id": "p1", "url": "https://www.alghaffar.com.pk/", "status_code": 200, "indexable": True, "title": "Home", "canonical": "https://www.alghaffar.com.pk/"},
        {"id": "p2", "url": "https://www.alghaffar.com.pk/about/", "status_code": 200, "indexable": True, "title": "About", "canonical": "https://www.alghaffar.com.pk/about/"},
    ]
    sitemap_urls = {"https://www.alghaffar.com.pk", "https://www.alghaffar.com.pk/about"}
    
    issues = detect_issues_from_data(
        crawl_pages=crawl_pages,
        crawl_links=[],
        psi_results=[],
        sitemap_status="found",
        sitemap_urls=sitemap_urls
    )
    issue_types = [i["type"] for i in issues]
    assert "crawled_page_missing_from_sitemap" not in issue_types
