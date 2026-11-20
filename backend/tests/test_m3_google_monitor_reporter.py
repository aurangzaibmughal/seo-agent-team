import os
import openpyxl
from app.core.security import encrypt_token, decrypt_token
from app.services.google_data import parse_gsc_rows, parse_ga4_rows
from app.services.performance_metrics import compute_performance_metrics, calculate_pct_change
from app.agents.verifier import Verifier
from app.models.agent_schemas import MonitorFinding
from app.services.reporter import ReportExporter
from app.core.db import DBManager
from app.crawler.parser import parse_html_page

# ---------------------------------------------------------
# Step 0 Missing Tests from M2
# ---------------------------------------------------------
def test_all_non_indexable_reasons():
    """Tests each non-indexable reason: noindex_meta, noindex_header, canonical_to_other, http_error."""
    # 1. noindex_meta
    p1 = parse_html_page('<meta name="robots" content="noindex">', "https://example.com/p1", status_code=200)
    assert p1["indexable"] is False
    assert p1["indexability_status"] == "noindex_meta"

    # 2. noindex_header
    p2 = parse_html_page('<html><body>OK</body></html>', "https://example.com/p2", status_code=200, headers={"x-robots-tag": "noindex, noarchive"})
    assert p2["indexable"] is False
    assert p2["indexability_status"] == "noindex_header"

    # 3. canonical_to_other
    p3 = parse_html_page('<link rel="canonical" href="https://example.com/target">', "https://example.com/p3", status_code=200)
    assert p3["indexable"] is False
    assert p3["indexability_status"] == "canonical_to_other"

    # 4. http_error
    p4 = parse_html_page('<html>Not Found</html>', "https://example.com/p4", status_code=404)
    assert p4["indexable"] is False
    assert p4["indexability_status"] == "http_error"

def test_crawl_links_found_on_correctness():
    job = DBManager.create_job("https://example.com", max_pages=10)
    job_id = job["id"]

    # Source 1 links to Target A
    # Source 2 links to Target A
    links = [
        {"job_id": job_id, "source_url": "https://example.com/blog", "target_url": "https://example.com/404-broken", "anchor_text": "Broken Link"},
        {"job_id": job_id, "source_url": "https://example.com/about", "target_url": "https://example.com/404-broken", "anchor_text": "Click Here"},
    ]
    DBManager.save_crawl_links(links)
    
    inlinks = DBManager.get_inlinks_for_url(job_id, "https://example.com/404-broken")
    assert len(inlinks) == 2
    sources = [i["source_url"] for i in inlinks]
    assert "https://example.com/blog" in sources
    assert "https://example.com/about" in sources

def test_sitemap_comparison_counts():
    # If sitemap has 3 URLs, and crawl visited 2 of them + 1 extra
    sitemap_urls = {"https://example.com/", "https://example.com/about", "https://example.com/pricing"}
    crawled_urls = {"https://example.com/", "https://example.com/about", "https://example.com/hidden"}

    in_sitemap_not_crawled = len(sitemap_urls - crawled_urls)
    crawled_not_in_sitemap = len(crawled_urls - sitemap_urls)

    assert in_sitemap_not_crawled == 1  # /pricing
    assert crawled_not_in_sitemap == 1  # /hidden

# ---------------------------------------------------------
# Milestone M3 Tests
# ---------------------------------------------------------
def test_token_encryption_round_trip():
    original_refresh_token = "1//04ABCDefgh_mock_refresh_token_very_secret_12345"
    encrypted = encrypt_token(original_refresh_token)
    
    assert encrypted != original_refresh_token
    assert "secret" not in encrypted
    
    decrypted = decrypt_token(encrypted)
    assert decrypted == original_refresh_token

def test_authorization_user_isolation():
    """User A cannot access User B's google connection."""
    token_a = encrypt_token("refresh_a")
    token_b = encrypt_token("refresh_b")
    
    DBManager.save_google_connection("user_a", "user_a@gmail.com", token_a, ["scope1"])
    DBManager.save_google_connection("user_b", "user_b@gmail.com", token_b, ["scope2"])

    conn_a = DBManager.get_google_connection("user_a")
    assert conn_a["google_email"] == "user_a@gmail.com"
    assert decrypt_token(conn_a["encrypted_refresh_token"]) == "refresh_a"

    conn_b = DBManager.get_google_connection("user_b")
    assert conn_b["google_email"] == "user_b@gmail.com"
    assert decrypt_token(conn_b["encrypted_refresh_token"]) == "refresh_b"

