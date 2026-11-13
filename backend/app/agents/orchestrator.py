import asyncio
import time
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Set

from app.core.config import settings
from app.core.db import DBManager, get_sqlite_conn
from app.crawler.engine import AsyncCrawler
from app.crawler.competitor_crawler import CompetitorCrawler
from app.services.pagespeed import run_pagespeed_pipeline
from app.agents.issue_rules import detect_issues_from_data
from app.agents.technical_agent import TechnicalAgent
from app.agents.monitor_agent import MonitorAgent
from app.agents.research_metrics import compute_research_metrics
from app.agents.research_agent import ResearchAgent
from app.agents.strategist_agent import StrategistAgent
from app.agents.content_agent import ContentAgent
from app.agents.code_agent import CodeGeneratorAgent
from app.agents.code_verifier import CodeVerifier
from app.agents.verifier import Verifier
from app.services.reporter import ReportExporter
from app.services.performance_metrics import compute_performance_metrics
from app.models.agent_schemas import TechnicalIssue, MonitorFinding, ResearchOpportunity

def is_cancelled(job_id: str) -> bool:
    j = DBManager.get_job(job_id)
    return bool(j and j.get("status") == "cancelled")

def check_cost_caps(job_id: str, current_cost: float) -> tuple[bool, str]:
    daily_cost = DBManager.get_daily_cost_usd()
    if current_cost >= settings.MAX_JOB_COST_USD:
        reason = f"MAX_JOB_COST_USD reached (${current_cost:.4f} >= ${settings.MAX_JOB_COST_USD:.2f})"
        try:
            if DBManager.get_job(job_id):
                DBManager.update_job(job_id, {"error": f"Cost cap reached: {reason}"})
        except Exception:
            pass
        return True, reason
    if daily_cost >= settings.DAILY_COST_CAP_USD:
        reason = f"DAILY_COST_CAP_USD reached (${daily_cost:.4f} >= ${settings.DAILY_COST_CAP_USD:.2f})"
        try:
            if DBManager.get_job(job_id):
                DBManager.update_job(job_id, {"error": f"Cost cap reached: {reason}"})
        except Exception:
            pass
        return True, reason
    return False, ""

