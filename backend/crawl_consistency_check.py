import asyncio
import json
from app.crawler.engine import AsyncCrawler

async def run_crawl(crawl_id: str, max_pages: int = 30):
    crawler = AsyncCrawler(job_id=crawl_id, target_url="https://demo-agency.vercel.app/", max_pages=max_pages)
    await crawler.run()
    # Collect all visited URLs and failed fetches
    return list(crawler.visited), crawler.failed_fetches

async def main():
    print("=== STARTING CRAWL 1 ===")
    urls_1, failed_1 = await run_crawl("crawl-test-1", max_pages=30)
    print(f"Crawl 1 completed: {len(urls_1)} pages crawled. Failed fetches: {len(failed_1)}")

    print("\n=== STARTING CRAWL 2 ===")
    urls_2, failed_2 = await run_crawl("crawl-test-2", max_pages=30)
    print(f"Crawl 2 completed: {len(urls_2)} pages crawled. Failed fetches: {len(failed_2)}")

    set1 = set(urls_1)
    set2 = set(urls_2)

    diff_1_minus_2 = set1 - set2
    diff_2_minus_1 = set2 - set1
    intersection = set1 & set2

    print("\n=== CRAWL CONSISTENCY REPORT ===")
    print(f"Crawl 1 Total Pages: {len(set1)}")
    print(f"Crawl 2 Total Pages: {len(set2)}")
    print(f"Common Pages: {len(intersection)}")
    print(f"URLs in Crawl 1 but NOT in Crawl 2 ({len(diff_1_minus_2)}):")
    for u in sorted(list(diff_1_minus_2)):
        print(f"  - {u}")
    print(f"URLs in Crawl 2 but NOT in Crawl 1 ({len(diff_2_minus_1)}):")
    for u in sorted(list(diff_2_minus_1)):
        print(f"  - {u}")

    print("\n=== FAILED-FETCH LOGS ===")
    print(f"Crawl 1 Failed Fetches ({len(failed_1)}):")
    if failed_1:
        for f in failed_1:
            print(f"  • {f['url']} -> {f['reason']} at {f['timestamp']}")
    else:
        print("  None (0 failed fetches, all URLs succeeded or clean)")

    print(f"Crawl 2 Failed Fetches ({len(failed_2)}):")
    if failed_2:
        for f in failed_2:
            print(f"  • {f['url']} -> {f['reason']} at {f['timestamp']}")
    else:
        print("  None (0 failed fetches, all URLs succeeded or clean)")

    if len(diff_1_minus_2) == 0 and len(diff_2_minus_1) == 0:
        print("\nRESULT: 100% CONSISTENT (0 differences in URL sets).")
    else:
        print(f"\nRESULT: Minor diff of {abs(len(set1) - len(set2))} page(s).")

if __name__ == "__main__":
    asyncio.run(main())
