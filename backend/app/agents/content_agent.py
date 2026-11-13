import re
import json
import asyncio
import difflib
import random
import httpx
from urllib.parse import urlparse
from typing import List, Dict, Any, Tuple, Optional, Set
from collections import defaultdict, Counter
from app.core.config import settings
from app.core.classification import classify_page_type
from app.models.agent_schemas import (
    ResearchOpportunity, ContentBrief, OnPageRewrite,
    InternalLinkSuggestion, ContentAgentReport
)

GENERIC_LINK_TERMS = {
    "digital", "services", "service", "business", "agency", "solutions",
    "solution", "company", "web", "online", "website", "websites", "home", "contact",
    "about", "expert", "experts", "work", "page", "top", "best", "read",
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
    "ai search", "ai search optimization", "custom websites", "software development",
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

def rewrite_natural_meta(current_m: str, h1: str, curr_markets: set, curr_services: set, url: str) -> str:
    """Builds an elegant, natural English sentence preserving all service and market terms,
    strictly capping length to 155 chars, avoiding keyword stuffing, and enforcing correct capitalization.
    """
    m_lower = current_m.lower()
    has_ai_opt = "ai search optimization" in m_lower
    has_nextjs = "next.js" in m_lower or "nextjs" in m_lower
    has_ecom = "e-commerce" in m_lower or "ecommerce" in m_lower
    has_uiux = "ui/ux" in m_lower
    has_pakistan = "pakistan" in m_lower
    has_intl = any(loc in m_lower for loc in ["uk", "usa", "uae"])

    # High-fidelity natural rewrite for homepage or comprehensive service pages:
    if has_ai_opt and (has_nextjs or has_ecom) and (has_pakistan or has_intl):
        cand = "WebSpire is Pakistan's premier web agency for custom Next.js websites, e-commerce, UI/UX, and AI search optimization across Pakistan, UK, USA & UAE."
        if len(cand) <= 155:
            return fix_term_capitalization(cand)

    # General natural sentence builder
    services_list = []
    if has_nextjs: services_list.append("Next.js websites")
    if has_ecom: services_list.append("e-commerce")
    if has_uiux: services_list.append("UI/UX design")
    if has_ai_opt: services_list.append("AI search optimization")
    
    if not services_list and curr_services:
        for s in sorted(list(curr_services)):
            s_fixed = fix_term_capitalization(s)
            if s_fixed not in services_list:
                services_list.append(s_fixed)
                
    services_phrase = ", ".join(services_list[:3]) if services_list else (h1 or "custom web solutions")
    if len(services_list) >= 4:
        services_phrase = f"{', '.join(services_list[:3])}, and {services_list[3]}"
        
    markets_phrase = ""
    if has_pakistan and has_intl:
        markets_phrase = " in Pakistan, UK, USA & UAE"
    elif curr_markets:
        locs = [m_loc.upper() if len(m_loc) <= 3 else m_loc.title() for m_loc in sorted(list(curr_markets))[:3]]
        markets_phrase = f" across {', '.join(locs)}"

    cand = f"WebSpire engineering custom {services_phrase}{markets_phrase} with verified digital growth."
    cand = fix_term_capitalization(cand)
    if len(cand) > 155:
        cand = cand[:155].rsplit(" ", 1)[0].rstrip(" ,.") + "."
    return cand

def rewrite_natural_title(current_t: str, h1: str, url: str) -> str:
    """Builds a natural English phrase title:
    - Strictly <= 60 characters
    - Never appends unnatural keyword tags like '... Agency Pakistan'
    - Preserves country 'Pakistan' where appropriate, never 'PK'
    - Preserves 'Agency' if present in existing branding
    - Uses clean delimiters (| or -)
    """
    path = urlparse(url).path.strip("/")
    url_slug = path.split("/")[-1].lower() if path else ""

    # Specific natural titles for core duplicate routes
    if url_slug == "portfolio":
        return "Portfolio & Case Studies | WebSpire Agency"
    if url_slug == "calculator":
        return "Project Cost Calculator | WebSpire Agency"
    if url_slug == "track":
        return "Track Project Milestones | WebSpire Delivery Portal"
    if url_slug == "services":
        return "Our Services | WebSpire Digital Agency"
    if not path or path == "":
        return "WebSpire | Pakistan's Trusted Digital & Web Agency"

    if not current_t:
        cand = f"{h1.title()} | WebSpire Agency" if len(h1) + 18 <= 60 else f"{h1.title()} | WebSpire"
        return cand[:60]

    has_agency = "agency" in current_t.lower()

    segs = [s.strip() for s in re.split(r"[|–—]", current_t) if s.strip()]
    unique_segs = []
    seen = set()
    for s in segs:
        s_norm = s.lower()
        if s_norm not in seen:
            unique_segs.append(s)
            seen.add(s_norm)

    if len(unique_segs) >= 2:
        cand = f"{unique_segs[0]} | {unique_segs[1]}"
        if len(cand) <= 60:
            if has_agency and "agency" not in cand.lower() and len(f"{cand} Agency") <= 60:
                cand = f"{cand} Agency"
            return fix_term_capitalization(re.sub(r"\bPK\b", "Pakistan", cand, flags=re.IGNORECASE))

    first_seg = unique_segs[0] if unique_segs else h1.title()
    if "webspire" not in first_seg.lower():
        cand = f"{first_seg} | WebSpire Agency" if len(first_seg) + 18 <= 60 else f"{first_seg} | WebSpire"
    else:
        cand = first_seg

    if len(cand) > 60:
        cand = cand[:60].rsplit(" ", 1)[0].rstrip(" |-–—")
    return fix_term_capitalization(re.sub(r"\bPK\b", "Pakistan", cand, flags=re.IGNORECASE))

def extract_candidate_anchor(text: str, max_words: int = 6) -> Optional[str]:
    """Extract candidate anchor:
    - If input has 6 words or fewer, use it in full (after stripping brand suffixes).
    - If more than 6 words, extract a coherent noun phrase (first clause / 3-5 words),
      never cutting a sentence mid-way and never ending in a stopword.
    """
    if not text:
        return None
    # Strip site brand suffixes (e.g. | WebSpire Agency, - WebSpire)
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
    
    # Existing links lookup set: (source_norm, target_norm)
    existing_links = set()
    for l in crawl_links:
        src = l.get("source_url", "").rstrip("/")
        tgt = l.get("target_url", "").rstrip("/")
        if src and tgt:
            existing_links.add((src, tgt))

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
            if src_url == tgt_url:
                continue
            if (src_url, tgt_url) in existing_links:
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
                    suggested_meta=f"Explore verified solutions, strategies, and key insights regarding {term}. Learn how to optimize results."[:155],
                    h1=f"Ultimate Guide to {term.title()}",
                    outline=[
                        f"Understanding {term.title()}",
                        f"Key Benefits and Best Practices",
                        f"Common Mistakes to Avoid",
                        f"Strategic Implementation Plan"
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

        # On-Page Rewrites for pages with missing or long title/meta or duplicates
        for p in crawl_pages:
            if p.get("status_code") == 200:
                t = p.get("title") or ""
                m = p.get("meta_desc") or ""
                url = p.get("url", "")
                
                is_title_duplicate = bool(t and title_counts[t.strip().lower()] > 1)
                is_meta_duplicate = bool(m and meta_counts[m.strip().lower()] > 1)

                is_title_fine = bool(t and 30 <= len(t) <= 60 and not is_title_duplicate)
                is_meta_fine = bool(m and 70 <= len(m) <= 160 and not is_meta_duplicate)

                needs_title_rewrite = not is_title_fine
                needs_meta_rewrite = not is_meta_fine

                suggested_t = "no change needed" if is_title_fine else None
                suggested_m = "no change needed" if is_meta_fine else None

                if needs_title_rewrite or needs_meta_rewrite:
                    h1 = p.get("h1") or "Expert Solutions"
                    curr_markets, curr_services = extract_preserved_entities(m)

                    if not is_title_fine:
                        suggested_t = rewrite_natural_title(t, h1, url)

                    if not is_meta_fine:
                        base_m = rewrite_natural_meta(m, h1, curr_markets, curr_services, url)
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
                    if len(rewrites) >= 5:
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
                                        rw["suggested_title"] = rw["suggested_title"].replace("WebSpire", "WebSpire Agency")
                                    elif len(rw["suggested_title"]) + 9 > 60:
                                        rw["suggested_title"] = rw["suggested_title"][:50].rsplit(" ", 1)[0] + " | Agency"
                                rw["suggested_title"] = re.sub(r"\bPK\b", "Pakistan", rw["suggested_title"], flags=re.IGNORECASE)

                            # If current meta is fine (70-160 chars) or suggested is no-op, AND not duplicate
                            if not is_meta_dup and ((curr_m and 70 <= len(curr_m) <= 160) or (curr_m and sugg_m and difflib.SequenceMatcher(None, curr_m.lower(), sugg_m.lower()).ratio() > 0.90)):
                                rw["suggested_meta"] = "no change needed"
                            else:
                                if rw.get("suggested_meta") == "no change needed" and is_meta_dup:
                                    url_tail = rw.get("url", "").rstrip("/").split("/")[-1].replace("-", " ").title() or "Services"
                                    rw["suggested_meta"] = f"Discover {url_tail} solutions from WebSpire. Custom Next.js web development, e-commerce, and digital strategy for Pakistan, UK, USA & UAE."
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
                                        sugg_m = f"Discover {url_tail} solutions from WebSpire. Specialized digital development and tailored web strategy."
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
