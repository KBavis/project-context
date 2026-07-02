from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services import EmbedTaskService
from app.models import ProcessingStatus
from ..svc_deps import (
    get_async_embed_task_svc
)

from uuid import UUID
import logging


router = APIRouter(prefix="/ingestion/jobs")

logger = logging.getLogger(__name__)

@router.post(
    "/{data_source_id}", summary="Kick off ingestion of data from a datasource"
)
async def create_embed_task(
    data_source_id: UUID, 
    background_tasks: BackgroundTasks,
    svc: EmbedTaskService = Depends(get_async_embed_task_svc)
):

    """
    Kick off ingestion job for a specific data source
    """


    job_start_time = datetime.now(ZoneInfo("America/New_York"))
    logging.info(f"create_embed_task() request recieved for dataSource={data_source_id} at {job_start_time}")

    # create inital ingestion job 
    try:
        data_source, job_pk = await svc.init_embed_task(data_source_id, job_start_time)
    except Exception as e: 
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )
    
    # TODO: Ensure DataSource isn't locked (if not, lock this data source to ensure no other EmbedTasks are ran while procesisng)

    # run ingestion job in background 
    background_tasks.add_task(svc.run_embed_task, job_pk, job_start_time, data_source)

    return {
        "id": job_pk,
        "processing_status": ProcessingStatus.IN_PROGRESS,
        "data_source_id": data_source_id,
        "start_time": job_start_time
    }



@router.get("/", summary="Retrieve all ingestion jobs")
async def get_embed_tasks(
    svc: EmbedTaskService = Depends(get_async_embed_task_svc)
):
    """
    Retrieve ingestion jobs for authenticated user
    """
    try:
        return await svc.get_all_embed_tasks()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{str(e)}"
        )
