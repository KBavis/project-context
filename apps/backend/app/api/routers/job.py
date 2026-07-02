from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from typing import List, Optional
from uuid import UUID
import logging

from app.pydantic.job import JobResponse, LatestJobsByDataSourceResponse
from app.pydantic.status import ProcessingStatus
from app.services.job import JobService
from app.api.svc_deps import get_job_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.post("/projects/{project_id}", status_code=status.HTTP_202_ACCEPTED, summary="Fan-out one Job per applicable source")
async def run_project_jobs(
    project_id: UUID,
    background_tasks: BackgroundTasks,
    svc: JobService = Depends(get_job_svc),
):
    """
    Orchestrate Jobs for an entire project. This fans out and creates one Job per applicable source.
    Returns 202 immediately — the orchestrator runs as a background task.
    """
    try:
        logger.info(f"Project-wide Job triggered for Project={project_id}")
        background_tasks.add_task(
            svc.run_project_jobs,
            project_id
        )

        return {
            "message": "Project Jobs kicked off successfully",
            "project_id": str(project_id),
        }
    except Exception as e:
        logger.error(f"Error triggering Jobs for Project={project_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/projects/{project_id}/data-sources/{data_source_id}", status_code=status.HTTP_202_ACCEPTED, summary="Run a Job for one source")
async def run_data_source_job(
    project_id: UUID,
    data_source_id: UUID,
    background_tasks: BackgroundTasks,
    svc: JobService = Depends(get_job_svc),
):
    """
    Orchestrate a Job for a specific data source.
    Returns 202 immediately — the orchestrator runs as a background task.
    """
    try:
        logger.info(f"Job triggered for Project={project_id}, DataSource={data_source_id}")
        background_tasks.add_task(
            svc.run_data_source_job,
            project_id,
            data_source_id
        )

        return {
            "message": "Data Source Job kicked off successfully",
            "project_id": str(project_id),
            "data_source_id": str(data_source_id),
        }
    except Exception as e:
        logger.error(f"Error triggering Job for Project={project_id}, DataSource={data_source_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/{job_id}", response_model=JobResponse, summary="Get Job status")
async def get_job(
    job_id: UUID,
    svc: JobService = Depends(get_job_svc),
):
    """Get the status and details of a specific Job."""
    try:
        job = await svc.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving Job={job_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get(
    "/projects/{project_id}/latest",
    response_model=List[JobResponse],
    summary="Get latest jobs for a project (last 3 per data source)",
)
async def get_latest_project_jobs(
    project_id: UUID,
    svc: JobService = Depends(get_job_svc),
):
    """
    Return the latest 3 jobs for each data source configured for the project,
    as a flat list sorted by start_time descending.
    """
    try:
        return await svc.get_latest_project_jobs_flat(project_id)
    except Exception as e:
        logger.error(f"Error retrieving latest jobs for Project={project_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get(
    "/data-sources/{data_source_id}/latest",
    response_model=List[JobResponse],
    summary="Get latest jobs for a specific data source",
)
async def get_latest_data_source_jobs(
    data_source_id: UUID,
    svc: JobService = Depends(get_job_svc),
):
    """Return the most recent 3 jobs for a specific data source."""
    try:
        return await svc.get_latest_data_source_jobs(data_source_id)
    except Exception as e:
        logger.error(f"Error retrieving latest jobs for DataSource={data_source_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
