from pathlib import Path
import pytest
from app.crawler.parser import parse_html_page
from app.agents.issue_rules import detect_issues_from_data
from app.services.reporter import ReportExporter

FIXTURES_DIR = Path(__file__).parent / "fixtures"

def test_a04_canonical_audit_flags_trip_without_canonical_and_not_home():
    # Read fixtures
    with open(FIXTURES_DIR / "alghaffar" / "home.html", "r", encoding="utf-8") as f:
        home_html = f.read()
    with open(FIXTURES_DIR / "alghaffar" / "about.html", "r", encoding="utf-8") as f:
        about_html = f.read()
    with open(FIXTURES_DIR / "alghaffar" / "trip-no-canonical.html", "r", encoding="utf-8") as f:
        trip_no_can_html = f.read()

    p_home = parse_html_page(home_html, "https://www.alghaffar.com.pk/", status_code=200)
    p_about = parse_html_page(about_html, "https://www.alghaffar.com.pk/about/", status_code=200)
    p_trip = parse_html_page(trip_no_can_html, "https://www.alghaffar.com.pk/trip/", status_code=200)

    # Home and About have self canonicals
    assert p_home["canonical"] == "https://www.alghaffar.com.pk/"
    assert p_about["canonical"] == "https://www.alghaffar.com.pk/about/"
    # Trip has NO canonical
    assert p_trip["canonical"] is None

    candidates = detect_issues_from_data(
        crawl_pages=[p_home, p_about, p_trip],
        crawl_links=[],
        psi_results=[]
    )
    can_issues = [c for c in candidates if c["type"] == "missing_canonical"]
    assert len(can_issues) == 1
    # MUST contain exactly the trip URL
    assert can_issues[0]["urls"] == ["https://www.alghaffar.com.pk/trip/"]
    assert "https://www.alghaffar.com.pk/" not in can_issues[0]["urls"]
    assert "https://www.alghaffar.com.pk/about/" not in can_issues[0]["urls"]

def test_a05_duplicate_groups_with_exact_strings():
    p1 = {"id": "1", "url": "https://example.com/p1", "status_code": 200, "title": "Shared Title", "meta_desc": "Shared Meta", "indexable": True}
    p2 = {"id": "2", "url": "https://example.com/p2", "status_code": 200, "title": "Shared Title", "meta_desc": "Shared Meta", "indexable": True}
    p3 = {"id": "3", "url": "https://example.com/p3", "status_code": 200, "title": "Unique Title", "meta_desc": "Unique Meta", "indexable": True}

    candidates = detect_issues_from_data(
        crawl_pages=[p1, p2, p3],
        crawl_links=[],
        psi_results=[]
    )
    dup_titles = [c for c in candidates if c["type"] == "duplicate_title"]
    assert len(dup_titles) == 1
    assert dup_titles[0]["group_key"] == "shared title"
    assert set(dup_titles[0]["urls"]) == {"https://example.com/p1", "https://example.com/p2"}

def test_a06_csv_export_contains_per_url_evidence():
    job_id = "test-a06-evidence-job"
    issues = [
        {
            "id": "T-002",
            "type": "missing_canonical",
            "severity": "high",
            "urls": ["https://www.alghaffar.com.pk/trip/"],
            "impact": "Missing canonical tag",
            "fix_hint": "Add self-referential canonical"
        }
    ]
    csv_path = ReportExporter.generate_csv(job_id, issues, None)
    with open(csv_path, "r", encoding="utf-8") as f:
        content = f.read()
        assert "https://www.alghaffar.com.pk/trip/" in content
        assert "T-002" in content
