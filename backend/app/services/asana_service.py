import os
import io
import csv
import json
import time
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta, timezone
import httpx

from app.core.config import settings
from app.core.db import DBManager, get_sqlite_conn

ASANA_API_BASE = "https://app.asana.com/api/1.0"


def format_to_mm_dd_yyyy(date_str: str) -> str:
    """Converts YYYY-MM-DD to MM/DD/YYYY format for Asana CSV importer."""
    try:
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
        return dt.strftime("%m/%d/%Y")
    except Exception:
        return date_str


class AsanaService:
    """Asana export integration service with preview, idempotency, rate-limit backoff, and CSV fallback."""

    @classmethod
    def get_token(cls) -> Optional[str]:
        return os.environ.get("ASANA_ACCESS_TOKEN") or settings.ASANA_ACCESS_TOKEN

    @classmethod
    def is_configured(cls) -> bool:
        token = cls.get_token()
        return bool(token and token.strip())

    @classmethod
    def _get_headers(cls) -> Dict[str, str]:
        token = cls.get_token()
        if not token:
            raise ValueError("Asana access token not configured in environment")
        return {
            "Authorization": f"Bearer {token.strip()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    @classmethod
    async def list_workspaces(cls) -> List[Dict[str, Any]]:
        headers = cls._get_headers()
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(f"{ASANA_API_BASE}/workspaces", headers=headers)
            if res.status_code != 200:
                raise RuntimeError(f"Asana API error {res.status_code}: {res.text}")
            data = res.json()
            return data.get("data", [])

    @classmethod
    async def list_projects(cls, workspace_gid: str) -> List[Dict[str, Any]]:
        headers = cls._get_headers()
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.get(
                f"{ASANA_API_BASE}/projects",
                headers=headers,
                params={"workspace": workspace_gid, "archived": "false"}
            )
            if res.status_code != 200:
                raise RuntimeError(f"Asana API error {res.status_code}: {res.text}")
            data = res.json()
            return data.get("data", [])

    @classmethod
    def build_task_payload(
        cls,
        task: Dict[str, Any],
        start_date: str,
        job_id: str,
        target_url: str
    ) -> Dict[str, Any]:
        """Maps an approved StrategyTask to Asana fields."""
        week_num = int(task.get("week") or 1)
        base_dt = datetime.strptime(start_date, "%Y-%m-%d")
        due_dt = base_dt + timedelta(days=(week_num * 7))
        due_on = due_dt.strftime("%Y-%m-%d")

        source_refs = task.get("source_refs", [])
        source_ids = [ref.get("id") if isinstance(ref, dict) else getattr(ref, "id", str(ref)) for ref in source_refs]
        source_urls = task.get("affected_urls", [])

        notes_lines = [
            f"SEO Action Plan Task: {task.get('title', '')}",
            f"Impact: {str(task.get('impact', 'medium')).upper()} | Effort: {str(task.get('effort', 'medium')).upper()}",
            f"Assigned Milestone: Week {week_num}",
            f"Target URL: {target_url}",
            f"Job ID: {job_id}",
            "",
            "### Done When Criteria:",
            task.get("done_when", "Task implementation is complete and verified."),
            "",
            f"Source Issue IDs: {', '.join(source_ids) if source_ids else 'None'}",
            f"Dependencies: {', '.join(task.get('dependencies', [])) if task.get('dependencies') else 'None'}",
        ]
        if source_urls:
            notes_lines.append(f"Affected URLs ({len(source_urls)}):")
            for u in source_urls[:10]:
                notes_lines.append(f"  - {u}")
            if len(source_urls) > 10:
                notes_lines.append(f"  ... and {len(source_urls) - 10} more.")

        notes = "\n".join(notes_lines)

        return {
            "task_id": task.get("id"),
            "name": f"[{task.get('id', 'TASK')}] {task.get('title', '')}",
            "notes": notes,
            "due_on": due_on,
            "section": f"Week {week_num}",
            "impact": task.get("impact", "medium"),
            "effort": task.get("effort", "medium"),
            "asana_task_gid": task.get("asana_task_gid")
        }

    @classmethod
    def get_approved_strategy_tasks_for_job(cls, job_id: str, include_unreviewed: bool = False) -> List[Dict[str, Any]]:
        """Retrieves strategy tasks, strictly returning approved/edited items unless include_unreviewed is True."""
        strat = DBManager.get_strategy_plan(job_id)
        if not strat or not strat.get("plan"):
            return []
        all_tasks = strat["plan"].get("tasks", [])

        # Check review items
        review_items = DBManager.get_review_items(job_id)
        task_reviews = {}
        for r in review_items:
            if r["item_type"] == "strategy_task":
                ref = r["item_ref"]
                if ref not in task_reviews or r["status"] in ("approved", "edited"):
                    task_reviews[ref] = r

        if not task_reviews:
            # If review workflow has never been initiated for this job, return all tasks
            return all_tasks

        approved_or_edited_tasks = []
        for t in all_tasks:
            t_id = t.get("id") or t.get("task_id")
            rev = task_reviews.get(t_id)
            if rev:
                if rev["status"] in ("approved", "edited"):
                    task_copy = dict(t)
                    if rev["status"] == "edited" and rev.get("edited_payload"):
                        task_copy.update(rev["edited_payload"])
                    approved_or_edited_tasks.append(task_copy)
                elif include_unreviewed:
                    task_copy = dict(t)
                    task_copy["title"] = f"[UNREVIEWED] {task_copy.get('title', '')}"
                    approved_or_edited_tasks.append(task_copy)
            elif include_unreviewed:
                task_copy = dict(t)
                task_copy["title"] = f"[UNREVIEWED] {task_copy.get('title', '')}"
                approved_or_edited_tasks.append(task_copy)

        return approved_or_edited_tasks

    @classmethod
    async def preview_export(
        cls,
        job_id: str,
        start_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generates dry-run task payload mapping for review before push."""
        job = DBManager.get_job(job_id)
        if not job:
            raise ValueError("Job not found")

        s_date = start_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        tasks = cls.get_approved_strategy_tasks_for_job(job_id)

        preview_items = [
            cls.build_task_payload(t, s_date, job_id, job.get("target_url", ""))
            for t in tasks
        ]

        return {
            "job_id": job_id,
            "target_url": job.get("target_url"),
            "start_date": s_date,
            "tasks_count": len(preview_items),
            "tasks": preview_items
        }

    @classmethod
    async def export_to_asana(
        cls,
        job_id: str,
        workspace_gid: str,
        project_gid: str,
        start_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Syncs approved strategy tasks to Asana project with idempotency and section grouping."""
        job = DBManager.get_job(job_id)
        if not job:
            raise ValueError("Job not found")

        s_date = start_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        tasks = cls.get_approved_strategy_tasks_for_job(job_id)
        if not tasks:
            return {"status": "success", "exported_count": 0, "tasks": [], "message": "No tasks to export"}

        headers = cls._get_headers()

        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. Fetch or create project sections ("Week 1" to "Week 4")
            sec_res = await client.get(f"{ASANA_API_BASE}/projects/{project_gid}/sections", headers=headers)
            sections_map: Dict[str, str] = {}
            if sec_res.status_code == 200:
                for sec in sec_res.json().get("data", []):
                    sections_map[sec["name"]] = sec["gid"]

            for week_i in range(1, 5):
                sec_name = f"Week {week_i}"
                if sec_name not in sections_map:
                    create_sec = await client.post(
                        f"{ASANA_API_BASE}/projects/{project_gid}/sections",
                        headers=headers,
                        json={"data": {"name": sec_name}}
                    )
                    if create_sec.status_code == 201:
                        sections_map[sec_name] = create_sec.json()["data"]["gid"]

            # 2. Iterate and create or update tasks
            synced_tasks = []
            failed_tasks = []

            for t in tasks:
                mapped = cls.build_task_payload(t, s_date, job_id, job.get("target_url", ""))
                task_gid = t.get("asana_task_gid")
                section_name = mapped["section"]
                section_gid = sections_map.get(section_name)

                # Retry logic for rate limits
                max_retries = 3
                success = False

                for attempt in range(max_retries):
                    try:
                        if task_gid:
                            # Update existing task
                            update_res = await client.put(
                                f"{ASANA_API_BASE}/tasks/{task_gid}",
                                headers=headers,
                                json={"data": {"name": mapped["name"], "notes": mapped["notes"], "due_on": mapped["due_on"]}}
                            )
                            if update_res.status_code == 429:
                                retry_after = int(update_res.headers.get("Retry-After", 2))
                                await asyncio.sleep(retry_after)
                                continue
                            if update_res.status_code == 200:
                                success = True
                                synced_tasks.append({"id": t.get("id"), "asana_task_gid": task_gid, "action": "updated"})
                                break
                            else:
                                failed_tasks.append({"id": t.get("id"), "error": update_res.text})
                                break
                        else:
                            # Create new task
                            task_body: Dict[str, Any] = {
                                "name": mapped["name"],
                                "notes": mapped["notes"],
                                "due_on": mapped["due_on"],
                                "projects": [project_gid],
                                "workspace": workspace_gid,
                            }
                            create_res = await client.post(
                                f"{ASANA_API_BASE}/tasks",
                                headers=headers,
                                json={"data": task_body}
                            )
                            if create_res.status_code == 429:
                                retry_after = int(create_res.headers.get("Retry-After", 2))
                                await asyncio.sleep(retry_after)
                                continue
                            if create_res.status_code == 201:
                                created_gid = create_res.json()["data"]["gid"]
                                t["asana_task_gid"] = created_gid
                                # Move to appropriate section if available
                                if section_gid:
                                    await client.post(
                                        f"{ASANA_API_BASE}/sections/{section_gid}/addTask",
                                        headers=headers,
                                        json={"data": {"task": created_gid}}
                                    )
                                synced_tasks.append({"id": t.get("id"), "asana_task_gid": created_gid, "action": "created"})
                                success = True
                                break
                            else:
                                failed_tasks.append({"id": t.get("id"), "error": create_res.text})
                                break
                    except Exception as exc:
                        if attempt == max_retries - 1:
                            failed_tasks.append({"id": t.get("id"), "error": str(exc)})
                        await asyncio.sleep(1)

            # 3. Update strategy plan in DB with updated asana_task_gids
            strat = DBManager.get_strategy_plan(job_id)
            if strat and strat.get("plan"):
                plan_tasks = strat["plan"].get("tasks", [])
                task_map = {t["id"]: t.get("asana_task_gid") for t in tasks if t.get("asana_task_gid")}
                for pt in plan_tasks:
                    if pt.get("id") in task_map:
                        pt["asana_task_gid"] = task_map[pt["id"]]
                DBManager.save_strategy_plan(job_id, strat["plan"])

            return {
                "status": "success" if not failed_tasks else "partial_success",
                "synced_count": len(synced_tasks),
                "failed_count": len(failed_tasks),
                "synced_tasks": synced_tasks,
                "failed_tasks": failed_tasks
            }

    @classmethod
    def generate_asana_csv(cls, job_id: str, start_date: Optional[str] = None) -> str:
        """Generates Asana CSV mapping guide export file for manual import.
        Compatible with Asana Free & Paid plans:
        - Mapping Guide: Columns are mapped interactively during upload in Asana's CSV importer.
        - Dates formatted as MM/DD/YYYY.
        - Section header rows ending with a colon ('Week 1:') automatically organize tasks into sections.
        - Assignee left blank by default (importer requires workspace member work email).
        - Impact, Effort, Done When criteria, Issue IDs, and affected URLs embedded in Description
          so no paid Custom Fields are required.
        """
        job = DBManager.get_job(job_id)
        if not job:
            raise ValueError("Job not found")

        s_date_iso = start_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        s_date_formatted = format_to_mm_dd_yyyy(s_date_iso)
        tasks = cls.get_approved_strategy_tasks_for_job(job_id)

        output = io.StringIO()
        writer = csv.writer(output)
        
        # Asana CSV mapping guide headers:
        # Columns mapped interactively during upload in Asana's CSV importer
        headers = [
            "Name",
            "Description",
            "Assignee",
            "Start Date",
            "Due Date",
            "Dependencies"
        ]
        writer.writerow(headers)

        # Group tasks by milestone/week section
        sections: Dict[str, List[Dict[str, Any]]] = {}
        for t in tasks:
            week_val = t.get("week") or 1
            sec_name = f"Week {week_val}:"
            if sec_name not in sections:
                sections[sec_name] = []
            sections[sec_name].append(t)

        for sec_name, sec_tasks in sections.items():
            # Section header row ending with a colon (e.g. 'Week 1:')
            # Asana CSV importer automatically creates a Section from any row ending with ':'
            writer.writerow([sec_name, "", "", "", "", ""])

            for t in sec_tasks:
                mapped = cls.build_task_payload(t, s_date_iso, job_id, job.get("target_url", ""))
                due_date_formatted = format_to_mm_dd_yyyy(mapped["due_on"])
                deps = ", ".join(t.get("dependencies", [])) if t.get("dependencies") else ""

                writer.writerow([
                    mapped["name"],
                    mapped["notes"],
                    "",  # Assignee left blank by default (importer requires workspace work email)
                    s_date_formatted,  # Start Date (MM/DD/YYYY)
                    due_date_formatted,  # Due Date (MM/DD/YYYY)
                    deps  # Dependencies
                ])

        return output.getvalue()
