from __future__ import annotations
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from app.models import ExecutionTokenUsage

logger = logging.getLogger(__name__)

class ExecutionTokenUsageService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_usage_record(
        self,
        conversation_id: UUID,
        user_message_id: UUID,
        model_message_id: UUID,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int
    ) -> ExecutionTokenUsage:
        """
        Record the token usage metrics for a specific conversation turn.
        """
        logger.info(f"Creating Execution Token Usage for Conversation={conversation_id}")
        execution = ExecutionTokenUsage(
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            model_message_id=model_message_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens
        )
        self.db.add(execution)
        await self.db.flush()
        return execution
