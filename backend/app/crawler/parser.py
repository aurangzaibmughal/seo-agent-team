import re
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse
from collections import Counter
from bs4 import BeautifulSoup

from app.crawler.url_utils import (
    normalize_url,
    urls_compare_equal
)

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
    h1_tags = soup.find_all("h1")
    all_h1s = [re.sub(r"\s+", " ", h.get_text(separator=" ", strip=True)).strip() for h in h1_tags if h.get_text(strip=True)]
    h1 = all_h1s[0] if all_h1s else None

    headings: List[Dict[str, str]] = []
    for h in soup.find_all(["h1", "h2", "h3"]):
        h_text = re.sub(r"\s+", " ", h.get_text(separator=" ", strip=True)).strip()
        if h_text:
            headings.append({"level": h.name.lower(), "text": h_text})

    # Canonical (Audit fix: detect multiple canonicals and record raw attribute)
    canonical_tags = soup.find_all("link", attrs={"rel": re.compile(r"^canonical$", re.I)})
    multiple_canonicals = len(canonical_tags) > 1
    raw_canonical = canonical_tags[0].get("href", "").strip() if canonical_tags else None
    canonical = normalize_url(raw_canonical, base_url=current_url, trailing_slash=None) if raw_canonical else None

    # Robots meta tag
    robots_tag = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
    robots_content = (robots_tag.get("content", "") or "").lower() if robots_tag else ""
    is_meta_noindex = "noindex" in robots_content

    # Structural elements before script/style tags are decomposed
    has_schema = bool(
        soup.find("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}) or
        soup.find(attrs={"itemscope": True})
    )

    has_og = bool(
        soup.find("meta", attrs={"property": re.compile(r"^og:(title|description|image)", re.I)}) or
        soup.find("meta", attrs={"name": re.compile(r"^og:(title|description|image)", re.I)})
    )

    has_twitter_card = bool(
        soup.find("meta", attrs={"name": re.compile(r"^twitter:(card|title|description)", re.I)})
    )

    bc_container = (
        soup.find("nav", attrs={"aria-label": re.compile(r"breadcrumb", re.I)}) or
        soup.find(attrs={"class": re.compile(r"breadcrumb", re.I)}) or
        soup.find(attrs={"id": re.compile(r"breadcrumb", re.I)})
    )
    has_breadcrumbs = bool(
        bc_container or
        "breadcrumblist" in (soup.get_text() + str(soup.find_all("script"))).lower()
    )
    breadcrumb_trail: List[str] = []
    if bc_container:
        for it in bc_container.find_all(["a", "span", "li"]):
            t = it.get_text(strip=True)
            if t and t not in (">", "/", "\\", "»", "›", "-") and t not in breadcrumb_trail:
                breadcrumb_trail.append(t)

    has_privacy_link = False
    has_terms_link = False
    for a_tag in soup.find_all("a"):
        a_txt = a_tag.get_text(strip=True).lower()
        if "privacy" in a_txt or "privacy-policy" in (a_tag.get("href") or "").lower():
            has_privacy_link = True
        if "terms" in a_txt or "terms-and-conditions" in (a_tag.get("href") or "").lower():
            has_terms_link = True

    images = soup.find_all("img")
    images_missing_alt = [
        img.get("src", "") for img in images
        if not img.get("alt") or not img.get("alt", "").strip()
    ]

    images_missing_dimensions = [
        img.get("src", "") for img in images
        if not img.get("width") or not img.get("height")
    ]

    images_non_modern = [
        img.get("src", "") for img in images
        if any(img.get("src", "").lower().split("?")[0].endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".bmp"])
    ]

    videos = soup.find_all("video")
    unmuted_autoplay_videos = [
        v.get("src") or "video_element" for v in videos
        if v.has_attr("autoplay") and not v.has_attr("muted")
    ]

    # Detect autoplay or heavy video above the fold (in hero/header/banner or near top)
    videos_above_fold = []
    for v in videos:
        parent_tags = [p.name.lower() for p in v.parents]
        parent_classes = " ".join([str(c) for p in v.parents for c in p.get("class", [])]).lower()
        parent_ids = " ".join([str(p.get("id", "")) for p in v.parents]).lower()
        is_above_fold = (
            "header" in parent_tags
            or any(k in parent_classes or k in parent_ids for k in ["hero", "banner", "header", "top", "slider"])
            or (soup.body and v in list(soup.body.children)[:5])
        )
        if is_above_fold and (v.has_attr("autoplay") or not v.get("poster")):
            videos_above_fold.append({
                "src": v.get("src") or (v.find("source").get("src") if v.find("source") else "inline_video"),
                "autoplay": v.has_attr("autoplay"),
                "has_poster": bool(v.get("poster"))
            })

    empty_legal_links = []
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        # Exclude Elementor actions and popup triggers
        if href.startswith("#elementor-action") or "elementor-action:" in href or href.startswith("#popup") or href.startswith("#modal"):
            continue
        anchor_text = a.get_text(strip=True).lower()
        if href in ("#", "", "javascript:void(0)", "javascript:;"):
            if any(k in anchor_text for k in ["privacy", "terms", "condition", "policy", "disclaimer", "refund"]):
                empty_legal_links.append({"text": a.get_text(strip=True), "href": href})

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

    # Precise indexability reasoning using robust URL equality
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
    elif canonical and not urls_compare_equal(canonical, current_url):
        indexable = False
        indexability_status = "canonical_to_other"

    return {
        "url": current_url,
        "status_code": status_code,
        "title": title,
        "meta_desc": meta_desc,
        "h1": h1,
        "h1_list": all_h1s,
        "canonical": canonical,
        "raw_canonical": raw_canonical,
        "multiple_canonicals": multiple_canonicals,
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
        "has_schema": has_schema,
        "has_og": has_og,
        "has_twitter_card": has_twitter_card,
        "has_breadcrumbs": has_breadcrumbs,
        "breadcrumb_trail": breadcrumb_trail,
        "has_privacy_link": has_privacy_link,
        "has_terms_link": has_terms_link,
        "images_missing_alt": images_missing_alt,
        "images_missing_dimensions": images_missing_dimensions,
        "images_non_modern": images_non_modern,
        "unmuted_autoplay_videos": unmuted_autoplay_videos,
        "videos_above_fold": videos_above_fold,
        "empty_legal_links": empty_legal_links,
    }

def extract_page_data(html: str, current_url: str, status_code: int = 200, **kwargs) -> Dict[str, Any]:
    return parse_html_page(html, current_url, status_code, **kwargs)

