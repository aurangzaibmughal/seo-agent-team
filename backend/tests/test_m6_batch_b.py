import os
import io
import csv
import json
from uuid import uuid4
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.core.db import DBManager, get_sqlite_conn
from app.services.asana_service import AsanaService
from app.agents.orchestrator import check_cost_caps
from app.agents.technical_agent import TechnicalAgent
from app.agents.research_agent import ResearchAgent
from app.agents.strategist_agent import StrategistAgent
from app.models.agent_schemas import TechnicalIssue, MonitorFinding, ResearchOpportunity

client = TestClient(app)


def test_asana_export_preview_and_csv_generation():
    """Verify that AsanaService maps strategy tasks to Asana preview and official Asana CSV headers."""
    job_id = f"test-asana-preview-{uuid4().hex[:8]}"
    with get_sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO jobs (id, target_url, status, created_at, updated_at) VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            (job_id, "https://webspire-agency.vercel.app/", "completed")
        )

    strategy_plan = {
        "tasks": [
            {
                "id": "S-001",
                "title": "Fix Critical 404 Pages",
                "impact": "high",
                "effort": "low",
                "week": 1,
                "priority_score": 5.0,
                "done_when": "Zero 404 links returning in crawl audit.",
                "source_refs": [{"id": "T-001", "type": "issue"}],
                "affected_urls": ["https://webspire-agency.vercel.app/old-page"]
            },
            {
                "id": "S-002",
                "title": "Rewrite Truncated Meta Descriptions",
                "impact": "medium",
                "effort": "low",
                "week": 2,
                "priority_score": 3.0,
                "done_when": "All meta descriptions between 70 and 155 chars.",
                "source_refs": [{"id": "T-002", "type": "issue"}],
                "affected_urls": ["https://webspire-agency.vercel.app/services"],
                "dependencies": ["S-001"]
            }
        ],
        "summary": "SEO Action Roadmap"
    }
    DBManager.save_strategy_plan(job_id, strategy_plan)

    # 1. Preview export
    import asyncio
    preview = asyncio.run(AsanaService.preview_export(job_id, start_date="2026-04-01"))
    assert preview["job_id"] == job_id
    assert preview["tasks_count"] == 2
    tasks = preview["tasks"]

    # Week 1 task
    t1 = tasks[0]
    assert "[S-001]" in t1["name"]
    assert t1["section"] == "Week 1"
    assert t1["due_on"] == "2026-04-08" # 2026-04-01 + 7 days
    assert "Zero 404 links returning in crawl audit." in t1["notes"]
    assert "https://webspire-agency.vercel.app/old-page" in t1["notes"]

    # Week 2 task
    t2 = tasks[1]
    assert "[S-002]" in t2["name"]
    assert t2["section"] == "Week 2"
    assert t2["due_on"] == "2026-04-15" # 2026-04-01 + 14 days
    assert "Dependencies: S-001" in t2["notes"]

    # 2. CSV export matching Asana CSV mapping guide (free plan compatible)
    csv_text = AsanaService.generate_asana_csv(job_id, start_date="2026-04-01")
    reader = list(csv.reader(io.StringIO(csv_text)))
    expected_headers = [
        "Name", "Description", "Assignee",
        "Start Date", "Due Date", "Dependencies"
    ]
    assert reader[0] == expected_headers
    
    # Section row 1 (ending with colon)
    assert reader[1][0] == "Week 1:"
    assert reader[1][1:] == ["", "", "", "", ""]
    
    # Task 1 row
    assert reader[2][0] == t1["name"]
    assert "Impact: HIGH | Effort: LOW" in reader[2][1] # In Description
    assert "Zero 404 links returning in crawl audit." in reader[2][1] # In Description
    assert reader[2][2] == "" # Assignee blank by default
    assert reader[2][3] == "04/01/2026" # Start Date in MM/DD/YYYY
    assert reader[2][4] == "04/08/2026" # Due Date in MM/DD/YYYY
    
    # Section row 2 (ending with colon)
    assert reader[3][0] == "Week 2:"
    assert reader[4][0] == t2["name"]
    assert reader[4][5] == "S-001" # Dependencies mapped


