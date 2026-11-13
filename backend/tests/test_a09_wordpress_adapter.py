import pytest
from pathlib import Path
from app.crawler.detector import PlatformDetector
from app.code_generator.templates import CodeTemplateEngine
from app.agents.code_agent import CodeGeneratorAgent
from app.models.agent_schemas import TechnicalIssue, OnPageRewrite

FIXTURES_DIR = Path(__file__).parent / "fixtures"

def test_a09_platform_detector_detects_wordpress_elementor_with_evidence():
    with open(FIXTURES_DIR / "alghaffar" / "home.html", "r", encoding="utf-8") as f:
        html = f.read()

    detector = PlatformDetector()
    detector.analyze_page("https://www.alghaffar.com.pk/", 200, {}, html)
    platform, confidence = detector.detect()

    assert platform == "wordpress"
    assert confidence >= 0.8
    # Must have evidence collected
    assert hasattr(detector, "evidence")
    assert len(detector.evidence) > 0
    # Must detect elementor in evidence or subframework
    elementor_found = any("elementor" in e.lower() for e in detector.evidence) or detector.detected_subframework == "elementor"
    assert elementor_found is True

def test_a09_wordpress_adapter_generates_instructions_and_functions():
    schema = {"@context": "https://schema.org", "@type": "TravelAgency", "name": "Al Ghaffar"}
    instructions = CodeTemplateEngine.render_wordpress_instructions()
    assert "# SEO Implementation Instructions" in instructions
    assert "metadata_table.csv" in instructions
    assert "functions.php" in instructions

    functions_php = CodeTemplateEngine.render_wordpress_functions_php(schema)
    assert "add_action('wp_head'" in functions_php
    assert "rel_canonical" in functions_php or "schema" in functions_php.lower()

@pytest.mark.asyncio
async def test_a09_code_agent_wordpress_produces_artifacts_and_fix_instructions():
    pages = [
        {"url": "https://www.alghaffar.com.pk/", "status_code": 200, "title": "Home", "meta_desc": "Meta", "indexable": True},
        {"url": "https://www.alghaffar.com.pk/about/", "status_code": 200, "title": "About", "meta_desc": "Meta", "indexable": True},
    ]
    tech_issues = [
        TechnicalIssue(
            id="T-002",
            type="missing_canonical",
            category="indexing",
            severity="high",
            title="Missing Canonical Tag",
            description="Page missing canonical",
            impact="Indexing ambiguity",
            effort="low",
            fix_hint="Add canonical link",
            urls=["https://www.alghaffar.com.pk/trip/"]
        )
    ]
    rewrites = [
        OnPageRewrite(
            url="https://www.alghaffar.com.pk/",
            current_title="Short",
            suggested_title="Al Ghaffar Travel & Tours | Hajj & Umrah Packages Karachi",
            current_meta="Theme default",
            suggested_meta="Certified travel agency in Karachi offering verified Umrah and Hajj packages."
        )
    ]

    bundle, mode, cost, err, model = await CodeGeneratorAgent.run(
        platform="wordpress",
        platform_confidence=0.95,
        verified_tech_issues=tech_issues,
        strategy_tasks=[],
        crawl_pages=pages,
        crawl_links=[],
        verified_rewrites=rewrites,
        internal_links=[]
    )

    artifact_paths = [a.file_path for a in bundle.artifacts]
    assert "FIX-INSTRUCTIONS.md" in artifact_paths
    assert "functions.php" in artifact_paths
    assert "sitemap.xml" in artifact_paths
    assert "metadata_table.csv" in artifact_paths
    assert len(bundle.artifacts) >= 5
