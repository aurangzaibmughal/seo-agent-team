import re
from typing import List, Dict, Any, Set, Tuple
from collections import defaultdict

DEFAULT_INTENT_PATTERNS = {
    "informational": [r"\bhow\b", r"\bwhat\b", r"\bwhy\b", r"\bguide\b", r"\btutorial\b", r"\btips\b", r"\bexamples?\b", r"\blearn\b"],
    "commercial": [r"\bbest\b", r"\bvs\b", r"\breviews?\b", r"\bpricing\b", r"\bcost\b", r"\balternatives?\b", r"\btop\b", r"\bcomparison\b"],
    "transactional": [r"\bbuy\b", r"\bhire\b", r"\bservice\b", r"\bnear me\b", r"\bquote\b", r"\border\b", r"\bdownload\b", r"\bagency\b", r"\bconsultant\b"],
    "navigational": [r"\blogin\b", r"\bsignin\b", r"\bportal\b", r"\bofficial\b"]
}

QUESTION_WORDS = {"who", "what", "where", "when", "why", "how", "can", "does", "do", "is", "are", "which"}

def classify_intent(query: str, brand_name: str = "", patterns: Dict[str, List[str]] = None) -> str:
    patterns = patterns or DEFAULT_INTENT_PATTERNS
    q = query.lower().strip()
    if brand_name and brand_name.lower() in q:
        return "navigational"
    
    for intent, pat_list in patterns.items():
        for pat in pat_list:
            if re.search(pat, q):
                return intent
    return "informational"

def jaccard_similarity(tokens1: Set[str], tokens2: Set[str]) -> float:
    if not tokens1 or not tokens2:
        return 0.0
    return len(tokens1 & tokens2) / len(tokens1 | tokens2)

