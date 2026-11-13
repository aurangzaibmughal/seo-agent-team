import re
import json
import asyncio
import time
from typing import List, Dict, Any, Set
from urllib.parse import urlparse, urljoin
from urllib.robotparser import RobotFileParser
import httpx
from bs4 import BeautifulSoup
from app.core.db import DBManager
from app.crawler.parser import normalize_url, is_internal_url, parse_html_page
from app.core.security import validate_safe_url, safe_fetch_url, SSRFSecurityError

COMPETITOR_USER_AGENT = "Mozilla/5.0 (compatible; SEOAgentTeamCompetitorBot/1.0; +https://seo-agent-team.local)"

def extract_schema_types(soup: BeautifulSoup) -> List[str]:
    """Extracts Schema.org types from JSON-LD scripts and Microdata."""
    types = set()
    # 1. JSON-LD
    for script in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, dict):
                st = data.get("@type")
                if st:
                    if isinstance(st, list):
                        types.update(st)
                    else:
                        types.add(st)
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type"):
                        types.add(item["@type"])
        except Exception:
            pass

    # 2. Microdata
    for item in soup.find_all(attrs={"itemtype": True}):
        it = item.get("itemtype")
        if it:
            clean = it.split("/")[-1]
            types.add(clean)

    return sorted(list(types))

class CompetitorCrawler:
    """Light, polite competitor crawler.
    - Max 30 pages per domain
    - Respects robots.txt
    - Strict rate limit (at least 1.0s delay)
    - Labels: 'on-page comparison only — no traffic or backlink data'
    """
    def __init__(self, job_id: str, competitor_domain: str, max_pages: int = 30):
        self.job_id = job_id
        domain = competitor_domain.strip().lower()
        if not domain.startswith(("http://", "https://")):
            domain = f"https://{domain}"
        self.start_url = domain
        validate_safe_url(self.start_url)
        self.parsed_domain = urlparse(domain).netloc
        self.max_pages = min(max_pages, 30)
        self.visited: Set[str] = set()
        self.to_visit: List[str] = [self.start_url]
        self.rp = RobotFileParser()
        self.sitemap_size = 0

    async def run(self) -> int:
        headers = {
            "User-Agent": COMPETITOR_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }

        async with httpx.AsyncClient(headers=headers, timeout=12.0, follow_redirects=True) as client:
            # 1. Check robots.txt
            robots_url = f"https://{self.parsed_domain}/robots.txt"
            try:
                r_resp = await safe_fetch_url(client, robots_url, timeout=10.0)
                if r_resp.status_code == 200:
                    self.rp.parse(r_resp.text.splitlines())
                else:
                    self.rp.allow_all = True
            except Exception:
                self.rp.allow_all = True

            # 2. Check sitemap size
            sitemap_url = f"https://{self.parsed_domain}/sitemap.xml"
            try:
                s_resp = await safe_fetch_url(client, sitemap_url, timeout=10.0)
                if s_resp.status_code == 200 and "xml" in s_resp.headers.get("content-type", ""):
                    urls_in_sm = re.findall(r"<loc>(.*?)</loc>", s_resp.text)
                    self.sitemap_size = len(urls_in_sm)
            except Exception:
                self.sitemap_size = 0

            # 3. Light crawl with rate-limiting
            stored_count = 0
            while self.to_visit and stored_count < self.max_pages:
                curr_url = self.to_visit.pop(0)
                norm_curr = normalize_url(curr_url)
                if not norm_curr or norm_curr in self.visited:
                    continue
                self.visited.add(norm_curr)

                # robots.txt check
                if not self.rp.can_fetch(COMPETITOR_USER_AGENT, norm_curr):
                    continue

                try:
                    resp = await safe_fetch_url(client, norm_curr, timeout=12.0)
                    if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
                        soup = BeautifulSoup(resp.text, "html.parser")
                        parsed = parse_html_page(resp.text, norm_curr, resp.status_code)
                        schema_types = extract_schema_types(soup)

                        DBManager.save_competitor_page(self.job_id, {
                            "competitor_domain": self.parsed_domain,
                            "url": norm_curr,
                            "title": parsed.get("title"),
                            "headings": parsed.get("headings", []),
                            "word_count": parsed.get("word_count", 0),
                            "schema_types": schema_types,
                            "sitemap_size": self.sitemap_size
                        })
                        stored_count += 1

                        # Discover internal links
                        for link in parsed.get("outlinks_list", []):
                            if is_internal_url(link, self.parsed_domain) and link not in self.visited:
                                if len(self.to_visit) < 60:
                                    self.to_visit.append(link)

                    # Strict polite rate limit (at least 1.0 second delay)
                    await asyncio.sleep(1.0)
                except Exception as e:
                    await asyncio.sleep(1.0)
                    continue

            return stored_count
