from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from typing import Dict, Any
import os
from app.services.comparator import JobComparator

router = APIRouter(prefix="/api/compare", tags=["comparator"])

EXPORTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "exports"))

@router.get("", response_model=Dict[str, Any])
async def compare_jobs(
    before_job_id: str = Query(..., description="Baseline job ID"),
    after_job_id: str = Query(..., description="Follow-up job ID")
):
    try:
        return JobComparator.compare(before_job_id, after_job_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Comparison failed: {e}")

@router.get("/export/csv")
async def export_comparison_csv(
    before_job_id: str = Query(...),
    after_job_id: str = Query(...)
):
    try:
        data = JobComparator.compare(before_job_id, after_job_id)
        out_file = os.path.join(EXPORTS_DIR, f"comparison_{before_job_id[:8]}_{after_job_id[:8]}.csv")
        JobComparator.export_csv(data, out_file)
        return FileResponse(out_file, media_type="text/csv", filename=f"comparison_{before_job_id[:8]}_{after_job_id[:8]}.csv")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/export/pdf")
async def export_comparison_pdf(
    before_job_id: str = Query(...),
    after_job_id: str = Query(...)
):
    try:
        data = JobComparator.compare(before_job_id, after_job_id)
        out_file = os.path.join(EXPORTS_DIR, f"comparison_{before_job_id[:8]}_{after_job_id[:8]}.pdf")
        JobComparator.export_pdf(data, out_file)
        return FileResponse(out_file, media_type="application/pdf", filename=f"comparison_{before_job_id[:8]}_{after_job_id[:8]}.pdf")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
