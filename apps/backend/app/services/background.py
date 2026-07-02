from __future__ import annotations
import logging
from uuid import UUID
from typing import Optional, Callable, Any
from contextvars import ContextVar

from sqlalchemy.ext.asyncio import AsyncSession
from app.core import get_async_db_session_context
from app.services.record_lock import RecordLockService
from app.models.record_lock import RecordType
from app.pydantic.status import ProcessingStatus

logger = logging.getLogger(__name__)

_current_session: ContextVar[AsyncSession | None] = ContextVar("current_session", default=None)

def get_current_session() -> AsyncSession:
    """
    Services call this in background scope instead of receiving a session param.
    """
    s = _current_session.get()
    if s is None:
        raise RuntimeError("no ambient session - must run inside run_task")
    return s

async def run_task(
    task_id: UUID,
    resource_id: UUID,
    resource_type: RecordType,
    execute: Callable[[], Any],
    mark_task: Callable[[AsyncSession, UUID, ProcessingStatus, Optional[str]], Any],
    mark_task_fresh: Callable[[UUID, ProcessingStatus, Optional[str]], Any],
):
    """
    Wraps task execution in an ambient DB session and a resource lock.
    """
    lock_svc = RecordLockService()
    # 1. acquire the resource lock
    if not await lock_svc.lock(resource_id, resource_type):
        await mark_task_fresh(task_id, ProcessingStatus.SKIPPED, "skipped: resource already locked")
        return
    
    try:
        async with get_async_db_session_context() as session:
            token = _current_session.set(session)
            try:
                await mark_task(session, task_id, ProcessingStatus.IN_PROGRESS, None)
                await execute()
                await mark_task(session, task_id, ProcessingStatus.SUCCESS, None)
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.error(f"[run_task] Task {task_id} failed: {e}", exc_info=True)
                await mark_task_fresh(task_id, ProcessingStatus.FAILED, str(e))
            finally:
                _current_session.reset(token)
    finally:
        await lock_svc.unlock(resource_id, resource_type)
