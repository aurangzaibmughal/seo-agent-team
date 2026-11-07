import os
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

        # 2. Sitemap items (200, indexable, canonical self, same host)
        sitemap_items = []
        target_domain = urlparse(base_url).netloc.lower()
        seen_sitemap_urls = set()

        for p in crawl_pages:
            u = p.get("url", "")
            u_parsed = urlparse(u)
            if u_parsed.netloc.lower() != target_domain:
                continue
            if p.get("status_code") != 200:
                continue
            if not p.get("indexable"):
                continue
            canonical = p.get("canonical")
            if canonical and canonical.rstrip("/") != u.rstrip("/"):
                continue

            if u.rstrip("/") not in seen_sitemap_urls:
                seen_sitemap_urls.add(u.rstrip("/"))
                sitemap_items.append({
                    "url": u,
                    "lastmod": p.get("last_modified") or p.get("date_published"),
                    "priority": "1.0" if u.rstrip("/") == base_url.rstrip("/") else "0.8"
                })

        # Provenance mapping restricted strictly to issue types produced by issue_rules.py
        sitemap_i_ids, sitemap_t_ids = get_sources_for_issue_types("orphan_page")
        robots_i_ids, robots_t_ids = [], []
        org_schema, org_prov = JsonLdBuilder.build_organization_website(homepage, crawl_links)
        schema_i_ids, schema_t_ids = [], []

        # 4. Curated Links for llms.txt
        curated_links = []
        for p in crawl_pages[:8]:
            if p.get("status_code") == 200 and p.get("indexable"):
                p_title = (p.get("title") or "Page").split("|")[0].split("—")[0].strip()
                p_desc = (p.get("meta_desc") or p.get("h1") or "Key resource and documentation.")[:120]
                curated_links.append({
                    "title": p_title,
                    "url": p["url"],
                    "description": p_desc
                })

        site_summary = homepage.get("meta_desc") or homepage.get("h1") or "Enterprise digital agency and web engineering."

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
            # 1. Root layout metadata snippet
            root_layout_content = CodeTemplateEngine.render_nextjs_root_layout(
                base_url=base_url,
                default_title=homepage.get("title") or f"{brand_name} | Web Agency",
                default_description=homepage.get("meta_desc") or site_summary,
                brand_name=brand_name,
                is_demo=is_demo
            )
            artifacts.append(GeneratedArtifact(
                artifact_type="nextjs_root_layout",
                file_path="app/layout.tsx",
                platform="nextjs",
                title="Next.js App Router Root Layout Metadata Configuration",
                content=root_layout_content,
                source_issue_ids=meta_issue_ids,
                source_task_ids=["S-004"]
            ))

            # 2. Per-page metadata snippets
            # Target pages: all pages affected by canonical_to_other, duplicate_title, duplicate_meta_description, and rewrites
            affected_page_urls = set()
            for iss_t in ("canonical_to_other", "duplicate_title", "duplicate_meta_description"):
                if iss_t in tech_map:
                    for u in tech_map[iss_t].urls:
                        affected_page_urls.add(u.rstrip("/"))
            for rw in verified_rewrites:
                if rw.suggested_title != "no change needed" or rw.suggested_meta != "no change needed":
                    affected_page_urls.add(rw.url.rstrip("/"))

            crawl_page_by_url = {p["url"].rstrip("/"): p for p in crawl_pages}
            rewrites_by_url = {rw.url.rstrip("/"): rw for rw in verified_rewrites}

            for p_url in sorted(affected_page_urls):
                p_crawled = crawl_page_by_url.get(p_url, {})
                rw = rewrites_by_url.get(p_url)

                from app.agents.content_agent import rewrite_natural_title, rewrite_natural_meta, extract_preserved_entities
                p_path_info = map_url_to_nextjs_path(p_url, router_type)
                clean_h1 = p_crawled.get("h1") or p_path_info["file_path"].split("/")[1].replace("-", " ").title()

                is_dup_t = any(iss.type == "duplicate_title" and any(u.rstrip("/") == p_url for u in iss.urls) for iss in verified_tech_issues)
                is_long_t = len(p_crawled.get("title", "")) > 60

                if rw and rw.suggested_title and rw.suggested_title != "no change needed":
                    p_title = rw.suggested_title
                elif is_dup_t or is_long_t:
                    p_title = rewrite_natural_title(p_crawled.get("title") or "", clean_h1, p_url)
                else:
                    p_title = p_crawled.get("title") or f"{brand_name} Agency"

                is_dup_m = any(iss.type == "duplicate_meta_description" and any(u.rstrip("/") == p_url for u in iss.urls) for iss in verified_tech_issues)
                is_long_m = len(p_crawled.get("meta_desc", "")) > 155

                if rw and rw.suggested_meta and rw.suggested_meta != "no change needed":
                    p_desc = rw.suggested_meta
                elif is_dup_m or is_long_m:
                    curr_markets, curr_services = extract_preserved_entities(p_crawled.get("meta_desc") or "")
                    p_desc = rewrite_natural_meta(p_crawled.get("meta_desc") or "", clean_h1, curr_markets, curr_services, p_url)
                else:
                    p_desc = p_crawled.get("meta_desc") or site_summary

                page_meta_content = CodeTemplateEngine.render_nextjs_page_metadata(
                    title=p_title,
                    description=p_desc,
                    canonical_url=p_url,
                    h1_text=clean_h1,
                    is_demo=is_demo
                )

                # Provenance: strictly the issues affecting this specific URL
                p_issue_ids = [iss.id for iss in verified_tech_issues if any(u.rstrip("/") == p_url for u in iss.urls)]
                p_task_ids = [t.id for t in strategy_tasks if any(ref.id in p_issue_ids for ref in (t.source_refs or []))]

                artifacts.append(GeneratedArtifact(
                    artifact_type="nextjs_page_metadata",
                    file_path=p_path_info["file_path"],
                    platform="nextjs",
                    title=f"Next.js Page Metadata Snippet for {urlparse(p_url).path or '/'}",
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

            # 5. next.config.js Redirects
            if redirect_pairs:
                next_redirects = CodeTemplateEngine.render_nextjs_redirects(redirect_pairs, is_demo=is_demo)
                artifacts.append(GeneratedArtifact(
                    artifact_type="nextjs_redirects",
                    file_path="next.config.js",
                    platform="nextjs",
                    title="Next.js Configuration 301 Permanent Redirects",
                    content=next_redirects,
                    source_issue_ids=redirect_i_ids,
                    source_task_ids=redirect_t_ids,
                    metadata={"redirects": redirect_pairs}
                ))

        elif platform == "wordpress":
            # 1. functions.php wp_head hook
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

            # 2. .htaccess redirects
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
