from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from uuid import UUID
from app.services import DiffService
from app.models.diff_sync_job import DiffSyncJob
from sqlalchemy import select
from ..svc_deps import get_async_diff_svc
from app.pydantic.status import ProcessingStatus
import logging

router = APIRouter(prefix="/diff")
logger = logging.getLogger(__name__)

@router.get(
    "/{project_id}/repository-code-changes",
    summary="Retrieve total repository code changes for a project",
)
async def get_repository_code_changes(
    project_id: UUID,
    data_source_id: UUID | None = Query(
        None,
        description="Optional data source ID to filter repository code changes",
    ),
    svc: DiffService = Depends(get_async_diff_svc),
):
    """
    Retrieve repository code change totals for the requested project.
    """
    try:
        return svc.get_total_repository_code_changes(
            project_id=project_id,
            data_source_id=data_source_id,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{str(e)}",
        )

@router.post("/sync/{project_id}/{data_source_id}", status_code=status.HTTP_202_ACCEPTED)
async def trigger_diff_sync(
    project_id: UUID,
    data_source_id: UUID,
    background_tasks: BackgroundTasks,
    svc: DiffService = Depends(get_async_diff_svc)
):
    try:
        job = await svc.init_diff_sync_job(project_id, data_source_id)
        background_tasks.add_task(svc.execute_repository_sync_job, job.id)
        return {"job_id": job.id, "status": job.status.value}
    except Exception as e:
        logger.error(f"Error triggering diff sync: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sync/status/{project_id}")
async def validate_project_initial_syncing(
    project_id: UUID,
    svc: DiffService = Depends(get_async_diff_svc)
):
    try:
        state = await svc.get_project_sync_state(project_id)
        return {
            "is_initial_sync_complete": state == ProcessingStatus.SUCCESS.value,
            "status": state
        }
    except Exception as e:
        logger.error(f"Error checking project sync status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
