from pathlib import Path
from app.models.agent_schemas import TechnicalIssue
from app.agents.strategist_agent import StrategistAgent
from app.agents.content_agent import ContentAgent

FIXTURES_DIR = Path(__file__).parent / "fixtures"

def test_a07_strategist_fallback_generates_4_week_plan_from_issues_without_gsc():
    tech_issues = [
        TechnicalIssue(
            id="T-001",
            type="missing_canonical",
            severity="high",
            impact="high",
            effort="low",
            fix_hint="Add rel canonical",
            urls=["https://www.alghaffar.com.pk/trip/"]
        ),
        TechnicalIssue(
            id="T-002",
            type="meta_description_placeholder",
            severity="high",
            impact="high",
            effort="low",
            fix_hint="Replace theme default text",
            urls=["https://www.alghaffar.com.pk/", "https://www.alghaffar.com.pk/about/"]
        ),
        TechnicalIssue(
            id="T-003",
            type="slow_lcp",
            severity="high",
            impact="high",
            effort="medium",
            fix_hint="Optimize hero image",
            urls=["https://www.alghaffar.com.pk/"]
        ),
        TechnicalIssue(
            id="T-004",
            type="title_too_short",
            severity="medium",
            impact="medium",
            effort="low",
            fix_hint="Expand title",
            urls=["https://www.alghaffar.com.pk/about/"]
        )
    ]

    report = StrategistAgent._run_deterministic(
        tech_issues=tech_issues,
        perf_findings=[],
        research_opps=[]
    )

    assert report.tasks, "Strategist report must have tasks even without GSC/research"
    assert len(report.tasks) >= 4
    weeks = {t.week for t in report.tasks}
    # Tasks must span multiple weeks
    assert 1 in weeks
    assert 2 in weeks
    # High severity in week 1
    w1_tasks = [t for t in report.tasks if t.week == 1]
    assert any("canonical" in t.title.lower() for t in w1_tasks)

def test_a08_content_rewrites_without_gsc_and_no_webspire_hardcoding():
    pages = [
        {
            "url": "https://www.alghaffar.com.pk/",
            "status_code": 200,
            "title": "Al Ghaffar Travel",  # 17 chars (too short)
            "meta_desc": "IT Service WordPress Theme",  # placeholder
            "h1": "Al Ghaffar Travel & Tours Karachi",
            "body_text": "We provide Umrah and Hajj packages in Karachi Pakistan.",
            "indexable": True
        },
        {
            "url": "https://www.alghaffar.com.pk/about/",
            "status_code": 200,
            "title": "About Us",  # 8 chars (too short)
            "meta_desc": "IT Service WordPress Theme",  # placeholder
            "h1": "About Al Ghaffar Travel Agency",
            "body_text": "Trusted travel agency with 15 years experience.",
            "indexable": True
        }
    ]

    report = ContentAgent._run_deterministic(
        verified_research=[],
        crawl_pages=pages,
        internal_links=[],
        research_snapshot={},
        competitor_pages=[]
    )

    assert len(report.rewrites) == 2
    for rw in report.rewrites:
        # Absolutely NO hardcoded 'WebSpire'
        assert "webspire" not in (rw.suggested_title or "").lower()
        assert "webspire" not in (rw.suggested_meta or "").lower()
        # Title length strictly 50-60
        assert 45 <= len(rw.suggested_title) <= 60
        # Meta length strictly 120-155
        assert 120 <= len(rw.suggested_meta) <= 155
        # Must NOT retain placeholder text
        assert "it service wordpress theme" not in (rw.suggested_meta or "").lower()
