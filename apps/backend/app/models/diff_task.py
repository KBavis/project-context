from __future__ import annotations
from .base import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey, text, Enum as SQLEnum, DateTime, String
from uuid import UUID
from datetime import datetime

from app.pydantic.status import ProcessingStatus
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .job import Job

class DiffTask(Base):
    __tablename__: str = "diff_task"

    id: Mapped[UUID] = mapped_column(
        primary_key=True, index=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[UUID] = mapped_column(ForeignKey("project.id"), nullable=False, index=True)
    data_source_id: Mapped[UUID] = mapped_column(ForeignKey("data_source.id"), nullable=False, index=True)
    
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("job.id"), nullable=True, index=True)
    job: Mapped["Job"] = relationship(back_populates="diff_tasks")
    
    status: Mapped[ProcessingStatus] = mapped_column(SQLEnum(ProcessingStatus), nullable=False)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)

    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    total_duration: Mapped[int] = mapped_column(nullable=True)
