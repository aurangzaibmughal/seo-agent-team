from typing import List, Dict, Any, Optional
from collections import defaultdict
import difflib
import re
from urllib.parse import urlparse
from app.core.classification import classify_page_type, is_admin_page
from app.crawler.url_utils import canonical_url_key, urls_compare_equal

PLACEHOLDER_PATTERNS = [
    r"it service wordpress theme",
    r"just another wordpress site",
    r"lorem ipsum",
    r"default description",
    r"your tagline here",
    r"sample page",
    r"coming soon",
    r"under construction",
    r"my wordpress blog",
    r"elementor wordpress theme",
    r"site description",
    r"insert description here",
]

def infer_brand_name(crawl_pages: List[Dict[str, Any]], brand_hint: Optional[str] = None) -> Optional[str]:
    """Infers the brand or project name from titles or URL domain."""
    if brand_hint and brand_hint.strip():
        return brand_hint.strip()

    suffix_counts: Dict[str, int] = defaultdict(int)
    for p in crawl_pages:
        title = p.get("title") or ""
        parts = re.split(r"[|\-—–]", title)
        if len(parts) > 1:
            last_part = parts[-1].strip()
            if len(last_part) >= 2:
                suffix_counts[last_part] += 1

    if suffix_counts:
        top_suffix, count = max(suffix_counts.items(), key=lambda x: x[1])
        if count >= 2:
            return top_suffix

    for p in crawl_pages:
        u = p.get("url") or ""
        parsed = urlparse(u)
        if parsed.netloc:
            domain_part = parsed.netloc.split(".")[0]
            raw_token = domain_part.split("-")[0]
            if len(raw_token) >= 3:
                return raw_token
    return None

def find_closest_slug(target_url: str, valid_urls: List[str]) -> Optional[str]:
    """Finds the closest existing crawled 200 URL for a broken 4xx URL using slug similarity."""
    t_parsed = urlparse(target_url)
    t_path = t_parsed.path.strip("/")
    if not t_path:
        return None
    t_slug = t_path.split("/")[-1].lower()
    t_slug_clean = t_slug.replace("-", "").replace("_", "")

    best_url = None
    best_score = 0.0

    for u in valid_urls:
        u_parsed = urlparse(u)
        u_path = u_parsed.path.strip("/")
        if not u_path:
            continue
        u_slug = u_path.split("/")[-1].lower()
        u_slug_clean = u_slug.replace("-", "").replace("_", "")

        score_clean = difflib.SequenceMatcher(None, t_slug_clean, u_slug_clean).ratio()
        score_raw = difflib.SequenceMatcher(None, t_slug, u_slug).ratio()
        score = max(score_clean, score_raw)
        if t_slug_clean == u_slug_clean:
            score = 1.0

        if score > best_score:
            best_score = score
            best_url = u_parsed.path or "/"

    if best_url and best_score >= 0.55:
        return best_url
    return None

