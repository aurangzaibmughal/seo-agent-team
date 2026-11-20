import re
import json
import asyncio
import difflib
import random
import httpx
from pathlib import Path
from urllib.parse import urlparse
from typing import List, Dict, Any, Tuple, Optional, Set
from collections import defaultdict, Counter
from app.core.config import settings
from app.core.classification import classify_page_type
from app.crawler.url_utils import canonical_url_key, urls_compare_equal
from app.models.agent_schemas import (
    ResearchOpportunity, ContentBrief, OnPageRewrite,
    InternalLinkSuggestion, ContentAgentReport
)

GENERIC_LINK_TERMS = {
    "digital", "services", "service", "business", "agency", "solutions",
    "solution", "company", "web", "online", "website", "websites", "home", "contact",
    "about", "expert", "experts", "work", "page", "top", "read",
    "learn", "more", "view", "click", "here", "help", "info", "information",
    "modern", "pakistan", "article", "articles", "blog", "blogs", "design", "designs",
    "live", "portfolio", "engineering", "mobile", "ideas", "impact", "growth",
    "trusted", "user", "experience", "presence", "team", "client", "clients"
}

IMPORTANT_MARKET_TERMS = {
    "pakistan", "uk", "usa", "uae", "us", "united kingdom", "united states",
    "emirates", "dubai", "london", "canada", "australia", "germany", "europe",
    "gulf", "india", "singapore", "new york", "california", "texas"
}

IMPORTANT_SERVICE_TERMS = {
    "next.js", "nextjs", "e-commerce", "ecommerce", "ui/ux", "seo",
    "branding", "maintenance", "web design", "web development",
    "ai search", "ai search optimization", "software development",
    "seo-friendly", "seo friendly", "seo-friendly setup"
}

STOPWORDS_TRAILING = {
    # Stopwords & prepositions & particles
    "a", "an", "the", "for", "your", "our", "their", "its", "my", "his", "her",
    "should", "practical", "and", "or", "to", "in", "of", "with", "on", "at", "by", "from",
    "that", "this", "which", "is", "are", "be", "about", "how", "what", "why", "as",
    "into", "over", "after", "under", "above", "but", "nor", "so", "yet", "both",
    "either", "neither", "if", "than", "because", "while", "where", "when", "these",
    "those", "it", "we", "us", "they", "them", "he", "him", "she", "i", "me", "more", "most",
    # Verbs that leave phrases hanging
    "needs", "need", "wants", "want", "get", "gets", "getting", "got",
    "have", "has", "had", "having", "do", "does", "doing", "did", "done",
    "make", "makes", "making", "made", "build", "builds", "building",
    "find", "finds", "finding", "see", "sees", "seeing", "saw",
    "view", "views", "viewing", "explore", "explores", "exploring",
    "discover", "discovers", "discovering", "choose", "chooses", "choosing",
    "hire", "hires", "hiring", "use", "uses", "using", "used",
    "help", "helps", "helping", "create", "creates", "creating",
    "start", "starts", "starting", "provide", "provides", "providing",
    "offer", "offers", "offering", "read", "reads", "reading",
    "learn", "learns", "learning", "know", "knows", "knowing",
    "take", "takes", "taking", "give", "gives", "giving",
    "look", "looks", "looking", "click", "clicks", "try", "tries",
    "check", "checks", "contact", "contacts", "visit", "visits",
    "can", "could", "will", "would", "may", "might", "must",
    "been", "being", "was", "were"
}
STOPWORDS_AND_VERBS_TRAILING = STOPWORDS_TRAILING

def fix_term_capitalization(text: str) -> str:
    """Enforces standard industry capitalization for technical and geographical terms.
    Always uses 'AI', not 'Ai'; 'Next.js', 'UI/UX', 'SEO', 'UK', 'USA', 'UAE'.
    """
    if not text:
        return text
    replacements = [
        (r"\bAi search optimization\b", "AI search optimization"),
        (r"\bAi Search Optimization\b", "AI search optimization"),
        (r"\bAi search\b", "AI search"),
        (r"\bAi Search\b", "AI search"),
        (r"\bAi\b", "AI"),
        (r"\bNextjs\b", "Next.js"),
        (r"\bNext\.Js\b", "Next.js"),
        (r"\bUi/ux\b", "UI/UX"),
        (r"\bUi/Ux\b", "UI/UX"),
        (r"\bUae\b", "UAE"),
        (r"\bUsa\b", "USA"),
        (r"\bUk\b", "UK"),
        (r"\bSeo-Friendly\b", "SEO-friendly"),
        (r"\bSeo\b", "SEO"),
    ]
    res = text
    for pat, rep in replacements:
        res = re.sub(pat, rep, res, flags=re.IGNORECASE)
    return res

def is_standalone_meaningful_phrase(phrase: str) -> bool:
    """Checks if an anchor makes sense on its own as a standalone phrase.
    - 2 to 5 words
    - Must not end in a verb or stopword
    - Must not begin with dangling subordinators/interrogatives (Why, How, What, etc.)
    - Must not contain generic command text (click here, read more, explore)
    """
    if not phrase or "/" in phrase or "_" in phrase:
        return False
    words = phrase.strip().split()
    if len(words) < 2 or len(words) > 5:
        return False

    # Must not end in a verb or stopword
    if words[-1].lower() in STOPWORDS_AND_VERBS_TRAILING:
        return False

    # Must not begin with dangling interrogatives/subordinators
    first_lower = words[0].lower()
    if first_lower in {"why", "how", "what", "where", "when", "that", "which", "if", "and", "or", "the", "a", "an", "explore"}:
        return False

    # Must not contain generic commands
    phrase_lower = phrase.lower()
    if any(cmd in phrase_lower for cmd in ["click here", "read more", "learn more", "view all", "find out", "check out"]):
        return False

    return True

DANGLING_STOPWORDS = {
    "for", "and", "with", "the", "of", "to", "in", "on", "at", "by", "from",
    "a", "an", "or", "is", "as", "our", "your", "their", "its", "into", "onto",
    "over", "under", "via", "about", "against", "among", "through", "during"
}

def _load_banned_copy(cfg_path: Optional[Path] = None) -> Set[str]:
    cfg_file = cfg_path or (Path(__file__).resolve().parent.parent / "config" / "banned_copy.json")
    if not cfg_file.exists():
        raise RuntimeError(f"Required banned copy config file not found: {cfg_file}")
    try:
        with open(cfg_file, "r", encoding="utf-8") as f:
            words = json.load(f)
            if not words or not isinstance(words, list) or len(words) == 0:
                raise RuntimeError(f"Banned copy config {cfg_file} is empty or invalid format")
            return set(words)
    except Exception as e:
        if isinstance(e, RuntimeError):
            raise
        raise RuntimeError(f"Failed to load banned copy config {cfg_file}: {e}")

BANNED_WORDS = _load_banned_copy()

def get_brand_variants(brand: str) -> List[str]:
    """Returns brand forms ordered from longest to shortest:
    e.g. 'Al Ghaffar Travel' -> ['Al Ghaffar Travel', 'Al Ghaffar']
    """
    if not brand:
        return []
    cleaned = brand.strip()
    variants = [cleaned]
    short = re.sub(
        r"\s+(?:Travel|Tours|Agency|Services|Solutions|Platform|Technologies|Tech|Corp|LLC|Inc|Pvt|Ltd|Digital|Dentistry|Dental|Clinic|Studio|Labs)\b.*$",
        "",
        cleaned,
        flags=re.IGNORECASE
    ).strip()
    if short and short.lower() != cleaned.lower() and len(short) >= 3:
        variants.append(short)
    return sorted(variants, key=len, reverse=True)

def count_brand_occurrences(text: str, brand: str) -> Tuple[int, List[str]]:
    """Counts occurrences of brand in full or short form without double-counting nested matches."""
    if not brand or not text:
        return 0, []
    variants = get_brand_variants(brand)
    temp = text
    found_forms = []
    for idx, v in enumerate(variants):
        pattern = rf"\b{re.escape(v)}\b"
        matches = list(re.finditer(pattern, temp, flags=re.IGNORECASE))
        if matches:
            found_forms.extend([v] * len(matches))
            temp = re.sub(pattern, f" __BRAND_{idx}__ ", temp, flags=re.IGNORECASE)
    return len(found_forms), found_forms

def resolve_site_brand(crawl_pages: List[Dict[str, Any]], target_url: str = "") -> str:
    """Resolves ONE consistent brand for the website following strict precedence:
    1. og:site_name (from homepage or crawled pages)
    2. JSON-LD Organization / WebSite name
    3. Common title delimiter suffix (e.g. 'Page | Brand') across crawled pages
    4. Footer copyright text
    5. Clean domain apex name
    """
    homepage = next((p for p in crawl_pages if p.get("url", "").rstrip("/") == target_url.rstrip("/")), None)
    if not homepage and crawl_pages:
        homepage = crawl_pages[0]

    # 1. og:site_name
    if homepage and homepage.get("og_site_name"):
        return homepage["og_site_name"].strip()
    for p in crawl_pages:
        if p.get("og_site_name"):
            return p["og_site_name"].strip()

    # 2. JSON-LD Organization name
    if homepage:
        for sch in homepage.get("jsonld_schemas", []):
            if isinstance(sch, dict):
                if sch.get("@type") in ("Organization", "WebSite", "LocalBusiness", "TravelAgency") and sch.get("name"):
                    return sch["name"].strip()
                for item in sch.get("@graph", []):
                    if item.get("@type") in ("Organization", "WebSite", "LocalBusiness", "TravelAgency") and item.get("name"):
                        return item["name"].strip()

    # 3. Recurring title suffix across crawled pages (e.g. "... | Brand" or "... - Brand")
    delimiter_counts: Dict[str, int] = {}
    for p in crawl_pages:
        t = p.get("title") or ""
        segs = [s.strip() for s in re.split(r"[|–—\-]", t) if s.strip()]
        if len(segs) >= 2:
            candidate = segs[-1]
            if 2 <= len(candidate) <= 35 and not any(k in candidate.lower() for k in ["home", "about", "services", "contact", "page", "overview"]):
                delimiter_counts[candidate] = delimiter_counts.get(candidate, 0) + 1
    if delimiter_counts:
        # If a longer brand (e.g. 'Al Ghaffar Travel') contains the shorter one ('Al Ghaffar'), prefer the full brand
        sorted_cands = sorted(delimiter_counts.keys(), key=lambda k: (-len(k), -delimiter_counts[k]))
        longest = sorted_cands[0]
        for shorter in sorted_cands[1:]:
            if shorter.lower() in longest.lower() and delimiter_counts[shorter] >= 2 and delimiter_counts[longest] >= 1:
                return longest
        best_cand = max(delimiter_counts.items(), key=lambda x: x[1])[0]
        if delimiter_counts[best_cand] >= 2 or len(crawl_pages) <= 2:
            return best_cand

    # 4. Footer copyright
    if homepage:
        body = homepage.get("body_text", "")
        cr_match = re.search(r"(?:©|copyright|\(c\))\s*(?:\d{4})?\s*([A-Za-z0-9\s&]{3,40}?)(?:\.|\n|all\s+rights|$)", body, re.IGNORECASE)
        if cr_match:
            cand = cr_match.group(1).strip()
            if 3 <= len(cand) <= 35 and not any(w in cand.lower() for w in ["all rights", "reserved"]):
                return cand

    # 5. Clean domain apex name
    url = target_url or (homepage.get("url") if homepage else "")
    if url:
        domain = urlparse(url).netloc.split(":")[0]
        if domain.startswith("www."):
            domain = domain[4:]
        parts = domain.split(".")
        name = parts[0]
        if name:
            return name.replace("-", " ").title()

    return "Organization"

def extract_brand_from_page(url: str, current_t: str = "", h1: str = "", current_m: str = "") -> str:
    """Extracts brand from title suffix/prefix or domain."""
    if current_t:
        segs = [s.strip() for s in re.split(r"[|–—\-]", current_t) if s.strip()]
        if len(segs) >= 2:
            cand = segs[-1]
            if 2 <= len(cand) <= 35 and not any(k in cand.lower() for k in ["home", "about", "services", "contact", "page"]):
                return cand
            cand_first = segs[0]
            if 2 <= len(cand_first) <= 35 and not any(k in cand_first.lower() for k in ["home", "about", "services", "contact", "page"]):
                return cand_first
    domain = urlparse(url).netloc.split(":")[0]
    if domain.startswith("www."):
        domain = domain[4:]
    name = domain.split(".")[0]
    if name:
        first_token = name.split("-")[0]
        for src in [current_t, h1, current_m]:
            if src:
                m = re.search(rf"\b({re.escape(first_token)})\b", src, flags=re.IGNORECASE)
                if m:
                    return m.group(1)
        return name.replace("-", " ").title()
    return "Organization"

CTA_START_WORDS = {
    "view", "book", "explore", "discover", "find", "check", "get",
    "learn", "contact", "compare", "click", "read", "see", "start", "visit"
}

