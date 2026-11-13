import re
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from collections import Counter
from bs4 import BeautifulSoup

DEFAULT_STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but",
    "by", "can", "cannot", "could", "did", "do", "does", "doing", "down", "during", "each", "few",
    "for", "from", "further", "had", "has", "have", "having", "he", "her", "here", "hers", "herself",
    "him", "himself", "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just",
    "me", "more", "most", "my", "myself", "no", "nor", "not", "now", "of", "off", "on", "once",
    "only", "or", "other", "our", "ours", "ourselves", "out", "over", "own", "same", "she",
    "should", "so", "some", "such", "than", "that", "the", "their", "theirs", "them", "themselves",
    "then", "there", "these", "they", "this", "those", "through", "to", "too", "under", "until",
    "up", "very", "was", "we", "were", "what", "when", "where", "which", "while", "who", "whom",
    "why", "with", "would", "you", "your", "yours", "yourself", "yourselves"
}

def extract_text_terms(text: str, stopwords: Optional[set] = None, top_n: int = 15) -> List[str]:
    """Deterministic term extraction with pluggable stopword handling."""
    sw = stopwords if stopwords is not None else DEFAULT_STOPWORDS
    tokens = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", text.lower())
    valid_tokens = [t for t in tokens if len(t) > 2 and t not in sw and not t.isdigit()]
    counts = Counter(valid_tokens)
    return [term for term, _ in counts.most_common(top_n)]

def normalize_url(url: str, base_url: str = "") -> Optional[str]:
    """Resolves relative URLs, removes fragments, standardizes scheme/netloc."""
    if not url:
        return None
    url = url.strip()
    if url.startswith(("javascript:", "mailto:", "tel:", "#", "whatsapp:", "data:")):
        return None
    
    if base_url:
        url = urljoin(base_url, url)
    
    parsed = urlparse(url)
    if not parsed.scheme or parsed.scheme not in ("http", "https"):
        return None
    
    path = parsed.path
    if path.endswith("/") and len(path) > 1:
        path = path.rstrip("/")
        
    netloc = parsed.netloc.lower()
    if netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif netloc.endswith(":443"):
        netloc = netloc[:-4]

    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme}://{netloc}{path or '/'}{query}"

def is_internal_url(url: str, base_domain: str) -> bool:
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        base = base_domain.lower()
        if netloc == base or netloc.endswith("." + base):
            return True
        return False
    except Exception:
        return False

def parse_html_page(
    html_content: str,
    current_url: str,
    status_code: int,
    headers: Optional[Dict[str, str]] = None,
    response_time_ms: int = 0
) -> Dict[str, Any]:
    """Deterministic parser extracting SEO technical elements."""
    headers = headers or {}
    
    # Check headers for X-Robots-Tag
    x_robots = (headers.get("x-robots-tag") or "").lower()
    has_header_noindex = "noindex" in x_robots

    soup = BeautifulSoup(html_content, "html.parser")

    # Title
    title_tag = soup.find("title")
    if title_tag:
        raw_t = title_tag.get_text(separator=" ", strip=True)
        raw_t = re.sub(r"<[^>]+>", " ", raw_t)
        title = re.sub(r"\s+", " ", raw_t).strip()
    else:
        title = None

    # Meta Description
    meta_desc_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    if not meta_desc_tag:
        meta_desc_tag = soup.find("meta", attrs={"property": re.compile(r"^og:description$", re.I)})
    meta_desc = meta_desc_tag.get("content", "").strip() if meta_desc_tag else None

    # Headings (preserve spacing across inline elements/spans)
    h1_tag = soup.find("h1")
    h1 = re.sub(r"\s+", " ", h1_tag.get_text(separator=" ", strip=True)).strip() if h1_tag else None

    headings: List[Dict[str, str]] = []
    for h in soup.find_all(["h1", "h2", "h3"]):
        h_text = re.sub(r"\s+", " ", h.get_text(separator=" ", strip=True)).strip()
        if h_text:
            headings.append({"level": h.name.lower(), "text": h_text})

    # Canonical
    canonical_tag = soup.find("link", attrs={"rel": re.compile(r"^canonical$", re.I)})
    raw_canonical = canonical_tag.get("href", "").strip() if canonical_tag else None
    canonical = normalize_url(raw_canonical, base_url=current_url) if raw_canonical else None

    # Robots meta tag
    robots_tag = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
    robots_content = (robots_tag.get("content", "") or "").lower() if robots_tag else ""
    is_meta_noindex = "noindex" in robots_content

    # Word count and term extraction
    for tag in soup(["script", "style", "noscript", "svg", "head"]):
        tag.decompose()
    
    text_content = soup.get_text(separator=" ", strip=True)
    body_text = text_content[:20000]
    words = [w for w in re.split(r"\s+", text_content) if len(w) > 1]
    word_count = len(words)
    text_terms = extract_text_terms(text_content, top_n=20)

    # Links Out with Anchor text
    outlinks_list: List[str] = []
    links_with_anchors: List[Dict[str, str]] = []
    
    for a in soup.find_all("a", href=True):
        href = a.get("href")
        anchor = re.sub(r"\s+", " ", a.get_text(separator=" ", strip=True)).strip()
        normalized = normalize_url(href, base_url=current_url)
        if normalized:
            if normalized not in outlinks_list:
                outlinks_list.append(normalized)
            links_with_anchors.append({
                "target_url": normalized,
                "anchor_text": anchor[:100] if anchor else ""
            })

    # Precise indexability reasoning
    indexable = True
    indexability_status = "indexable"

    if status_code != 200:
        indexable = False
        indexability_status = "http_error"
    elif has_header_noindex:
        indexable = False
        indexability_status = "noindex_header"
    elif is_meta_noindex:
        indexable = False
        indexability_status = "noindex_meta"
    elif canonical and normalize_url(canonical) != normalize_url(current_url):
        indexable = False
        indexability_status = "canonical_to_other"

    return {
        "url": current_url,
        "status_code": status_code,
        "title": title,
        "meta_desc": meta_desc,
        "h1": h1,
        "canonical": canonical,
        "word_count": word_count,
        "links_out": len(outlinks_list),
        "indexable": indexable,
        "indexability_status": indexability_status,
        "outlinks_list": outlinks_list,
        "links_with_anchors": links_with_anchors,
        "headings": headings,
        "text_terms": text_terms,
        "body_text": body_text,
        "response_time_ms": response_time_ms,
    }

def extract_page_data(html: str, current_url: str, status_code: int = 200, **kwargs) -> Dict[str, Any]:
    return parse_html_page(html, current_url, status_code, **kwargs)

