import asyncio
import json
import sqlite3
import time
from app.core.db import DBManager
from app.agents.orchestrator import run_full_pipeline

async def main():
    target_url = "https://agency-sandbox.example.com/"
    max_pages = 30
    is_demo = False

    print("=== CREATING AND RUNNING NEW NON-DEMO JOB ===")
    job = DBManager.create_job(
        target_url=target_url,
        max_pages=max_pages,
        project_id=None,
        competitor_domains=[],
        is_demo=is_demo
    )
    job_id = job["id"]
    print(f"Created Job ID: {job_id}")
    print(f"Running full pipeline for {target_url} (is_demo={is_demo})...")

    start_time = time.time()
    await run_full_pipeline(job_id, target_url, max_pages, None)
    elapsed = int(time.time() - start_time)
    print(f"\nPipeline finished in {elapsed}s.")

    # Inspect the database directly for exact verified reports
    conn = sqlite3.connect("local_seo.db")
    c = conn.cursor()

    row = c.execute("SELECT id, target_url, status, pages_crawled, cost_usd, is_demo, failed_fetches_json, crawl_incomplete FROM jobs WHERE id = ?", (job_id,)).fetchone()
    print("\n" + "="*70)
    print("JOB AUDIT PROOF REPORT")
    print("="*70)
    print(f"Job ID: {row[0]}")
    print(f"Target URL: {row[1]}")
    print(f"Status: {row[2]}")
    print(f"Pages Crawled: {row[3]}")
    print(f"Cost USD: ${row[4]:.6f}")
    print(f"Is Demo: {bool(row[5])}")
    print(f"Crawl Incomplete: {bool(row[7])}")

    failed_fetches = json.loads(row[6]) if row[6] else []
    print(f"\nCrawler Failed Fetches ({len(failed_fetches)}):")
    if failed_fetches:
        for f in failed_fetches:
            print(f"  • {f.get('url')} -> {f.get('reason')} at {f.get('timestamp')}")
    else:
        print("  0 failed fetches (clean crawl)")

    # 1. Internal Link Suggestions
    print("\n" + "-"*70)
    print("1. ALL INTERNAL LINK SUGGESTIONS (Source, Target, Anchor)")
    print("-"*70)
    out_row = c.execute("SELECT output_json FROM content_outputs WHERE job_id = ?", (job_id,)).fetchone()
    if out_row and out_row[0]:
        data = json.loads(out_row[0])
        links = data.get("internal_links", [])
        print(f"Total Internal Link Suggestions: {len(links)}\n")
        tgt_counts = {}
        for idx, l in enumerate(links, 1):
            src = l.get("source_url")
            tgt = l.get("target_url")
            anchor = l.get("anchor_text")
            reason = l.get("reason")
            tgt_counts[tgt] = tgt_counts.get(tgt, 0) + 1
            print(f"[{idx:02d}] Anchor: \"{anchor}\"")
            print(f"     Source: {src}")
            print(f"     Target: {tgt}")
            print(f"     Reason: {reason}\n")

        print("Suggestions Per Target Page Count (Max 2 cap verification):")
        for tgt, count in tgt_counts.items():
            print(f"  • {tgt}: {count} link(s)")
    else:
        print("No content output found.")

    # 2. All Rewrites Before/After Including 'no change needed'
    print("\n" + "-"*70)
    print("2. ALL REWRITES BEFORE / AFTER (including 'no change needed')")
    print("-"*70)
    if out_row and out_row[0]:
        data = json.loads(out_row[0])
        rewrites = data.get("rewrites", [])
        print(f"Total Rewrites: {len(rewrites)}\n")
        for idx, rw in enumerate(rewrites, 1):
            url = rw.get("url") or rw.get("target_url")
            print(f"Rewrite [{idx:02d}] URL: {url}")
            print(f"  Current Title:   {rw.get('current_title')}")
            print(f"  Suggested Title: {rw.get('suggested_title')}")
            print(f"  Current Meta:    {rw.get('current_meta') or rw.get('current_meta_desc')}")
            print(f"  Suggested Meta:  {rw.get('suggested_meta') or rw.get('suggested_meta_desc')}")
            print(f"  Current H1:      {rw.get('current_h1')}")
            print(f"  Suggested H1:    {rw.get('suggested_h1')}\n")

    # 3. Strategist Task List with Page Totals
    print("\n" + "-"*70)
    print("3. STRATEGIST TASK LIST WITH PAGE TOTALS")
    print("-"*70)
    strat_row = c.execute("SELECT plan_json FROM strategy_plans WHERE job_id = ?", (job_id,)).fetchone()
    if strat_row and strat_row[0]:
        plan = json.loads(strat_row[0])
        tasks = plan.get("tasks", [])
        print(f"Total Strategy Tasks: {len(tasks)}\n")
        for idx, t in enumerate(tasks, 1):
            print(f"Task [{idx:02d}] {t.get('id')}: {t.get('title')}")
            print(f"  Category: {t.get('category')} | Week: {t.get('week')} | Priority Score: {t.get('priority_score')}")
            print(f"  Expected Outcome: {t.get('expected_outcome')}")
            print(f"  Done When: {t.get('done_when')}\n")
    else:
        print("No strategy plan found.")

    # 4. PSI Results Rows
    print("\n" + "-"*70)
    print("4. PSI RESULTS ROWS (job_id: " + job_id + ")")
    print("-"*70)
    psi_status_row = c.execute("SELECT psi_status FROM jobs WHERE id = ?", (job_id,)).fetchone()
    print(f"Overall PSI Status in Jobs table: {psi_status_row[0] if psi_status_row else 'None'}\n")
    psi_rows = c.execute("SELECT url, strategy, performance_score, lcp_ms, cls, error, fetched_at FROM psi_results WHERE job_id = ? ORDER BY url, strategy", (job_id,)).fetchall()
    print(f"Total PSI Rows Recorded: {len(psi_rows)}")
    for r in psi_rows:
        print(f"  • URL: {r[0]} | Strategy: {r[1]} | Score: {r[2]} | Error: {r[5]} | Fetched At: {r[6]}")

    conn.close()

if __name__ == "__main__":
    asyncio.run(main())
