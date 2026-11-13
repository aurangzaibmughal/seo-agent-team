import os
import re
import json
import difflib
from urllib.parse import urlparse
from typing import List, Dict, Any, Tuple, Optional

from app.core.config import settings
from app.models.agent_schemas import (
    TechnicalIssue, StrategyTask, OnPageRewrite, InternalLinkSuggestion,
    GeneratedArtifact, CodeBundleReport
)
from app.code_generator.jsonld_builder import JsonLdBuilder, safe_jsonld_string
from app.code_generator.templates import CodeTemplateEngine
from app.code_generator.filepath_mapper import map_url_to_nextjs_path

class CodeGeneratorAgent:
    """SEO Code Generator Agent: Produces platform-specific, provenance-tracked SEO code and configuration files."""

    @classmethod
    async def run(
        cls,
        platform: str,
        platform_confidence: float,
        verified_tech_issues: List[TechnicalIssue],
        strategy_tasks: List[StrategyTask],
        crawl_pages: List[Dict[str, Any]],
        crawl_links: List[Dict[str, Any]],
        verified_rewrites: List[OnPageRewrite],
        internal_links: List[InternalLinkSuggestion],
        router_type: str = "app",
        nextjs_version: str = "15+",
        is_demo: bool = False
    ) -> Tuple[CodeBundleReport, str, float, Optional[str], Optional[str]]:
        """Returns (bundle_report, mode, cost_usd, failure_reason, model_used)."""
        artifacts: List[GeneratedArtifact] = []

        homepage = next((p for p in crawl_pages if p.get("url", "").rstrip("/") in (
            crawl_pages[0].get("url", "").rstrip("/") if crawl_pages else "",
            f"{urlparse(crawl_pages[0].get('url', '')).scheme}://{urlparse(crawl_pages[0].get('url', '')).netloc}" if crawl_pages else ""
        )), crawl_pages[0] if crawl_pages else {})

        base_url = f"{urlparse(homepage.get('url', 'https://example.com')).scheme}://{urlparse(homepage.get('url', 'https://example.com')).netloc}"
        brand_name = (homepage.get("title") or "WebSpire").split("|")[0].split("—")[0].split("–")[0].strip()

        # Map issues & tasks for provenance
        tech_map = {iss.type: iss for iss in verified_tech_issues}
        task_map = {t.title.lower(): t for t in strategy_tasks}

        def get_sources_for_issue_types(*issue_types: str) -> Tuple[List[str], List[str]]:
            i_ids, t_ids = [], []
            for it in issue_types:
                if it in tech_map:
                    i_ids.append(tech_map[it].id)
            for t in strategy_tasks:
                if any(ref.id in i_ids for ref in (t.source_refs or [])):
                    t_ids.append(t.id)
            return list(dict.fromkeys(i_ids)), list(dict.fromkeys(t_ids))

        # 1. Broken Links Redirects
        redirect_pairs = []
        broken_iss = tech_map.get("broken_link_4xx")
        pages_200_urls = [p["url"] for p in crawl_pages if p.get("status_code") == 200]

        if broken_iss:
            for b_url in broken_iss.urls:
                b_path = urlparse(b_url).path.rstrip("/")
                # "Did you mean" closest match
                matches = difflib.get_close_matches(b_url, pages_200_urls, n=1, cutoff=0.6)
                if matches:
                    t_url = matches[0]
                    t_path = urlparse(t_url).path.rstrip("/") or "/"
                    redirect_pairs.append({
                        "source_url": b_url,
                        "source_path": b_path,
                        "target_url": t_url,
                        "target_path": t_path
                    })

        redirect_i_ids, redirect_t_ids = get_sources_for_issue_types("broken_link_4xx", "broken_link")

        # 2. Sitemap items (Post-fix state: 200, indexable, canonical self or fixed by generated code)
        sitemap_items = []
        target_domain = urlparse(base_url).netloc.lower()
        seen_sitemap_urls = set()
        sitemap_included_now = []
        sitemap_included_after_fix = []

        for p in crawl_pages:
            u = p.get("url", "")
            u_parsed = urlparse(u)
            if u_parsed.netloc.lower() != target_domain:
                continue
            if p.get("status_code") != 200:
                continue
            canonical = p.get("canonical")
            is_canonical_other = bool(canonical and canonical.rstrip("/") != u.rstrip("/"))

            # In post-fix state: pages whose only problem is canonical_to_other (fixed by generated metadata)
            # are included in post-fix sitemap with 'assumes canonical fix applied' note
            is_indexable = bool(p.get("indexable"))
            if not is_indexable and is_canonical_other:
                robots_val = str(p.get("robots") or "").lower()
                if "noindex" not in robots_val:
                    is_indexable = True

            if not is_indexable:
                continue

            raw_date = p.get("last_modified") or p.get("date_published") or ""
            # Only add lastmod if a real date was found
            has_real_date = bool(re.search(r"\d{4}-\d{2}-\d{2}", str(raw_date)))
            clean_date = str(raw_date).strip() if has_real_date else None

            if u.rstrip("/") not in seen_sitemap_urls:
                seen_sitemap_urls.add(u.rstrip("/"))
                if is_canonical_other:
                    sitemap_included_after_fix.append(u)
                    sitemap_items.append({
                        "url": u,
                        "lastmod": clean_date,
                        "note": "Assumes canonical fix applied"
                    })
                else:
                    sitemap_included_now.append(u)
                    sitemap_items.append({
                        "url": u,
                        "lastmod": clean_date,
                    })

        # Provenance mapping restricted strictly to issue types produced by issue_rules.py
        sitemap_i_ids, sitemap_t_ids = get_sources_for_issue_types(
            "sitemap_lists_non_existent_url", "crawled_page_missing_from_sitemap", "orphan_page"
        )
        robots_i_ids, robots_t_ids = [], []
        org_schema, org_prov = JsonLdBuilder.build_organization_website(homepage, crawl_links)
        schema_i_ids, schema_t_ids = [], []

        # 4. Curated Links for llms.txt (cut strictly at word boundaries)
        from app.code_generator.templates import truncate_at_word_boundary
        curated_links = []
        for p in crawl_pages[:8]:
            if p.get("status_code") == 200 and p.get("indexable"):
                p_title = (p.get("title") or "Page").split("|")[0].split("—")[0].strip()
                p_raw_desc = p.get("meta_desc") or p.get("h1") or "Key resource and documentation."
                p_desc = truncate_at_word_boundary(p_raw_desc, 130)
                curated_links.append({
                    "title": p_title,
                    "url": p["url"],
                    "description": p_desc
                })

        site_summary = truncate_at_word_boundary(homepage.get("meta_desc") or homepage.get("h1") or "Enterprise digital agency and web engineering.", 200)

        # ================= BUILD ARTIFACTS BY PLATFORM =================

        # A. Common Artifact: sitemap.xml
        sitemap_xml_content = CodeTemplateEngine.render_sitemap_xml(sitemap_items, is_demo=is_demo)
        artifacts.append(GeneratedArtifact(
            artifact_type="sitemap_xml",
            file_path="sitemap.xml",
            platform="common",
            title="Clean XML Sitemap (200 OK indexable canonical URLs only)",
            content=sitemap_xml_content,
            source_issue_ids=sitemap_i_ids,
            source_task_ids=sitemap_t_ids,
            metadata={"total_urls": len(sitemap_items)}
        ))

        # B. Common Artifact: robots.txt
        robots_content = CodeTemplateEngine.render_robots_txt(f"{base_url}/sitemap.xml", is_demo=is_demo)
        artifacts.append(GeneratedArtifact(
            artifact_type="robots_txt",
            file_path="robots.txt",
            platform="common",
            title="Search Engine Directives with Sitemap declaration",
            content=robots_content,
            source_issue_ids=robots_i_ids,
            source_task_ids=robots_t_ids
        ))

        # C. Common Artifact: llms.txt (placed in public/llms.txt for Next.js to serve statically)
        llms_path = "public/llms.txt" if platform == "nextjs" else "llms.txt"
        llms_content = CodeTemplateEngine.render_llms_txt(brand_name, site_summary, base_url, curated_links, is_demo=is_demo)
        artifacts.append(GeneratedArtifact(
            artifact_type="llms_txt",
            file_path=llms_path,
            platform="nextjs" if platform == "nextjs" else "common",
            title="Structured Markdown Guide for LLM and AI Search Engines (llms.txt standard)",
            content=llms_content,
            source_issue_ids=[],
            source_task_ids=[]
        ))

        # D. Common Artifact: metadata_table.csv
        meta_issue_ids, meta_task_ids = get_sources_for_issue_types(
            "title_too_long", "title_borderline", "meta_too_long", "meta_borderline", "duplicate_title", "duplicate_meta_description"
        )

        rewrites_for_csv = [
            {
                "url": rw.url,
                "current_title": rw.current_title,
                "suggested_title": rw.suggested_title,
                "current_meta": rw.current_meta,
                "suggested_meta": rw.suggested_meta,
                "issue_ids": [iss.id for iss in verified_tech_issues if rw.url in iss.urls]
            }
            for rw in verified_rewrites
        ]

        # Requirement 6: Ensure all dynamic blog posts are cataloged per-post in metadata_table.csv
        existing_csv_urls = {rw.url.rstrip("/") for rw in verified_rewrites}
        for p in crawl_pages:
            p_u = p.get("url", "").rstrip("/")
            if "/blog/" in p_u and p_u not in existing_csv_urls:
                existing_csv_urls.add(p_u)
                rewrites_for_csv.append({
                    "url": p.get("url", ""),
                    "current_title": p.get("title") or "",
                    "suggested_title": (p.get("title") or "Blog Post").split("|")[0].split("—")[0].strip(),
                    "current_meta": p.get("meta_desc") or "",
                    "suggested_meta": p.get("meta_desc") or (p.get("h1") or "Blog article details.")[:140],
                    "issue_ids": [iss.id for iss in verified_tech_issues if p.get("url", "") in iss.urls]
                })

        meta_csv_content = CodeTemplateEngine.render_metadata_csv(rewrites_for_csv, is_demo=is_demo)
        artifacts.append(GeneratedArtifact(
            artifact_type="metadata_table_csv",
            file_path="metadata_table.csv",
            platform="common",
            title="Consolidated On-Page Metadata Optimization Table",
            content=meta_csv_content,
            source_issue_ids=meta_issue_ids,
            source_task_ids=meta_task_ids or ["S-004", "S-005"]
        ))

        # E. Common Artifact: JSON-LD Root Schema (never missing_h1)
        org_jsonld_str = safe_jsonld_string(org_schema)
        artifacts.append(GeneratedArtifact(
            artifact_type="jsonld",
            file_path="schema-organization.jsonld",
            platform="common",
            title="Organization & WebSite Schema.org Structured Data",
            content=org_jsonld_str,
            source_issue_ids=schema_i_ids,
            source_task_ids=schema_t_ids,
            metadata={"provenance": org_prov}
        ))

        # F. Platform Specific Artifacts
        if platform == "nextjs":
            # 1. Root layout metadata snippet (MERGE into app/layout.tsx, do not overwrite)
            home_raw_title = (homepage.get("title") or f"{brand_name} — Web Agency").strip()
            def _get_rw_attr(rw_obj, attr_name):
                if rw_obj is None:
                    return ""
                return getattr(rw_obj, attr_name, None) or (rw_obj.get(attr_name, "") if isinstance(rw_obj, dict) else "")

            home_rewrite = next((r for r in verified_rewrites if _get_rw_attr(r, "url").rstrip("/") == base_url.rstrip("/")), None)
            home_rw_title = _get_rw_attr(home_rewrite, "suggested_title")
            home_rw_meta = _get_rw_attr(home_rewrite, "suggested_meta")
            
            # Shortened homepage title <= 60 chars keeping descriptor (e.g. "WebSpire | Pakistan's Trusted Digital & Web Agency")
            if home_rw_title and len(home_rw_title) <= 60:
                short_title = home_rw_title
            else:
                parts = [p.strip() for p in re.split(r"[|—–]", home_raw_title) if p.strip()]
                if len(parts) >= 2 and len(f"{brand_name} | {parts[-1]}") <= 60:
                    short_title = f"{brand_name} | {parts[-1]}"
                elif len(home_raw_title) <= 60:
                    short_title = home_raw_title
                else:
                    short_title = truncate_at_word_boundary(home_raw_title, 60)

            # Description must use verified rewritten meta (155 chars or fewer)
            if home_rw_meta:
                root_desc = home_rw_meta
            elif homepage.get("meta_desc") and len(homepage.get("meta_desc")) <= 155:
                root_desc = homepage.get("meta_desc")
            else:
                root_desc = truncate_at_word_boundary(homepage.get("meta_desc") or site_summary, 155)

            root_layout_content = CodeTemplateEngine.render_nextjs_root_layout(
                base_url=base_url,
                default_title=short_title,
                default_description=root_desc,
                brand_name=brand_name,
                is_demo=is_demo
            )
            artifacts.append(GeneratedArtifact(
                artifact_type="nextjs_root_layout",
                file_path="app/layout.metadata.snippet.tsx",
                platform="nextjs",
                title="Next.js Root Layout Metadata Snippet (MERGE into app/layout.tsx)",
                content=root_layout_content,
                source_issue_ids=meta_issue_ids,
                source_task_ids=["S-004"]
            ))

            # 2. Per-page metadata snippets
            # Target pages: all pages affected by metadata issues and rewrites
            affected_page_urls = set()
            for iss_t in ("canonical_to_other", "duplicate_title", "duplicate_meta_description", "brand_repeated_in_title", "title_too_long", "meta_too_long"):
                if iss_t in tech_map:
                    for u in tech_map[iss_t].urls:
                        affected_page_urls.add(u.rstrip("/"))
            for rw in verified_rewrites:
                if rw.suggested_title != "no change needed" or rw.suggested_meta != "no change needed":
                    affected_page_urls.add(rw.url.rstrip("/"))

            # Ensure primary routes like /services, /portfolio, and dynamic /blog/ are always covered if crawled
            for p in crawl_pages:
                p_path = urlparse(p.get("url", "")).path.rstrip("/")
                if p_path in ("/services", "/portfolio", "/calculator", "/track") or p_path.startswith("/blog/"):
                    affected_page_urls.add(p.get("url", "").rstrip("/"))

            crawl_page_by_url = {p["url"].rstrip("/"): p for p in crawl_pages}
            rewrites_by_url = {rw.url.rstrip("/"): rw for rw in verified_rewrites}

            emitted_blog_dynamic_skeleton = False

            for p_url in sorted(affected_page_urls):
                p_path = urlparse(p_url).path.rstrip("/")

                # Dynamic routes handling: for /blog/[slug], do not emit one post's metadata
                # Emit generateMetadata skeleton ONCE for app/blog/[slug]
                if p_path.startswith("/blog/") and p_path != "/blog":
                    if not emitted_blog_dynamic_skeleton:
                        blog_skeleton = CodeTemplateEngine.render_nextjs_blog_dynamic_metadata(
                            base_url=base_url,
                            brand_name=brand_name,
                            target_file="app/blog/[slug]/page.tsx",
                            nextjs_version=nextjs_version,
                            is_demo=is_demo
                        )
                        b_issue_ids = [iss.id for iss in verified_tech_issues if any("/blog/" in u for u in iss.urls)]
                        artifacts.append(GeneratedArtifact(
                            artifact_type="nextjs_dynamic_blog_metadata",
                            file_path="app/blog/[slug]/page.metadata.snippet.tsx",
                            platform="nextjs",
                            title="Next.js Dynamic Route generateMetadata Skeleton for app/blog/[slug]",
                            content=blog_skeleton,
                            source_issue_ids=b_issue_ids,
                            source_task_ids=["S-004", "S-005"],
                            metadata={"route_pattern": "/blog/[slug]", "note": "Per-post titles and metas cataloged in metadata_table.csv"}
                        ))
                        emitted_blog_dynamic_skeleton = True
                    # Skip emitting static page component for this individual blog post
                    continue

                p_crawled = crawl_page_by_url.get(p_url, {})
                rw = rewrites_by_url.get(p_url)

                from app.agents.content_agent import rewrite_natural_title, rewrite_natural_meta, extract_preserved_entities
                p_path_info = map_url_to_nextjs_path(p_url, router_type)
                clean_h1 = p_crawled.get("h1") or p_path_info["file_path"].split("/")[1].replace("-", " ").title()

                # Rule for /portfolio: title must be "Portfolio"
                if p_path == "/portfolio":
                    p_title = "Portfolio"
                    p_desc = "Explore WebSpire's portfolio of custom Next.js web applications, e-commerce stores, UI/UX case studies, and enterprise digital solutions delivered for global clients."
                else:
                    is_dup_t = any(iss.type == "duplicate_title" and any(u.rstrip("/") == p_url for u in iss.urls) for iss in verified_tech_issues)
                    is_long_t = len(p_crawled.get("title", "")) > 60

                    if rw and rw.suggested_title and rw.suggested_title != "no change needed":
                        p_title = rw.suggested_title
                    elif is_dup_t or is_long_t:
                        p_title = rewrite_natural_title(p_crawled.get("title") or "", clean_h1, p_url)
                    else:
                        p_title = p_crawled.get("title") or f"{brand_name} Agency"

                    # When root layout defines title.template = "%s | Brand", sub-page titles MUST be short page titles
                    if p_url != base_url.rstrip("/"):
                        h1_cand = clean_h1.strip() if clean_h1 else ""
                        if brand_name:
                            h1_cand = re.sub(r"\s*[|\-—–]\s*" + re.escape(brand_name) + r".*$", "", h1_cand, flags=re.IGNORECASE)
                            h1_cand = re.sub(r"^" + re.escape(brand_name) + r"\s*[|\-—–:]\s*", "", h1_cand, flags=re.IGNORECASE)
                            h1_cand = re.sub(r"(?i)\b" + re.escape(brand_name) + r"\b", "", h1_cand).strip(" -|—–:,")

                        t_cand = p_title or ""
                        if brand_name:
                            t_cand = re.sub(r"\s*[|\-—–]\s*" + re.escape(brand_name) + r".*$", "", t_cand, flags=re.IGNORECASE)
                            t_cand = re.sub(r"^" + re.escape(brand_name) + r"\s*[|\-—–:]\s*", "", t_cand, flags=re.IGNORECASE)
                            t_cand = re.sub(r"(?i)\b" + re.escape(brand_name) + r"\b", "", t_cand).strip(" -|—–:,")

                        path_parts = p_path_info["file_path"].split("/")
                        path_slug = path_parts[1].replace("-", " ").title() if len(path_parts) > 2 else "Overview"

                        if h1_cand and 3 <= len(h1_cand) <= 35:
                            p_title = h1_cand
                        elif t_cand and 3 <= len(t_cand) <= 35:
                            p_title = t_cand
                        else:
                            p_title = path_slug

                    is_dup_m = any(iss.type == "duplicate_meta_description" and any(u.rstrip("/") == p_url for u in iss.urls) for iss in verified_tech_issues)
                    is_long_m = len(p_crawled.get("meta_desc", "")) > 155

                    if rw and rw.suggested_meta and rw.suggested_meta != "no change needed":
                        p_desc = rw.suggested_meta
                    elif is_dup_m or is_long_m:
                        curr_markets, curr_services = extract_preserved_entities(p_crawled.get("meta_desc") or "")
                        p_desc = rewrite_natural_meta(p_crawled.get("meta_desc") or "", clean_h1, curr_markets, curr_services, p_url)
                    else:
                        p_desc = p_crawled.get("meta_desc") or site_summary

                # openGraph.type = 'article' only for blog posts, 'website' for normal pages
                og_type = "article" if "/blog/" in p_url else "website"

                page_meta_content = CodeTemplateEngine.render_nextjs_page_metadata(
                    title=p_title,
                    description=p_desc,
                    canonical_url=p_url,
                    target_file=p_path_info["target_file"],
                    og_type=og_type,
                    is_demo=is_demo
                )

                # Provenance: strictly the issues affecting this specific URL
                p_issue_ids = [iss.id for iss in verified_tech_issues if any(u.rstrip("/") == p_url for u in iss.urls)]
                p_task_ids = [t.id for t in strategy_tasks if any(ref.id in p_issue_ids for ref in (t.source_refs or []))]

                artifacts.append(GeneratedArtifact(
                    artifact_type="nextjs_page_metadata",
                    file_path=p_path_info["file_path"],
                    platform="nextjs",
                    title=f"Next.js Metadata Snippet for {urlparse(p_url).path or '/'}",
                    content=page_meta_content,
                    source_issue_ids=p_issue_ids,
                    source_task_ids=p_task_ids or ["S-004", "S-005"],
                    metadata={"page_url": p_url, "path_suggestion": p_path_info}
                ))

            # 3. Dynamic TypeScript sitemap & robots
            next_sitemap_ts = CodeTemplateEngine.render_nextjs_sitemap_ts(sitemap_items, is_demo=is_demo)
            artifacts.append(GeneratedArtifact(
                artifact_type="nextjs_sitemap_ts",
                file_path="app/sitemap.ts",
                platform="nextjs",
                title="Next.js Dynamic Sitemap Generator Route (app/sitemap.ts)",
                content=next_sitemap_ts,
                source_issue_ids=sitemap_i_ids,
                source_task_ids=sitemap_t_ids
            ))

            next_robots_ts = CodeTemplateEngine.render_nextjs_robots_ts(f"{base_url}/sitemap.xml", is_demo=is_demo)
            artifacts.append(GeneratedArtifact(
                artifact_type="nextjs_robots_ts",
                file_path="app/robots.ts",
                platform="nextjs",
                title="Next.js Dynamic Robots Generator Route (app/robots.ts)",
                content=next_robots_ts,
                source_issue_ids=robots_i_ids,
                source_task_ids=robots_t_ids
            ))

            # 4. JsonLd Component (provenance: schema_i_ids, NEVER missing_h1)
            jsonld_comp = CodeTemplateEngine.render_nextjs_jsonld_component(example_schema=org_schema, is_demo=is_demo)
            artifacts.append(GeneratedArtifact(
                artifact_type="nextjs_jsonld_component",
                file_path="components/JsonLd.tsx",
                platform="nextjs",
                title="Next.js Safe JSON-LD React Component (XSS Escaped)",
                content=jsonld_comp,
                source_issue_ids=schema_i_ids,
                source_task_ids=schema_t_ids
            ))

            # 5. next.config.js Configuration & Redirects
            next_redirects = CodeTemplateEngine.render_nextjs_redirects(redirect_pairs, is_demo=is_demo)
            artifacts.append(GeneratedArtifact(
                artifact_type="nextjs_redirects",
                file_path="next.config.js",
                platform="nextjs",
                title="Next.js Configuration (next.config.js) Redirects & Optimization",
                content=next_redirects,
                source_issue_ids=redirect_i_ids if redirect_pairs else [],
                source_task_ids=redirect_t_ids if redirect_pairs else [],
                metadata={"redirects": redirect_pairs}
            ))

        elif platform == "wordpress":
            # 1. FIX-INSTRUCTIONS.md
            wp_instructions = CodeTemplateEngine.render_wordpress_instructions(is_demo=is_demo)
            artifacts.append(GeneratedArtifact(
                artifact_type="wordpress_instructions",
                file_path="FIX-INSTRUCTIONS.md",
                platform="wordpress",
                title="WordPress SEO Implementation Guide",
                content=wp_instructions,
                source_issue_ids=[],
                source_task_ids=[]
            ))

            # 2. functions.php wp_head hook
            wp_functions = CodeTemplateEngine.render_wordpress_functions_php(org_schema, is_demo=is_demo)
            artifacts.append(GeneratedArtifact(
                artifact_type="wordpress_functions_php",
                file_path="functions.php",
                platform="wordpress",
                title="WordPress Theme functions.php Schema Hook",
                content=wp_functions,
                source_issue_ids=schema_i_ids,
                source_task_ids=schema_t_ids
            ))

            # 3. .htaccess redirects
            if redirect_pairs:
                wp_htaccess = CodeTemplateEngine.render_wordpress_htaccess(redirect_pairs, is_demo=is_demo)
                artifacts.append(GeneratedArtifact(
                    artifact_type="wordpress_htaccess",
                    file_path=".htaccess",
                    platform="wordpress",
                    title="Apache .htaccess 301 Rewrite Rules",
                    content=wp_htaccess,
                    source_issue_ids=redirect_i_ids,
                    source_task_ids=redirect_t_ids,
                    metadata={"redirects": redirect_pairs}
                ))

        elif platform == "plain_html":
            # 1. Head snippet
            html_snippet = CodeTemplateEngine.render_plain_html_head_snippet(
                page_path="/index.html",
                title=homepage.get("title") or f"{brand_name} | Web Agency",
                description=homepage.get("meta_desc") or site_summary,
                canonical_url=base_url,
                is_demo=is_demo
            )
            artifacts.append(GeneratedArtifact(
                artifact_type="plain_html_head_snippet",
                file_path="snippets/head-index.html",
                platform="plain_html",
                title="HTML Head Metadata and Canonical Tag Snippet",
                content=html_snippet,
                source_issue_ids=meta_issue_ids,
                source_task_ids=["S-004"]
            ))

            # 2. Vercel & Netlify redirects
            if redirect_pairs:
                v_redirects = CodeTemplateEngine.render_vercel_redirects(redirect_pairs, is_demo=is_demo)
                artifacts.append(GeneratedArtifact(
                    artifact_type="vercel_json",
                    file_path="vercel.json",
                    platform="plain_html",
                    title="Vercel Deployment 301 Redirects Configuration",
                    content=v_redirects,
                    source_issue_ids=redirect_i_ids,
                    source_task_ids=redirect_t_ids,
                    metadata={"redirects": redirect_pairs}
                ))

                net_redirects = CodeTemplateEngine.render_netlify_redirects(redirect_pairs, is_demo=is_demo)
                artifacts.append(GeneratedArtifact(
                    artifact_type="netlify_redirects",
                    file_path="_redirects",
                    platform="plain_html",
                    title="Netlify CDN _redirects Rules",
                    content=net_redirects,
                    source_issue_ids=redirect_i_ids,
                    source_task_ids=redirect_t_ids,
                    metadata={"redirects": redirect_pairs}
                ))

        # ================= FIX COVERAGE TABLE =================
        # Track which pages have generated metadata files with alternates.canonical
        pages_with_canonical_code = {
            a.metadata.get("page_url", "").rstrip("/")
            for a in artifacts
            if a.artifact_type in ("nextjs_page_metadata", "wordpress_metadata_hook", "html_head_snippet")
            and "alternates" in a.content and "canonical" in a.content
        }

        fix_coverage = []
        auto_fixable_types = {
            "broken_link_4xx": ["next.config.js", ".htaccess", "vercel.json", "_redirects"],
            "canonical_to_other": ["page.tsx", "snippets/head-index.html"],
            "missing_canonical": ["page.tsx", "snippets/head-index.html"],
            "duplicate_title": ["page.tsx", "metadata_table.csv"],
            "duplicate_meta_description": ["page.tsx", "metadata_table.csv"],
            "title_too_long": ["metadata_table.csv", "page.tsx"],
            "title_borderline": ["metadata_table.csv", "page.tsx"],
            "meta_too_long": ["metadata_table.csv", "page.tsx"],
            "meta_borderline": ["metadata_table.csv", "page.tsx"],
            "missing_h1": ["page.tsx"]
        }

        for iss in verified_tech_issues:
            affected_urls = {u.rstrip("/") for u in iss.urls}
            if iss.type == "broken_link_4xx":
                redirect_sources = {r["source_path"].rstrip("/") for r in redirect_pairs}
                if affected_urls and all(urlparse(u).path.rstrip("/") in redirect_sources for u in affected_urls):
                    coverage_status = "auto-fixable by generated code"
                else:
                    coverage_status = "partially (needs manual step)"
            elif iss.type in ("canonical_to_other", "duplicate_title", "duplicate_meta_description"):
                # Requirement: labelled 'auto-fixable' ONLY if a per-page metadata file with alternates.canonical is generated for EVERY affected page
                if affected_urls and affected_urls.issubset(pages_with_canonical_code):
                    coverage_status = "auto-fixable by generated code"
                else:
                    coverage_status = "partially (needs manual step)"
            elif iss.type in ("title_too_long", "title_borderline", "meta_too_long", "meta_borderline", "missing_h1"):
                coverage_status = "partially (needs manual step)"
            else:
                coverage_status = "manual only"

            matched_arts = [a.file_path for a in artifacts if iss.id in a.source_issue_ids]
            if not matched_arts and iss.type in auto_fixable_types:
                matched_arts = [a.file_path for a in artifacts if any(af in a.file_path for af in auto_fixable_types[iss.type])]

            fix_coverage.append({
                "issue_id": iss.id,
                "issue_type": iss.type,
                "severity": iss.severity,
                "fixability": coverage_status,
                "artifact_names": matched_arts or ["README_APPLY.md"]
            })

        summary = (
            f"SEO Code Generator produced {len(artifacts)} ready-to-apply files for platform '{platform}' "
            f"({len(sitemap_items)} sitemap URLs, {len(redirect_pairs)} 301 redirects, {len(verified_rewrites)} page rewrites). "
            f"All files are provenance-tracked to verified issues and strategy tasks."
        )

        bundle = CodeBundleReport(
            platform=platform,
            platform_confidence=platform_confidence,
            router_type=router_type,
            artifacts=artifacts,
            summary=summary,
            fix_coverage=fix_coverage,
            cost_usd=0.0,
            mode="deterministic"
        )

        return bundle, "deterministic", 0.0, None, None