def test_asana_preview_approved_tasks_only_filter():
    """Verify that when review items exist, Asana preview and export include ONLY approved tasks."""
    job_id = f"test-asana-reviews-{uuid4().hex[:8]}"
    with get_sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO jobs (id, target_url, status, created_at, updated_at) VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            (job_id, "https://webspire-agency.vercel.app/", "completed")
        )

    # 10 tasks in strategy plan
    tasks = [
        {
            "id": f"S-00{i+1}",
            "title": f"Action Task {i+1}",
            "impact": "high" if i < 3 else "medium",
            "effort": "low",
            "week": (i % 4) + 1,
            "priority_score": 4.0,
            "done_when": f"Completion of task {i+1}"
        }
        for i in range(10)
    ]
    DBManager.save_strategy_plan(job_id, {"tasks": tasks, "summary": "10-task plan"})

    # Populate review items: exactly 3 approved, 7 pending
    DBManager.populate_review_items_for_job(job_id)
    items = DBManager.get_review_items(job_id)
    strat_items = [it for it in items if it["item_type"] == "strategy_task"]
    assert len(strat_items) == 10

    # Approve 3 tasks (S-001, S-002, S-003), leave remaining 7 as pending
    approved_ids = ["S-001", "S-002", "S-003"]
    for it in strat_items:
        if it["item_ref"] in approved_ids:
            DBManager.update_review_item_status(it["id"], "approved", note="Verified by lead")

    # Call Asana preview
    import asyncio
    preview = asyncio.run(AsanaService.preview_export(job_id, start_date="2026-04-01"))
    assert preview["tasks_count"] == 3
    preview_task_ids = [t["task_id"] for t in preview["tasks"]]
    assert sorted(preview_task_ids) == ["S-001", "S-002", "S-003"]

    # CSV also includes only the 3 approved tasks (excluding section header rows)
    csv_text = AsanaService.generate_asana_csv(job_id, start_date="2026-04-01")
    lines = list(csv.reader(io.StringIO(csv_text)))
    task_rows = [r for r in lines[1:] if not r[0].endswith(":")]
    assert len(task_rows) == 3 # Exactly the 3 approved tasks


def test_asana_export_mocked_sync_and_idempotency():
    """Verify Asana API calls create tasks, map sections, update existing task GIDs idempotently."""
    job_id = f"test-asana-sync-{uuid4().hex[:8]}"
    with get_sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO jobs (id, target_url, status, created_at, updated_at) VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            (job_id, "https://webspire-agency.vercel.app/", "completed")
        )

    strategy_plan = {
        "tasks": [
            {
                "id": "S-001",
                "title": "Fix Critical 404 Pages",
                "impact": "high",
                "effort": "low",
                "week": 1,
                "priority_score": 5.0,
                "done_when": "Zero 404 links returning in crawl audit."
            }
        ],
        "summary": "SEO Action Roadmap"
    }
    DBManager.save_strategy_plan(job_id, strategy_plan)

    with patch.object(AsanaService, "get_token", return_value="1/fake-valid-token-for-tests"):
        async def mock_get(url, *args, **kwargs):
            if "/sections" in url:
                return httpx.Response(200, json={"data": [{"gid": "sec-wk1", "name": "Week 1"}]})
            return httpx.Response(200, json={"data": []})

        async def mock_post(url, *args, **kwargs):
            if "/tasks" in url and "/sections" not in url:
                return httpx.Response(201, json={"data": {"gid": "asana-task-999"}})
            return httpx.Response(200, json={"data": {}})

        async def mock_put(url, *args, **kwargs):
            return httpx.Response(200, json={"data": {"gid": "asana-task-999"}})

        with patch("httpx.AsyncClient.get", side_effect=mock_get), \
             patch("httpx.AsyncClient.post", side_effect=mock_post) as mock_post_call, \
             patch("httpx.AsyncClient.put", side_effect=mock_put) as mock_put_call:

            import asyncio
            # First sync: creates new task
            res1 = asyncio.run(AsanaService.export_to_asana(job_id, "ws-1", "proj-1", "2026-04-01"))
            assert res1["status"] == "success"
            assert res1["synced_count"] == 1
            assert res1["synced_tasks"][0]["action"] == "created"
            assert res1["synced_tasks"][0]["asana_task_gid"] == "asana-task-999"

            # Check that task in DB now has asana_task_gid
            strat = DBManager.get_strategy_plan(job_id)
            assert strat["plan"]["tasks"][0].get("asana_task_gid") == "asana-task-999"

            # Second sync: should UPDATE instead of create (idempotency!)
            res2 = asyncio.run(AsanaService.export_to_asana(job_id, "ws-1", "proj-1", "2026-04-01"))
            assert res2["status"] == "success"
            assert res2["synced_tasks"][0]["action"] == "updated"
            assert mock_put_call.called


