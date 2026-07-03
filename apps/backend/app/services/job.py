from __future__ import annotations
import logging
import uuid
from uuid import UUID
from datetime import datetime, timezone
from typing import TYPE_CHECKING 

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.job import Job
from app.models.data_source import DataSourceType
from app.models.record_lock import RecordType
from app.pydantic.status import ProcessingStatus
from app.core import get_async_db_session_context
from app.core.background import run_task, get_current_session
from app.tasks import DiffTaskRunner, EmbedTaskRunner
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

    async def create_job(self, project_id: UUID, data_source_id: UUID) -> UUID:
        """Create a new Job record with IN_PROGRESS status and return its ID."""
        async with get_async_db_session_context() as session:
            job = Job(
                project_id=project_id,
                data_source_id=data_source_id,
                status=ProcessingStatus.IN_PROGRESS,
                start_time=datetime.now(timezone.utc),
            )
            session.add(job)
            await session.commit()
            return job.id

    async def get_job(self, job_id: UUID) -> Job | None:
        """Retrieve a single Job by its primary key with tasks eager-loaded."""
        stmt = (
            select(Job)
            .options(selectinload(Job.diff_tasks), selectinload(Job.embed_tasks))
            .where(Job.id == job_id)
        )
        res = await self.async_db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_all_jobs(self, limit: int = 50) -> list[Job]:
        """
        Retrieve a list of all jobs globally for system-level views,
        with tasks eager-loaded.
        """
        stmt = (
            select(Job)
            .options(selectinload(Job.diff_tasks), selectinload(Job.embed_tasks))
            .order_by(Job.start_time.desc())
            .limit(limit)
        )
        res = await self.async_db.execute(stmt)
        return list(res.scalars().all())

    async def run_project_jobs(self, project_id: UUID):
        """
        Fan-out: run_data_source_job for every applicable source.

        Concurrency is bounded so a large Project can't open more session that the ConnectionPool 
        can serve (each DataSource job opens new AsyncSession per Task while it runs)
        """
        async with get_async_db_session_context() as session:
            data_sources = await self.data_source_svc.aget_project_data_sources(
                project_id, async_session=session
            )
            applicable = [ds for ds in data_sources if ds.type != DataSourceType.ISSUE_TRACKER]
        

        # configure Semaphore to bound maximum concurrent run_data_source_job() calls happening 
        semaphore = asyncio.Semaphore(5)
        async def _run(data_source_id: UUID): 
            async with semaphore:
                await self.run_data_source_job(project_id, data_source_id)

        # run DataSource jobs concurrently (bounded by semaphore)
        # NOTE (for future me): `asyncio.gather` wraps each coroutine in an `asyncio.Task`
        # and runs them concurrently on one thread (cooperative multitasking) — unlike
        # `asyncio.to_thread`, which offloads a blocking call to a separate OS thread.
        # Use to_thread for blocking/sync calls, gather+Tasks for native async coroutines.
        await asyncio.gather(*[
            _run(ds.id)
            for ds in applicable
        ])

    async def run_data_source_job(self, project_id: UUID, data_source_id: UUID):
        """
        Creates Job, builds the applicable Tasks, and runs them. 
        Tasks will have their own DB Session Life Cycle + Locking via `Task.run()` 
        """
        job_start_time = datetime.now(timezone.utc)
        
        async with get_async_db_session_context() as session:
            ds = await self.data_source_svc.aget_data_source_by_id_with_session(data_source_id, session)
            if not ds:
                return
            is_scoped_repo = ds.type == DataSourceType.REPOSITORY and ds.scope_by_issues

        # 1. Create Job 
        job_id = await self.create_job(project_id, data_source_id)
            
        # 2. Run DiffTask (only for issue-scoped repositories)
        if is_scoped_repo:
            await DiffTaskRunner(
                self.diff_svc, 
                project_id, 
                data_source_id, 
                job_id).run() 

        # 3. Run EmbedTask
        await EmbedTaskRunner(
            self.embed_task_svc,
            self.data_source_svc,
            project_id,
            data_source_id,
            job_id,
            job_start_time
        ).run()
        
        # 4. Aggregate task statuses into the single Job status
        await self.update_job_status(job_id)
        
    async def update_job_status(self, job_id: UUID):
        async with get_async_db_session_context() as session:
            job = await session.get(Job, job_id)
            if not job:
                raise Exception(f"No job found with JobID={job_id}")

            diff = await self.diff_svc.get_diff_tasks_by_job_id(job_id, session)
            embed = await self.embed_task_svc.get_embed_tasks_by_job_id(job_id, session)
            
            statuses = [t.status for t in diff] + [t.processing_status for t in embed]

            if not statuses:
                job.status = ProcessingStatus.FAILED
            elif ProcessingStatus.FAILED in statuses:
                job.status = ProcessingStatus.FAILED
            elif ProcessingStatus.IN_PROGRESS in statuses:
                job.status = ProcessingStatus.IN_PROGRESS
            elif ProcessingStatus.SKIPPED in statuses and not any(s == ProcessingStatus.SUCCESS for s in statuses):
                job.status = ProcessingStatus.SKIPPED
            else:
                job.status = ProcessingStatus.SUCCESS

            job.end_time = datetime.now(timezone.utc)
            job.total_duration = int((job.end_time - job.start_time).total_seconds())
            await session.commit()

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
            
            # Fetch exactly the latest 3 jobs for this specific data source, scoped to THIS
            # project. A Job is grained (project, data_source), so scoping here keeps a shared
            # data source (e.g. an issue-scoped repo linked to multiple projects) from showing
            # another project's jobs in this project's view.
            latest_jobs = await self.get_latest_data_source_jobs(ds.id, limit=3, project_id=project_id)
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

    async def get_latest_data_source_jobs(
        self, data_source_id: UUID, limit: int = 3, project_id: UUID | None = None
    ) -> list[Job]:
        """
        Return the most recent `limit` jobs for a specific data source.

        Args:
            data_source_id: The data source to query jobs for.
            limit: Max number of jobs to return (default 3).
            project_id: If provided, restrict to jobs run in the context of this project
                (a Job is grained (project, data_source)). Omit for a global, cross-project
                view (e.g. embed-once / non-scoped sources).
        """
        stmt = (
            select(Job)
            .options(selectinload(Job.diff_tasks), selectinload(Job.embed_tasks))
            .where(Job.data_source_id == data_source_id)
        )
        if project_id is not None:
            stmt = stmt.where(Job.project_id == project_id)
        stmt = stmt.order_by(Job.start_time.desc()).limit(limit)
        res = await self.async_db.execute(stmt)
        return list(res.scalars().all())

    async def get_project_sync_state(self, project_id: UUID) -> tuple[str, list[str]]:
        """
        Calculates the project-wide sync state by aggregating
        the latest Job status for each ingestible data source.
        Returns:
            (aggregate_status, blocked_reasons)
            where aggregate_status is one of NOT_YET_SYNCED, IN_PROGRESS, FAILED, SUCCESS.
        """
        data_sources = await self.data_source_svc.aget_project_data_sources(project_id)
        applicable_ds = [ds for ds in data_sources if ds.type != DataSourceType.ISSUE_TRACKER]

        if not applicable_ds:
            return ProcessingStatus.SUCCESS.value, []

        blocked_reasons = []
        statuses = []
        
        for ds in applicable_ds:
            stmt = (
                select(Job)
                .where(Job.data_source_id == ds.id)
                .where(Job.project_id == project_id)
                .order_by(Job.start_time.desc())
                .limit(1)
            )
            res = await self.async_db.execute(stmt)
            latest_job = res.scalar_one_or_none()
            
            if not latest_job:
                statuses.append(ProcessingStatus.NOT_YET_SYNCED.value)
                blocked_reasons.append(f"Data source {ds.id} is not yet synced.")
            elif latest_job.status == ProcessingStatus.FAILED:
                statuses.append(ProcessingStatus.FAILED.value)
                blocked_reasons.append(f"Data source {ds.id} sync failed.")
            elif latest_job.status == ProcessingStatus.IN_PROGRESS:
                statuses.append(ProcessingStatus.IN_PROGRESS.value)
            elif latest_job.status == ProcessingStatus.SKIPPED:
                statuses.append(ProcessingStatus.SUCCESS.value)
            elif latest_job.status == ProcessingStatus.SUCCESS:
                statuses.append(ProcessingStatus.SUCCESS.value)
                    
        # Aggregate precedence: IN_PROGRESS -> FAILED -> NOT_YET_SYNCED -> SUCCESS
        if ProcessingStatus.IN_PROGRESS.value in statuses:
            return ProcessingStatus.IN_PROGRESS.value, blocked_reasons
        if ProcessingStatus.FAILED.value in statuses:
            return ProcessingStatus.FAILED.value, blocked_reasons
        if ProcessingStatus.NOT_YET_SYNCED.value in statuses:
            return ProcessingStatus.NOT_YET_SYNCED.value, blocked_reasons
        
        return ProcessingStatus.SUCCESS.value, []
