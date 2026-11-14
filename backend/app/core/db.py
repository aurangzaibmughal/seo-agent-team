import json
import sqlite3
import os
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from app.core.config import settings

supabase_client = None
if settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY:
    try:
        from supabase import create_client
        supabase_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    except Exception as e:
        print(f"Warning: Failed to initialize Supabase client: {e}")

LOCAL_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "local_seo.db")

def get_sqlite_conn():
    conn = sqlite3.connect(LOCAL_DB_PATH, check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_sqlite_conn()
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            domain TEXT NOT NULL,
            platform TEXT DEFAULT 'unknown',
            agency_name TEXT DEFAULT '',
            agency_logo_url TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            project_id TEXT,
            target_url TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            current_step TEXT NOT NULL DEFAULT 'init',
            max_pages INTEGER NOT NULL DEFAULT 50,
            pages_crawled INTEGER NOT NULL DEFAULT 0,
            in_sitemap_not_crawled INTEGER DEFAULT 0,
            crawled_not_in_sitemap INTEGER DEFAULT 0,
            sitemap_found INTEGER DEFAULT 0,
            error TEXT,
            cost_usd REAL DEFAULT 0.0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS crawl_pages (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            url TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            title TEXT,
            meta_desc TEXT,
            h1 TEXT,
            canonical TEXT,
            word_count INTEGER DEFAULT 0,
            links_out INTEGER DEFAULT 0,
            inlinks_count INTEGER DEFAULT 0,
            indexable INTEGER DEFAULT 1,
            indexability_status TEXT DEFAULT 'indexable',
            redirect_url TEXT,
            content_type TEXT DEFAULT 'text/html',
            response_time_ms INTEGER DEFAULT 0,
            outlinks_list TEXT DEFAULT '[]',
            headings_json TEXT DEFAULT '[]',
            text_terms TEXT DEFAULT '[]',
            body_text TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS crawl_links (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            source_url TEXT NOT NULL,
            target_url TEXT NOT NULL,
            anchor_text TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS psi_results (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            url TEXT NOT NULL,
            strategy TEXT NOT NULL,
            performance_score INTEGER,
            lcp_ms REAL,
            cls REAL,
            inp_or_tbt_ms REAL,
            fcp_ms REAL,
            ttfb_ms REAL,
            raw_json TEXT,
            error TEXT,
            fetched_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_runs (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            agent TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            mode TEXT DEFAULT 'fallback',
            model TEXT,
            failure_reason TEXT,
            input_ref TEXT,
            output_json TEXT,
            confidence REAL DEFAULT 1.0,
            started_at TEXT,
            finished_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
        )
    """)
    try:
        cursor.execute("ALTER TABLE agent_runs ADD COLUMN failure_reason TEXT")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE agent_runs ADD COLUMN model TEXT")
    except Exception:
        pass
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS google_connections (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT 'default_user',
            google_email TEXT NOT NULL,
            encrypted_refresh_token TEXT NOT NULL,
            scopes TEXT NOT NULL,
            created_at TEXT NOT NULL,
            revoked_at TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS project_google_links (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            gsc_site_url TEXT,
            ga4_property_id TEXT,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS performance_snapshots (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            file_url TEXT NOT NULL,
            format TEXT NOT NULL DEFAULT 'pdf',
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gsc_query_pages (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            project_id TEXT,
            query TEXT NOT NULL,
            page TEXT NOT NULL,
            clicks INTEGER DEFAULT 0,
            impressions INTEGER DEFAULT 0,
            ctr REAL DEFAULT 0.0,
            position REAL DEFAULT 0.0,
            period TEXT DEFAULT 'last_90_days',
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS competitor_pages (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            competitor_domain TEXT NOT NULL,
            url TEXT NOT NULL,
            title TEXT,
            headings_json TEXT DEFAULT '[]',
            word_count INTEGER DEFAULT 0,
            schema_types TEXT DEFAULT '[]',
            sitemap_size INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS research_snapshots (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS strategy_plans (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            plan_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS content_outputs (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            output_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
        )
    """)

    # Auto-migration safety
    try:
        cursor.execute("ALTER TABLE agent_runs ADD COLUMN mode TEXT DEFAULT 'fallback'")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE agent_runs ADD COLUMN tokens_prompt INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE agent_runs ADD COLUMN tokens_completion INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE agent_runs ADD COLUMN cost_usd REAL DEFAULT 0.0")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE crawl_pages ADD COLUMN inlinks_count INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE crawl_pages ADD COLUMN headings_json TEXT DEFAULT '[]'")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE crawl_pages ADD COLUMN text_terms TEXT DEFAULT '[]'")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE crawl_pages ADD COLUMN body_text TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN in_sitemap_not_crawled INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE jobs ADD COLUMN crawled_not_in_sitemap INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE jobs ADD COLUMN sitemap_found INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN psi_status TEXT DEFAULT 'pending'")
        cursor.execute("ALTER TABLE jobs ADD COLUMN is_demo INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE jobs ADD COLUMN competitor_domains TEXT DEFAULT '[]'")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN failed_fetches_json TEXT DEFAULT '[]'")
        cursor.execute("ALTER TABLE jobs ADD COLUMN crawl_incomplete INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE jobs ADD COLUMN sitemap_status TEXT DEFAULT 'pending'")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE projects ADD COLUMN platform_confidence REAL DEFAULT 0.0")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN platform TEXT DEFAULT 'unknown'")
        cursor.execute("ALTER TABLE jobs ADD COLUMN platform_confidence REAL DEFAULT 0.0")
        cursor.execute("ALTER TABLE jobs ADD COLUMN detected_platform TEXT DEFAULT 'unknown'")
        cursor.execute("ALTER TABLE jobs ADD COLUMN detected_platform_confidence REAL DEFAULT 0.0")
        cursor.execute("ALTER TABLE jobs ADD COLUMN router_type TEXT DEFAULT 'app'")
    except Exception:
        pass
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS code_outputs (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            output_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS review_items (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            item_type TEXT NOT NULL,
            item_ref TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            reviewer_note TEXT DEFAULT '',
            original_payload_json TEXT DEFAULT '{}',
            edited_payload_json TEXT DEFAULT '{}',
            updated_at TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS review_events (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            action TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            reviewer_note TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
        )
    """)
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN sitemap_entries_json TEXT DEFAULT '[]'")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN completeness_status TEXT DEFAULT 'complete'")
    except Exception:
        pass
    conn.commit()
    conn.close()

init_db()

class DBManager:
    @staticmethod
    def create_job(
        target_url: str,
        max_pages: int = 50,
        project_id: Optional[str] = None,
        competitor_domains: Optional[List[str]] = None,
        is_demo: bool = False,
        fresh_psi: bool = False
    ) -> Dict[str, Any]:
        job_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        job_data = {
            "id": job_id,
            "project_id": project_id,
            "target_url": target_url,
            "status": "pending",
            "current_step": "init",
            "max_pages": max_pages,
            "pages_crawled": 0,
            "in_sitemap_not_crawled": 0,
            "crawled_not_in_sitemap": 0,
            "sitemap_found": 0,
            "psi_status": "pending",
            "is_demo": 1 if is_demo else 0,
            "fresh_psi": 1 if fresh_psi else 0,
            "competitor_domains": json.dumps(competitor_domains or []),
            "cost_usd": 0.0,
            "created_at": now,
            "updated_at": now
        }
        if supabase_client:
            try:
                res = supabase_client.table("jobs").insert(job_data).execute()
                if res.data:
                    return res.data[0]
            except Exception as e:
                print(f"Supabase error creating job: {e}")

        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO jobs (id, project_id, target_url, status, current_step, max_pages, pages_crawled, psi_status, is_demo, competitor_domains, cost_usd, created_at, updated_at)
            VALUES (?, ?, ?, 'pending', 'init', ?, 0, 'pending', ?, ?, 0.0, ?, ?)
        """, (job_id, project_id, target_url, max_pages, 1 if is_demo else 0, json.dumps(competitor_domains or []), now, now))
        conn.commit()
        conn.close()
        return job_data

    @staticmethod
    def update_job(job_id: str, updates: Dict[str, Any]):
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        if supabase_client:
            try:
                supabase_client.table("jobs").update(updates).eq("id", job_id).execute()
                return
            except Exception as e:
                print(f"Supabase error updating job: {e}")

        conn = get_sqlite_conn()
        cursor = conn.cursor()
        fields = ", ".join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [job_id]
        cursor.execute(f"UPDATE jobs SET {fields} WHERE id = ?", values)
        conn.commit()
        conn.close()

    @staticmethod
    def get_job(job_id: str) -> Optional[Dict[str, Any]]:
        if supabase_client:
            try:
                res = supabase_client.table("jobs").select("*").eq("id", job_id).execute()
                if res.data:
                    return res.data[0]
            except Exception as e:
                print(f"Supabase error fetching job: {e}")

        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    @staticmethod
    def get_previous_completed_job_for_domain(target_url: str, exclude_job_id: str) -> Optional[Dict[str, Any]]:
        from urllib.parse import urlparse
        domain = urlparse(target_url).netloc.lower()
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM jobs 
            WHERE id != ? AND (status = 'completed' OR pages_crawled > 0)
            ORDER BY created_at DESC
        """, (exclude_job_id,))
        rows = cursor.fetchall()
        conn.close()
        for r in rows:
            d = dict(r)
            if urlparse(d.get("target_url", "")).netloc.lower() == domain:
                return d
        return None

    @staticmethod
    def get_daily_cost_usd() -> float:
        """Returns the sum of cost_usd for jobs created in the last 24 hours."""
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        one_day_ago = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        cursor.execute("SELECT SUM(cost_usd) FROM jobs WHERE created_at >= ?", (one_day_ago,))
        res = cursor.fetchone()
        conn.close()
        return float(res[0]) if (res and res[0] is not None) else 0.0

    @staticmethod
    def get_jobs_history(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Returns ordered jobs with issue counts, pending review count, mode, and cost."""
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, target_url, status, current_step, max_pages, pages_crawled, 
                   cost_usd, crawl_incomplete, completeness_status, incomplete_reasons_json,
                   platform, router_type, is_demo, created_at, updated_at
            FROM jobs
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))
        jobs = [dict(r) for r in cursor.fetchall()]

        for job in jobs:
            j_id = job["id"]
            cursor.execute("SELECT output_json FROM agent_runs WHERE job_id = ? AND agent = 'verifier'", (j_id,))
            ver_row = cursor.fetchone()
            verified_count = 0
            rejected_count = 0
            if ver_row and ver_row[0]:
                try:
                    ver_data = json.loads(ver_row[0])
                    verified_count = len(ver_data.get("verified_issues", []))
                    rejected_count = len(ver_data.get("rejected_issues", []))
                except Exception:
                    pass
            job["verified_issues_count"] = verified_count
            job["rejected_issues_count"] = rejected_count

            cursor.execute("SELECT COUNT(*) FROM review_items WHERE job_id = ? AND status = 'pending'", (j_id,))
            p_row = cursor.fetchone()
            job["pending_reviews_count"] = p_row[0] if p_row else 0

            cursor.execute("SELECT agent, mode FROM agent_runs WHERE job_id = ?", (j_id,))
            job["agent_modes"] = {r["agent"]: r["mode"] for r in cursor.fetchall()}

        conn.close()
        return jobs

    @staticmethod
    def delete_job(job_id: str) -> bool:
        """Purges a job and all associated child data."""
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        tables = [
            "crawl_pages", "crawl_links", "agent_runs", "review_items", "review_events",
            "performance_snapshots", "research_snapshots", "strategy_plans", "content_outputs",
            "code_outputs", "competitor_pages", "psi_results"
        ]
        for t in tables:
            try:
                cursor.execute(f"DELETE FROM {t} WHERE job_id = ?", (job_id,))
            except Exception:
                pass
        cursor.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()
        conn.close()
        return True

    @staticmethod
    def mark_stuck_jobs_as_interrupted() -> int:
        """Finds any jobs stuck in 'running' or 'crawling' state at server startup and marks them 'interrupted'."""
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            UPDATE jobs 
            SET status = 'interrupted', error = 'Server restarted while job was in progress', updated_at = ?
            WHERE status IN ('running', 'crawling', 'in_progress')
        """, (now,))
        count = cursor.rowcount
        conn.commit()
        conn.close()
        return count

    # =========================================================================
    # Milestone 6: Review & Approval Workflow
    # =========================================================================

    @staticmethod
    @staticmethod
    def save_review_item(item_data: Dict[str, Any]):
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            INSERT OR REPLACE INTO review_items (id, job_id, item_type, item_ref, title, status, reviewer_note, original_payload_json, edited_payload_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item_data.get("id") or str(uuid4()),
            item_data["job_id"],
            item_data.get("item_type", "code_artifact"),
            item_data.get("item_ref", ""),
            item_data.get("title", ""),
            item_data.get("status", "pending"),
            item_data.get("reviewer_note", ""),
            item_data.get("original_payload_json", "{}"),
            item_data.get("edited_payload_json", "{}"),
            item_data.get("updated_at", now)
        ))
        conn.commit()
        conn.close()

    @staticmethod
    def populate_review_items_for_job(job_id: str) -> int:
        """Populates review items from content rewrites, briefs, strategy tasks, and code redirects without duplicating."""
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        inserted = 0

        # Existing items set
        cursor.execute("SELECT item_type, item_ref FROM review_items WHERE job_id = ?", (job_id,))
        existing_items = {(row[0], row[1]) for row in cursor.fetchall()}

        # 1. Content rewrites
        cont = DBManager.get_content_output(job_id)
        if cont and cont.get("content"):
            c_data = cont["content"]
            for rw in c_data.get("rewrites", []):
                r_url = rw.get("url", "")
                if ("meta_rewrite", r_url) in existing_items:
                    continue
                r_id = f"REV-RW-{uuid4().hex[:8]}"
                cursor.execute("""
                    INSERT OR IGNORE INTO review_items (id, job_id, item_type, item_ref, title, status, original_payload_json, edited_payload_json, updated_at)
                    VALUES (?, ?, 'meta_rewrite', ?, ?, 'pending', ?, '{}', ?)
                """, (r_id, job_id, r_url, f"Rewrite: {r_url}", json.dumps(rw), now))
                if cursor.rowcount > 0:
                    inserted += 1
                    existing_items.add(("meta_rewrite", r_url))

            for br in c_data.get("briefs", []):
                b_kw = br.get("primary_keyword", "")
                if ("content_brief", b_kw) in existing_items:
                    continue
                b_id = f"REV-BR-{uuid4().hex[:8]}"
                cursor.execute("""
                    INSERT OR IGNORE INTO review_items (id, job_id, item_type, item_ref, title, status, original_payload_json, edited_payload_json, updated_at)
                    VALUES (?, ?, 'content_brief', ?, ?, 'pending', ?, '{}', ?)
                """, (b_id, job_id, b_kw, f"Brief: {b_kw}", json.dumps(br), now))
                if cursor.rowcount > 0:
                    inserted += 1
                    existing_items.add(("content_brief", b_kw))

        # 2. Strategy tasks
        strat = DBManager.get_strategy_plan(job_id)
        if strat and strat.get("plan"):
            for t in strat["plan"].get("tasks", []):
                t_id = t.get("id") or t.get("task_id") or ""
                if ("strategy_task", t_id) in existing_items:
                    continue
                r_id = f"REV-TSK-{uuid4().hex[:8]}"
                cursor.execute("""
                    INSERT OR IGNORE INTO review_items (id, job_id, item_type, item_ref, title, status, original_payload_json, edited_payload_json, updated_at)
                    VALUES (?, ?, 'strategy_task', ?, ?, 'pending', ?, '{}', ?)
                """, (r_id, job_id, t_id, f"Strategy: {t.get('title', '')}", json.dumps(t), now))
                if cursor.rowcount > 0:
                    inserted += 1
                    existing_items.add(("strategy_task", t_id))

        conn.commit()
        conn.close()
        return inserted

    @staticmethod
    def get_review_items(job_id: str, item_type: Optional[str] = None, status: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        query = "SELECT * FROM review_items WHERE job_id = ?"
        params: List[Any] = [job_id]
        if item_type:
            query += " AND item_type = ?"
            params.append(item_type)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC"
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        conn.close()

        results = []
        for r in rows:
            d = dict(r)
            try:
                d["original_payload"] = json.loads(d.get("original_payload_json") or "{}")
            except Exception:
                d["original_payload"] = {}
            try:
                d["edited_payload"] = json.loads(d.get("edited_payload_json") or "{}")
            except Exception:
                d["edited_payload"] = {}
            results.append(d)
        return results

    @staticmethod
    def get_review_counts(job_id: str) -> Dict[str, int]:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT status, COUNT(*) FROM review_items WHERE job_id = ? GROUP BY status", (job_id,))
        counts = {r[0]: r[1] for r in cursor.fetchall()}
        conn.close()
        total = sum(counts.values())
        return {
            "total": total,
            "pending": counts.get("pending", 0),
            "approved": counts.get("approved", 0),
            "rejected": counts.get("rejected", 0),
            "edited": counts.get("edited", 0)
        }

    @staticmethod
    def get_review_events(job_id: str, item_id: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        if item_id:
            cursor.execute("SELECT * FROM review_events WHERE job_id = ? AND item_id = ? ORDER BY timestamp ASC", (job_id, item_id))
        else:
            cursor.execute("SELECT * FROM review_events WHERE job_id = ? ORDER BY timestamp ASC", (job_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def update_review_item_status(item_id: str, status: str, note: str = "") -> Optional[Dict[str, Any]]:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM review_items WHERE id = ?", (item_id,))
        item = cursor.fetchone()
        if not item:
            conn.close()
            return None

        old_status = item["status"]
        now = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            UPDATE review_items 
            SET status = ?, reviewer_note = ?, updated_at = ?
            WHERE id = ?
        """, (status, note, now, item_id))

        # Log event
        cursor.execute("""
            INSERT INTO review_events (id, job_id, item_id, action, old_value, new_value, reviewer_note, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (str(uuid4()), item["job_id"], item_id, f"status_change_to_{status}", old_status, status, note, now))

        conn.commit()
        cursor.execute("SELECT * FROM review_items WHERE id = ?", (item_id,))
        updated = cursor.fetchone()
        conn.close()
        return dict(updated) if updated else None

    @staticmethod
    def edit_review_item(job_id: str, item_id: str, edited_payload: Dict[str, Any], reviewer_note: str = "human-edited") -> Dict[str, Any]:
        # Validate character bounds
        if "suggested_title" in edited_payload:
            val = str(edited_payload["suggested_title"]).strip()
            if len(val) > 60:
                raise ValueError("suggested_title exceeds maximum 60 characters limit")
        if "suggested_meta" in edited_payload:
            val = str(edited_payload["suggested_meta"]).strip()
            if len(val) > 155:
                raise ValueError("suggested_meta exceeds maximum 155 characters limit")

        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM review_items WHERE id = ?", (item_id,))
        item = cursor.fetchone()
        if not item:
            conn.close()
            raise ValueError("Review item not found")

        now = datetime.now(timezone.utc).isoformat()
        old_val = item["edited_payload_json"] or item["original_payload_json"]
        new_val = json.dumps(edited_payload)

        cursor.execute("""
            UPDATE review_items
            SET status = 'edited', edited_payload_json = ?, reviewer_note = ?, updated_at = ?
            WHERE id = ?
        """, (new_val, reviewer_note, now, item_id))

        cursor.execute("""
            INSERT INTO review_events (id, job_id, item_id, action, old_value, new_value, reviewer_note, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (str(uuid4()), job_id, item_id, "edit", old_val, new_val, reviewer_note, now))

        conn.commit()
        cursor.execute("SELECT * FROM review_items WHERE id = ?", (item_id,))
        res = dict(cursor.fetchone())
        conn.close()
        res["edited_payload"] = edited_payload
        return res

    @staticmethod
    def bulk_approve_review_items(job_id: str, low_risk_only: bool = False, item_types: Optional[List[str]] = None) -> int:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        query = "SELECT id, status FROM review_items WHERE job_id = ? AND status = 'pending'"
        params: List[Any] = [job_id]
        if item_types:
            placeholders = ",".join("?" for _ in item_types)
            query += f" AND item_type IN ({placeholders})"
            params.extend(item_types)

        cursor.execute(query, tuple(params))
        items_to_approve = cursor.fetchall()
        now = datetime.now(timezone.utc).isoformat()
        count = 0

        for r in items_to_approve:
            iid = r["id"]
            cursor.execute("UPDATE review_items SET status = 'approved', updated_at = ? WHERE id = ?", (now, iid))
            cursor.execute("""
                INSERT INTO review_events (id, job_id, item_id, action, old_value, new_value, reviewer_note, timestamp)
                VALUES (?, ?, ?, 'bulk_approve', 'pending', 'approved', 'bulk approved by user', ?)
            """, (str(uuid4()), job_id, iid, now))
            count += 1

        conn.commit()
        conn.close()
        return count


    @staticmethod
    def save_crawl_page(page_data: Dict[str, Any]) -> str:
        page_id = str(uuid4())
        page_data["id"] = page_id
        page_data["created_at"] = datetime.now(timezone.utc).isoformat()

        if supabase_client:
            try:
                supabase_client.table("crawl_pages").insert(page_data).execute()
                return page_id
            except Exception as e:
                print(f"Supabase error saving page: {e}")

        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO crawl_pages (
                id, job_id, url, status_code, title, meta_desc, h1, canonical,
                word_count, links_out, inlinks_count, indexable, indexability_status, redirect_url,
                content_type, response_time_ms, outlinks_list, headings_json, text_terms, body_text, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            page_id,
            page_data["job_id"],
            page_data["url"],
            page_data["status_code"],
            page_data.get("title"),
            page_data.get("meta_desc"),
            page_data.get("h1"),
            page_data.get("canonical"),
            page_data.get("word_count", 0),
            page_data.get("links_out", 0),
            page_data.get("inlinks_count", 0),
            1 if page_data.get("indexable", True) else 0,
            page_data.get("indexability_status", "indexable"),
            page_data.get("redirect_url"),
            page_data.get("content_type", "text/html"),
            page_data.get("response_time_ms", 0),
            json.dumps(page_data.get("outlinks_list", [])),
            json.dumps(page_data.get("headings", [])),
            json.dumps(page_data.get("text_terms", [])),
            (page_data.get("body_text") or "")[:20000],
            page_data["created_at"]
        ))
        conn.commit()
        conn.close()
        return page_id

    @staticmethod
    def save_crawl_links(links: List[Dict[str, Any]]):
        if not links:
            return
        now = datetime.now(timezone.utc).isoformat()
        records = []
        for l in links:
            records.append((
                str(uuid4()),
                l["job_id"],
                l["source_url"],
                l["target_url"],
                l.get("anchor_text", ""),
                now
            ))
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.executemany("""
            INSERT INTO crawl_links (id, job_id, source_url, target_url, anchor_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, records)
        conn.commit()
        conn.close()

    @staticmethod
    def get_inlinks_for_url(job_id: str, target_url: str) -> List[Dict[str, Any]]:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT source_url, anchor_text 
            FROM crawl_links 
            WHERE job_id = ? AND (target_url = ? OR target_url = ?)
        """, (job_id, target_url, target_url.rstrip("/")))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def update_inlinks_counts(job_id: str):
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE crawl_pages
            SET inlinks_count = (
                SELECT COUNT(DISTINCT source_url)
                FROM crawl_links
                WHERE crawl_links.job_id = crawl_pages.job_id
                AND (crawl_links.target_url = crawl_pages.url OR crawl_links.target_url = rtrim(crawl_pages.url, '/'))
            )
            WHERE job_id = ?
        """, (job_id,))
        conn.commit()
        conn.close()

    @staticmethod
    def get_crawl_pages(job_id: str, limit: int = 500) -> List[Dict[str, Any]]:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM crawl_pages WHERE job_id = ? ORDER BY created_at ASC LIMIT ?", (job_id, limit))
        rows = cursor.fetchall()
        conn.close()

        result = []
        for r in rows:
            d = dict(r)
            d["indexable"] = bool(d["indexable"])
            try:
                d["outlinks_list"] = json.loads(d["outlinks_list"]) if d.get("outlinks_list") else []
            except Exception:
                d["outlinks_list"] = []
            try:
                d["headings"] = json.loads(d.get("headings_json", "[]"))
            except Exception:
                d["headings"] = []
            try:
                d["text_terms"] = json.loads(d.get("text_terms", "[]"))
            except Exception:
                d["text_terms"] = []
            result.append(d)
        return result

    @staticmethod
    def get_crawl_page_by_id(page_id: str) -> Optional[Dict[str, Any]]:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM crawl_pages WHERE id = ?", (page_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        d = dict(row)
        d["indexable"] = bool(d["indexable"])
        try:
            d["outlinks_list"] = json.loads(d["outlinks_list"]) if d.get("outlinks_list") else []
        except Exception:
            d["outlinks_list"] = []
        try:
            d["headings"] = json.loads(d.get("headings_json", "[]"))
        except Exception:
            d["headings"] = []
        try:
            d["text_terms"] = json.loads(d.get("text_terms", "[]"))
        except Exception:
            d["text_terms"] = []
        return d

    # PSI methods
    @staticmethod
    def get_psi_cached(url: str, strategy: str) -> Optional[Dict[str, Any]]:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM psi_results
            WHERE url = ? AND strategy = ? AND fetched_at >= ? AND error IS NULL AND performance_score IS NOT NULL
            ORDER BY fetched_at DESC LIMIT 1
        """, (url, strategy, cutoff))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        d = dict(row)
        try:
            d["raw_json"] = json.loads(d["raw_json"]) if d.get("raw_json") else None
        except Exception:
            pass
        return d

    @staticmethod
    def save_psi_result(psi_data: Dict[str, Any]) -> str:
        psi_id = str(uuid4())
        psi_data["id"] = psi_id
        if "fetched_at" not in psi_data:
            psi_data["fetched_at"] = datetime.now(timezone.utc).isoformat()

        raw_obj = psi_data.get("raw_json") or {}
        if not isinstance(raw_obj, dict):
            try:
                raw_obj = json.loads(raw_obj)
            except Exception:
                raw_obj = {}
        if "is_cached" in psi_data:
            raw_obj["is_cached"] = psi_data["is_cached"]
        if "cached_measured_at" in psi_data:
            raw_obj["cached_measured_at"] = psi_data["cached_measured_at"]

        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO psi_results (
                id, job_id, url, strategy, performance_score, lcp_ms, cls,
                inp_or_tbt_ms, fcp_ms, ttfb_ms, raw_json, error, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            psi_id,
            psi_data["job_id"],
            psi_data["url"],
            psi_data["strategy"],
            psi_data.get("performance_score"),
            psi_data.get("lcp_ms"),
            psi_data.get("cls"),
            psi_data.get("inp_or_tbt_ms"),
            psi_data.get("fcp_ms"),
            psi_data.get("ttfb_ms"),
            json.dumps(raw_obj) if raw_obj else None,
            psi_data.get("error"),
            psi_data["fetched_at"]
        ))
        conn.commit()
        conn.close()
        return psi_id

    @staticmethod
    def get_psi_results(job_id: str) -> List[Dict[str, Any]]:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM psi_results WHERE job_id = ? ORDER BY fetched_at ASC", (job_id,))
        rows = cursor.fetchall()
        conn.close()
        results = []
        for r in rows:
            d = dict(r)
            try:
                raw_parsed = json.loads(d["raw_json"]) if d.get("raw_json") else None
                d["raw_json"] = raw_parsed
                if isinstance(raw_parsed, dict):
                    d["is_cached"] = raw_parsed.get("is_cached", False)
                    d["cached_measured_at"] = raw_parsed.get("cached_measured_at")
            except Exception:
                pass
            results.append(d)
        return results

    # Agent runs
    @staticmethod
    def save_agent_run(run_data: Dict[str, Any]) -> str:
        run_id = str(uuid4())
        run_data["id"] = run_id
        now = datetime.now(timezone.utc).isoformat()
        if "created_at" not in run_data:
            run_data["created_at"] = now

        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO agent_runs (
                id, job_id, agent, status, mode, model, failure_reason, tokens_prompt,
                tokens_completion, cost_usd, input_ref, output_json,
                confidence, started_at, finished_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id,
            run_data["job_id"],
            run_data["agent"],
            run_data.get("status", "pending"),
            run_data.get("mode", "fallback"),
            run_data.get("model"),
            run_data.get("failure_reason"),
            run_data.get("tokens_prompt", 0),
            run_data.get("tokens_completion", 0),
            run_data.get("cost_usd", 0.0),
            json.dumps(run_data.get("input_ref", [])),
            json.dumps(run_data.get("output_json", {})),
            run_data.get("confidence", 1.0),
            run_data.get("started_at"),
            run_data.get("finished_at"),
            run_data["created_at"]
        ))
        conn.commit()
        conn.close()
        return run_id

    @staticmethod
    def get_agent_runs(job_id: str) -> List[Dict[str, Any]]:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM agent_runs WHERE job_id = ? ORDER BY created_at ASC", (job_id,))
        rows = cursor.fetchall()
        conn.close()
        results = []
        for r in rows:
            d = dict(r)
            try:
                d["input_ref"] = json.loads(d["input_ref"]) if d.get("input_ref") else []
                d["output_json"] = json.loads(d["output_json"]) if d.get("output_json") else {}
            except Exception:
                pass
            results.append(d)
        return results

    # Google OAuth Connections (M3)
    @staticmethod
    def save_google_connection(user_id: str, email: str, encrypted_refresh_token: str, scopes: List[str]) -> str:
        conn_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        # Revoke previous active tokens for this user/email
        cursor.execute("""
            UPDATE google_connections SET revoked_at = ?
            WHERE user_id = ? AND google_email = ? AND revoked_at IS NULL
        """, (now, user_id, email))
        cursor.execute("""
            INSERT INTO google_connections (id, user_id, google_email, encrypted_refresh_token, scopes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (conn_id, user_id, email, encrypted_refresh_token, json.dumps(scopes), now))
        conn.commit()
        conn.close()
        return conn_id

    @staticmethod
    def get_google_connection(user_id: str) -> Optional[Dict[str, Any]]:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM google_connections
            WHERE user_id = ? AND revoked_at IS NULL
            ORDER BY created_at DESC LIMIT 1
        """, (user_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        d = dict(row)
        try:
            d["scopes"] = json.loads(d["scopes"]) if d.get("scopes") else []
        except Exception:
            d["scopes"] = []
        return d

    @staticmethod
    def revoke_google_connection(user_id: str):
        now = datetime.now(timezone.utc).isoformat()
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE google_connections SET revoked_at = ?
            WHERE user_id = ? AND revoked_at IS NULL
        """, (now, user_id))
        conn.commit()
        conn.close()

    # Performance Snapshots (M3)
    @staticmethod
    def save_performance_snapshot(job_id: str, snapshot_data: Dict[str, Any]) -> str:
        snapshot_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO performance_snapshots (id, job_id, snapshot_json, created_at)
            VALUES (?, ?, ?, ?)
        """, (snapshot_id, job_id, json.dumps(snapshot_data), now))
        conn.commit()
        conn.close()
        return snapshot_id

    @staticmethod
    def get_performance_snapshot(job_id: str) -> Optional[Dict[str, Any]]:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM performance_snapshots WHERE job_id = ? ORDER BY created_at DESC LIMIT 1
        """, (job_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        d = dict(row)
        try:
            d["snapshot_json"] = json.loads(d["snapshot_json"]) if d.get("snapshot_json") else {}
        except Exception:
            d["snapshot_json"] = {}
        return d

    # Reports (M3)
    @staticmethod
    def save_report_record(job_id: str, file_url: str, format_type: str = "pdf") -> str:
        report_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO reports (id, job_id, file_url, format, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (report_id, job_id, file_url, format_type, now))
        conn.commit()
        conn.close()
        return report_id

    @staticmethod
    def get_reports(job_id: str) -> List[Dict[str, Any]]:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reports WHERE job_id = ? ORDER BY created_at DESC", (job_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # M4 - GSC Query Pages
    @staticmethod
    def save_gsc_query_pages(job_id: str, rows: List[Dict[str, Any]]) -> int:
        now = datetime.now(timezone.utc).isoformat()
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        count = 0
        for r in rows:
            qid = str(uuid4())
            cursor.execute("""
                INSERT INTO gsc_query_pages (
                    id, job_id, project_id, query, page, clicks, impressions, ctr, position, period, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                qid, job_id, r.get("project_id"), r.get("query", ""), r.get("page", ""),
                r.get("clicks", 0), r.get("impressions", 0), r.get("ctr", 0.0),
                r.get("position", 0.0), r.get("period", "last_90_days"), now
            ))
            count += 1
        conn.commit()
        conn.close()
        return count

    @staticmethod
    def get_gsc_query_pages(job_id: str) -> List[Dict[str, Any]]:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM gsc_query_pages WHERE job_id = ? ORDER BY impressions DESC", (job_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # M4 - Competitor Pages
    @staticmethod
    def save_competitor_page(job_id: str, comp_data: Dict[str, Any]) -> str:
        cid = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO competitor_pages (
                id, job_id, competitor_domain, url, title, headings_json,
                word_count, schema_types, sitemap_size, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            cid, job_id, comp_data["competitor_domain"], comp_data["url"],
            comp_data.get("title"),
            json.dumps(comp_data.get("headings", [])),
            comp_data.get("word_count", 0),
            json.dumps(comp_data.get("schema_types", [])),
            comp_data.get("sitemap_size", 0),
            now
        ))
        conn.commit()
        conn.close()
        return cid

    @staticmethod
    def get_competitor_pages(job_id: str) -> List[Dict[str, Any]]:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM competitor_pages WHERE job_id = ? ORDER BY created_at ASC", (job_id,))
        rows = cursor.fetchall()
        conn.close()
        res = []
        for r in rows:
            d = dict(r)
            try:
                d["headings"] = json.loads(d.get("headings_json", "[]"))
                d["schema_types"] = json.loads(d.get("schema_types", "[]"))
            except Exception:
                d["headings"] = []
                d["schema_types"] = []
            res.append(d)
        return res

    # M4 - Research Snapshots
    @staticmethod
    def save_research_snapshot(job_id: str, snapshot_data: Dict[str, Any]) -> str:
        sid = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO research_snapshots (id, job_id, snapshot_json, created_at)
            VALUES (?, ?, ?, ?)
        """, (sid, job_id, json.dumps(snapshot_data), now))
        conn.commit()
        conn.close()
        return sid

    @staticmethod
    def get_research_snapshot(job_id: str) -> Optional[Dict[str, Any]]:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM research_snapshots WHERE job_id = ? ORDER BY created_at DESC LIMIT 1", (job_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        d = dict(row)
        try:
            d["snapshot"] = json.loads(d["snapshot_json"]) if d.get("snapshot_json") else {}
        except Exception:
            d["snapshot"] = {}
        return d

    # M4 - Strategy Plans
    @staticmethod
    def save_strategy_plan(job_id: str, plan_data: Dict[str, Any]) -> str:
        pid = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO strategy_plans (id, job_id, plan_json, created_at)
            VALUES (?, ?, ?, ?)
        """, (pid, job_id, json.dumps(plan_data), now))
        conn.commit()
        conn.close()
        return pid

    @staticmethod
    def get_strategy_plan(job_id: str) -> Optional[Dict[str, Any]]:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM strategy_plans WHERE job_id = ? ORDER BY created_at DESC LIMIT 1", (job_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        d = dict(row)
        try:
            d["plan"] = json.loads(d["plan_json"]) if d.get("plan_json") else {}
        except Exception:
            d["plan"] = {}
        return d

    # M4 - Content Outputs
    @staticmethod
    def save_content_output(job_id: str, content_data: Dict[str, Any]) -> str:
        cid = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO content_outputs (id, job_id, output_json, created_at)
            VALUES (?, ?, ?, ?)
        """, (cid, job_id, json.dumps(content_data), now))
        conn.commit()
        conn.close()
        return cid

    @staticmethod
    def get_content_output(job_id: str) -> Optional[Dict[str, Any]]:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM content_outputs WHERE job_id = ? ORDER BY created_at DESC LIMIT 1", (job_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        d = dict(row)
        try:
            d["content"] = json.loads(d["output_json"]) if d.get("output_json") else {}
        except Exception:
            d["content"] = {}
        return d

    @staticmethod
    def save_code_output(job_id: str, code_data: Dict[str, Any]) -> str:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        cid = str(uuid4())
        cursor.execute("DELETE FROM code_outputs WHERE job_id = ?", (job_id,))
        cursor.execute("""
            INSERT INTO code_outputs (id, job_id, output_json, created_at)
            VALUES (?, ?, ?, ?)
        """, (cid, job_id, json.dumps(code_data), now))
        conn.commit()
        conn.close()
        return cid

    @staticmethod
    def get_code_output(job_id: str) -> Optional[Dict[str, Any]]:
        conn = get_sqlite_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM code_outputs WHERE job_id = ? ORDER BY created_at DESC LIMIT 1", (job_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        d = dict(row)
        try:
            d["code"] = json.loads(d["output_json"]) if d.get("output_json") else {}
        except Exception:
            d["code"] = {}
        return d