def test_gsc_and_ga4_parsing_fixtures():
    # Mock GSC Response with keys, clicks, impressions
    mock_gsc = [
        {"keys": ["buy widgets online"], "clicks": 50, "impressions": 1000, "ctr": 0.05, "position": 4.5},
        {"keys": ["cheap widgets"], "clicks": 10, "impressions": 200, "ctr": 0.05, "position": 12.0}
    ]
    parsed_gsc = parse_gsc_rows(mock_gsc)
    assert len(parsed_gsc) == 2
    assert parsed_gsc[0]["key"] == "buy widgets online"
    assert parsed_gsc[0]["clicks"] == 50
    assert parsed_gsc[0]["ctr"] == 5.0  # converted to percent

    # Empty data handling
    assert parse_gsc_rows([]) == []

    # Mock GA4 Response
    mock_ga4 = [
        {
            "dimensionValues": [{"value": "2026-10-01"}],
            "metricValues": [{"value": "120"}, {"value": "90"}, {"value": "110"}, {"value": "5"}]
        }
    ]
    parsed_ga4 = parse_ga4_rows(mock_ga4)
    assert len(parsed_ga4) == 1
    assert parsed_ga4[0]["sessions"] == 120
    assert parsed_ga4[0]["key_events"] == 5

def test_performance_metrics_math_and_safeguards():
    # Test divide-by-zero safeguard
    assert calculate_pct_change(100.0, 0.0) == 100.0
    assert calculate_pct_change(0.0, 0.0) == 0.0
    assert calculate_pct_change(80.0, 100.0) == -20.0

    curr_q = [
        {"key": "striking distance term", "clicks": 20, "impressions": 500, "ctr": 4.0, "position": 11.2},
        {"key": "high imp low ctr", "clicks": 5, "impressions": 2000, "ctr": 0.25, "position": 5.0},
    ]
    prev_q = [
        {"key": "striking distance term", "clicks": 15, "impressions": 450, "ctr": 3.3, "position": 12.1},
        {"key": "high imp low ctr", "clicks": 6, "impressions": 1900, "ctr": 0.31, "position": 5.2},
    ]
    curr_p = [{"key": "https://example.com/drop", "clicks": 10, "impressions": 100}]
    prev_p = [{"key": "https://example.com/drop", "clicks": 25, "impressions": 150}]

    metrics = compute_performance_metrics(curr_q, prev_q, curr_p, prev_p, {"sessions": 500}, {"sessions": 600})

    # Striking distance check (position 11.2 between 8 and 20)
    sd_keys = [q["query"] for q in metrics["striking_distance_queries"]]
    assert "striking distance term" in sd_keys

    # Declining page check (clicks dropped from 25 to 10 -> -60%)
    dec_urls = [p["url"] for p in metrics["declining_pages"]]
    assert "https://example.com/drop" in dec_urls

