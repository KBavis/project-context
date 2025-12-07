from .base import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey, text, Index, Enum as SQLEnum
from uuid import UUID
from typing import TYPE_CHECKING
from enum import Enum
from datetime import datetime

# avoid warning
if TYPE_CHECKING:
    from .data_source import DataSource


class ProcessingStatus(Enum):
    SUCCESS = "success"
    IN_PROGRESS = "in_progress"
    FAILED = "failed"

class IngestionJob(Base):
    __tablename__ = "ingestion_job"

    # ensure data_source is leading column in index, to mitigate blocking of IngestionJobs
    __table_args__ = (
        Index("ix_ingestion_job_data_source_status", "data_source_id", "processing_status"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, index=True, server_default=text("gen_random_uuid()")
    )
    processing_status: Mapped[ProcessingStatus] = mapped_column(SQLEnum(ProcessingStatus), nullable=False)
    data_source_id: Mapped[UUID] = mapped_column(ForeignKey("data_source.id"))


    start_time: Mapped[datetime] = mapped_column(nullable=False, comment="Start time of IngestionJob processing")
    end_time: Mapped[datetime] = mapped_column(nullable=True, comment="End time of IngestionJob processing")
    total_duration: Mapped[int] = mapped_column(nullable=True, comment="Total duration of IngestionJob in seconds")

    data_source: Mapped["DataSource"] = relationship(back_populates="ingestion_jobs")
