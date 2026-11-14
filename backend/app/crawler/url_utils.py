from typing import Optional, List
from urllib.parse import urlparse, urljoin, parse_qsl, urlencode, unquote

TRACKING_PARAM_PREFIXES = ("utm_", "mc_")
TRACKING_PARAMS = {
    "gclid", "fbclid", "msclkid", "dclid", "yclid", "_ga", "_gl",
    "ref", "source", "affiliate", "campaign"
}

NON_HTML_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
    ".pdf", ".zip", ".tar", ".gz", ".rar", ".7z",
    ".css", ".js", ".json", ".xml", ".txt",
    ".mp3", ".mp4", ".avi", ".mov", ".wmv",
    ".woff", ".woff2", ".ttf", ".eot", ".otf"
)

def filter_tracking_params(query_str: str) -> str:
    """Removes marketing/tracking query parameters (utm_*, gclid, fbclid, etc.) while preserving functional params."""
    if not query_str:
        return ""
    pairs = parse_qsl(query_str, keep_blank_values=True)
    clean_pairs = []
    for k, v in pairs:
        k_lower = k.lower()
        if any(k_lower.startswith(pfx) for pfx in TRACKING_PARAM_PREFIXES):
            continue
        if k_lower in TRACKING_PARAMS:
            continue
        clean_pairs.append((k, v))
    if not clean_pairs:
        return ""
    # Sort pairs for deterministic canonical output
    clean_pairs.sort(key=lambda x: (x[0], x[1]))
    return urlencode(clean_pairs)

def normalize_url(
    url: str,
    base_url: str = "",
    trailing_slash: Optional[bool] = False,
    strip_tracking: bool = True
) -> Optional[str]:
    """Single robust URL normalization utility used across crawler, diffs, rules and reporters.
    - Resolves relative URLs
    - Drops fragments (#)
    - Lowercases scheme and netloc
    - Strips default HTTP (:80) and HTTPS (:443) ports
    - Strips marketing tracking query parameters
    - Normalizes trailing slashes according to site convention or preserves original
    """
    if not url:
        return None
    url = url.strip()
    if url.startswith(("javascript:", "mailto:", "tel:", "#", "whatsapp:", "data:")):
        return None

    if base_url:
        url = urljoin(base_url, url)

    try:
        parsed = urlparse(url)
    except Exception:
        return None

    scheme = parsed.scheme.lower()
    if not scheme or scheme not in ("http", "https"):
        return None

    netloc = parsed.netloc.lower()
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    elif netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]

    path = parsed.path or "/"

    # Normalize trailing slash if requested
    has_extension = any(path.lower().endswith(ext) for ext in NON_HTML_EXTENSIONS)
    if not has_extension and path != "/":
        if trailing_slash is True and not path.endswith("/"):
            path = path + "/"
        elif trailing_slash is False and path.endswith("/"):
            path = path.rstrip("/")

    # Query string handling
    query = parsed.query
    if strip_tracking and query:
        clean_query = filter_tracking_params(query)
        query_part = f"?{clean_query}" if clean_query else ""
    else:
        query_part = f"?{query}" if query else ""

    return f"{scheme}://{netloc}{path}{query_part}"

def canonical_url_key(url: str) -> str:
    """Produces a canonical comparison key for URL diffs, sitemaps, and deduplication.
    Treats www and non-www as equivalent, ignores trailing slashes, strips tracking params,
    and normalizes protocol and percent-encodings.
    """
    if not url:
        return ""
    norm = normalize_url(url, strip_tracking=True)
    if not norm:
        return ""
    parsed = urlparse(norm)
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    path = unquote(parsed.path.lower())
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    if not path:
        path = "/"

    query = filter_tracking_params(parsed.query)
    q_part = f"?{query}" if query else ""
    return f"{netloc}{path}{q_part}"

def urls_compare_equal(url1: str, url2: str) -> bool:
    """Determines if two URLs refer to the same logical resource."""
    if not url1 or not url2:
        return False
    k1 = canonical_url_key(url1)
    k2 = canonical_url_key(url2)
    return bool(k1 and k2 and k1 == k2)

def detect_trailing_slash_convention(urls: List[str]) -> bool:
    """Detects whether the target website uses trailing slashes on non-root paths."""
    slash_count = 0
    non_slash_count = 0
    for u in urls:
        if not u:
            continue
        try:
            path = urlparse(u).path
            if path in ("", "/"):
                continue
            # Ignore file extensions like .html, .xml, .jpg
            if any(path.lower().endswith(ext) for ext in NON_HTML_EXTENSIONS):
                continue
            if path.endswith("/"):
                slash_count += 1
            else:
                non_slash_count += 1
        except Exception:
            continue
    return slash_count >= non_slash_count
