import json
from uuid import uuid4
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_sqlite_conn, DBManager

client = TestClient(app)

REAL_JOB_ID = "a83d2fb4-36ae-4ac2-a04b-c928ab7957b8"


def _create_test_job(
    status: str = "completed",
    current_step: str = "completed",
    with_competitors: bool = False,
    page_count: int = 3,
    error: str = None
) -> str:
    job_id = f"test-stats-{uuid4().hex[:8]}"
    competitors = ["https://comp1.com"] if with_competitors else []
    
    with get_sqlite_conn() as conn:
        conn.execute(
            """
            INSERT INTO jobs (
                id, target_url, status, current_step, cost_usd, error,
                competitor_domains, sitemap_entries_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (
                job_id,
                "https://example.com",
                status,
                current_step,
                0.05,
                error,
                json.dumps(competitors),
                json.dumps([{"url": "https://example.com/", "status_code": 200}])
            )
        )
        
        for i in range(page_count):
            p_id = f"p-{uuid4().hex[:6]}"
            conn.execute(
                """
                INSERT INTO crawl_pages (
                    id, job_id, url, status_code, title, meta_desc, h1,
                    canonical, word_count, links_out, inlinks_count,
                    indexable, response_time_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    p_id,
                    job_id,
                    f"https://example.com/page-{i}",
                    200 if i > 0 else 404,
                    f"Page Title {i}",
                    f"Meta description for page {i}",
                    f"Main Heading {i}",
                    f"https://example.com/page-{i}",
                    300,
                    5,
                    2,
                    1 if i > 0 else 0,
                    120
                )
            )

        if with_competitors:
            conn.execute(
                """
                INSERT INTO competitor_pages (
                    id, job_id, competitor_domain, url, title, word_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (f"cp-{uuid4().hex[:6]}", job_id, "comp1.com", "https://comp1.com/about", "Comp About", 450)
            )

    return job_id


def test_stats_normal_completed_job():
    """Verify /stats works smoothly on a normal completed job."""
    job_id = _create_test_job(status="completed", page_count=4)
    res = client.get(f"/api/jobs/{job_id}/stats")
    assert res.status_code == 200
    data = res.json()
    assert data["total_pages"] == 4
    assert data["status_200"] == 3
    assert data["status_4xx"] == 1
    assert "sitemap_missing_urls" in data
    assert isinstance(data["sitemap_missing_urls"], list)


def test_stats_job_with_competitors():
    """Verify /stats computes competitor page counts when competitors exist."""
    job_id = _create_test_job(status="completed", with_competitors=True)
    res = client.get(f"/api/jobs/{job_id}/stats")
    assert res.status_code == 200
    data = res.json()
    assert data["competitor_pages_count"] >= 1


def test_stats_job_without_competitors():
    """Verify /stats works when no competitors are attached to the job."""
    job_id = _create_test_job(status="completed", with_competitors=False)
    res = client.get(f"/api/jobs/{job_id}/stats")
    assert res.status_code == 200
    data = res.json()
    assert data["competitor_pages_count"] == 0


def test_stats_job_in_progress():
    """Verify /stats returns live progress metrics during job execution."""
    job_id = _create_test_job(status="crawling", current_step="crawling", page_count=2)
    res = client.get(f"/api/jobs/{job_id}/stats")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "crawling"
    assert data["current_step"] == "crawling"


def test_stats_failed_job():
    """Verify /stats succeeds even when a job has failed."""
    job_id = _create_test_job(status="failed", current_step="crawling", error="SSRF security check failed")
    res = client.get(f"/api/jobs/{job_id}/stats")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "failed"


def test_stats_job_zero_pages():
    """Verify /stats handles jobs with zero pages without division by zero or errors."""
    job_id = _create_test_job(status="completed", page_count=0)
    res = client.get(f"/api/jobs/{job_id}/stats")
    assert res.status_code == 200
    data = res.json()
    assert data["total_pages"] == 0
    assert data["avg_response_time_ms"] == 0.0
    assert data["sitemap_missing_urls"] == []


def test_smoke_every_job_endpoint_returns_no_500():
    """Smoke test calling EVERY GET /api/jobs/{id}/* endpoint for real completed job a83d2fb4."""
    # Ensure job a83d2fb4 exists in DB, or seed a comprehensive fixture
    job = DBManager.get_job(REAL_JOB_ID)
    if not job:
        test_id = _create_test_job(status="completed", with_competitors=True, page_count=5)
    else:
        test_id = REAL_JOB_ID

    pages = DBManager.get_crawl_pages(test_id, limit=5)
    first_page_id = pages[0]["id"] if pages else "dummy-page-id"

    endpoints = [
        f"/api/jobs/{test_id}",
        f"/api/jobs/{test_id}/pages",
        f"/api/jobs/{test_id}/pages?limit=10",
        f"/api/jobs/{test_id}/pages/{first_page_id}/inlinks",
        f"/api/jobs/{test_id}/psi",
        f"/api/jobs/{test_id}/issues",
        f"/api/jobs/{test_id}/performance",
        f"/api/jobs/{test_id}/research",
        f"/api/jobs/{test_id}/strategy",
        f"/api/jobs/{test_id}/content",
        f"/api/jobs/{test_id}/competitors",
        f"/api/jobs/{test_id}/agent-runs",
        f"/api/jobs/{test_id}/stats",
        f"/api/jobs/{test_id}/code-artifacts",
        f"/api/jobs/{test_id}/code-zip",
        f"/api/jobs/{test_id}/export/csv",
        f"/api/jobs/{test_id}/export/xlsx",
        f"/api/jobs/{test_id}/export/pdf",
        f"/api/asana/jobs/{test_id}/csv",
    ]

    for ep in endpoints:
        res = client.get(ep)
        assert res.status_code != 500, f"Endpoint {ep} crashed with HTTP 500: {res.text}"
        # Endpoints should return 200 or 404 (if optional sub-resource not seeded), but never 500
        assert res.status_code in [200, 404], f"Endpoint {ep} returned unexpected status {res.status_code}: {res.text}"