def test_cost_caps_enforcement_and_graceful_fallback():
    """Verify that when cost limit is hit, agents gracefully fall back to deterministic mode with cost_usd=0."""
    import asyncio
    job_id = f"test-cost-cap-{uuid4().hex[:8]}"

    # Test check_cost_caps logic
    with patch.object(settings, "MAX_JOB_COST_USD", 0.10):
        # Under cap
        cap_hit, _ = check_cost_caps(job_id, 0.05)
        assert cap_hit is False

        # Exceeds cap
        cap_hit, reason = check_cost_caps(job_id, 0.15)
        assert cap_hit is True
        assert "MAX_JOB_COST_USD reached" in reason

    # Test TechnicalAgent with force_fallback
    candidates = [
        {"id": "iss-1", "type": "missing_h1", "title": "Missing H1", "severity": "medium", "impact": "low", "effort": "low", "urls": ["/"], "evidence": {}, "fix_hint": "Add H1"}
    ]
    report, mode, cost, err, model = asyncio.run(
        TechnicalAgent.run(candidates, force_fallback=True)
    )
    assert mode == "fallback_cost_cap"
    assert cost == 0.0
    assert "Cost cap" in err


def test_cost_caps_mid_run_crossing_falls_back():
    """Test that a job crossing the cap mid-run causes remaining stages to fall back."""
    import asyncio
    job_id = f"test-mid-cap-{uuid4().hex[:8]}"

    with get_sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO jobs (id, target_url, status, cost_usd, created_at, updated_at) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
            (job_id, "https://webspire-agency.vercel.app/", "running", 0.0)
        )

    with patch.object(settings, "MAX_JOB_COST_USD", 0.10):
        # Stage 1: Technical costs $0.06 (under cap)
        tech_cost = 0.06
        cap1, _ = check_cost_caps(job_id, tech_cost)
        assert cap1 is False

        # Stage 2: Research costs $0.05 -> total is $0.11 (crosses $0.10 cap!)
        total_cost = tech_cost + 0.05
        DBManager.update_job(job_id, {"cost_usd": total_cost})
        cap2, reason2 = check_cost_caps(job_id, total_cost)
        assert cap2 is True
        assert "MAX_JOB_COST_USD reached" in reason2

        # Stage 3 (Strategist Agent) must receive force_fallback=True and run in fallback_cost_cap mode
        strat_report, strat_mode, strat_cost, strat_err, _ = asyncio.run(
            StrategistAgent.run(
                verified_tech=[],
                verified_perf=[],
                verified_research=[],
                force_fallback=cap2
            )
        )
        assert strat_mode == "fallback_cost_cap"
        assert strat_cost == 0.0
        assert "Cost cap" in strat_err


