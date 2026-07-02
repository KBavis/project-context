from __future__ import annotations
import logging
from tkinter import E
from uuid import UUID
from datetime import datetime, timezone
from typing import TYPE_CHECKING 

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.models.embed_task import EmbedTask
from app.models.data_source import DataSourceType
from app.models.record_lock import RecordType
from app.pydantic.status import ProcessingStatus
from app.core import get_async_db_session_context
from app.services.background import run_task
import asyncio

if TYPE_CHECKING:
    from app.services.diff_task import DiffTaskService
    from app.services.data_source import DataSourceService
    from app.services.embed_task import EmbedTaskService

logger = logging.getLogger(__name__)


class JobService:
    """
    Service responsible for Job CRUD and query operations, as well
    as orchestrating data source synchronization.
    """

    def __init__(
        self,
        async_db: AsyncSession,
        diff_svc: "DiffTaskService",
        embed_task_svc: "EmbedTaskService",
        data_source_svc: "DataSourceService",
    ):
        self.async_db = async_db
        self.diff_svc = diff_svc
        self.embed_task_svc = embed_task_svc
        self.data_source_svc = data_source_svc

    async def create_job(self, project_id: UUID, data_source_id: UUID) -> Job:
        """Create a new Job record with IN_PROGRESS status."""
        job = Job(
            project_id=project_id,
            data_source_id=data_source_id,
            status=ProcessingStatus.IN_PROGRESS,
            start_time=datetime.now(timezone.utc),
        )
        self.async_db.add(job)
        await self.async_db.flush()
        return job

    async def get_job(self, job_id: UUID) -> Job | None:
        """Retrieve a single Job by its primary key."""
        stmt = select(Job).where(Job.id == job_id)
        res = await self.async_db.execute(stmt)
        return res.scalar_one_or_none()

    async def run_project_jobs(self, project_id: UUID):
        """
        Fan-out: run_data_source_job for every applicable source.
        """
        async with get_async_db_session_context() as session:
            data_sources = await self.data_source_svc.aget_project_data_sources(
                project_id, async_session=session
            )
            applicable = [ds for ds in data_sources if ds.type != DataSourceType.ISSUE_TRACKER]
            
        await asyncio.gather(*[
            self.run_data_source_job(project_id, ds.id)
            for ds in applicable
        ])

    async def run_data_source_job(self, project_id: UUID, data_source_id: UUID):
        """
        Creates Job, tasks, and orchestrates them via run_task.
        """
        job_start_time = datetime.now(timezone.utc)
        
        # 1. Create Job & Tasks using a fresh session
        async with get_async_db_session_context() as session:
            ds = await self.data_source_svc.aget_data_source_by_id_with_session(data_source_id, session)
            if not ds:
                return
            
            job = Job(
                project_id=project_id,
                data_source_id=data_source_id,
                status=ProcessingStatus.IN_PROGRESS,
                start_time=job_start_time,
            )
            session.add(job)
            await session.flush()
            
            diff_task_id = None
            if ds.type == DataSourceType.REPOSITORY and ds.scope_by_issues:
                dt = await self.diff_svc.init_diff_task(project_id, data_source_id, job_id=job.id, async_session=session)
                diff_task_id = dt.id
                
            _, embed_task_id = await self.embed_task_svc.init_embed_task(data_source_id, job_start_time, job_id=job.id, async_session=session)
            await session.commit()
            
            job_id = job.id

        # 2. Run DiffTask (if applicable)
        if diff_task_id:
            await self._run_diff_task(project_id, diff_task_id)

        # 3. Run EmbedTask
        await self._run_embed_task(project_id, data_source_id, embed_task_id, job_start_time)
        
        # 4. Update Job Status
        async with get_async_db_session_context() as session:
            et = await session.get(EmbedTask, embed_task_id)
            final_job = await session.get(Job, job_id)

            if not final_job:
                raise Exception(f"No job found with JobID={job_id}")
            if not et:
                raise Exception(f"No embed task found with EmbedTaskID={embed_task_id}")

            # The job status matches the embed task status, as embed is the final step
            final_job.status = et.processing_status
            final_job.end_time = datetime.now(timezone.utc)
            await session.commit()

    async def _run_diff_task(self, project_id: UUID, diff_task_id: UUID):
        async def execute_diff():
            await self.diff_svc.execute_repository_sync_job(diff_task_id)
        
        async def mark_diff(sess, t_id, status, reason):
            await self.diff_svc.update_diff_task(job_id=t_id, status=status, end_time=datetime.now(timezone.utc), duration=0, session=sess, reason=reason)
            
        async def mark_diff_fresh(t_id, status, reason):
            async with get_async_db_session_context() as fresh_sess:
                await self.diff_svc.update_diff_task(job_id=t_id, status=status, end_time=datetime.now(timezone.utc), duration=0, session=fresh_sess, reason=reason, commit=True)

        await run_task(
            task_id=diff_task_id,
            resource_id=project_id,
            resource_type=RecordType.PROJECT_DATA,
            execute=execute_diff,
            mark_task=mark_diff,
            mark_task_fresh=mark_diff_fresh
        )

    async def _run_embed_task(self, project_id: UUID, data_source_id: UUID, embed_task_id: UUID, job_start_time: datetime):
        async def execute_embed():
            from app.services.background import get_current_session
            sess = get_current_session()
            fresh_ds = await self.data_source_svc.aget_data_source_by_id_with_session(data_source_id, sess)
            await self.embed_task_svc.run_embed_task(embed_task_id, job_start_time, fresh_ds, project_id)

        async def mark_embed(sess, t_id, status, reason):
            await self.embed_task_svc.update_embed_task(job_pk=t_id, status=status, end_time=datetime.now(timezone.utc), duration=0, session=sess, reason=reason)
            
        async def mark_embed_fresh(t_id, status, reason):
            async with get_async_db_session_context() as fresh_sess:
                await self.embed_task_svc.update_embed_task(job_pk=t_id, status=status, end_time=datetime.now(timezone.utc), duration=0, session=fresh_sess, reason=reason, commit=True)

        await run_task(
            task_id=embed_task_id,
            resource_id=data_source_id,
            resource_type=RecordType.DATA_SOURCE,
            execute=execute_embed,
            mark_task=mark_embed,
            mark_task_fresh=mark_embed_fresh
        )

    async def get_latest_project_jobs(self, project_id: UUID) -> dict[UUID, list[Job]]:
        """
        Return the last 3 jobs for each data source configured for the project.

        Returns a dict keyed by data_source_id (or the project_id for project-wide jobs)
        mapping to the most recent 3 Job records for that scope.
        """
        # Get all data sources linked to the project
        linked_data_sources = await self.data_source_svc.aget_project_data_sources(project_id)
        
        # Iterate over each applicable data source and get its latest jobs
        grouped: dict[UUID, list[Job]] = {}
        for ds in linked_data_sources:
            # Skip non-ingestible data sources like ISSUE_TRACKER
            if ds.type == DataSourceType.ISSUE_TRACKER:
                continue
            
            # Fetch exactly the latest 3 jobs for this specific data source
            latest_jobs = await self.get_latest_data_source_jobs(ds.id, limit=3)
            grouped[ds.id] = latest_jobs

        return grouped

    async def get_latest_project_jobs_flat(self, project_id: UUID) -> list[Job]:
        """
        Return a flat list of the latest 3 jobs per data source for the project.
        Convenience wrapper over get_latest_project_jobs for API serialization.
        """
        grouped = await self.get_latest_project_jobs(project_id)
        result = []
        for jobs in grouped.values():
            result.extend(jobs)
        # Sort by start_time descending for consistent ordering
        result.sort(key=lambda j: j.start_time, reverse=True)
        return result

    async def get_latest_data_source_jobs(self, data_source_id: UUID, limit: int = 3) -> list[Job]:
        """
        Return the most recent `limit` jobs for a specific data source.

        Args:
            data_source_id: The data source to query jobs for.
            limit: Max number of jobs to return (default 3).
        """
        stmt = (
            select(Job)
            .where(Job.data_source_id == data_source_id)
            .order_by(Job.start_time.desc())
            .limit(limit)
        )
        res = await self.async_db.execute(stmt)
        return list(res.scalars().all())