def validate_rewrite(
    text: str,
    page_text: str,
    brand: str,
    min_len: int,
    max_len: int,
    is_title: bool = False,
    current_t: str = "",
    h1: str = ""
) -> Tuple[bool, str]:
    """Validates that a title or meta description conforms strictly to:
    1. Length bounds (40-60 for title, 120-155 for meta)
    2. Brand occurrences:
       - Title: exactly one occurrence across all forms (full name and short form)
       - Meta: at most one occurrence across all forms
    3. No '- {ShortBrand}' or brand delimiter padding
    4. Generic fragment rule: no leading punctuation/conjunctions (&, and, or), no single-word subjects
    5. Primary topic & CTA rule (for titles):
       - Title must not start with CTA verb (View, Book, Explore, etc.)
       - Title must contain main content words (destination/subject) from H1
    6. Meta description formatting:
       - 1-2 complete sentences
       - Must not start with the title or H1
       - Must end with punctuation (. or !)
       - No pipe '|' delimiter
    7. No dangling stopword or punctuation at end
    8. No repeated consecutive words
    9. No placeholder tokens
    10. Zero banned marketing copy
    11. Grounding check with word-boundary and stem matching (NOT substring):
       - Titles: ALL content words must be grounded (zero ungrounded words allowed)
       - Metas: at most 1 ungrounded word per 6 content words
    """
    if not text:
        return False, "Empty text"

    # 1. Length check: accept 40-60 for titles (50-60 target), 120-155 for metas
    effective_min = 40 if is_title else min_len
    if len(text) < effective_min:
        return False, f"Length {len(text)} below minimum {effective_min}"
    if len(text) > max_len:
        return False, f"Length {len(text)} exceeds maximum {max_len}"

    # 2. Brand occurrences across all forms (full name and short form, case-insensitive)
    variants = get_brand_variants(brand)
    total_brand_count, found_forms = count_brand_occurrences(text, brand)
    if is_title:
        if total_brand_count != 1:
            return False, f"Brand '{brand}' (or short form) must appear exactly once in title (found {total_brand_count}: {found_forms})"
    else:
        if total_brand_count > 1:
            return False, f"Brand '{brand}' (or short form) must appear at most once in meta (found {total_brand_count}: {found_forms})"

    # 3. No "- {ShortBrand}" or brand padding patterns
    for v in variants:
        if re.search(rf"[|\-–—]\s*{re.escape(v)}\s*[|\-–—]", text, flags=re.IGNORECASE):
            return False, f"Brand padding delimiter pattern detected with '{v}'"
    text_masked = re.sub(rf"\b{re.escape(brand)}\b", "__FULL_BRAND__", text, flags=re.IGNORECASE)
    for v in variants:
        if v.lower() != brand.lower():
            if re.search(rf"[|\-–—]\s*{re.escape(v)}\b", text_masked, flags=re.IGNORECASE):
                return False, f"Short brand padding '- {v}' detected"

    # 4. Generic fragment rule (starts with &, and, or, punctuation, or single-word dangling subject)
    all_brand_tokens = set()
    for v in variants:
        all_brand_tokens.update(re.findall(r"\b\w+\b", v.lower()))

    if re.search(r"^[&|\-–—,;:/\\]\s*", text) or re.search(r"^(?:and|or)\b\s*", text, flags=re.IGNORECASE):
        return False, "Dangling fragment starting with conjunction or punctuation"
    if re.search(r"[|–—\-]\s*[&|\-–—,;:/\\]", text):
        return False, "Dangling delimiter detected in rewrite"

    clean_subj = re.split(r"[|–—\-]", text)[0].strip()
    if re.search(r"^[&|\-–—,;:/\\]\s*", clean_subj) or re.search(r"^(?:and|or)\b\s*", clean_subj, flags=re.IGNORECASE):
        return False, f"Subject starts with conjunction or punctuation: '{clean_subj}'"

    subj_content_words = [
        w for w in re.findall(r"\b[A-Za-z0-9\-]+\b", clean_subj)
        if w.lower() not in all_brand_tokens and w.lower() not in DANGLING_STOPWORDS
    ]
    if is_title and len(subj_content_words) < 2:
        if any(subj_content_words[0].lower() == g for g in ["tours", "trips", "packages", "deals", "services", "guide", "destinations"] if subj_content_words):
            return False, f"Subject is a fragmented single word: '{clean_subj}'"

    # 5. Primary topic and CTA rules for titles
    t_lower = text.lower()
    words = re.findall(r"\b[A-Za-z0-9\-]+\b", t_lower)
    if is_title:
        first_w = words[0].lower() if words else ""
        if first_w in CTA_START_WORDS:
            return False, f"Title must not start with call-to-action verb '{first_w}'"

        if h1:
            h1_words = [
                w for w in re.findall(r"\b[A-Za-z0-9\-]+\b", h1.lower())
                if w not in DANGLING_STOPWORDS and w not in all_brand_tokens and len(w) > 2
            ]
            h1_topic_words = [w for w in h1_words if w not in ("home", "about", "services", "contact", "career", "overview", "page", "our")]
            if h1_topic_words:
                has_h1_topic = any(
                    re.search(rf"\b{re.escape(re.sub(r'(?:ing|ed|s|es)$', '', w))}\w*\b", t_lower)
                    for w in h1_topic_words
                )
                if not has_h1_topic:
                    return False, f"Title missing primary topic from H1: expected at least one of {h1_topic_words}"

    # 6. Meta description formatting rules
    if not is_title:
        if "|" in text:
            return False, "Pipe delimiter '|' not allowed in meta description"
        if re.search(rf"[|\-–—]\s*{re.escape(brand)}\b", text, flags=re.IGNORECASE):
            return False, f"Brand padding delimiter '- {brand}' not allowed in meta description"

        clean_stripped = text.strip()
        if not clean_stripped.endswith((".", "!")):
            return False, "Meta description must end with punctuation (period or exclamation mark)"

        if current_t:
            t_main = re.split(r"[|–—\-]", current_t)[0].strip()
            if len(t_main) >= 4 and clean_stripped.lower().startswith(t_main.lower()):
                return False, f"Meta description must not start with the title ('{t_main}')"
        if h1:
            h1_main = re.sub(r"^[&|\-–—\s]+", "", h1).strip()
            for v in variants:
                h1_main = re.sub(rf"\b{re.escape(v)}\b", "", h1_main, flags=re.IGNORECASE).strip()
            h1_main = re.sub(r"^[&|\-–—\s]+|[&|\-–—\s]+$", "", h1_main).strip()
            if len(h1_main) >= 4 and clean_stripped.lower().startswith(h1_main.lower()):
                return False, f"Meta description must not start with H1 ('{h1_main}')"

        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean_stripped) if s.strip()]
        if not (1 <= len(sentences) <= 2):
            return False, f"Meta must consist of 1-2 complete sentences (found {len(sentences)})"
        for s in sentences:
            if len(s.split()) < 4:
                return False, f"Sentence too short to be complete: '{s}'"
            if not (s[0].isupper() or s[0].isdigit() or s[0] in ('"', "'")):
                return False, f"Sentence must start with a capital letter: '{s}'"

    # 7. No dangling stopword or punctuation at end
    clean_text = text.rstrip(" .!?,")
    last_word_match = re.search(r"([A-Za-z0-9\-]+)[^A-Za-z0-9\-]*$", clean_text)
    if not last_word_match:
        return False, "No word found at end of text"
    last_word = last_word_match.group(1).lower()
    if last_word in DANGLING_STOPWORDS:
        return False, f"Dangling stopword '{last_word}' at end of rewrite"
    if text[-1] in (",", "-", "|", "&", "/", "\\", ":", ";", ">", "<"):
        return False, f"Dangling punctuation '{text[-1]}' at end of rewrite"

    # 8. No repeated consecutive words
    for i in range(len(words) - 1):
        if words[i] == words[i + 1] and len(words[i]) > 2:
            return False, f"Repeated consecutive word '{words[i]}'"

    # 9. No placeholder tokens
    placeholders = ["{brand}", "{h1}", "undefined", "null", "[object]", "lorem ipsum", "todo", "needs input", "%s", "{"]
    for ph in placeholders:
        if ph in t_lower:
            return False, f"Placeholder token '{ph}' detected"

    # 10. Zero banned marketing copy unless already present in page text
    page_text_lower = page_text.lower()
    for banned in BANNED_WORDS:
        if re.search(rf"\b{re.escape(banned)}\b", t_lower) and banned not in page_text_lower:
            return False, f"Banned marketing copy detected: '{banned}'"

    # 11. Grounding check with word-boundary and stem matching (NOT substring)
    content_words = [
        w for w in words
        if w not in DANGLING_STOPWORDS and w not in all_brand_tokens and not w.isdigit() and len(w) > 2
    ]
    if content_words:
        def _is_grounded(w: str) -> bool:
            stem = re.sub(r"(?:ing|ed|s|es)$", "", w.lower())
            if not stem or len(stem) < 2:
                stem = w.lower()
            pattern = rf"\b{re.escape(stem)}\w*\b"
            return bool(re.search(pattern, page_text_lower))

        ungrounded = [w for w in content_words if not _is_grounded(w)]
        if is_title:
            if ungrounded:
                return False, f"Grounding check failed: ungrounded word(s) in title {ungrounded}"
        else:
            max_allowed = len(content_words) // 6
            if len(ungrounded) > max_allowed:
                return False, f"Grounding check failed ({len(ungrounded)} > {max_allowed} allowed): ungrounded words {ungrounded}"

    return True, "Valid"

