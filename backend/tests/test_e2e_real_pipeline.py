import os
import re
import json
import threading
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from unittest.mock import patch

import pytest
import pypdf

from app.core.db import DBManager
from app.core.config import settings
from app.agents.orchestrator import run_full_pipeline
from app.services.reporter import ReportExporter
from app.services.report_linter import lint_audit_report
from app.crawler.url_utils import canonical_url_key

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "alghaffar_real")

# Mapping of URL paths to fixture HTML files
PATH_TO_FIXTURE = {
    "/": "home.html",
    "/about/": "about.html",
    "/career/": "career.html",
    "/contact/": "contact.html",
    "/faqs/": "faqs.html",
    "/services/": "services.html",
    "/trip/": "trip.html",
    "/destinations/kuala-lumpur/": "destinations_kuala_lumpur.html",
    "/destinations/sri-lanka/": "destinations_sri_lanka.html",
    "/destinations/thailand/": "destinations_thailand.html",
    "/trip/kuala-lumpur/": "trip_kuala_lumpur.html",
    "/trip/sri-lanka/": "trip_sri_lanka.html",
    "/trip/thailand/": "trip_thailand.html",
}

class MockAlGhaffarHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        # Silence HTTP server logging during tests
        pass

    def end_headers(self):
        self.send_header("Connection", "close")
        super().end_headers()

    def do_GET(self):
        host = self.headers.get("Host") or f"127.0.0.1:{self.server.server_port}"
        base_origin = f"http://{host}"

        # 1. robots.txt
        if self.path == "/robots.txt":
            body = f"User-agent: *\nAllow: /\nSitemap: {base_origin}/sitemap.xml\n".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # 2. sitemap.xml
        if self.path == "/sitemap.xml":
            # 12 URLs in sitemap (all except /trip/ which is intentionally missing to test sitemap diff)
            sitemap_urls = [
                f"{base_origin}/",
                f"{base_origin}/about/",
                f"{base_origin}/career/",
                f"{base_origin}/contact/",
                f"{base_origin}/faqs/",
                f"{base_origin}/services/",
                f"{base_origin}/destinations/kuala-lumpur/",
                f"{base_origin}/destinations/sri-lanka/",
                f"{base_origin}/destinations/thailand/",
                f"{base_origin}/trip/kuala-lumpur/",
                f"{base_origin}/trip/sri-lanka/",
                f"{base_origin}/trip/thailand/",
            ]
            xml_lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
            for u in sitemap_urls:
                xml_lines.append(f"  <url><loc>{u}</loc><lastmod>2026-11-14</lastmod></url>")
            xml_lines.append("</urlset>")
            body = "\n".join(xml_lines).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # 3. 4xx URL: /broken-page -> HTTP 404
        if self.path == "/broken-page":
            body = b"<html><body><h1>404 Not Found</h1></body></html>"
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # 4. 403 URL: /blocked-page -> HTTP 403 (blocked by server)
        if self.path == "/blocked-page":
            body = b"<html><body><h1>403 Forbidden</h1></body></html>"
            self.send_response(403)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # 5. /cdn-cgi/ link
        if self.path.startswith("/cdn-cgi/"):
            body = b"<html><body>Cloudflare email protection</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # 6. /wp-json/ or /?p=
        if self.path.startswith("/wp-json/") or "?p=" in self.path:
            body = b'{"status": "ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # 7. Normalize path and look up in fixtures
        norm_path = self.path.split("?")[0]
        if not norm_path.endswith("/") and norm_path != "/":
            # If requesting /services without slash, serve 200 or 301
            # Here we serve directly to test trailing slash inconsistency
            pass

        fixture_file = PATH_TO_FIXTURE.get(norm_path) or PATH_TO_FIXTURE.get(norm_path + "/")
        fixture_path = os.path.join(FIXTURES_DIR, fixture_file) if fixture_file else ""
        if not fixture_file or not os.path.exists(fixture_path):
            body = b"<html><body><h1>404 Not Found</h1></body></html>"
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        with open(fixture_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Replace https://www.alghaffar.com.pk with our mock base_origin
        content = content.replace("https://www.alghaffar.com.pk", base_origin)

        # Inject real WordPress / Elementor markers, test links, and trailing slash test links
        if norm_path == "/":
            extra_tags = f"""
            <meta name="generator" content="Elementor 4.2.3; wp-elementor">
            <link rel="stylesheet" href="{base_origin}/wp-content/plugins/elementor/css/frontend.css">
            <link rel="shortlink" href="{base_origin}/?p=42">
            """
            extra_nav = f"""
            <nav id="test-nav">
                <a href="{base_origin}/about/">About</a>
                <a href="{base_origin}/career/">Career</a>
                <a href="{base_origin}/contact/">Contact</a>
                <a href="{base_origin}/faqs/">FAQs</a>
                <a href="{base_origin}/services">Services (No Slash)</a>
                <a href="{base_origin}/trip/">Trips Overview</a>
                <a href="{base_origin}/destinations/kuala-lumpur/">Kuala Lumpur Destination</a>
                <a href="{base_origin}/destinations/sri-lanka/">Sri Lanka Destination</a>
                <a href="{base_origin}/destinations/thailand/">Thailand Destination</a>
                <a href="{base_origin}/trip/kuala-lumpur/">Kuala Lumpur Trip</a>
                <a href="{base_origin}/trip/sri-lanka/">Sri Lanka Trip</a>
                <a href="{base_origin}/trip/thailand/">Thailand Trip</a>
                <a href="{base_origin}/broken-page">Broken Page</a>
                <a href="{base_origin}/blocked-page">Blocked Page</a>
                <a href="{base_origin}/cdn-cgi/l/email-protection">Email Protection Link</a>
                <a href="{base_origin}/wp-json/wp/v2/pages">WordPress REST API</a>
                <a href="https://www.google.com/">Google External Link</a>
            </nav>
            """
            content = content.replace("</head>", f"{extra_tags}\n</head>")
            content = content.replace("<body>", f"<body>\n{extra_nav}")
        else:
            # Add home link and navigation
            nav = f'<nav><a href="{base_origin}/">Home</a> <a href="{base_origin}/services/">Services</a></nav>'
            content = content.replace("<body>", f"<body>\n{nav}")

        body = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if norm_path == "/":
            self.send_header("X-Powered-By", "WordPress")
            self.send_header("Link", f'<{base_origin}/wp-json/>; rel="https://api.w.org/"')
        self.end_headers()
        self.wfile.write(body)

@pytest.fixture(scope="module")
def mock_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockAlGhaffarHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    yield base_url
    server.shutdown()
    server.server_close()

async def mock_median_psi_for_url(client, job_id, url, strategy="mobile", n_runs=3, ignore_cache=False):
    """Deterministic PSI response for the mock server's URLs with slow_lcp on /services/."""
    is_mobile = strategy == "mobile"
    is_services = "services" in url
    score = 42 if is_services else (78 if is_mobile else 92)
    lcp = 4500 if is_services else 2100
    cls_v = 0.05
    res = {
        "job_id": job_id,
        "url": url,
        "strategy": strategy,
        "performance_score": score,
        "lcp_ms": lcp,
        "cls": cls_v,
        "inp_or_tbt_ms": 150,
        "fcp_ms": 1800,
        "ttfb_ms": 250,
        "is_cached": False,
        "runs_count": n_runs,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "error": None
    }
    DBManager.save_psi_result(res)
    return res

@pytest.mark.asyncio
async def test_e2e_real_pipeline_alghaffar_real(mock_server):
    """End-to-End integration test running the REAL pipeline (crawler -> agents -> reporter -> PDF)
    against the alghaffar_real fixtures served from local mock HTTP server.
    """
    base_url = mock_server

    # Create non-demo job targeting the mock server
    job = DBManager.create_job(target_url=base_url, max_pages=50, is_demo=False)
    job_id = job["id"]

    # Run the real pipeline with SSRF check bypassed for mock server and PSI mocked for deterministic Lighthouse results
    with patch.object(settings, "GEMINI_API_KEY", ""), \
         patch("app.core.security.validate_safe_url", side_effect=lambda u, *args, **kwargs: u), \
         patch("app.crawler.engine.validate_safe_url", side_effect=lambda u, *args, **kwargs: u), \
         patch("app.core.security.is_ip_prohibited", return_value=False), \
         patch("app.services.pagespeed.run_median_psi_for_url", side_effect=mock_median_psi_for_url):
        await run_full_pipeline(job_id, base_url, max_pages=50, resume=False)

    # -------------------------------------------------------------------------
    # 1. P0-1: 30-Day Plan Verification (Deterministic Fallback)
    # -------------------------------------------------------------------------
    strat_rec = DBManager.get_strategy_plan(job_id)
    assert strat_rec is not None, "Strategy plan record must exist in DB."
    strat_data = strat_rec.get("plan", {})
    tasks = strat_data.get("tasks", [])
    assert len(tasks) > 0, "30-day action plan must not be empty ('No strategy tasks generated')."
    assert any(t["id"].startswith("S-") for t in tasks), "Tasks must follow S-001 ID convention."

    # -------------------------------------------------------------------------
    # 2. P0-2: Platform Detection & WordPress Adapter Bundle
    # -------------------------------------------------------------------------
    updated_job = DBManager.get_job(job_id)
    assert updated_job["platform"] == "wordpress", f"Platform should be detected as wordpress, got {updated_job.get('platform')}"
    assert updated_job["detected_platform"] == "wordpress"

    code_rec = DBManager.get_code_output(job_id)
    assert code_rec is not None, "Code output record must exist in DB."
    bundle = code_rec.get("code", {}).get("bundle", {})
    assert bundle.get("platform") == "wordpress", f"Code bundle platform must be wordpress, got {bundle.get('platform')}"
    artifacts = bundle.get("artifacts", [])
    assert len(artifacts) > 0, "WordPress adapter must generate code artifacts (> 0)."
    artifact_types = [a.get("artifact_type") for a in artifacts]
    assert "wordpress_functions_php" in artifact_types
    assert "wordpress_instructions" in artifact_types

    # -------------------------------------------------------------------------
    # 3. P0-4: Crawl Budget, Junk Links, and Referring Page Tracking
    # -------------------------------------------------------------------------
    crawled_pages = DBManager.get_crawl_pages(job_id, limit=2000)
    crawled_200 = [p["url"] for p in crawled_pages if p.get("status_code") == 200]
    crawled_urls = [p["url"] for p in crawled_pages]

    # /broken-page (404) must NOT count toward max_pages or appear as 200 OK crawl_pages
    assert f"{base_url}/broken-page" not in crawled_200
    assert updated_job["pages_crawled"] == len(crawled_200)

    # Failed fetches record status_code, reason, and referring_url
    failed_fetches = json.loads(updated_job.get("failed_fetches_json") or "[]")
    assert any(f.get("url") == f"{base_url}/broken-page" and f.get("status_code") == 404 for f in failed_fetches), \
        "Failed fetch /broken-page must be recorded with HTTP 404 in failed_fetches_json"
    broken_fetch = next(f for f in failed_fetches if f.get("url") == f"{base_url}/broken-page")
    assert broken_fetch.get("referring_url") == f"{base_url}/", "Failed fetch must track referring page"

    # /cdn-cgi/ and /wp-json/ and ?p= must NOT be followed
    assert not any("/cdn-cgi/" in u for u in crawled_urls), "/cdn-cgi/ must not be crawled"
    assert not any("/wp-json/" in u for u in crawled_urls), "/wp-json/ must not be crawled"
    assert not any("?p=" in u for u in crawled_urls), "Shortlinks (?p=) must not be crawled"

    # 403 /blocked-page must be classified as blocked_by_server, not broken_link_4xx
    runs = DBManager.get_agent_runs(job_id)
    ver_run = next((r for r in runs if r["agent"] == "verifier"), None)
    verified_issues = ver_run["output_json"].get("verified_issues", []) if ver_run else []
    issue_types = [i["type"] for i in verified_issues]
    assert "blocked_by_server" in issue_types or any(f.get("status_code") == 403 for f in failed_fetches), \
        "403 status must be treated as blocked_by_server, not broken link"
    assert not any(i["type"] == "broken_link_4xx" and f"{base_url}/blocked-page" in i.get("urls", []) for i in verified_issues), \
        "403 status must not be classified as broken_link_4xx"

    # -------------------------------------------------------------------------
    # 4. P0-5 & P0-6: Crawl Numbers Consistency & Trailing Slash Inconsistency
    # -------------------------------------------------------------------------
    in_sitemap_not_crawled = updated_job.get("in_sitemap_not_crawled", 0)
    crawled_not_in_sitemap = updated_job.get("crawled_not_in_sitemap", 0)
    pages_crawled = updated_job.get("pages_crawled", 0)
    sitemap_entries = json.loads(updated_job.get("sitemap_entries_json") or "[]")
    
    # Cross-check: in_sitemap_not_crawled + (pages_crawled - crawled_not_in_sitemap) == total_sitemap_urls
    crawled_overlap = pages_crawled - crawled_not_in_sitemap
    assert in_sitemap_not_crawled + crawled_overlap == len(sitemap_entries), \
        f"Sitemap numbers must be consistent: {len(sitemap_entries)} total, {in_sitemap_not_crawled} not crawled, {pages_crawled} crawled"

    # Trailing slash inconsistency detected for /services (internal link form vs final served URL)
    ts_issue = next((i for i in verified_issues if i["type"] == "trailing_slash_inconsistency"), None)
    assert ts_issue is not None, "trailing_slash_inconsistency must be detected"
    assert "internal link" in ts_issue.get("impact", "").lower() or "canonical" in ts_issue.get("impact", "").lower()

    # -------------------------------------------------------------------------
    # 5. P0-7: PageSpeed Invariant (Every Cited URL in Source Table)
    # -------------------------------------------------------------------------
    psi_results = DBManager.get_psi_results(job_id)
    psi_urls = {canonical_url_key(p["url"]) for p in psi_results if p.get("url")}
    speed_issues = [i for i in verified_issues if i["type"] in ("slow_lcp", "poor_cls", "low_performance_score")]
    for iss in speed_issues:
        for u in iss.get("urls", []):
            assert canonical_url_key(u) in psi_urls, f"URL {u} cited by {iss['type']} must exist in PSI table"

    # -------------------------------------------------------------------------
    # 6. P0-3: Report QA Lint Gate Injections & Status Partial
    # -------------------------------------------------------------------------
    # Invariant 1: Empty plan injection fails lint gate
    warns_empty_plan = lint_audit_report(
        job=updated_job,
        tech_issues=verified_issues,
        strategy_tasks=[],
        rewrites=[],
        psi_results=psi_results,
        code_bundle=bundle
    )
    assert any("0 strategy tasks" in w for w in warns_empty_plan)

    # Invariant 2: 0-file bundle injection fails lint gate
    warns_0_bundle = lint_audit_report(
        job=updated_job,
        tech_issues=verified_issues,
        strategy_tasks=tasks,
        rewrites=[],
        psi_results=psi_results,
        code_bundle={"platform": "wordpress", "artifacts": []}
    )
    assert any("0 code artifacts generated" in w for w in warns_0_bundle)

    # Invariant 3: Speed finding with missing source-table row fails lint gate
    fake_tech_issue = [{
        "id": "T-999",
        "type": "slow_lcp",
        "severity": "high",
        "urls": [f"{base_url}/phantom-uncached-page"]
    }]
    warns_missing_source = lint_audit_report(
        job=updated_job,
        tech_issues=fake_tech_issue,
        strategy_tasks=tasks,
        rewrites=[],
        psi_results=psi_results,
        code_bundle=bundle
    )
    assert any("no entry in the PageSpeed source table" in w for w in warns_missing_source)

    # Invariant 4: When QA warnings are present, PDF includes "Report Quality Notes" banner and status is "partial"
    pdf_with_banner_path = ReportExporter.generate_pdf(
        job_id=job_id,
        target_url=base_url,
        verified_issues=fake_tech_issue,
        performance_data=None,
        strategy_data=strat_data,
        content_data=None,
        code_data=code_rec.get("code"),
        psi_data=psi_results,
        is_demo=False,
        strict_lint_gate=False
    )
    assert os.path.exists(pdf_with_banner_path)
    job_after_lint = DBManager.get_job(job_id)
    assert job_after_lint["status"] == "partial", "Job status must be 'partial', never 'complete' when QA warnings occur"

    # Verify banner in PDF text
    reader_banner = pypdf.PdfReader(pdf_with_banner_path)
    full_text_banner = "\n".join(page.extract_text() for page in reader_banner.pages)
    assert "Report Quality Notes" in full_text_banner

    # -------------------------------------------------------------------------
    # 7. Extract & Assert Final PDF Content (Sections 3 & 5)
    # -------------------------------------------------------------------------
    exports_dir = os.path.join(os.path.dirname(__file__), "..", "exports")
    pdf_path = os.path.join(exports_dir, f"SEO_Report_{job_id[:8]}.pdf")
    assert os.path.exists(pdf_path), f"Final PDF must exist at {pdf_path}"

    reader = pypdf.PdfReader(pdf_path)
    assert len(reader.pages) >= 2, "Report PDF should have multiple pages"
    full_pdf_text = "\n".join(page.extract_text() for page in reader.pages)

    # Section 3 assertions: 30-Day Strategy Roadmap
    assert "30-Day Prioritized SEO Action Plan" in full_pdf_text
    assert "S-001" in full_pdf_text

    # Section 5/6 assertions: Implementation Code & Adapter Bundle
    assert "Target Platform: WORDPRESS" in full_pdf_text or "WORDPRESS" in full_pdf_text
    assert "WORDPRESS" in full_pdf_text

    print("\n--- SECTION 3 EXTRACTED PDF TEXT ---")
    s3_match = re.search(r"\d+\.\s+30-Day Prioritized SEO Action Plan.*?(?=\d+\.\s+Content|\d+\.\s+Automated Code Fixes|$)", full_pdf_text, re.DOTALL)
    if s3_match:
        print(s3_match.group(0)[:1500])
    else:
        print(full_pdf_text[:1000])

    print("\n--- SECTION 5 EXTRACTED PDF TEXT ---")
    s5_match = re.search(r"\d+\.\s+Automated Code Fixes.*?(?=\d+\.\s+Page Inventory|$)", full_pdf_text, re.DOTALL)
    if s5_match:
        print(s5_match.group(0)[:1500])
    else:
        print(full_pdf_text[-1500:])