def detect_issues_from_data(
    crawl_pages: List[Dict[str, Any]],
    crawl_links: List[Dict[str, Any]],
    psi_results: List[Dict[str, Any]],
    brand_name: Optional[str] = None,
    sitemap_entries: Optional[List[Dict[str, Any]]] = None,
    sitemap_urls: Optional[Any] = None,
    sitemap_status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Deterministic, rule-based SEO issue detector (Plain Python, No LLM)."""
    candidates: List[Dict[str, Any]] = []
    resolved_brand = infer_brand_name(crawl_pages, brand_name)

    # Map inlinks count
    inlink_map: Dict[str, int] = defaultdict(int)
    for link in crawl_links:
        target = link.get("target_url", "").rstrip("/")
        inlink_map[target] += 1

    # Group pages by title and meta_description for duplicates
    title_to_pages: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    meta_to_pages: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    # Collect all 200 OK URLs for closest slug matching
    pages_200_urls = [p.get("url") for p in crawl_pages if p.get("status_code") == 200 and p.get("url")]

    # 1. Crawl Page Rules
    for page in crawl_pages:
        pid = page.get("id")
        url = page.get("url")
        status = page.get("status_code", 0)
        title = page.get("title")
        meta_desc = page.get("meta_desc")
        h1 = page.get("h1")
        canonical = page.get("canonical")
        indexable = page.get("indexable", True)
        index_status = page.get("indexability_status", "indexable")

        # Broken links (4xx) and Server errors (5xx)
        if 400 <= status < 500:
            closest = find_closest_slug(url, pages_200_urls) if url else None
            cand = {
                "type": "broken_link_4xx",
                "urls": [url],
                "evidence": [{"table": "crawl_pages", "id": pid, "field": "status_code", "value": status}],
            }
            if closest:
                cand["did_you_mean"] = closest
            candidates.append(cand)
        elif status >= 500:
            candidates.append({
                "type": "server_error_5xx",
                "urls": [url],
                "evidence": [{"table": "crawl_pages", "id": pid, "field": "status_code", "value": status}],
            })

        # Redirect chain / status
        if 300 <= status < 400:
            candidates.append({
                "type": "redirect_chain",
                "urls": [url],
                "evidence": [{"table": "crawl_pages", "id": pid, "field": "status_code", "value": status}],
            })

        # CRITICAL RULE: On-page checks ONLY run for 200 OK pages!
        if status == 200:
            # Missing Title
            if not title or len(title.strip()) == 0:
                candidates.append({
                    "type": "missing_title",
                    "urls": [url],
                    "evidence": [{"table": "crawl_pages", "id": pid, "field": "title", "value": None}],
                })
            else:
                title_len = len(title.strip())
                if 61 <= title_len <= 65:
                    candidates.append({
                        "type": "title_borderline",
                        "urls": [url],
                        "evidence": [{"table": "crawl_pages", "id": pid, "field": "title", "value": title}],
                    })
                elif title_len > 65:
                    candidates.append({
                        "type": "title_too_long",
                        "urls": [url],
                        "evidence": [{"table": "crawl_pages", "id": pid, "field": "title", "value": title}],
                    })
                elif title_len < 30:
                    candidates.append({
                        "type": "title_too_short",
                        "urls": [url],
                        "evidence": [{"table": "crawl_pages", "id": pid, "field": "title", "value": title}],
                    })
                title_to_pages[title.strip().lower()].append(page)

                # Brand repeated in title check
                if resolved_brand and title:
                    pattern = r"\b" + re.escape(resolved_brand) + r"\b"
                    b_matches = re.findall(pattern, title, re.IGNORECASE)
                    if len(b_matches) >= 2:
                        candidates.append({
                            "type": "brand_repeated_in_title",
                            "urls": [url],
                            "brand": resolved_brand,
                            "occurrences": len(b_matches),
                            "evidence": [{"table": "crawl_pages", "id": pid, "field": "title", "value": title}],
                        })

            # Meta Description Rules (A-03: Placeholder, Short, Long, Missing)
            clean_meta = meta_desc.strip() if meta_desc else ""
            if not clean_meta:
                candidates.append({
                    "type": "missing_meta_description",
                    "urls": [url],
                    "evidence": [{"table": "crawl_pages", "id": pid, "field": "meta_desc", "value": None}],
                })
            else:
                clean_meta_lower = clean_meta.lower()
                is_placeholder = any(re.search(pat, clean_meta_lower) for pat in PLACEHOLDER_PATTERNS)

                # Heuristic relevance check
                if not is_placeholder and len(clean_meta.split()) >= 3:
                    page_terms = set(re.findall(r"[a-z0-9]+", f"{page.get('title', '')} {page.get('h1', '')}".lower()))
                    meta_terms = set(re.findall(r"[a-z0-9]+", clean_meta_lower)) - {"the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "with", "of", "is"}
                    if page_terms and meta_terms and not (meta_terms & page_terms) and len(clean_meta) < 60:
                        is_placeholder = True

                if is_placeholder:
                    candidates.append({
                        "type": "meta_description_placeholder",
                        "urls": [url],
                        "severity": "high",
                        "impact": f"Page displays generic theme or placeholder text ('{clean_meta}') instead of business copy in SERPs.",
                        "fix_hint": "Replace theme placeholder with a tailored, business-relevant meta description (120–155 chars).",
                        "evidence": [{"table": "crawl_pages", "id": pid, "field": "meta_desc", "value": clean_meta}],
                    })

                meta_len = len(clean_meta)
                if meta_len < 70:
                    candidates.append({
                        "type": "meta_description_too_short",
                        "urls": [url],
                        "severity": "medium",
                        "impact": f"Meta description is only {meta_len} characters (recommended: 120–155). Short descriptions fail to capture SERP CTR.",
                        "fix_hint": "Expand meta description to 120–155 characters with service details and a clear call to action.",
                        "evidence": [{"table": "crawl_pages", "id": pid, "field": "meta_desc", "value": f"{meta_len} chars: {clean_meta}"}],
                    })
                elif 161 <= meta_len <= 170:
                    candidates.append({
                        "type": "meta_borderline",
                        "urls": [url],
                        "evidence": [{"table": "crawl_pages", "id": pid, "field": "meta_desc", "value": clean_meta}],
                    })
                elif meta_len > 170:
                    candidates.append({
                        "type": "meta_too_long",
                        "urls": [url],
                        "evidence": [{"table": "crawl_pages", "id": pid, "field": "meta_desc", "value": clean_meta}],
                    })
                meta_to_pages[clean_meta_lower].append(page)

            # Missing H1
            if not h1 or len(h1.strip()) == 0:
                candidates.append({
                    "type": "missing_h1",
                    "urls": [url],
                    "evidence": [{"table": "crawl_pages", "id": pid, "field": "h1", "value": None}],
                })

            # Canonical checks
            if not canonical:
                candidates.append({
                    "type": "missing_canonical",
                    "urls": [url],
                    "evidence": [{"table": "crawl_pages", "id": pid, "field": "canonical", "value": None}],
                })
            elif index_status == "canonical_to_other":
                candidates.append({
                    "type": "canonical_to_other",
                    "urls": [url],
                    "evidence": [{"table": "crawl_pages", "id": pid, "field": "canonical", "value": canonical}],
                })

            # Noindex page: Only content pages should be flagged!
            # Utility pages (login, signup, admin, cart, account) SHOULD be noindexed (positive practice).
            if index_status in ("noindex_meta", "noindex_header"):
                if classify_page_type(url) == "content":
                    candidates.append({
                        "type": "noindex_page",
                        "urls": [url],
                        "evidence": [{"table": "crawl_pages", "id": pid, "field": "indexability_status", "value": index_status}],
                    })
            else:
                # Page is indexable: Flag private/admin pages that SHOULD NOT be indexable
                if classify_page_type(url) == "utility" and indexable is not False:
                    if is_admin_page(url):
                        candidates.append({
                            "type": "indexable_admin_page",
                            "urls": [url],
                            "evidence": [{"table": "crawl_pages", "id": pid, "field": "indexability_status", "value": index_status}],
                        })
                    else:
                        candidates.append({
                            "type": "indexable_private_page",
                            "urls": [url],
                            "evidence": [{"table": "crawl_pages", "id": pid, "field": "indexability_status", "value": index_status}],
                        })

            # Orphan page (crawled with 0 inlinks, excluding target start page if needed)
            norm_url = url.rstrip("/")
            if inlink_map.get(norm_url, 0) == 0 and page.get("inlinks_count", 0) == 0:
                candidates.append({
                    "type": "orphan_page",
                    "urls": [url],
                    "evidence": [{"table": "crawl_pages", "id": pid, "field": "inlinks_count", "value": 0}],
                })

    # Canonical Mass-Misconfiguration Rule
    total_200_pages = [p for p in crawl_pages if p.get("status_code") == 200]
    canonical_mismatch_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    all_mismatched = []

    for p in total_200_pages:
        c_val = p.get("canonical")
        u_val = p.get("url", "")
        if c_val and c_val.rstrip("/") != u_val.rstrip("/"):
            target_norm = c_val.rstrip("/")
            canonical_mismatch_groups[target_norm].append(p)
            all_mismatched.append(p)

    if total_200_pages and (len(all_mismatched) / len(total_200_pages)) >= 0.30:
        # Find dominant target
        if canonical_mismatch_groups:
            dominant_target, dom_pages = max(canonical_mismatch_groups.items(), key=lambda x: len(x[1]))
            if len(dom_pages) / len(all_mismatched) >= 0.50:
                candidates.append({
                    "type": "canonical_mass_misconfiguration",
                    "urls": [p["url"] for p in dom_pages],
                    "target_url": dominant_target,
                    "target_canonical": dominant_target,
                    "evidence": [{"table": "crawl_pages", "id": p["id"], "field": "canonical", "value": p.get("canonical")} for p in dom_pages],
                })

    # Duplicate Titles (A-05: Grouped with exact shared text)
    for t_text, plist in title_to_pages.items():
        if len(plist) > 1:
            candidates.append({
                "type": "duplicate_title",
                "urls": [p["url"] for p in plist],
                "group_key": t_text,
                "evidence": [{"table": "crawl_pages", "id": p.get("id"), "field": "title", "value": p.get("title")} for p in plist],
            })

    # Duplicate Meta Descriptions (A-05: Grouped with exact shared text)
    for m_text, plist in meta_to_pages.items():
        if len(plist) > 1:
            candidates.append({
                "type": "duplicate_meta_description",
                "urls": [p["url"] for p in plist],
                "group_key": m_text,
                "evidence": [{"table": "crawl_pages", "id": p.get("id"), "field": "meta_desc", "value": p.get("meta_desc")} for p in plist],
            })

    # 2. PageSpeed Insights Rules
    speed_issues_found = False
    for psi in psi_results:
        psi_id = psi.get("id")
        p_url = psi.get("url")
        score = psi.get("performance_score")
        lcp = psi.get("lcp_ms")
        cls_val = psi.get("cls")

        if score is not None and score < 50:
            speed_issues_found = True
            candidates.append({
                "type": "low_performance_score",
                "urls": [p_url],
                "evidence": [{"table": "psi_results", "id": psi_id, "field": "performance_score", "value": score}],
            })

        # LCP rules (A-11: 3-band)
        if lcp is not None:
            if lcp > 4000:
                speed_issues_found = True
                candidates.append({
                    "type": "slow_lcp",
                    "urls": [p_url],
                    "severity": "high",
                    "impact": f"Largest Contentful Paint is {lcp/1000:.1f}s (poor, Google threshold > 4.0s), severely penalizing mobile organic rankings.",
                    "fix_hint": "Preload hero images, remove autoplaying video above fold, and optimize server TTFB.",
                    "evidence": [{"table": "psi_results", "id": psi_id, "field": "lcp_ms", "value": lcp}],
                })
            elif lcp > 2500:
                speed_issues_found = True
                candidates.append({
                    "type": "lcp_needs_improvement",
                    "urls": [p_url],
                    "severity": "medium",
                    "impact": f"Largest Contentful Paint is {lcp/1000:.1f}s (needs improvement, range 2.5s–4.0s).",
                    "fix_hint": "Compress images to WebP/AVIF and optimize critical CSS.",
                    "evidence": [{"table": "psi_results", "id": psi_id, "field": "lcp_ms", "value": lcp}],
                })

        # CLS rules (A-11: 3-band)
        if cls_val is not None:
            if cls_val > 0.25:
                speed_issues_found = True
                candidates.append({
                    "type": "poor_cls",
                    "urls": [p_url],
                    "severity": "high",
                    "impact": f"Cumulative Layout Shift is {cls_val} (poor, Google threshold > 0.25), causing severe visual instability.",
                    "fix_hint": "Add explicit width and height attributes to all images, sliders and embed containers.",
                    "evidence": [{"table": "psi_results", "id": psi_id, "field": "cls", "value": cls_val}],
                })
            elif cls_val > 0.10:
                speed_issues_found = True
                candidates.append({
                    "type": "cls_needs_improvement",
                    "urls": [p_url],
                    "severity": "low",
                    "impact": f"Cumulative Layout Shift is {cls_val} (needs improvement, range 0.10–0.25).",
                    "fix_hint": "Reserve aspect ratio space for dynamic widgets and web font loading.",
                    "evidence": [{"table": "psi_results", "id": psi_id, "field": "cls", "value": cls_val}],
                })

    if psi_results and not speed_issues_found:
        print("PSI ran, no speed issues found")

    # 3. Sitemap Comparison Rules
    if sitemap_entries:
        stale_entries = []
        for e in sitemap_entries:
            code = e.get("status_code", 0)
            if (isinstance(code, int) and (code >= 400 or code == 0)) or isinstance(code, str):
                stale_entries.append(e)

        if stale_entries:
            candidates.append({
                "type": "sitemap_lists_non_existent_url",
                "urls": [e["url"] for e in stale_entries],
                "severity": "high" if len(stale_entries) >= 5 else "medium",
                "stale_entries": stale_entries,
                "evidence": [
                    {
                        "table": "sitemap.xml",
                        "id": e["url"],
                        "field": "status_code",
                        "value": e.get("status_code", 404),
                    }
                    for e in stale_entries
                ],
            })

    # Rule 2: Sitemap Discovery, Unreadable and Missing Checks (A-02)
    if sitemap_status == "missing":
        candidates.append({
            "type": "sitemap_missing",
            "urls": [crawl_pages[0].get("url")] if crawl_pages else [],
            "severity": "medium",
            "impact": "Search engines cannot efficiently discover all indexable pages because no XML sitemap was found in robots.txt or standard paths.",
            "fix_hint": "Generate an XML sitemap and reference it in robots.txt via 'Sitemap: https://domain/sitemap.xml'.",
            "evidence": [{
                "table": "sitemap.xml",
                "id": "sitemap",
                "field": "status",
                "value": "missing"
            }]
        })
    elif sitemap_status == "unreadable":
        candidates.append({
            "type": "sitemap_unreadable",
            "urls": [crawl_pages[0].get("url")] if crawl_pages else [],
            "severity": "medium",
            "impact": "XML sitemap returned HTTP 200 but contains invalid or malformed XML syntax, preventing search engines from parsing it.",
            "fix_hint": "Validate XML syntax against the sitemaps.org schema and ensure all special characters in URLs are properly escaped.",
            "evidence": [{
                "table": "sitemap.xml",
                "id": "sitemap",
                "field": "status",
                "value": "unreadable"
            }]
        })
    else:
        # Sitemaps found -> perform safe diff using canonical_url_key
        known_sitemap_keys = set()
        if sitemap_entries:
            for e in sitemap_entries:
                u_val = e.get("url") or ""
                if u_val:
                    known_sitemap_keys.add(canonical_url_key(u_val))
        if sitemap_urls:
            for su in sitemap_urls:
                if su:
                    known_sitemap_keys.add(canonical_url_key(su))

        if known_sitemap_keys:
            missing_crawled_pages = []
            for p in crawl_pages:
                if p.get("status_code") != 200:
                    continue
                if not p.get("indexable"):
                    continue
                canonical = p.get("canonical")
                p_url = p.get("url", "")
                if canonical and not urls_compare_equal(canonical, p_url):
                    continue
                if canonical_url_key(p_url) not in known_sitemap_keys:
                    missing_crawled_pages.append(p)

            if missing_crawled_pages:
                candidates.append({
                    "type": "crawled_page_missing_from_sitemap",
                    "urls": [p["url"] for p in missing_crawled_pages],
                    "severity": "medium",
                    "evidence": [
                        {
                            "table": "crawl_pages",
                            "id": p.get("id"),
                            "field": "url",
                            "value": p.get("url"),
                        }
                        for p in missing_crawled_pages
                    ],
                })

    # Assign stable candidate IDs (C-001, C-002, ...)
    for idx, c in enumerate(candidates, start=1):
        if "id" not in c:
            c["id"] = f"C-{idx:03d}"

    return candidates