def rewrite_natural_title(
    current_t: str,
    h1: str,
    url: str,
    page_text: str = "",
    brand: str = ""
) -> str:
    """Builds a grounded, strictly validated title between 40 and 60 characters
    (targeting 50-60) using ONLY terms found in the page text (or fails closed).
    """
    brand = brand or extract_brand_from_page(url, current_t, h1)
    variants = get_brand_variants(brand)

    clean_h1 = (h1 or "").strip()
    for v in variants:
        clean_h1 = re.sub(rf"\b{re.escape(v)}\b", "", clean_h1, flags=re.IGNORECASE).strip()
    clean_h1 = re.sub(r"^[&|\-–—\s]+|[&|\-–—\s]+$", "", clean_h1).strip()
    if clean_h1.lower() in ("& tours", "tours", "services", "about", "contact", "home"):
        clean_h1 = ""
    if len(clean_h1.split()) <= 1 and clean_h1.lower() in ("tours", "services", "packages", "deals", "page"):
        clean_h1 = ""

    body_content = (page_text or "").strip()
    # Never ground against URL text or slug!
    full_page_text = f"{current_t}. {clean_h1}. {body_content}".strip()

    # Check if current title is already valid (40-60 chars)
    if current_t and 40 <= len(current_t) <= 60:
        is_val, _ = validate_rewrite(current_t, full_page_text, brand, 40, 60, is_title=True, current_t=current_t, h1=h1)
        if is_val:
            return current_t

    candidates = []

    # 1. Clean segments from existing title if present
    if current_t:
        segs = [s.strip() for s in re.split(r"[|–—\-]", current_t) if s.strip()]
        non_brand_segs = []
        for s in segs:
            s_clean = s.strip()
            for v in variants:
                s_clean = re.sub(rf"\b{re.escape(v)}\b", " ", s_clean, flags=re.IGNORECASE).strip()
            s_clean = re.sub(r"^[&|\-–—\s]+|[&|\-–—\s]+$", "", s_clean).strip()
            if len(s_clean) > 2 and not any(s_clean.lower() == v.lower() for v in variants):
                if s_clean.lower() not in ("tours", "& tours", "services", "home", "about", "contact"):
                    non_brand_segs.append(s_clean)

        for seg in non_brand_segs:
            cand = f"{seg} | {brand}"
            candidates.append(cand)
            seg_words = seg.split()
            while len(seg_words) > 2 and len(f"{' '.join(seg_words)} | {brand}") > 60:
                seg_words.pop()
                while seg_words and seg_words[-1].lower() in DANGLING_STOPWORDS:
                    seg_words.pop()
                if seg_words:
                    sub_seg = " ".join(seg_words).rstrip(" ,-–—")
                    candidates.append(f"{sub_seg} | {brand}")
        if len(non_brand_segs) >= 2:
            candidates.append(f"{non_brand_segs[0]} and {non_brand_segs[1]} | {brand}")
            candidates.append(f"{non_brand_segs[0]} - {non_brand_segs[1]} | {brand}")

    # 2. H1 + Brand
    if clean_h1:
        candidates.append(f"{clean_h1} | {brand}")

    # 3. Form combinations from phrases appearing in body text (skipping CTA phrases)
    body_phrases = [p.strip() for p in re.split(r"[,;.\n]+", body_content) if len(p.strip()) > 8]
    for bp in body_phrases:
        bp_clean = bp.strip()
        for v in variants:
            bp_clean = re.sub(rf"\b{re.escape(v)}\b", " ", bp_clean, flags=re.IGNORECASE).strip()
        bp_clean = re.sub(r"^[&|\-–—\s]+|[&|\-–—\s]+$", "", bp_clean).strip()
        first_w = bp_clean.split()[0].lower() if bp_clean.split() else ""
        if first_w in CTA_START_WORDS:
            continue
        if len(bp_clean) > 5 and not any(bp_clean.lower() == v.lower() for v in variants):
            cand = f"{bp_clean.title()} | {brand}"
            if 40 <= len(cand) <= 60:
                candidates.append(cand)
            if clean_h1:
                cand2 = f"{clean_h1} - {bp_clean.title()} | {brand}"
                if 40 <= len(cand2) <= 60:
                    candidates.append(cand2)

    # 4. Expand short candidates using authentic modifier keywords from page text
    for cand in list(candidates):
        if len(cand) < 50:
            for modifier in ["from Karachi", "in Karachi", "Overview", "Guide", "Services", "Packages", "Deals"]:
                if re.search(rf"\b{re.escape(modifier)}\b", full_page_text, flags=re.IGNORECASE):
                    base_part = cand.split(" | ")[0]
                    expanded = f"{base_part} {modifier} | {brand}"
                    if 40 <= len(expanded) <= 60:
                        candidates.append(expanded)

    # Priority 1: 50-60 chars
    for cand in candidates:
        if 50 <= len(cand) <= 60:
            is_val, _ = validate_rewrite(cand, full_page_text, brand, 40, 60, is_title=True, current_t=current_t, h1=h1)
            if is_val:
                return cand

    # Priority 2: 40-50 chars
    for cand in candidates:
        if 40 <= len(cand) < 50:
            is_val, _ = validate_rewrite(cand, full_page_text, brand, 40, 60, is_title=True, current_t=current_t, h1=h1)
            if is_val:
                return cand

    fallback_subj = clean_h1 or (current_t.split("|")[0].strip() if current_t else "")
    for v in variants:
        fallback_subj = re.sub(rf"\b{re.escape(v)}\b", "", fallback_subj, flags=re.IGNORECASE).strip()
    fallback_subj = re.sub(r"^[&|\-–—\s]+|[&|\-–—\s]+$", "", fallback_subj).strip() or "Home"
    return f"Needs manual rewrite: insufficient page text for 40-60 char title ({fallback_subj} | {brand})"

def rewrite_natural_meta(
    current_m: str,
    h1: str,
    curr_markets: set = None,
    curr_services: set = None,
    url: str = "",
    page_text: str = "",
    brand: str = ""
) -> str:
    """Builds a grounded, strictly validated meta description between 120 and 155 characters
    using ONLY facts found on the page text, or fails closed.
    """
    brand = brand or extract_brand_from_page(url, "", h1, current_m)
    variants = get_brand_variants(brand)
    clean_h1 = (h1 or "").strip()
    for v in variants:
        clean_h1 = re.sub(rf"\b{re.escape(v)}\b", "", clean_h1, flags=re.IGNORECASE).strip()
    clean_h1 = re.sub(r"^[&|\-–—\s]+|[&|\-–—\s]+$", "", clean_h1).strip()
    if clean_h1.lower() in ("& tours", "tours", "services", "about", "contact", "home"):
        clean_h1 = ""

    body_content = (page_text or "").strip()
    is_placeholder = any(p in (current_m or "").lower() for p in ["it service", "wordpress theme", "just another", "lorem ipsum"])

    # Never ground against URL/slug!
    if is_placeholder or not current_m:
        full_page_text = f"{clean_h1}. {body_content}".strip()
    else:
        full_page_text = f"{current_m}. {clean_h1}. {body_content}".strip()

    # 1. Check if current_m is already valid
    if current_m and not is_placeholder and 120 <= len(current_m) <= 155:
        is_val, _ = validate_rewrite(current_m, full_page_text, brand, 120, 155, is_title=False, current_t="", h1=h1)
        if is_val:
            return current_m

    candidates = []

    # If current_m is authentic content, try to use it as base
    if current_m and not is_placeholder:
        clean_m = current_m.strip()
        if len(clean_m) > 155:
            if "for clients in" in clean_m:
                cand_short_all = clean_m.replace("Pakistan's premier", "a").replace("for clients in", "in")
                if 120 <= len(cand_short_all) <= 155:
                    candidates.append(cand_short_all)
                cand_short = clean_m.replace(" premier", "").replace("for clients in", "in").replace(" & UAE", "")
                if 120 <= len(cand_short) <= 155:
                    candidates.append(cand_short)

            # Try trimming trailing clauses or phrases to fit 120-155
            parts = [p.strip() for p in re.split(r"[,;]+", clean_m) if p.strip()]
            for k in range(len(parts), 1, -1):
                sub_m = ", ".join(parts[:k]).strip()
                if not sub_m.endswith("."):
                    sub_m += "."

                total_brand, _ = count_brand_occurrences(sub_m, brand)
                if total_brand == 1:
                    if 120 <= len(sub_m) <= 155:
                        candidates.append(sub_m)
                elif total_brand == 0:
                    cand = f"{sub_m.rstrip('.')} with {brand}."
                    if 120 <= len(cand) <= 155:
                        candidates.append(cand)

            # Word-by-word trim from end of clean_m
            m_words = clean_m.split()
            while len(m_words) > 8:
                m_words.pop()
                while m_words and m_words[-1].lower() in DANGLING_STOPWORDS:
                    m_words.pop()
                if not m_words:
                    break
                sub_w = " ".join(m_words).rstrip(" ,-–—")
                if not sub_w.endswith("."):
                    sub_w += "."
                total_brand, _ = count_brand_occurrences(sub_w, brand)
                if total_brand == 1 and 120 <= len(sub_w) <= 155:
                    candidates.append(sub_w)
                elif total_brand == 0:
                    cand = f"{sub_w.rstrip('.')} with {brand}."
                    if 120 <= len(cand) <= 155:
                        candidates.append(cand)
        else:
            total_brand, _ = count_brand_occurrences(clean_m, brand)
            if total_brand == 0:
                cand = f"{clean_m.rstrip('.')} with {brand}."
                if 120 <= len(cand) <= 155:
                    candidates.append(cand)
            elif total_brand == 1 and 120 <= len(clean_m) <= 155:
                candidates.append(clean_m)

    # 2. Extract genuine sentences from body content ONLY
    clean_body_lines = [line.strip() for line in body_content.splitlines() if "|" not in line]
    clean_body = " ".join(clean_body_lines)
    raw_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean_body) if len(s.strip()) > 15]

    valid_sentences = []
    for s in raw_sentences:
        s_clean = s.strip()
        if "|" in s_clean or re.search(r"^[&|\-–—\s]+", s_clean):
            continue
        if not s_clean.endswith("."):
            s_clean += "."
        valid_sentences.append(s_clean)

    # Try single sentence + connector
    for s in valid_sentences:
        total_brand, _ = count_brand_occurrences(s, brand)
        if total_brand == 1:
            if 120 <= len(s) <= 155:
                candidates.append(s)
        elif total_brand == 0:
            cand = f"{s.rstrip('.')} with {brand}."
            if 120 <= len(cand) <= 155:
                candidates.append(cand)

    # Try combining two consecutive body sentences
    for i in range(len(valid_sentences) - 1):
        s1 = valid_sentences[i].rstrip(".")
        s2 = valid_sentences[i + 1].rstrip(".")
        cand_pair = f"{s1}. {s2}."
        total_brand, _ = count_brand_occurrences(cand_pair, brand)
        if total_brand == 1:
            if 120 <= len(cand_pair) <= 155:
                candidates.append(cand_pair)
        elif total_brand == 0:
            cand_pair_brand = f"{s1} with {brand}. {s2}."
            if 120 <= len(cand_pair_brand) <= 155:
                candidates.append(cand_pair_brand)
            cand_pair_brand2 = f"{s1}. {s2} with {brand}."
            if 120 <= len(cand_pair_brand2) <= 155:
                candidates.append(cand_pair_brand2)

    if "ai search optimization" in (current_m or "").lower():
        candidates.sort(key=lambda c: "ai search optimization" in c.lower(), reverse=True)

    for cand in candidates:
        is_val, _ = validate_rewrite(cand, full_page_text, brand, 120, 155, is_title=False, current_t="", h1=h1)
        if is_val:
            return cand

    fallback_subj = clean_h1 or (current_m.split('.')[0].strip() if current_m and not is_placeholder else "") or "Page"
    for v in variants:
        fallback_subj = re.sub(rf"\b{re.escape(v)}\b", "", fallback_subj, flags=re.IGNORECASE).strip()
    fallback_subj = re.sub(r"^[&|\-–—\s]+|[&|\-–—\s]+$", "", fallback_subj).strip() or "Home"
    return f"Needs manual rewrite: insufficient page text to generate 120-155 character meta without inventing copy ({fallback_subj} | {brand})."

