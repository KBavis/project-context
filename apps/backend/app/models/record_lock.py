from .base import Base 

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import text, UniqueConstraint, Enum as SQLEnum

from uuid import UUID
from enum import Enum

class RecordType(Enum):
    CONVERSATION = "Conversation"
    DATA_SOURCE = "DataSource"

class RecordLock(Base):

    __tablename__ = "record_lock"

    record_id: Mapped[UUID] = mapped_column(
        primary_key=True,
        nullable=False,
        comment="Primary key of record that is being locked"
    )

    record_type: Mapped[RecordType] = mapped_column(
        SQLEnum(RecordType),
        primary_key=True,
        nullable=False,
        comment="Relevant type of the locked record "
    )

    is_locked: Mapped[str] = mapped_column(
        nullable=False,
        default="N",
        comment="Y or N indicator for determing if resource is locked"
    )
