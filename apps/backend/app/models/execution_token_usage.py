from __future__ import annotations
from .base import Base 

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey, text

if TYPE_CHECKING:
    from .conversation import Conversation
    from .message import Message

class ExecutionTokenUsage(Base):
    __tablename__: str = "execution_token_usage"

    id: Mapped["UUID"] = mapped_column(primary_key=True, index=True, server_default=text("gen_random_uuid()"))

    conversation_id: Mapped["UUID"] = mapped_column(ForeignKey("conversation.id"), nullable=False)
    user_message_id: Mapped["UUID"] = mapped_column(ForeignKey("message.id"), nullable=False)
    model_message_id: Mapped["UUID"] = mapped_column(ForeignKey("message.id"), nullable=False)

    input_tokens: Mapped[int] = mapped_column(nullable=False, comment="Total input tokens for this execution")
    output_tokens: Mapped[int] = mapped_column(nullable=False, comment="Total output tokens for this execution")
    total_tokens: Mapped[int] = mapped_column(nullable=False, comment="Total tokens used in this execution")
    execution_time_seconds: Mapped[float | None] = mapped_column(nullable=True, comment="Total execution time in seconds")

    # Relationships
    conversation: Mapped["Conversation"] = relationship(back_populates="execution_token_usages")
    user_message: Mapped["Message"] = relationship(foreign_keys=[user_message_id])
    model_message: Mapped["Message"] = relationship(foreign_keys=[model_message_id])
