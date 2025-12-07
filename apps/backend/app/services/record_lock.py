from app.models import RecordLock, RecordType
from app.core import AsyncSessionsLocal 

from uuid import UUID
import logging

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)

class RecordLockService:

    """
    TODO: Figure out a way to abstract the async vs sync database logic from service 
    so we aren't forced to use async DB connection to use this logic
    """

    def __init__(self):
        pass

    
    async def lock(self, record_id: UUID, record_type: RecordType):
        """
        Functionality to lock a particular record from future updates 

        Args:
            record_id (UUID): ID of record that is being locked
            record_type (RecordType): the type of record being locked
        """

        async with AsyncSessionsLocal() as session:

            # Step 1. Ensure record already exists 
            insert_stmt = insert(RecordLock).values(
                record_id=record_id,
                record_type=record_type,
                is_locked="N"
            )

            # NOTE: If the record already exists, DO NOTHING 
            on_conflict_stmt = insert_stmt.on_conflict_do_nothing(
                index_elements=[RecordLock.record_id, RecordLock.record_type],
            )
            await session.execute(on_conflict_stmt)
            await session.flush() 

            # Step 2. Acquire the lock 
            update_stmt = (
                update(RecordLock)
                .where(
                    RecordLock.record_id == record_id,
                    RecordLock.record_type == record_type,
                    RecordLock.is_locked == 'N' # ONLY update if currently UNLOCKED
                )
                .values(is_locked = "Y")
            )
            res = await session.execute(update_stmt)
            await session.flush()
            await session.commit()

            # Step 3. Ensure exactly one row updated
            if res.rowcount == 1:
                logger.debug(f"Successfully locked RecordLock with recordId={record_id} and recordType={record_type}")
                return True 
            else:
                logger.error(f"Lock failed for recordType={record_type} and recordId={record_id}: Already locked.")
                return False 



    async def unlock(self, record_id: UUID, record_type: RecordType):
        """
        Functionality to lock a particular record from future updates 

        Args:
            record_id (UUID): ID of record that is being locked
            record_type (RecordType): the type of record being locked
        """
        # create seperate session to ensure DB changes are persisted  
        async with AsyncSessionsLocal() as session: 

            # unlock the record 
            stmt = (
                update(RecordLock)
                .where(
                    RecordLock.record_id == record_id,
                    RecordLock.record_type == record_type
                )
                .values(is_locked = "N")
            )

            result = await session.execute(stmt)

            # ensure we updated record 
            if result.rowcount == 0:
                logger.error(f"Failed to find RecordLock by recordId={record_id} and recordType={record_type}")
                raise Exception(f"No RecordLock found by recordId={record_id} and recordType={record_type}")

            await session.flush()
            await session.commit()
            logger.debug(f"Successfully unlocked RecordLock with recordId={record_id} and recordType={record_type}")



