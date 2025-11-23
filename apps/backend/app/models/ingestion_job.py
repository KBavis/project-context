from .base import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey, text, Enum as SQLEnum
from uuid import UUID
from typing import TYPE_CHECKING
from enum import Enum


# avoid warning
if TYPE_CHECKING:
    from .data_source import DataSource


class ProcessingStatus(Enum):
    SUCCESS = "success"
    IN_PROGRESS = "in_progress"
    FAILED = "failed"

class IngestionJob(Base):
    __tablename__ = "ingestion_job"

    id: Mapped[UUID] = mapped_column(
        primary_key=True, index=True, server_default=text("gen_random_uuid()")
    )
    processing_status: Mapped[ProcessingStatus] = mapped_column(SQLEnum(ProcessingStatus), nullable=False)
    data_source_id: Mapped[UUID] = mapped_column(ForeignKey("data_source.id"))

    data_source: Mapped["DataSource"] = relationship(back_populates="ingestion_jobs")
