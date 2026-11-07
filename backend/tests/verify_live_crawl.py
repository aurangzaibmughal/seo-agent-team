import asyncio
from app.crawler.engine import AsyncCrawler
from app.core.db import DBManager

async def test_live():
    print("Testing live crawl against https://example.com ...")
    job = DBManager.create_job("https://example.com", max_pages=5)
    crawler = AsyncCrawler(job_id=job["id"], target_url="https://example.com", max_pages=5)
    await crawler.run()
    
    pages = DBManager.get_crawl_pages(job["id"])
    print(f"Crawl finished! Total pages stored: {len(pages)}")
    for p in pages:
        print(f"-> URL: {p['url']}")
        print(f"   Status Code: {p['status_code']}")
        print(f"   Title: {p['title']}")
        print(f"   Indexable: {p['indexable']}")
        print(f"   Word Count: {p['word_count']}")
        print(f"   Latency: {p['response_time_ms']} ms")
    assert len(pages) > 0, "No pages stored"
    print("ALL LIVE CRAWLER VALIDATIONS PASSED!")

if __name__ == "__main__":
    asyncio.run(test_live())
