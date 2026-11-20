import json
import csv
import os
from typing import Dict, Any, List, Optional, Tuple, Set
from urllib.parse import urlparse
from app.core.classification import classify_page_type
from app.core.db import DBManager

def normalize_url(u: str) -> str:
    """Normalizes URL for deterministic matching across jobs."""
    if not u:
        return ""
    p = urlparse(u)
    path = p.path.rstrip("/")
    if not path:
        path = "/"
    return f"{p.scheme}://{p.netloc.lower()}{path}"

class JobComparator:
    @staticmethod
    def compare(before_job_id: str, after_job_id: str) -> Dict[str, Any]:
        """Compares two crawl/audit jobs deterministically.
        Rules:
        - Compare ONLY URLs crawled in BOTH jobs.
        - Issues on URLs missing from the later crawl are categorized as 'not re-checked', NEVER 'fixed'.
        - Report fixed / new / unchanged / not re-checked separately.
        - If either job is flagged incomplete, mark comparison 'incomplete' and do NOT generate a narrative claiming issues were resolved.
        """
        before_job = DBManager.get_job(before_job_id)
        after_job = DBManager.get_job(after_job_id)

        if not before_job or not after_job:
            raise ValueError("One or both jobs not found")

        # Crawled pages and URL sets
        before_pages = DBManager.get_crawl_pages(before_job_id, limit=2000)
        after_pages = DBManager.get_crawl_pages(after_job_id, limit=2000)
        before_crawled_urls: Set[str] = {normalize_url(p.get("url", "")) for p in before_pages if p.get("url")}
        after_crawled_urls: Set[str] = {normalize_url(p.get("url", "")) for p in after_pages if p.get("url")}

        before_pages_cnt = before_job.get("pages_crawled", len(before_pages))
        after_pages_cnt = after_job.get("pages_crawled", len(after_pages))
        pages_delta = after_pages_cnt - before_pages_cnt

        is_incomplete = False
        incomplete_reasons: List[str] = []

        if before_job.get("status") != "completed":
            is_incomplete = True
            incomplete_reasons.append(f"Baseline job ({before_job_id[:8]}) status is '{before_job.get('status')}'")
        if after_job.get("status") != "completed":
            is_incomplete = True
            incomplete_reasons.append(f"Subsequent job ({after_job_id[:8]}) status is '{after_job.get('status')}'")

        if before_job.get("completeness_status") == "possibly incomplete" or before_job.get("crawl_incomplete") == 1:
            is_incomplete = True
            incomplete_reasons.append(f"Baseline job ({before_job_id[:8]}) is marked possibly incomplete")
        if after_job.get("completeness_status") == "possibly incomplete" or after_job.get("crawl_incomplete") == 1:
            is_incomplete = True
            incomplete_reasons.append(f"Subsequent job ({after_job_id[:8]}) is marked possibly incomplete")

        if before_pages_cnt > 0 and after_pages_cnt < before_pages_cnt * 0.8:
            is_incomplete = True
            drop_pct = (before_pages_cnt - after_pages_cnt) / before_pages_cnt * 100
            incomplete_reasons.append(f"Pages dropped by {drop_pct:.1f}% ({after_pages_cnt} vs {before_pages_cnt} pages)")

        # 1. Fetch Verified Issues from verifier runs
        def get_verified_issues(jid: str) -> List[Dict[str, Any]]:
            runs = DBManager.get_agent_runs(jid)
            for r in runs:
                if r.get("agent") == "verifier" and r.get("status") == "done":
                    out = r.get("output_json", {})
                    if isinstance(out, str):
                        try:
                            out = json.loads(out)
                        except Exception:
                            out = {}
                    return out.get("verified_issues", [])
            return []

        before_raw_issues = get_verified_issues(before_job_id)
        after_raw_issues = get_verified_issues(after_job_id)

        # Build issue map: (type, normalized_url) -> issue
        def build_issue_map(issues: List[Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
            imap = {}
            for iss in issues:
                itype = iss.get("type", "")
                urls = iss.get("urls", [])
                if not urls:
                    imap[(itype, "")] = iss
                for u in urls:
                    norm = normalize_url(u)
                    imap[(itype, norm)] = iss
            return imap

        before_map = build_issue_map(before_raw_issues)
        after_map = build_issue_map(after_raw_issues)

        fixed_issues: List[Dict[str, Any]] = []
        unchanged_issues: List[Dict[str, Any]] = []
        not_rechecked_issues: List[Dict[str, Any]] = []

        for (itype, norm_url), iss in sorted(before_map.items()):
            if norm_url:
                # Issue is tied to a specific URL
                if norm_url not in after_crawled_urls:
                    # URL was missing from the subsequent crawl -> NOT RE-CHECKED
                    not_rechecked_issues.append({
                        "type": itype,
                        "url": norm_url,
                        "issue": iss,
                        "status": "not_rechecked",
                        "reason": "URL was not crawled in subsequent audit"
                    })
                elif (itype, norm_url) in after_map:
                    # Crawled in both, issue still present -> UNCHANGED
                    unchanged_issues.append({
                        "type": itype,
                        "url": norm_url,
                        "issue": after_map[(itype, norm_url)],
                        "status": "unchanged"
                    })
                else:
                    # Crawled in both, issue no longer present -> FIXED
                    fixed_issues.append({
                        "type": itype,
                        "url": norm_url,
                        "issue": iss,
                        "status": "fixed"
                    })
            else:
                # Domain-level issue (no specific URL)
                if (itype, "") in after_map:
                    unchanged_issues.append({
                        "type": itype,
                        "url": "",
                        "issue": after_map[(itype, "")],
                        "status": "unchanged"
                    })
                elif is_incomplete:
                    not_rechecked_issues.append({
                        "type": itype,
                        "url": "",
                        "issue": iss,
                        "status": "not_rechecked",
                        "reason": "Subsequent crawl incomplete"
                    })
                else:
                    fixed_issues.append({
                        "type": itype,
                        "url": "",
                        "issue": iss,
                        "status": "fixed"
                    })

        # New issues in after_job & Improvements (e.g. private pages gaining noindex)
        new_issues: List[Dict[str, Any]] = []
        improvements: List[Dict[str, Any]] = []

        for (itype, norm_url), iss in sorted(after_map.items()):
            if (itype, norm_url) not in before_map:
                # If noindex appeared on private pages, classify as IMPROVEMENT, not new issue
                if itype == "noindex_page" and classify_page_type(norm_url) == "utility":
                    improvements.append({
                        "type": "private_page_protected",
                        "url": norm_url,
                        "description": f"Private utility page correctly protected with noindex ({norm_url})",
                        "status": "improvement"
                    })
                    continue
                new_issues.append({
                    "type": itype,
                    "url": norm_url,
                    "issue": iss,
                    "status": "new"
                })

        # Check for pages that gained noindex protection between jobs
        before_page_map = {normalize_url(p.get("url", "")): p for p in before_pages if p.get("url")}
        after_page_map = {normalize_url(p.get("url", "")): p for p in after_pages if p.get("url")}
        for norm_url, ap in after_page_map.items():
            bp = before_page_map.get(norm_url)
            if bp and classify_page_type(norm_url) == "utility":
                bp_noindex = bp.get("indexability_status") in ("noindex_meta", "noindex_header")
                ap_noindex = ap.get("indexability_status") in ("noindex_meta", "noindex_header")
                if not bp_noindex and ap_noindex:
                    if not any(imp.get("url") == norm_url for imp in improvements):
                        improvements.append({
                            "type": "private_page_protected",
                            "url": norm_url,
                            "description": f"Private utility page correctly protected with noindex ({norm_url})",
                            "status": "improvement"
                        })

        if not_rechecked_issues:
            is_incomplete = True
            incomplete_reasons.append(
                f"{len(not_rechecked_issues)} issue(s) could not be re-checked because their URLs were not crawled in the subsequent audit"
            )

        # Severity totals
        def count_severities(issues: List[Dict[str, Any]]) -> Dict[str, int]:
            counts = {"high": 0, "medium": 0, "low": 0}
            for iss in issues:
                sev = iss.get("severity", "medium").lower()
                if sev in counts:
                    counts[sev] += 1
                else:
                    counts["medium"] += 1
            return counts

        before_sev = count_severities(before_raw_issues)
        after_sev = count_severities(after_raw_issues)
        sev_deltas = {
            "high": after_sev["high"] - before_sev["high"],
            "medium": after_sev["medium"] - before_sev["medium"],
            "low": after_sev["low"] - before_sev["low"],
        }

        # PSI scores
        before_psi = DBManager.get_psi_results(before_job_id)
        after_psi = DBManager.get_psi_results(after_job_id)

        def avg_psi_metric(psi_list: List[Dict[str, Any]], field: str) -> Optional[float]:
            vals = [p[field] for p in psi_list if p.get(field) is not None]
            return round(sum(vals) / len(vals), 2) if vals else None

        before_perf_score = avg_psi_metric(before_psi, "performance_score")
        after_perf_score = avg_psi_metric(after_psi, "performance_score")
        perf_delta = round(after_perf_score - before_perf_score, 2) if (before_perf_score is not None and after_perf_score is not None) else None

        before_lcp = avg_psi_metric(before_psi, "lcp_ms")
        after_lcp = avg_psi_metric(after_psi, "lcp_ms")
        lcp_delta = round(after_lcp - before_lcp, 2) if (before_lcp is not None and after_lcp is not None) else None

        before_cls = avg_psi_metric(before_psi, "cls")
        after_cls = avg_psi_metric(after_psi, "cls")
        cls_delta = round(after_cls - before_cls, 3) if (before_cls is not None and after_cls is not None) else None

        # Length tiers
        def get_length_tiers(jid: str) -> Dict[str, Dict[str, int]]:
            pages = DBManager.get_crawl_pages(jid, limit=2000)
            title_tiers = {"<30": 0, "30-60": 0, "61-65": 0, ">65": 0}
            meta_tiers = {"<70": 0, "70-155": 0, "156-170": 0, ">170": 0}
            for p in pages:
                t = p.get("title") or ""
                t_len = len(t.strip())
                if t_len < 30:
                    title_tiers["<30"] += 1
                elif t_len <= 60:
                    title_tiers["30-60"] += 1
                elif t_len <= 65:
                    title_tiers["61-65"] += 1
                else:
                    title_tiers[">65"] += 1

                m = p.get("meta_desc") or ""
                m_len = len(m.strip())
                if m_len < 70:
                    meta_tiers["<70"] += 1
                elif m_len <= 155:
                    meta_tiers["70-155"] += 1
                elif m_len <= 170:
                    meta_tiers["156-170"] += 1
                else:
                    meta_tiers[">170"] += 1
            return {"title_tiers": title_tiers, "meta_tiers": meta_tiers}

        before_tiers = get_length_tiers(before_job_id)
        after_tiers = get_length_tiers(after_job_id)

        # Deterministic narrative: If incomplete, DO NOT claim issues were resolved
        if is_incomplete:
            narrative = (
                f"Comparison between baseline audit ({before_job_id[:8]}) and subsequent audit ({after_job_id[:8]}) is INCOMPLETE: "
                f"The subsequent audit crawled only {after_pages_cnt} page(s) compared to {before_pages_cnt} in the baseline. "
                f"A total of {len(not_rechecked_issues)} issue(s) were NOT re-checked because their URLs were omitted or missing from the later crawl. "
                f"Due to the incomplete crawl ({'; '.join(incomplete_reasons)}), no conclusive fix claims can be verified until a full crawl is completed."
            )
        else:
            narrative = (
                f"Comparison between initial baseline audit ({before_job_id[:8]}) and subsequent audit ({after_job_id[:8]}): "
                f"A total of {len(fixed_issues)} technical issues were successfully resolved (fixed) across mutually crawled pages, "
                f"while {len(new_issues)} new issues were detected, and {len(unchanged_issues)} issues remain unchanged. "
                f"High-severity issues shifted by {sev_deltas['high']} (from {before_sev['high']} to {after_sev['high']}). "
                f"Total crawled pages changed from {before_pages_cnt} to {after_pages_cnt}."
            )

        return {
            "before_job_id": before_job_id,
            "after_job_id": after_job_id,
            "target_url": after_job.get("target_url") or before_job.get("target_url"),
            "is_incomplete": is_incomplete,
            "incomplete_reasons": incomplete_reasons,
            "issues": {
                "fixed_count": len(fixed_issues),
                "new_count": len(new_issues),
                "unchanged_count": len(unchanged_issues),
                "not_rechecked_count": len(not_rechecked_issues),
                "improvements_count": len(improvements),
                "improvements": improvements,
                "fixed": fixed_issues,
                "new": new_issues,
                "unchanged": unchanged_issues,
                "not_rechecked": not_rechecked_issues,
            },
            "severity_totals": {
                "before": before_sev,
                "after": after_sev,
                "delta": sev_deltas,
            },
            "page_counts": {
                "before": before_pages_cnt,
                "after": after_pages_cnt,
                "delta": pages_delta,
            },
            "psi_changes": {
                "performance_score": {"before": before_perf_score, "after": after_perf_score, "delta": perf_delta},
                "lcp_ms": {"before": before_lcp, "after": after_lcp, "delta": lcp_delta},
                "cls": {"before": before_cls, "after": after_cls, "delta": cls_delta},
            },
            "length_tiers": {
                "before": before_tiers,
                "after": after_tiers,
            },
            "narrative": narrative
        }

    @staticmethod
    def export_csv(comparison: Dict[str, Any], output_path: str) -> str:
        """Exports Before/After issue comparison into CSV."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Comparison Status", "Issue Type", "URL", "Severity", "Impact / Notes"])

            for item in comparison["issues"]["fixed"]:
                iss = item["issue"]
                writer.writerow(["FIXED", item["type"], item["url"], iss.get("severity", ""), iss.get("impact", "")])

            for item in comparison["issues"].get("improvements", []):
                writer.writerow(["IMPROVEMENT", item.get("type", "improvement"), item.get("url", ""), "POSITIVE", item.get("description", "")])

            for item in comparison["issues"]["new"]:
                iss = item["issue"]
                writer.writerow(["NEW", item["type"], item["url"], iss.get("severity", ""), iss.get("impact", "")])

            for item in comparison["issues"]["unchanged"]:
                iss = item["issue"]
                writer.writerow(["UNCHANGED", item["type"], item["url"], iss.get("severity", ""), iss.get("impact", "")])

            for item in comparison["issues"]["not_rechecked"]:
                iss = item["issue"]
                writer.writerow(["NOT_RECHECKED", item["type"], item["url"], iss.get("severity", ""), item.get("reason", "")])

        return output_path

    @staticmethod
    def export_pdf(comparison: Dict[str, Any], output_path: str) -> str:
        """Exports Before/After comparison into a clean PDF."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors

        doc = SimpleDocTemplate(output_path, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
        styles = getSampleStyleSheet()
        elements = []

        title_style = ParagraphStyle("TitleStyle", parent=styles["Heading1"], fontSize=18, textColor=colors.HexColor("#1e1b4b"), spaceAfter=10)
        h2_style = ParagraphStyle("H2Style", parent=styles["Heading2"], fontSize=13, textColor=colors.HexColor("#312e81"), spaceBefore=12, spaceAfter=6)
        body_style = ParagraphStyle("BodyStyle", parent=styles["Normal"], fontSize=9, leading=12, textColor=colors.HexColor("#1f2937"))

        elements.append(Paragraph("SEO Before / After Audit Comparison", title_style))
        elements.append(Paragraph(f"<b>Target Domain:</b> {comparison.get('target_url')}<br/><b>Baseline Job:</b> {comparison['before_job_id']}<br/><b>Follow-up Job:</b> {comparison['after_job_id']}", body_style))
        elements.append(Spacer(1, 10))

        if comparison.get("is_incomplete"):
            warn_style = ParagraphStyle("WarnStyle", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#b91c1c"))
            elements.append(Paragraph(f"<b>WARNING (INCOMPLETE COMPARISON):</b> {'; '.join(comparison.get('incomplete_reasons', []))}", warn_style))
            elements.append(Spacer(1, 8))

        elements.append(Paragraph("<b>Executive Summary:</b>", h2_style))
        elements.append(Paragraph(comparison["narrative"], body_style))
        elements.append(Spacer(1, 12))

        # Metrics Table
        sev_d = comparison["severity_totals"]
        pages_d = comparison["page_counts"]
        table_data = [
            ["Metric", "Before", "After", "Delta"],
            ["Crawled Pages", str(pages_d["before"]), str(pages_d["after"]), f"{pages_d['delta']:+d}"],
            ["High Severity Issues", str(sev_d["before"]["high"]), str(sev_d["after"]["high"]), f"{sev_d['delta']['high']:+d}"],
            ["Medium Severity Issues", str(sev_d["before"]["medium"]), str(sev_d["after"]["medium"]), f"{sev_d['delta']['medium']:+d}"],
            ["Low Severity Issues", str(sev_d["before"]["low"]), str(sev_d["after"]["low"]), f"{sev_d['delta']['low']:+d}"],
            ["Resolved (Fixed) Issues", "-", "-", str(comparison["issues"]["fixed_count"])],
            ["New Issues Detected", "-", "-", str(comparison["issues"]["new_count"])],
            ["Unchanged Issues", "-", "-", str(comparison["issues"]["unchanged_count"])],
            ["Not Re-checked (URL Missing)", "-", "-", str(comparison["issues"]["not_rechecked_count"])],
        ]

        t = Table(table_data, colWidths=[180, 80, 80, 80])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#e0e7ff")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor("#1e1b4b")),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ('PADDING', (0, 0), (-1, -1), 5),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 14))

        # Fixed Issues List
        elements.append(Paragraph("<b>Fixed Issues (Resolved Across Mutually Crawled Pages):</b>", h2_style))
        if comparison["issues"]["fixed"]:
            fixed_rows = [["Type", "URL"]]
            for f in comparison["issues"]["fixed"][:15]:
                fixed_rows.append([f["type"], f["url"][:60]])
            ft = Table(fixed_rows, colWidths=[150, 270])
            ft.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#dcfce7")),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor("#14532d")),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ('PADDING', (0, 0), (-1, -1), 4),
            ]))
            elements.append(ft)
        else:
            elements.append(Paragraph("No verified issues were fixed on mutually crawled pages.", body_style))

        # Not Re-checked List
        if comparison["issues"]["not_rechecked"]:
            elements.append(Spacer(1, 10))
            elements.append(Paragraph("<b>Not Re-checked Issues (Omitted / Un-crawled URLs):</b>", h2_style))
            nr_rows = [["Type", "URL", "Reason"]]
            for nr in comparison["issues"]["not_rechecked"][:15]:
                nr_rows.append([nr["type"], nr["url"][:50], nr.get("reason", "")[:35]])
            nrt = Table(nr_rows, colWidths=[120, 180, 120])
            nrt.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#fef3c7")),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor("#92400e")),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ('PADDING', (0, 0), (-1, -1), 4),
            ]))
            elements.append(nrt)

        doc.build(elements)
        return output_path
