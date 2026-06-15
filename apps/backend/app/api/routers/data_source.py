from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks

from app.services import DataSourceService
from app.pydantic import DataSourceRequest
from app.models.data_source import DataSourceType
from app.services.diff import DiffService
from ..svc_deps import get_data_source_svc, get_async_diff_svc

from uuid import UUID
from app.pydantic import DataSourceRequest, DataSourceUpdateRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data/sources")


@router.get("/", summary="Retrieve all data sources")
def get_data_sources(
    svc: DataSourceService = Depends(get_data_source_svc)
):
    """
    Retrieve all data sources
    """
    try:
        return svc.get_all_data_sources()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )


@router.post("/", summary="Connect to external data source")
async def create_datasource(
    request: DataSourceRequest, 
    background_tasks: BackgroundTasks,
    svc: DataSourceService = Depends(get_data_source_svc),
    diff_svc: DiffService = Depends(get_async_diff_svc)
):
    """
    Connect application to an external datasource in order to ingest data from.
    If the new data source is a REPOSITORY with scope_by_issues=True and is linked
    to projects at creation time, a DiffSyncJob will be kicked off for each linked project.
    """

    try:
        result = svc.create_data_source(request)

        # Kick off DiffSyncJobs for linked projects if this is an issue-scoped repository
        if request.type == DataSourceType.REPOSITORY and request.scope_by_issues and request.project_ids:
            data_source_id = result["id"]
            for project_id in request.project_ids:
                logger.info(
                    f"[CreateDataSource] DataSource={data_source_id} is REPOSITORY with scope_by_issues=True: "
                    f"kicking off DiffSyncJob for Project={project_id}"
                )
                job = await diff_svc.init_diff_sync_job(project_id, data_source_id)
                background_tasks.add_task(diff_svc.execute_repository_sync_job, job.id)

        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )



@router.patch("/{data_source_id}", summary="Update data source")
def update_datasource(
    data_source_id: UUID,
    updates: DataSourceUpdateRequest,
    svc: DataSourceService = Depends(get_data_source_svc)
):
    """
    Patch/update a Data Source. Only permitted updates are `name`, `branch`, `scope_by_issues`, `url`, `provider`.
    Returns 400 on validation errors (e.g. enabling `scope_by_issues` when linked projects lack parent_issues).
    """
    try:
        # Only send fields that were provided
        return svc.update_data_source(data_source_id, updates.dict(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))



# TODO: Add logic to associate existing DataSource to new Project

@router.get("/{project_id}", summary="Get connected data sources")
def get_project_data_sources(
    project_id: UUID, 
    svc: DataSourceService = Depends(get_data_source_svc)
):
    """
    Retrieve data sources corresponding to a Project that the authenticated user is able to view
    """

    try:
        return svc.get_project_data_sources(project_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )


@router.post("/{data_source_id}/mcp/configs/{mcp_config_id}", summary="Associate MCP configuration with data source")
def link_mcp_config(
    data_source_id: UUID,
    mcp_config_id: UUID,
    svc: DataSourceService = Depends(get_data_source_svc)
):
    """
    Associate an existing MCP Configuration with a Data Source
    """
    try:
        return svc.link_mcp_config_to_data_source(data_source_id, mcp_config_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )
