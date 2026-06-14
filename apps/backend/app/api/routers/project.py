from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks

from app.services import ProjectService
from app.pydantic import ProjectRequest
from app.models.data_source import DataSourceType
from ..svc_deps import get_project_svc, get_async_diff_svc, get_data_source_svc
from app.services.diff import DiffService
from app.services.data_source import DataSourceService

from typing import List
from uuid import UUID
import logging

router = APIRouter(prefix="/projects")

logger = logging.getLogger(__name__)

@router.post("/", summary="Create new project")
def create_project(
    project: ProjectRequest, 
    svc: ProjectService = Depends(get_project_svc)
):
    """
    Create a new Project for RAG Pipeline to account for
    """

    try:
        return svc.create_project(project)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )


@router.get("/", summary="Retrieve all projects")
def get_projects(
    svc: ProjectService = Depends(get_project_svc)
) -> List[dict]:
    """
    Fetch all persisted Projects

    TODO: Only fetch Projects authenticated user is able to see
    """

    try:
        return svc.get_all_projects()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )


@router.post("/{project_id}/data-sources/{data_source_id}", summary="Link data source to project")
async def link_data_source(
    project_id: UUID,
    data_source_id: UUID,
    background_tasks: BackgroundTasks,
    svc: ProjectService = Depends(get_project_svc),
    diff_svc: DiffService = Depends(get_async_diff_svc),
    ds_svc: DataSourceService = Depends(get_data_source_svc)
):
    """
    Associate an existing Data Source with a Project
    """

    try:
        res = svc.link_data_source_to_project(project_id, data_source_id)
        logger.info(f"DataSource={data_source_id} successfully linked to Project {project_id}")

        # kick of DiffSyncJob for RepositoryDataSource if its scoped_by_issues when first linking Data Source & Project 
        # this runs in the background and the consumer of this endpoint will not need to wait for this to finish processing
        ds = await ds_svc.aget_data_source_by_id(data_source_id)
        if ds.type == DataSourceType.REPOSITORY and ds.scope_by_issues:
            logger.info(f"DataSource={data_source_id} is type={ds.type} and scoped_by_issues={ds.scope_by_issues}: attempting to run DiffSyncJob for Project={project_id} and Data Source={data_source_id}")
            job = await diff_svc.init_diff_sync_job(project_id, data_source_id)
            background_tasks.add_task(diff_svc.execute_repository_sync_job, job.id)
            
        return res
    except ValueError as e:
        logger.error(f"ValueError while attempting to link Project={project_id} to DataSource={data_source_id}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Fatal Exception while attempting to link Project={project_id} to DataSource={data_source_id}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )
