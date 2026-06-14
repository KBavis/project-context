from __future__ import annotations
from .base import Base
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey, text, Enum as SQLEnum, DateTime, String
from uuid import UUID
from datetime import datetime

from app.pydantic.status import ProcessingStatus

class DiffSyncJob(Base):
    __tablename__: str = "diff_sync_job"

    id: Mapped["UUID"] = mapped_column(
        primary_key=True, index=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped["UUID"] = mapped_column(ForeignKey("project.id"), nullable=False, index=True)
    data_source_id: Mapped["UUID"] = mapped_column(ForeignKey("data_source.id"), nullable=False, index=True)
    
    status: Mapped["ProcessingStatus"] = mapped_column(SQLEnum(ProcessingStatus), nullable=False)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)

    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    total_duration: Mapped[int] = mapped_column(nullable=True)
