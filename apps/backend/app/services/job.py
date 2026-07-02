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
        
        async with get_async_db_session_context() as session:
            ds = await self.data_source_svc.aget_data_source_by_id_with_session(data_source_id, session)
            if not ds:
                return
            is_repo = ds.type == DataSourceType.REPOSITORY and ds.scope_by_issues

        # 1. Create Job 
        job_id = await self.create_job(project_id, data_source_id)
            
        # 2. Run DiffTask (if applicable)
        if is_repo:
            await self._run_diff_task(project_id, data_source_id, job_id)

        # 3. Run EmbedTask
        await self._run_embed_task(project_id, data_source_id, job_id, job_start_time)
        
        # 4. Update Job Status
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

    async def _run_diff_task(self, project_id: UUID, data_source_id: UUID, job_id: UUID):
        async def init_task():
            sess = get_current_session()
            dt = await self.diff_svc.init_diff_task(project_id, data_source_id, job_id=job_id, async_session=sess)
            return dt.id

        async def execute_diff(task_id: UUID):
            await self.diff_svc.execute_repository_sync_job(task_id)
        
        async def mark_diff(sess, t_id, status, reason, end_time, duration):
            if not t_id: return
            await self.diff_svc.update_diff_task(diff_task_id=t_id, status=status, end_time=end_time, duration=duration, session=sess, reason=reason)
            
        async def mark_diff_fresh(t_id, status, reason, end_time, duration):
            if not t_id: return
            async with get_async_db_session_context() as fresh_sess:
                await self.diff_svc.update_diff_task(diff_task_id=t_id, status=status, end_time=end_time, duration=duration, session=fresh_sess, reason=reason, commit=True)

        lock_key = uuid.uuid5(uuid.NAMESPACE_OID, f"sync:{project_id}:{data_source_id}")
        await run_task(
            resource_id=lock_key,
            resource_type=RecordType.PROJECT_DATA,
            init_task=init_task,
            execute=execute_diff,
            mark_task=mark_diff,
            mark_task_fresh=mark_diff_fresh
        )

    async def _run_embed_task(self, project_id: UUID, data_source_id: UUID, job_id: UUID, job_start_time: datetime):
        async def init_task():
            sess = get_current_session()
            _, dt_id = await self.embed_task_svc.init_embed_task(data_source_id, job_start_time, job_id=job_id, async_session=sess)
            return dt_id

        async def execute_embed(task_id: UUID):
            sess = get_current_session()
            fresh_ds = await self.data_source_svc.aget_data_source_by_id_with_session(data_source_id, sess)
            if not fresh_ds:
                raise Exception(f"DataSource {data_source_id} not found!")
            await self.embed_task_svc.run_embed_task(task_id, job_start_time, fresh_ds, project_id)

        async def mark_embed(sess, t_id, status, reason, end_time, duration):
            if not t_id: return
            await self.embed_task_svc.update_embed_task(embed_task_id=t_id, status=status, end_time=end_time, duration=duration, session=sess, reason=reason)
            
        async def mark_embed_fresh(t_id, status, reason, end_time, duration):
            if not t_id: return
            async with get_async_db_session_context() as fresh_sess:
                await self.embed_task_svc.update_embed_task(embed_task_id=t_id, status=status, end_time=end_time, duration=duration, session=fresh_sess, reason=reason, commit=True)

        await run_task(
            resource_id=data_source_id,
            resource_type=RecordType.DATA_SOURCE,
            init_task=init_task,
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