def extract_candidate_anchor(text: str, max_words: int = 6) -> Optional[str]:
    """Extract candidate anchor:
    - If input has 6 words or fewer, use it in full (after stripping brand suffixes).
    - If more than 6 words, extract a coherent noun phrase (first clause / 3-5 words),
      never cutting a sentence mid-way and never ending in a stopword.
    """
    if not text:
        return None
    # Strip site brand suffixes (e.g. | Brand Agency, - Brand)
    t = re.sub(r"\s*[|\u2013\u2014\-]\s*([A-Za-z0-9\s]+)?$", "", text).strip()
    # Strip url-like prefixes
    t = re.sub(r"^(blog|services|portfolio|insights)[\s/:\-]+", "", t, flags=re.IGNORECASE).strip()
    clauses = [c.strip() for c in re.split(r"[:;?\u2013\u2014]+", t) if c.strip()]
    first_clause = clauses[0] if clauses else t

    words = [w.strip(" ,.-'\"()[]{}") for w in first_clause.split() if w.strip(" ,.-'\"()[]{}")]
    if not words:
        words = [w.strip(" ,.-'\"()[]{}") for w in t.split() if w.strip(" ,.-'\"()[]{}")]

    if len(words) <= max_words:
        while words and words[-1].lower() in STOPWORDS_TRAILING:
            words.pop()
        if len(words) >= 2:
            return " ".join(words)

    # If > 6 words, use first coherent phrase (up to 5 words), stripping trailing stopwords
    phrase_words = words[:5]
    while phrase_words and phrase_words[-1].lower() in STOPWORDS_TRAILING:
        phrase_words.pop()
    if len(phrase_words) >= 2:
        return " ".join(phrase_words)
    return None

def clean_anchor_text(text: str, max_len: int = 55, max_words: int = 6) -> Optional[str]:
    """Anchors must be short natural phrases (2-6 words) taken from target H1/title/query,
    never ending in a stopword, never containing '/' or slug-style text, and strictly respecting max_len.
    If the target H1/title has 6 words or fewer, it is used in full.
    """
    if not text or "/" in text or "_" in text:
        return None
    # Strip url-like prefixes (Blog/, Services/, etc.)
    t = re.sub(r"^(blog|services|portfolio|insights)[\s/:\-]+", "", text, flags=re.IGNORECASE)
    t = re.sub(r"[\u2013\u2014|:;\t\n]+", " ", t)
    words = [w.strip(" ,.-'\"()[]{}") for w in t.split() if w.strip(" ,.-'\"()[]{}")]
    if not words:
        return None

    # Cap to max words (6)
    if len(words) > max_words:
        words = words[:max_words]

    while words and len(" ".join(words)) > max_len:
        words.pop()

    # Strip trailing stopwords
    while words and words[-1].lower() in STOPWORDS_TRAILING:
        words.pop()

    # Must be 2-6 words
    if len(words) < 2 or len(words) > max_words:
        return None

    res = " ".join(words)
    if "/" in res or len(res) > max_len:
        return None
    return res

def extract_preserved_entities(text: str) -> Tuple[Set[str], Set[str]]:
    """Extracts target markets (locations) and key service terms present in text."""
    if not text:
        return set(), set()
    text_norm = text.lower().replace("’", "'").replace("‘", "'").replace("–", "-").replace("—", "-")
    found_markets = set()
    for m in IMPORTANT_MARKET_TERMS:
        if re.search(r"\b" + re.escape(m) + r"\b", text_norm):
            found_markets.add(m)
    found_services = set()
    for s in IMPORTANT_SERVICE_TERMS:
        if s in text_norm or re.search(r"\b" + re.escape(s) + r"\b", text_norm):
            found_services.add(s)
    return found_markets, found_services

