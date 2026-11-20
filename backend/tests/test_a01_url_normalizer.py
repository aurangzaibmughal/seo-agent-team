import pytest
from app.crawler.url_utils import (
    normalize_url,
    urls_compare_equal,
    canonical_url_key,
    detect_trailing_slash_convention
)

TABLE_TEST_CASES = [
    # (url1, url2, should_compare_equal, description)
    (
        "https://www.alghaffar.com.pk/about",
        "https://www.alghaffar.com.pk/about/",
        True,
        "Trailing slash difference on same host and path"
    ),
    (
        "https://www.alghaffar.com.pk/about/?utm_source=facebook&gclid=123",
        "https://www.alghaffar.com.pk/about/",
        True,
        "Tracking parameters stripped"
    ),
    (
        "http://www.alghaffar.com.pk/about/",
        "https://www.alghaffar.com.pk/about/",
        True,
        "HTTP vs HTTPS protocol equivalence for comparison"
    ),
    (
        "https://alghaffar.com.pk/about/",
        "https://www.alghaffar.com.pk/about/",
        True,
        "www vs non-www host equivalence for comparison"
    ),
    (
        "https://www.alghaffar.com.pk/ABOUT/",
        "https://www.alghaffar.com.pk/about/",
        True,
        "Case insensitivity in path comparison"
    ),
    (
        "https://www.alghaffar.com.pk/about#section-team",
        "https://www.alghaffar.com.pk/about/",
        True,
        "Fragment stripped"
    ),
    (
        "https://www.alghaffar.com.pk:443/about/",
        "https://www.alghaffar.com.pk/about/",
        True,
        "Default HTTPS port stripped"
    ),
    (
        "https://www.alghaffar.com.pk/services",
        "https://www.alghaffar.com.pk/about",
        False,
        "Different paths must NOT compare equal"
    ),
    (
        "https://otherdomain.com/about/",
        "https://www.alghaffar.com.pk/about/",
        False,
        "Different domains must NOT compare equal"
    ),
]

@pytest.mark.parametrize("url1,url2,expected,desc", TABLE_TEST_CASES)
def test_urls_compare_equal(url1, url2, expected, desc):
    assert urls_compare_equal(url1, url2) is expected, f"Failed: {desc}"

def test_canonical_url_key_diff_equality():
    k1 = canonical_url_key("https://www.alghaffar.com.pk/about")
    k2 = canonical_url_key("https://www.alghaffar.com.pk/about/")
    assert k1 == k2

    # In sitemap diff, /about and /about/ must never report as missing or diff
    crawled = {canonical_url_key("https://www.alghaffar.com.pk/about/")}
    sitemap = {canonical_url_key("https://www.alghaffar.com.pk/about")}
    assert len(crawled - sitemap) == 0
    assert len(sitemap - crawled) == 0

def test_normalize_url_preserves_display_form():
    # When site serves trailing slash, normalize preserves it
    assert normalize_url("https://www.alghaffar.com.pk/about/", trailing_slash=True) == "https://www.alghaffar.com.pk/about/"
    # Default strips trailing slash for non-root paths
    assert normalize_url("https://www.alghaffar.com.pk/about/") == "https://www.alghaffar.com.pk/about"
    # Relative resolution
    assert normalize_url("/trip/", base_url="https://www.alghaffar.com.pk") == "https://www.alghaffar.com.pk/trip"
    assert normalize_url("/trip/", base_url="https://www.alghaffar.com.pk", trailing_slash=True) == "https://www.alghaffar.com.pk/trip/"
    # Strips fragments
    assert normalize_url("https://www.alghaffar.com.pk/about/#team") == "https://www.alghaffar.com.pk/about"
    # Drops tracking params
    assert normalize_url("https://www.alghaffar.com.pk/about/?utm_medium=cpc&fbclid=abc") == "https://www.alghaffar.com.pk/about"
    # Preserves functional query params (e.g. search / page / category)
    norm = normalize_url("https://www.alghaffar.com.pk/tours?page=2&category=hajj")
    assert "page=2" in norm and "category=hajj" in norm

def test_detect_trailing_slash_convention():
    slash_urls = [
        "https://example.com/",
        "https://example.com/about/",
        "https://example.com/services/",
        "https://example.com/contact/"
    ]
    no_slash_urls = [
        "https://example.com/",
        "https://example.com/about",
        "https://example.com/services",
        "https://example.com/contact"
    ]
    assert detect_trailing_slash_convention(slash_urls) is True
    assert detect_trailing_slash_convention(no_slash_urls) is False