def compute_research_metrics(
    gsc_rows: List[Dict[str, Any]],
    crawl_pages: List[Dict[str, Any]],
    competitor_pages: List[Dict[str, Any]] = None,
    min_impressions: int = 5,
    brand_name: str = ""
) -> Dict[str, Any]:
    """Deterministic, empirical research metrics engine (no LLM, no invented numbers)."""
    competitor_pages = competitor_pages or []
    crawled_200 = [p for p in crawl_pages if p.get("status_code") == 200]
    
    # Pre-index crawled page text/titles
    page_by_url = {p["url"].rstrip("/"): p for p in crawled_200}
    all_site_titles_h1 = []
    for p in crawled_200:
        t = (p.get("title") or "").lower()
        h = (p.get("h1") or "").lower()
        all_site_titles_h1.append(f"{t} {h}")
    combined_site_titles_h1 = " ".join(all_site_titles_h1)

    # 1. Query-Page aggregation & Cannibalization
    query_to_pages: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in gsc_rows:
        q = r.get("query", "").strip()
        if q:
            query_to_pages[q].append(r)

    cannibalization_items: List[Dict[str, Any]] = []
    for q, p_rows in query_to_pages.items():
        if len(p_rows) >= 2:
            total_imp = sum(r.get("impressions", 0) for r in p_rows)
            # Both pages have at least 10% of total query impressions
            significant_pages = [r for r in p_rows if r.get("impressions", 0) >= max(3, total_imp * 0.10)]
            if len(significant_pages) >= 2:
                cannibalization_items.append({
                    "query": q,
                    "pages": [r.get("page") for r in significant_pages],
                    "competing_pages": [r.get("page") for r in significant_pages],
                    "total_impressions": total_imp,
                    "total_clicks": sum(r.get("clicks", 0) for r in significant_pages),
                    "urls_count": len(significant_pages)
                })

    # 2. Query Clustering (token overlap + landing page mapping)
    # Filter by minimum impressions threshold
    filtered_gsc = [r for r in gsc_rows if r.get("impressions", 0) >= min_impressions]
    
    clusters_dict: Dict[str, Dict[str, Any]] = {}
    for r in filtered_gsc:
        q = r.get("query", "").strip().lower()
        tokens = set(re.findall(r"\w+", q))
        page = r.get("page", "")

        matched_cluster_id = None
        for cid, cl in clusters_dict.items():
            head_tokens = set(re.findall(r"\w+", cl["head_term"].lower()))
            # Group if tokens overlap by Jaccard >= 0.40 or same landing page with overlap >= 0.25
            overlap = jaccard_similarity(tokens, head_tokens)
            if overlap >= 0.40 or (page in cl["landing_pages"] and overlap >= 0.25):
                matched_cluster_id = cid
                break

        if matched_cluster_id:
            cl = clusters_dict[matched_cluster_id]
            cl["member_queries"].append(r["query"])
            cl["total_clicks"] += r.get("clicks", 0)
            cl["total_impressions"] += r.get("impressions", 0)
            if page and page not in cl["landing_pages"]:
                cl["landing_pages"].append(page)
            # Update head term if higher impressions
            if r.get("impressions", 0) > cl["head_impressions"]:
                cl["head_term"] = r["query"]
                cl["head_impressions"] = r.get("impressions", 0)
        else:
            cid = f"CLUST-{len(clusters_dict) + 1:03d}"
            intent = classify_intent(r["query"], brand_name=brand_name)
            clusters_dict[cid] = {
                "id": cid,
                "head_term": r["query"],
                "head_impressions": r.get("impressions", 0),
                "intent": intent,
                "member_queries": [r["query"]],
                "total_clicks": r.get("clicks", 0),
                "total_impressions": r.get("impressions", 0),
                "avg_position": round(r.get("position", 0.0), 1),
                "landing_pages": [page] if page else []
            }

    clusters = sorted(clusters_dict.values(), key=lambda x: x["total_impressions"], reverse=True)

    # 3. Content Gaps
    # Clusters with real impressions where head term is NOT in any crawled page title or H1
    content_gaps = []
    for cl in clusters:
        head = cl["head_term"].lower()
        if head not in combined_site_titles_h1:
            content_gaps.append({
                "cluster_id": cl["id"],
                "head_term": cl["head_term"],
                "intent": cl["intent"],
                "impressions": cl["total_impressions"],
                "clicks": cl["total_clicks"],
                "landing_pages": cl["landing_pages"]
            })

    # 4. Mismatch
    # Cluster whose ranking landing page does not contain the head term in title, H1 or headings
    mismatch_items = []
    for cl in clusters:
        head = cl["head_term"].lower()
        for lp in cl["landing_pages"]:
            page = page_by_url.get(lp.rstrip("/"))
            if page:
                page_t = (page.get("title") or "").lower()
                page_h1 = (page.get("h1") or "").lower()
                headings_txt = " ".join(h.get("text", "").lower() for h in page.get("headings", []))
                if head not in page_t and head not in page_h1 and head not in headings_txt:
                    mismatch_items.append({
                        "cluster_id": cl["id"],
                        "head_term": cl["head_term"],
                        "page_url": lp,
                        "impressions": cl["total_impressions"],
                        "page_title": page.get("title"),
                        "reason": f"Ranking page does not contain cluster head term '{cl['head_term']}' in title or headings."
                    })

    # 5. Question Queries
    question_queries = []
    for r in gsc_rows:
        q = r.get("query", "").strip()
        words = set(re.findall(r"\w+", q.lower()))
        if words & QUESTION_WORDS:
            question_queries.append({
                "query": q,
                "clicks": r.get("clicks", 0),
                "impressions": r.get("impressions", 0),
                "position": round(r.get("position", 0.0), 1),
                "page": r.get("page", "")
            })
    question_queries = sorted(question_queries, key=lambda x: x["impressions"], reverse=True)

    # 6. Competitor On-Page Comparison
    competitor_comparison: Dict[str, Any] = {
        "topics_competitors_cover": [],
        "competitor_schema_types": [],
        "competitor_stats": []
    }
    
    if competitor_pages:
        comp_headings = defaultdict(set)
        comp_schemas = defaultdict(set)
        site_schemas = set()
        
        # Collect site headings and schemas
        site_headings_text = set()
        for p in crawled_200:
            for h in p.get("headings", []):
                site_headings_text.add(h.get("text", "").strip().lower())
        
        for cp in competitor_pages:
            dom = cp.get("competitor_domain", "")
            for h in cp.get("headings", []):
                h_text = h.get("text", "").strip()
                if h_text and h_text.lower() not in site_headings_text and len(h_text) > 5:
                    comp_headings[dom].add(h_text)
            for st in cp.get("schema_types", []):
                comp_schemas[dom].add(st)

        topics_diff = []
        for dom, h_set in comp_headings.items():
            for top in list(h_set)[:10]:
                topics_diff.append({"competitor": dom, "topic": top})

        competitor_comparison = {
            "disclaimer": "on-page comparison only — no traffic or backlink data",
            "topics_competitors_cover": topics_diff,
            "competitor_schema_types": [{"competitor": dom, "schemas": sorted(list(s))} for dom, s in comp_schemas.items()],
            "competitor_pages_crawled": len(competitor_pages)
        }

    return {
        "query_clusters": clusters,
        "content_gaps": content_gaps,
        "cannibalization": cannibalization_items,
        "mismatch": mismatch_items,
        "question_queries": question_queries,
        "competitor_comparison": competitor_comparison,
        "total_queries_analyzed": len(gsc_rows)
    }