def test_job_delete_with_confirm_flag():
    """Verify DELETE /api/jobs/{job_id} requires ?confirm=true and purges database records."""
    job_id = f"test-del-{uuid4().hex[:8]}"
    with get_sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO jobs (id, target_url, status, created_at, updated_at) VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            (job_id, "https://webspire-agency.vercel.app/", "completed")
        )
        conn.execute(
            "INSERT INTO crawl_pages (job_id, url, status_code, created_at) VALUES (?, ?, ?, datetime('now'))",
            (job_id, "https://webspire-agency.vercel.app/test", 200)
        )

    # 1. DELETE without ?confirm=true must return 400 Bad Request
    res_no_confirm = client.delete(f"/api/jobs/{job_id}")
    assert res_no_confirm.status_code == 400
    assert "Explicit confirmation required" in res_no_confirm.json()["detail"]

    # Verify job is NOT deleted
    assert DBManager.get_job(job_id) is not None

    # 2. DELETE with ?confirm=true succeeds and purges data
    res_confirmed = client.delete(f"/api/jobs/{job_id}?confirm=true")
    assert res_confirmed.status_code == 200
    assert res_confirmed.json()["status"] == "success"

    # Verify job and child records are purged
    assert DBManager.get_job(job_id) is None
    with get_sqlite_conn() as conn:
        cnt = conn.execute("SELECT COUNT(*) FROM crawl_pages WHERE job_id = ?", (job_id,)).fetchone()[0]
        assert cnt == 0


def test_job_history_and_purge():
    """Verify DBManager.get_jobs_history returns enriched rows and delete_job purges all data."""
    job_id = f"test-hist-{uuid4().hex[:8]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO jobs (id, target_url, status, pages_crawled, cost_usd, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (job_id, "https://example.com/hist", "completed", 12, 0.045, now_iso, now_iso)
        )
        conn.execute(
            "INSERT INTO crawl_pages (job_id, url, status_code, created_at) VALUES (?, ?, ?, datetime('now'))",
            (job_id, "https://example.com/hist/p1", 200)
        )
        conn.execute(
            "INSERT INTO agent_runs (job_id, agent, status, mode, cost_usd, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, "verifier", "done", "deterministic", 0.0, now_iso)
        )

    # 1. Read history
    hist = DBManager.get_jobs_history()
    matching = next((j for j in hist if j["id"] == job_id), None)
    assert matching is not None
    assert matching["pages_crawled"] == 12
    assert matching["cost_usd"] == 0.045
    assert matching["agent_modes"].get("verifier") == "deterministic"

    # 2. Delete and purge
    deleted = DBManager.delete_job(job_id)
    assert deleted is True

    # Confirm purged from jobs, crawl_pages, and agent_runs
    with get_sqlite_conn() as conn:
        c1 = conn.execute("SELECT COUNT(*) FROM jobs WHERE id = ?", (job_id,)).fetchone()[0]
        c2 = conn.execute("SELECT COUNT(*) FROM crawl_pages WHERE job_id = ?", (job_id,)).fetchone()[0]
        c3 = conn.execute("SELECT COUNT(*) FROM agent_runs WHERE job_id = ?", (job_id,)).fetchone()[0]
        assert c1 == 0
        assert c2 == 0
        assert c3 == 0


def test_orchestrator_cancellation_and_resume():
    """Verify job status transition to cancelled, stopping pipeline, and resuming from stored outputs."""
    job_id = f"test-cancel-{uuid4().hex[:8]}"
    with get_sqlite_conn() as conn:
        conn.execute(
            "INSERT INTO jobs (id, target_url, status, created_at, updated_at) VALUES (?, ?, ?, datetime('now'), datetime('now'))",
            (job_id, "https://webspire-agency.vercel.app/", "running")
        )

    # Cancel job
    res = client.post(f"/api/jobs/{job_id}/cancel")
    assert res.status_code == 200
    assert res.json()["status"] == "success"

    job = DBManager.get_job(job_id)
    assert job["status"] == "cancelled"

    # Resume job (mock background task execution so unit test doesn't re-crawl the live web)
    with patch("app.api.routes_jobs.run_full_pipeline"):
        res_resume = client.post(f"/api/jobs/{job_id}/resume")
        assert res_resume.status_code == 200
        assert res_resume.json()["status"] in ("resumed", "success")

    job_resumed = DBManager.get_job(job_id)
    assert job_resumed["status"] == "resuming"
