from __future__ import annotations
import logging
from abc import ABC, abstractmethod
from uuid import UUID
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ambient_session
from app.models.record_lock import RecordType
from app.pydantic.status import ProcessingStatus
from app.services.record_lock import RecordLockService
from app.exceptions import TaskSkipped

logger = logging.getLogger(__name__)

class Task(ABC):
    """
    A single unit of background work that runs itself via ``run()``.

    A Task owns its resource-lock scope (``resource_id`` / ``resource_type``) and
    implements its own lifecycle:

    - ``init`` - create the task row and return its id.
    - ``execute`` - perform the work (raise ``TaskSkipped`` for a legitimate skip,
      or any ``Exception`` to signal failure).
    - ``mark`` - persist a terminal status/reason/timing for the task row (no commit).

    ``run()`` (concrete, shared by all tasks) owns the DB-session and lock lifecycle. In
    particular it decides which session ``mark`` runs on: the ambient execute session on
    success, or a brand-new session on failure/skip (a rolled-back async session cannot
    persist the row). Because of that, a Task implements ``mark`` exactly once - never a
    "fresh" variant.
    """

    #: Record id used as the resource-lock key (may be a real row id or a synthetic key).
    resource_id: UUID
    #: The type of record being locked (e.g. DATA_SOURCE, PROJECT_DATA).
    resource_type: RecordType

    @abstractmethod
    async def init(self, session: AsyncSession) -> UUID:
        """Create the task row and return its primary key."""

    @abstractmethod
    async def execute(self, session: AsyncSession, task_id: UUID) -> None:
        """
        Perform the task's work.

        Raise ``app.exceptions.TaskSkipped`` for a legitimate (non-error) skip, or any
        other ``Exception`` to mark the task failed.
        """

    @abstractmethod
    async def mark(
        self,
        session: AsyncSession,
        task_id: UUID,
        status: ProcessingStatus,
        reason: Optional[str],
        end_time: datetime,
        duration: int,
    ) -> None:
        """Persist the terminal status/reason/timing for the task row (caller commits)."""

    # -------------------------------------------------------------------------
    # Orchestration (concrete - shared by every Task)
    # -------------------------------------------------------------------------

    async def run(self) -> None:
        """
        Orchestrate this task end-to-end:

        1. init - create the task row in its own session (committed independently).
        2. lock - acquire the resource lock (skip if already held).
        3. exec - run the work in an ambient session, then persist the terminal status
           (SUCCESS on the same session; FAILED/SKIPPED via a fresh session).
        4. unlock.

        Session commit/rollback is delegated to ``ambient_session``: a clean block commits,
        an exception rolls back + re-raises (which we catch to record FAILED/SKIPPED).
        """
        lock_svc = RecordLockService()
        start = datetime.now(timezone.utc)

        def _dur() -> int:
            return int((datetime.now(timezone.utc) - start).total_seconds())

        # 1. Initialize the task row (own session, committed on clean exit)
        task_id: UUID | None = None
        try:
            async with ambient_session() as session:
                task_id = await self.init(session)
        except Exception as e:
            logger.error(f"[Task.run] Failed to init task: {e}", exc_info=True)
            return

        # 2. Acquire the resource lock (skip if already held - a sibling task owns it)
        if not await lock_svc.lock(self.resource_id, self.resource_type):
            await self._mark_fresh(task_id, ProcessingStatus.SKIPPED, "skipped: resource already locked", _dur())
            return

        # 3. Execute + persist terminal status
        try:
            try:
                async with ambient_session() as session:
                    await self.execute(session, task_id)
                    await self.mark(session, task_id, ProcessingStatus.SUCCESS, None, datetime.now(timezone.utc), _dur())
            except TaskSkipped as s:
                logger.info(f"[Task.run] Task {task_id} skipped: {s.reason}")
                await self._mark_fresh(task_id, ProcessingStatus.SKIPPED, s.reason, _dur())
            except Exception as e:
                logger.error(f"[Task.run] Task {task_id} failed: {e}", exc_info=True)
                await self._mark_fresh(task_id, ProcessingStatus.FAILED, str(e), _dur())
        # 4. Release the resource lock
        finally:
            await lock_svc.unlock(self.resource_id, self.resource_type)

    async def _mark_fresh(
        self,
        task_id: UUID,
        status: ProcessingStatus,
        reason: Optional[str],
        duration: int,
    ) -> None:
        """
        Persist a terminal status in a brand-new session.

        Used after a rollback (failure/skip) or when the lock can't be acquired - a
        rolled-back async session can't be reused to write the row. ``ambient_session``
        commits on clean exit.
        """
        async with ambient_session() as session:
            await self.mark(session, task_id, status, reason, datetime.now(timezone.utc), duration)
