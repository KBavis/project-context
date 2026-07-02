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
