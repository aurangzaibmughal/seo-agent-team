import os
import json
from collections import Counter
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
from fastapi.responses import FileResponse, Response
from typing import List, Dict, Any, Optional

from app.models.schemas import JobCreate
from app.models.agent_schemas import (
    TechnicalIssue, StrategyTask, OnPageRewrite, InternalLinkSuggestion, GeneratedArtifact
)
from app.core.config import settings
from app.core.db import DBManager, get_sqlite_conn
from app.agents.orchestrator import run_full_pipeline
from app.agents.verifier import Verifier
from app.agents.monitor_agent import MonitorAgent
from app.services.reporter import ReportExporter
from app.services.performance_metrics import compute_performance_metrics
from app.core.security import validate_safe_url, SSRFSecurityError, job_creation_limiter, get_client_ip
from fastapi import Request

router = APIRouter(prefix="/api/jobs", tags=["Jobs & Agents"])

@router.post("", response_model=Dict[str, Any])
async def create_job(payload: JobCreate, background_tasks: BackgroundTasks, request: Request):
    # 1. Rate limit check (Max 5 jobs per minute per client)
    client_ip = get_client_ip(request)
    allowed, retry_after = job_creation_limiter.is_allowed(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: maximum 5 jobs per minute. Please retry after {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)}
        )

    # 2. Production Demo Guard
    if settings.ENVIRONMENT == "production" and payload.is_demo:
        raise HTTPException(status_code=400, detail="Demo mode seeding is disabled in production environment.")

    url = payload.url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # 3. SSRF Guard
    try:
        url = validate_safe_url(url)
    except SSRFSecurityError as ssrf_err:
        raise HTTPException(status_code=400, detail=f"Target URL failed security check: {ssrf_err}")

    job = DBManager.create_job(
        target_url=url,
        max_pages=payload.max_pages,
        project_id=payload.project_id,
        competitor_domains=payload.competitor_domains,
        is_demo=payload.is_demo,
        fresh_psi=payload.fresh_psi
    )
    background_tasks.add_task(run_full_pipeline, job["id"], url, payload.max_pages, payload.project_id)
    
    return {
        "status": "success",
        "message": "SEO audit pipeline initiated",
        "job": job
    }

