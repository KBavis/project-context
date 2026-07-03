from __future__ import annotations
import uuid
from uuid import UUID
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.tasks.base import Task
from app.models.record_lock import RecordType
from app.pydantic.status import ProcessingStatus

if TYPE_CHECKING:
    from app.services.diff_task import DiffTaskService


class DiffTaskRunner(Task):
    """
    Task that syncs a project's tracked repository changes (diff-sync). Locks on the
    `(project, data source)` pair (`PROJECT_DATA`) because diff work is project-specific.
    """

    def __init__(
        self,
        diff_svc: "DiffTaskService",
        project_id: UUID,
        data_source_id: UUID,
        job_id: UUID,
    ):
        self.diff_svc = diff_svc
        self.project_id = project_id
        self.data_source_id = data_source_id
        self.job_id = job_id
        # Deterministic composite key for the (project, data source) lock scope.
        self.resource_id = uuid.uuid5(uuid.NAMESPACE_OID, f"{project_id}:{data_source_id}")
        self.resource_type = RecordType.PROJECT_DATA

    async def init(self, session: AsyncSession) -> UUID:
        diff_task = await self.diff_svc.init_diff_task(
            self.project_id, self.data_source_id, job_id=self.job_id, async_session=session
        )
        return diff_task.id

    async def execute(self, session: AsyncSession, task_id: UUID) -> None:
        await self.diff_svc.execute_repository_sync_job(task_id)

    async def mark(
        self,
        session: AsyncSession,
        task_id: UUID,
        status: ProcessingStatus,
        reason: Optional[str],
        end_time: datetime,
        duration: int,
    ) -> None:
        await self.diff_svc.update_diff_task(
            diff_task_id=task_id,
            status=status,
            end_time=end_time,
            duration=duration,
            session=session,
            reason=reason,
        )