async def run_full_pipeline(job_id: str, target_url: str, max_pages: int, project_id: Optional[str] = None, resume: bool = False):
    """
    Autonomous Multi-Agent SEO Pipeline (Milestone 1, 2, 3 & 4):
    1. Crawler Engine -> crawl_pages & crawl_links
    2. PageSpeed Insights -> psi_results
    3. Rule-Based Issue Detector -> candidates
    4. Technical Agent (LLM / fallback) -> TechnicalAgentReport
    5. Verifier (Audit technical issues) -> VerifierReport
    6. Fetch Google data (GSC query×page pairs & GA4) in parallel with Competitor Crawl
    7. Monitor Agent (LLM / fallback) -> MonitorReport + Verifier
    8. Research Engine & Research Agent -> research_snapshots + Verifier
    9. Strategist Agent (30-day plan) -> strategy_plans + Verifier
    10. Content Agent (briefs, rewrites, internal links) -> content_outputs + Verifier
    11. Reporter Agent -> PDF, CSV, XLSX exports (with DEMO DATA watermark if applicable)
    """
    try:
        total_job_cost = 0.0
        job = DBManager.get_job(job_id)
        if not job:
            return

        is_demo = bool(job.get("is_demo", 0))
        competitor_domains = []
        if job.get("competitor_domains"):
            try:
                comp_raw = job["competitor_domains"]
                competitor_domains = json.loads(comp_raw) if isinstance(comp_raw, str) else comp_raw
            except Exception:
                competitor_domains = []

        # -------------------------------------------------------------
        # Step 1: Crawler
        # -------------------------------------------------------------
        if is_cancelled(job_id):
            print(f"Pipeline cancelled before crawl for job {job_id}")
            return

        existing_pages = DBManager.get_crawl_pages(job_id, limit=2000) if resume else []
        if resume and existing_pages:
            print(f"Resuming job {job_id}: Reusing {len(existing_pages)} crawled pages.")
        else:
            DBManager.update_job(job_id, {"status": "crawling", "current_step": "crawling"})
            crawler = AsyncCrawler(job_id=job_id, target_url=target_url, max_pages=max_pages)
            await crawler.run()

        # -------------------------------------------------------------
        # Step 2: PageSpeed Insights
        # -------------------------------------------------------------
        if is_cancelled(job_id):
            print(f"Pipeline cancelled before PSI for job {job_id}")
            return

        existing_psi = DBManager.get_psi_results(job_id) if resume else []
        if resume and existing_psi:
            print(f"Resuming job {job_id}: Reusing PSI results.")
        else:
            DBManager.update_job(job_id, {"status": "pagespeed", "current_step": "pagespeed"})
            try:
                job_rec = DBManager.get_job(job_id)
                ignore_cache = bool(job_rec.get("fresh_psi")) if job_rec else False
                await run_pagespeed_pipeline(job_id, target_url, ignore_cache=ignore_cache)
            except Exception as e:
                print(f"PSI non-fatal warning: {e}")
                DBManager.update_job(job_id, {"psi_status": f"failed ({str(e)[:100]})"})

        # -------------------------------------------------------------
        # Step 3: Rule-Based Issue Detector & Technical Agent
        # -------------------------------------------------------------
        DBManager.update_job(job_id, {"status": "analysing", "current_step": "analysing_technical"})
        crawl_pages = DBManager.get_crawl_pages(job_id, limit=2000)
        
        conn = get_sqlite_conn()
        c = conn.cursor()
        c.execute("SELECT * FROM crawl_links WHERE job_id = ?", (job_id,))
        crawl_links = [dict(r) for r in c.fetchall()]
        conn.close()

        psi_results = DBManager.get_psi_results(job_id)
        job_record = DBManager.get_job(job_id) or {}
        sitemap_entries = []
        if job_record.get("sitemap_entries_json"):
            try:
                sitemap_entries = json.loads(job_record["sitemap_entries_json"])
            except Exception:
                sitemap_entries = []

        candidates = detect_issues_from_data(
            crawl_pages,
            crawl_links,
            psi_results,
            sitemap_entries=sitemap_entries,
        )

        tech_start = datetime.now(timezone.utc).isoformat()
        if is_cancelled(job_id):
            print(f"Pipeline cancelled before Technical Agent for job {job_id}")
            return
        cap_active, cap_reason = check_cost_caps(job_id, total_job_cost)
        tech_report, tech_mode, tech_cost, tech_failure_reason, tech_model_used = await TechnicalAgent.run(
            candidates,
            force_fallback=cap_active
        )
        tech_finish = datetime.now(timezone.utc).isoformat()
        total_job_cost += tech_cost
        DBManager.update_job(job_id, {"cost_usd": total_job_cost})
        cap_active, cap_reason = check_cost_caps(job_id, total_job_cost)

        DBManager.save_agent_run({
            "job_id": job_id,
            "agent": "technical",
            "status": "done",
            "mode": tech_mode,
            "model": tech_model_used,
            "failure_reason": tech_failure_reason,
            "tokens_prompt": getattr(tech_report, "tokens_prompt", 0),
            "tokens_completion": getattr(tech_report, "tokens_completion", 0),
            "cost_usd": tech_cost,
            "input_ref": [f"candidates_count:{len(candidates)}"],
            "output_json": tech_report.model_dump(),
            "confidence": 0.95,
            "started_at": tech_start,
            "finished_at": tech_finish
        })

        # -------------------------------------------------------------
        # Step 4: Verifier Agent (Technical Issues)
        # -------------------------------------------------------------
        DBManager.update_job(job_id, {"status": "verifying", "current_step": "verifying_technical"})
        ver_start = datetime.now(timezone.utc).isoformat()
        verifier_report = Verifier.verify_issues(
            job_id,
            tech_report.issues,
            candidates=candidates,
            dismissed=tech_report.dismissed
        )
        ver_finish = datetime.now(timezone.utc).isoformat()

        DBManager.save_agent_run({
            "job_id": job_id,
            "agent": "verifier",
            "status": "done",
            "mode": "deterministic",
            "input_ref": [f"technical_issues:{len(tech_report.issues)}"],
            "output_json": verifier_report.model_dump(),
            "confidence": 1.0,
            "started_at": ver_start,
            "finished_at": ver_finish
        })

        verified_tech_issues = verifier_report.verified_issues

        # -------------------------------------------------------------
        # Step 5: Fetch Google Data & Parallel Competitor Crawl
        # -------------------------------------------------------------
        DBManager.update_job(job_id, {"status": "fetching_data", "current_step": "fetching_google_data"})

        # Launch competitor crawler in parallel if domains provided
        comp_tasks = []
        if competitor_domains:
            for c_dom in competitor_domains[:3]:
                comp_tasks.append(CompetitorCrawler(job_id, c_dom, max_pages=30).run())
        
        if comp_tasks:
            try:
                await asyncio.gather(*comp_tasks, return_exceptions=True)
            except Exception as e:
                print(f"Competitor crawl non-fatal warning: {e}")

        # Fetch / seed Google Data
        perf_snapshot = DBManager.get_performance_snapshot(job_id)
        if not perf_snapshot and is_demo:
            # Seed demo performance and query pages
            curr_q = [
                {"key": "web design agency", "clicks": 180, "impressions": 2400, "ctr": 7.5, "position": 4.2},
                {"key": "nextjs development services", "clicks": 95, "impressions": 1100, "ctr": 8.6, "position": 3.8},
                {"key": "seo optimization pricing", "clicks": 32, "impressions": 1450, "ctr": 2.2, "position": 11.4},
                {"key": "ecommerce store developers", "clicks": 14, "impressions": 920, "ctr": 1.5, "position": 14.8},
                {"key": "ai web automation", "clicks": 8, "impressions": 850, "ctr": 0.9, "position": 16.2},
                {"key": "how to optimize website speed", "clicks": 25, "impressions": 1900, "ctr": 1.3, "position": 12.0},
                {"key": "what is technical seo audit", "clicks": 40, "impressions": 3100, "ctr": 1.2, "position": 9.5},
            ]
            prev_q = [
                {"key": "web design agency", "clicks": 235, "impressions": 2600, "ctr": 9.0, "position": 3.9},
                {"key": "nextjs development services", "clicks": 70, "impressions": 900, "ctr": 7.8, "position": 4.1},
                {"key": "seo optimization pricing", "clicks": 30, "impressions": 1300, "ctr": 2.3, "position": 12.0},
                {"key": "ecommerce store developers", "clicks": 28, "impressions": 950, "ctr": 2.9, "position": 13.5},
                {"key": "ai web automation", "clicks": 6, "impressions": 700, "ctr": 0.8, "position": 17.0},
                {"key": "how to optimize website speed", "clicks": 10, "impressions": 1500, "ctr": 0.6, "position": 15.0},
                {"key": "what is technical seo audit", "clicks": 35, "impressions": 2900, "ctr": 1.2, "position": 10.0},
            ]
            first_page = crawl_pages[0]["url"] if crawl_pages else target_url
            curr_p = [
                {"key": first_page, "clicks": 140, "impressions": 1800},
                {"key": f"{target_url.rstrip('/')}/services", "clicks": 12, "impressions": 400},
            ]
            prev_p = [
                {"key": first_page, "clicks": 120, "impressions": 1700},
                {"key": f"{target_url.rstrip('/')}/services", "clicks": 45, "impressions": 550},
            ]
            curr_ga4 = {"sessions": 3120, "engaged_sessions": 2100, "active_users": 2800, "key_events": 84}
            prev_ga4 = {"sessions": 3450, "engaged_sessions": 2250, "active_users": 3100, "key_events": 92}

            metrics = compute_performance_metrics(curr_q, prev_q, curr_p, prev_p, curr_ga4, prev_ga4)
            DBManager.save_performance_snapshot(job_id, metrics)
            perf_snapshot = DBManager.get_performance_snapshot(job_id)

            # Seed GSC query×page pairs
            gsc_pairs = [
                {"query": "web design agency", "page": first_page, "clicks": 180, "impressions": 2400, "ctr": 7.5, "position": 4.2},
                {"query": "nextjs development services", "page": f"{target_url.rstrip('/')}/services", "clicks": 95, "impressions": 1100, "ctr": 8.6, "position": 3.8},
                {"query": "seo optimization pricing", "page": first_page, "clicks": 32, "impressions": 1450, "ctr": 2.2, "position": 11.4},
                {"query": "ecommerce store developers", "page": f"{target_url.rstrip('/')}/services", "clicks": 14, "impressions": 920, "ctr": 1.5, "position": 14.8},
                {"query": "how to optimize website speed", "page": first_page, "clicks": 25, "impressions": 1900, "ctr": 1.3, "position": 12.0},
                {"query": "what is technical seo audit", "page": f"{target_url.rstrip('/')}/blog/audit", "clicks": 40, "impressions": 3100, "ctr": 1.2, "position": 9.5},
            ]
            DBManager.save_gsc_query_pages(project_id or job_id, gsc_pairs)

        # -------------------------------------------------------------
        # Step 6: Monitor Agent (Performance Findings)
        # -------------------------------------------------------------
        verified_perf_findings: List[MonitorFinding] = []
        if perf_snapshot and perf_snapshot.get("snapshot_json"):
            snapshot_data = perf_snapshot["snapshot_json"]
            snapshot_id = perf_snapshot["id"]

            DBManager.update_job(job_id, {"status": "analysing", "current_step": "analysing_performance"})
            mon_start = datetime.now(timezone.utc).isoformat()
            mon_report, mon_mode, mon_cost, mon_err, mon_model = await MonitorAgent.run(snapshot_id, snapshot_data)
            mon_finish = datetime.now(timezone.utc).isoformat()
            total_job_cost += mon_cost

            DBManager.save_agent_run({
                "job_id": job_id,
                "agent": "monitor",
                "status": "done",
                "mode": mon_mode,
                "model": mon_model,
                "failure_reason": mon_err,
                "tokens_prompt": getattr(mon_report, "tokens_prompt", 0),
                "tokens_completion": getattr(mon_report, "tokens_completion", 0),
                "cost_usd": mon_cost,
                "input_ref": [f"snapshot:{snapshot_id}"],
                "output_json": mon_report.model_dump(),
                "confidence": 0.95,
                "started_at": mon_start,
                "finished_at": mon_finish
            })

            mon_ver_report = Verifier.verify_monitor_findings(
                snapshot_id=snapshot_id,
                snapshot=snapshot_data,
                findings=mon_report.findings,
                summary=mon_report.summary
            )
            DBManager.save_agent_run({
                "job_id": job_id,
                "agent": "verifier_monitor",
                "status": "done",
                "mode": "deterministic",
                "input_ref": [f"monitor_findings:{len(mon_report.findings)}"],
                "output_json": mon_ver_report.model_dump(),
                "confidence": 1.0,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat()
            })
            verified_perf_findings = mon_ver_report.verified_findings

        # -------------------------------------------------------------
        # Step 7: Research Metrics Engine & Research Agent (M4)
        # -------------------------------------------------------------
        DBManager.update_job(job_id, {"status": "researching", "current_step": "researching"})
        gsc_query_pages = DBManager.get_gsc_query_pages(project_id or job_id)
        competitor_pages = DBManager.get_competitor_pages(job_id)

        research_metrics = compute_research_metrics(
            gsc_rows=gsc_query_pages,
            crawl_pages=crawl_pages,
            competitor_pages=competitor_pages,
            brand_name=""
        )
        research_snapshot_id = DBManager.save_research_snapshot(job_id, research_metrics)

        cap_active, cap_reason = check_cost_caps(job_id, total_job_cost)
        res_start = datetime.now(timezone.utc).isoformat()
        res_report, res_mode, res_cost, res_err, res_model = await ResearchAgent.run(
            research_snapshot_id,
            research_metrics,
            force_fallback=cap_active
        )
        res_finish = datetime.now(timezone.utc).isoformat()
        total_job_cost += res_cost
        DBManager.update_job(job_id, {"cost_usd": total_job_cost})
        cap_active, cap_reason = check_cost_caps(job_id, total_job_cost)

        DBManager.save_agent_run({
            "job_id": job_id,
            "agent": "research",
            "status": "done",
            "mode": res_mode,
            "model": res_model,
            "failure_reason": res_err,
            "tokens_prompt": getattr(res_report, "tokens_prompt", 0),
            "tokens_completion": getattr(res_report, "tokens_completion", 0),
            "cost_usd": res_cost,
            "input_ref": [f"research_snapshot:{research_snapshot_id}"],
            "output_json": res_report.model_dump(),
            "confidence": 0.95,
            "started_at": res_start,
            "finished_at": res_finish
        })

        # Verify research opportunities
        res_ver_report = Verifier.verify_research_opportunities(
            snapshot_id=research_snapshot_id,
            snapshot=research_metrics,
            opportunities=res_report.opportunities
        )
        DBManager.save_agent_run({
            "job_id": job_id,
            "agent": "verifier_research",
            "status": "done",
            "mode": "deterministic",
            "input_ref": [f"research_opportunities:{len(res_report.opportunities)}"],
            "output_json": res_ver_report.model_dump(),
            "confidence": 1.0,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat()
        })
        verified_research_opps = res_ver_report.verified_opportunities

        # -------------------------------------------------------------
        # Step 8: Strategist Agent (M4)
        # -------------------------------------------------------------
        DBManager.update_job(job_id, {"status": "strategizing", "current_step": "strategizing"})
        cap_active, cap_reason = check_cost_caps(job_id, total_job_cost)
        strat_start = datetime.now(timezone.utc).isoformat()
        strat_report, strat_mode, strat_cost, strat_err, strat_model = await StrategistAgent.run(
            verified_tech=verified_tech_issues,
            verified_perf=verified_perf_findings,
            verified_research=verified_research_opps,
            force_fallback=cap_active
        )
        strat_finish = datetime.now(timezone.utc).isoformat()
        total_job_cost += strat_cost
        DBManager.update_job(job_id, {"cost_usd": total_job_cost})
        cap_active, cap_reason = check_cost_caps(job_id, total_job_cost)

        DBManager.save_agent_run({
            "job_id": job_id,
            "agent": "strategist",
            "status": "done",
            "mode": strat_mode,
            "model": strat_model,
            "failure_reason": strat_err,
            "tokens_prompt": getattr(strat_report, "tokens_prompt", 0),
            "tokens_completion": getattr(strat_report, "tokens_completion", 0),
            "cost_usd": strat_cost,
            "input_ref": [
                f"tech:{len(verified_tech_issues)}",
                f"perf:{len(verified_perf_findings)}",
                f"res:{len(verified_research_opps)}"
            ],
            "output_json": strat_report.model_dump(),
            "confidence": 0.95,
            "started_at": strat_start,
            "finished_at": strat_finish
        })

        # Verify strategy tasks
        verified_source_ids: Set[str] = (
            {i.id for i in verified_tech_issues} |
            {f.id for f in verified_perf_findings} |
            {o.id for o in verified_research_opps}
        )
        rejected_source_ids: Set[str] = (
            {r.get("id") or r.get("issue_id") or r.get("finding_id") for r in verifier_report.rejected_issues} |
            {r.get("id") or r.get("finding_id") for r in (mon_ver_report.rejected_findings if perf_snapshot else [])} |
            {r.get("id") for r in res_ver_report.rejected_opportunities}
        )
        strat_ver_report = Verifier.verify_strategy_tasks(
            tasks=strat_report.tasks,
            verified_source_ids=verified_source_ids,
            rejected_source_ids=rejected_source_ids
        )
        DBManager.save_agent_run({
            "job_id": job_id,
            "agent": "verifier_strategy",
            "status": "done",
            "mode": "deterministic",
            "input_ref": [f"strategy_tasks:{len(strat_report.tasks)}"],
            "output_json": strat_ver_report.model_dump(),
            "confidence": 1.0,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat()
        })

        verified_strat_tasks = strat_ver_report.verified_tasks
        DBManager.save_strategy_plan(job_id, {
            "tasks": [t.model_dump() for t in verified_strat_tasks],
            "summary": strat_report.summary
        })

        # -------------------------------------------------------------
        # Step 9: Content Agent (M4)
        # -------------------------------------------------------------
        DBManager.update_job(job_id, {"status": "content_generation", "current_step": "content_generation"})
        cont_start = datetime.now(timezone.utc).isoformat()
        if is_cancelled(job_id):
            print(f"Pipeline cancelled before Content Agent for job {job_id}")
            return
        cap_active, cap_reason = check_cost_caps(job_id, total_job_cost)
        cont_report, cont_mode, cont_cost, cont_err, cont_model = await ContentAgent.run(
            verified_research=verified_research_opps,
            crawl_pages=crawl_pages,
            crawl_links=crawl_links,
            research_snapshot=research_metrics,
            competitor_pages=competitor_pages,
            force_fallback=cap_active
        )
        cont_finish = datetime.now(timezone.utc).isoformat()
        total_job_cost += cont_cost
        DBManager.update_job(job_id, {"cost_usd": total_job_cost})
        cap_active, cap_reason = check_cost_caps(job_id, total_job_cost)

        DBManager.save_agent_run({
            "job_id": job_id,
            "agent": "content",
            "status": "done",
            "mode": cont_mode,
            "model": cont_model,
            "failure_reason": cont_err,
            "tokens_prompt": getattr(cont_report, "tokens_prompt", 0),
            "tokens_completion": getattr(cont_report, "tokens_completion", 0),
            "cost_usd": cont_cost,
            "input_ref": [f"research_opps:{len(verified_research_opps)}"],
            "output_json": cont_report.model_dump(),
            "confidence": 0.95,
            "started_at": cont_start,
            "finished_at": cont_finish
        })

        # Verify content outputs
        cont_ver_report = Verifier.verify_content_outputs(
            report=cont_report,
            crawl_pages=crawl_pages,
            crawl_links=crawl_links,
            research_snapshot=research_metrics,
            project_name=job.get("project_name") or job.get("target_url")
        )
        DBManager.save_agent_run({
            "job_id": job_id,
            "agent": "verifier_content",
            "status": "done",
            "mode": "deterministic",
            "input_ref": [f"briefs:{len(cont_report.briefs)}", f"rewrites:{len(cont_report.rewrites)}"],
            "output_json": cont_ver_report.model_dump(),
            "confidence": 1.0,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat()
        })

        verified_content_data = {
            "briefs": [b.model_dump() for b in cont_ver_report.verified_briefs],
            "rewrites": [r.model_dump() for r in cont_ver_report.verified_rewrites],
            "internal_links": [l.model_dump() for l in cont_ver_report.verified_internal_links],
            "summary": cont_report.summary
        }
        DBManager.save_content_output(job_id, verified_content_data)

        # -------------------------------------------------------------
        # Step 10: Code Generation & Code Verification (M5)
        # -------------------------------------------------------------
        code_output_data = None
        DBManager.update_job(job_id, {"status": "code_generation", "current_step": "code_generation"})
        try:
            # Re-fetch latest job to check for detected platform or user override
            job = DBManager.get_job(job_id) or job
            platform = job.get("platform") or job.get("detected_platform") or "nextjs"
            platform_confidence = float(job.get("platform_confidence") or job.get("detected_platform_confidence") or 1.0)
            router_type = job.get("router_type") or "app"

            code_start = datetime.now(timezone.utc).isoformat()
            code_bundle, code_mode, code_cost, code_err, code_model = await CodeGeneratorAgent.run(
                platform=platform,
                platform_confidence=platform_confidence,
                verified_tech_issues=verified_tech_issues,
                strategy_tasks=verified_strat_tasks,
                crawl_pages=crawl_pages,
                crawl_links=crawl_links,
                verified_rewrites=cont_ver_report.verified_rewrites,
                internal_links=cont_ver_report.verified_internal_links,
                router_type=router_type,
                is_demo=is_demo
            )
            code_finish = datetime.now(timezone.utc).isoformat()
            total_job_cost += code_cost

            # Run deterministic Code Verifier
            code_verifier_rep = CodeVerifier.verify_code_bundle(
                bundle=code_bundle,
                crawl_pages=crawl_pages,
                crawl_links=crawl_links,
                is_demo=is_demo,
                verified_tech_issues=verified_tech_issues
            )

            code_output_data = {
                "bundle": code_bundle.model_dump(),
                "verifier": code_verifier_rep.model_dump()
            }
            DBManager.save_code_output(job_id, code_output_data)

            DBManager.save_agent_run({
                "job_id": job_id,
                "agent": "code_generator",
                "status": "done",
                "mode": code_mode,
                "model": code_model,
                "failure_reason": code_err,
                "tokens_prompt": 0,
                "tokens_completion": 0,
                "cost_usd": code_cost,
                "input_ref": [f"pages:{len(crawl_pages)}", f"issues:{len(verified_tech_issues)}"],
                "output_json": code_bundle.model_dump(),
                "confidence": 1.0,
                "started_at": code_start,
                "finished_at": code_finish
            })

            DBManager.save_agent_run({
                "job_id": job_id,
                "agent": "verifier_code",
                "status": "done",
                "mode": "deterministic",
                "input_ref": [f"artifacts:{len(code_bundle.artifacts)}"],
                "output_json": code_verifier_rep.model_dump(),
                "confidence": 1.0,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat()
            })

        except Exception as e:
            print(f"Code generation unavailable: {e}")
            import traceback
            traceback.print_exc()
            DBManager.save_agent_run({
                "job_id": job_id,
                "agent": "code_generator",
                "status": "failed",
                "mode": "deterministic",
                "failure_reason": f"Code generation unavailable: {e}",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat()
            })

        # -------------------------------------------------------------
        # Step 11: Reporter Agent (Exports)
        # -------------------------------------------------------------
        DBManager.update_job(job_id, {"status": "reporting", "current_step": "reporting"})
        verified_issues_list = [i.model_dump() for i in verified_tech_issues]
        perf_data = perf_snapshot.get("snapshot_json") if perf_snapshot else None
        strategy_data = {"tasks": [t.model_dump() for t in verified_strat_tasks], "summary": strat_report.summary}

        pdf_path = ReportExporter.generate_pdf(
            job_id=job_id,
            target_url=target_url,
            verified_issues=verified_issues_list,
            performance_data=perf_data,
            strategy_data=strategy_data,
            content_data=verified_content_data,
            research_data=research_metrics,
            code_data=code_output_data,
            is_demo=is_demo
        )
        csv_path = ReportExporter.generate_csv(
            job_id=job_id,
            verified_issues=verified_issues_list,
            performance_data=perf_data,
            strategy_data=strategy_data,
            content_data=verified_content_data,
            research_data=research_metrics,
            code_data=code_output_data,
            is_demo=is_demo
        )
        xlsx_path = ReportExporter.generate_xlsx(
            job_id=job_id,
            target_url=target_url,
            verified_issues=verified_issues_list,
            performance_data=perf_data,
            strategy_data=strategy_data,
            content_data=verified_content_data,
            research_data=research_metrics,
            code_data=code_output_data,
            is_demo=is_demo
        )

        DBManager.save_report_record(job_id, pdf_path, "pdf")
        DBManager.save_report_record(job_id, csv_path, "csv")
        DBManager.save_report_record(job_id, xlsx_path, "xlsx")

        # Milestone M6: Populate review items for owner approval workflow
        try:
            DBManager.populate_review_items_for_job(job_id)
        except Exception as rev_err:
            print(f"Warning: Failed to populate review items: {rev_err}")

        # Mark completed
        DBManager.update_job(job_id, {
            "status": "completed",
            "current_step": "completed",
            "cost_usd": round(total_job_cost, 6)
        })

    except Exception as e:
        print(f"Pipeline failure for job {job_id}: {e}")
        import traceback
        traceback.print_exc()
        DBManager.update_job(job_id, {
            "status": "failed",
            "error": str(e)
        })
