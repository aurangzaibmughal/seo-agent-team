import asyncio
from app.agents.orchestrator import run_full_pipeline
from app.core.db import DBManager

async def test_webspire_integration():
    target_url = "https://webspire-agency.vercel.app/"
    print(f"=== Starting Autonomous Multi-Agent Pipeline for {target_url} ===")
    
    # 1. Create Job
    job = DBManager.create_job(target_url=target_url, max_pages=30)
    job_id = job["id"]
    print(f"Created Job ID: {job_id}")

    # 2. Run full autonomous pipeline
    await run_full_pipeline(job_id=job_id, target_url=target_url, max_pages=30)

    # 3. Fetch Job results & statistics
    pages = DBManager.get_crawl_pages(job_id)
    runs = DBManager.get_agent_runs(job_id)
    psi = DBManager.get_psi_results(job_id)

    print("\n--- Crawl Results ---")
    print(f"Total Pages Crawled: {len(pages)}")
    
    error_pages = [p for p in pages if p["status_code"] >= 400]
    ok_pages = [p for p in pages if p["status_code"] == 200]
    
    print(f"200 OK Pages: {len(ok_pages)}")
    print(f"4xx/5xx Error Pages: {len(error_pages)}")
    for ep in error_pages:
        inlinks = DBManager.get_inlinks_for_url(job_id, ep["url"])
        print(f"  * Error URL: {ep['url']} (Status {ep['status_code']}) - Found on {len(inlinks)} source pages")

    # Step 0 Acceptance check:
    # A 404/5xx page must NEVER be counted as Missing Title or Missing Meta!
    missing_title_in_errors = [p for p in error_pages if not p.get("title")]
    print(f"Error pages with no title: {len(missing_title_in_errors)} (Must be ignored from on-page issues)")

    # 4. Check Agent Runs & Verified Issues
    tech_run = next((r for r in runs if r["agent"] == "technical"), None)
    verifier_run = next((r for r in runs if r["agent"] == "verifier"), None)

    assert tech_run is not None, "Technical Agent run is missing"
    assert verifier_run is not None, "Verifier Agent run is missing"

    v_report = verifier_run["output_json"]
    verified_issues = v_report.get("verified_issues", [])
    rejected_issues = v_report.get("rejected_issues", [])

    print("\n--- Technical Agent & Verifier Results ---")
    print(f"Total Verified Issues: {len(verified_issues)}")
    print(f"Total Rejected False Claims: {len(rejected_issues)}")

    for issue in verified_issues:
        print(f"[{issue['severity'].upper()}] {issue['type']} ({issue['id']})")
        print(f"  Impact: {issue['impact']}")
        print(f"  Fix: {issue['fix_hint']}")
        print(f"  Affected URLs ({len(issue['urls'])}): {issue['urls'][:2]}")
        print(f"  Evidence: {issue['evidence']}")
        print("-" * 50)

    # Check that no missing_title was generated for 404 pages
    for issue in verified_issues:
        if issue["type"] in ("missing_title", "missing_meta_description"):
            for u in issue["urls"]:
                matching_page = next((p for p in pages if p["url"] == u), None)
                if matching_page:
                    assert matching_page["status_code"] == 200, f"Violation: {issue['type']} fired on status {matching_page['status_code']}!"

    print("\nSUCCESS: All Step 0 and Milestone 2 Acceptance Criteria Verified!")

if __name__ == "__main__":
    asyncio.run(test_webspire_integration())
