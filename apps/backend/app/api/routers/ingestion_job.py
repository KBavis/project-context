from fastapi import APIRouter, Depends, HTTPException, status

from app.services import IngestionJobService, FileService
from ..svc_deps import get_ingestion_job_svc

from uuid import UUID


router = APIRouter(prefix="/ingestion/jobs")


@router.post(
    "/{data_source_id}", summary="Kick off ingestion of data from a datasource"
)
def create_ingestion_job(
    data_source_id: UUID, 
    svc: IngestionJobService = Depends(get_ingestion_job_svc)
):

    """
    Kick off ingestion job for a specific data source
    """

    try:
        return svc.run_ingestion_job(data_source_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )


@router.post(
    "/{data_source_id}/{project_id}",
    summary="Kick off ingestion of data from a datasource for a specific Project",
)
def create_ingestion_job(
    data_source_id: UUID, 
    project_id: UUID, 
    svc: IngestionJobService = Depends(get_ingestion_job_svc)
):
    """
    Kick off ingestion job for a datasource for only data corresponding to specified Project
    """

    try:
        return svc.run_ingestion_job(data_source_id, project_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )


@router.get("/", summary="Retrieve all ingestion jobs")
def get_ingestion_jobs():
    """
    Retrieve ingestion jobs for authenticated user
    """
