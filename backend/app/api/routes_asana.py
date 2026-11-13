from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from app.core.db import DBManager
from app.services.asana_service import AsanaService

router = APIRouter(prefix="/api/asana", tags=["asana"])


class AsanaExportRequest(BaseModel):
    workspace_gid: str
    project_gid: str
    start_date: Optional[str] = None


class AsanaPreviewRequest(BaseModel):
    start_date: Optional[str] = None


@router.get("/status")
async def get_asana_status():
    """Returns whether the server has ASANA_ACCESS_TOKEN configured."""
    return {
        "configured": AsanaService.is_configured()
    }


@router.get("/workspaces")
async def list_asana_workspaces():
    """Lists workspaces accessible to the authenticated Asana token."""
    if not AsanaService.is_configured():
        raise HTTPException(status_code=400, detail="Asana access token not configured in environment")
    try:
        workspaces = await AsanaService.list_workspaces()
        return {"workspaces": workspaces}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects")
async def list_asana_projects(workspace: str = Query(..., description="Asana Workspace GID")):
    """Lists active projects in the specified workspace."""
    if not AsanaService.is_configured():
        raise HTTPException(status_code=400, detail="Asana access token not configured in environment")
    try:
        projects = await AsanaService.list_projects(workspace)
        return {"projects": projects}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jobs/{job_id}/preview")
async def preview_asana_export(job_id: str, payload: Optional[AsanaPreviewRequest] = None):
    """Previews task mapping and due dates for approved strategy tasks without modifying Asana."""
    job = DBManager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    start_date = payload.start_date if payload else None
    try:
        preview = await AsanaService.preview_export(job_id, start_date=start_date)
        return preview
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jobs/{job_id}/export")
async def export_job_to_asana(job_id: str, payload: AsanaExportRequest):
    """Pushes approved strategy tasks into the specified Asana project grouped by milestone weeks."""
    if not AsanaService.is_configured():
        raise HTTPException(status_code=400, detail="Asana access token not configured in environment")

    job = DBManager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        result = await AsanaService.export_to_asana(
            job_id=job_id,
            workspace_gid=payload.workspace_gid,
            project_gid=payload.project_gid,
            start_date=payload.start_date
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}/csv")
async def download_asana_csv(job_id: str, start_date: Optional[str] = Query(None)):
    """Downloads an asana_import.csv formatted for native Asana CSV importer."""
    job = DBManager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        csv_content = AsanaService.generate_asana_csv(job_id, start_date=start_date)
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="asana_import_{job_id[:8]}.csv"',
                "Access-Control-Expose-Headers": "Content-Disposition"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
