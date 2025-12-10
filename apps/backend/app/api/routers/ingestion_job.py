from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from datetime import datetime

from app.services import IngestionJobService
from app.models import ProcessingStatus
from ..svc_deps import (
    get_async_ingestion_job_svc
)

from uuid import UUID
import logging


router = APIRouter(prefix="/ingestion/jobs")

logger = logging.getLogger(__name__)

@router.post(
    "/{data_source_id}", summary="Kick off ingestion of data from a datasource"
)
async def create_ingestion_job(
    data_source_id: UUID, 
    background_tasks: BackgroundTasks,
    svc: IngestionJobService = Depends(get_async_ingestion_job_svc)
):

    """
    Kick off ingestion job for a specific data source
    """


    job_start_time = datetime.now()
    logging.info(f"create_ingestion_job() request recieved for dataSource={data_source_id} at {job_start_time}")

    # create inital ingestion job 
    try:
        data_source, job_pk = await svc.init_ingestion_job(data_source_id, job_start_time)
    except Exception as e: 
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )
    
    # TODO: Ensure DataSource isn't locked (if not, lock this data source to ensure no other IngestionJobs are ran while procesisng)

    # run ingestion job in background 
    background_tasks.add_task(svc.run_ingestion_job, job_pk, job_start_time, data_source)

    return {
        "ingestion_job_id": job_pk,
        "status": ProcessingStatus.IN_PROGRESS,
        "start_time": job_start_time
    }



@router.post(
    "/{data_source_id}/{project_id}",
    summary="Kick off ingestion of data from a datasource for a specific Project",
)
async def create_ingestion_job(
    data_source_id: UUID, 
    project_id: UUID, 
    svc: IngestionJobService = Depends(get_async_ingestion_job_svc)
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
