import asyncio
import json
import sqlite3
import time
import io
import re
import zipfile
import difflib
from urllib.parse import urlparse

from app.core.db import DBManager, get_sqlite_conn
from app.agents.orchestrator import run_full_pipeline
from app.code_generator.packager import CodePackager
from app.models.agent_schemas import GeneratedArtifact

async def main():
    target_url = "https://webspire-agency.vercel.app/"
    max_pages = 30
    is_demo = False

    print("=== CREATING AND RUNNING FRESH REAL JOB (BATCH A.2) ===")
    job = DBManager.create_job(
        target_url=target_url,
        max_pages=max_pages,
        project_id=None,
        competitor_domains=[],
        is_demo=is_demo
    )
    job_id = job["id"]
    print(f"Created Real Job ID: {job_id}")

    start_time = time.time()
    await run_full_pipeline(job_id, target_url, max_pages, None)
    elapsed = int(time.time() - start_time)
    print(f"\nPipeline finished in {elapsed}s.")

    # 1. Inspect DB Job Record
    conn = get_sqlite_conn()
    c = conn.cursor()
    c.row_factory = sqlite3.Row

    job_row = c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    print("\n" + "="*70)
    print("1. FRESH REAL JOB DETAILS")
    print("="*70)
    print(f"Job ID: {job_row['id']}")
    print(f"Target URL: {job_row['target_url']}")
    print(f"Status: {job_row['status']}")
    print(f"Pages Crawled: {job_row['pages_crawled']}")
    print(f"Completeness Status: {job_row['completeness_status']}")
    print(f"Incomplete Reasons: {job_row['incomplete_reasons_json']}")
    print(f"Cost USD: ${job_row['cost_usd']:.6f}")
    print(f"Is Demo: {bool(job_row['is_demo'])}")

    failed_fetches = json.loads(job_row['failed_fetches_json']) if job_row['failed_fetches_json'] else []
    print(f"Failed Fetches Count: {len(failed_fetches)}")

    # 2. Text Extraction Proof from crawl_pages (Item 2)
    print("\n" + "="*70)
    print("2. TEXT EXTRACTION PROOF FROM crawl_pages (ADJACENT ELEMENTS)")
    print("="*70)
    target_paths = ["/services", "/portfolio", "/calculator", "/track", "/"]
    for p_path in target_paths:
        row = c.execute(
            "SELECT url, title, h1, status_code FROM crawl_pages WHERE job_id = ? AND (url = ? OR url LIKE ?)",
            (job_id, f"https://webspire-agency.vercel.app{p_path}", f"%{p_path}")
        ).fetchone()
        if row:
            print(f"URL: {row['url']}")
            print(f"  Status Code: {row['status_code']}")
            print(f"  Extracted H1: {repr(row['h1'])}")
            print(f"  Extracted Title: {repr(row['title'])}\n")
        else:
            print(f"URL: {p_path} -> NOT FOUND IN CRAWL\n")

    # 3. Provenance Check
    print("="*70)
    print("3. PROVENANCE VERIFICATION")
    print("="*70)
    code_out = DBManager.get_code_output(job_id)
    bundle = code_out["code"]["bundle"]
    artifacts = [GeneratedArtifact(**a) for a in bundle.get("artifacts", [])]

    # Get verified issues for this job
    runs = DBManager.get_agent_runs(job_id)
    verifier_run = next((r for r in runs if r["agent_name"] == "verifier"), None)
    verified_issue_ids = set()
    if verifier_run and verifier_run.get("output_json"):
        v_out = json.loads(verifier_run["output_json"])
        for iss in v_out.get("verified_issues", []):
            verified_issue_ids.add(iss.get("id"))

    provenance_clean = True
    for a in artifacts:
        for sid in a.source_issue_ids:
            if sid not in verified_issue_ids:
                print(f"PROVENANCE ERROR: Artifact {a.file_path} claims issue {sid} not in verified issues!")
                provenance_clean = False
    if provenance_clean:
        print(f"PROVENANCE PERFECT: All artifact issue IDs exist in verified issues {verified_issue_ids}!")

    # 4. Review Gating Proof (Item 9)
    print("\n" + "="*70)
    print("4. REVIEW GATING PROOF (3 APPROVED, REST PENDING)")
    print("="*70)
    review_items = DBManager.get_review_items(job_id, item_type="code_artifact")
    print(f"Total Code Review Items: {len(review_items)}")
    # Approve exactly 3 items
    for item in review_items[:3]:
        DBManager.update_review_item_status(item["id"], "approved", reviewer_note="Batch A.2 test approval")
    # Leave remaining as pending
    approved_items = DBManager.get_review_items(job_id, item_type="code_artifact", status="approved")
    pending_items = DBManager.get_review_items(job_id, item_type="code_artifact", status="pending")
    print(f"Approved items count: {len(approved_items)}")
    for a in approved_items:
        print(f"  • APPROVED: {a['item_ref']}")
    print(f"Pending items count: {len(pending_items)}")

    # Generate Gated ZIP (include_unreviewed=False)
    zip_gated_bytes = CodePackager.generate_zip(
        job_id=job_id,
        domain="webspire-agency.vercel.app",
        platform="nextjs",
        artifacts=artifacts,
        validation_results=code_out["code"]["verifier"]["results"],
        is_demo=False,
        include_unreviewed=False
    )
    with zipfile.ZipFile(io.BytesIO(zip_gated_bytes)) as zf:
        gated_files = zf.namelist()
        gated_code_files = [f for f in gated_files if f.startswith("files/nextjs/")]
        print(f"\nGated ZIP (include_unreviewed=False) contains {len(gated_code_files)} code file(s):")
        for f in gated_code_files:
            print(f"  [GATED] {f}")

    # Generate Ungated ZIP (include_unreviewed=True)
    zip_ungated_bytes = CodePackager.generate_zip(
        job_id=job_id,
        domain="webspire-agency.vercel.app",
        platform="nextjs",
        artifacts=artifacts,
        validation_results=code_out["code"]["verifier"]["results"],
        is_demo=False,
        include_unreviewed=True
    )
    with zipfile.ZipFile(io.BytesIO(zip_ungated_bytes)) as zf:
        ungated_files = zf.namelist()
        ungated_code_files = [f for f in ungated_files if f.startswith("files/nextjs/")]
        print(f"\nUngated ZIP (include_unreviewed=True) contains {len(ungated_code_files)} code file(s):")
        for f in ungated_code_files:
            print(f"  [UNGATED] {f}")
        changes_csv = zf.read("CHANGES.csv").decode("utf-8")
        readme_md = zf.read("README_APPLY.md").decode("utf-8")
        unreviewed_count = changes_csv.count("[UNREVIEWED]")
        print(f"\nCHANGES.csv contains [UNREVIEWED] markers: {unreviewed_count} occurrences.")

    # 5. Extract and print specific files from the ZIP
    with zipfile.ZipFile(io.BytesIO(zip_ungated_bytes)) as zf:
        print("\n" + "="*70)
        print("5. FILES CONTENT FROM ZIP")
        print("="*70)

        for filename in [
            "files/nextjs/app/layout.metadata.snippet.tsx",
            "files/nextjs/app/services/page.metadata.snippet.tsx",
            "files/nextjs/app/portfolio/page.metadata.snippet.tsx",
            "files/nextjs/app/blog/[slug]/page.metadata.snippet.tsx",
            "files/nextjs/next.config.js",
            "files/nextjs/public/llms.txt",
            "CHANGES.csv",
            "README_APPLY.md"
        ]:
            if filename in zf.namelist():
                print(f"\n>>> FULL CONTENT OF: {filename}")
                print("-" * 50)
                content = zf.read(filename).decode("utf-8")
                print(content)
                print("-" * 50)
            else:
                print(f"\n>>> FILE NOT IN ZIP: {filename}")

    # 6. Meta Pairwise Similarity Matrix (Item 3)
    print("\n" + "="*70)
    print("6. METADATA SIMILARITY MATRIX (< 0.60 REQUIREMENT)")
    print("="*70)
    metas = []
    for a in artifacts:
        if a.file_path.endswith(".metadata.snippet.tsx"):
            desc_match = re.search(r"description:\s*'([^']+)'", a.content)
            if desc_match:
                metas.append((a.file_path, desc_match.group(1)))

    for i in range(len(metas)):
        for j in range(i + 1, len(metas)):
            f1, m1 = metas[i]
            f2, m2 = metas[j]
            ratio = difflib.SequenceMatcher(None, m1, m2).ratio()
            status = "PASS (< 0.60)" if ratio < 0.60 else "FAIL (>= 0.60)"
            print(f"Similarity: {ratio:.3f} | {status}")
            print(f"  • {f1}: \"{m1[:60]}...\"")
            print(f"  • {f2}: \"{m2[:60]}...\"\n")

    conn.close()

if __name__ == "__main__":
    asyncio.run(main())