@router.get("/history")
async def get_jobs_history(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    """Returns paginated history of audit jobs with costs, statuses, issue counts, and agent modes."""
    jobs = DBManager.get_jobs_history(limit=limit, offset=offset)
    return {"jobs": jobs, "limit": limit, "offset": offset, "count": len(jobs)}

@router.get("/{job_id}", response_model=Dict[str, Any])
async def get_job_status(job_id: str):
    job = DBManager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@router.delete("/{job_id}")
async def delete_job(job_id: str, confirm: bool = Query(False)):
    """Deletes an audit job and purges all associated data across tables."""
    if not confirm:
        raise HTTPException(status_code=400, detail="Explicit confirmation required to delete job. Pass ?confirm=true.")
    job = DBManager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    DBManager.delete_job(job_id)
    return {"status": "success", "message": f"Job {job_id} and all related records purged"}

@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancels an active or pending audit job gracefully."""
    job = DBManager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") in ("completed", "failed", "cancelled"):
        return {"status": "already_terminated", "job_status": job.get("status")}
    DBManager.update_job(job_id, {"status": "cancelled", "error": "Job was cancelled by user"})
    return {"status": "success", "message": f"Job {job_id} cancelled successfully"}

@router.post("/{job_id}/resume")
async def resume_job(job_id: str, background_tasks: BackgroundTasks):
    """Resumes an interrupted, cancelled, or failed job from its last completed stage."""
    job = DBManager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") not in ("interrupted", "failed", "cancelled"):
        raise HTTPException(status_code=400, detail=f"Cannot resume job with status '{job.get('status')}'")
    DBManager.update_job(job_id, {"status": "resuming", "error": None})
    background_tasks.add_task(
        run_full_pipeline,
        job_id=job_id,
        target_url=job["target_url"],
        max_pages=job.get("max_pages", 50),
        project_id=job.get("project_id"),
        resume=True
    )
    return {"status": "success", "message": f"Job {job_id} resumed in background from last stage"}

@router.get("/{job_id}/pages", response_model=List[Dict[str, Any]])
async def get_job_pages(job_id: str, limit: int = 500):
    job = DBManager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return DBManager.get_crawl_pages(job_id, limit=limit)

@router.get("/{job_id}/pages/{page_id}/inlinks")
async def get_page_inlinks(job_id: str, page_id: str):
    page = DBManager.get_crawl_page_by_id(page_id)
    if not page or page["job_id"] != job_id:
        raise HTTPException(status_code=404, detail="Page not found")
    
    inlinks = DBManager.get_inlinks_for_url(job_id, page["url"])
    return {
        "url": page["url"],
        "inlinks_count": len(inlinks),
        "found_on": inlinks
    }

@router.get("/{job_id}/psi")
async def get_psi_data(job_id: str):
    return DBManager.get_psi_results(job_id)

@router.get("/{job_id}/issues")
async def get_job_issues(job_id: str):
    runs = DBManager.get_agent_runs(job_id)
    tech_run = next((r for r in runs if r["agent"] == "technical"), None)
    verifier_run = next((r for r in runs if r["agent"] == "verifier"), None)

    return {
        "technical_agent": tech_run["output_json"] if tech_run else None,
        "mode": tech_run.get("mode", "fallback") if tech_run else "fallback",
        "model": tech_run.get("model") if tech_run else None,
        "cost_usd": tech_run.get("cost_usd", 0.0) if tech_run else 0.0,
        "failure_reason": tech_run.get("failure_reason") if tech_run else None,
        "verifier": verifier_run["output_json"] if verifier_run else None
    }

# Performance (M3)
@router.get("/{job_id}/performance")
async def get_job_performance(job_id: str):
    perf_snapshot = DBManager.get_performance_snapshot(job_id)
    runs = DBManager.get_agent_runs(job_id)
    mon_run = next((r for r in runs if r["agent"] == "monitor"), None)
    mon_ver_run = next((r for r in runs if r["agent"] == "verifier_monitor"), None)

    return {
        "connected": bool(perf_snapshot),
        "snapshot": perf_snapshot["snapshot_json"] if perf_snapshot else None,
        "monitor_agent": mon_run["output_json"] if mon_run else None,
        "mode": mon_run.get("mode", "fallback") if mon_run else "fallback",
        "model": mon_run.get("model") if mon_run else None,
        "cost_usd": mon_run.get("cost_usd", 0.0) if mon_run else 0.0,
        "verifier": mon_ver_run["output_json"] if mon_ver_run else None
    }

# Research (M4)
@router.get("/{job_id}/research")
async def get_job_research(job_id: str):
    snap = DBManager.get_research_snapshot(job_id)
    runs = DBManager.get_agent_runs(job_id)
    res_run = next((r for r in runs if r["agent"] == "research"), None)
    res_ver = next((r for r in runs if r["agent"] == "verifier_research"), None)

    return {
        "snapshot": snap.get("snapshot") if snap else None,
        "research_agent": res_run["output_json"] if res_run else None,
        "mode": res_run.get("mode", "fallback") if res_run else "fallback",
        "model": res_run.get("model") if res_run else None,
        "cost_usd": res_run.get("cost_usd", 0.0) if res_run else 0.0,
        "failure_reason": res_run.get("failure_reason") if res_run else None,
        "verifier": res_ver["output_json"] if res_ver else None
    }

# Strategy (M4)
@router.get("/{job_id}/strategy")
async def get_job_strategy(job_id: str):
    plan = DBManager.get_strategy_plan(job_id)
    runs = DBManager.get_agent_runs(job_id)
    strat_run = next((r for r in runs if r["agent"] == "strategist"), None)
    strat_ver = next((r for r in runs if r["agent"] == "verifier_strategy"), None)

    return {
        "plan": plan.get("plan") if plan else None,
        "strategist_agent": strat_run["output_json"] if strat_run else None,
        "mode": strat_run.get("mode", "fallback") if strat_run else "fallback",
        "model": strat_run.get("model") if strat_run else None,
        "cost_usd": strat_run.get("cost_usd", 0.0) if strat_run else 0.0,
        "failure_reason": strat_run.get("failure_reason") if strat_run else None,
        "verifier": strat_ver["output_json"] if strat_ver else None
    }

# Content (M4)
@router.get("/{job_id}/content")
async def get_job_content(job_id: str):
    cont = DBManager.get_content_output(job_id)
    runs = DBManager.get_agent_runs(job_id)
    cont_run = next((r for r in runs if r["agent"] == "content"), None)
    cont_ver = next((r for r in runs if r["agent"] == "verifier_content"), None)

    return {
        "content": cont.get("content") if cont else None,
        "content_agent": cont_run["output_json"] if cont_run else None,
        "mode": cont_run.get("mode", "fallback") if cont_run else "fallback",
        "model": cont_run.get("model") if cont_run else None,
        "cost_usd": cont_run.get("cost_usd", 0.0) if cont_run else 0.0,
        "failure_reason": cont_run.get("failure_reason") if cont_run else None,
        "verifier": cont_ver["output_json"] if cont_ver else None
    }

# Competitors (M4)
@router.get("/{job_id}/competitors")
async def get_competitors_data(job_id: str):
    pages = DBManager.get_competitor_pages(job_id)
    return {
        "competitor_pages": pages,
        "count": len(pages),
        "disclaimer": "on-page comparison only — no traffic or backlink data"
    }

# Full Agent Runs Debug Endpoint
@router.get("/{job_id}/agent-runs")
async def get_job_agent_runs(job_id: str):
    runs = DBManager.get_agent_runs(job_id)
    return {"runs": runs}

# Seed Demo Endpoint (M4 Step 0)
@router.post("/{job_id}/seed-demo")
async def seed_full_demo(job_id: str, background_tasks: BackgroundTasks):
    job = DBManager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    DBManager.update_job(job_id, {"is_demo": 1})
    background_tasks.add_task(run_full_pipeline, job_id, job["target_url"], job.get("max_pages", 30), job.get("project_id"))
    return {"status": "success", "message": "Demo data pipeline triggered with DEMO DATA flag"}

# Dev Inject Fake Issue
@router.post("/{job_id}/inject-fake-issue")
async def inject_fake_issue(job_id: str):
    """Dev-only endpoint to demonstrate Verifier rejection of unbacked & false claims."""
    if settings.ENVIRONMENT != "development":
        raise HTTPException(status_code=403, detail="Disabled in production")

    job = DBManager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    pages = DBManager.get_crawl_pages(job_id)
    first_url = pages[0]["url"] if pages else job["target_url"]
    first_id = pages[0]["id"] if pages else "mock-id"

    fake_no_evidence = TechnicalIssue(
        id="FAKE-001",
        type="missing_title",
        severity="high",
        impact="Fake issue with zero evidence",
        effort="low",
        urls=[first_url],
        evidence=[],
        fix_hint="None"
    )

    fake_false_claim = TechnicalIssue(
        id="FAKE-002",
        type="missing_title",
        severity="high",
        impact="Fake issue claiming missing title on a valid page",
        effort="low",
        urls=[first_url],
        evidence=[{"table": "crawl_pages", "id": first_id, "field": "title"}],
        fix_hint="None"
    )

    runs = DBManager.get_agent_runs(job_id)
    tech_run = next((r for r in runs if r["agent"] == "technical"), None)
    existing_issues = []
    if tech_run and tech_run.get("output_json", {}).get("issues"):
        for i in tech_run["output_json"]["issues"]:
            existing_issues.append(TechnicalIssue.model_validate(i))

    all_issues = existing_issues + [fake_no_evidence, fake_false_claim]
    new_verifier_report = Verifier.verify_issues(job_id, all_issues)

    DBManager.save_agent_run({
        "job_id": job_id,
        "agent": "verifier",
        "status": "done",
        "mode": "deterministic",
        "input_ref": [f"injected_fake_demo_count:{len(all_issues)}"],
        "output_json": new_verifier_report.model_dump(),
        "confidence": 1.0
    })

    return {
        "status": "success",
        "message": "Injected 2 fake issues (1 no-evidence, 1 false claim) and re-verified",
        "verifier_report": new_verifier_report.model_dump()
    }

# Export Downloads (PDF, CSV, XLSX)
@router.get("/{job_id}/export/{format_type}")
async def export_report_file(job_id: str, format_type: str):
    format_type = format_type.lower()
    if format_type not in ("pdf", "csv", "xlsx", "asana"):
        raise HTTPException(status_code=400, detail="Invalid format. Supported: pdf, csv, xlsx, asana")

    job = DBManager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if format_type == "asana":
        from app.services.asana_service import AsanaService
        csv_content = AsanaService.generate_asana_csv(job_id)
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="asana_import_{job_id[:8]}.csv"',
                "Access-Control-Expose-Headers": "Content-Disposition"
            }
        )

    is_demo = bool(job.get("is_demo", 0))

    runs = DBManager.get_agent_runs(job_id)
    ver_run = next((r for r in runs if r["agent"] == "verifier"), None)
    v_issues = ver_run["output_json"].get("verified_issues", []) if ver_run else []
    
    perf = DBManager.get_performance_snapshot(job_id)
    p_data = perf["snapshot_json"] if perf else None

    strat = DBManager.get_strategy_plan(job_id)
    strat_data = strat.get("plan") if strat else None

    cont = DBManager.get_content_output(job_id)
    cont_data = cont.get("content") if cont else None

    res = DBManager.get_research_snapshot(job_id)
    res_data = res.get("snapshot") if res else None

    psi_results = DBManager.get_psi_results(job_id)

    if format_type == "pdf":
        path = ReportExporter.generate_pdf(
            job_id, job["target_url"], v_issues, p_data,
            strategy_data=strat_data, content_data=cont_data, research_data=res_data,
            psi_data=psi_results, is_demo=is_demo
        )
        media_type = "application/pdf"
    elif format_type == "csv":
        path = ReportExporter.generate_csv(
            job_id, v_issues, p_data,
            strategy_data=strat_data, content_data=cont_data, research_data=res_data,
            psi_data=psi_results, is_demo=is_demo
        )
        media_type = "text/csv"
    else:
        path = ReportExporter.generate_xlsx(
            job_id, job["target_url"], v_issues, p_data,
            strategy_data=strat_data, content_data=cont_data, research_data=res_data,
            psi_data=psi_results, is_demo=is_demo
        )
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    return FileResponse(path, media_type=media_type, filename=os.path.basename(path))

@router.get("/{job_id}/stats", response_model=Dict[str, Any])
async def get_job_stats(job_id: str):
    job = DBManager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    pages = DBManager.get_crawl_pages(job_id, limit=2000)
    psi_results = DBManager.get_psi_results(job_id)
    runs = DBManager.get_agent_runs(job_id)
    perf_snapshot = DBManager.get_performance_snapshot(job_id)
    res_snapshot = DBManager.get_research_snapshot(job_id)
    strat_plan = DBManager.get_strategy_plan(job_id)
    cont_out = DBManager.get_content_output(job_id)
    comp_pages = DBManager.get_competitor_pages(job_id)

    total = len(pages)
    status_200_pages = [p for p in pages if p["status_code"] == 200]
    
    status_200 = len(status_200_pages)
    status_3xx = sum(1 for p in pages if 300 <= p["status_code"] < 400)
    status_4xx = sum(1 for p in pages if 400 <= p["status_code"] < 500)
    status_5xx = sum(1 for p in pages if p["status_code"] >= 500)
    
    missing_title = sum(1 for p in status_200_pages if not p.get("title") or len(p["title"].strip()) == 0)
    missing_meta = sum(1 for p in status_200_pages if not p.get("meta_desc") or len(p["meta_desc"].strip()) == 0)
    missing_h1 = sum(1 for p in status_200_pages if not p.get("h1") or len(p["h1"].strip()) == 0)
    non_indexable = sum(1 for p in pages if not p.get("indexable", True))
    
    titles = [p["title"].strip() for p in status_200_pages if p.get("title")]
    title_counts = Counter(titles)
    duplicate_titles = sum(count for title, count in title_counts.items() if count > 1)

    avg_response_time = (
        sum(p.get("response_time_ms", 0) for p in pages) / total if total > 0 else 0.0
    )

    mobile_psi = next((p for p in psi_results if p["strategy"] == "mobile" and p.get("performance_score") is not None), None)
    desktop_psi = next((p for p in psi_results if p["strategy"] == "desktop" and p.get("performance_score") is not None), None)

    verifier_run = next((r for r in runs if r["agent"] == "verifier"), None)
    verified_issues = verifier_run["output_json"].get("verified_issues", []) if verifier_run else []
    high_issues = sum(1 for i in verified_issues if i.get("severity") == "high")
    medium_issues = sum(1 for i in verified_issues if i.get("severity") == "medium")
    low_issues = sum(1 for i in verified_issues if i.get("severity") == "low")

    tech_run = next((r for r in runs if r["agent"] == "technical"), None)
    mode = tech_run.get("mode", "fallback") if tech_run else "fallback"

    strat_tasks_count = len(strat_plan.get("plan", {}).get("tasks", [])) if strat_plan else 0
    briefs_count = len(cont_out.get("content", {}).get("briefs", [])) if cont_out else 0

    code_out = DBManager.get_code_output(job_id)

    # Length tiers breakdown (M4 carry-over & M5)
    title_borderline_pages = [p["url"] for p in status_200_pages if p.get("title") and 60 < len(p["title"].strip()) <= 65]
    title_too_long_pages = [p["url"] for p in status_200_pages if p.get("title") and len(p["title"].strip()) > 65]
    meta_borderline_pages = [p["url"] for p in status_200_pages if p.get("meta_desc") and 160 < len(p["meta_desc"].strip()) <= 170]
    meta_too_long_pages = [p["url"] for p in status_200_pages if p.get("meta_desc") and len(p["meta_desc"].strip()) > 170]

    failed_fetches = []
    if job.get("failed_fetches_json"):
        try:
            failed_fetches = json.loads(job["failed_fetches_json"])
        except Exception:
            failed_fetches = []

    # Sitemap Comparison URL Lists
    sm_entries = []
    if job.get("sitemap_entries_json"):
        try:
            sm_entries = json.loads(job["sitemap_entries_json"])
        except Exception:
            sm_entries = []
    sitemap_stale_urls = [
        {"url": e.get("url"), "status_code": e.get("status_code", 404)}
        for e in sm_entries
        if (isinstance(e.get("status_code"), int) and (e.get("status_code", 0) >= 400 or e.get("status_code", 0) == 0)) or isinstance(e.get("status_code"), str)
    ]
    sm_norm_set = {(e.get("url") or "").rstrip("/") for e in sm_entries}
    sitemap_missing_urls = [
        {"url": p.get("url"), "title": p.get("title") or "Page"}
        for p in pages
        if p.get("status_code") == 200
        and p.get("indexable")
        and (not p.get("canonical") or p.get("canonical", "").rstrip("/") == p.get("url", "").rstrip("/"))
        and p.get("url", "").rstrip("/") not in sm_norm_set
    ]

    return {
        "total_pages": total,
        "status_200": status_200,
        "status_3xx": status_3xx,
        "status_4xx": status_4xx,
        "status_5xx": status_5xx,
        "missing_title": missing_title,
        "missing_meta": missing_meta,
        "missing_h1": missing_h1,
        "duplicate_titles": duplicate_titles,
        "non_indexable": non_indexable,
        "avg_response_time_ms": round(avg_response_time, 1),
        "sitemap_found": bool(job.get("sitemap_found")),
        "in_sitemap_not_crawled": job.get("in_sitemap_not_crawled", 0),
        "crawled_not_in_sitemap": job.get("crawled_not_in_sitemap", 0),
        "psi_status": job.get("psi_status", "pending"),
        "is_demo": bool(job.get("is_demo", 0)),
        "crawl_incomplete": bool(job.get("crawl_incomplete", 0)),
        "completeness_status": job.get("completeness_status", "complete"),
        "incomplete_reasons": json.loads(job.get("incomplete_reasons_json", "[]")) if isinstance(job.get("incomplete_reasons_json"), str) else (job.get("incomplete_reasons_json") or []),
        "failed_fetches": failed_fetches,
        "psi_mobile_score": mobile_psi["performance_score"] if mobile_psi else None,
        "psi_desktop_score": desktop_psi["performance_score"] if desktop_psi else None,
        "psi_is_cached": bool(mobile_psi and mobile_psi.get("is_cached")),
        "psi_cached_measured_at": (mobile_psi.get("cached_measured_at") or mobile_psi.get("fetched_at")) if (mobile_psi and mobile_psi.get("is_cached")) else None,
        "issues_high": high_issues,
        "issues_medium": medium_issues,
        "issues_low": low_issues,
        "current_step": job.get("current_step", "init"),
        "status": job.get("status", "pending"),
        "cost_usd": job.get("cost_usd", 0.0),
        "mode": mode,
        "has_performance": bool(perf_snapshot),
        "has_research": bool(res_snapshot),
        "has_strategy": bool(strat_plan),
        "has_code": bool(code_out),
        "strategy_tasks_count": strat_tasks_count,
        "briefs_count": briefs_count,
        "competitor_pages_count": len(comp_pages),
        # Length tier counts & lists
        "title_borderline_count": len(title_borderline_pages),
        "title_too_long_count": len(title_too_long_pages),
        "meta_borderline_count": len(meta_borderline_pages),
        "meta_too_long_count": len(meta_too_long_pages),
        "title_borderline_urls": title_borderline_pages,
        "title_too_long_urls": title_too_long_pages,
        "meta_borderline_urls": meta_borderline_pages,
        "meta_too_long_urls": meta_too_long_pages,
        "sitemap_stale_urls": sitemap_stale_urls,
        "sitemap_missing_urls": sitemap_missing_urls,
        # Platform info
        "detected_platform": job.get("detected_platform") or job.get("platform") or "nextjs",
        "detected_platform_confidence": job.get("detected_platform_confidence") or job.get("platform_confidence") or 1.0,
        "platform": job.get("platform") or job.get("detected_platform") or "nextjs",
        "platform_confidence": job.get("platform_confidence") or job.get("detected_platform_confidence") or 1.0,
        "router_type": job.get("router_type") or "app"
    }


# =========================================================================
# Milestone 5: SEO Code Generator Endpoints
# =========================================================================

@router.get("/{job_id}/code-artifacts")
async def get_job_code_artifacts(job_id: str):
    """Returns the generated code bundle, verifier report, and fix-coverage table."""
    code_out = DBManager.get_code_output(job_id)
    if not code_out or not code_out.get("code"):
        return {
            "bundle": None,
            "verifier": None,
            "artifacts": [],
            "fix_coverage": [],
            "summary": "No code artifacts generated yet for this job."
        }
    return code_out["code"]


@router.get("/{job_id}/code-zip")
async def download_code_zip(job_id: str, include_unreviewed: bool = Query(False)):
    """Generates and serves the downloadable ZIP archive of validated SEO code artifacts."""
    job = DBManager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    code_out = DBManager.get_code_output(job_id)
    if not code_out or not code_out.get("code"):
        raise HTTPException(status_code=404, detail="No code artifacts generated for this job")

    from urllib.parse import urlparse
    from app.code_generator.packager import CodePackager

    bundle_data = code_out["code"].get("bundle", {})
    verifier_data = code_out["code"].get("verifier", {})
    artifacts_data = bundle_data.get("artifacts", [])
    val_results = verifier_data.get("results", [])

    artifacts = [GeneratedArtifact(**a) for a in artifacts_data]
    domain = urlparse(job.get("target_url", "https://example.com")).netloc or "site"
    platform = bundle_data.get("platform", "nextjs")
    is_demo = bool(job.get("is_demo", 0))

    zip_bytes = CodePackager.generate_zip(
        job_id=job_id,
        domain=domain,
        platform=platform,
        artifacts=artifacts,
        validation_results=val_results,
        is_demo=is_demo,
        include_unreviewed=include_unreviewed
    )

    clean_domain = domain.replace(":", "_").replace("/", "_")
    filename = f"seo-code-{clean_domain}-{job_id[:8]}.zip"

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )


class PlatformOverrideRequest(BaseModel):
    platform: str
    router_type: Optional[str] = "app"
    nextjs_version: Optional[str] = "15+"


@router.post("/{job_id}/platform")
async def override_job_platform(job_id: str, payload: PlatformOverrideRequest):
    """Allows user to override detected platform (nextjs, wordpress, shopify, plain_html) and router type."""
    job = DBManager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    valid_platforms = ["nextjs", "wordpress", "shopify", "plain_html"]
    if payload.platform not in valid_platforms:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid platform '{payload.platform}'. Allowed: {valid_platforms}"
        )

    valid_routers = ["app", "pages"]
    router = payload.router_type if payload.router_type in valid_routers else "app"

    DBManager.update_job(job_id, {
        "platform": payload.platform,
        "platform_confidence": 1.0,
        "router_type": router
    })

    # Re-run Code Generator & Code Verifier deterministically
    crawl_pages = DBManager.get_crawl_pages(job_id, limit=2000)
    conn = get_sqlite_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM crawl_links WHERE job_id = ?", (job_id,))
    crawl_links = [dict(r) for r in c.fetchall()]
    conn.close()

    runs = DBManager.get_agent_runs(job_id)
    tech_run = next((r for r in runs if r["agent"] == "verifier"), None)
    verified_tech_issues = [
        TechnicalIssue(**i) for i in (tech_run["output_json"].get("verified_issues", []) if tech_run else [])
    ]

    strat_run = next((r for r in runs if r["agent"] == "verifier_strategy"), None)
    strat_tasks = [
        StrategyTask(**t) for t in (strat_run["output_json"].get("verified_tasks", []) if strat_run else [])
    ]

    cont_out = DBManager.get_content_output(job_id)
    rewrites = [
        OnPageRewrite(**r) for r in (cont_out.get("content", {}).get("rewrites", []) if cont_out else [])
    ]
    internal_links = [
        InternalLinkSuggestion(**l) for l in (cont_out.get("content", {}).get("internal_links", []) if cont_out else [])
    ]

    from app.agents.code_agent import CodeGeneratorAgent
    from app.agents.code_verifier import CodeVerifier

    code_bundle, code_mode, code_cost, code_err, code_model = await CodeGeneratorAgent.run(
        platform=payload.platform,
        platform_confidence=1.0,
        verified_tech_issues=verified_tech_issues,
        strategy_tasks=strat_tasks,
        crawl_pages=crawl_pages,
        crawl_links=crawl_links,
        verified_rewrites=rewrites,
        internal_links=internal_links,
        router_type=router,
        nextjs_version=payload.nextjs_version or "15+",
        is_demo=bool(job.get("is_demo", 0))
    )

    code_verifier_rep = CodeVerifier.verify_code_bundle(
        bundle=code_bundle,
        crawl_pages=crawl_pages,
        crawl_links=crawl_links,
        is_demo=bool(job.get("is_demo", 0))
    )

    code_output_data = {
        "bundle": code_bundle.model_dump(),
        "verifier": code_verifier_rep.model_dump()
    }
    DBManager.save_code_output(job_id, code_output_data)

    return {
        "status": "success",
        "message": f"Code artifacts regenerated for platform '{payload.platform}' ({router} router)",
        "platform": payload.platform,
        "router_type": router,
        "bundle": code_bundle.model_dump(),
        "verifier": code_verifier_rep.model_dump()
    }
