from .base import Base 

from typing import TYPE_CHECKING
from uuid import UUID
from enum import Enum

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey, text, String, Text, Enum as SQLEnum


if TYPE_CHECKING:
    from .conversation import Conversation

# enum for determing who sent a particular message
class Sender(Enum):
    USER = "user"
    MODEL = "model"


class Message(Base):
    __tablename__ = "message"

    id: Mapped[UUID] = mapped_column(primary_key=True, index=True, server_default=text("gen_random_uuid()"))

    sender: Mapped[Sender] = mapped_column(
        SQLEnum(Sender), 
        nullable=False,
        comment="The origin of who sent this particular message, which is either the user or LLM"
    ) 

    sequence_number: Mapped[int] = mapped_column(
        nullable=False,
        comment="Order in which this particular message came in the associated conversation"
    )

    token_count: Mapped[int] = mapped_column(
        nullable=False,
        comment="Total number of tokens used in this message"
    )

    model: Mapped[str] = mapped_column(
        String(50),
        nullable=True,
        comment="The LLM model utilzied when generating this particular message, will be null if user sent this message"
    )

    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=True,
        comment="The LLM provider utilized when generating this particular message, will be null if user sent this message"
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="The raw message content that was either sent or generated"
    )

    content_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="text/markdown",
        comment="The desired format to use when storing content"
    )

    # many to one relationship with Conversation
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversation.id"))
    conversation: Mapped["Conversation"] = relationship(back_populates="messages")