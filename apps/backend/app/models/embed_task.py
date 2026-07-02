from __future__ import annotations
from .base import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey, text, Index, Enum as SQLEnum, DateTime
from uuid import UUID
from typing import TYPE_CHECKING
from datetime import datetime

from app.pydantic.status import ProcessingStatus

# avoid warning
if TYPE_CHECKING:
    from .data_source import DataSource
    from .job import Job

class EmbedTask(Base):
    __tablename__: str = "embed_task"

    # ensure data_source is leading column in index, to mitigate blocking of EmbedTask
    __table_args__: tuple[Index, ...] = (
        Index("ix_embed_task_data_source_status", "data_source_id", "processing_status"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, index=True, server_default=text("gen_random_uuid()")
    )
    processing_status: Mapped[ProcessingStatus] = mapped_column(SQLEnum(ProcessingStatus), nullable=False)
    reason: Mapped[str | None] = mapped_column(nullable=True, comment="Detailed reason or error message")
    data_source_id: Mapped[UUID] = mapped_column(ForeignKey("data_source.id"))
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("job.id"), nullable=True, index=True)

    job: Mapped["Job"] = relationship(back_populates="embed_tasks")


    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Start time of EmbedTask processing")
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True, comment="End time of EmbedTask processing")
    total_duration: Mapped[int] = mapped_column(nullable=True, comment="Total duration of EmbedTask in seconds")

    data_source: Mapped["DataSource"] = relationship(back_populates="ingestion_jobs")
