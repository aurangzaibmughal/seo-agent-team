from fastapi import APIRouter, HTTPException, Query, Body
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from app.core.db import DBManager

router = APIRouter(prefix="/api/jobs/{job_id}/reviews", tags=["reviews"])

class ReviewActionRequest(BaseModel):
    reviewer_note: Optional[str] = ""

class ReviewDismissRequest(BaseModel):
    reason: str

class ReviewEditRequest(BaseModel):
    edited_payload: Dict[str, Any]
    reviewer_note: Optional[str] = "human-edited"

class BulkApproveRequest(BaseModel):
    low_risk_only: bool = False
    item_types: Optional[List[str]] = None

@router.get("", response_model=Dict[str, Any])
async def list_review_items(
    job_id: str,
    item_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None)
):
    job = DBManager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # If items not yet populated, auto-populate now
    items = DBManager.get_review_items(job_id, item_type=item_type, status=status)
    if not items and not item_type and not status:
        DBManager.populate_review_items_for_job(job_id)
        items = DBManager.get_review_items(job_id)

    counts = DBManager.get_review_counts(job_id)
    return {
        "job_id": job_id,
        "counts": counts,
        "items": items
    }

@router.get("/counts", response_model=Dict[str, Any])
async def get_review_counts(job_id: str):
    job = DBManager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return DBManager.get_review_counts(job_id)

@router.get("/events", response_model=List[Dict[str, Any]])
async def get_review_events(job_id: str, item_id: Optional[str] = Query(None)):
    job = DBManager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return DBManager.get_review_events(job_id, item_id=item_id)

@router.post("/{item_id}/approve", response_model=Dict[str, Any])
async def approve_review_item(job_id: str, item_id: str, req: ReviewActionRequest = Body(default=ReviewActionRequest())):
    job = DBManager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    updated = DBManager.update_review_item_status(item_id, "approved", note=req.reviewer_note or "approved by owner")
    if not updated:
        raise HTTPException(status_code=404, detail="Review item not found")
    return {"status": "success", "item": updated}

@router.post("/{item_id}/reject", response_model=Dict[str, Any])
async def reject_review_item(job_id: str, item_id: str, req: ReviewActionRequest = Body(...)):
    job = DBManager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    updated = DBManager.update_review_item_status(item_id, "rejected", note=req.reviewer_note or "rejected by owner")
    if not updated:
        raise HTTPException(status_code=404, detail="Review item not found")
    return {"status": "success", "item": updated}

@router.post("/{item_id}/dismiss", response_model=Dict[str, Any])
async def dismiss_false_positive(job_id: str, item_id: str, req: ReviewDismissRequest = Body(...)):
    job = DBManager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    note = f"False positive dismissed: {req.reason}"
    updated = DBManager.update_review_item_status(item_id, "rejected", note=note)
    if not updated:
        raise HTTPException(status_code=404, detail="Review item not found")
    return {"status": "success", "item": updated}

@router.post("/{item_id}/edit", response_model=Dict[str, Any])
async def edit_review_item(job_id: str, item_id: str, req: ReviewEditRequest = Body(...)):
    job = DBManager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        updated = DBManager.edit_review_item(job_id, item_id, req.edited_payload, reviewer_note=req.reviewer_note or "human-edited")
        return {"status": "success", "item": updated}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

@router.post("/bulk-approve", response_model=Dict[str, Any])
async def bulk_approve_items(job_id: str, req: BulkApproveRequest = Body(default=BulkApproveRequest())):
    job = DBManager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    approved_count = DBManager.bulk_approve_review_items(job_id, low_risk_only=req.low_risk_only, item_types=req.item_types)
    return {"status": "success", "approved_count": approved_count, "counts": DBManager.get_review_counts(job_id)}
