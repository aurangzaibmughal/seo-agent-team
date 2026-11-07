import asyncio
import json
import time
import xml.etree.ElementTree as ET
from typing import Set, List, Dict, Optional
from urllib.parse import urlparse
import httpx

from app.core.config import settings
from app.core.db import DBManager
from app.crawler.parser import normalize_url, is_internal_url, parse_html_page
from app.crawler.detector import PlatformDetector

NON_HTML_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".pdf", ".zip", ".tar", ".gz", ".rar", ".7z",
    ".css", ".js", ".json", ".xml", ".txt",
    ".mp3", ".mp4", ".avi", ".mov", ".wmv",
    ".woff", ".woff2", ".ttf", ".eot", ".otf"
)

def is_potential_html_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return not any(path.endswith(ext) for ext in NON_HTML_EXTENSIONS)

FAILED_FETCH_RETRY_DELAY = 1.5  # seconds

async def fetch_sitemap_urls(client: httpx.AsyncClient, base_url: str) -> Set[str]:
    """Attempts to find and parse sitemap.xml from robots.txt or /sitemap.xml."""
    sitemap_urls: Set[str] = set()
    sitemap_locations = [
        normalize_url("/sitemap.xml", base_url=base_url),
        normalize_url("/sitemap_index.xml", base_url=base_url),
    ]

    # Try robots.txt first
    try:
        robots_url = normalize_url("/robots.txt", base_url=base_url)
        if robots_url:
            resp = await client.get(robots_url, timeout=8.0)
            if resp.status_code == 200:
                for line in resp.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        loc = line.split(":", 1)[1].strip()
                        norm_loc = normalize_url(loc, base_url=base_url)
                        if norm_loc and norm_loc not in sitemap_locations:
                            sitemap_locations.insert(0, norm_loc)
    except Exception:
        pass

    for sm_url in sitemap_locations:
        if not sm_url:
            continue
        try:
            resp = await client.get(sm_url, timeout=10.0)
            if resp.status_code == 200 and ("xml" in resp.headers.get("content-type", "") or resp.text.startswith("<?xml") or "<urlset" in resp.text):
                root = ET.fromstring(resp.content)
                # Handle namespaces
                for elem in root.iter():
                    if elem.tag.endswith("loc") and elem.text:
                        norm = normalize_url(elem.text.strip(), base_url=base_url)
                        if norm:
                            sitemap_urls.add(norm)
                if sitemap_urls:
                    break
        except Exception:
            continue

    return sitemap_urls

