import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from app.crawler.engine import AsyncCrawler

@pytest.mark.asyncio
async def test_crawler_respects_max_attempts_with_broken_sitemaps():
    """Verify that when sitemap contains hundreds of broken/404 URLs,
    crawler stops when max_attempts is reached, avoiding infinite crawling."""
    crawler = AsyncCrawler(job_id="test_job_limits", target_url="https://example.com", max_pages=10)
    
    # Simulate a discovered sitemap with 1,000 URLs
    fake_sitemap_urls = {f"https://example.com/spam-product-{i}" for i in range(1000)}
    crawler.sitemap_urls = fake_sitemap_urls
    crawler.sitemap_status = "found"
    
    # Mock client and responses: all sitemap URLs return 404
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = "Not Found"
    mock_resp.headers = {"content-type": "text/html"}
    
    with patch("app.crawler.engine.safe_fetch_url", new_callable=AsyncMock) as mock_fetch, \
         patch("app.crawler.engine.DBManager.update_job") as mock_db_up, \
         patch("app.crawler.engine.DBManager.save_crawl_page") as mock_db_save, \
         patch("app.crawler.engine.DBManager.get_crawl_pages", return_value=[]):
        
        mock_fetch.return_value = mock_resp
        
        # Run crawler - it should terminate quickly rather than crawling all 1,000 URLs
        await asyncio.wait_for(crawler.run(), timeout=5.0)
        
        # Total attempts must not exceed max_attempts
        assert crawler.total_attempts <= crawler.max_attempts
        assert crawler.max_attempts <= 200
