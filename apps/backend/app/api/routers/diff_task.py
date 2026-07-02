from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from uuid import UUID
from app.services import DiffTaskService
from app.models.diff_task import DiffTask
from sqlalchemy import select
from ..svc_deps import get_async_diff_task_svc
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
    svc: DiffTaskService = Depends(get_async_diff_task_svc),
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