class AsyncCrawler:
    def __init__(self, job_id: str, target_url: str, max_pages: int = 50):
        self.job_id = job_id
        self.start_url = normalize_url(target_url) or target_url
        self.target_domain = urlparse(self.start_url).netloc
        self.max_pages = min(max_pages, settings.MAX_CRAWL_PAGES)
        
        self.visited: Set[str] = set()
        self.to_visit: asyncio.Queue[str] = asyncio.Queue()
        self.semaphore = asyncio.Semaphore(settings.CRAWL_CONCURRENCY)
        self.crawled_count = 0
        self.active_workers = 0
        self.discovered_links: List[Dict[str, str]] = []
        self.sitemap_urls: Set[str] = set()
        self.failed_fetches: List[Dict] = []  # {url, reason, timestamp}
        self.skipped_urls: List[Dict[str, str]] = []  # {url, reason}
        self.detector = PlatformDetector()

    async def run(self):
        """Main crawl execution loop."""
        DBManager.update_job(self.job_id, {
            "status": "crawling",
            "current_step": "crawling"
        })

        await self.to_visit.put(self.start_url)
        self.visited.add(self.start_url)

        headers = {
            "User-Agent": settings.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        async with httpx.AsyncClient(headers=headers, timeout=settings.CRAWL_TIMEOUT_SECONDS, follow_redirects=True) as client:
            # 1. Fetch sitemap URLs concurrently
            try:
                self.sitemap_urls = await fetch_sitemap_urls(client, self.start_url)
            except Exception:
                self.sitemap_urls = set()

            # 2. Run crawl workers
            workers = [asyncio.create_task(self._worker(client)) for _ in range(settings.CRAWL_CONCURRENCY)]
            
            while self.crawled_count < self.max_pages:
                if self.to_visit.empty() and self.active_workers == 0:
                    break
                await asyncio.sleep(0.1)

            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

        # 3. Save all discovered links ("Found on" references)
        if self.discovered_links:
            DBManager.save_crawl_links(self.discovered_links)
            DBManager.update_inlinks_counts(self.job_id)

        # 4. Compare sitemap with crawled pages
        crawled_urls = self.visited
        in_sitemap_not_crawled = len(self.sitemap_urls - crawled_urls)
        crawled_not_in_sitemap = len(crawled_urls - self.sitemap_urls) if self.sitemap_urls else 0

        platform, platform_conf = self.detector.detect()

        job_update: Dict = {
            "pages_crawled": self.crawled_count,
            "sitemap_found": 1 if len(self.sitemap_urls) > 0 else 0,
            "in_sitemap_not_crawled": in_sitemap_not_crawled,
            "crawled_not_in_sitemap": crawled_not_in_sitemap,
            "failed_fetches_json": json.dumps(self.failed_fetches),
            "platform": platform,
            "platform_confidence": platform_conf,
            "detected_platform": platform,
            "detected_platform_confidence": platform_conf,
        }
        # Mark crawl incomplete if any URL permanently failed
        if self.failed_fetches:
            job_update["crawl_incomplete"] = 1
            print(f"[Crawler] Crawl marked INCOMPLETE — {len(self.failed_fetches)} URL(s) failed after retry:")
            for ff in self.failed_fetches:
                print(f"  • {ff['url']} [{ff['reason']}] @ {ff['timestamp']}")
        else:
            job_update["crawl_incomplete"] = 0

        DBManager.update_job(self.job_id, job_update)

    async def _worker(self, client: httpx.AsyncClient):
        while self.crawled_count < self.max_pages:
            try:
                url = await asyncio.wait_for(self.to_visit.get(), timeout=1.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                if self.to_visit.empty() and self.active_workers == 0:
                    break
                continue

            self.active_workers += 1
            try:
                async with self.semaphore:
                    await self._crawl_page(client, url)
            finally:
                self.active_workers -= 1
                self.to_visit.task_done()

    async def _fetch_once(self, client: httpx.AsyncClient, url: str):
        """Single fetch attempt. Returns (status_code, html, content_type, redirect_url, headers_dict, elapsed_ms, error_reason)."""
        start_time = time.time()
        status_code = 0
        html = ""
        content_type = ""
        redirect_url = None
        headers_dict = {}
        error_reason = None

        try:
            resp = await client.get(url)
            elapsed_ms = int((time.time() - start_time) * 1000)
            status_code = resp.status_code
            content_type = resp.headers.get("content-type", "")
            headers_dict = dict(resp.headers)

            final_url = str(resp.url)
            if normalize_url(final_url) != normalize_url(url):
                redirect_url = final_url

            if "text/html" in content_type:
                html = resp.text

            if status_code >= 400:
                error_reason = f"HTTP {status_code}"

        except httpx.TimeoutException:
            elapsed_ms = int((time.time() - start_time) * 1000)
            status_code = 0
            error_reason = "timeout"
        except httpx.HTTPStatusError as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            status_code = e.response.status_code
            error_reason = f"HTTP {status_code}"
        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            status_code = 500
            error_reason = f"error: {type(e).__name__}"

        return status_code, html, content_type, redirect_url, headers_dict, elapsed_ms, error_reason

    async def _crawl_page(self, client: httpx.AsyncClient, url: str):
        if self.crawled_count >= self.max_pages:
            return

        status_code, html, content_type, redirect_url, headers_dict, elapsed_ms, error_reason = \
            await self._fetch_once(client, url)

        # Retry once after a short delay if the fetch failed (4xx/5xx/timeout)
        if error_reason is not None:
            await asyncio.sleep(FAILED_FETCH_RETRY_DELAY)
            status_code, html, content_type, redirect_url, headers_dict, elapsed_ms, error_reason = \
                await self._fetch_once(client, url)
            if error_reason is not None:
                # Still failing after retry — log it
                self.failed_fetches.append({
                    "url": url,
                    "reason": error_reason,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                })
                print(f"[Crawler] Failed fetch (after retry): {url} — {error_reason}")

        self.detector.analyze_page(url, status_code, headers_dict, html)

        parsed_data = parse_html_page(
            html_content=html,
            current_url=url,
            status_code=status_code,
            headers=headers_dict,
            response_time_ms=elapsed_ms
        )
        parsed_data["job_id"] = self.job_id
        parsed_data["content_type"] = content_type
        parsed_data["redirect_url"] = redirect_url

        # Store internal link edges for "Found on (N)"
        for link_obj in parsed_data.get("links_with_anchors", []):
            target = link_obj["target_url"]
            if is_internal_url(target, self.target_domain):
                self.discovered_links.append({
                    "job_id": self.job_id,
                    "source_url": url,
                    "target_url": target,
                    "anchor_text": link_obj.get("anchor_text", "")
                })

        is_crawlable_html = (
            parsed_data["status_code"] == 200
            and "text/html" in content_type
            and is_internal_url(url, self.target_domain)
        )

        DBManager.save_crawl_page(parsed_data)
        if is_crawlable_html:
            self.crawled_count += 1
            DBManager.update_job(self.job_id, {
                "pages_crawled": self.crawled_count
            })
        else:
            reason = f"HTTP {status_code}" if status_code != 200 else f"Non-HTML content-type: {content_type}"
            if not any(s["url"] == url for s in self.skipped_urls):
                self.skipped_urls.append({"url": url, "reason": reason})

        # Queue discovered internal links
        if is_crawlable_html:
            for link in parsed_data["outlinks_list"]:
                if self.crawled_count >= self.max_pages:
                    break
                if not is_internal_url(link, self.target_domain):
                    if not any(s["url"] == link for s in self.skipped_urls):
                        self.skipped_urls.append({"url": link, "reason": "external domain"})
                    continue
                if not is_potential_html_url(link):
                    ext = urlparse(link).path.split(".")[-1].lower() if "." in urlparse(link).path else "asset"
                    if not any(s["url"] == link for s in self.skipped_urls):
                        self.skipped_urls.append({"url": link, "reason": f"non-HTML asset extension (.{ext})"})
                    continue
                if link not in self.visited:
                    self.visited.add(link)
                    await self.to_visit.put(link)
