import os
import csv
import json
import html
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import openpyxl
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from urllib.parse import urlparse
from app.core.classification import classify_page_type
from app.core.db import DBManager

EXPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "exports")
os.makedirs(EXPORTS_DIR, exist_ok=True)

class ReportExporter:
    @classmethod
    def filter_by_review(
        cls,
        job_id: str,
        items: List[Dict[str, Any]],
        item_type: str,
        include_unreviewed: bool = False
    ) -> List[Dict[str, Any]]:
        from app.core.db import DBManager
        reviews = DBManager.get_review_items(job_id, item_type=item_type)
        if not reviews:
            return items

        rev_map = {r["item_ref"]: r for r in reviews}
        filtered = []
        for itm in items:
            ref = itm.get("id") or itm.get("url") or itm.get("file_path") or itm.get("type")
            rev = rev_map.get(ref)
            if not rev:
                if include_unreviewed:
                    itm["review_label"] = "[UNREVIEWED]"
                    filtered.append(itm)
                continue

            st = rev.get("status", "pending")
            if st in ("approved", "edited"):
                if st == "edited" and rev.get("edited_payload"):
                    merged = dict(itm)
                    merged.update(rev["edited_payload"])
                    merged["review_label"] = "[HUMAN-EDITED]"
                    filtered.append(merged)
                else:
                    itm["review_label"] = "[APPROVED]"
                    filtered.append(itm)
            elif include_unreviewed and st == "pending":
                itm["review_label"] = "[UNREVIEWED]"
                filtered.append(itm)

        return filtered

    @classmethod
    def generate_pdf(
        cls,
        job_id: str,
        target_url: str,
        verified_issues: List[Dict[str, Any]],
        performance_data: Optional[Dict[str, Any]] = None,
        strategy_data: Optional[Dict[str, Any]] = None,
        content_data: Optional[Dict[str, Any]] = None,
        research_data: Optional[Dict[str, Any]] = None,
        psi_data: Optional[List[Dict[str, Any]]] = None,
        code_data: Optional[Dict[str, Any]] = None,
        is_demo: bool = False,
        agency_name: Optional[str] = None,
        include_unreviewed: bool = False,
        crawl_pages: Optional[List[Dict[str, Any]]] = None,
        strict_lint_gate: bool = False,
        **kwargs
    ) -> str:
        # Filter items based on review status
        verified_issues = cls.filter_by_review(job_id, verified_issues, "technical_issue", include_unreviewed)
        if content_data and "rewrites" in content_data:
            content_data = dict(content_data)
            content_data["rewrites"] = cls.filter_by_review(job_id, content_data["rewrites"], "rewrite", include_unreviewed)
        if strategy_data and "tasks" in strategy_data:
            strategy_data = dict(strategy_data)
            strategy_data["tasks"] = cls.filter_by_review(job_id, strategy_data["tasks"], "strategy_task", include_unreviewed)
        if code_data and "bundle" in code_data and "artifacts" in code_data["bundle"]:
            code_data = dict(code_data)
            code_data["bundle"] = dict(code_data["bundle"])
            code_data["bundle"]["artifacts"] = cls.filter_by_review(job_id, code_data["bundle"]["artifacts"], "code_artifact", include_unreviewed)

        filename = f"SEO_Report_{job_id[:8]}.pdf"
        file_path = os.path.join(EXPORTS_DIR, filename)

        doc = SimpleDocTemplate(file_path, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
        story = []
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=18, leading=22, textColor=colors.HexColor('#0f172a'))
        h2_style = ParagraphStyle('H2Style', parent=styles['Heading2'], fontSize=12, leading=16, textColor=colors.HexColor('#1e293b'), spaceBefore=10, spaceAfter=5)
        body_style = ParagraphStyle('BodyStyle', parent=styles['Normal'], fontSize=8.5, leading=11, textColor=colors.HexColor('#334155'))
        meta_style = ParagraphStyle('MetaStyle', parent=styles['Normal'], fontSize=8, leading=10, textColor=colors.HexColor('#64748b'))

        # DEMO DATA Watermark Banner
        if is_demo:
            demo_banner = Table([["DEMO DATA — AUDIT GENERATED USING SEEDED TEST DATA"]], colWidths=[540])
            demo_banner.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fee2e2')),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#991b1b')),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#f87171')),
                ('PADDING', (0, 0), (-1, -1), 6),
            ]))
            story.append(demo_banner)
            story.append(Spacer(1, 8))

        # Header / White-label
        header_text = agency_name if agency_name else "SEO Agent Team — Autonomous Multi-Agent Platform"
        story.append(Paragraph(f"<b>{header_text}</b>", meta_style))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#e2e8f0'), spaceAfter=8))

        # Crawl Completeness & Health Breakdown Notice
        job_info = DBManager.get_job(job_id) or {}

        # Report-Time QA Linter Gate (A-16): checks evidence, metric plausibility, and speed issue counts vs PSI table
        from app.services.report_linter import lint_audit_report, ReportLintGateError
        strat_tasks = strategy_data.get("tasks", []) if strategy_data else []
        rws = content_data.get("rewrites", []) if content_data else []
        effective_psi = psi_data if psi_data is not None else (DBManager.get_psi_results(job_id) or [])
        qa_warnings = lint_audit_report(
            job=job_info,
            tech_issues=verified_issues,
            strategy_tasks=strat_tasks,
            rewrites=rws,
            psi_results=effective_psi,
            code_bundle=code_data.get("bundle") if code_data else None
        )
        if qa_warnings:
            print(f"[Report-Time Linter Gate] {len(qa_warnings)} QA warning(s) detected for job {job_id}:")
            for w in qa_warnings:
                print(f"  - {w}")
            if strict_lint_gate:
                raise ReportLintGateError(qa_warnings)

        pages_crawled = job_info.get("pages_crawled", len(crawl_pages or []))
        max_pages = job_info.get("max_pages", 100)
        sitemap_entries = []
        if job_info.get("sitemap_entries_json"):
            try:
                sitemap_entries = json.loads(job_info["sitemap_entries_json"])
            except Exception:
                sitemap_entries = []
        sitemap_cnt = len(sitemap_entries)
        comp_status = job_info.get("completeness_status", "complete")

        inc_reasons = []
        if job_info.get("incomplete_reasons_json"):
            try:
                inc_reasons = json.loads(job_info["incomplete_reasons_json"])
            except Exception:
                inc_reasons = []

        # Parse dropped / excluded pages with reasons
        dropped_pages = []
        raw_dropped = job_info.get("dropped_pages_json")
        if raw_dropped:
            try:
                if isinstance(raw_dropped, str):
                    dropped_pages = json.loads(raw_dropped)
                elif isinstance(raw_dropped, list):
                    dropped_pages = raw_dropped
            except Exception:
                dropped_pages = []
        if not dropped_pages and crawl_pages:
            for p in crawl_pages:
                st = p.get("status_code", 200)
                if st != 200:
                    dropped_pages.append({"url": p.get("url"), "reason": f"HTTP {st}"})

        is_incomplete = comp_status == "possibly incomplete" or job_info.get("crawl_incomplete") == 1 or bool(inc_reasons)
        bg_col = colors.HexColor('#fef3c7') if is_incomplete else colors.HexColor('#f0fdf4')
        border_col = colors.HexColor('#f59e0b') if is_incomplete else colors.HexColor('#22c55e')
        text_col = colors.HexColor('#92400e') if is_incomplete else colors.HexColor('#166534')

        banner_text = f"<b>Crawl Breakdown:</b> {pages_crawled} HTML pages crawled (limit: {max_pages}) | {sitemap_cnt} sitemap URLs discovered | Status: {comp_status.upper()}"
        if inc_reasons:
            banner_text += f"<br/><b>Notes:</b> {'; '.join(inc_reasons)}"
        if dropped_pages:
            drop_summary = "; ".join(f"{d.get('url')} ({d.get('reason')})" for d in dropped_pages[:5])
            if len(dropped_pages) > 5:
                drop_summary += f" (+{len(dropped_pages) - 5} more)"
            banner_text += f"<br/><b>Dropped / Excluded Pages ({len(dropped_pages)}):</b> {drop_summary}"

        inc_banner = Table([[Paragraph(banner_text, body_style)]], colWidths=[540])
        inc_banner.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), bg_col),
            ('TEXTCOLOR', (0, 0), (-1, -1), text_col),
            ('GRID', (0, 0), (-1, -1), 1, border_col),
            ('PADDING', (0, 0), (-1, -1), 5),
        ]))
        story.append(inc_banner)
        story.append(Spacer(1, 8))

        # Title
        story.append(Paragraph("Executive SEO & Action Plan Report", title_style))
        story.append(Paragraph(f"Target Domain: <b>{target_url}</b> | Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", meta_style))
        story.append(Spacer(1, 10))

        # Dynamic Section Numbering
        sec_num = 1

        # 1. Technical Audit Summary
        story.append(Paragraph(f"{sec_num}. Technical SEO Audit Findings", h2_style))
        sec_num += 1
        high_cnt = sum(1 for i in verified_issues if i.get("severity") == "high")
        med_cnt = sum(1 for i in verified_issues if i.get("severity") == "medium")
        low_cnt = sum(1 for i in verified_issues if i.get("severity") == "low")

        stats_data = [
            ["High Severity", "Medium Severity", "Low Severity", "Total Verified Issues"],
            [str(high_cnt), str(med_cnt), str(low_cnt), str(len(verified_issues))]
        ]
        t_stats = Table(stats_data, colWidths=[135, 135, 135, 135])
        t_stats.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('FONTSIZE', (0, 1), (-1, 1), 11),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('PADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(t_stats)
        story.append(Spacer(1, 6))

        # Length Tiers Summary (M4 carry-over & M5)
        t_bord = sum(len(i.get("urls", [])) for i in verified_issues if i.get("type") == "title_borderline")
        t_long = sum(len(i.get("urls", [])) for i in verified_issues if i.get("type") == "title_too_long")
        m_bord = sum(len(i.get("urls", [])) for i in verified_issues if i.get("type") == "meta_borderline")
        m_long = sum(len(i.get("urls", [])) for i in verified_issues if i.get("type") == "meta_too_long")

        tier_data = [
            ["Title Borderline (61-65 chars)", "Title Too Long (>65 chars)", "Meta Borderline (161-170 chars)", "Meta Too Long (>170 chars)"],
            [f"{t_bord} pages", f"{t_long} pages", f"{m_bord} pages", f"{m_long} pages"]
        ]
        t_tier = Table(tier_data, colWidths=[135, 135, 135, 135])
        t_tier.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f8fafc')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#475569')),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 7),
            ('FONTSIZE', (0, 1), (-1, 1), 9),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('PADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(t_tier)
        story.append(Spacer(1, 8))

        # Technical Issues Table
        if verified_issues:
            issues_rows = [["ID", "Type", "Sev", "Affected", "Impact & Fix Hint"]]
            for issue in verified_issues[:10]:
                clean_impact = html.escape(str(issue.get("impact", "")))
                clean_fix = html.escape(str(issue.get("fix_hint", "")))
                txt = f"<b>Impact:</b> {clean_impact}<br/><b>Fix:</b> {clean_fix}"
                issues_rows.append([
                    issue.get("id", ""),
                    issue.get("type", ""),
                    issue.get("severity", "").upper(),
                    str(len(issue.get("urls", []))),
                    Paragraph(txt, body_style)
                ])
            t_issues = Table(issues_rows, colWidths=[40, 100, 45, 50, 305])
            t_issues.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 7.5),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('PADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(t_issues)

            # Detailed Issues Evidence (A-06: Every issue lists affected URLs)
            story.append(Spacer(1, 8))
            story.append(Paragraph("<b>Issue Evidence & Affected URLs (Full Reproduction Trail)</b>", h2_style))
            evidence_rows = [["ID", "Type", "Affected URL", "Found / Required Action"]]
            for issue in verified_issues:
                i_id = issue.get("id", "")
                i_type = issue.get("type", "")
                hint = html.escape(str(issue.get("fix_hint", "")[:120]))
                for u in issue.get("urls", []):
                    evidence_rows.append([
                        i_id,
                        i_type,
                        Paragraph(f"<font size=6.5>{html.escape(u)}</font>", body_style),
                        Paragraph(f"<font size=6.5>{hint}</font>", body_style)
                    ])
            if len(evidence_rows) > 1:
                t_ev = Table(evidence_rows, colWidths=[40, 110, 240, 150])
                t_ev.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e293b')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 6.5),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('PADDING', (0, 0), (-1, -1), 2),
                ]))
                story.append(t_ev)
        else:
            story.append(Paragraph("No technical issues identified.", body_style))

        # Positive Note: Private utility pages correctly noindexed
        crawl_pages = DBManager.get_crawl_pages(job_id, limit=2000)
        private_noindexed = [
            p.get("url") for p in crawl_pages
            if classify_page_type(p.get("url")) == "utility"
            and p.get("indexability_status") in ("noindex_meta", "noindex_header")
        ]
        if private_noindexed:
            clean_paths = [urlparse(u).path for u in private_noindexed if u]
            story.append(Spacer(1, 4))
            story.append(Paragraph(
                f"<b>Positive Note:</b> Private pages correctly noindexed ({len(private_noindexed)} pages: {', '.join(clean_paths[:4])}). Prevents search engine indexing of private auth and utility routes.",
                meta_style
            ))

        # Sitemap Comparison & Health Section
        story.append(Spacer(1, 10))
        story.append(Paragraph("Sitemap Health & Discrepancy Comparison", h2_style))
        sm_issues = [i for i in verified_issues if i.get("type") in ("sitemap_lists_non_existent_url", "crawled_page_missing_from_sitemap")]
        if sm_issues:
            sm_table_rows = [["Issue Type", "URL", "Severity", "Impact & Action"]]
            for smi in sm_issues:
                itype = smi.get("type")
                sev_label = smi.get("severity", "").upper()
                label = "Stale Sitemap URL (4xx/5xx)" if itype == "sitemap_lists_non_existent_url" else "Crawled Page Missing From Sitemap"
                for u in smi.get("urls", []):
                    action_txt = "Remove from sitemap.xml or publish live page" if itype == "sitemap_lists_non_existent_url" else "Add 200 OK indexable page to sitemap.xml"
                    sm_table_rows.append([
                        label,
                        Paragraph(html.escape(u), body_style),
                        sev_label,
                        Paragraph(action_txt, body_style)
                    ])
            t_sm = Table(sm_table_rows, colWidths=[130, 220, 50, 140])
            t_sm.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 7.5),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('PADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(t_sm)
        else:
            story.append(Paragraph("<i>Sitemap and crawl are 100% synchronized. No stale sitemap URLs or omitted indexable pages.</i>", body_style))

        story.append(Spacer(1, 10))

        # 2. Performance Section (GSC & GA4)
        story.append(Paragraph(f"{sec_num}. Organic Search Performance (Google Search Console & GA4)", h2_style))
        sec_num += 1
        if performance_data and "summary_totals" in performance_data:
            totals = performance_data["summary_totals"]
            perf_table_data = [
                ["Metric", "Current Period", "Previous Period", "Change"],
                ["Total Clicks", str(totals.get("clicks", 0)), str(totals.get("previous_clicks", 0)), f"{totals.get('clicks_change_pct', 0.0)}%"],
                ["Impressions", str(totals.get("impressions", 0)), str(totals.get("previous_impressions", 0)), f"{totals.get('impressions_change_pct', 0.0)}%"],
                ["Average CTR", f"{totals.get('ctr', 0.0)}%", f"{totals.get('previous_ctr', 0.0)}%", f"{totals.get('ctr_change_abs', 0.0)}%"],
                ["Average Position", str(totals.get("avg_position", 0.0)), str(totals.get("previous_avg_position", 0.0)), str(totals.get("avg_position_change_abs", 0.0))],
                ["Organic Sessions", str(totals.get("organic_sessions", 0)), str(totals.get("previous_organic_sessions", 0)), f"{totals.get('sessions_change_pct', 0.0)}%"],
            ]
            t_perf = Table(perf_table_data, colWidths=[135, 135, 135, 135])
            t_perf.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f8fafc')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 7.5),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
                ('PADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(t_perf)
        else:
            story.append(Paragraph("<i>Performance data not connected (Google Search Console & GA4 not linked).</i>", body_style))

        # Core Web Vitals & PageSpeed Section (lab data (Lighthouse))
        story.append(Spacer(1, 8))
        story.append(Paragraph("PageSpeed & Core Web Vitals (lab data (Lighthouse))", h2_style))

        if psi_data and any(p.get("performance_score") is not None for p in psi_data):
            tested_urls = set(p.get("url") for p in psi_data if p.get("url"))
            total_crawl_count = len(crawl_pages) if crawl_pages else len(tested_urls)
            disclosure_text = (
                f"<i>Tested {len(tested_urls)} of {total_crawl_count} crawled pages (sampled top pages by internal inlinks). "
                f"Metrics are simulated lab data (Lighthouse) under standardized mobile/desktop throttling, strictly separated from field user data (Chrome UX Report / CrUX).</i>"
            )
            story.append(Paragraph(disclosure_text, body_style))
            story.append(Spacer(1, 4))

            psi_rows = [["URL", "Device", "Score [lab data (Lighthouse)]", "LCP", "CLS", "FCP", "TTFB"]]
            for p in psi_data[:8]:
                sc = str(p.get("performance_score")) if p.get("performance_score") is not None else "N/A"
                lcp = f"{p.get('lcp_ms')} ms" if p.get("lcp_ms") is not None else "N/A"
                cls_v = str(p.get("cls")) if p.get("cls") is not None else "N/A"
                fcp = f"{p.get('fcp_ms')} ms" if p.get("fcp_ms") is not None else "N/A"
                ttfb = f"{p.get('ttfb_ms')} ms" if p.get("ttfb_ms") is not None else "N/A"
                dev_str = p.get("strategy", "").capitalize()

                # Requirement: measured_at + fresh/cached label on EVERY PSI row
                is_cached = bool(p.get("is_cached"))
                m_time = (p.get("cached_measured_at") if is_cached else None) or p.get("fetched_at") or p.get("measured_at") or ""
                clean_time = m_time[:19].replace("T", " ") if m_time else datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
                cache_status = "cached" if is_cached else "fresh"
                dev_str = f"{dev_str}<br/><font size='5.5' color='#64748b'>({cache_status}, measured at {clean_time})</font>"

                psi_rows.append([
                    Paragraph(html.escape(p.get("url", "")), body_style),
                    Paragraph(dev_str, body_style),
                    sc,
                    lcp,
                    cls_v,
                    fcp,
                    ttfb
                ])
            t_psi = Table(psi_rows, colWidths=[180, 50, 90, 55, 55, 55, 55])
            t_psi.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 7.5),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('PADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(t_psi)
        else:
            reason = (job_info.get("psi_status") or "API key not configured or calls failed").replace("failed: ", "")
            story.append(Paragraph(f"<i>PageSpeed unavailable: {reason}</i>", body_style))

        story.append(Spacer(1, 10))

        # 3. 30-Day Prioritized Action Plan (M4)
        story.append(Paragraph(f"{sec_num}. 30-Day Prioritized SEO Action Plan", h2_style))
        sec_num += 1
        tasks = []
        if strategy_data and "tasks" in strategy_data:
            tasks = strategy_data["tasks"]
        elif strategy_data and isinstance(strategy_data, list):
            tasks = strategy_data

        if tasks:
            strat_rows = [["Week", "ID", "Task Title", "Category", "Priority", "Acceptance / Done When"]]
            for t in tasks[:12]:
                strat_rows.append([
                    f"W{t.get('week', 1)}",
                    t.get("id", ""),
                    t.get("title", ""),
                    t.get("category", ""),
                    str(t.get("priority_score", round((t.get("impact", 3) * 2.0) / max(t.get("effort", 3), 1), 2))),
                    Paragraph(t.get("done_when", ""), body_style)
                ])
            t_strat = Table(strat_rows, colWidths=[35, 45, 150, 70, 45, 195])
            t_strat.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e293b')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 7.5),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('PADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(t_strat)
        else:
            story.append(Paragraph("No strategy tasks generated.", body_style))

        story.append(Spacer(1, 10))

        # 4. Content Briefs & On-Page Rewrites (M4)
        story.append(Paragraph(f"{sec_num}. Content Briefs & On-Page Title/Meta Rewrites (Suggested drafts: review before use)", h2_style))
        sec_num += 1
        briefs = content_data.get("briefs", []) if content_data else []
        rewrites = content_data.get("rewrites", []) if content_data else []
        links = content_data.get("internal_links", []) if content_data else []

        if briefs:
            story.append(Paragraph("<b>Target Content Briefs:</b>", meta_style))
            b_rows = [["Cluster / Target", "Source (URL & Query)", "Suggested Title (≤60)", "Suggested Meta (≤155)", "Outline / Questions"]]
            for b in briefs[:3]:
                outline_txt = ", ".join(b.get("outline", []))[:100]
                q_txt = "<br/><b>Q:</b> " + "<br/><b>Q:</b> ".join(b.get("questions_to_answer", []))[:120] if b.get("questions_to_answer") else ""
                s_url = html.escape(str(b.get("source_url") or b.get("target_url") or "GSC"))
                s_txt = html.escape(str(b.get("source_text") or b.get("target_cluster") or ""))
                src_html = f"<b>URL:</b> {s_url}<br/><b>Query:</b> {s_txt}"
                b_rows.append([
                    Paragraph(f"<b>{b.get('target_cluster', '')}</b><br/>Intent: {b.get('intent', 'informational')}", body_style),
                    Paragraph(src_html, body_style),
                    Paragraph(f"{b.get('suggested_title', '')} ({len(b.get('suggested_title', ''))} chars)", body_style),
                    Paragraph(f"{b.get('suggested_meta', '')} ({len(b.get('suggested_meta', ''))} chars)", body_style),
                    Paragraph(f"{outline_txt}{q_txt}", body_style)
                ])
            t_b = Table(b_rows, colWidths=[90, 110, 110, 115, 115])
            t_b.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 7),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('PADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(t_b)
            story.append(Spacer(1, 6))
        else:
            story.append(Paragraph("<b>Target Content Briefs:</b> <i>n/a - requires Search Console data</i>", meta_style))
            story.append(Spacer(1, 6))

        if rewrites:
            story.append(Paragraph("<b>On-Page Metadata Rewrites (Suggested drafts: review before use):</b>", meta_style))
            rw_rows = [["URL", "Current Title / Meta", "Suggested Title / Meta (Suggested drafts: review before use)"]]
            for rw in rewrites[:4]:
                c_title = html.escape(str(rw.get('current_title', '')))
                c_meta = html.escape(str(rw.get('current_meta', '')))
                s_title = html.escape(str(rw.get('suggested_title', '')))
                s_meta = html.escape(str(rw.get('suggested_meta', '')))
                curr = f"<b>T:</b> {c_title}<br/><b>M:</b> {c_meta}"
                sugg = f"<b>[Suggested drafts: review before use]</b><br/><b>T:</b> {s_title} ({len(rw.get('suggested_title', ''))} chars)<br/><b>M:</b> {s_meta} ({len(rw.get('suggested_meta', ''))} chars)"
                rw_rows.append([
                    Paragraph(html.escape(str(rw.get("url", ""))), body_style),
                    Paragraph(curr, body_style),
                    Paragraph(sugg, body_style)
                ])
            t_rw = Table(rw_rows, colWidths=[150, 195, 195])
            t_rw.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f8fafc')),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 7),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('PADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(t_rw)

        if links:
            story.append(Spacer(1, 6))
            story.append(Paragraph("<b>Deterministic Internal Link Suggestions:</b>", meta_style))
            il_rows = [["Source URL", "Target URL", "Anchor Text", "Reason"]]
            for l in links[:5]:
                il_rows.append([
                    Paragraph(l.get("source_url", ""), body_style),
                    Paragraph(l.get("target_url", ""), body_style),
                    Paragraph(f"<b>{l.get('anchor_text', '')}</b>", body_style),
                    Paragraph(l.get("reason", ""), body_style)
                ])
            t_il = Table(il_rows, colWidths=[160, 160, 110, 110])
            t_il.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 7),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('PADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(t_il)

        # 5. Competitor Comparison Section (if available)
        comp_data = research_data.get("competitor_comparison") if research_data else None
        if comp_data and comp_data.get("competitors"):
            story.append(Spacer(1, 10))
            story.append(Paragraph(f"{sec_num}. Competitor On-Page Comparison", h2_style))
            sec_num += 1
            story.append(Paragraph("<i>Note: on-page comparison only — no traffic or backlink data</i>", meta_style))
            c_rows = [["Competitor Domain", "Pages Crawled", "Detected Schema Types", "Content Depth / Headings"]]
            for comp in comp_data.get("competitors", []):
                c_rows.append([
                    comp.get("domain", ""),
                    str(comp.get("pages_crawled", 0)),
                    ", ".join(comp.get("schema_types", [])) or "None",
                    f"Headings: {len(comp.get('headings_sample', []))} found"
                ])
            t_c = Table(c_rows, colWidths=[120, 80, 170, 170])
            t_c.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f8fafc')),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 7.5),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
                ('PADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(t_c)

        # 6. Automated Code Fixes & Implementation Package (M5)
        story.append(Spacer(1, 10))
        story.append(Paragraph(f"{sec_num}. Automated Code Fixes & Implementation Package", h2_style))
        sec_num += 1

        bundle = code_data.get("bundle", {}) if code_data else {}
        verifier = code_data.get("verifier", {}) if code_data else {}
        artifacts = bundle.get("artifacts", [])
        fix_coverage = bundle.get("fix_coverage", [])
        platform = bundle.get("platform", "plain_html")

        if len(artifacts) > 0:
            story.append(Paragraph("<i>Code fixes generated deterministically via Jinja2 templates. Download full bundle as ZIP via API/UI.</i>", meta_style))
            story.append(Paragraph(f"<b>Target Platform:</b> {platform.upper()} | <b>Generated Files:</b> {len(artifacts)} | <b>ZIP Package:</b> seo-fixes-{job_id[:8]}.zip", body_style))
        else:
            story.append(Paragraph("<i>No automated code fix bundle generated for this audit. Follow manual implementation instructions.</i>", meta_style))
            story.append(Paragraph(f"<b>Target Platform:</b> {platform.upper()} | <b>Generated Files:</b> 0 (Manual implementation required)", body_style))
        story.append(Spacer(1, 6))

        # Fix Coverage Table
        if fix_coverage:
            story.append(Paragraph("<b>Issue Fixability & Coverage:</b>", meta_style))
            cov_rows = [["Issue ID", "Type", "Severity", "Fixability Status", "Resolving Files"]]
            for fc in fix_coverage[:8]:
                art_str = ", ".join(fc.get("artifact_names", []))[:60]
                cov_rows.append([
                    fc.get("issue_id", ""),
                    fc.get("issue_type", ""),
                    fc.get("severity", "").upper(),
                    fc.get("fixability", ""),
                    art_str
                ])
            t_cov = Table(cov_rows, colWidths=[55, 120, 65, 160, 140])
            t_cov.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 7),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('PADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(t_cov)
            story.append(Spacer(1, 6))

        # Artifacts Table
        if artifacts:
            story.append(Paragraph("<b>Generated Code & Configuration Artifacts:</b>", meta_style))
            art_rows = [["File Path", "Artifact Type", "Validation Status", "Issues Addressed"]]
            for a in artifacts[:8]:
                src_issues = ", ".join(a.get("source_issue_ids", [])) or "S-001"
                art_rows.append([
                    Paragraph(f"<code>{html.escape(a.get('file_path', ''))}</code>", body_style),
                    Paragraph(a.get("artifact_type", ""), body_style),
                    Paragraph(f"<b>{a.get('validation_status', 'passed')}</b>", body_style),
                    Paragraph(src_issues, body_style)
                ])
            t_art = Table(art_rows, colWidths=[180, 140, 100, 120])
            t_art.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 7),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('PADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(t_art)

        # Appendix: Crawled Page Inventory & Health
        if crawl_pages:
            story.append(Spacer(1, 10))
            story.append(Paragraph(f"{sec_num}. Page Inventory & Crawl Health", h2_style))
            sec_num += 1
            inv_rows = [["URL", "Status", "Title Length", "Meta Length", "Canonical", "Indexable"]]
            for p in (crawl_pages or [])[:25]:
                u = p.get("url", "")
                sc = str(p.get("status_code", 200))
                t_len = f"{len(p.get('title') or '')} chars"
                m_len = f"{len(p.get('meta_desc') or '')} chars"
                can = "Self" if p.get("canonical") == u else ("Missing" if not p.get("canonical") else "Other")
                idx = "Yes" if p.get("indexable") else "No"
                inv_rows.append([
                    Paragraph(html.escape(u), body_style),
                    sc,
                    t_len,
                    m_len,
                    can,
                    idx
                ])
            t_inv = Table(inv_rows, colWidths=[200, 45, 75, 75, 75, 70])
            t_inv.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 7),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('PADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(t_inv)

        doc.build(story)
        return file_path

    @classmethod
    def export_pdf(cls, *args, **kwargs) -> bytes:
        """Helper to generate PDF and return the raw bytes directly."""
        # Handle dict job parameter if passed as positional or keyword
        file_path = cls.generate_pdf(*args, **kwargs)
        with open(file_path, "rb") as f:
            return f.read()

    @classmethod
    def generate_csv(
        cls,
        job_id: str,
        verified_issues: List[Dict[str, Any]],
        performance_data: Optional[Dict[str, Any]] = None,
        strategy_data: Optional[Dict[str, Any]] = None,
        content_data: Optional[Dict[str, Any]] = None,
        research_data: Optional[Dict[str, Any]] = None,
        psi_data: Optional[List[Dict[str, Any]]] = None,
        code_data: Optional[Dict[str, Any]] = None,
        is_demo: bool = False
    ) -> str:
        filename = f"SEO_Export_{job_id[:8]}.csv"
        file_path = os.path.join(EXPORTS_DIR, filename)

        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if is_demo:
                writer.writerow(["### DEMO DATA ###", "This export was generated using seeded demonstration data", "", "", "", ""])

            writer.writerow(["SECTION", "ID_OR_KEY", "TYPE_OR_QUERY_OR_URL", "METRIC_1", "METRIC_2", "EXPLANATION_OR_DETAIL"])

            # Length Tiers Summary
            t_bord = sum(len(i.get("urls", [])) for i in verified_issues if i.get("type") == "title_borderline")
            t_long = sum(len(i.get("urls", [])) for i in verified_issues if i.get("type") == "title_too_long")
            m_bord = sum(len(i.get("urls", [])) for i in verified_issues if i.get("type") == "meta_borderline")
            m_long = sum(len(i.get("urls", [])) for i in verified_issues if i.get("type") == "meta_too_long")
            writer.writerow(["Length Tier", "title_borderline", f"{t_bord} pages", "61-65 chars", "Informational", "Monitored tier"])
            writer.writerow(["Length Tier", "title_too_long", f"{t_long} pages", ">65 chars", "Actionable", "Fix required"])
            writer.writerow(["Length Tier", "meta_borderline", f"{m_bord} pages", "161-170 chars", "Informational", "Monitored tier"])
            writer.writerow(["Length Tier", "meta_too_long", f"{m_long} pages", ">170 chars", "Actionable", "Fix required"])

            # Technical issues
            for i in verified_issues:
                writer.writerow([
                    "Technical Issue",
                    i.get("id"),
                    i.get("type"),
                    f"Severity: {i.get('severity')}",
                    f"Affected: {len(i.get('urls', []))}",
                    f"{i.get('impact')} | Fix: {i.get('fix_hint')}"
                ])
                # A-06: Every issue lists affected URLs with evidence
                for u in i.get("urls", []):
                    writer.writerow([
                        "Technical Issue URL Evidence",
                        i.get("id"),
                        i.get("type"),
                        u,
                        f"Severity: {i.get('severity')}",
                        f"Fix: {i.get('fix_hint')}"
                    ])

            # Sitemap Comparison Detailed Rows
            for i in verified_issues:
                if i.get("type") == "sitemap_lists_non_existent_url":
                    for u in i.get("urls", []):
                        writer.writerow([
                            "Sitemap Stale URL",
                            i.get("id"),
                            u,
                            "4xx/5xx/Uncrawlable",
                            "High Severity" if len(i.get("urls", [])) >= 5 else "Medium Severity",
                            "Declared in sitemap.xml but non-existent on server. Action: Remove from sitemap."
                        ])
                elif i.get("type") == "crawled_page_missing_from_sitemap":
                    for u in i.get("urls", []):
                        writer.writerow([
                            "Sitemap Missing Page",
                            i.get("id"),
                            u,
                            "200 OK",
                            "Medium Severity",
                            "Crawled 200 indexable canonical page missing from sitemap.xml. Action: Add to sitemap."
                        ])

            # Performance opportunities
            if performance_data:
                for q in performance_data.get("striking_distance_queries", []):
                    writer.writerow([
                        "Performance Striking Distance",
                        "SD",
                        q.get("query"),
                        f"Position: {q.get('position')}",
                        f"Impr: {q.get('impressions')}, Clicks: {q.get('clicks')}",
                        "Volume: n/a — requires keyword data provider"
                    ])
                for d in performance_data.get("declining_pages", []):
                    writer.writerow([
                        "Performance Declining Page",
                        "DEC",
                        d.get("url"),
                        f"Change: {d.get('change_pct')}%",
                        f"Current: {d.get('current_clicks')} clicks",
                        "Traffic decline > 20%"
                    ])

            # 30-Day Strategy Tasks
            tasks = strategy_data.get("tasks", []) if strategy_data and isinstance(strategy_data, dict) else (strategy_data or [])
            for t in tasks:
                p_score = t.get("priority_score", round((t.get("impact", 3) * 2.0) / max(t.get("effort", 3), 1), 2))
                writer.writerow([
                    "Strategy Task",
                    t.get("id"),
                    t.get("title"),
                    f"Week {t.get('week', 1)} | Category: {t.get('category')}",
                    f"Priority Score: {p_score}",
                    f"Done when: {t.get('done_when')} | Expected: {t.get('expected_outcome')}"
                ])

            # Content Briefs
            if content_data and content_data.get("briefs"):
                for b in content_data.get("briefs", []):
                    writer.writerow([
                        "Content Brief",
                        b.get("target_cluster"),
                        b.get("suggested_title"),
                        f"Meta: {b.get('suggested_meta')}",
                        f"H1: {b.get('h1')}",
                        f"Questions: {'; '.join(b.get('questions_to_answer', []))}"
                    ])
            else:
                writer.writerow([
                    "Content Brief",
                    "n/a - requires Search Console data",
                    "n/a - requires Search Console data",
                    "", "", ""
                ])

            if content_data:
                for rw in content_data.get("rewrites", []):
                    writer.writerow([
                        "On-Page Rewrite (Suggested drafts: review before use)",
                        rw.get("url"),
                        f"Cur Title: {rw.get('current_title')}",
                        f"New Title: {rw.get('suggested_title')}",
                        f"New Meta: {rw.get('suggested_meta')}",
                        "Char bounds enforced by code | Status: Suggested drafts: review before use"
                    ])
                for il in content_data.get("internal_links", []):
                    writer.writerow([
                        "Internal Link",
                        il.get("source_url"),
                        il.get("target_url"),
                        f"Anchor: {il.get('anchor_text')}",
                        "Cap: max 3/source, max 2/target",
                        il.get("reason")
                    ])

            # Research & Gaps
            if not research_data or not (research_data.get("query_clusters") or research_data.get("opportunities")):
                writer.writerow([
                    "Research & Gaps",
                    "n/a - requires Search Console data",
                    "n/a - requires Search Console data",
                    "", "", ""
                ])

            # Competitor comparison
            if research_data and research_data.get("competitor_comparison"):
                comp = research_data["competitor_comparison"]
                for c in comp.get("competitors", []):
                    writer.writerow([
                        "Competitor Comparison",
                        c.get("domain"),
                        "on-page comparison only — no traffic or backlink data",
                        f"Pages: {c.get('pages_crawled', 0)}",
                        f"Schemas: {', '.join(c.get('schema_types', []))}",
                        "Search volume / KD: n/a — requires keyword data provider"
                    ])

            # PageSpeed & Core Web Vitals (lab data (Lighthouse))
            if psi_data:
                for p in psi_data:
                    writer.writerow([
                        "PageSpeed (lab data (Lighthouse))",
                        p.get("url", ""),
                        p.get("strategy", ""),
                        f"Score [lab data (Lighthouse)]: {p.get('performance_score')}",
                        f"LCP: {p.get('lcp_ms')}ms",
                        f"CLS: {p.get('cls')}, FCP: {p.get('fcp_ms')}ms, TTFB: {p.get('ttfb_ms')}ms"
                    ])

            # Code Fix Coverage & Artifacts (M5)
            if code_data:
                bundle = code_data.get("bundle", {})
                for fc in bundle.get("fix_coverage", []):
                    writer.writerow([
                        "Fix Coverage",
                        fc.get("issue_id", ""),
                        fc.get("issue_type", ""),
                        f"Severity: {fc.get('severity', '')}",
                        f"Fixability: {fc.get('fixability', '')}",
                        f"Files: {', '.join(fc.get('artifact_names', []))}"
                    ])
                for a in bundle.get("artifacts", []):
                    src_issues = ", ".join(a.get("source_issue_ids", [])) or "S-001"
                    writer.writerow([
                        "Code Artifact",
                        a.get("file_path", ""),
                        a.get("artifact_type", ""),
                        f"Status: {a.get('validation_status', 'passed')}",
                        f"Addresses: {src_issues}",
                        f"Title: {a.get('title', '')} | Platform: {bundle.get('platform', '')}"
                    ])

        return file_path

    @classmethod
    def generate_xlsx(
        cls,
        job_id: str,
        target_url: str,
        verified_issues: List[Dict[str, Any]],
        performance_data: Optional[Dict[str, Any]] = None,
        strategy_data: Optional[Dict[str, Any]] = None,
        content_data: Optional[Dict[str, Any]] = None,
        research_data: Optional[Dict[str, Any]] = None,
        psi_data: Optional[List[Dict[str, Any]]] = None,
        code_data: Optional[Dict[str, Any]] = None,
        is_demo: bool = False
    ) -> str:
        filename = f"SEO_Workbook_{job_id[:8]}.xlsx"
        file_path = os.path.join(EXPORTS_DIR, filename)

        wb = openpyxl.Workbook()

        # Sheet 1: Summary
        ws_sum = wb.active
        ws_sum.title = "Summary"
        if is_demo:
            ws_sum.append(["DEMO DATA", "THIS AUDIT WAS GENERATED USING SEEDED DEMO DATA"])
            ws_sum.append([])

        ws_sum.append(["SEO Audit Workbook", target_url, f"Generated: {datetime.now(timezone.utc).isoformat()}"])
        ws_sum.append([])
        ws_sum.append(["Metric", "Value"])
        ws_sum.append(["Total Verified Technical Issues", len(verified_issues)])
        ws_sum.append(["High Severity Issues", sum(1 for i in verified_issues if i.get("severity") == "high")])
        ws_sum.append(["Medium Severity Issues", sum(1 for i in verified_issues if i.get("severity") == "medium")])
        ws_sum.append(["Low Severity Issues", sum(1 for i in verified_issues if i.get("severity") == "low")])

        # Length Tiers Summary (M4 carry-over & M5)
        t_bord = sum(len(i.get("urls", [])) for i in verified_issues if i.get("type") == "title_borderline")
        t_long = sum(len(i.get("urls", [])) for i in verified_issues if i.get("type") == "title_too_long")
        m_bord = sum(len(i.get("urls", [])) for i in verified_issues if i.get("type") == "meta_borderline")
        m_long = sum(len(i.get("urls", [])) for i in verified_issues if i.get("type") == "meta_too_long")
        ws_sum.append(["Title Borderline (61-65 chars)", f"{t_bord} pages"])
        ws_sum.append(["Title Too Long (>65 chars)", f"{t_long} pages"])
        ws_sum.append(["Meta Borderline (161-170 chars)", f"{m_bord} pages"])
        ws_sum.append(["Meta Too Long (>170 chars)", f"{m_long} pages"])

        if performance_data and "summary_totals" in performance_data:
            totals = performance_data["summary_totals"]
            ws_sum.append([])
            ws_sum.append(["Performance Summary", ""])
            ws_sum.append(["Organic Clicks", totals.get("clicks", 0)])
            ws_sum.append(["Clicks Change %", f"{totals.get('clicks_change_pct', 0.0)}%"])
            ws_sum.append(["Organic Impressions", totals.get("impressions", 0)])
            ws_sum.append(["Average CTR", f"{totals.get('ctr', 0.0)}%"])
            ws_sum.append(["Average Position", totals.get("avg_position", 0.0)])

        # Sheet 2: Technical Issues
        ws_iss = wb.create_sheet(title="Technical Issues")
        ws_iss.append(["Issue ID", "Type", "Severity", "Effort", "Affected URLs Count", "Impact", "Fix Hint"])
        for i in verified_issues:
            ws_iss.append([
                i.get("id"),
                i.get("type"),
                i.get("severity", "").upper(),
                i.get("effort", "").capitalize(),
                len(i.get("urls", [])),
                i.get("impact"),
                i.get("fix_hint")
            ])

        # Sheet 2b: Technical Issue Evidence (Per URL) (A-06)
        ws_iss_ev = wb.create_sheet(title="Issue Evidence (Per URL)")
        ws_iss_ev.append(["Issue ID", "Type", "Severity", "Affected URL", "Fix Hint"])
        for i in verified_issues:
            for u in i.get("urls", []):
                ws_iss_ev.append([
                    i.get("id"),
                    i.get("type"),
                    i.get("severity", "").upper(),
                    u,
                    i.get("fix_hint")
                ])

        # Sheet: Sitemap Comparison
        ws_sm = wb.create_sheet(title="Sitemap Comparison")
        ws_sm.append(["Category", "Issue ID", "Full URL", "Status / Details", "Action Required"])
        has_sm_discrepancies = False
        for i in verified_issues:
            if i.get("type") == "sitemap_lists_non_existent_url":
                has_sm_discrepancies = True
                for u in i.get("urls", []):
                    ws_sm.append([
                        "Stale Sitemap URL",
                        i.get("id"),
                        u,
                        "Returns 4xx/5xx or un-crawlable",
                        "Remove URL from sitemap.xml or publish live page"
                    ])
            elif i.get("type") == "crawled_page_missing_from_sitemap":
                has_sm_discrepancies = True
                for u in i.get("urls", []):
                    ws_sm.append([
                        "Crawled Page Missing From Sitemap",
                        i.get("id"),
                        u,
                        "200 OK, indexable, canonical to self",
                        "Add clean URL to sitemap.xml / app/sitemap.ts"
                    ])
        if not has_sm_discrepancies:
            ws_sm.append(["Notice", "-", "Sitemap is 100% synchronized with crawl", "No discrepancies found", "None"])

        # Sheet: Opportunities
        ws_opp = wb.create_sheet(title="Opportunities")
        ws_opp.append(["Type", "Query / URL", "SERP Position", "Impressions", "Clicks", "Detail"])
        if performance_data:
            for q in performance_data.get("striking_distance_queries", []):
                ws_opp.append(["Striking Distance", q.get("query"), q.get("position"), q.get("impressions"), q.get("clicks"), "Ranking 8-20"])
            for l in performance_data.get("low_ctr_opportunities", []):
                ws_opp.append(["Low CTR", l.get("query"), l.get("position"), l.get("impressions"), l.get("clicks"), f"CTR {l.get('ctr')}% vs Median {l.get('median_ctr')}%"])
            for d in performance_data.get("declining_pages", []):
                ws_opp.append(["Declining Page", d.get("url"), "-", d.get("impressions"), d.get("current_clicks"), f"Drop: {d.get('change_pct')}%"])
        else:
            ws_opp.append(["Notice", "Performance data not connected", "", "", "", ""])

        # Sheet 3: 30-Day Strategy
        ws_strat = wb.create_sheet(title="30-Day Strategy")
        ws_strat.append(["Task ID", "Week", "Category", "Title", "Impact (1-5)", "Effort (1-5)", "Priority Score", "Expected Outcome", "Done When"])
        tasks = strategy_data.get("tasks", []) if strategy_data and isinstance(strategy_data, dict) else (strategy_data or [])
        for t in tasks:
            p_score = t.get("priority_score", round((t.get("impact", 3) * 2.0) / max(t.get("effort", 3), 1), 2))
            ws_strat.append([
                t.get("id"),
                f"Week {t.get('week', 1)}",
                t.get("category"),
                t.get("title"),
                t.get("impact"),
                t.get("effort"),
                p_score,
                t.get("expected_outcome"),
                t.get("done_when")
            ])

        # Sheet 4: Content Briefs & Rewrites
        ws_cont = wb.create_sheet(title="Content & Rewrites")
        ws_cont.append(["Type", "Target / URL", "Suggested Title", "Suggested Meta", "H1 / Details", "Questions / Internal Links"])
        if content_data and content_data.get("briefs"):
            for b in content_data.get("briefs", []):
                ws_cont.append([
                    "Brief",
                    b.get("target_cluster"),
                    b.get("suggested_title"),
                    b.get("suggested_meta"),
                    b.get("h1"),
                    "; ".join(b.get("questions_to_answer", []))
                ])
        else:
            ws_cont.append([
                "Brief",
                "n/a - requires Search Console data",
                "n/a - requires Search Console data",
                "", "", ""
            ])

        if content_data:
            for rw in content_data.get("rewrites", []):
                ws_cont.append([
                    "Rewrite [Suggested drafts: review before use]",
                    rw.get("url"),
                    rw.get("suggested_title"),
                    rw.get("suggested_meta"),
                    f"Cur: {rw.get('current_title')}",
                    f"Cur Meta: {rw.get('current_meta')}"
                ])

        # Sheet 5: Internal Links
        ws_links = wb.create_sheet(title="Internal Links")
        ws_links.append(["Source URL", "Target URL", "Anchor Text", "Reason"])
        if content_data:
            for l in content_data.get("internal_links", []):
                ws_links.append([
                    l.get("source_url"),
                    l.get("target_url"),
                    l.get("anchor_text"),
                    l.get("reason")
                ])

        # Sheet 6: Competitor On-Page
        if research_data and research_data.get("competitor_comparison"):
            ws_comp = wb.create_sheet(title="Competitor Comparison")
            ws_comp.append(["Notice: on-page comparison only — no traffic or backlink data", "Volume / KD: n/a — requires keyword data provider"])
            ws_comp.append(["Domain", "Pages Analyzed", "Schema Types Detected", "Headings Found"])
            for c in research_data["competitor_comparison"].get("competitors", []):
                ws_comp.append([
                    c.get("domain"),
                    c.get("pages_crawled", 0),
                    ", ".join(c.get("schema_types", [])),
                    len(c.get("headings_sample", []))
                ])

        # Sheet 7: PageSpeed (lab data (Lighthouse))
        if psi_data:
            ws_psi = wb.create_sheet(title="PageSpeed (lab data)")
            ws_psi.append(["PageSpeed & Core Web Vitals (lab data (Lighthouse))"])
            ws_psi.append(["URL", "Device", "Score [lab data (Lighthouse)]", "LCP (ms)", "CLS", "FCP (ms)", "TTFB (ms)"])
            for p in psi_data:
                ws_psi.append([
                    p.get("url", ""),
                    p.get("strategy", ""),
                    p.get("performance_score", ""),
                    p.get("lcp_ms", ""),
                    p.get("cls", ""),
                    p.get("fcp_ms", ""),
                    p.get("ttfb_ms", "")
                ])

        # Sheet 8: Code Fixes & Implementation (M5)
        if code_data:
            bundle = code_data.get("bundle", {})
            ws_code = wb.create_sheet(title="Code Fixes & Coverage")
            ws_code.append(["Target Platform", bundle.get("platform", "nextjs"), f"Generated Files: {len(bundle.get('artifacts', []))}"])
            ws_code.append(["ZIP Archive", f"seo-fixes-{job_id[:8]}.zip", "Includes README_APPLY.md, CHANGES.csv, provenance.json, validation_report.md"])
            ws_code.append([])
            ws_code.append(["--- FIX COVERAGE TABLE ---"])
            ws_code.append(["Issue ID", "Type", "Severity", "Fixability", "Resolving Artifacts"])
            for fc in bundle.get("fix_coverage", []):
                ws_code.append([
                    fc.get("issue_id", ""),
                    fc.get("issue_type", ""),
                    fc.get("severity", ""),
                    fc.get("fixability", ""),
                    ", ".join(fc.get("artifact_names", []))
                ])
            ws_code.append([])
            ws_code.append(["--- GENERATED CODE ARTIFACTS ---"])
            ws_code.append(["File Path", "Artifact Type", "Validation Status", "Reason / Detail", "Addressed Issues", "Addressed Tasks"])
            for a in bundle.get("artifacts", []):
                ws_code.append([
                    a.get("file_path", ""),
                    a.get("artifact_type", ""),
                    a.get("validation_status", "passed"),
                    a.get("validation_reason", ""),
                    ", ".join(a.get("source_issue_ids", [])),
                    ", ".join(a.get("source_task_ids", []))
                ])

        wb.save(file_path)
        return file_path
