from __future__ import annotations
from .base import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey, text, Enum as SQLEnum, DateTime, Index
from uuid import UUID
from datetime import datetime
from typing import List

from app.pydantic.status import ProcessingStatus
from .embed_task import EmbedTask
from .diff_task import DiffTask

class Job(Base):
    __tablename__: str = "job"

    __table_args__ = (
        Index("ix_job_project_data_source", "project_id", "data_source_id"),
    )

    id: Mapped["UUID"] = mapped_column(
        primary_key=True, index=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped["UUID"] = mapped_column(ForeignKey("project.id"), nullable=False, index=True)
    data_source_id: Mapped[UUID] = mapped_column(ForeignKey("data_source.id"), nullable=False, index=True)
    
    status: Mapped["ProcessingStatus"] = mapped_column(SQLEnum(ProcessingStatus), nullable=False)

    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    total_duration: Mapped[int] = mapped_column(nullable=True)

    embed_tasks: Mapped[List["EmbedTask"]] = relationship(back_populates="job")
    diff_tasks: Mapped[List["DiffTask"]] = relationship(back_populates="job")