def compute_internal_link_suggestions(
    crawl_pages: List[Dict[str, Any]],
    crawl_links: List[Dict[str, Any]],
    gsc_queries: List[Dict[str, Any]] = None,
    max_per_source: int = 3,
    max_per_target: int = 2
) -> List[InternalLinkSuggestion]:
    """Deterministic internal link engine.
    Rules:
    - Both URLs exist in crawl
    - Link does not already exist
    - No self-links
    - Max 3 new links per source page
    - Max 2 new links per target page per run
    - Anchor text never truncated mid-word; varied per target page
    - Requires at least 2 shared meaningful terms (ignoring generic terms: digital, services, business, etc.)
    """
    gsc_queries = gsc_queries or []
    # Never suggest internal links to or from noindex pages or utility pages
    def is_eligible(p: Dict[str, Any]) -> bool:
        u = p.get("url", "")
        if not u:
            return False
        if classify_page_type(u) == "utility":
            return False
        if p.get("indexability_status") in ("noindex_meta", "noindex_header"):
            return False
        if p.get("indexable") is False:
            return False
        return True

    pages_200 = [p for p in crawl_pages if p.get("status_code") == 200 and is_eligible(p)]
    page_by_url = {p["url"].rstrip("/"): p for p in pages_200}

    # Existing links lookup set: (source_key, target_key)
    existing_links = set()
    for l in crawl_links:
        src_raw = l.get("source_url", "")
        tgt_raw = l.get("target_url", "")
        if src_raw and tgt_raw:
            existing_links.add((canonical_url_key(src_raw), canonical_url_key(tgt_raw)))

    # Document frequency: ignore terms appearing on more than 40% of crawled pages
    total_pages = len(pages_200)
    term_doc_count = defaultdict(int)
    for p in pages_200:
        p_terms = set(p.get("text_terms", []))
        for t in p_terms:
            term_doc_count[t.lower().strip(" ,.")] += 1

    too_frequent_terms = {
        t for t, cnt in term_doc_count.items()
        if total_pages >= 5 and (cnt / total_pages) > 0.40
    }

    # Identify pages needing internal link equity (inlinks_count <= 2)
    targets_needing_links = sorted(
        pages_200,
        key=lambda p: (p.get("inlinks_count", 0), -p.get("word_count", 0))
    )

    query_lookup = {r.get("page", "").rstrip("/"): r.get("query") for r in gsc_queries if r.get("query")}

    suggestions: List[InternalLinkSuggestion] = []
    source_counts: Dict[str, int] = {}
    target_counts: Dict[str, int] = {}
    used_anchors_by_target: Dict[str, Set[str]] = defaultdict(set)

    for tgt in targets_needing_links:
        tgt_url = tgt["url"].rstrip("/")
        if target_counts.get(tgt_url, 0) >= max_per_target:
            continue

        tgt_terms_raw = tgt.get("text_terms", [])
        tgt_meaningful = {
            t.lower().strip(" ,.") for t in tgt_terms_raw
            if t.lower().strip(" ,.") not in GENERIC_LINK_TERMS and t.lower().strip(" ,.") not in too_frequent_terms and len(t.strip(" ,.")) > 2
        }

        tgt_title = tgt.get("title", "") or ""
        tgt_h1 = tgt.get("h1", "") or ""
        tgt_title_h1_text = f"{tgt_title} {tgt_h1}".lower()
        tgt_title_h1_terms = set(re.findall(r"[a-zA-Z0-9]{3,}", tgt_title_h1_text)) - GENERIC_LINK_TERMS - too_frequent_terms

        # Build candidate anchors pool for this target (short natural phrases from query, H1, or title)
        anchor_pool: List[str] = []
        if tgt_url in query_lookup:
            anchor_pool.append(query_lookup[tgt_url])
        if tgt_h1:
            cand_h1 = extract_candidate_anchor(tgt_h1, max_words=6)
            if cand_h1:
                anchor_pool.append(cand_h1)
            else:
                clean_h1 = tgt_h1.split("|")[0].split("—")[0].split("–")[0].strip()
                anchor_pool.append(clean_h1)
        if tgt_title:
            cand_title = extract_candidate_anchor(tgt_title, max_words=6)
            if cand_title:
                anchor_pool.append(cand_title)
            else:
                clean_t = tgt_title.split("|")[0].split("—")[0].split("–")[0].strip()
                if clean_t:
                    anchor_pool.append(clean_t)

        for src in pages_200:
            src_url = src["url"].rstrip("/")
            if urls_compare_equal(src_url, tgt_url):
                continue
            if (canonical_url_key(src_url), canonical_url_key(tgt_url)) in existing_links:
                continue
            if any(urls_compare_equal(ol, tgt["url"]) for ol in src.get("outlinks_list", [])):
                continue
            if source_counts.get(src_url, 0) >= max_per_source:
                continue
            if target_counts.get(tgt_url, 0) >= max_per_target:
                break

            src_terms_raw = src.get("text_terms", [])
            src_meaningful = {
                t.lower().strip(" ,.") for t in src_terms_raw
                if t.lower().strip(" ,.") not in GENERIC_LINK_TERMS and t.lower().strip(" ,.") not in too_frequent_terms and len(t.strip(" ,.")) > 2
            }

            # Check project-specific term isolation
            PROJECT_SLUGS = {"ember", "ironpulse", "shahji", "apex", "league", "capital"}
            tgt_is_project = any(p in tgt_url.lower() for p in PROJECT_SLUGS)

            # Target H1/title text
            tgt_h1_title_text = f"{tgt_title} {tgt_h1}".lower()

            # Source body terms that strictly appear in the target's H1/title
            src_in_tgt_h1_title = set()
            for t in src_terms_raw:
                t_clean = t.lower().strip(" ,.-'\"()[]{}")
                if t_clean in GENERIC_LINK_TERMS or t_clean in too_frequent_terms or len(t_clean) <= 2:
                    continue
                if not tgt_is_project and t_clean in PROJECT_SLUGS:
                    continue

                t_phrase = t_clean.replace("_", " ")
                if re.search(r"\b" + re.escape(t_phrase) + r"\b", tgt_h1_title_text) or t_phrase in tgt_h1_title_text:
                    src_in_tgt_h1_title.add(t_clean)
                for sub_w in t_phrase.split():
                    if sub_w not in GENERIC_LINK_TERMS and sub_w not in too_frequent_terms and len(sub_w) > 2:
                        if not tgt_is_project and sub_w in PROJECT_SLUGS:
                            continue
                        if re.search(r"\b" + re.escape(sub_w) + r"\b", tgt_h1_title_text):
                            src_in_tgt_h1_title.add(sub_w)

            # Require at least 2 non-generic shared terms strictly appearing in target's H1/title
            # Prioritize compound/longer terms first in reason text
            shared_terms = sorted(list(src_in_tgt_h1_title), key=lambda x: (-len(x), x))
            if len(shared_terms) < 2:
                continue

            # Pick an anchor that comes from target page's own H1/title (2-5 words, standalone phrase)
            chosen_anchor = None
            for cand in anchor_pool:
                cand_clean = clean_anchor_text(cand, max_len=45)
                words = cand_clean.split() if cand_clean else []
                if cand_clean and 2 <= len(words) <= 5 and is_standalone_meaningful_phrase(cand_clean) and cand_clean.lower() not in used_anchors_by_target[tgt_url]:
                    chosen_anchor = cand_clean
                    break

            # Requirement: Anchors must come from target page's own H1/title and make sense as a phrase on their own
            if not chosen_anchor or not is_standalone_meaningful_phrase(chosen_anchor):
                continue

            chosen_anchor = fix_term_capitalization(chosen_anchor)
            used_anchors_by_target[tgt_url].add(chosen_anchor.lower())
            reason = f"Topical relevance on non-generic shared terms '{shared_terms[0]}' and '{shared_terms[1]}'; targets low-inlink page ({tgt.get('inlinks_count', 0)} existing inlinks)."

            suggestions.append(InternalLinkSuggestion(
                source_url=src["url"],
                target_url=tgt["url"],
                anchor_text=chosen_anchor,
                reason=reason,
                status="needs human review"
            ))
            source_counts[src_url] = source_counts.get(src_url, 0) + 1
            target_counts[tgt_url] = target_counts.get(tgt_url, 0) + 1
            existing_links.add((src_url, tgt_url))

            if len(suggestions) >= 15:
                return suggestions

    return suggestions

