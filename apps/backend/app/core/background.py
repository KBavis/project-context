from __future__ import annotations
import logging
from uuid import UUID
from typing import Optional, Callable, Any
from contextvars import ContextVar
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from app.core import get_async_db_session_context
from app.services.record_lock import RecordLockService
from app.models.record_lock import RecordType
from app.pydantic.status import ProcessingStatus
from app.exceptions import TaskSkipped

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
    resource_id: UUID,
    resource_type: RecordType,
    init_task: Callable[[], Any],
    execute: Callable[[UUID], Any],
    mark_task: Callable[[AsyncSession, UUID, ProcessingStatus, Optional[str], Optional[datetime], Optional[int]], Any],
    mark_task_fresh: Callable[[UUID, ProcessingStatus, Optional[str], Optional[datetime], Optional[int]], Any],
):
    """
    Wraps task execution in an ambient DB session and a resource lock.
    """
    lock_svc = RecordLockService()
    start = datetime.now(timezone.utc)

    def _dur(start_t: datetime) -> int:
        return int((datetime.now(timezone.utc) - start_t).total_seconds())

    # 1. initalize the Task in the Database
    task_id = None
    try:
        async with get_async_db_session_context() as session:
            token = _current_session.set(session)
            try:
                task_id = await init_task()
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.error(f"[run_task] Failed to init task: {e}", exc_info=True)
                return
            finally:
                _current_session.reset(token)
    except Exception as e:
        logger.error(f"[run_task] Session error during init: {e}")
        return

    # 2. acquire the resource lock
    if not await lock_svc.lock(resource_id, resource_type):
        await mark_task_fresh(task_id, ProcessingStatus.SKIPPED, "skipped: resource already locked", datetime.now(timezone.utc), _dur(start))
        return
    
    # 3. execute task and update statuses
    try:
        async with get_async_db_session_context() as session:
            token = _current_session.set(session)
            try:
                await execute(task_id)
                await mark_task(session, task_id, ProcessingStatus.SUCCESS, None, datetime.now(timezone.utc), _dur(start))
                await session.commit()
            except TaskSkipped as s:
                logger.info(f"[run_task] Task {task_id} skipped: {s.reason}")
                await session.rollback()
                await mark_task_fresh(task_id, ProcessingStatus.SKIPPED, s.reason, datetime.now(timezone.utc), _dur(start))
            except Exception as e:
                await session.rollback()
                logger.error(f"[run_task] Task {task_id} failed: {e}", exc_info=True)
                await mark_task_fresh(task_id, ProcessingStatus.FAILED, str(e), datetime.now(timezone.utc), _dur(start))
            finally:
                _current_session.reset(token)
    # 4. unlock resource lock
    finally:
        await lock_svc.unlock(resource_id, resource_type)

