from __future__ import annotations
from uuid import UUID
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.tasks.base import Task
from app.models.record_lock import RecordType
from app.pydantic.status import ProcessingStatus

if TYPE_CHECKING:
    from app.services.embed_task import EmbedTaskService
    from app.services.data_source import DataSourceService


class EmbedTaskRunner(Task):
    """
    Task that embeds (indexes) a data source. Locks on the data source itself
    (`DATA_SOURCE`) because embedding is embed-once / global per data source.
    """

    def __init__(
        self,
        embed_svc: "EmbedTaskService",
        data_source_svc: "DataSourceService",
        project_id: UUID,
        data_source_id: UUID,
        job_id: UUID,
        job_start_time: datetime,
    ):
        self.embed_svc = embed_svc
        self.data_source_svc = data_source_svc
        self.project_id = project_id
        self.data_source_id = data_source_id
        self.job_id = job_id
        self.job_start_time = job_start_time
        self.resource_id = data_source_id
        self.resource_type = RecordType.DATA_SOURCE

    async def init(self, session: AsyncSession) -> UUID:
        _, task_id = await self.embed_svc.init_embed_task(
            self.data_source_id, self.job_start_time, job_id=self.job_id, async_session=session
        )
        return task_id

    async def execute(self, session: AsyncSession, task_id: UUID) -> None:
        fresh_ds = await self.data_source_svc.aget_data_source_by_id_with_session(
            self.data_source_id, session
        )
        if not fresh_ds:
            raise Exception(f"DataSource {self.data_source_id} not found!")
        await self.embed_svc.run_embed_task(task_id, self.job_start_time, fresh_ds, self.project_id)

    async def mark(
        self,
        session: AsyncSession,
        task_id: UUID,
        status: ProcessingStatus,
        reason: Optional[str],
        end_time: datetime,
        duration: int,
    ) -> None:
        await self.embed_svc.update_embed_task(
            embed_task_id=task_id,
            status=status,
            end_time=end_time,
            duration=duration,
            session=session,
            reason=reason,
        )