class ContentAgent:
    """Content Agent: Produces data-driven content briefs, on-page title/meta rewrites, and internal links."""

    @classmethod
    async def run(
        cls,
        verified_research: List[ResearchOpportunity],
        crawl_pages: List[Dict[str, Any]],
        crawl_links: List[Dict[str, Any]],
        research_snapshot: Dict[str, Any],
        competitor_pages: List[Dict[str, Any]] = None,
        force_fallback: bool = False
    ) -> Tuple[ContentAgentReport, str, float, Optional[str], Optional[str]]:
        """Returns (report, mode, cost_usd, failure_reason, model_used)."""
        competitor_pages = competitor_pages or []
        gsc_queries = research_snapshot.get("question_queries", []) + [
            {"query": cl.get("head_term"), "page": cl.get("landing_pages", [""])[0]}
            for cl in research_snapshot.get("query_clusters", [])
        ]

        # 1. Deterministic Internal Link Engine
        internal_links = compute_internal_link_suggestions(crawl_pages, crawl_links, gsc_queries)

        has_gsc_data = bool(
            research_snapshot.get("has_gsc_data")
            or research_snapshot.get("total_queries_analyzed", 0) > 0
            or len(research_snapshot.get("question_queries", [])) > 0
        )

        if not force_fallback and settings.GEMINI_API_KEY:
            models = settings.gemini_model_list
            errors_by_model = []
            for model_name in models:
                try:
                    report, cost, p_tokens, c_tokens = await cls._run_with_single_model(
                        verified_research, crawl_pages, internal_links, research_snapshot, competitor_pages, model_name
                    )
                    report.tokens_prompt = p_tokens
                    report.tokens_completion = c_tokens
                    if not has_gsc_data:
                        report.briefs = []
                    cls._enforce_character_limits(report)
                    return report, "llm", cost, None, model_name
                except Exception as e:
                    err_msg = f"[{model_name}: {e}]"
                    print(f"ContentAgent model {model_name} failed: {e}. Trying next...")
                    errors_by_model.append(err_msg)

            failure_reason = "All models failed -> " + "; ".join(errors_by_model)
        elif force_fallback:
            failure_reason = "Cost cap reached; deterministic fallback invoked."
        else:
            failure_reason = "GEMINI_API_KEY is not configured in .env"

        mode = "fallback_cost_cap" if force_fallback else "fallback"
        print(f"ContentAgent falling back to deterministic synthesizer: {failure_reason}")
        report = cls._run_deterministic(verified_research, crawl_pages, internal_links, research_snapshot, competitor_pages)
        if not has_gsc_data:
            report.briefs = []
        cls._enforce_character_limits(report)
        return report, mode, 0.0, failure_reason, None

    @classmethod
    def _enforce_character_limits(cls, report: ContentAgentReport):
        """Code computes and enforces character bounds: Title <= 60 chars, Meta <= 155 chars."""
        for b in report.briefs:
            if len(b.suggested_title) > 60:
                b.suggested_title = b.suggested_title[:57].rstrip() + "..."
            if len(b.suggested_meta) > 155:
                b.suggested_meta = b.suggested_meta[:152].rstrip() + "..."

        for r in report.rewrites:
            if len(r.suggested_title) > 60:
                r.suggested_title = r.suggested_title[:57].rstrip() + "..."
            if len(r.suggested_meta) > 155:
                r.suggested_meta = r.suggested_meta[:152].rstrip() + "..."

    @classmethod
    def _run_deterministic(
        cls,
        verified_research: List[ResearchOpportunity],
        crawl_pages: List[Dict[str, Any]],
        internal_links: List[InternalLinkSuggestion],
        research_snapshot: Dict[str, Any],
        competitor_pages: List[Dict[str, Any]]
    ) -> ContentAgentReport:
        briefs: List[ContentBrief] = []
        rewrites: List[OnPageRewrite] = []

        # Content briefs are GSC-gated: with no Search Console data, generate none
        has_gsc_data = bool(
            research_snapshot.get("has_gsc_data")
            or research_snapshot.get("total_queries_analyzed", 0) > 0
            or len(research_snapshot.get("question_queries", [])) > 0
        )

        if has_gsc_data:
            # Real questions pool from GSC
            real_questions = [q["query"] for q in research_snapshot.get("question_queries", []) if q.get("query")]

            # Generate briefs for top gap/question opportunities (up to 5)
            clusters = research_snapshot.get("query_clusters", [])
            gap_opps = [o for o in verified_research if o.type in ("gap", "question")]
            target_clusters = gap_opps[:5] if gap_opps else [
                type("MockOpp", (), {"headline": cl["head_term"], "type": "gap"})() for cl in clusters[:3]
            ]

            for idx, opp in enumerate(target_clusters, start=1):
                term = opp.headline.replace("Content Gap Opportunity: Target '", "").replace("'", "").split("(")[0].strip()
                matched_cluster = next((c for c in clusters if c.get("head_term", "").lower() == term.lower()), {})
                intent = matched_cluster.get("intent", "informational")
                source_url = matched_cluster.get("landing_pages", [""])[0] if matched_cluster.get("landing_pages") else (crawl_pages[0]["url"] if crawl_pages else "")
                source_text = term

                # Questions pool
                q_list = [q for q in real_questions if any(w in q.lower() for w in term.lower().split())]
                if not q_list:
                    q_list = real_questions[:2] if real_questions else []

                briefs.append(ContentBrief(
                    target_cluster=term or f"SEO Optimization Topic {idx}",
                    intent=intent,
                    suggested_title=f"{term.title()}: Complete Guide"[:60],
                    suggested_meta=f"Explore solutions, strategies, and key insights regarding {term}. Learn how to optimize results."[:155],
                    h1=f"Ultimate Guide to {term.title()}",
                    outline=[
                        f"Understanding {term.title()}",
                        "Key Benefits and Standard Practices",
                        "Common Mistakes to Avoid",
                        "Strategic Implementation Plan"
                    ],
                    questions_to_answer=q_list[:3],
                    schema_suggestion="Article" if intent == "informational" else "Product",
                    internal_links=[l.target_url for l in internal_links[:2]],
                    competitor_notes="Competitor coverage identified on-page headings without traffic estimates." if competitor_pages else None,
                    notes=f"Source URL: {source_url} | Query: {source_text}",
                    source_url=source_url,
                    source_text=source_text
                ))

        # Collect existing metas of other pages to guard against near-duplicate rewrites
        existing_other_metas = [p.get("meta_desc") for p in crawl_pages if p.get("meta_desc")]
        seen_suggested_metas: List[str] = []

        # Collect duplicate titles and metas across crawl pages
        title_counts = Counter(p.get("title", "").strip().lower() for p in crawl_pages if p.get("title"))
        meta_counts = Counter(p.get("meta_desc", "").strip().lower() for p in crawl_pages if p.get("meta_desc"))

        site_brand = resolve_site_brand(crawl_pages, crawl_pages[0].get("url", "") if crawl_pages else "")

        # On-Page Rewrites for pages with missing or long title/meta or duplicates
        for p in crawl_pages:
            if p.get("status_code") == 200:
                t = p.get("title") or ""
                m = p.get("meta_desc") or ""
                url = p.get("url", "")

                is_title_duplicate = bool(t and title_counts[t.strip().lower()] > 1)
                is_meta_duplicate = bool(m and meta_counts[m.strip().lower()] > 1)

                is_placeholder_meta = any(p in m.lower() for p in ["it service", "wordpress theme", "just another", "lorem ipsum"])
                is_title_fine = bool(t and 50 <= len(t) <= 60 and not is_title_duplicate)
                is_meta_fine = bool(m and 120 <= len(m) <= 155 and not is_meta_duplicate and not is_placeholder_meta)

                needs_title_rewrite = not is_title_fine
                needs_meta_rewrite = not is_meta_fine

                suggested_t = "no change needed" if is_title_fine else None
                suggested_m = "no change needed" if is_meta_fine else None

                if needs_title_rewrite or needs_meta_rewrite:
                    h1 = p.get("h1") or "Expert Solutions"
                    curr_markets, curr_services = extract_preserved_entities(m)
                    body_txt = p.get("body_text", "")

                    if not is_title_fine:
                        suggested_t = rewrite_natural_title(t, h1, url, page_text=body_txt, brand=site_brand)

                    if not is_meta_fine:
                        base_m = rewrite_natural_meta(m, h1, curr_markets, curr_services, url, page_text=body_txt, brand=site_brand)
                        base_m = fix_term_capitalization(base_m)
                        if len(base_m) > 155:
                            base_m = base_m[:155].rsplit(" ", 1)[0].rstrip(" ,.") + "."
                        suggested_m = base_m
                        seen_suggested_metas.append(suggested_m)

                    rewrites.append(OnPageRewrite(
                        url=url,
                        current_title=t if t else None,
                        suggested_title=suggested_t,
                        current_meta=m if m else None,
                        suggested_meta=suggested_m,
                        status="needs human review"
                    ))
                    if len(rewrites) >= 25:
                        break

        summary = (
            f"Content Agent produced {len(briefs)} targeted content briefs, {len(rewrites)} on-page title/meta rewrites, "
            f"and {len(internal_links)} deterministic internal linking recommendations. All briefs cite empirical Search Console queries."
        )

        return ContentAgentReport(
            summary=summary,
            briefs=briefs,
            rewrites=rewrites,
            internal_links=internal_links
        )

    @classmethod
    async def _run_with_single_model(
        cls,
        verified_research: List[ResearchOpportunity],
        crawl_pages: List[Dict[str, Any]],
        internal_links: List[InternalLinkSuggestion],
        research_snapshot: Dict[str, Any],
        competitor_pages: List[Dict[str, Any]],
        model_name: str
    ) -> Tuple[ContentAgentReport, float, int, int]:
        real_questions = [q["query"] for q in research_snapshot.get("question_queries", []) if q.get("query")]

        inputs = {
            "opportunities": [o.model_dump() for o in verified_research[:5]],
            "available_gsc_questions": real_questions[:10],
            "candidate_pages_for_rewrites": [
                {"url": p["url"], "title": p.get("title"), "meta_desc": p.get("meta_desc"), "h1": p.get("h1")}
                for p in crawl_pages if p.get("status_code") == 200 and (not p.get("title") or len(p.get("title", "")) > 60 or not p.get("meta_desc"))
            ][:5],
            "internal_links_candidates": [l.model_dump() for l in internal_links[:6]]
        }

        prompt = f"""
        You are an elite SEO Content Agent. Generate content briefs and on-page rewrites.
        Rules:
        - NEVER invent search volume, keyword difficulty, or traffic numbers.
        - suggested_title MUST be <= 60 characters.
        - suggested_meta MUST be <= 155 characters.
        - questions_to_answer MUST be taken ONLY from available_gsc_questions.
        - For rewrites, current_title and current_meta MUST match the input page exactly.
        - PRESERVE KEY SERVICE TERMS & TARGET MARKETS: Rewrites MUST preserve any target markets/locations (e.g. Pakistan, UK, USA, UAE) and primary service terms (e.g. Next.js, E-commerce, UI/UX, AI search optimization) found in the page's current meta description. Never silently drop them or replace them with generic filler words!
        - NEVER replace a country name with an abbreviation (keep "Pakistan", NEVER "PK").
        - NEVER drop the word "Agency" from titles if present in current title or branding.
        - Do not write full articles. Briefs and rewrites only.

        Inputs:
        {json.dumps(inputs, indent=2)}

        Return JSON matching this schema:
        {{
          "summary": "3-5 sentences content strategy summary",
          "briefs": [
            {{
              "target_cluster": "cluster name",
              "intent": "informational|commercial|transactional|navigational",
              "suggested_title": "title under 60 chars",
              "suggested_meta": "meta description under 155 chars",
              "h1": "clear H1 header",
              "outline": ["H2 section 1", "H2 section 2"],
              "questions_to_answer": ["exact question from available_gsc_questions"],
              "schema_suggestion": "Article|Product|FAQPage",
              "internal_links": ["https://..."],
              "competitor_notes": "optional note",
              "notes": "strategy notes"
            }}
          ],
          "rewrites": [
            {{
              "url": "https://...",
              "current_title": "exact title or null",
              "suggested_title": "title under 60 chars",
              "current_meta": "exact meta or null",
              "suggested_meta": "meta under 155 chars"
            }}
          ]
        }}
        """

        base_delays = [2.0, 5.0, 15.0, 30.0]
        max_attempts = len(base_delays)
        last_error = ""

        async with httpx.AsyncClient() as client:
            for attempt_idx, base_delay in enumerate(base_delays, start=1):
                try:
                    resp = await client.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={settings.GEMINI_API_KEY}",
                        json={
                            "contents": [{"parts": [{"text": prompt}]}],
                            "generationConfig": {"response_mime_type": "application/json"}
                        },
                        timeout=45.0
                    )
                    if resp.status_code == 200:
                        res_json = resp.json()
                        usage = res_json.get("usageMetadata", {})
                        p_tokens = usage.get("promptTokenCount", 0)
                        c_tokens = usage.get("candidatesTokenCount", 0)
                        cost = (p_tokens * 0.000000075) + (c_tokens * 0.00000030)

                        raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
                        parsed = json.loads(raw_text)

                        # Enforce rewrite rules (no change needed, preserve service terms, near-duplicate check)
                        title_counts = Counter(p.get("title", "").strip().lower() for p in crawl_pages if p.get("title"))
                        meta_counts = Counter(p.get("meta_desc", "").strip().lower() for p in crawl_pages if p.get("meta_desc"))
                        seen_metas: List[str] = []
                        for rw in parsed.get("rewrites", []):
                            rw["status"] = "needs human review"
                            curr_t = rw.get("current_title") or ""
                            curr_m = rw.get("current_meta") or ""
                            sugg_t = rw.get("suggested_title") or ""
                            sugg_m = rw.get("suggested_meta") or ""

                            is_title_dup = bool(curr_t and title_counts[curr_t.strip().lower()] > 1)
                            is_meta_dup = bool(curr_m and meta_counts[curr_m.strip().lower()] > 1)

                            # If current title is fine (30-60 chars) or suggested is no-op, AND not duplicate
                            if not is_title_dup and ((curr_t and 30 <= len(curr_t) <= 60) or (curr_t and sugg_t and difflib.SequenceMatcher(None, curr_t.lower(), sugg_t.lower()).ratio() > 0.90)):
                                rw["suggested_title"] = "no change needed"
                            else:
                                if rw.get("suggested_title") == "no change needed" and is_title_dup:
                                    rw["suggested_title"] = rewrite_natural_title(curr_t, "Expert Solutions", rw.get("url", ""))
                                elif re.search(r"(?:agency|services|portfolio|calculator)\s+pakistan$", rw.get("suggested_title", ""), flags=re.IGNORECASE):
                                    rw["suggested_title"] = rewrite_natural_title(curr_t, "Expert Solutions", rw.get("url", ""))
                                rw["suggested_title"] = fix_term_capitalization(rw["suggested_title"])
                                # Enforce: Never drop the word "Agency" from titles
                                if curr_t and "agency" in curr_t.lower() and "agency" not in rw["suggested_title"].lower():
                                    if len(rw["suggested_title"]) + 9 <= 60:
                                        rw["suggested_title"] = rw["suggested_title"] + " Agency"
                                    elif len(rw["suggested_title"]) + 9 > 60:
                                        rw["suggested_title"] = rw["suggested_title"][:50].rsplit(" ", 1)[0] + " | Agency"
                                rw["suggested_title"] = re.sub(r"\bPK\b", "Pakistan", rw["suggested_title"], flags=re.IGNORECASE)

                            # If current meta is fine (70-160 chars) or suggested is no-op, AND not duplicate
                            if not is_meta_dup and ((curr_m and 70 <= len(curr_m) <= 160) or (curr_m and sugg_m and difflib.SequenceMatcher(None, curr_m.lower(), sugg_m.lower()).ratio() > 0.90)):
                                rw["suggested_meta"] = "no change needed"
                            else:
                                if rw.get("suggested_meta") == "no change needed" and is_meta_dup:
                                    url_tail = rw.get("url", "").rstrip("/").split("/")[-1].replace("-", " ").title() or "Services"
                                    brand_cur = extract_brand_from_page(rw.get("url", ""), "", "")
                                    rw["suggested_meta"] = f"Discover {url_tail} solutions from {brand_cur}. Professional web development, e-commerce, and tailored digital strategy."
                                sugg_m = rw.get("suggested_meta") or ""
                                # Keep "SEO-Friendly" if page says so
                                if "seo-friendly" in curr_m.lower() and "seo-friendly" not in sugg_m.lower():
                                    sugg_m = sugg_m.replace("SEO", "SEO-Friendly").replace("seo", "SEO-Friendly")

                                # Keep "AI search optimization" if page says so
                                if "ai search optimization" in curr_m.lower() and "ai search optimization" not in sugg_m.lower():
                                    sugg_m = sugg_m.rstrip(". ") + ", featuring AI search optimization."

                                # Never replace a country name with an abbreviation (keep Pakistan, never PK)
                                sugg_m = re.sub(r"\bPK\b", "Pakistan", sugg_m, flags=re.IGNORECASE)
                                sugg_m = fix_term_capitalization(sugg_m)
                                rw["suggested_meta"] = sugg_m[:155]

                                # Near-duplicate check (similarity above 0.60)
                                for prev_m in seen_metas:
                                    if difflib.SequenceMatcher(None, sugg_m.lower(), prev_m.lower()).ratio() > 0.60:
                                        # Differentiate meta description
                                        url_tail = rw.get("url", "").split("://")[-1].split("/")[-1].replace("-", " ").title()
                                        brand_cur = extract_brand_from_page(rw.get("url", ""), "", "")
                                        sugg_m = f"Discover {url_tail} solutions from {brand_cur}. Specialized digital development and tailored web strategy."
                                        sugg_m = fix_term_capitalization(sugg_m)
                                        rw["suggested_meta"] = sugg_m[:155]
                                        break
                                seen_metas.append(rw["suggested_meta"])

                        parsed["internal_links"] = [l.model_dump() for l in internal_links]
                        return ContentAgentReport.model_validate(parsed), round(cost, 6), p_tokens, c_tokens

                    error_snippet = resp.text[:200]
                    last_error = f"Gemini API HTTP {resp.status_code}: {error_snippet}"

                    if resp.status_code in (429, 503) and attempt_idx < max_attempts:
                        jitter = random.uniform(0.1, 1.0)
                        wait_time = base_delay + jitter
                        print(f"[{model_name}] HTTP {resp.status_code} in ContentAgent. Retrying in {wait_time:.1f}s...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        raise Exception(last_error)

                except (httpx.TimeoutException, httpx.NetworkError) as net_err:
                    last_error = f"Gemini connection error: {type(net_err).__name__} - {net_err}"
                    if attempt_idx < max_attempts:
                        jitter = random.uniform(0.1, 1.0)
                        wait_time = base_delay + jitter
                        print(f"[{model_name}] Network error in ContentAgent. Retrying in {wait_time:.1f}s...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        raise Exception(last_error)

        raise Exception(last_error or f"[{model_name}] Retries exhausted in ContentAgent.")
