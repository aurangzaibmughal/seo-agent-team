import asyncio
import os
import sys
import json
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.db import DBManager, get_sqlite_conn
from app.crawler.engine import AsyncCrawler
from app.agents.orchestrator import run_full_pipeline

async def run_real_site_tasks():
    target_url = "https://webspire-agency.vercel.app/"
    print("=" * 80)
    print(f"REAL LIVE SITE EXECUTION ON: {target_url}")
    print("=" * 80)

    # -------------------------------------------------------------------------
    # PART 2: CRAWL REAL SITE 3 TIMES IN A ROW AT LIMIT 100
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("PART 2: TRIPLE CRAWL BENCHMARK (REAL SITE, LIMIT 100)")
    print("=" * 80)

    crawls = []
    for run_idx in range(1, 4):
        print(f"\n--- Initiating Real Crawl Run #{run_idx} at max_pages=100 ---")
        job = DBManager.create_job(target_url=target_url, max_pages=100, is_demo=False)
        jid = job["id"]
        
        crawler = AsyncCrawler(job_id=jid, target_url=target_url, max_pages=100)
        start_time = time.time()
        await crawler.run()
        duration = time.time() - start_time

        pages = DBManager.get_crawl_pages(jid, limit=500)
        html_200 = [p["url"] for p in pages if p.get("status_code") == 200 and "text/html" in (p.get("content_type") or "")]
        non_html_or_non_200 = [p for p in pages if not (p.get("status_code") == 200 and "text/html" in (p.get("content_type") or ""))]
        
        crawls.append({
            "run": run_idx,
            "job_id": jid,
            "duration": duration,
            "html_urls": sorted(html_200),
            "non_html_or_non_200": non_html_or_non_200,
            "skipped_urls": crawler.skipped_urls,
            "failed_fetches": crawler.failed_fetches,
            "pages_crawled_db": DBManager.get_job(jid).get("pages_crawled")
        })

        print(f"Run #{run_idx} Done: Job ID = {jid}")
        print(f"  • Duration: {duration:.2f}s")
        print(f"  • HTML Pages Crawled (Status 200 text/html): {len(html_200)}")
        print(f"  • Failed Fetches count: {len(crawler.failed_fetches)}")
        print(f"  • Skipped URLs count: {len(crawler.skipped_urls)}")

    print("\n--- Summary of 3 Consecutive Crawls ---")
    for c in crawls:
        print(f"Run {c['run']} ({c['job_id']}): {len(c['html_urls'])} HTML pages crawled in {c['duration']:.2f}s")

    # URL Diffs
    diff_1_2 = set(crawls[0]["html_urls"]) ^ set(crawls[1]["html_urls"])
    diff_2_3 = set(crawls[1]["html_urls"]) ^ set(crawls[2]["html_urls"])
    diff_1_3 = set(crawls[0]["html_urls"]) ^ set(crawls[2]["html_urls"])

    print("\n--- URL Differences Across Runs ---")
    print(f"Diff Run 1 vs Run 2: {len(diff_1_2)} differences -> {diff_1_2}")
    print(f"Diff Run 2 vs Run 3: {len(diff_2_3)} differences -> {diff_2_3}")
    print(f"Diff Run 1 vs Run 3: {len(diff_1_3)} differences -> {diff_1_3}")
    if len(diff_1_2) == 0 and len(diff_2_3) == 0:
        print(">>> 100% Deterministic match across all 3 real site crawls!")

    # Skipped or Non-HTML URLs and reasons (from Run 1)
    print("\n--- Skipped or Non-HTML URLs & Reason Log (Real Site) ---")
    run1 = crawls[0]
    for s in run1["skipped_urls"]:
        print(f"  • [SKIPPED] {s['url']} | Reason: {s['reason']}")

    print("\n--- Failed-Fetch Log (Real Site) ---")
    for f in run1["failed_fetches"]:
        print(f"  • [FAILED FETCH] {f['url']} | Reason: {f['reason']} | Timestamp: {f['timestamp']}")

    # -------------------------------------------------------------------------
    # PART 1: RUN A NEW NON-DEMO JOB & PRINT REAL OUTPUTS
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("PART 1: FULL MULTI-AGENT RUN ON REAL SITE (NON-DEMO)")
    print("=" * 80)

    job = DBManager.create_job(
        target_url=target_url,
        max_pages=100,
        is_demo=False,
        competitor_domains=[]
    )
    main_job_id = job["id"]
    print(f"NEW NON-DEMO REAL JOB ID: {main_job_id}")

    # Run full orchestrator pipeline on real site
    await run_full_pipeline(main_job_id, target_url, max_pages=100)

    # Fetch stored agent outputs
    content_record = DBManager.get_content_output(main_job_id)
    content_data = content_record.get("content", {}) if content_record else {}
    rewrites = content_data.get("rewrites", [])
    internal_links = content_data.get("internal_links", [])

    strat_record = DBManager.get_strategy_plan(main_job_id)
    strat_data = strat_record.get("plan", {}) if strat_record else {}
    tasks = strat_data.get("tasks", []) if isinstance(strat_data, dict) else (strat_data or [])

    print(f"\n--- Real Metadata Rewrites ({len(rewrites)} generated) ---")
    for idx, rw in enumerate(rewrites, 1):
        print(f"\nRewrite #{idx}: {rw.get('url')}")
        print(f"  Status          : {rw.get('status', 'needs human review')}")
        print(f"  Current Title   : {rw.get('current_title')} ({len(rw.get('current_title') or '')} chars)")
        print(f"  Suggested Title : {rw.get('suggested_title')} ({len(rw.get('suggested_title') or '')} chars)")
        print(f"  Current Meta    : {rw.get('current_meta')} ({len(rw.get('current_meta') or '')} chars)")
        print(f"  Suggested Meta  : {rw.get('suggested_meta')} ({len(rw.get('suggested_meta') or '')} chars)")

    print(f"\n--- Real Internal Link Suggestions & Anchors ({len(internal_links)} generated) ---")
    for idx, il in enumerate(internal_links, 1):
        print(f"Link #{idx}:")
        print(f"  From Target / Source: {il.get('source_url')} -> {il.get('target_url')}")
        print(f"  Anchor Text         : \"{il.get('anchor_text')}\"")
        print(f"  Reason              : {il.get('reason')}")

    print(f"\n--- Real Strategist Roadmap Tasks ({len(tasks)} generated) ---")
    for t in tasks:
        print(f"  • [{t.get('id')}] Week {t.get('week')} ({t.get('category')}): {t.get('title')}")
        print(f"      Outcome: {t.get('expected_outcome')}")
        print(f"      Done When: {t.get('done_when')}")

    print("\n" + "=" * 80)
    print("ALL REAL SITE TASKS COMPLETED SUCCESSFULLY")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(run_real_site_tasks())
