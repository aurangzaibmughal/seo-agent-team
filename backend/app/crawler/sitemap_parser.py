import gzip
import xml.etree.ElementTree as ET
from typing import Set, List, Dict, Tuple, Optional
from pydantic import BaseModel
import httpx

from app.core.security import safe_fetch_url
from app.crawler.url_utils import normalize_url

COMMON_SITEMAP_PATHS = [
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/wp-sitemap.xml",
    "/sitemap/sitemap.xml",
    "/sitemap-index.xml"
]

class SitemapDiscoveryResult(BaseModel):
    status: str = "missing"  # "found", "missing", "unreadable"
    sitemap_urls: Set[str] = set()
    sitemaps_discovered: List[str] = []
    status_codes: Dict[str, int] = {}
    error_reason: Optional[str] = None
    robots_found: bool = False
    robots_has_sitemap: bool = False

def parse_sitemap_xml(content: bytes, base_url: str, is_gz: bool = False) -> Tuple[List[str], List[str]]:
    """Parses XML sitemap bytes into (page_urls, child_sitemap_urls).
    Supports standard namespaces, sitemapindex, and gzip decompress.
    """
    if not content:
        return [], []

    raw_bytes = content
    if is_gz:
        try:
            raw_bytes = gzip.decompress(content)
        except Exception:
            return [], []

    try:
        root = ET.fromstring(raw_bytes)
    except Exception:
        return [], []

    page_urls: List[str] = []
    child_sitemaps: List[str] = []

    # Strip namespace for clean tag inspection
    tag_clean = root.tag.split("}")[-1].lower() if "}" in root.tag else root.tag.lower()

    if tag_clean == "sitemapindex":
        for sitemap_node in root.findall(".//{*}sitemap") or root.findall(".//sitemap"):
            loc_node = sitemap_node.find("{*}loc") if sitemap_node.find("{*}loc") is not None else sitemap_node.find("loc")
            if loc_node is not None and loc_node.text:
                norm = normalize_url(loc_node.text.strip(), base_url=base_url, trailing_slash=None)
                if norm:
                    child_sitemaps.append(norm)
    else:
        # Standard <urlset> or general element iteration
        for url_node in root.findall(".//{*}url") or root.findall(".//url"):
            loc_node = url_node.find("{*}loc") if url_node.find("{*}loc") is not None else url_node.find("loc")
            if loc_node is not None and loc_node.text:
                norm = normalize_url(loc_node.text.strip(), base_url=base_url, trailing_slash=None)
                if norm:
                    page_urls.append(norm)

        # Fallback if no <url> tags found, scan all <loc>
        if not page_urls and not child_sitemaps:
            for elem in root.iter():
                clean_elem_tag = elem.tag.split("}")[-1].lower() if "}" in elem.tag else elem.tag.lower()
                if clean_elem_tag == "loc" and elem.text:
                    norm = normalize_url(elem.text.strip(), base_url=base_url, trailing_slash=None)
                    if norm:
                        page_urls.append(norm)

    return page_urls, child_sitemaps

async def discover_and_parse_sitemaps(
    client: httpx.AsyncClient,
    base_url: str,
    max_depth: int = 3,
    max_urls: int = 50000
) -> SitemapDiscoveryResult:
    """Discovers sitemaps via robots.txt and standard locations, recursing into sitemap index files."""
    result = SitemapDiscoveryResult()
    candidate_locations: List[str] = []
    robots_has_sitemap = False

    # 1. Try robots.txt first
    try:
        robots_url = normalize_url("/robots.txt", base_url=base_url)
        if robots_url:
            resp = await safe_fetch_url(client, robots_url, timeout=8.0)
            result.status_codes[robots_url] = resp.status_code
            if resp.status_code == 200:
                result.robots_found = True
                for line in resp.text.splitlines():
                    clean_line = line.strip()
                    if clean_line.lower().startswith("sitemap:"):
                        loc = clean_line.split(":", 1)[1].strip()
                        norm_loc = normalize_url(loc, base_url=base_url)
                        if norm_loc and norm_loc not in candidate_locations:
                            candidate_locations.append(norm_loc)
                            robots_has_sitemap = True
    except Exception:
        pass

    result.robots_has_sitemap = robots_has_sitemap

    # 2. Add standard paths
    for p in COMMON_SITEMAP_PATHS:
        loc = normalize_url(p, base_url=base_url)
        if loc and loc not in candidate_locations:
            candidate_locations.append(loc)

    visited_sitemaps: Set[str] = set()
    sitemaps_to_crawl = list(candidate_locations)
    depth = 0
    parse_errors = 0

    while sitemaps_to_crawl and depth < max_depth and len(result.sitemap_urls) < max_urls:
        depth += 1
        current_batch = list(sitemaps_to_crawl)
        sitemaps_to_crawl.clear()

        for sm_url in current_batch:
            if sm_url in visited_sitemaps:
                continue
            visited_sitemaps.add(sm_url)

            try:
                resp = await safe_fetch_url(client, sm_url, timeout=10.0)
                result.status_codes[sm_url] = resp.status_code
                if resp.status_code == 200:
                    is_gz = sm_url.endswith(".gz") or "gzip" in resp.headers.get("content-type", "")
                    content_text = resp.text if not is_gz else ""
                    if is_gz or "xml" in resp.headers.get("content-type", "") or content_text.startswith("<?xml") or "<urlset" in content_text or "<sitemapindex" in content_text:
                        pages, children = parse_sitemap_xml(resp.content, base_url=base_url, is_gz=is_gz)
                        if pages or children:
                            result.sitemaps_discovered.append(sm_url)
                            result.sitemap_urls.update(pages)
                            for child in children:
                                if child not in visited_sitemaps and child not in sitemaps_to_crawl:
                                    sitemaps_to_crawl.append(child)
                        else:
                            parse_errors += 1
            except Exception:
                parse_errors += 1

    if result.sitemap_urls or result.sitemaps_discovered:
        result.status = "found"
    elif parse_errors > 0 and any(code == 200 for code in result.status_codes.values()):
        result.status = "unreadable"
        result.error_reason = "Sitemap returned HTTP 200 but XML content was invalid or unparseable"
    else:
        result.status = "missing"
        result.error_reason = "No valid sitemap found in robots.txt or standard paths (/sitemap.xml, /wp-sitemap.xml)"

    return result
