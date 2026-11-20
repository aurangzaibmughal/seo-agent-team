import pytest
from app.agents.issue_rules import detect_issues_from_data

PLACEHOLDER_METAS = [
    "IT Service WordPress Theme",
    "Just another WordPress site",
    "Lorem ipsum dolor sit amet",
    "Default description text here",
    "Your tagline here",
    "My WordPress Blog - Coming Soon",
]

@pytest.mark.parametrize("placeholder", PLACEHOLDER_METAS)
def test_placeholder_meta_detected_as_high_severity(placeholder):
    crawl_pages = [
        {
            "id": "p-ph",
            "url": "https://www.alghaffar.com.pk/",
            "status_code": 200,
            "title": "Al Ghaffar Travel - Karachi",
            "h1": "Explore The World",
            "meta_desc": placeholder,
            "indexable": True,
            "indexability_status": "indexable"
        }
    ]
    candidates = detect_issues_from_data(crawl_pages=crawl_pages, crawl_links=[], psi_results=[])
    types = [c["type"] for c in candidates]
    assert "meta_description_placeholder" in types
    ph_issue = next(c for c in candidates if c["type"] == "meta_description_placeholder")
    assert ph_issue["severity"] == "high"
    assert ph_issue["urls"] == ["https://www.alghaffar.com.pk/"]

def test_short_meta_description_detected():
    # 26 chars meta description
    crawl_pages = [
        {
            "id": "p-short",
            "url": "https://www.alghaffar.com.pk/about/",
            "status_code": 200,
            "title": "About Al Ghaffar Travel",
            "h1": "About Us",
            "meta_desc": "Short agency description.",  # 25 chars < 70
            "indexable": True,
            "indexability_status": "indexable"
        }
    ]
    candidates = detect_issues_from_data(crawl_pages=crawl_pages, crawl_links=[], psi_results=[])
    types = [c["type"] for c in candidates]
    assert "meta_description_too_short" in types

def test_alghaffar_fixture_detects_placeholder_short_and_duplicate_group():
    # Home, About, Services all have "IT Service WordPress Theme"
    crawl_pages = [
        {
            "id": "p1",
            "url": "https://www.alghaffar.com.pk/",
            "status_code": 200,
            "title": "Al Ghaffar Travel",
            "h1": "Explore The World",
            "meta_desc": "IT Service WordPress Theme",
            "indexable": True,
            "indexability_status": "indexable"
        },
        {
            "id": "p2",
            "url": "https://www.alghaffar.com.pk/about/",
            "status_code": 200,
            "title": "About Us",
            "h1": "About",
            "meta_desc": "IT Service WordPress Theme",
            "indexable": True,
            "indexability_status": "indexable"
        },
    ]
    candidates = detect_issues_from_data(crawl_pages=crawl_pages, crawl_links=[], psi_results=[])
    types = [c["type"] for c in candidates]
    assert "meta_description_placeholder" in types
    assert "meta_description_too_short" in types
    assert "duplicate_meta_description" in types

    dup_issue = next(c for c in candidates if c["type"] == "duplicate_meta_description")
    assert len(dup_issue["urls"]) == 2
    assert "https://www.alghaffar.com.pk/" in dup_issue["urls"]
    assert "https://www.alghaffar.com.pk/about/" in dup_issue["urls"]
