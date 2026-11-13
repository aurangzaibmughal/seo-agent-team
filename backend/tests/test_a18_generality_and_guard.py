import os
from pathlib import Path
from app.crawler.detector import PlatformDetector

FIXTURES_DIR = Path(__file__).parent / "fixtures"

def test_a18_platform_generality_nextjs_and_shopify():
    # 1. Next.js fixture
    with open(FIXTURES_DIR / "generic" / "nextjs-fixture.html", "r", encoding="utf-8") as f:
        next_html = f.read()
    det_next = PlatformDetector()
    det_next.analyze_page("https://nextjs-app.example.com/", 200, {"x-powered-by": "Next.js"}, next_html)
    plat_next, conf_next = det_next.detect()
    assert plat_next == "nextjs"
    assert conf_next >= 0.8

    # 2. Shopify fixture
    with open(FIXTURES_DIR / "generic" / "shopify-fixture.html", "r", encoding="utf-8") as f:
        shopify_html = f.read()
    det_shop = PlatformDetector()
    det_shop.analyze_page("https://store.example.com/", 200, {}, shopify_html)
    plat_shop, conf_shop = det_shop.detect()
    assert plat_shop == "shopify"
    assert conf_shop >= 0.8

def test_a18_anti_hardcoding_guard():
    """Verifies that no client-specific brand names ('alghaffar', 'webspire') are hardcoded in application code, templates, and configurations."""
    repo_root = Path(__file__).parent.parent.parent
    forbidden = ["alghaffar", "al-ghaffar", "webspire"]
    violations = []

    scan_dirs = [
        repo_root / "backend" / "app",
        repo_root / "frontend" / "src",
    ]

    checked_extensions = (
        ".py", ".ts", ".tsx", ".js", ".json", ".html",
        ".md", ".j2", ".jinja", ".yml", ".yaml", ".sh", ".ps1", ".bat"
    )

    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for root, _, files in os.walk(scan_dir):
            for file in files:
                if file.endswith(checked_extensions):
                    path = Path(root) / file
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read().lower()
                        for term in forbidden:
                            if term in content:
                                violations.append(f"{path}: contains forbidden client-specific term '{term}'")

    assert not violations, "Client-specific hardcoding detected in production codebase:\n" + "\n".join(violations)

def test_a19_documentation_and_changelog():
    """Verifies that CHANGELOG.md, report-qa-checklist.md, and known-limitations.md exist and document hardening fixes."""
    repo_root = Path(__file__).parent.parent.parent

    changelog = repo_root / "CHANGELOG.md"
    assert changelog.exists()
    changelog_content = changelog.read_text(encoding="utf-8")
    for task_id in ["A-01", "A-02", "A-03", "A-09", "A-10", "A-12", "A-15", "A-18"]:
        assert task_id in changelog_content

    qa_checklist = repo_root / "docs" / "report-qa-checklist.md"
    assert qa_checklist.exists()
    qa_content = qa_checklist.read_text(encoding="utf-8")
    assert "checklist" in qa_content.lower() or "qa" in qa_content.lower()

    limitations = repo_root / "docs" / "known-limitations.md"
    assert limitations.exists()
    lim_content = limitations.read_text(encoding="utf-8")
    assert "limitations" in lim_content.lower() or "could not verify" in lim_content.lower()