def test_verifier_monitor_findings_audit():
    snapshot_id = "snap-123"
    snapshot = {
        "summary_totals": {
            "clicks": 500,
            "previous_clicks": 650,
            "clicks_change_pct": -23.1,
            "impressions": 10000,
            "avg_position": 6.5
        }
    }

    # 1. Valid finding -> verified
    valid_finding = MonitorFinding(
        id="P-001",
        type="traffic_drop",
        headline="Clicks dropped by 23.1%",
        explanation="Traffic fell from 650 to 500 clicks (-23.1%).",
        metrics_used=[{"snapshot_id": snapshot_id, "field": "clicks_change_pct", "value": -23.1}],
        recommended_action="Inspect drops",
        confidence=0.95
    )
    res_valid = Verifier.verify_monitor_findings(snapshot_id, snapshot, [valid_finding])
    assert res_valid.verified_count == 1
    assert res_valid.rejected_count == 0

    # 2. Rejection: Empty metrics_used
    finding_no_metrics = MonitorFinding(
        id="P-002",
        type="traffic_drop",
        headline="Drop",
        explanation="Drop",
        metrics_used=[],
        recommended_action="Inspect",
        confidence=0.9
    )
    res_no_met = Verifier.verify_monitor_findings(snapshot_id, snapshot, [finding_no_metrics])
    assert res_no_met.rejected_count == 1

    # 3. Rejection: Wrong value
    finding_wrong_val = MonitorFinding(
        id="P-003",
        type="traffic_drop",
        headline="Drop",
        explanation="Drop",
        metrics_used=[{"snapshot_id": snapshot_id, "field": "clicks_change_pct", "value": -99.9}],  # Stored is -23.1
        recommended_action="Inspect",
        confidence=0.9
    )
    res_wrong_val = Verifier.verify_monitor_findings(snapshot_id, snapshot, [finding_wrong_val])
    assert res_wrong_val.rejected_count == 1

    # 4. Rejection: Untraceable number in narrative
    finding_fake_number = MonitorFinding(
        id="P-004",
        type="traffic_drop",
        headline="We lost 987654 users",  # 987654 is not in snapshot!
        explanation="Untraceable number",
        metrics_used=[{"snapshot_id": snapshot_id, "field": "clicks_change_pct", "value": -23.1}],
        recommended_action="Inspect",
        confidence=0.9
    )
    res_fake_num = Verifier.verify_monitor_findings(snapshot_id, snapshot, [finding_fake_number])
    assert res_fake_num.rejected_count == 1
    assert "Untraceable number" in res_fake_num.rejected_findings[0]["reason"]

    # 5. Rejection: traffic_drop on positive data
    finding_inverted_type = MonitorFinding(
        id="P-005",
        type="traffic_drop",
        headline="Drop claim",
        explanation="Drop claim",
        metrics_used=[{"snapshot_id": snapshot_id, "field": "clicks_change_pct", "value": 15.0}],  # Positive value!
        recommended_action="Inspect",
        confidence=0.9
    )
    res_inv = Verifier.verify_monitor_findings(snapshot_id, snapshot, [finding_inverted_type])
    assert res_inv.rejected_count == 1

def test_report_exporters_pdf_csv_xlsx():
    job_id = "test-job-m3-exporter"
    issues = [
        {"id": "T-001", "type": "missing_title", "severity": "high", "urls": ["https://example.com/p1"], "impact": "Bad title", "fix_hint": "Add title"}
    ]
    perf = {
        "summary_totals": {
            "clicks": 1200, "previous_clicks": 1000, "clicks_change_pct": 20.0,
            "impressions": 20000, "previous_impressions": 18000, "impressions_change_pct": 11.1,
            "ctr": 6.0, "previous_ctr": 5.5, "ctr_change_abs": 0.5,
            "avg_position": 5.2, "previous_avg_position": 5.8, "avg_position_change_abs": -0.6,
            "organic_sessions": 2500, "previous_organic_sessions": 2200, "sessions_change_pct": 13.6
        },
        "striking_distance_queries": [{"query": "test query", "position": 12.0, "impressions": 500, "clicks": 25}]
    }

    # 1. PDF
    pdf_path = ReportExporter.generate_pdf(job_id, "https://example.com", issues, perf, agency_name="Digital Pro")
    assert os.path.exists(pdf_path)
    assert os.path.getsize(pdf_path) > 1000

    # 2. CSV
    csv_path = ReportExporter.generate_csv(job_id, issues, perf)
    assert os.path.exists(csv_path)
    with open(csv_path, "r", encoding="utf-8") as f:
        content = f.read()
        assert "missing_title" in content
        assert "test query" in content

    # 3. XLSX
    xlsx_path = ReportExporter.generate_xlsx(job_id, "https://example.com", issues, perf)
    assert os.path.exists(xlsx_path)
    wb = openpyxl.load_workbook(xlsx_path)
    assert "Summary" in wb.sheetnames
    assert "Technical Issues" in wb.sheetnames
    assert "Opportunities" in wb.sheetnames

def test_report_generates_when_performance_not_connected():
    job_id = "test-job-not-connected"
    issues = [{"id": "T-001", "type": "broken_link_4xx", "severity": "high", "urls": ["https://example.com/404"], "impact": "Broken link", "fix_hint": "Fix"}]
    
    # Pass None for performance_data
    pdf_path = ReportExporter.generate_pdf(job_id, "https://example.com", issues, None)
    assert os.path.exists(pdf_path)
    assert os.path.getsize(pdf_path) > 500
