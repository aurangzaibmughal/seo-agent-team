import asyncio
import os
from app.agents.orchestrator import run_full_pipeline
from app.core.db import DBManager
from app.services.reporter import ReportExporter
from app.services.performance_metrics import compute_performance_metrics
from app.agents.monitor_agent import MonitorAgent
from app.agents.verifier import Verifier
from app.models.agent_schemas import TechnicalIssue

async def verify_m3_full_integration():
    print("=== Testing Milestone 3 & Step 0 End-to-End Integration ===")
    
    target_url = "https://webspire-agency.vercel.app/"
    job = DBManager.create_job(target_url, max_pages=10)
    job_id = job["id"]
    print(f"1. Created Job ID: {job_id}")

    # Seed realistic GSC & GA4 performance data
    curr_q = [
        {"key": "web design agency", "clicks": 210, "impressions": 2800, "ctr": 7.5, "position": 4.1},
        {"key": "nextjs development services", "clicks": 115, "impressions": 1300, "ctr": 8.8, "position": 3.7},
        {"key": "seo optimization pricing", "clicks": 35, "impressions": 1600, "ctr": 2.1, "position": 11.2},
    ]
    prev_q = [
        {"key": "web design agency", "clicks": 240, "impressions": 2900, "ctr": 8.2, "position": 4.0},
        {"key": "nextjs development services", "clicks": 80, "impressions": 1000, "ctr": 8.0, "position": 4.2},
        {"key": "seo optimization pricing", "clicks": 32, "impressions": 1400, "ctr": 2.2, "position": 12.0},
    ]
    curr_p = [{"key": "https://webspire-agency.vercel.app/services", "clicks": 180, "impressions": 2200}]
    prev_p = [{"key": "https://webspire-agency.vercel.app/services", "clicks": 150, "impressions": 2000}]
    curr_ga4 = {"sessions": 3400, "engaged_sessions": 2300, "active_users": 3000, "key_events": 95}
    prev_ga4 = {"sessions": 3600, "engaged_sessions": 2400, "active_users": 3200, "key_events": 102}

    metrics = compute_performance_metrics(curr_q, prev_q, curr_p, prev_p, curr_ga4, prev_ga4)
    DBManager.save_performance_snapshot(job_id, metrics)
    print("2. Performance snapshot saved to database.")

    # Run full autonomous pipeline (Crawl -> PSI -> Technical Agent -> Verifier -> Monitor Agent -> Verifier -> Exporters)
    await run_full_pipeline(job_id=job_id, target_url=target_url, max_pages=10)
    print("3. Pipeline finished successfully.")

    # Check Agent Runs and Modes (Step 0)
    runs = DBManager.get_agent_runs(job_id)
    tech_run = next((r for r in runs if r["agent"] == "technical"), None)
    mon_run = next((r for r in runs if r["agent"] == "monitor"), None)
    ver_tech_run = next((r for r in runs if r["agent"] == "verifier"), None)
    ver_mon_run = next((r for r in runs if r["agent"] == "verifier_monitor"), None)

    assert tech_run is not None, "Technical agent run missing"
    assert mon_run is not None, "Monitor agent run missing"
    assert ver_tech_run is not None, "Verifier technical run missing"
    assert ver_mon_run is not None, "Verifier monitor run missing"

    print(f"4. Technical Agent Mode: {tech_run['mode']}")
    print(f"   Monitor Agent Mode: {mon_run['mode']}")

    # Check Verifier Audit Results
    v_tech = ver_tech_run["output_json"]
    print(f"5. Technical Issues Verified: {v_tech['verified_count']}, Rejected: {v_tech['rejected_count']}")

    v_mon = ver_mon_run["output_json"]
    print(f"6. Monitor Findings Verified: {v_mon['verified_count']}, Rejected: {v_mon['rejected_count']}")
    for f in v_mon["verified_findings"]:
        print(f"   * [{f['type'].upper()}] {f['headline']}")

    # Check Step 0: Inject Fake Issue Rejection Demo
    pages = DBManager.get_crawl_pages(job_id)
    fake_no_ev = TechnicalIssue(
        id="DEMO-NO-EV",
        type="missing_title",
        severity="high",
        impact="Fake",
        effort="low",
        urls=[pages[0]["url"]],
        evidence=[],  # EMPTY EVIDENCE
        fix_hint="None"
    )
    fake_false_claim = TechnicalIssue(
        id="DEMO-FALSE-CLAIM",
        type="missing_title",
        severity="high",
        impact="Fake",
        effort="low",
        urls=[pages[0]["url"]],
        evidence=[{"table": "crawl_pages", "id": pages[0]["id"], "field": "title"}],
        fix_hint="None"
    )
    all_issues = [TechnicalIssue.model_validate(i) for i in v_tech["verified_issues"]] + [fake_no_ev, fake_false_claim]
    demo_report = Verifier.verify_issues(job_id, all_issues)
    assert demo_report.rejected_count >= 1, "Verifier failed to reject fake claims!"
    print(f"7. Step 0 Demo: Injected 2 fake issues -> Verifier caught and rejected {demo_report.rejected_count} unbacked claims!")

    # Check Export Files (PDF, CSV, XLSX)
    reports = DBManager.get_reports(job_id)
    print(f"8. Generated Reports in DB: {len(reports)}")
    for r in reports:
        assert os.path.exists(r["file_url"]), f"Report file not found: {r['file_url']}"
        size = os.path.getsize(r["file_url"])
        print(f"   - {r['format'].upper()} ({size} bytes): {r['file_url']}")

    print("\nSUCCESS: All Step 0 & Milestone 3 Integration Criteria Verified!")

if __name__ == "__main__":
    asyncio.run(verify_m3_full_integration())
