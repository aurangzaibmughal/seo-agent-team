import pytest
from app.crawler.engine import AsyncCrawler
from app.core.db import DBManager

@pytest.mark.asyncio
async def test_crawler_max_pages_limit():
    job = DBManager.create_job("https://testsite.com", max_pages=10)
    job_id = job["id"]
    
    crawler = AsyncCrawler(job_id=job_id, target_url="https://testsite.com", max_pages=10)
    assert crawler.max_pages == 10

@pytest.mark.asyncio
async def test_crawler_respects_200_hard_cap():
    job = DBManager.create_job("https://testsite.com", max_pages=500)
    job_id = job["id"]
    
    crawler = AsyncCrawler(job_id=job_id, target_url="https://testsite.com", max_pages=500)
    # Rule capped at 200
    assert crawler.max_pages <= 200
